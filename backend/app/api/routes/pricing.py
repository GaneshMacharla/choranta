from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.services.pricing import PricingSnapshot, get_pricing, recent_charge_per_minute, update_pricing

router = APIRouter(prefix="/pricing", tags=["Pricing"])



class UpdatePricingRequest(BaseModel):
    profit_percent: float = Field(..., description="Profit added on top of each call's real cost, in percent")


def _preview(db: Session, pricing: PricingSnapshot) -> Dict[str, Any]:
    """Average cost and resulting client charge per minute over recent completed calls."""
    return recent_charge_per_minute(db, pricing)


def _response(db: Session, pricing: PricingSnapshot) -> Dict[str, Any]:
    return {
        "profit_percent": pricing.profit_percent,
        "updated_at": pricing.updated_at.isoformat() if pricing.updated_at else None,
        "updated_by": pricing.updated_by,
        "preview": _preview(db, pricing),
    }


@router.get("")
def get_pricing_settings(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Profit %, with a cost/charge preview from recent calls (admin only)."""
    return _response(db, get_pricing(db))


@router.put("")
def update_pricing_settings(
    req: UpdatePricingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Sets the profit % added to every call's real cost (admin only)."""
    pricing = update_pricing(db, req.profit_percent, current_user.id)
    return _response(db, pricing)
