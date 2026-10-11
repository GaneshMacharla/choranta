from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Table, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base

agent_integrations = Table(
    "agent_integrations",
    Base.metadata,
    Column("agent_id", String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("integration_id", String(64), ForeignKey("integrations.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
)


class Integration(Base):
    __tablename__ = "integrations"

    id = Column(String(64), primary_key=True, index=True)  # int_xxxxxxxx or slug
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=False)  # CALENDAR, CRM, WEBHOOK, MESSAGING, EMAIL
    provider = Column(String(64), nullable=False)  # GOOGLE, HUBSPOT, SALESFORCE, CUSTOM, TWILIO, SENDGRID
    connection_status = Column(String(32), nullable=False, default="CONFIGURED")
    meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    agents = relationship("Agent", secondary=agent_integrations, backref="integrations")

    def __repr__(self) -> str:
        return f"<Integration {self.name} ({self.provider})>"
