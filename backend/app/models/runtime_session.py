from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base


class RuntimeSession(Base):
    __tablename__ = "runtime_sessions"

    id = Column(String(64), primary_key=True, index=True)  # ses_xxxxxxxx
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="CREATED", index=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)
    usage_json = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    client = relationship("Client")
    agent = relationship("Agent")
    agent_version = relationship("AgentVersion")
    events = relationship("RuntimeEvent", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<RuntimeSession {self.id} ({self.status}) agent={self.agent_id}>"
