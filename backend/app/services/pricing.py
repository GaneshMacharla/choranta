from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.pricing_settings import PricingSettings

PRICING_ROW_ID = "default"
MAX_PROFIT_PERCENT = 1000.0


@dataclass(frozen=True)
class PricingSnapshot:
    profit_percent: float
    infra_cost_per_minute_inr: float
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


def get_pricing(db: Session) -> PricingSnapshot:
    """Current admin pricing, or the configured defaults if it has never been set."""
    row = db.get(PricingSettings, PRICING_ROW_ID)
    if row is None:
        return PricingSnapshot(
            profit_percent=settings.DEFAULT_PROFIT_PERCENT,
            infra_cost_per_minute_inr=settings.DEFAULT_INFRA_COST_PER_MINUTE_INR,
        )
    return PricingSnapshot(
        profit_percent=row.profit_percent,
        infra_cost_per_minute_inr=row.infra_cost_per_minute_inr,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def update_pricing(db: Session, profit_percent: float, infra_cost_per_minute_inr: float, user_id: Optional[str]) -> PricingSnapshot:
    if not 0 <= profit_percent <= MAX_PROFIT_PERCENT:
        raise ValidationException(f"Profit percent must be between 0 and {MAX_PROFIT_PERCENT:.0f}.")
    if infra_cost_per_minute_inr < 0:
        raise ValidationException("Infrastructure cost per minute cannot be negative.")

    row = db.get(PricingSettings, PRICING_ROW_ID)
    if row is None:
        row = PricingSettings(id=PRICING_ROW_ID)
        db.add(row)
    row.profit_percent = float(profit_percent)
    row.infra_cost_per_minute_inr = float(infra_cost_per_minute_inr)
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_pricing(db)
