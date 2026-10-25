"""
WhatsApp follow-ups: a client connects its own WhatsApp Business number (Meta Cloud API) and writes, per AI
employee, the message interested callers get after the call ("Hi {name}, thanks for your interest in {course}...").

Meta only lets a business start a chat with an approved template, so saving the message submits it as a
UTILITY template ({name} -> {{1}}...). Meta reports the review through the webhook (polled as a backup); the
last approved version keeps being sent until a newer one is approved.

Sending and billing live in services/whatsapp_followups.py.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import ChorantaException
from app.core.secrets_box import decrypt, encrypt
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.whatsapp import WhatsAppAccount, WhatsAppFollowup, WhatsAppMessage
from app.runtime.providers.messaging import (
    MessagingError, MessagingProvider, TemplateSpec, TemplateStatus, WhatsAppCredentials,
)
from app.runtime.providers.registry import default_registry
from app.services import notifications

logger = logging.getLogger("choranta.services.whatsapp")

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
NAME, CENTRE = "name", "centre"
MAX_MESSAGE_CHARS = 1024     # Meta's limit for a template body
LANGUAGES = {"en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam",
             "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi"}
SEND_WHEN = ("qualified", "interested", "callback")  # "qualified": the client's lead qualification says so
TEMPLATE_POLL_EVERY = timedelta(minutes=5)

# Shown in the editor's preview and sent to Meta as the template's example values
SAMPLE_VALUES = {NAME: "Priya", CENTRE: "your centre"}


class WhatsAppError(ChorantaException):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def provider() -> MessagingProvider:
    return default_registry.get_messaging("whatsapp")


# ---------------------------------------------------------------- account


def get_account(db: Session, client_id: str) -> Optional[WhatsAppAccount]:
    return db.query(WhatsAppAccount).filter(WhatsAppAccount.client_id == client_id).first()


def credentials(account: WhatsAppAccount) -> WhatsAppCredentials:
    return WhatsAppCredentials(waba_id=account.waba_id, phone_number_id=account.phone_number_id,
                               access_token=decrypt(account.access_token_enc))


def account_out(account: Optional[WhatsAppAccount]) -> Dict[str, Any]:
    if not account:
        return {"connected": False}
    return {"connected": True, "has_app_secret": bool(account.app_secret_enc), "status": account.status, "status_detail": account.status_detail,
            "waba_id": account.waba_id, "phone_number_id": account.phone_number_id,
            "display_phone": account.display_phone, "verified_name": account.verified_name,
            "verified_at": account.verified_at}


def connect_account(db: Session, client_id: str, waba_id: str, phone_number_id: str, access_token: str,
                    app_secret: Optional[str] = None) -> WhatsAppAccount:
    """
    Checks the ids and token with Meta, subscribes the WABA to the token's app (so its webhook reaches us), then
    saves them, secrets encrypted. Replaces an earlier connection.
    """
    waba_id, phone_number_id, access_token = waba_id.strip(), phone_number_id.strip(), access_token.strip()
    app_secret = (app_secret or "").strip() or None
    if not (waba_id.isdigit() and phone_number_id.isdigit()):
        raise WhatsAppError("The WhatsApp Business Account ID and Phone number ID are numbers; copy them from Meta's WhatsApp > API Setup page.")
    if not access_token:
        raise WhatsAppError("Paste the access token.")
    other = db.query(WhatsAppAccount).filter(WhatsAppAccount.phone_number_id == phone_number_id,
                                             WhatsAppAccount.client_id != client_id).first()
    if other:
        raise WhatsAppError("This WhatsApp number is already connected to another account.", 409)
    creds = WhatsAppCredentials(waba_id=waba_id, phone_number_id=phone_number_id, access_token=access_token)
    try:
        info = provider().verify_number(creds)
        provider().subscribe_app(creds)
    except MessagingError as exc:
        raise WhatsAppError(f"WhatsApp didn't accept these details: {exc}") from exc

    account = get_account(db, client_id)
    if account is None:
        account = WhatsAppAccount(client_id=client_id, waba_id=waba_id, phone_number_id=phone_number_id,
                                  access_token_enc="")
        db.add(account)
    elif account.waba_id != waba_id:
        # Templates belong to a WABA: every message must be approved again under the new one
        for followup in db.query(WhatsAppFollowup).filter(WhatsAppFollowup.client_id == client_id).all():
            followup.template_name = followup.template_status = followup.template_detail = None
            followup.approved_template_name = followup.approved_message = None
            followup.approved_placeholders = []
    account.waba_id, account.phone_number_id = waba_id, phone_number_id
    try:
        account.access_token_enc = encrypt(access_token)
        if app_secret:
            account.app_secret_enc = encrypt(app_secret)
    except ValueError as exc:
        db.rollback()
        raise WhatsAppError(f"WhatsApp can't be connected right now: {exc} Please contact Choranta support.", 503) from exc
    account.display_phone = info.get("display_phone")
    account.verified_name = info.get("verified_name")
    account.status, account.status_detail = "ACTIVE", None
    account.verified_at = utcnow()
    db.commit()
    submit_unsent_templates(db, client_id)
    return account


def disconnect_account(db: Session, client_id: str) -> None:
    account = get_account(db, client_id)
    if account:
        db.delete(account)
    # Messages still waiting can't be sent without the number
    db.query(WhatsAppMessage).filter(
        WhatsAppMessage.client_id == client_id, WhatsAppMessage.status == "QUEUED",
    ).update({"status": "SKIPPED", "error": "WhatsApp was disconnected."}, synchronize_session=False)
    db.commit()


def webhook_secrets(db: Session, payload: Dict[str, Any]) -> List[str]:
    """
    App secrets that may have signed this webhook: those of the accounts it is about (read from the unverified
    body only to pick the secret), and Choranta's own app's.
    """
    from app.core.config import settings
    ids = set()
    entries = payload.get("entry") if isinstance(payload, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        ids.add(str(entry.get("id") or ""))
        for change in entry.get("changes") or []:
            ids.add(str(((change.get("value") or {}).get("metadata") or {}).get("phone_number_id") or ""))
    ids.discard("")
    secrets = []
    if ids:
        rows = db.query(WhatsAppAccount).filter(
            (WhatsAppAccount.waba_id.in_(ids)) | (WhatsAppAccount.phone_number_id.in_(ids))).all()
        for account in rows:
            if account.app_secret_enc:
                try:
                    secrets.append(decrypt(account.app_secret_enc))
                except ValueError:
                    pass
    if settings.WHATSAPP_APP_SECRET:
        secrets.append(settings.WHATSAPP_APP_SECRET)
    return secrets


def mark_account_invalid(db: Session, account: WhatsAppAccount, detail: str) -> None:
    """Meta rejected the token: stop sending and tell the client to reconnect (once)."""
    if account.status != "INVALID":
        notifications.notify(db, account.client_id, "WHATSAPP_DISCONNECTED", "WhatsApp needs reconnecting",
                             f"WhatsApp rejected your access token, so follow-up messages are paused. {detail}",
                             link="/portal/integrations", level="warning")
    account.status, account.status_detail = "INVALID", detail[:500]


# ---------------------------------------------------------------- the follow-up message


def latest_version(db: Session, agent_id: str) -> Optional[AgentVersion]:
    """The version calls run on: the newest published one, else the newest."""
    query = db.query(AgentVersion).filter(AgentVersion.agent_id == agent_id)
    return (query.filter(AgentVersion.status == "PUBLISHED").order_by(AgentVersion.version_number.desc()).first()
            or query.order_by(AgentVersion.version_number.desc()).first())


def available_placeholders(db: Session, agent_id: str) -> List[Dict[str, str]]:
    """What a message can include: the lead's name, the client's name, and the agent's call details."""
    out = [{"key": NAME, "label": "Lead's name"}, {"key": CENTRE, "label": "Your business name"}]
    version = latest_version(db, agent_id)
    variables = ((version.configuration_json or {}) if version else {}).get("variables") or {}
    seen = {NAME, CENTRE, "user_name", "lead_id"}
    for kind, items in (("From the call", variables.get("outputs") or []), ("Campaign detail", variables.get("inputs") or [])):
        for v in items:
            key = v.get("name") if isinstance(v, dict) else None
            if key and key not in seen and PLACEHOLDER.fullmatch("{" + key + "}"):
                seen.add(key)
                out.append({"key": key, "label": f"{kind}: {v.get('description') or key}"})
    return out


def to_template(message: str) -> Tuple[str, List[str]]:
    """'Hi {name}, about {course}' -> ('Hi {{1}}, about {{2}}', ['name', 'course'])."""
    keys: List[str] = []

    def number(match: re.Match) -> str:
        keys.append(match.group(1))
        return "{{" + str(len(keys)) + "}}"

    return PLACEHOLDER.sub(number, message), keys


def render(message: str, values: Dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), message)


def validate_message(db: Session, agent_id: str, message: str, button_text: Optional[str],
                     button_url: Optional[str]) -> None:
    text = (message or "").strip()
    if not text:
        raise WhatsAppError("Write the message to send.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise WhatsAppError(f"Keep the message under {MAX_MESSAGE_CHARS} characters.")
    known = {p["key"] for p in available_placeholders(db, agent_id)}
    unknown = sorted({k for k in PLACEHOLDER.findall(text) if k not in known})
    if unknown:
        raise WhatsAppError(f"Unknown placeholder(s): {', '.join('{' + k + '}' for k in unknown)}.")
    if PLACEHOLDER.match(text) or re.search(r"\{[a-zA-Z0-9_]+\}[\s.!?]*$", text):
        raise WhatsAppError("WhatsApp doesn't allow a message to start or end with a {placeholder}; add a word before or after it.")
    words, slots = len(PLACEHOLDER.sub("", text).split()), len(PLACEHOLDER.findall(text))
    if slots and words < slots * 2 + 1:
        raise WhatsAppError("Add more words around the placeholders; WhatsApp rejects messages that are mostly placeholders.")
    if button_url:
        if not re.match(r"^https://\S+$", button_url.strip()):
            raise WhatsAppError("The button link must start with https://")
        if not (button_text or "").strip():
            raise WhatsAppError("Give the button a label, e.g. 'View brochure'.")
        if len(button_text.strip()) > 25:
            raise WhatsAppError("Keep the button label to 25 characters.")


def get_followup(db: Session, client_id: str, agent_id: str) -> Optional[WhatsAppFollowup]:
    return db.query(WhatsAppFollowup).filter(WhatsAppFollowup.agent_id == agent_id,
                                             WhatsAppFollowup.client_id == client_id).first()


def own_agent(db: Session, client_id: str, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent or agent.client_id != client_id:
        raise WhatsAppError("AI employee not found.", 404)
    return agent


def save_followup(db: Session, client_id: str, agent_id: str, *, enabled: bool, message: str,
                  send_when: List[str], language: str = "en", button_text: Optional[str] = None,
                  button_url: Optional[str] = None) -> WhatsAppFollowup:
    own_agent(db, client_id, agent_id)
    message = (message or "").strip()
    button_text = (button_text or "").strip() or None
    button_url = (button_url or "").strip() or None
    if not button_url:
        button_text = None
    validate_message(db, agent_id, message, button_text, button_url)
    send_when = [s for s in SEND_WHEN if s in (send_when or [])]
    if not send_when:
        raise WhatsAppError("Choose when to send the message.")
    if language not in LANGUAGES:
        raise WhatsAppError("Choose the message's language.")

    followup = get_followup(db, client_id, agent_id)
    if followup is None:
        followup = WhatsAppFollowup(client_id=client_id, agent_id=agent_id, message=message, version=0,
                                    template_placeholders=[], approved_placeholders=[])
        db.add(followup)
        changed = True
    else:
        changed = (followup.message, followup.language, followup.button_text, followup.button_url) != (
            message, language, button_text, button_url)
    followup.enabled, followup.send_when = enabled, send_when
    followup.message, followup.language = message, language
    followup.button_text, followup.button_url = button_text, button_url
    db.commit()
    if changed or followup.template_status in (None, "REJECTED", "ERROR"):
        submit_template(db, followup)
    return followup


def _template_name(followup: WhatsAppFollowup) -> str:
    """Lowercase letters, digits and underscores, unique per WABA: chr_<agent>_v<n>."""
    agent = re.sub(r"[^a-z0-9]+", "_", followup.agent_id.lower()).strip("_")
    return f"chr_{agent}_v{followup.version}"


def submit_template(db: Session, followup: WhatsAppFollowup) -> None:
    """Submits the current message for Meta's approval. Without a connected number it waits for one."""
    account = get_account(db, followup.client_id)
    if not account or account.status != "ACTIVE":
        followup.template_status = None
        followup.template_detail = "Connect your WhatsApp Business number to submit this message."
        db.commit()
        return
    body, keys = to_template(followup.message)
    followup.version = (followup.version or 0) + 1
    name = _template_name(followup)
    spec = TemplateSpec(name=name, language=followup.language, body=body,
                        examples=[SAMPLE_VALUES.get(k, k.replace("_", " ")) for k in keys],
                        button_text=followup.button_text, button_url=followup.button_url)
    followup.template_name, followup.template_placeholders = name, keys
    try:
        result = provider().submit_template(credentials(account), spec)
    except MessagingError as exc:
        if exc.auth:
            mark_account_invalid(db, account, str(exc))
        followup.template_status, followup.template_detail = "ERROR", f"WhatsApp refused the message: {exc}"[:1000]
        db.commit()
        return
    except ValueError as exc:  # token can't be decrypted
        followup.template_status, followup.template_detail = "ERROR", str(exc)
        db.commit()
        return
    followup.template_status, followup.template_detail = "PENDING", None
    db.commit()
    apply_template_status(db, followup, result)


def submit_unsent_templates(db: Session, client_id: str) -> None:
    """After connecting: submits messages written before the number was connected."""
    for followup in db.query(WhatsAppFollowup).filter(WhatsAppFollowup.client_id == client_id,
                                                      WhatsAppFollowup.template_status.is_(None)).all():
        submit_template(db, followup)


def apply_template_status(db: Session, followup: WhatsAppFollowup, status: TemplateStatus) -> None:
    """Records Meta's review of the latest submitted version; an approved one becomes the one that is sent."""
    if status.name != followup.template_name:
        if status.name == followup.approved_template_name and status.category:
            followup.approved_category = status.category.upper()
            db.commit()
        return
    state = (status.status or "").upper()
    if state == "APPROVED":
        followup.template_status, followup.template_detail = "APPROVED", None
        followup.approved_template_name = followup.template_name
        followup.approved_message = followup.message
        followup.approved_placeholders = list(followup.template_placeholders or [])
        followup.approved_language = followup.language
        followup.approved_category = (status.category or "UTILITY").upper()
    elif state == "REJECTED":
        was = followup.template_status
        followup.template_status = "REJECTED"
        followup.template_detail = _rejection_text(status.reason)
        if was != "REJECTED":
            agent = db.get(Agent, followup.agent_id)
            notifications.notify(db, followup.client_id, "WHATSAPP_REJECTED", "WhatsApp rejected a follow-up message",
                                 f"{agent.name if agent else 'Your AI employee'}'s message: {followup.template_detail}",
                                 link="/portal/integrations", level="warning")
    elif state in ("PAUSED", "DISABLED"):
        # Meta won't deliver it any more: stop sending until a new version is approved
        followup.template_status = "REJECTED"
        followup.template_detail = f"WhatsApp {state.lower()} this message (often after people reported or blocked it). Edit and save it to submit a new version."
        if followup.approved_template_name == followup.template_name:
            followup.approved_template_name = None
    elif state == "PENDING":
        followup.template_status = "PENDING"
    followup.updated_at = utcnow()
    db.commit()


_REJECTIONS = {
    "INVALID_FORMAT": "the message's format isn't allowed (check the placeholders and the button link).",
    "PROMOTIONAL": "it reads like an advert. Keep it to the details the lead asked for.",
    "TAG_CONTENT_MISMATCH": "the content doesn't match a follow-up message.",
    "SCAM": "it looks misleading to WhatsApp.",
    "ABUSIVE_CONTENT": "it was flagged as abusive.",
}


def _rejection_text(reason: Optional[str]) -> str:
    key = (reason or "").upper()
    return "Rejected: " + _REJECTIONS.get(key, (reason or "no reason given").replace("_", " ").lower() + ".") + \
        " Edit the message and save it to submit again."


def refresh_pending_templates(db: Session, now: Optional[datetime] = None) -> None:
    """Backup for the webhook: asks Meta about messages still waiting for review, every few minutes each."""
    now = now or utcnow()
    pending = db.query(WhatsAppFollowup).filter(
        WhatsAppFollowup.template_status == "PENDING", WhatsAppFollowup.updated_at <= now - TEMPLATE_POLL_EVERY,
    ).limit(20).all()
    for followup in pending:
        account = get_account(db, followup.client_id)
        if not account or account.status != "ACTIVE":
            continue
        try:
            status = provider().template_status(credentials(account), followup.template_name)
        except (MessagingError, ValueError) as exc:
            logger.warning(f"Couldn't check WhatsApp template {followup.template_name}: {exc}")
            status = None
        if status:
            apply_template_status(db, followup, status)
        else:
            followup.updated_at = now
            db.commit()


def followup_out(db: Session, agent: Agent, followup: Optional[WhatsAppFollowup]) -> Dict[str, Any]:
    placeholders = available_placeholders(db, agent.id)
    base: Dict[str, Any] = {"agent_id": agent.id, "agent_name": agent.name, "placeholders": placeholders,
                            "languages": [{"code": k, "label": v} for k, v in LANGUAGES.items()]}
    if not followup:
        return {**base, "configured": False, "enabled": False, "message": "", "language": "en",
                "send_when": ["qualified"], "button_text": None, "button_url": None,
                "template_status": None, "template_detail": None, "sending_version": False}
    return {**base, "configured": True, "enabled": followup.enabled, "message": followup.message,
            "language": followup.language, "send_when": followup.send_when or ["qualified"],
            "button_text": followup.button_text, "button_url": followup.button_url,
            "template_status": followup.template_status, "template_detail": followup.template_detail,
            # An earlier approved version is sent while the latest one is reviewed
            "sending_version": bool(followup.approved_template_name),
            "sending_latest": bool(followup.approved_template_name) and followup.approved_template_name == followup.template_name,
            "updated_at": followup.updated_at}


def prompt_line(db: Session, agent_id: Optional[str]) -> str:
    """What the agent is told when its interested callers get a WhatsApp message after the call."""
    if not agent_id:
        return ""
    followup = db.query(WhatsAppFollowup).filter(WhatsAppFollowup.agent_id == agent_id).first()
    if not followup or not followup.enabled or not followup.approved_template_name:
        return ""
    account = get_account(db, followup.client_id)
    if not account or account.status != "ACTIVE":
        return ""
    return ("\n\nWhatsApp follow-up: callers who are interested usually get a WhatsApp message with the details "
            "after this call. When a caller is interested, tell them you'll send the details on WhatsApp to this number. "
            "This replaces any earlier rule against promising WhatsApp; still don't promise SMS, email or anything else.")
