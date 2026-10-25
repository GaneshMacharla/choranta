from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApiKey(Base):
    """
    A client's key for Choranta's public API, checked by its SHA-256 hash. The key every client gets at sign-up
    (is_default) is also kept encrypted, so the portal dashboard can show it again; keys made by hand are not.
    """
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
    is_default = Column(Boolean, nullable=True)  # the automatic instant-outbound key
    key_enc = Column(Text, nullable=True)        # the full key, encrypted (default keys only)
