from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.core.security import generate_unique_id


class Lead(Base):
    """
    Tenant-isolated lead and CRM enquiry record for real estate qualification.
    Stores initial campaign/enquiry context and tracks qualification outputs.
    """
    __tablename__ = "leads"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("lead_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(64), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    lead_source = Column(String(128), nullable=False, default="Website Enquiry")
    property_viewed = Column(String(255), nullable=True)
    enquiry_location = Column(String(255), nullable=True)
    enquiry_budget = Column(String(128), nullable=True)
    enquiry_bhk = Column(String(32), nullable=True)

    # Discovered / Confirmed qualification outputs
    buyer_budget = Column(String(128), nullable=True)
    buyer_location = Column(String(255), nullable=True)
    buyer_bhk = Column(String(32), nullable=True)
    purchase_timeline = Column(String(64), nullable=True)
    lead_qualification_status = Column(String(64), nullable=False, default="PENDING", index=True)  # PENDING, QUALIFIED, UNQUALIFIED, NURTURING
    property_interest = Column(String(255), nullable=True)
    site_visit_interest = Column(Boolean, nullable=False, default=False)
    callback_requested = Column(Boolean, nullable=False, default=False)
    call_disposition = Column(String(64), nullable=True)  # CONNECTED, INTERESTED, NOT_INTERESTED, DO_NOT_CALL, CALLBACK_REQUESTED
    next_action = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    client = relationship("Client")

    def __repr__(self) -> str:
        return f"<Lead {self.id}: {self.name} ({self.lead_qualification_status})>"
