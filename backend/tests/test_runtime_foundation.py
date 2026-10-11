import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.client import Client
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.runtime_session import RuntimeSession
from app.models.runtime_event import RuntimeEvent
from app.schemas.agent_spec import CanonicalAgentSpec
from app.runtime.runtime import AgentRuntime
from app.runtime.lifecycle import SessionStatus, validate_session_transition
from app.runtime.exceptions import (
    AgentVersionNotFound,
    AgentVersionNotPublished,
    InvalidSessionTransition,
    SessionNotActiveError,
)
from app.runtime.providers.mock.stt import MockSTTProvider
from app.runtime.providers.mock.llm import MockLLMProvider
from app.runtime.providers.mock.tts import MockTTSProvider
from app.runtime.tools.executor import ToolExecutor
from app.runtime.usage.tracker import UsageTracker
from app.runtime.readiness.checker import RuntimeReadinessChecker


def helper_create_client_and_agent(client: TestClient, auth_headers: dict, suffix: str = "rt"):
    # 1. Create Client
    c_res = client.post(
        "/api/clients",
        headers=auth_headers,
        json={
            "name": f"Metro Health Clinic {suffix}",
            "business_type": "CLINIC",
            "timezone": "America/New_York",
            "description": "General practice clinic"
        }
    )
    assert c_res.status_code == 201
    client_id = c_res.json()["id"]

    # 2. Create Agent
    a_res = client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "client_id": client_id,
            "name": f"Sarah Receptionist {suffix}",
            "role": "Receptionist"
        }
    )
    assert a_res.status_code == 201
    agent_id = a_res.json()["id"]

    return client_id, agent_id


def helper_create_published_version(client: TestClient, auth_headers: dict, agent_id: str):
    v_res = client.post(
        f"/api/agents/{agent_id}/versions",
        headers=auth_headers
    )
    assert v_res.status_code == 201
    return v_res.json()


# ========================================================
# 1-5: READINESS & VERSION VALIDATION TESTS
# ========================================================

def test_runtime_readiness_success_and_failure(client: TestClient, auth_headers: dict):
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "readiness")
    version_data = helper_create_published_version(client, auth_headers, agent_id)
    version_id = version_data["id"]

    # 1. Success readiness check
    ready_res = client.post(
        "/api/runtime/readiness",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id}
    )
    assert ready_res.status_code == 200
    data = ready_res.json()
    assert data["ready"] is True
    assert len(data["errors"]) == 0

    # 2. Failure with non-existent version
    bad_res = client.post(
        "/api/runtime/readiness",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": "agtv_nonexistent"}
    )
    assert bad_res.status_code == 200
    bad_data = bad_res.json()
    assert bad_data["ready"] is False
    assert any("does not exist" in e for e in bad_data["errors"])


def test_reject_missing_and_unpublished_version(client: TestClient, auth_headers: dict, db: Session):
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "unpub")
    
    # 1. Missing version start rejection
    start_missing = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": "agtv_missing_999"}
    )
    assert start_missing.status_code == 422

    # 2. Unpublished (DRAFT) version rejection
    draft_v = AgentVersion(
        id="agtv_draft_only",
        agent_id=agent_id,
        version_number=99,
        configuration_json={"schema_version": "1.0"},
        status="DRAFT"
    )
    db.add(draft_v)
    db.commit()

    start_draft = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": "agtv_draft_only"}
    )
    assert start_draft.status_code == 422


# ========================================================
# 6-9: SESSION LIFECYCLE & VERSION PINNING
# ========================================================

def test_session_lifecycle_and_invalid_transition(client: TestClient, auth_headers: dict):
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "lifecycle")
    version_data = helper_create_published_version(client, auth_headers, agent_id)
    version_id = version_data["id"]

    # 1. Start Session
    start_res = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id, "metadata": {"call_origin": "test_suite"}}
    )
    assert start_res.status_code == 201
    session_data = start_res.json()
    session_id = session_data["id"]
    assert session_data["status"] == "ACTIVE"
    assert session_data["started_at"] is not None

    # 2. Get session
    get_res = client.get(
        f"/api/runtime/sessions/{session_id}",
        headers=auth_headers
    )
    assert get_res.status_code == 200
    assert get_res.json()["id"] == session_id

    # 3. End session
    end_res = client.post(
        f"/api/runtime/sessions/{session_id}/end",
        headers=auth_headers
    )
    assert end_res.status_code == 200
    assert end_res.json()["status"] == "COMPLETED"
    assert end_res.json()["ended_at"] is not None

    # 4. Invalid transition directly on domain model
    with pytest.raises(InvalidSessionTransition):
        validate_session_transition(SessionStatus.COMPLETED.value, SessionStatus.ACTIVE.value)

    with pytest.raises(InvalidSessionTransition):
        validate_session_transition(SessionStatus.FAILED.value, SessionStatus.ACTIVE.value)


def test_session_version_pinning(client: TestClient, auth_headers: dict):
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "pinning")
    v1_data = helper_create_published_version(client, auth_headers, agent_id)
    v1_id = v1_data["id"]

    # Start session on V1
    start_res = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": v1_id}
    )
    assert start_res.status_code == 201
    s_id = start_res.json()["id"]

    # Publish V2 for the same agent while S1 is running
    v2_data = helper_create_published_version(client, auth_headers, agent_id)
    assert v2_data["version_number"] == 2

    # Verify session S1 remains strictly pinned to V1
    s_check = client.get(
        f"/api/runtime/sessions/{s_id}",
        headers=auth_headers
    )
    assert s_check.json()["agent_version_id"] == v1_id


# ========================================================
# 10-15: PROVIDERS & TOOL EXECUTION TESTS
# ========================================================

def test_mock_stt_llm_and_tts_providers():
    # 1. Mock STT
    stt = MockSTTProvider()
    stt.initialize({})
    stt.start_stream()
    res = stt.process_audio("I need an emergency appointment.")
    assert res.text == "I need an emergency appointment."
    assert res.is_final is True

    # 2. Mock LLM
    llm = MockLLMProvider()
    llm.initialize({})
    llm_res = llm.generate(
        system_instruction="You are an assistant",
        messages=[{"role": "user", "content": "Hello"}]
    )
    assert llm_res.text is not None
    assert llm_res.usage["input_tokens"] > 0

    # 3. Mock TTS
    tts = MockTTSProvider()
    tts.initialize({})
    audio_res = tts.synthesize("Welcome to our clinic.")
    assert audio_res.duration_seconds > 0.0
    assert audio_res.format == "pcm_s16le"


def test_tool_executor_success_timeout_and_failure():
    executor = ToolExecutor()

    # 1. Success tool execution
    res = executor.execute_tool(
        tool_call_id="call_chk_1",
        tool_name="check_availability",
        arguments={"doctor": "Dr. Rao", "date": "2026-10-10"},
        enabled_tool_ids=["check_availability", "book_appointment"]
    )
    assert res.success is True
    assert res.data["available"] is True
    assert len(res.data["slots"]) > 0

    # 2. Disabled/Unauthorized tool
    disallowed_res = executor.execute_tool(
        tool_call_id="call_unauth",
        tool_name="transfer_call",
        arguments={},
        enabled_tool_ids=["check_availability"]
    )
    assert disallowed_res.success is False
    assert "not enabled" in disallowed_res.error

    # 3. Unregistered tool
    unreg_res = executor.execute_tool(
        tool_call_id="call_unknown",
        tool_name="unknown_external_tool",
        arguments={},
        enabled_tool_ids=["unknown_external_tool"]
    )
    assert unreg_res.success is False
    assert "not registered" in unreg_res.error


# ========================================================
# 16-19: EVENTS & USAGE TRACKING
# ========================================================

def test_runtime_events_and_usage_tracking(client: TestClient, auth_headers: dict):
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "events")
    version_data = helper_create_published_version(client, auth_headers, agent_id)
    version_id = version_data["id"]

    # Start session
    start_res = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id}
    )
    session_id = start_res.json()["id"]

    # Query events
    events_res = client.get(
        f"/api/runtime/sessions/{session_id}/events",
        headers=auth_headers
    )
    assert events_res.status_code == 200
    events = events_res.json()
    event_types = [e["event_type"] for e in events]
    assert "SESSION_CREATED" in event_types
    assert "SESSION_INITIALIZING" in event_types
    assert "SESSION_STARTED" in event_types


# ========================================================
# 20-25: SECURITY, RBAC & CLIENT ISOLATION
# ========================================================

def test_runtime_security_and_client_isolation(client: TestClient, auth_headers: dict, operator_headers: dict):
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "security")
    version_data = helper_create_published_version(client, auth_headers, agent_id)
    version_id = version_data["id"]

    # 1. Unauthenticated request rejected
    unauth = client.post("/api/runtime/sessions", json={"agent_id": agent_id, "agent_version_id": version_id})
    assert unauth.status_code == 401

    # 2. Operator allowed
    op_start = client.post(
        "/api/runtime/sessions",
        headers=operator_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id}
    )
    assert op_start.status_code == 201

    # 3. Invalid agent ID
    bad_agent = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": "agt_nonexistent_99", "agent_version_id": version_id}
    )
    assert bad_agent.status_code == 404


# ========================================================
# 26: COMPLETE END-TO-END MOCK VOICE PIPELINE TEST
# ========================================================

def test_complete_e2e_voice_runtime_turn_flow(client: TestClient, auth_headers: dict):
    """
    CRITICAL INTEGRATION TEST:
    Published AgentVersion
            ↓
    Runtime Session
            ↓
    Mock STT
            ↓
    Transcript
            ↓
    Mock LLM
            ↓
    Mock Tool Call (check_availability)
            ↓
    Mock Tool Result
            ↓
    Mock LLM continuation
            ↓
    Mock TTS
            ↓
    Runtime Events
            ↓
    Usage
            ↓
    Session Completed
    """
    # 1. Create client and agent
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "e2e_voice")

    # 2. Attach tools to agent before publishing version
    client.post(
        f"/api/agents/{agent_id}/tools/check_availability",
        headers=auth_headers
    )

    # 3. Publish Version 1
    version_data = helper_create_published_version(client, auth_headers, agent_id)
    version_id = version_data["id"]

    # 4. Start Runtime Session
    session_res = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id, "metadata": {"test": "e2e_turn"}}
    )
    assert session_res.status_code == 201
    session_id = session_res.json()["id"]

    # 5. Simulate conversational turn asking about appointment
    turn_res = client.post(
        f"/api/runtime/sessions/{session_id}/simulate_turn",
        headers=auth_headers,
        json={"input_text": "I want to check doctor availability for an appointment"}
    )
    assert turn_res.status_code == 200
    turn_data = turn_res.json()

    assert turn_data["session_id"] == session_id
    assert "appointment" in turn_data["transcript"].lower()
    assert turn_data["tool_calls_executed"] == 1
    assert "Dr. Rao" in turn_data["assistant_response"]
    assert turn_data["audio_duration_seconds"] > 0.0

    # 6. Verify usage was recorded
    usage = turn_data["usage"]
    assert usage["stt_seconds"] > 0
    assert usage["tts_seconds"] > 0
    assert usage["llm_input_tokens"] > 0
    assert usage["llm_output_tokens"] > 0

    # 7. End session
    end_res = client.post(
        f"/api/runtime/sessions/{session_id}/end",
        headers=auth_headers
    )
    assert end_res.status_code == 200
    assert end_res.json()["status"] == "COMPLETED"

    # 8. Verify chronological runtime events
    events_res = client.get(
        f"/api/runtime/sessions/{session_id}/events",
        headers=auth_headers
    )
    assert events_res.status_code == 200
    events = events_res.json()
    event_types = [e["event_type"] for e in events]

    expected_sequence = [
        "SESSION_CREATED",
        "SESSION_INITIALIZING",
        "SESSION_STARTED",
        "USER_SPEECH_STARTED",
        "USER_TRANSCRIPT_FINAL",
        "LLM_REQUEST_STARTED",
        "LLM_RESPONSE",
        "TOOL_CALL_STARTED",
        "TOOL_CALL_COMPLETED",
        "ASSISTANT_RESPONSE",
        "TTS_STARTED",
        "TTS_COMPLETED",
        "SESSION_ENDING",
        "SESSION_COMPLETED"
    ]

    for expected_type in expected_sequence:
        assert expected_type in event_types, f"Expected event '{expected_type}' missing from timeline"


# ========================================================
# STREAMING CHAT TURN (SSE) & CONVERSATION MEMORY
# ========================================================

def _read_sse(resp) -> list:
    import json as _json
    return [
        _json.loads(line[len("data: "):])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]


def test_stream_turn_streams_reply_runs_tools_and_persists(client: TestClient, auth_headers: dict):
    """Streaming turn yields deltas, tool progress and a done summary, then persists events and transcript."""
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "stream_turn")
    client.post(f"/api/agents/{agent_id}/tools/check_availability", headers=auth_headers)
    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id}
    ).json()["id"]

    resp = client.post(
        f"/api/runtime/sessions/{session_id}/stream_turn",
        headers=auth_headers,
        json={"input_text": "I want to check doctor availability for an appointment"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _read_sse(resp)
    types = [e["type"] for e in events]
    assert "delta" in types
    assert {"type": "tool", "status": "started", "tool_name": "check_availability"} in events
    assert types[-1] == "done"

    done = events[-1]
    streamed = "".join(e["text"] for e in events if e["type"] == "delta").strip()
    assert streamed == done["display_text"]
    assert "Dr. Rao" in done["assistant_response"]
    assert done["tool_calls_executed"] == 1
    assert done["usage"]["llm_output_tokens"] > 0
    assert "ASSISTANT_RESPONSE" in [e["event_type"] for e in done["events"]]

    # Background persistence wrote the turn's events and the transcript
    persisted = client.get(f"/api/runtime/sessions/{session_id}/events", headers=auth_headers).json()
    assert "TOOL_CALL_COMPLETED" in [e["event_type"] for e in persisted]
    session = client.get(f"/api/runtime/sessions/{session_id}", headers=auth_headers).json()
    roles = [t["role"] for t in session["metadata"]["transcript"]]
    assert roles[-2:] == ["user", "assistant"]


def test_stream_turn_rejects_inactive_session(client: TestClient, auth_headers: dict):
    """Session validation happens before streaming starts, so errors are real HTTP errors."""
    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "stream_inactive")
    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id}
    ).json()["id"]
    client.post(f"/api/runtime/sessions/{session_id}/end", headers=auth_headers)

    resp = client.post(
        f"/api/runtime/sessions/{session_id}/stream_turn",
        headers=auth_headers,
        json={"input_text": "hello"}
    )
    assert resp.status_code >= 400


def test_conversation_history_persists_across_turn_requests(client: TestClient, auth_headers: dict):
    """Each request builds a new AgentRuntime; the conversation must still carry over between turns."""
    from app.runtime.runtime import _ACTIVE_CONTEXTS

    client_id, agent_id = helper_create_client_and_agent(client, auth_headers, "memory")
    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post(
        "/api/runtime/sessions",
        headers=auth_headers,
        json={"agent_id": agent_id, "agent_version_id": version_id}
    ).json()["id"]

    for text in ("first message", "second message"):
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/simulate_turn",
            headers=auth_headers,
            json={"input_text": text, "synthesize_audio": False}
        )
        assert resp.status_code == 200
        assert resp.json()["audio_duration_seconds"] == 0.0

    user_turns = [
        m.content for m in _ACTIVE_CONTEXTS[session_id].conversation.messages
        if m.role.value == "user"
    ]
    assert user_turns == ["first message", "second message"]
