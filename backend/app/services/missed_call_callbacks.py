"""
Calling back inbound callers turned away because every line was busy.

The caller hears that they'll be called back, and the campaign dispatcher calls them from the number they dialled as
soon as an outbound line is free: after instant leads, ahead of bulk campaigns. A callback that can't happen soon is
dropped rather than made long after the customer has moved on.

A caller turned away by the carrier itself never reaches us, so can't be called back; the line kept free for inbound
calls makes that less likely.
"""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.call import Call
from app.models.call_capacity import MissedCallCallback
from app.models.campaign import DoNotCallEntry
from app.models.lead import Lead
from app.models.phone_number import PhoneNumber
from app.services import billing, call_capacity, phone_numbers, subscriptions
from app.services.outbound_calls import OutboundCallError, place_outbound_call

logger = logging.getLogger("choranta.services.missed_call_callbacks")

PENDING_STATUSES = ("QUEUED", "DIALING", "CALLING")
FINISHED_CALL_STATUSES = ("COMPLETED", "FAILED", "TERMINATED", "CANCELLED")
ONE_CALLBACK_PER = timedelta(hours=24)
# A callback claimed for dialling whose dial never happened (e.g. a crash) goes back in the queue
CLAIM_TIMEOUT = timedelta(minutes=2)
# Same hours as bulk campaigns: the caller may have rung at 8:59, but nobody is called outside these
CALLING_ZONE = ZoneInfo("Asia/Kolkata")
EARLIEST_MIN, LATEST_MIN = 9 * 60, 21 * 60
# Errors that won't clear before the callback expires
SKIPPING_ERRORS = ("NO_BALANCE", "PLAN_EXPIRED", "NOT_READY", "CONFIG", "CALLER_UNAVAILABLE", "NOT_FOUND", "NOT_ALLOWED")


def _in_calling_hours(now: datetime) -> bool:
    local = now.replace(tzinfo=timezone.utc).astimezone(CALLING_ZONE)
    return EARLIEST_MIN <= local.hour * 60 + local.minute < LATEST_MIN


def _opted_out(db: Session, client_id: str, phone: str) -> bool:
    last_digits = phone[-10:]
    return bool(
        db.query(DoNotCallEntry.id).filter(DoNotCallEntry.client_id == client_id,
                                           DoNotCallEntry.phone.endswith(last_digits)).first()
        or db.query(Lead.id).filter(Lead.client_id == client_id, Lead.call_disposition == "DO_NOT_CALL",
                                    Lead.phone.endswith(last_digits)).first()
    )


def queue(db: Session, phone_record: PhoneNumber, caller_number: str, now: Optional[datetime] = None) -> bool:
    """Queues a callback for this caller. True only when one is on its way, so the caller can be told so."""
    now = now or subscriptions.utcnow()
    if not settings.MISSED_CALL_CALLBACKS_ENABLED or not _in_calling_hours(now):
        return False
    digits = "".join(c for c in caller_number or "" if c.isdigit())
    if len(digits) < 10 or _opted_out(db, phone_record.client_id, caller_number):
        return False

    recent = (
        db.query(MissedCallCallback)
        .filter(MissedCallCallback.client_id == phone_record.client_id,
                MissedCallCallback.caller_number == caller_number,
                MissedCallCallback.created_at >= now - ONE_CALLBACK_PER)
        .order_by(MissedCallCallback.created_at.desc())
        .first()
    )
    if recent:
        return recent.status in PENDING_STATUSES
    db.add(MissedCallCallback(client_id=phone_record.client_id, phone_number_id=phone_record.id,
                              agent_id=phone_record.agent_id, agent_version_id=phone_record.agent_version_id,
                              caller_number=caller_number, next_attempt_at=now, created_at=now))
    db.commit()
    call_capacity.count("callbacks_queued")
    return True


def _expiry(now: datetime) -> datetime:
    return now - timedelta(minutes=settings.MISSED_CALL_CALLBACK_EXPIRY_MIN)


def _retry_or_fail(callback: MissedCallCallback, error: str, now: datetime) -> None:
    callback.error = error
    if callback.attempts >= settings.MISSED_CALL_CALLBACK_MAX_ATTEMPTS:
        callback.status = "FAILED"
        return
    callback.status = "QUEUED"
    callback.next_attempt_at = now + timedelta(minutes=settings.MISSED_CALL_CALLBACK_RETRY_MIN)


def _settle(db: Session, now: datetime) -> None:
    """Records how placed callbacks went, and drops the ones whose time has passed."""
    for callback in db.query(MissedCallCallback).filter(MissedCallCallback.status == "CALLING").all():
        call = db.get(Call, callback.last_call_id) if callback.last_call_id else None
        if call is not None and call.status not in FINISHED_CALL_STATUSES:
            continue
        if call is not None and (call.answered_at or (call.duration_seconds or 0) > 0):
            callback.status = "CONNECTED"
            call_capacity.count("callbacks_connected")
        else:
            _retry_or_fail(callback, f"Not answered ({call.termination_reason})" if call else "Call record missing", now)

    db.query(MissedCallCallback).filter(
        MissedCallCallback.status == "DIALING", MissedCallCallback.updated_at <= now - CLAIM_TIMEOUT,
    ).update({"status": "QUEUED"}, synchronize_session=False)
    expired = db.query(MissedCallCallback).filter(
        MissedCallCallback.status == "QUEUED", MissedCallCallback.created_at <= _expiry(now),
    ).update({"status": "EXPIRED"}, synchronize_session=False)
    if expired:
        call_capacity.count("callbacks_expired", expired)
    db.commit()


def _dial(db: Session, callback: MissedCallCallback, now: datetime, dial: Callable[..., Call]) -> str:
    """Dials a claimed callback. Returns "placed", "skipped", "failed" or "stop" (no more dials this pass)."""
    number = db.get(PhoneNumber, callback.phone_number_id)
    if not number or number.status != "ACTIVE" or phone_numbers.blocked_reason(db, number):
        callback.status, callback.error = "SKIPPED", "The number can't place calls right now."
        db.commit()
        return "skipped"
    if _opted_out(db, callback.client_id, callback.caller_number):
        callback.status, callback.error = "SKIPPED", "On the do-not-call list"
        db.commit()
        return "skipped"
    try:
        call = dial(
            db,
            destination_number=callback.caller_number,
            agent_id=callback.agent_id,
            agent_version_id=callback.agent_version_id,
            caller_id=number.phone_number,
            custom_field=f"callback:{callback.id}",
            variables={},
            extra_metadata={"missed_call_callback_id": callback.id},
            caller_record=SimpleNamespace(id=number.id, phone_number=number.phone_number, provider=number.provider or "exotel"),
            client_id=callback.client_id,
        )
    except OutboundCallError as e:
        if e.code == "CONCURRENCY":  # lines filled up again: wait for the next pass, without using an attempt
            callback.status = "QUEUED"
            db.commit()
            return "stop"
        if e.code in SKIPPING_ERRORS:
            callback.status, callback.error = "SKIPPED", e.message
            db.commit()
            return "skipped"
        callback.attempts += 1
        _retry_or_fail(callback, e.message, now)
        db.commit()
        return "failed"
    callback.attempts += 1
    callback.status = "CALLING"
    callback.last_call_id = call.id
    db.commit()
    return "placed"


def run_due(db: Session, now: Optional[datetime] = None, dial: Callable[..., Call] = place_outbound_call) -> int:
    """One pass: settles placed callbacks, then calls waiting people while lines are free. Returns the calls placed."""
    now = now or subscriptions.utcnow()
    if not db.query(MissedCallCallback.id).filter(MissedCallCallback.status.in_(PENDING_STATUSES)).first():
        return 0
    _settle(db, now)
    if not _in_calling_hours(now):
        return 0
    placed = 0
    due = (
        db.query(MissedCallCallback)
        .filter(MissedCallCallback.status == "QUEUED", MissedCallCallback.next_attempt_at <= now)
        .order_by(MissedCallCallback.created_at)
        .limit(max(1, billing.outbound_headroom(db)))
        .all()
    )
    for callback in due:
        if billing.outbound_headroom(db) <= 0:
            break
        claimed = db.query(MissedCallCallback).filter(
            MissedCallCallback.id == callback.id, MissedCallCallback.status == "QUEUED",
        ).update({"status": "DIALING", "updated_at": now}, synchronize_session=False)
        db.commit()
        if not claimed:
            continue
        db.refresh(callback)
        result = _dial(db, callback, now, dial)
        if result == "placed":
            placed += 1
        elif result == "stop":
            break
    return placed
