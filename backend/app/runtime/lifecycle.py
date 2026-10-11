from enum import Enum
from typing import Set, Dict
from app.runtime.exceptions import InvalidSessionTransition


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    ENDING = "ENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Allowed state transitions graph
VALID_TRANSITIONS: Dict[SessionStatus, Set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.INITIALIZING, SessionStatus.FAILED},
    SessionStatus.INITIALIZING: {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.ACTIVE: {SessionStatus.ENDING, SessionStatus.FAILED},
    SessionStatus.ENDING: {SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.COMPLETED: set(),  # Terminal state
    SessionStatus.FAILED: set(),     # Terminal state
}


def validate_session_transition(current_status: str, target_status: str) -> None:
    try:
        curr = SessionStatus(current_status)
        target = SessionStatus(target_status)
    except ValueError:
        raise InvalidSessionTransition(current_status, target_status)

    allowed = VALID_TRANSITIONS.get(curr, set())
    if target not in allowed:
        raise InvalidSessionTransition(curr.value, target.value)
