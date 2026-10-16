from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON, Text
from app.db.session import Base


class StandardCallScript(Base):
    """
    Admin-maintained call script shared by every AI employee linked to it (one per template, e.g. real estate).
    Linked employees take its current content each time they are published.
    """
    __tablename__ = "standard_call_scripts"

    key = Column(String(64), primary_key=True)  # template id, e.g. real_estate_lead_qualification
    name = Column(String(255), nullable=False)
    discovery_questions = Column(JSON, nullable=False, default=list)
    offer_points = Column(JSON, nullable=False, default=list)
    next_step = Column(Text, nullable=False, default="")
    updated_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self) -> str:
        return f"<StandardCallScript {self.key}>"
