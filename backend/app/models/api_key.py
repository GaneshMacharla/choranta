from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, String
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApiKey(Base):
    """A client's key for Choranta's public API. Only a SHA-256 hash of the key is stored."""
    __tablename__ = "api_keys"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("key"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    prefix = Column(String(32), nullable=False)  # first characters, shown so keys can be told apart
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
