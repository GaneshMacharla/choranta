from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Table, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base

agent_knowledge_sources = Table(
    "agent_knowledge_sources",
    Base.metadata,
    Column("agent_id", String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("knowledge_source_id", String(64), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id = Column(String(64), primary_key=True, index=True)  # knw_xxxxxxxx
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False, index=True)  # PDF, TEXT, WEBSITE, FAQ
    status = Column(String(32), nullable=False, default="READY")
    description = Column(Text, nullable=True)
    meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    agents = relationship("Agent", secondary=agent_knowledge_sources, backref="knowledge_sources")

    def __repr__(self) -> str:
        return f"<KnowledgeSource {self.name} ({self.type})>"
