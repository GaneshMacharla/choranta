"""Monthly plans: admin catalogue, client subscriptions, call usage, and the Razorpay webhook."""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_any_user, get_db, require_admin, require_operator
from app.models.client import Client
from app.models.subscription import CallUsage, NumberPricing, Plan
from app.models.user import User
from app.services import billing, exotel_numbers, phone_numbers, razorpay_gateway, subscriptions
from app.services.pricing import credits_per_minute

logger = logging.getLogger("choranta.api.plans")

router = APIRouter(tags=["Plans"])


class PlanRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    monthly_price_inr: float = Field(..., gt=0, description="Monthly fee, excluding GST")
    monthly_credits: float = Field(..., gt=0, description="Credits granted each period (1 credit = Rs 1); they expire at period end")
    max_concurrent_calls: Optional[int] = Field(None, ge=1, description="Empty for no limit")
    is_active: bool = True
    sort_order: int = 0


class AssignPlanRequest(BaseModel):
    plan_id: str
    amount_received_inr: Optional[float] = Field(None, gt=0, description="GST included; defaults to the plan price + GST")
    reference: Optional[str] = Field(None, max_length=255, description="UTR / UPI reference")


class SubscriptionSettingsRequest(BaseModel):
    cancel_at_period_end: bool


def _plan_or_404(db: Session, plan_id: str) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return plan


def _client_or_404(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found.")
    return client


def usage_out(db: Session, client_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    rows = (
        db.query(CallUsage).filter(CallUsage.client_id == client_id)
        .order_by(CallUsage.created_at.desc()).limit(limit).all()
    )
    return [
        {"call_id": u.call_id, "plan_id": u.plan_id, "billed_minutes": u.billed_minutes,
         "included_minutes": u.included_minutes, "overage_minutes": u.overage_minutes,
         "overage_charge_inr": u.overage_charge_inr, "plan_credits": u.plan_credits or 0.0,
         "wallet_credits": u.wallet_credits or 0.0, "created_at": u.created_at}
        for u in rows
    ]


# ---------------------------------------------------------------- plan catalogue

@router.get("/plans")
def list_plans(include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_any_user)):
    query = db.query(Plan)
    if not (include_archived and user.role in ("ADMIN", "OPERATOR")):
        query = query.filter(Plan.is_active.is_(True))
    rate = credits_per_minute(db)
    return [subscriptions.plan_out(p, rate) for p in query.order_by(Plan.sort_order, Plan.monthly_price_inr).all()]


def _apply_plan(plan: Plan, req: PlanRequest, rate: float) -> None:
    subscriptions.validate_plan_fields(req.name, req.monthly_price_inr, req.monthly_credits, req.max_concurrent_calls)
    plan.name = req.name.strip()
    plan.description = (req.description or "").strip() or None
    plan.monthly_price_inr = req.monthly_price_inr
    subscriptions.apply_credit_fields(plan, req.monthly_credits, rate)
    plan.max_concurrent_calls = req.max_concurrent_calls
    plan.is_active = req.is_active
    plan.sort_order = req.sort_order


@router.post("/plans", status_code=201)
def create_plan(req: PlanRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rate = credits_per_minute(db)
    plan = Plan()
    _apply_plan(plan, req, rate)
    db.add(plan)
    db.commit()
    return subscriptions.plan_out(plan, rate)


@router.put("/plans/{plan_id}")
def update_plan(plan_id: str, req: PlanRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Changes apply to current subscribers immediately (credits, call limit)."""
    rate = credits_per_minute(db)
    plan = _plan_or_404(db, plan_id)
    _apply_plan(plan, req, rate)
    db.commit()
    return subscriptions.plan_out(plan, rate)


# ---------------------------------------------------------------- client subscriptions

@router.get("/clients/{client_id}/subscription")
def get_client_subscription(client_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    _client_or_404(db, client_id)
    out = subscriptions.subscription_out(db, client_id)
    db.commit()  # persist a status change worked out on read
    return {"subscription": out}


@router.post("/clients/{client_id}/subscription")
def assign_plan(client_id: str, req: AssignPlanRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Records an offline plan payment (bank transfer / UPI): applies the period and issues the GST invoice."""
    _client_or_404(db, client_id)
    plan = _plan_or_404(db, req.plan_id)
    return billing.pay_for_plan(db, client_id, plan, req.reference, user.id, amount_received=req.amount_received_inr)


@router.put("/clients/{client_id}/subscription")
def update_subscription(client_id: str, req: SubscriptionSettingsRequest, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    sub = subscriptions.get_subscription(db, client_id)
    if not sub:
        raise HTTPException(status_code=404, detail="This client has no plan.")
    sub.cancel_at_period_end = req.cancel_at_period_end
    db.commit()
    return {"subscription": subscriptions.subscription_out(db, client_id)}


@router.get("/clients/{client_id}/usage")
def get_client_usage(client_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    _client_or_404(db, client_id)
    return usage_out(db, client_id)


# ---------------------------------------------------------------- Razorpay webhook

@router.post("/billing/razorpay/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """Fulfils paid orders when the browser didn't return to verify. Authenticated by signature."""
    body = await request.body()
    if not razorpay_gateway.verify_webhook_signature(body, request.headers.get("X-Razorpay-Signature", "")):
        raise HTTPException(status_code=400, detail="Invalid signature.")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload.")
    order = razorpay_gateway.handle_webhook(db, event)
    return {"ok": True, "order_id": order.id if order else None}


# ---------------------------------------------------------------- phone numbers sold by Choranta

class NumberPriceRequest(BaseModel):
    monthly_rent_inr: float = Field(..., gt=0, description="Per month, excluding GST")
    is_available: bool = True


class BuyNumberRequest(BaseModel):
    phone_number: str = Field(..., min_length=6, max_length=20)
    number_type: str = Field(..., pattern="^(Landline|Mobile|TollFree)$")


@router.get("/number-pricing")
def list_number_pricing(db: Session = Depends(get_db), user: User = Depends(get_any_user)):
    return [phone_numbers.pricing_out(p) for p in phone_numbers.get_pricing(db)]


@router.put("/number-pricing/{number_type}")
def update_number_pricing(number_type: str, req: NumberPriceRequest, db: Session = Depends(get_db),
                          user: User = Depends(require_admin)):
    """New prices apply to numbers bought from now on; existing rentals keep the rent they were bought at."""
    price = db.get(NumberPricing, number_type)
    if not price:
        raise HTTPException(status_code=404, detail="Unknown number type.")
    price.monthly_rent_inr = req.monthly_rent_inr
    price.is_available = req.is_available
    db.commit()
    return phone_numbers.pricing_out(price)


@router.get("/clients/{client_id}/numbers/available")
def admin_search_numbers(client_id: str, number_type: str = "Landline", region: Optional[str] = None,
                         db: Session = Depends(get_db), user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    try:
        return phone_numbers.search(db, number_type, region)
    except exotel_numbers.ExotelNumberError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/clients/{client_id}/numbers/buy", status_code=201)
def admin_buy_number(client_id: str, req: BuyNumberRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Buys a number for the client; the first month's rent is still debited from their wallet."""
    _client_or_404(db, client_id)
    pn = phone_numbers.buy_number(db, client_id, req.phone_number, req.number_type, user.id)
    return {"id": pn.id, "phone_number": pn.phone_number, **phone_numbers.rental_out(phone_numbers.rental_for(db, pn.id))}
