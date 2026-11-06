from datetime import datetime, timezone
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint
from app.core.security import generate_unique_id
from app.db.session import Base


def _now():
    return datetime.now(timezone.utc)


class ClientVerification(Base):
    """
    A client's business verification (KYC), done by Vobiz in the client's own name on their sub-account: the
    client types their PAN, GSTIN / CIN or verifies Aadhaar through DigiLocker in Choranta, and Choranta passes
    each one to Vobiz. VERIFIED once Vobiz stops blocking the sub-account's calls; numbers can be bought then.

    Kept when the client is deleted (client_id goes NULL, client_name stays): telecom rules expect the KYC
    behind every number given out to be available later.
    """
    __tablename__ = "client_kyc"
    __table_args__ = (UniqueConstraint("client_id", "is_mock", name="uq_client_kyc_client"),)

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("kyc"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    client_name = Column(String(255), nullable=True)
    kyc_type = Column(String(16), nullable=False)               # INDIVIDUAL or BUSINESS
    email = Column(String(255), nullable=False)
    status = Column(String(16), nullable=False, default="IN_PROGRESS", index=True)  # IN_PROGRESS / VERIFIED
    calls_blocked = Column(Boolean, nullable=False, default=True)  # Vobiz's gate on the sub-account
    sub_auth_id = Column(String(128), nullable=True)
    # pan / gst / cin / aadhaar -> {status, value, name, message, checked_at}
    checks = Column(JSON, nullable=False, default=dict)
    digilocker = Column(JSON, nullable=True)                    # {state, access_request_id} while Aadhaar is in progress
    is_mock = Column(Boolean, nullable=False, default=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
