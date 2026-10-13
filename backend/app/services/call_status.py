"""
Applies a carrier's call status (completed, busy, no-answer, ...) to a Call record. Shared by the
Exotel status webhook and the mock environment, which ends simulated calls the same way.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.call import Call
from app.repositories.call_repository import CallRepository
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.services import phone_numbers

COMPLETED_STATUSES = ("completed", "answered")
FAILED_STATUSES = ("busy", "failed", "no-answer", "canceled", "cancelled")


def apply_call_status(
    db: Session,
    call_record: Call,
    call_status: str,
    call_duration: float = 0.0,
    recording_url: Optional[str] = None,
) -> None:
    call_repo = CallRepository(db)
    if call_duration > 0:
        call_record.duration_seconds = call_duration

    if recording_url:
        call_record.recording_url = recording_url

    now = datetime.now(timezone.utc)
    emitter = EventEmitter(db)

    if call_status in COMPLETED_STATUSES:
        call_record.status = "COMPLETED"
        call_record.ended_at = now
        call_repo.update(call_record)
        if (call_record.metadata_ or {}).get("number_test"):
            phone_numbers.record_test_result(db, call_record, connected=(call_duration or 0) > 0 or call_status == "answered",
                                             reason="NOT_ANSWERED")
        emitter.emit(
            RuntimeEventType.CALL_COMPLETED,
            session_id=call_record.runtime_session_id or "",
            agent_id=call_record.agent_id,
            agent_version_id=call_record.agent_version_id,
            client_id=call_record.client_id,
            payload={"call_id": call_record.id, "duration": call_duration}
        )
    elif call_status in FAILED_STATUSES:
        call_record.status = "FAILED"
        call_record.ended_at = now
        call_record.termination_reason = call_status
        call_repo.update(call_record)
        if (call_record.metadata_ or {}).get("number_test"):
            phone_numbers.record_test_result(db, call_record, connected=False, reason=call_status.upper())
        emitter.emit(
            RuntimeEventType.CALL_FAILED,
            session_id=call_record.runtime_session_id or "",
            agent_id=call_record.agent_id,
            agent_version_id=call_record.agent_version_id,
            client_id=call_record.client_id,
            payload={"call_id": call_record.id, "reason": call_status}
        )
    else:
        call_repo.update(call_record)
