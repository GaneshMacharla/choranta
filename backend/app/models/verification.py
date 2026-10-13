from datetime import datetime, timezone
from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text
from app.db.session import Base


def _now():
    return datetime.now(timezone.utc)


class ClientVerification(Base):
    """
    One-time business verification (KYC) a client completes before buying phone numbers, as Indian telecom
    rules require. A Choranta admin reviews it: PENDING -> APPROVED, or REJECTED with a reason to fix.
    """
    __tablename__ = "client_verifications"

    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(16), nullable=False, default="PENDING", index=True)  # PENDING / APPROVED / REJECTED
    legal_name = Column(String(255), nullable=False)
    pan = Column(String(10), nullable=False)
    gstin = Column(String(15), nullable=True)
    cin = Column(String(32), nullable=True)
    registered_address = Column(Text, nullable=False)
    signatory_name = Column(String(255), nullable=False)
    signatory_designation = Column(String(100), nullable=True)
    signatory_phone = Column(String(32), nullable=True)
    documents = Column(JSON, nullable=False, default=list)  # [{kind, filename, path, size, content_type, uploaded_at}]
    admin_note = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=_now, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
