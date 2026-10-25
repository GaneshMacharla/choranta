"""
Instant website lead calls: a client's website (server side) posts a form submission to
POST /api/public/leads with its API key, and Choranta calls the person within seconds.

Request path (kept to a few database round trips, since the database is remote):
  API key (cached) -> trigger campaign -> duplicate check -> insert recipient -> 202.
The recipient is inserted already claimed (DIALING) when it can be called now, so the dial that
follows in the background never races the campaign dialer. Anything that can't be dialled right
away (outside calling hours, lines busy, a failure) is left to the normal dialer and retries.
"""
import hashlib
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.api_key import ApiKey
from app.models.call import Call
from app.models.campaign import Campaign, CampaignRecipient
from app.models.lead import Lead
from app.services import campaigns as campaign_svc
from app.services.outbound_calls import place_outbound_call

logger = logging.getLogger("choranta.services.instant_leads")

KEY_PREFIX = "chr_live_"
KEY_CACHE_TTL_S = 60.0
RATE_LIMIT_PER_MIN = 60
DUPLICATE_WINDOW = timedelta(hours=24)
RESERVED_FIELDS = {"phone", "phone_number", "mobile", "number", "name", "full_name", "source", "consent",
                   "campaign_id", "api_key"}
MAX_VARIABLES = 30


class LeadError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- API keys


@dataclass(frozen=True)
class KeyContext:
    key_id: str
    client_id: str


_key_cache: Dict[str, Tuple[float, Optional[KeyContext]]] = {}


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_api_key(db: Session, client_id: str, name: str, created_by: Optional[str],
                   default: bool = False) -> Tuple[ApiKey, str]:
    """
    Creates a key and returns it with the full secret. Only a default key keeps an encrypted copy that can be
    shown again; for any other key this is the only time the secret is seen.
    """
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(client_id=client_id, name=name.strip() or "Website", prefix=raw[:len(KEY_PREFIX) + 6],
                 key_hash=hash_key(raw), created_by=created_by)
    if default:
        from app.core.secrets_box import encrypt
        key.is_default, key.key_enc = True, encrypt(raw)
    db.add(key)
    db.commit()
    db.refresh(key)
    return key, raw


DEFAULT_KEY_NAME = "Instant outbound (created for you)"


def default_key(db: Session, client_id: str) -> Optional[ApiKey]:
    return (db.query(ApiKey).filter(ApiKey.client_id == client_id, ApiKey.is_default.is_(True),
                                    ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc()).first())


def ensure_default_key(db: Session, client_id: str, created_by: Optional[str] = None) -> Optional[ApiKey]:
    """
    The client's automatic instant-outbound key, created on first need (at sign-up, or when the dashboard opens
    for clients from before). None if it can't be stored (no encryption key on a production server).
    """
    key = default_key(db, client_id)
    if key:
        return key
    try:
        key, _ = create_api_key(db, client_id, DEFAULT_KEY_NAME, created_by, default=True)
    except ValueError as exc:
        db.rollback()
        logger.error(f"Couldn't create the default API key for client {client_id}: {exc}")
        return None
    return key


def reveal_key(key: ApiKey) -> str:
    from app.core.secrets_box import decrypt
    if not key.key_enc:
        raise LeadError("This key can't be shown again. Create a new one.", 409)
    try:
        return decrypt(key.key_enc)
    except ValueError:
        raise LeadError("This key can't be shown on this server. Create a new one.", 409)


def regenerate_default_key(db: Session, client_id: str, created_by: Optional[str]) -> Optional[ApiKey]:
    """Replaces the default key: the old one stops working at once."""
    old = default_key(db, client_id)
    if old:
        revoke_api_key(db, old)
    return ensure_default_key(db, client_id, created_by)


def revoke_api_key(db: Session, key: ApiKey) -> ApiKey:
    if not key.revoked_at:
        key.revoked_at = campaign_svc.utcnow()
        db.commit()
    _key_cache.pop(key.key_hash, None)
    return key


def authenticate(db: Session, raw: Optional[str]) -> KeyContext:
    """The client a key belongs to; raises LeadError(401) for a missing, unknown or revoked key."""
    raw = (raw or "").strip()
    if not raw:
        raise LeadError("Missing X-API-Key header.", 401)
    digest = hash_key(raw)
    cached = _key_cache.get(digest)
    if cached and time.monotonic() - cached[0] < KEY_CACHE_TTL_S:
        ctx = cached[1]
    else:
        key = db.query(ApiKey).filter(ApiKey.key_hash == digest).first()
        ctx = KeyContext(key.id, key.client_id) if key and not key.revoked_at else None
        _key_cache[digest] = (time.monotonic(), ctx)
    if ctx is None:
        raise LeadError("Invalid or revoked API key.", 401)
    return ctx


# ---------------------------------------------------------------- rate limiting (per process)


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit, self.window_s = limit, window_s
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


rate_limiter = RateLimiter(RATE_LIMIT_PER_MIN)


# ---------------------------------------------------------------- accepting a lead


def _trigger_campaign(db: Session, client_id: str, campaign_id: Optional[str]) -> Campaign:
    if campaign_id:
        campaign = db.get(Campaign, campaign_id)
        if not campaign or campaign.client_id != client_id or campaign.kind != "TRIGGER":
            raise LeadError("campaign_id is not one of your website-lead campaigns.", 404)
    else:
        candidates = (
            db.query(Campaign)
            .filter(Campaign.client_id == client_id, Campaign.kind == "TRIGGER",
                    Campaign.status.in_(("RUNNING", "PAUSED", "SCHEDULED")))
            .order_by(Campaign.created_at.desc()).all()
        )
        running = [c for c in candidates if c.status == "RUNNING"]
        campaign = (running or candidates or [None])[0]
        if campaign is None:
            raise LeadError("No website-lead campaign is set up. Create one under Campaigns → Website leads.", 409)
    if campaign.status not in ("RUNNING", "PAUSED", "SCHEDULED"):
        raise LeadError("This website-lead campaign has ended.", 409)
    return campaign


def _variables(payload: Dict[str, Any], name: Optional[str]) -> Dict[str, Any]:
    variables: Dict[str, Any] = {}
    for key, value in payload.items():
        clean = campaign_svc._column_key(str(key))
        if not clean or clean in RESERVED_FIELDS or value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text and len(variables) < MAX_VARIABLES:
            variables[clean] = text[:500]
    if name:
        variables["user_name"] = name
    return variables


def accept_lead(db: Session, ctx: KeyContext, payload: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Validates a submitted lead and queues it on the client's website-lead campaign.
    Returns {"status": "accepted"|"duplicate", "recipient_id", "campaign_id", "dial_now"}.
    """
    now = now or campaign_svc.utcnow()
    if not rate_limiter.allow(ctx.key_id):
        raise LeadError(f"Too many leads: at most {RATE_LIMIT_PER_MIN} per minute per API key.", 429)

    raw_phone = payload.get("phone") or payload.get("phone_number") or payload.get("mobile")
    phone = campaign_svc.normalize_phone(raw_phone)
    if not phone:
        raise LeadError("A valid phone number is required (field 'phone').")
    if payload.get("consent") not in (True, "true", "True", "yes", "1", 1, "on"):
        raise LeadError("The person must consent to be called: send \"consent\": true.")
    name = str(payload.get("name") or payload.get("full_name") or "").strip()[:255] or None
    source = str(payload.get("source") or "website").strip()[:64]

    campaign = _trigger_campaign(db, ctx.client_id, payload.get("campaign_id"))
    existing = db.query(CampaignRecipient).filter(
        CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.phone == phone
    ).first()
    if existing and (existing.created_at >= now - DUPLICATE_WINDOW
                     or existing.status in ("PENDING", "DIALING", "RETRY_WAIT")):
        return {"status": "duplicate", "recipient_id": existing.id, "campaign_id": campaign.id, "dial_now": False}

    dial_now = campaign.status == "RUNNING" and campaign_svc.in_calling_window(campaign, now)
    recipient = existing or CampaignRecipient(campaign_id=campaign.id, client_id=campaign.client_id, phone=phone)
    recipient.name = name
    recipient.variables = _variables(payload, name)
    recipient.source = source
    recipient.lead_id = None
    # Claimed at insert when it can be called now, so the dialer tick never picks it up meanwhile
    recipient.status = "DIALING" if dial_now else "PENDING"
    recipient.last_dialed_at = now if dial_now else None
    recipient.attempts = 0
    recipient.next_attempt_at = None
    recipient.last_call_id = None
    recipient.outcome = None
    recipient.result = {}
    recipient.error = None
    recipient.position = int(now.timestamp())
    recipient.created_at = now
    if not existing:
        db.add(recipient)
    db.commit()
    return {"status": "accepted", "recipient_id": recipient.id, "campaign_id": campaign.id, "dial_now": dial_now,
            "phone": phone, "name": name, "source": source}


# ---------------------------------------------------------------- after the response


def instant_dial(db: Session, recipient_id: str, now: Optional[datetime] = None,
                 dial: Callable[..., Call] = place_outbound_call) -> str:
    """Dials a lead claimed by accept_lead. Anything that can't go out now is left to the dialer."""
    now = now or campaign_svc.utcnow()
    recipient = db.get(CampaignRecipient, recipient_id)
    if not recipient or recipient.status != "DIALING" or recipient.last_call_id:
        return "skipped"
    campaign = db.get(Campaign, recipient.campaign_id)
    live = db.query(CampaignRecipient.id).filter(
        CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "DIALING",
        CampaignRecipient.id != recipient.id,
    ).count()
    if campaign.status != "RUNNING" or live >= campaign.max_concurrent:
        recipient.status = "PENDING"
        db.commit()
        return "queued"
    return campaign_svc.dial_claimed(db, campaign, recipient, "PENDING", now, dial)


def record_lead(db: Session, client_id: str, recipient_id: str, info: Dict[str, Any], now: datetime) -> Optional[Lead]:
    """Creates or updates the Lead with the consent record, and links it to the recipient."""
    phone = info["phone"]
    lead = db.query(Lead).filter(Lead.client_id == client_id, Lead.phone == phone).first()
    if not lead:
        lead = db.query(Lead).filter(Lead.client_id == client_id, Lead.phone.endswith(phone[-10:])).first()
    recipient = db.get(CampaignRecipient, recipient_id)
    if not lead:
        lead = Lead(client_id=client_id, name=info.get("name") or "Website lead", phone=phone,
                    lead_source=info.get("source") or "website")
        db.add(lead)
    elif info.get("name") and lead.name in (None, "", "Website lead"):
        lead.name = info["name"]
    lead.consent_given = True
    lead.consent_at = now
    lead.consent_source = info.get("source") or "website"
    if recipient is not None:
        lead.meta = {**(lead.meta or {}), "last_form": recipient.variables or {}}
    db.flush()
    if recipient is not None:
        recipient.lead_id = lead.id
    db.commit()
    return lead


def process_lead(db: Session, ctx: KeyContext, accepted: Dict[str, Any],
                 dial: Callable[..., Call] = place_outbound_call) -> Optional[str]:
    """Runs after the 202: dial first (speed matters), then record the lead and key usage."""
    t0 = time.perf_counter()
    result = None
    if accepted.get("dial_now"):
        try:
            result = instant_dial(db, accepted["recipient_id"], dial=dial)
            logger.info(f"Instant lead {accepted['recipient_id']}: {result} in {(time.perf_counter() - t0) * 1000:.0f} ms")
        except Exception:
            db.rollback()
            logger.exception(f"Instant dial failed for {accepted['recipient_id']}; the dialer will retry")
    now = campaign_svc.utcnow()
    try:
        record_lead(db, ctx.client_id, accepted["recipient_id"], accepted, now)
        key = db.get(ApiKey, ctx.key_id)
        if key and (not key.last_used_at or now - key.last_used_at > timedelta(minutes=1)):
            key.last_used_at = now
            db.commit()
    except Exception:
        db.rollback()
        logger.exception(f"Could not record lead for {accepted['recipient_id']}")
    return result


def process_lead_job(session_factory, ctx: KeyContext, accepted: Dict[str, Any],
                     dial: Callable[..., Call] = place_outbound_call) -> Optional[str]:
    db = session_factory()
    try:
        return process_lead(db, ctx, accepted, dial)
    finally:
        db.close()
