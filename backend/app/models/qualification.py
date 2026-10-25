from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    """Naive UTC, matching how DateTime columns are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LeadQualificationSetup(Base):
    """
    What makes a caller a qualified lead for one AI employee, set by the client: rules over the details the
    agent collects (any group of all-true conditions qualifies), and/or a plain-language test the post-call
    AI applies with a reason. See services/lead_qualification.py.
    """
    __tablename__ = "lead_qualification_setups"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("lqs"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True)
    # [[{"field": "demo_class_booked", "op": "is_true"}], [{"field": "target_exam", "op": "in", "value": ["NEET"]}, ...]]
    rules = Column(JSON, nullable=False, default=list)
    ai_criteria = Column(Text, nullable=True)  # e.g. "Plans to join this year and the fees suit them"
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
