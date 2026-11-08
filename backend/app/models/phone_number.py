from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.security import generate_unique_id
from app.db.session import Base


class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("phn_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True, index=True)

    provider = Column(String(32), nullable=False, default="vobiz")
    provider_number_id = Column(String(128), nullable=True)  # the carrier's id for the number
    phone_number = Column(String(32), nullable=False, unique=True, index=True)  # E.164 e.g. +14155552671
    country_code = Column(String(8), nullable=False, default="US")  # US, IN, GB, etc.
    status = Column(String(32), nullable=False, default="ACTIVE", index=True)  # ACTIVE, READY_TO_TEST (bought, waiting for a test call), INACTIVE, PROVISIONING

    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    client = relationship("Client")
    agent = relationship("Agent")
    agent_version = relationship("AgentVersion")
    calls = relationship("Call", back_populates="phone_number_rel", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PhoneNumber {self.id}: {self.phone_number} ({self.status}) provider={self.provider}>"
