"""
Phone numbers Choranta owns at a carrier, kept apart from who uses them.

- ProviderNumber: one number on Choranta's carrier account (bought, adopted by sync, or released). The carrier's
  state (provider_status) and ours (internal_status) are separate: a number is never marked owned just because a
  purchase was requested.
- NumberAssignment: which client (and AI employee / SIP trunk) a number is given to. History is kept; at most one
  ACTIVE assignment per number (partial unique index). The client-facing routing record is the existing
  PhoneNumber row (models/phone_number.py), which inbound calls are looked up by.
- NumberOperation: every purchase, assignment, release and sync, with its idempotency key and outcome. Doubles as
  the audit log.
- MockCarrierNumber: the simulated carrier's own state in PHONE_NUMBER_MOCK_MODE (never used with real Vobiz).
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, text

from app.core.security import generate_unique_id
from app.db.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderNumber(Base):
    __tablename__ = "provider_numbers"
    __table_args__ = (UniqueConstraint("provider", "e164", name="uq_provider_numbers_provider_e164"),)

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("pnm"))
    provider = Column(String(32), nullable=False, index=True)            # vobiz, exotel
    provider_number_id = Column(String(128), nullable=True)
    e164 = Column(String(32), nullable=False, index=True)
    country = Column(String(8), nullable=True)
    region = Column(String(128), nullable=True)
    number_type = Column(String(16), nullable=True)                      # Landline, Mobile, TollFree
    number_type_derived = Column(Boolean, nullable=False, default=True)  # worked out from the prefix (carrier doesn't say)
    capabilities = Column(JSON, default=dict)
    provider_status = Column(String(32), nullable=True)                  # as the carrier reports it; MISSING = gone there
    # AVAILABLE (owned, unassigned), ASSIGNED, RELEASING, RELEASED, NEEDS_RECONCILIATION
    internal_status = Column(String(32), nullable=False, default="AVAILABLE", index=True)
    monthly_cost = Column(Float, nullable=True)                          # what the carrier charges Choranta
    setup_cost = Column(Float, nullable=True)
    currency = Column(String(8), nullable=True)
    application_id = Column(String(128), nullable=True)
    trunk_id = Column(String(128), nullable=True)
    is_mock = Column(Boolean, nullable=False, default=False)
    attention = Column(Text, nullable=True)                              # something staff need to fix
    raw = Column(JSON, default=dict)
    purchased_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class NumberAssignment(Base):
    __tablename__ = "number_assignments"
    __table_args__ = (
        Index("uq_number_assignments_active", "provider_number_id", unique=True,
              sqlite_where=text("status = 'ACTIVE'"), postgresql_where=text("status = 'ACTIVE'")),
    )

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("nas"))
    provider_number_id = Column(String(64), ForeignKey("provider_numbers.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    trunk_id = Column(String(128), nullable=True)
    phone_number_id = Column(String(64), ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, default="ACTIVE", index=True)  # ACTIVE, ENDED
    assigned_by = Column(String(255), nullable=True)
    ended_by = Column(String(255), nullable=True)
    end_reason = Column(String(64), nullable=True)
    assigned_at = Column(DateTime, default=_now, nullable=False)
    released_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class NumberOperation(Base):
    __tablename__ = "number_operations"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("nop"))
    provider_number_id = Column(String(64), ForeignKey("provider_numbers.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String(32), nullable=True)
    e164 = Column(String(32), nullable=True, index=True)
    operation_type = Column(String(32), nullable=False, index=True)   # PURCHASE, ASSIGN, UNASSIGN, RELEASE, SYNC, ATTACH_APP
    # PENDING, SUCCEEDED, FAILED, UNCERTAIN, NEEDS_RECONCILIATION, RECOVERED
    operation_status = Column(String(32), nullable=False, default="PENDING", index=True)
    idempotency_key = Column(String(128), nullable=True, unique=True)
    provider_request_id = Column(String(128), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    actor = Column(String(255), nullable=True)          # "ADMIN a@b.com", "CLIENT owner@x.com", "SYSTEM"
    actor_user_id = Column(String(64), nullable=True)
    client_id = Column(String(64), nullable=True, index=True)
    is_mock = Column(Boolean, nullable=False, default=False)
    request = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class MockCarrierNumber(Base):
    """The simulated carrier's inventory and ownership (PHONE_NUMBER_MOCK_MODE only)."""
    __tablename__ = "mock_carrier_numbers"

    e164 = Column(String(32), primary_key=True)
    country = Column(String(8), nullable=False)
    region = Column(String(128), nullable=True)
    setup_fee = Column(Float, nullable=False, default=0)
    monthly_fee = Column(Float, nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="INR")
    scenario = Column(String(32), nullable=True)        # failure this number simulates when bought
    owned = Column(Boolean, nullable=False, default=False)
    application_id = Column(String(128), nullable=True)
    trunk_id = Column(String(128), nullable=True)
    purchased_at = Column(DateTime, nullable=True)
