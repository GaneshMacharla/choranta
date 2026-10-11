from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, Table, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base

agent_tools = Table(
    "agent_tools",
    Base.metadata,
    Column("agent_id", String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id", String(64), ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
)


class Tool(Base):
    __tablename__ = "tools"

    id = Column(String(64), primary_key=True, index=True)  # check_availability, etc.
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    input_schema = Column(JSON, nullable=False, default=dict)
    output_schema = Column(JSON, nullable=False, default=dict)
    executor_type = Column(String(64), nullable=False, default="SYSTEM")
    timeout = Column(Integer, nullable=False, default=30)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    agents = relationship("Agent", secondary=agent_tools, backref="tools")

    def __repr__(self) -> str:
        return f"<Tool {self.id}>"
