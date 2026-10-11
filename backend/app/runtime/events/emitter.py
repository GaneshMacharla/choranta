import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy.orm import Session
from app.core.security import generate_unique_id
from app.models.runtime_event import RuntimeEvent
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.runtime.events.types import RuntimeEventType, RuntimeEventPayload

logger = logging.getLogger("choranta.runtime.events")

SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "jwt", "authorization", "credentials"}


def scrub_payload(data: Any) -> Any:
    """Recursively scrub any sensitive keys from event payloads."""
    if isinstance(data, dict):
        return {
            k: ("[REDACTED]" if k.lower() in SENSITIVE_KEYS else scrub_payload(v))
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [scrub_payload(item) for item in data]
    return data


class EventEmitter:
    """
    Standardized Runtime Event Emitter.
    Dispatches events to registered listeners and saves immutable event records to the database.
    """

    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self.event_repo = RuntimeEventRepository(db) if db else None
        self._listeners: List[Callable[[RuntimeEventPayload], None]] = []
        # When set, events are collected here instead of being committed one by one
        self._buffer: Optional[List[RuntimeEvent]] = None

    def start_buffering(self) -> None:
        """Collect emitted events in memory so they can be persisted in a single transaction."""
        self._buffer = []

    def drain_buffer(self) -> List[RuntimeEvent]:
        """Stops buffering and returns the collected (unsaved) event records."""
        records = self._buffer or []
        self._buffer = None
        return records

    def subscribe(self, listener: Callable[[RuntimeEventPayload], None]) -> None:
        self._listeners.append(listener)

    def emit(
        self,
        event_type: RuntimeEventType,
        session_id: str,
        agent_id: str,
        agent_version_id: str,
        client_id: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> RuntimeEventPayload:
        event_id = generate_unique_id("evt", 12)
        safe_payload = scrub_payload(payload or {})

        event_obj = RuntimeEventPayload(
            event_id=event_id,
            session_id=session_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            client_id=client_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=safe_payload
        )

        # Notify in-memory subscribers
        for listener in self._listeners:
            try:
                listener(event_obj)
            except Exception as e:
                logger.error(f"Error in event listener for {event_type}: {e}")

        if not session_id:
            # runtime_events.session_id references runtime_sessions; events that happen before a
            # session exists (e.g. an outbound call that hasn't been answered) are log-only.
            pass
        elif self._buffer is not None:
            self._buffer.append(RuntimeEvent(
                id=event_id,
                session_id=session_id,
                client_id=client_id,
                agent_id=agent_id,
                agent_version_id=agent_version_id,
                event_type=event_type.value,
                payload_json=safe_payload,
                timestamp=event_obj.timestamp,
                created_at=event_obj.timestamp
            ))
        # Persist to database if db session is present
        elif self.event_repo:
            try:
                db_record = RuntimeEvent(
                    id=event_id,
                    session_id=session_id,
                    client_id=client_id,
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                    event_type=event_type.value,
                    payload_json=safe_payload,
                    timestamp=event_obj.timestamp
                )
                self.event_repo.create(db_record)
            except Exception as e:
                # Leave the caller's session usable: a failed flush otherwise poisons every later query
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.error(f"Failed to persist runtime event {event_id}: {e}")

        logger.info(
            f"[RUNTIME EVENT] {event_type.value} | session={session_id} | agent={agent_id}"
        )
        return event_obj
