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

# Tools switched off for now: hidden from the catalog, stripped from templates and never offered to agents
# on calls. Rows and agent links stay so a tool comes back by removing it from this list.
SWITCHED_OFF_TOOLS = frozenset({
    "check_availability", "book_appointment", "cancel_appointment", "reschedule_appointment", "create_lead",
    "update_customer", "transfer_call", "get_lead_details", "search_properties", "check_site_visit_slots",
    "update_lead_record", "book_site_visit", "schedule_callback",
})


def live_tool_ids(tool_ids):
    """The given tool ids without the switched-off ones, order kept."""
    return [t for t in (tool_ids or []) if t not in SWITCHED_OFF_TOOLS]


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
