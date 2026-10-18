from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Integer
from app.db.session import Base


class PricingSettings(Base):
    """Single-row, admin-editable pricing: credits per call minute, plus cost inputs for profit reporting."""
    __tablename__ = "pricing_settings"

    id = Column(String(32), primary_key=True, default="default")
    profit_percent = Column(Float, nullable=False)
    infra_cost_per_minute_inr = Column(Float, nullable=False, default=0.0)  # unused: calls are priced on real cost
    credits_per_minute = Column(Float, nullable=True)  # what clients pay per billed call minute (1 credit = Rs 1)
    payg_max_concurrent_calls = Column(Integer, nullable=True)  # unused: calls at a time follow the wallet
    updated_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
