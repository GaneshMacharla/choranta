from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.core.security import generate_unique_id
from app.db.session import Base


class Call(Base):
    __tablename__ = "calls"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("call_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    phone_number_id = Column(String(64), ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True, index=True)
    runtime_session_id = Column(String(64), ForeignKey("runtime_sessions.id", ondelete="SET NULL"), nullable=True, index=True)

    provider = Column(String(32), nullable=False, default="exotel")  # exotel
    provider_call_id = Column(String(128), nullable=False, unique=True, index=True)  # CallSid from exotel
    direction = Column(String(16), nullable=False, default="INBOUND", index=True)  # INBOUND, OUTBOUND
    caller_number = Column(String(32), nullable=False, index=True)  # Caller E.164
    destination_number = Column(String(32), nullable=False, index=True)  # Choranta E.164

    # Normalized canonical states: RINGING, ANSWERED, CONNECTED, ACTIVE, ENDING, COMPLETED, FAILED
    status = Column(String(32), nullable=False, default="RINGING", index=True)
    started_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=False, default=0.0)
    termination_reason = Column(String(64), nullable=True)  # caller_hangup, assistant_completed, error, timeout

    recording_url = Column(String(512), nullable=True)
    recording_sid = Column(String(128), nullable=True)
    transcript_summary = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    client = relationship("Client")
    agent = relationship("Agent")
    agent_version = relationship("AgentVersion")
    phone_number_rel = relationship("PhoneNumber", back_populates="calls")
    runtime_session = relationship("RuntimeSession")

    def __repr__(self) -> str:
        return f"<Call {self.id}: {self.caller_number} -> {self.destination_number} ({self.status}) sid={self.provider_call_id}>"
