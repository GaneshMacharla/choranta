"""Client portal: every endpoint is scoped to the signed-in client account's own client."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user
from app.api.routes.billing import invoice_out, invoice_pdf_response, wallet_out
from app.api.routes.plans import usage_out
from app.api.routes.telephony import _format_call_response, _recording_path, get_call_detail
from app.core.config import settings
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.billing import Invoice, WalletTransaction
from app.models.call import Call
from app.models.client import Client
from app.models.phone_number import PhoneNumber
from app.models.property import Property
from app.models.subscription import PaymentOrder
from app.models.user import User
from app.services import exotel_numbers, phone_numbers, razorpay_gateway, subscriptions
from app.services.pricing import get_pricing

router = APIRouter(prefix="/portal", tags=["Client Portal"])

ClientAccount = Tuple[User, str]


def _own_call(db: Session, client_id: str, call_id: str) -> Call:
    call = db.get(Call, call_id)
    if not call or call.client_id != client_id:
        raise HTTPException(status_code=404, detail="Call not found.")
    return call


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _past_due_numbers(db: Session, client_id: str) -> List[Dict[str, Any]]:
    from app.models.subscription import NumberRental
    rentals = db.query(NumberRental).filter(NumberRental.client_id == client_id, NumberRental.status == "PAST_DUE").all()
    out = []
    for r in rentals:
        pn = db.get(PhoneNumber, r.phone_number_id)
        details = phone_numbers.rental_out(r)
        out.append({"phone_number": phone_numbers.display_number(pn) if pn else "", "monthly_rent_inr": r.monthly_rent_inr,
                    "grace_ends_at": details["grace_ends_at"]})
    return out


@router.get("/summary")
def summary(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    user, client_id = account
    client = db.get(Client, client_id)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)

    calls = db.query(Call).filter(Call.client_id == client_id, Call.created_at >= min(month_start, since).replace(tzinfo=None)).all()
    debits = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.client_id == client_id, WalletTransaction.type == "DEBIT",
                WalletTransaction.created_at >= min(month_start, since).replace(tzinfo=None))
        .all()
    )

    daily: Dict[str, Dict[str, float]] = defaultdict(lambda: {"calls": 0, "minutes": 0.0, "spend_inr": 0.0})
    month = {"calls": 0, "minutes": 0.0, "spend_inr": 0.0}
    for c in calls:
        created = _aware(c.created_at)
        minutes = (c.duration_seconds or 0) / 60.0
        if created >= since:
            day = daily[created.date().isoformat()]
            day["calls"] += 1
            day["minutes"] += minutes
        if created >= month_start:
            month["calls"] += 1
            month["minutes"] += minutes
    for t in debits:
        created = _aware(t.created_at)
        if created >= since:
            daily[created.date().isoformat()]["spend_inr"] += -t.amount_inr
        if created >= month_start:
            month["spend_inr"] += -t.amount_inr

    series = []
    for offset in range(30):
        day = (since + timedelta(days=offset)).date().isoformat()
        values = daily.get(day, {"calls": 0, "minutes": 0.0, "spend_inr": 0.0})
        series.append({"date": day, "calls": values["calls"], "minutes": round(values["minutes"], 1),
                       "spend_inr": round(values["spend_inr"], 2)})

    wallet = wallet_out(db, client_id, limit=0)
    return {
        "client_name": client.name if client else "",
        "user_name": user.name,
        "wallet": {k: wallet[k] for k in ("balance_inr", "low_balance_threshold_inr", "low_balance", "calls_blocked",
                                          "calls_blocked_reason")},
        "subscription": wallet["subscription"],
        "numbers_past_due": _past_due_numbers(db, client_id),
        "month": {"calls": month["calls"], "minutes": round(month["minutes"], 1), "spend_inr": round(month["spend_inr"], 2)},
        "daily": series,
    }


@router.get("/calls")
def list_calls(
    limit: int = Query(50, ge=1, le=200),
    account: ClientAccount = Depends(require_client_user),
    db: Session = Depends(get_db),
):
    user, client_id = account
    calls = db.query(Call).filter(Call.client_id == client_id).order_by(Call.created_at.desc()).limit(limit).all()
    pricing = get_pricing(db)
    return [_format_call_response(c, db, user, pricing) for c in calls]


@router.get("/calls/{call_id}")
def call_detail(call_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    user, client_id = account
    _own_call(db, client_id, call_id)
    detail = get_call_detail(call_id=call_id, db=db, current_user=user)
    # Clients see the conversation and their charge, not internal runtime events or token usage
    return detail.model_copy(update={"events": [], "usage": {}})


@router.get("/calls/{call_id}/recording")
def call_recording(call_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    call = _own_call(db, client_id, call_id)
    path = _recording_path(call)
    if not path:
        raise HTTPException(status_code=404, detail="No recording is available for this call.")
    return FileResponse(path, media_type="audio/wav", filename=f"{call_id}.wav")


@router.get("/wallet")
def wallet(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    return wallet_out(db, client_id, limit=200)


@router.get("/invoices")
def invoices(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    _, client_id = account
    rows = db.query(Invoice).filter(Invoice.client_id == client_id).order_by(Invoice.created_at.desc()).all()
    return [invoice_out(i) for i in rows]


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    invoice = db.get(Invoice, invoice_id)
    if not invoice or invoice.client_id != client_id:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice_pdf_response(invoice)


@router.get("/properties")
def properties(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    props = (
        db.query(Property).filter(Property.client_id == client_id, Property.status != "UNAVAILABLE")
        .order_by(Property.project_name).limit(500).all()
    )
    return {
        "count": len(props),
        "last_synced_at": max((p.last_synced_at for p in props if p.last_synced_at), default=None),
        "properties": [
            {"id": p.id, "project_name": p.project_name, "location": p.location, "bhk": p.bhk,
             "price_display": p.price_display, "property_type": p.property_type, "status": p.status}
            for p in props
        ],
    }


@router.get("/payment-instructions")
def payment_instructions(account: ClientAccount = Depends(require_client_user)):
    return {
        "upi_id": settings.PAYMENT_UPI_ID or None,
        "bank_details": settings.PAYMENT_BANK_DETAILS or None,
        "gst_rate_percent": settings.GST_RATE_PERCENT,
        "note": "After paying, share the UTR / UPI reference with your Choranta contact. Your wallet is credited "
                "with the amount excluding GST, and a GST invoice is issued.",
    }


# ---------------------------------------------------------------- plan & online payments

class OrderRequest(BaseModel):
    purpose: str = Field(..., pattern="^(SUBSCRIPTION|WALLET_TOPUP)$")
    plan_id: str | None = None
    amount_inr: float | None = Field(None, gt=0, description="Wallet top-up, GST included")


class VerifyRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_signature: str


@router.get("/subscription")
def subscription(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    out = subscriptions.subscription_out(db, client_id)
    db.commit()
    return {
        "subscription": out,
        "online_payments": razorpay_gateway.is_configured(),
        "grace_days": settings.SUBSCRIPTION_GRACE_DAYS,
        "min_topup_inr": settings.MIN_WALLET_TOPUP_INR,
        "gst_rate_percent": settings.GST_RATE_PERCENT,
    }


@router.get("/usage")
def usage(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    return usage_out(db, client_id)


@router.post("/payments/orders", status_code=201)
def create_payment_order(req: OrderRequest, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    user, client_id = account
    try:
        order = razorpay_gateway.create_order(db, client_id, req.purpose, user.id, plan_id=req.plan_id, amount_inr=req.amount_inr)
    except razorpay_gateway.RazorpayError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc))
    order["prefill"] = {"name": user.name, "email": user.email}
    return order


@router.post("/payments/orders/{order_id}/verify")
def verify_payment(order_id: str, req: VerifyRequest, account: ClientAccount = Depends(require_client_user),
                   db: Session = Depends(get_db)):
    _, client_id = account
    order = db.get(PaymentOrder, order_id)
    if not order or order.client_id != client_id:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if not razorpay_gateway.verify_payment_signature(order.razorpay_order_id, req.razorpay_payment_id, req.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment could not be verified.")
    order = razorpay_gateway.fulfil_order(db, order, req.razorpay_payment_id)
    return {"status": order.status, "invoice_id": order.invoice_id, "subscription": subscriptions.subscription_out(db, client_id)}


# ---------------------------------------------------------------- phone numbers

class BuyNumberRequest(BaseModel):
    phone_number: str = Field(..., min_length=6, max_length=20)
    number_type: str = Field(..., pattern="^(Landline|Mobile|TollFree)$")


class NumberUpdateRequest(BaseModel):
    agent_id: str | None = None


def _own_number(db: Session, client_id: str, number_id: str) -> PhoneNumber:
    pn = db.get(PhoneNumber, number_id)
    if not pn or pn.client_id != client_id:
        raise HTTPException(status_code=404, detail="Phone number not found.")
    return pn


def _number_out(db: Session, pn: PhoneNumber) -> Dict[str, Any]:
    agent = db.get(Agent, pn.agent_id) if pn.agent_id else None
    return {
        "id": pn.id,
        "phone_number": phone_numbers.display_number(pn),
        "number_type": (pn.metadata_ or {}).get("number_type"),
        "status": pn.status,
        "agent_id": pn.agent_id,
        "agent_name": agent.name if agent else None,
        "created_at": pn.created_at,
        **phone_numbers.rental_out(phone_numbers.rental_for(db, pn.id)),
    }


@router.get("/numbers")
def my_numbers(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    rows = db.query(PhoneNumber).filter(PhoneNumber.client_id == client_id).order_by(PhoneNumber.created_at.desc()).all()
    return {
        "numbers": [_number_out(db, pn) for pn in rows],
        "pricing": [phone_numbers.pricing_out(p) for p in phone_numbers.get_pricing(db) if p.is_available],
        "grace_days": settings.NUMBER_GRACE_DAYS,
    }


@router.get("/numbers/available")
def available_numbers(number_type: str = "Landline", region: str | None = None,
                      account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    try:
        return phone_numbers.search(db, number_type, region)
    except exotel_numbers.ExotelNumberError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/numbers", status_code=201)
def buy_number(req: BuyNumberRequest, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    user, client_id = account
    pn = phone_numbers.buy_number(db, client_id, req.phone_number, req.number_type, user.id)
    return _number_out(db, pn)


@router.patch("/numbers/{number_id}")
def update_number(number_id: str, req: NumberUpdateRequest, account: ClientAccount = Depends(require_client_user),
                  db: Session = Depends(get_db)):
    """Chooses which of the client's AI employees answers this number."""
    _, client_id = account
    pn = _own_number(db, client_id, number_id)
    if pn.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="This number isn't active.")
    return _number_out(db, phone_numbers.assign_agent(db, pn, req.agent_id))


@router.delete("/numbers/{number_id}")
def release_number(number_id: str, now: bool = False, account: ClientAccount = Depends(require_client_user),
                   db: Session = Depends(get_db)):
    """Stops renting a number: at the end of the paid month, or right away with ?now=true (no refund)."""
    _, client_id = account
    pn = _own_number(db, client_id, number_id)
    rental = phone_numbers.rental_for(db, pn.id)
    if not rental or rental.status == "RELEASED":
        raise HTTPException(status_code=400, detail="Only numbers rented from Choranta can be released here.")
    if now:
        if not phone_numbers.release(db, rental):
            raise HTTPException(status_code=502, detail="Exotel couldn't release the number. Please try again.")
    else:
        rental.cancel_at_period_end = True
        db.commit()
    return _number_out(db, pn)


@router.post("/numbers/{number_id}/keep")
def keep_number(number_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    """Undoes a release that was scheduled for the end of the month."""
    _, client_id = account
    pn = _own_number(db, client_id, number_id)
    rental = phone_numbers.rental_for(db, pn.id)
    if rental and rental.status != "RELEASED":
        rental.cancel_at_period_end = False
        db.commit()
    return _number_out(db, pn)


@router.get("/agents")
def my_agents(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    """The client's AI employees that can answer a number (those with a published version)."""
    _, client_id = account
    agents = db.query(Agent).filter(Agent.client_id == client_id).order_by(Agent.name).all()
    published = {
        a for (a,) in db.query(AgentVersion.agent_id)
        .filter(AgentVersion.agent_id.in_([a.id for a in agents]), AgentVersion.status == "PUBLISHED").distinct().all()
    } if agents else set()
    return [{"id": a.id, "name": a.name, "role": a.role, "published": a.id in published} for a in agents]
