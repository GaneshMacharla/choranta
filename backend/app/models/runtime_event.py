from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"

    id = Column(String(64), primary_key=True, index=True)  # evt_xxxxxxxx
    session_id = Column(String(64), ForeignKey("runtime_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    payload_json = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    session = relationship("RuntimeSession", back_populates="events")

    def __repr__(self) -> str:
        return f"<RuntimeEvent {self.id} type={self.event_type} session={self.session_id}>"
