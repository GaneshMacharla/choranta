from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    """Naive UTC, matching how DateTime columns are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WhatsAppAccount(Base):
    """A client's own WhatsApp Business number (Meta Cloud API), used to send its follow-up messages."""
    __tablename__ = "whatsapp_accounts"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("wac"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True)
    waba_id = Column(String(64), nullable=False)                     # WhatsApp Business Account id
    phone_number_id = Column(String(64), nullable=False, index=True)  # Meta's id for the sending number
    display_phone = Column(String(32), nullable=True)
    verified_name = Column(String(255), nullable=True)
    access_token_enc = Column(Text, nullable=False)                   # permanent system-user token, encrypted
    # Secret of the client's own Meta app, which signs the webhooks it sends us (encrypted); none = Choranta's app
    app_secret_enc = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="ACTIVE")     # ACTIVE / INVALID (Meta rejected the token)
    status_detail = Column(Text, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class WhatsAppFollowup(Base):
    """
    The message an AI employee's interested callers get on WhatsApp after the call. Meta only allows
    business-started chats from approved templates, so the client's text is submitted as one; until a new
    version is approved, the last approved one keeps being sent.
    """
    __tablename__ = "whatsapp_followups"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("waf"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True)
    message = Column(Text, nullable=False)                 # "Hi {name}, thanks for your interest in {course}..."
    language = Column(String(16), nullable=False, default="en")  # the template's language code (en, hi, te...)
    button_text = Column(String(25), nullable=True)
    button_url = Column(Text, nullable=True)
    send_when = Column(JSON, nullable=False, default=lambda: ["qualified"])  # "qualified" and/or call interest values
    version = Column(Integer, nullable=False, default=0)

    # The latest submitted version
    template_name = Column(String(512), nullable=True)
    template_status = Column(String(16), nullable=True)    # PENDING / APPROVED / REJECTED / ERROR
    template_detail = Column(Text, nullable=True)          # Meta's rejection reason or the submission error
    template_placeholders = Column(JSON, nullable=False, default=list)  # placeholder name for {{1}}, {{2}}...

    # The version that is sent
    approved_template_name = Column(String(512), nullable=True)
    approved_message = Column(Text, nullable=True)
    approved_placeholders = Column(JSON, nullable=False, default=list)
    approved_language = Column(String(16), nullable=True)
    approved_category = Column(String(16), nullable=True)  # UTILITY / MARKETING (Meta may re-categorise; sets the price)

    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class WhatsAppMessage(Base):
    """A follow-up sent to a lead (OUT) or a lead's reply (IN)."""
    __tablename__ = "whatsapp_messages"
    __table_args__ = (UniqueConstraint("call_id", "direction", name="uq_whatsapp_message_call_direction"),)

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("wam"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), nullable=True, index=True)
    call_id = Column(String(64), nullable=True)            # the call an OUT follow-up was sent after
    lead_id = Column(String(64), nullable=True, index=True)
    direction = Column(String(8), nullable=False)          # OUT / IN
    phone = Column(String(32), nullable=False, index=True)  # the lead's number, E.164
    template_name = Column(String(512), nullable=True)
    language = Column(String(16), nullable=True)
    params = Column(JSON, nullable=False, default=list)
    body = Column(Text, nullable=True)                     # the text as the lead sees it / their reply
    wa_message_id = Column(String(128), nullable=True, unique=True)
    # OUT: QUEUED / SENDING / SENT / DELIVERED / READ / FAILED / SKIPPED; IN: RECEIVED
    status = Column(String(16), nullable=False, default="QUEUED", index=True)
    error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    charged_credits = Column(JSON, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
