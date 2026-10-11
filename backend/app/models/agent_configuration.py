from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base


class AgentConfiguration(Base):
    __tablename__ = "agent_configurations"

    id = Column(String(64), primary_key=True, index=True)  # cfg_xxxxxxxx
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    configuration_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    agent = relationship("Agent", backref="draft_configuration", uselist=False)

    def __repr__(self) -> str:
        return f"<AgentConfiguration {self.agent_id}>"
