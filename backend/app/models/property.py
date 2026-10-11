from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.core.security import generate_unique_id


class Property(Base):
    """
    Tenant-isolated, structured property store record for real estate inventory.
    Provides indexed querying for location, price, BHK, and availability.
    """
    __tablename__ = "properties"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("prop_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    project_name = Column(String(255), nullable=False, index=True)
    location = Column(String(255), nullable=False, index=True)
    price = Column(Integer, nullable=False)  # Numeric amount in standard currency
    price_display = Column(String(64), nullable=False)  # e.g. "₹85 Lakhs", "₹1.45 Cr"
    bhk = Column(Integer, nullable=False, index=True)  # e.g. 2, 3, 4
    property_type = Column(String(64), nullable=False, default="Apartment")  # Apartment, Villa, Plot
    status = Column(String(32), nullable=False, default="AVAILABLE", index=True)  # AVAILABLE, UNDER_OFFER, SOLD
    amenities = Column(JSON, nullable=False, default=list)
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    last_synced_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    client = relationship("Client")

    def __repr__(self) -> str:
        return f"<Property {self.id}: {self.project_name} ({self.bhk} BHK in {self.location})>"
