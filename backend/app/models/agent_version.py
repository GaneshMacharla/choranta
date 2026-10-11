from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.session import Base


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id = Column(String(64), primary_key=True, index=True)  # agtv_xxxxxxxx
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    configuration_json = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="DRAFT")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    agent = relationship("Agent", back_populates="versions")
    creator = relationship("User")

    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_version_number"),
    )

    def __repr__(self) -> str:
        return f"<AgentVersion {self.agent_id} v{self.version_number}>"
