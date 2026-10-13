from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.pricing_settings import PricingSettings

PRICING_ROW_ID = "default"
MAX_PROFIT_PERCENT = 1000.0
MAX_CREDITS_PER_MINUTE = 1000.0


@dataclass(frozen=True)
class PricingSnapshot:
    profit_percent: float
    infra_cost_per_minute_inr: float
    credits_per_minute: float = settings.DEFAULT_CREDITS_PER_MINUTE
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
        credits_per_minute=row.credits_per_minute if row.credits_per_minute is not None else settings.DEFAULT_CREDITS_PER_MINUTE,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def credits_per_minute(db: Session) -> float:
    return get_pricing(db).credits_per_minute


def update_pricing(
    db: Session,
    profit_percent: float,
    infra_cost_per_minute_inr: float,
    user_id: Optional[str],
    credits_per_minute: Optional[float] = None,
) -> PricingSnapshot:
    if credits_per_minute is not None and not 0 < credits_per_minute <= MAX_CREDITS_PER_MINUTE:
        raise ValidationException(f"Credits per minute must be above 0 and at most {MAX_CREDITS_PER_MINUTE:.0f}.")
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
    if credits_per_minute is not None:
        row.credits_per_minute = float(credits_per_minute)
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_pricing(db)
