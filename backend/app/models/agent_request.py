from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    return datetime.now(timezone.utc)


class AgentRequest(Base):
    """
    A paying client's request for a new AI employee: they pick the name and a Sarvam voice, and a
    Choranta admin builds the agent. PENDING -> IN_PROGRESS -> COMPLETED (linked agent), or REJECTED /
    CANCELLED (by the client while still pending). Before going live the admin may send it to the client to
    try (CLIENT_TRIAL: a short free browser call); the admin still decides when it goes live.
    """
    __tablename__ = "agent_requests"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("areq_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    company_name = Column(String(255), nullable=True)   # as the client typed it in the request
    business_type = Column(String(32), nullable=True)   # BusinessTypeEnum value, e.g. CLINIC
    voice_id = Column(String(64), nullable=False, default="")  # Sarvam speaker, e.g. "priya"; "" = admin picks
    notes = Column(Text, nullable=True)            # older requests: "about your business"
    details = Column(Text, nullable=True)          # older requests: JSON {"tasks": [...], "languages": [...]}
    status = Column(String(16), nullable=False, default="PENDING", index=True)
    agent_id = Column(String(64), nullable=True)
    admin_note = Column(Text, nullable=True)
    trial_calls_used = Column(Integer, nullable=False, default=0)  # client's trial calls since it was last sent to them
    requested_by = Column(String(64), nullable=True)
    handled_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
