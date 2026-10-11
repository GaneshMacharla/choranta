from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.models.user import User
from app.services.call_costing import estimate_call_cost
from app.services.pricing import PricingSnapshot, get_pricing, update_pricing

router = APIRouter(prefix="/pricing", tags=["Pricing"])

PREVIEW_WINDOW_DAYS = 30


class UpdatePricingRequest(BaseModel):
    profit_percent: float = Field(..., description="Profit margin added on top of cost, in percent")
    infra_cost_per_minute_inr: float = Field(..., description="Infrastructure overhead per conversation minute (INR)")


def _preview(db: Session, pricing: PricingSnapshot) -> Dict[str, Any]:
    """Average cost and resulting client charge per minute over recent completed calls."""
    since = datetime.now(timezone.utc) - timedelta(days=PREVIEW_WINDOW_DAYS)
    calls = (
        db.query(Call)
        .filter(Call.status == "COMPLETED", Call.duration_seconds > 0, Call.created_at >= since)
        .all()
    )
    total_seconds = 0.0
    total_cost = 0.0
    total_charge = 0.0
    for call in calls:
        usage: Dict[str, Any] = {}
        if call.runtime_session_id:
            session_obj = db.get(RuntimeSession, call.runtime_session_id)
            if session_obj and isinstance(session_obj.usage_json, dict):
                usage = session_obj.usage_json
        cost = estimate_call_cost(call.duration_seconds, usage, pricing)
        total_seconds += call.duration_seconds
        total_cost += cost["total"]
        total_charge += cost["charge_total"]

    minutes = total_seconds / 60.0
    return {
        "window_days": PREVIEW_WINDOW_DAYS,
        "calls": len(calls),
        "minutes": round(minutes, 2),
        "avg_cost_per_minute": round(total_cost / minutes, 4) if minutes else None,
        "avg_charge_per_minute": round(total_charge / minutes, 4) if minutes else None,
        "avg_profit_per_minute": round((total_charge - total_cost) / minutes, 4) if minutes else None,
    }


def _response(db: Session, pricing: PricingSnapshot) -> Dict[str, Any]:
    return {
        "profit_percent": pricing.profit_percent,
        "infra_cost_per_minute_inr": pricing.infra_cost_per_minute_inr,
        "updated_at": pricing.updated_at.isoformat() if pricing.updated_at else None,
        "updated_by": pricing.updated_by,
        "preview": _preview(db, pricing),
    }


@router.get("")
def get_pricing_settings(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Current profit margin and infrastructure overhead, with a preview from recent calls (admin only)."""
    return _response(db, get_pricing(db))


@router.put("")
def update_pricing_settings(
    req: UpdatePricingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Sets the profit margin and infrastructure overhead used to price every call (admin only)."""
    pricing = update_pricing(db, req.profit_percent, req.infra_cost_per_minute_inr, current_user.id)
    return _response(db, pricing)
