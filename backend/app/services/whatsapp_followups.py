"""
Sending WhatsApp follow-ups (see services/whatsapp.py for accounts and messages).

After a call's results are extracted, queue_for_call() queues the agent's approved message when the caller
is a qualified lead (or showed the interest the client chose). The WhatsApp loop (main.py) sends due messages, retries temporary failures and bills each
sent message (Meta's price + profit %). Meta's webhook reports delivered / read / failed and the lead's
replies, which are kept for the portal; a STOP reply puts the number on the do-not-call list.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.campaign import CampaignRecipient, DoNotCallEntry
from app.models.client import Client
from app.models.lead import Lead
from app.models.whatsapp import WhatsAppAccount, WhatsAppFollowup, WhatsAppMessage
from app.runtime.providers.messaging import MessagingError, TemplateStatus
from app.services import billing, notifications
from app.services.campaigns import add_do_not_call, normalize_phone
from app.services.lead_qualification import is_qualified
from app.services.whatsapp import (
    CENTRE, NAME, apply_template_status, credentials, get_account, mark_account_invalid, provider, render, utcnow,
)

logger = logging.getLogger("choranta.services.whatsapp_followups")

RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15)]
SEND_BATCH = 50
STUCK_SENDING = timedelta(minutes=10)
MAX_PARAM_CHARS = 200
STOP_WORDS = {"stop", "unsubscribe", "stop all", "opt out", "optout", "cancel"}
# Status order, so a late "delivered" never overwrites "read"
_STATUS_RANK = {"QUEUED": 0, "SENDING": 1, "SENT": 2, "DELIVERED": 3, "READ": 4}


def _clean_param(value: Any) -> str:
    """Meta rejects template values that are empty or contain newlines, tabs or long runs of spaces."""
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v not in (None, ""))
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return text[:MAX_PARAM_CHARS]


def lead_phone(call: Call) -> Optional[str]:
    return normalize_phone(call.destination_number if call.direction == "OUTBOUND" else call.caller_number)


def _lead_for(db: Session, call: Call, phone: str) -> Optional[Lead]:
    metadata = call.metadata_ or {}
    lead_id = (metadata.get("variables") or {}).get("lead_id")
    if not lead_id and metadata.get("recipient_id"):
        recipient = db.get(CampaignRecipient, metadata["recipient_id"])
        lead_id = recipient.lead_id if recipient else None
    lead = db.get(Lead, lead_id) if lead_id else None
    if lead and lead.client_id == call.client_id:
        return lead
    return db.query(Lead).filter(Lead.client_id == call.client_id, Lead.phone.endswith(phone[-10:])) \
        .order_by(Lead.updated_at.desc()).first()


def _lead_name(db: Session, call: Call, lead: Optional[Lead]) -> str:
    metadata = call.metadata_ or {}
    name = (metadata.get("variables") or {}).get("user_name")
    if not name and metadata.get("recipient_id"):
        recipient = db.get(CampaignRecipient, metadata["recipient_id"])
        name = recipient.name if recipient else None
    name = name or (lead.name if lead else None)
    name = _clean_param(name)
    return name if name and name.lower() not in ("unknown", "caller", "-") else "there"


def template_values(db: Session, call: Call, keys: List[str], lead: Optional[Lead]) -> Dict[str, str]:
    """The value for each placeholder: the lead's name, the client's name, then the call's results and details."""
    metadata = call.metadata_ or {}
    outputs = metadata.get("outputs") if isinstance(metadata.get("outputs"), dict) else {}
    variables = metadata.get("variables") if isinstance(metadata.get("variables"), dict) else {}
    values: Dict[str, str] = {}
    for key in keys:
        if key == NAME:
            values[key] = _lead_name(db, call, lead)
        elif key == CENTRE:
            client = db.get(Client, call.client_id)
            values[key] = _clean_param(client.name if client else "") or "us"
        else:
            raw = outputs.get(key)
            if raw in (None, ""):
                raw = variables.get(key)
            values[key] = _clean_param(raw) or "-"
    return values


def _blocked(db: Session, client_id: str, phone: str) -> bool:
    if db.query(DoNotCallEntry.id).filter(DoNotCallEntry.client_id == client_id, DoNotCallEntry.phone == phone).first():
        return True
    return db.query(Lead.id).filter(Lead.client_id == client_id, Lead.call_disposition == "DO_NOT_CALL",
                                    Lead.phone.endswith(phone[-10:])).first() is not None


def wants_followup(db: Session, call: Call) -> bool:
    """Whether the call's agent sends WhatsApp follow-ups (so the call's interest must be worked out)."""
    return db.query(WhatsAppFollowup.id).filter(WhatsAppFollowup.agent_id == call.agent_id,
                                                WhatsAppFollowup.enabled.is_(True)).first() is not None


def queue_for_call(db: Session, call: Call, now: Optional[datetime] = None) -> Optional[WhatsAppMessage]:
    """Queues the agent's follow-up after an answered call whose caller was interested. Never raises."""
    try:
        return _queue_for_call(db, call, now or utcnow())
    except Exception as exc:
        logger.error(f"Couldn't queue WhatsApp follow-up for call {call.id}: {type(exc).__name__}: {exc}")
        db.rollback()
        return None


def _queue_for_call(db: Session, call: Call, now: datetime) -> Optional[WhatsAppMessage]:
    metadata = call.metadata_ or {}
    if metadata.get("is_test") or call.status != "COMPLETED":
        return None
    followup = db.query(WhatsAppFollowup).filter(WhatsAppFollowup.agent_id == call.agent_id).first()
    if not followup or not followup.enabled or not followup.approved_template_name:
        return None
    send_when = followup.send_when or []
    if metadata.get("interest") not in send_when and not ("qualified" in send_when and is_qualified(metadata)):
        return None
    account = get_account(db, call.client_id)
    if not account or account.status != "ACTIVE":
        return None
    phone = lead_phone(call)
    if not phone or _blocked(db, call.client_id, phone):
        return None
    if db.query(WhatsAppMessage.id).filter(WhatsAppMessage.call_id == call.id, WhatsAppMessage.direction == "OUT").first():
        return None

    lead = _lead_for(db, call, phone)
    keys = list(followup.approved_placeholders or [])
    values = template_values(db, call, keys, lead)
    message = WhatsAppMessage(
        client_id=call.client_id, agent_id=call.agent_id, call_id=call.id, lead_id=lead.id if lead else None,
        direction="OUT", phone=phone, template_name=followup.approved_template_name,
        language=followup.approved_language or followup.language, params=[values[k] for k in keys],
        body=render(followup.approved_message or followup.message, values),
        status="QUEUED", next_attempt_at=now,
    )
    db.add(message)
    try:
        db.commit()
    except IntegrityError:  # queued already by a concurrent extraction
        db.rollback()
        return None
    return message


# ---------------------------------------------------------------- sending


def _claim(db: Session, message: WhatsAppMessage) -> bool:
    claimed = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.id == message.id, WhatsAppMessage.status == "QUEUED",
    ).update({"status": "SENDING"}, synchronize_session=False)
    db.commit()
    if claimed:
        db.refresh(message)
    return bool(claimed)


def _category(db: Session, message: WhatsAppMessage) -> Optional[str]:
    followup = db.query(WhatsAppFollowup).filter(WhatsAppFollowup.agent_id == message.agent_id).first()
    return followup.approved_category if followup else None


def send_message(db: Session, message: WhatsAppMessage, now: datetime) -> None:
    account = get_account(db, message.client_id)
    if not account or account.status != "ACTIVE":
        message.status, message.error = "SKIPPED", "WhatsApp isn't connected."
        db.commit()
        return
    credits = billing.message_charge(db, _category(db, message))
    if not billing.can_afford_message(db, message.client_id, credits):
        message.status, message.error = "SKIPPED", "Not enough credits to send the message."
        notifications.notify(db, message.client_id, "WHATSAPP_NO_CREDITS", "A WhatsApp follow-up wasn't sent",
                             f"You're out of credits, so the follow-up to {message.phone} was skipped.",
                             link="/portal/billing", level="warning")
        db.commit()
        return
    message.attempts = (message.attempts or 0) + 1
    try:
        wa_id = provider().send_template(credentials(account), message.phone, message.template_name,
                                         message.language or "en", list(message.params or []))
    except (MessagingError, ValueError) as exc:
        _send_failed(db, message, account, exc, now)
        return
    message.wa_message_id, message.status, message.error = wa_id, "SENT", None
    message.sent_at, message.next_attempt_at = now, None
    message.charged_credits = billing.charge_message(db, message.client_id, message.id, credits,
                                                     f"WhatsApp follow-up to {message.phone}")
    db.commit()


def _send_failed(db: Session, message: WhatsAppMessage, account: WhatsAppAccount, exc: Exception, now: datetime) -> None:
    auth = isinstance(exc, ValueError) or getattr(exc, "auth", False)
    permanent = auth or getattr(exc, "permanent", True)
    message.error = str(exc)[:1000]
    if auth:
        mark_account_invalid(db, account, str(exc))
    if not permanent and message.attempts <= len(RETRY_DELAYS):
        message.status, message.next_attempt_at = "QUEUED", now + RETRY_DELAYS[message.attempts - 1]
    else:
        message.status, message.next_attempt_at = "FAILED", None
    db.commit()


def deliver_due_messages(db: Session, now: Optional[datetime] = None) -> int:
    """Sends queued follow-ups that are due; returns how many were attempted."""
    now = now or utcnow()
    # A message left SENDING by a stopped process may or may not have gone out: don't risk sending it twice
    db.query(WhatsAppMessage).filter(
        WhatsAppMessage.status == "SENDING", WhatsAppMessage.updated_at <= now - STUCK_SENDING,
    ).update({"status": "FAILED", "error": "Sending was interrupted; it may not have been delivered."},
             synchronize_session=False)
    db.commit()
    due = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.direction == "OUT", WhatsAppMessage.status == "QUEUED",
        or_(WhatsAppMessage.next_attempt_at.is_(None), WhatsAppMessage.next_attempt_at <= now),
    ).order_by(WhatsAppMessage.created_at).limit(SEND_BATCH).all()
    attempted = 0
    for message in due:
        if not _claim(db, message):
            continue
        attempted += 1
        try:
            send_message(db, message, now)
        except Exception as exc:
            db.rollback()
            logger.error(f"WhatsApp message {message.id} failed: {type(exc).__name__}: {exc}")
            db.query(WhatsAppMessage).filter(WhatsAppMessage.id == message.id).update(
                {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"[:1000]}, synchronize_session=False)
            db.commit()
    return attempted


def run_whatsapp_job(session_factory) -> None:
    from app.services.whatsapp import refresh_pending_templates
    db = session_factory()
    try:
        deliver_due_messages(db)
        refresh_pending_templates(db)
    finally:
        db.close()


# ---------------------------------------------------------------- Meta's webhook


def handle_webhook(db: Session, payload: Dict[str, Any]) -> None:
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            field, value = change.get("field"), change.get("value") or {}
            try:
                if field == "messages":
                    _handle_messages(db, value)
                elif field in ("message_template_status_update", "template_category_update"):
                    _handle_template_update(db, str(entry.get("id") or ""), field, value)
            except Exception as exc:
                db.rollback()
                logger.error(f"WhatsApp webhook {field} failed: {type(exc).__name__}: {exc}")


def _handle_messages(db: Session, value: Dict[str, Any]) -> None:
    for status in value.get("statuses") or []:
        message = db.query(WhatsAppMessage).filter(WhatsAppMessage.wa_message_id == status.get("id")).first()
        if not message:
            continue
        state = (status.get("status") or "").upper()
        if state == "FAILED":
            errors = status.get("errors") or [{}]
            detail = (errors[0].get("error_data") or {}).get("details") or errors[0].get("title") or "Not delivered"
            message.status, message.error = "FAILED", str(detail)[:1000]
        elif _STATUS_RANK.get(state, -1) > _STATUS_RANK.get(message.status, 99):
            message.status = state
    db.commit()

    phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
    incoming = value.get("messages") or []
    if not incoming or not phone_number_id:
        return
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.phone_number_id == str(phone_number_id)).first()
    if not account:
        return
    names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
    for item in incoming:
        if db.query(WhatsAppMessage.id).filter(WhatsAppMessage.wa_message_id == item.get("id")).first():
            continue  # Meta retries webhooks
        phone = normalize_phone("+" + str(item.get("from") or "")) or "+" + str(item.get("from") or "")
        text = _incoming_text(item)
        last_out = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.client_id == account.client_id, WhatsAppMessage.phone == phone,
            WhatsAppMessage.direction == "OUT",
        ).order_by(WhatsAppMessage.created_at.desc()).first()
        db.add(WhatsAppMessage(
            client_id=account.client_id, agent_id=last_out.agent_id if last_out else None,
            lead_id=last_out.lead_id if last_out else None, direction="IN", phone=phone, body=text,
            wa_message_id=item.get("id"), status="RECEIVED", params=[],
        ))
        who = names.get(item.get("from")) or phone
        opted_out = text.strip().lower().strip(".!") in STOP_WORDS
        notifications.notify(
            db, account.client_id, "WHATSAPP_REPLY",
            f"{who} opted out on WhatsApp" if opted_out else f"New WhatsApp reply from {who}",
            "They won't be called or messaged again." if opted_out else text[:200],
            link="/portal/calls", level="warning" if opted_out else "info",
        )
        db.commit()
        if opted_out:
            add_do_not_call(db, account.client_id, phone, source="whatsapp_opt_out", note="Replied STOP on WhatsApp")


def _incoming_text(item: Dict[str, Any]) -> str:
    kind = item.get("type")
    if kind == "text":
        return (item.get("text") or {}).get("body") or ""
    if kind == "button":
        return (item.get("button") or {}).get("text") or ""
    if kind == "interactive":
        inter = item.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return reply.get("title") or ""
    caption = (item.get(kind) or {}).get("caption") if isinstance(item.get(kind), dict) else None
    return caption or f"[{kind or 'message'}]"


def _handle_template_update(db: Session, waba_id: str, field: str, value: Dict[str, Any]) -> None:
    name = value.get("message_template_name")
    if not name:
        return
    accounts = db.query(WhatsAppAccount.client_id).filter(WhatsAppAccount.waba_id == waba_id).all()
    client_ids = [a for (a,) in accounts]
    if not client_ids:
        return
    followup = db.query(WhatsAppFollowup).filter(
        WhatsAppFollowup.client_id.in_(client_ids),
        or_(WhatsAppFollowup.template_name == name, WhatsAppFollowup.approved_template_name == name),
    ).first()
    if not followup:
        return
    if field == "template_category_update":
        # Meta moved the template to another category (e.g. UTILITY -> MARKETING), which changes its price
        category = value.get("new_category")
        if name == followup.approved_template_name and category:
            followup.approved_category = str(category).upper()
            db.commit()
        return
    apply_template_status(db, followup, TemplateStatus(
        name=name, status=value.get("event") or "", reason=value.get("reason"), language=value.get("message_template_language"),
    ))


# ---------------------------------------------------------------- portal


def message_out(m: WhatsAppMessage) -> Dict[str, Any]:
    return {"id": m.id, "direction": m.direction, "phone": m.phone, "body": m.body, "status": m.status,
            "error": m.error, "call_id": m.call_id, "lead_id": m.lead_id, "sent_at": m.sent_at,
            "created_at": m.created_at}


def thread_for_call(db: Session, client_id: str, call_id: str) -> List[Dict[str, Any]]:
    """The follow-up sent after the call and the lead's replies since."""
    sent = db.query(WhatsAppMessage).filter(WhatsAppMessage.client_id == client_id, WhatsAppMessage.call_id == call_id,
                                            WhatsAppMessage.direction == "OUT").first()
    if not sent:
        return []
    replies = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.client_id == client_id, WhatsAppMessage.phone == sent.phone,
        WhatsAppMessage.direction == "IN", WhatsAppMessage.created_at >= sent.created_at,
    ).order_by(WhatsAppMessage.created_at).limit(50).all()
    return [message_out(sent)] + [message_out(r) for r in replies]


def threads_for_calls(db: Session, client_id: str, call_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Per call: the follow-up's status and how many replies came back (for lists)."""
    if not call_ids:
        return {}
    sent = db.query(WhatsAppMessage).filter(WhatsAppMessage.client_id == client_id,
                                            WhatsAppMessage.call_id.in_(call_ids),
                                            WhatsAppMessage.direction == "OUT").all()
    out: Dict[str, Dict[str, Any]] = {}
    for m in sent:
        replies = db.query(WhatsAppMessage.id).filter(
            WhatsAppMessage.client_id == client_id, WhatsAppMessage.phone == m.phone,
            WhatsAppMessage.direction == "IN", WhatsAppMessage.created_at >= m.created_at,
        ).count()
        out[m.call_id] = {"status": m.status, "replies": replies}
    return out
