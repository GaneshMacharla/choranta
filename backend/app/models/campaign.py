from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    """Naive UTC, matching how DateTime columns are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Campaign(Base):
    """An outbound calling campaign: one agent version dialling a list of recipients inside calling windows."""
    __tablename__ = "campaigns"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("cmp"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    purpose = Column(String(16), nullable=False, default="SERVICE")  # SERVICE / PROMOTIONAL
    # BULK = a fixed list dialled once; TRIGGER = always-on, recipients arrive from the public leads API
    kind = Column(String(16), nullable=False, default="BULK", index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    provider = Column(String(32), nullable=False, default="exotel")
    caller_number_ids = Column(JSON, nullable=False, default=list)  # PhoneNumber ids, rotated round-robin

    # DRAFT / SCHEDULED / RUNNING / PAUSED / STOPPING / COMPLETED / CANCELLED
    status = Column(String(16), nullable=False, default="DRAFT", index=True)
    pause_reason = Column(Text, nullable=True)

    # Calling windows in the campaign's local time: [{"start_min": 600, "end_min": 1140}], days 0=Mon..6=Sun
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata")
    windows = Column(JSON, nullable=False, default=lambda: [{"start_min": 600, "end_min": 1140}])
    days = Column(JSON, nullable=False, default=lambda: [0, 1, 2, 3, 4, 5])
    start_at = Column(DateTime, nullable=True)  # None = start on launch

    max_concurrent = Column(Integer, nullable=False, default=1)
    retry_max = Column(Integer, nullable=False, default=2)
    retry_intervals_min = Column(JSON, nullable=False, default=lambda: [30, 60])
    retry_on = Column(JSON, nullable=False, default=lambda: ["no-answer", "busy", "failed"])
    next_caller_index = Column(Integer, nullable=False, default=0)

    # Optional results webhook: every finished recipient is POSTed here, signed with webhook_secret
    webhook_url = Column(Text, nullable=True)
    webhook_secret = Column(String(64), nullable=True)

    consent_ack_by = Column(String(64), nullable=True)
    consent_ack_at = Column(DateTime, nullable=True)
    created_by = Column(String(64), nullable=True)
    launched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class CampaignRecipient(Base):
    """One person to call in a campaign, with the variables passed to the agent and the latest outcome."""
    __tablename__ = "campaign_recipients"
    __table_args__ = (UniqueConstraint("campaign_id", "phone", name="uq_campaign_recipient_phone"),)

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("rcp"))
    campaign_id = Column(String(64), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    phone = Column(String(32), nullable=False, index=True)  # E.164
    name = Column(String(255), nullable=True)
    variables = Column(JSON, nullable=False, default=dict)
    lead_id = Column(String(64), nullable=True)

    # PENDING / DIALING / RETRY_WAIT / COMPLETED / FAILED / SKIPPED
    status = Column(String(16), nullable=False, default="PENDING", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    last_call_id = Column(String(64), nullable=True)
    last_dialed_at = Column(DateTime, nullable=True)
    # answered / no-answer / busy / failed / suppressed / stopped
    outcome = Column(String(32), nullable=True)
    result = Column(JSON, nullable=False, default=dict)  # agent outputs / lead disposition after the call
    error = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0)  # upload order
    source = Column(String(64), nullable=True)  # csv / lead / website form name for instant leads
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class CampaignAttempt(Base):
    """Append-only log of every dial made for a recipient."""
    __tablename__ = "campaign_attempts"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("att"))
    campaign_id = Column(String(64), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id = Column(String(64), ForeignKey("campaign_recipients.id", ondelete="CASCADE"), nullable=False, index=True)
    call_id = Column(String(64), nullable=True)
    attempt_no = Column(Integer, nullable=False)
    caller_number = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False)  # COMPLETED / FAILED
    outcome = Column(String(32), nullable=True)
    duration_seconds = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, default=_now, nullable=False)


class DoNotCallEntry(Base):
    """A number a client must not call (caller opted out, or added manually)."""
    __tablename__ = "do_not_call"
    __table_args__ = (UniqueConstraint("client_id", "phone", name="uq_dnc_client_phone"),)

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("dnc"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    phone = Column(String(32), nullable=False)
    source = Column(String(32), nullable=False, default="manual")  # caller_request / manual / import
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class WebhookDelivery(Base):
    """A results webhook to send (or retry) for a finished campaign recipient."""
    __tablename__ = "webhook_deliveries"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("whd"))
    campaign_id = Column(String(64), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id = Column(String(64), nullable=False)
    url = Column(Text, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(16), nullable=False, default="PENDING", index=True)  # PENDING / SENT / FAILED
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, default=_now, nullable=False)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    sent_at = Column(DateTime, nullable=True)
