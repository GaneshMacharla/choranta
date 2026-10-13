from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    return datetime.now(timezone.utc)


class ClientNotification(Base):
    """A message shown under the bell in the client portal (plan activated, AI employee ready, low credits...)."""
    __tablename__ = "client_notifications"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("ntf_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)          # e.g. PLAN_ACTIVE, CREDITS_ADDED, EMPLOYEE_READY, CREDITS_LOW
    level = Column(String(16), nullable=False, default="info")  # info / success / warning
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    link = Column(String(255), nullable=True)          # portal path to open, e.g. /portal/employees
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
