from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime
from app.db.session import Base


class PricingSettings(Base):
    """Single-row, admin-editable pricing: profit margin and infrastructure overhead used to price calls."""
    __tablename__ = "pricing_settings"

    id = Column(String(32), primary_key=True, default="default")
    profit_percent = Column(Float, nullable=False)
    infra_cost_per_minute_inr = Column(Float, nullable=False)
    updated_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
