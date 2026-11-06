from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text

from app.core.security import generate_unique_id
from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MissedCallCallback(Base):
    """An inbound caller turned away because every line was busy, and told they'd be called back."""
    __tablename__ = "missed_call_callbacks"
    __table_args__ = (Index("ix_missed_call_callbacks_client_caller", "client_id", "caller_number"),)

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("mcb_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    phone_number_id = Column(String(64), ForeignKey("phone_numbers.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False)
    caller_number = Column(String(32), nullable=False)
    # QUEUED -> DIALING -> CALLING -> CONNECTED, or back to QUEUED for another attempt; else FAILED, EXPIRED or SKIPPED
    status = Column(String(16), nullable=False, default="QUEUED", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=False, default=_utcnow)
    last_call_id = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class CapacityDaily(Base):
    """One day's capacity totals (India time): what shows whether buying more lines or moving carrier is justified."""
    __tablename__ = "capacity_daily"

    day = Column(Date, primary_key=True)
    peak_live_calls = Column(Integer, nullable=False, default=0)
    inbound_refused_busy = Column(Integer, nullable=False, default=0)
    callbacks_queued = Column(Integer, nullable=False, default=0)
    callbacks_connected = Column(Integer, nullable=False, default=0)
    callbacks_expired = Column(Integer, nullable=False, default=0)
    campaign_wait_seconds = Column(Float, nullable=False, default=0.0)  # campaign-seconds with people waiting and no free line
    vobiz_limit_rejections = Column(Integer, nullable=False, default=0)
    sarvam_llm_requests = Column(Integer, nullable=False, default=0)    # live calls only: measures requests per call-minute
    sarvam_llm_limited = Column(Integer, nullable=False, default=0)     # turned away by our own limiter, never sent
    sarvam_429 = Column(Integer, nullable=False, default=0)
    sarvam_503 = Column(Integer, nullable=False, default=0)
    sarvam_ws_rejected = Column(Integer, nullable=False, default=0)
    gemini_fallbacks = Column(Integer, nullable=False, default=0)
    live_call_minutes = Column(Float, nullable=False, default=0.0)
