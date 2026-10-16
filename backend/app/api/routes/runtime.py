import json
import logging
from typing import Any, Dict, Iterator, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from app.api.deps import get_db, require_operator
from app.models.user import User
from app.models.agent import Agent
from app.models.runtime_session import RuntimeSession
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.schemas.runtime import (
    ReadinessCheckRequest,
    ReadinessCheckResponse,
    CreateRuntimeSessionRequest,
    RuntimeSessionResponse,
    SimulateTurnRequest,
    SimulateTurnResponse,
    RuntimeEventResponse
)
from app.runtime.runtime import AgentRuntime
from app.runtime.readiness.checker import RuntimeReadinessChecker

router = APIRouter(prefix="/runtime", tags=["Voice Runtime Foundation"])
logger = logging.getLogger("choranta.api.runtime")


def _event_response(e: Any) -> RuntimeEventResponse:
    return RuntimeEventResponse(
        id=e.id,
        session_id=e.session_id,
        client_id=e.client_id,
        agent_id=e.agent_id,
        agent_version_id=e.agent_version_id,
        event_type=e.event_type,
        payload=e.payload_json if isinstance(e.payload_json, dict) else {},
        timestamp=e.timestamp,
        created_at=e.created_at
    )


@router.get("/mode")
def get_runtime_mode(
    current_user: User = Depends(require_operator)
):
    """Return the server-selected provider mode; clients cannot override it."""
    from app.core.config import settings
    return {
        "mode": settings.RUNTIME_MODE,
        "mock": settings.RUNTIME_MODE == "mock",
        "external_provider_calls_enabled": settings.RUNTIME_MODE == "real",
        "label": "MOCK / SIMULATED" if settings.RUNTIME_MODE == "mock" else "REAL PROVIDERS",
        # *_PROVIDER_OVERRIDE settings: every call uses these instead of the agent's saved providers
        "provider_overrides": {
            kind: value
            for kind in ("stt", "llm", "tts")
            if (value := (getattr(settings, f"{kind.upper()}_PROVIDER_OVERRIDE", "") or "").strip().lower())
        },
    }


def format_session_response(s: RuntimeSession) -> RuntimeSessionResponse:
    return RuntimeSessionResponse(
        id=s.id,
        client_id=s.client_id,
        agent_id=s.agent_id,
        agent_version_id=s.agent_version_id,
        status=s.status,
        started_at=s.started_at,
        ended_at=s.ended_at,
        metadata=s.metadata_ if isinstance(s.metadata_, dict) else {},
        usage=s.usage_json if isinstance(s.usage_json, dict) else {},
        error_message=s.error_message,
        created_at=s.created_at,
        updated_at=s.updated_at
    )


@router.post("/readiness", response_model=ReadinessCheckResponse)
def check_runtime_readiness(
    req: ReadinessCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """
    Validate readiness of an agent version to execute in the voice runtime.
    Verifies version existence, published status, spec completeness, and provider availability.
    """
    checker = RuntimeReadinessChecker(db)
    result = checker.check(req.agent_id, req.agent_version_id)
    return ReadinessCheckResponse(
        ready=result["ready"],
        errors=result["errors"],
        warnings=result["warnings"],
        agent_id=result["agent_id"],
        version_id=result["version_id"],
        version_number=result.get("version_number")
    )


@router.post("/sessions", response_model=RuntimeSessionResponse, status_code=status.HTTP_201_CREATED)
def start_runtime_session(
    req: CreateRuntimeSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """
    Initiates an active voice runtime session with pinned immutable version.
    Rejects draft, unpublished, or invalid configurations.
    """
    # Enforce agent exists
    agent = db.query(Agent).filter(Agent.id == req.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' not found.")

    runtime = AgentRuntime(db)
    session_obj = runtime.start_session(
        agent_id=req.agent_id,
        agent_version_id=req.agent_version_id,
        metadata=req.metadata
    )
    return format_session_response(session_obj)


@router.get("/sessions/{session_id}", response_model=RuntimeSessionResponse)
def get_runtime_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Retrieve details and operational status for a runtime session."""
    repo = RuntimeSessionRepository(db)
    session_obj = repo.get_by_id(session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail=f"RuntimeSession '{session_id}' not found.")
    return format_session_response(session_obj)


@router.post("/sessions/{session_id}/end", response_model=RuntimeSessionResponse)
def end_runtime_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Gracefully conclude an active voice session, records duration and usage."""
    runtime = AgentRuntime(db)
    completed = runtime.end_session(session_id)
    return format_session_response(completed)


def _end_after_hang_up(bind: Any, session_id: str) -> None:
    """The AI employee hung up: end the session (in its own database session, after the turn is saved)."""
    db = Session(bind=bind)
    try:
        AgentRuntime(db).end_session(session_id)
    except Exception as e:
        logger.warning(f"Could not end session {session_id} after hang-up: {type(e).__name__}: {e}")
    finally:
        db.close()


@router.post("/sessions/{session_id}/simulate_turn", response_model=SimulateTurnResponse)
def simulate_session_turn(
    session_id: str,
    turn_req: SimulateTurnRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """
    Executes a conversational turn through the runtime pipeline:
    Input -> STT -> LLM -> Tool Calls -> (optional) TTS -> Events -> Usage.
    The turn's events and session state are written after the response is sent,
    keeping database round-trips off the reply latency.
    """
    runtime = AgentRuntime(db)
    result = runtime.process_turn(
        session_id,
        turn_req.input_text,
        synthesize_audio=turn_req.synthesize_audio,
        defer_persistence=True
    )
    background_tasks.add_task(result["persist"])
    if result.get("call_ended"):
        background_tasks.add_task(_end_after_hang_up, db.get_bind(), session_id)
    return SimulateTurnResponse(
        session_id=session_id,
        transcript=result["transcript"],
        assistant_response=result["assistant_response"],
        audio_duration_seconds=result["audio_duration_seconds"],
        tool_calls_executed=result["tool_calls_executed"],
        call_ended=result.get("call_ended", False),
        usage=result["usage"],
        events=[_event_response(e) for e in result["events"]]
    )


@router.post("/sessions/{session_id}/stream_turn")
def stream_session_turn(
    session_id: str,
    turn_req: SimulateTurnRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """
    Text chat turn streamed as Server-Sent Events. Each `data:` line is a JSON object:
    `delta` (assistant text as it is generated), `tool` (tool call progress),
    `done` (final reply, usage and runtime events) or `error`.
    The turn is persisted after the stream completes.
    """
    runtime = AgentRuntime(db)
    events_iter = runtime.stream_turn(session_id, turn_req.input_text or "")
    pending: Dict[str, Any] = {}
    bind = db.get_bind()

    def sse() -> Iterator[str]:
        try:
            for event in events_iter:
                if event["type"] == "done":
                    pending["persist"] = event.pop("persist")
                    pending["call_ended"] = event.get("call_ended", False)
                    event["events"] = [_event_response(e).model_dump(mode="json") for e in event["events"]]
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error(f"Streaming turn failed for session {session_id}: {type(e).__name__}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e) or type(e).__name__})}\n\n"

    def persist() -> None:
        if "persist" in pending:
            pending["persist"]()
        if pending.get("call_ended"):
            _end_after_hang_up(bind, session_id)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(persist)
    )


@router.get("/sessions/{session_id}/events", response_model=List[RuntimeEventResponse])
def get_session_events(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Retrieve immutable chronological event timeline for a session."""
    session_obj = RuntimeSessionRepository(db).get_by_id(session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail=f"RuntimeSession '{session_id}' not found.")

    events = RuntimeEventRepository(db).list_by_session(session_id)
    return [
        RuntimeEventResponse(
            id=e.id,
            session_id=e.session_id,
            client_id=e.client_id,
            agent_id=e.agent_id,
            agent_version_id=e.agent_version_id,
            event_type=e.event_type,
            payload=e.payload_json if isinstance(e.payload_json, dict) else {},
            timestamp=e.timestamp,
            created_at=e.created_at
        )
        for e in events
    ]


@router.get("/agents/{agent_id}/session-count")
def agent_session_count(agent_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_operator)):
    """How many test or live conversations this AI employee has had (the workspace's "tested" check)."""
    return {"sessions": db.query(RuntimeSession).filter(RuntimeSession.agent_id == agent_id).count()}
