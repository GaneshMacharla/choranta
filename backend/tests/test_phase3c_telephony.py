import asyncio
import io
import json
import base64
import audioop
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, generate_unique_id
from app.models.client import Client
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.phone_number import PhoneNumber
from app.models.call import Call
from app.models.user import User
from app.models.runtime_session import RuntimeSession
from app.runtime.providers.telephony.exotel import ExotelTelephonyProvider, normalize_exotel_number
from app.runtime.providers.telephony.mock import MockTelephonyProvider
from app.runtime.providers.telephony.base import InboundCallPayload
from app.runtime.telephony.session import TelephonyMediaSession, active_telephony_calls
from app.schemas.agent_spec import (
    CanonicalAgentSpec,
    AgentMetaSpec,
    IdentitySpec,
    BusinessContextSpec,
    InstructionsSpec,
    ConversationSpec,
    LanguagesSpec,
    KnowledgeSpec,
    ToolsSpec,
    IntegrationsSpec,
    VoiceSpec,
    ProvidersSpec,
)


def _build_test_agent_spec(agent_id: str = "ag_test", name: str = "Telephony Receptionist") -> CanonicalAgentSpec:
    return CanonicalAgentSpec(
        schema_version="1.0",
        agent=AgentMetaSpec(id=agent_id, name=name, role="Receptionist"),
        identity=IdentitySpec(name=name, persona="Receptionist"),
        business_context=BusinessContextSpec(business_name="Choranta Health"),
        instructions=InstructionsSpec(primary_goal="Answer calls politely."),
        conversation=ConversationSpec(greeting="Thank you for calling Choranta Health. How may I direct your call?"),
        languages=LanguagesSpec(primary="en", supported=["en"]),
        knowledge=KnowledgeSpec(),
        tools=ToolsSpec(),
        integrations=IntegrationsSpec(),
        voice=VoiceSpec(provider="cartesia", voice_id="test_voice_123", speed=1.0),
        providers=ProvidersSpec(stt="cartesia", llm="gemini", tts="cartesia"),
    )


# ===========================================================================
# 1. AUDIO TRANSCODING & NORMALIZATION TESTS (PCM16 8kHz ↔ PCM16 16kHz)
# ===========================================================================

def test_telephony_audio_transcoding_inbound():
    """Verifies that inbound Exotel 8kHz 16-bit PCM is resampled to 16kHz 16-bit PCM."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    slin_input = b"\x00\x00" * 80  # 10ms at 8kHz (80 samples)

    pcm16_output = provider.normalize_audio_inbound(slin_input)
    # 10ms at 16kHz = ~160 samples (approx 320 bytes due to audioop ratecv filter window)
    assert abs(len(pcm16_output) - 320) <= 4


def test_telephony_audio_transcoding_outbound():
    """Verifies that outbound 16kHz 16-bit PCM is resampled to Exotel 8kHz 16-bit PCM."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    pcm16_input = b"\x00\x00" * 160  # 10ms at 16kHz (160 samples)

    slin_output = provider.normalize_audio_outbound(pcm16_input)
    assert len(slin_output) == 160


def test_telephony_audio_roundtrip_fidelity():
    """Verifies that transcoding roundtrip maintains valid structure and sample length."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    pcm_original = b"\x10\x20" * 800  # 800 samples = 1600 bytes
    slin = provider.normalize_audio_outbound(pcm_original)
    assert len(slin) == 800
    pcm_reconstructed = provider.normalize_audio_inbound(slin)
    assert abs(len(pcm_reconstructed) - 1600) <= 4


# ===========================================================================
# 2. EXOTEL WEBHOOK VALIDATION & RESPONSE GENERATION TESTS
# ===========================================================================

def test_exotel_webhook_token_validation():
    """Verifies shared-secret token validation for Exotel webhooks."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="s3cret_token")
    url = "https://choranta.example.com/api/telephony/exotel/inbound"

    assert provider.validate_webhook(url, {}, "s3cret_token") is True
    assert provider.validate_webhook(url, {}, "wrong_token") is False
    assert provider.validate_webhook(url, {}, "") is False


def test_exotel_inbound_parsing_normalizes_numbers():
    """Verifies Exotel national-format numbers are normalized to E.164."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    parsed = provider.parse_inbound_call_webhook({
        "CallSid": "exo_sid_123",
        "CallFrom": "09876543210",
        "CallTo": "08047112233",
    })
    assert parsed.provider_call_id == "exo_sid_123"
    assert parsed.caller_number == "+919876543210"
    assert parsed.destination_number == "+918047112233"
    assert parsed.provider == "exotel"

    assert normalize_exotel_number("+91 98765 43210") == "+919876543210"
    assert normalize_exotel_number("919876543210") == "+919876543210"
    assert normalize_exotel_number("9876543210") == "+919876543210"


def test_exotel_connect_response():
    """Verifies the Voicebot dynamic-URL response carries the media stream URL."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    resp = json.loads(provider.generate_connect_response("wss://api.choranta.com/ws/telephony/exotel/media", "exo_sid"))
    assert resp == {"url": "wss://api.choranta.com/ws/telephony/exotel/media"}


def test_exotel_reject_response():
    """Verifies the reject response carries no stream URL."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    resp = json.loads(provider.generate_reject_response("Unassigned number"))
    assert resp["url"] == ""
    assert resp["error"] == "Unassigned number"


def test_exotel_stream_protocol_messages():
    """Verifies Exotel AgentStream start parsing and outbound media/clear frames."""
    provider = ExotelTelephonyProvider(account_sid="mock_sid", webhook_secret="mock_secret")
    stream_sid, call_sid = provider.parse_stream_start({
        "event": "start",
        "stream_sid": "stream_abc",
        "start": {"stream_sid": "stream_abc", "call_sid": "exo_sid_1", "media_format": {"encoding": "base64", "sample_rate": "8000"}},
    })
    assert (stream_sid, call_sid) == ("stream_abc", "exo_sid_1")

    media = json.loads(provider.build_media_message("stream_abc", b"\x01\x02"))
    assert media["event"] == "media"
    assert media["stream_sid"] == "stream_abc"
    assert base64.b64decode(media["media"]["payload"]) == b"\x01\x02"

    clear = json.loads(provider.build_clear_message("stream_abc"))
    assert clear == {"event": "clear", "stream_sid": "stream_abc"}


def test_mock_telephony_provider():
    """Verifies deterministic MockTelephonyProvider for test environments."""
    mock_prov = MockTelephonyProvider("mock_telephony")
    assert mock_prov.provider_name == "mock_telephony"
    assert mock_prov.environment == "development/test"
    assert mock_prov.validate_webhook("http://test", {}, "any") is True

    parsed = mock_prov.parse_inbound_call_webhook({"From": "+1000", "To": "+1999", "CallSid": "CA999"})
    assert parsed.caller_number == "+1000"
    assert parsed.destination_number == "+1999"
    assert parsed.provider_call_id == "CA999"


# ===========================================================================
# 3. ENDPOINT INTEGRATION: INBOUND WEBHOOK & ROUTING
# ===========================================================================

@pytest.fixture
def telephony_setup(db: Session):
    """Creates a complete client, agent, immutable version, and configured phone number."""
    client_id = generate_unique_id("cli_")
    client = Client(id=client_id, name="Downtown Medical Clinic", business_type="CLINIC")
    db.add(client)
    db.commit()
    db.refresh(client)

    agent_id = generate_unique_id("age_")
    agent = Agent(id=agent_id, client_id=client.id, name="Clinic Inbound Receptionist", role="Receptionist", status="PUBLISHED")
    db.add(agent)
    db.commit()
    db.refresh(agent)

    spec = _build_test_agent_spec(agent.id, "Clinic Inbound Receptionist")
    version_id = generate_unique_id("agv_")
    version = AgentVersion(
        id=version_id,
        agent_id=agent.id,
        version_number=1,
        status="PUBLISHED",
        configuration_json=spec.model_dump(),
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    phone_number_id = generate_unique_id("phn_")
    phone_number = PhoneNumber(
        id=phone_number_id,
        client_id=client.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        phone_number="+15550001111",
        provider="exotel",
        provider_number_id="EXO_MOCK_123",
        status="ACTIVE",
    )
    db.add(phone_number)
    db.commit()
    db.refresh(phone_number)

    return {
        "client": client,
        "agent": agent,
        "version": version,
        "phone_number": phone_number,
    }


def test_inbound_webhook_routes_to_pinned_version(client: TestClient, telephony_setup, db: Session):
    """Verifies that an incoming phone call to a provisioned number routes to its pinned version."""
    pn = telephony_setup["phone_number"]

    resp = client.get(
        "/api/telephony/exotel/inbound",
        params={
            "CallFrom": "+15558889999",
            "CallTo": pn.phone_number,
            "CallSid": "CA_TEST_CALL_001",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "ws/telephony/exotel/media" in resp.json()["url"]

    # Verify a Call record was persisted with status RINGING
    call_rec = db.query(Call).filter(Call.provider_call_id == "CA_TEST_CALL_001").first()
    assert call_rec is not None
    assert call_rec.caller_number == "+15558889999"
    assert call_rec.destination_number == pn.phone_number
    assert call_rec.agent_id == telephony_setup["agent"].id
    assert call_rec.agent_version_id == telephony_setup["version"].id
    assert call_rec.status in ["RINGING", "ANSWERED"]


def test_inbound_webhook_rejects_unassigned_number(client: TestClient, db: Session):
    """Verifies that an unknown destination number returns an empty stream URL and does not fail."""
    resp = client.post(
        "/api/telephony/exotel/inbound",
        data={
            "CallFrom": "+15558889999",
            "CallTo": "+19999999999",  # Not in DB
            "CallSid": "CA_UNASSIGNED_002",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["url"] == ""

    call_rec = db.query(Call).filter(Call.provider_call_id == "CA_UNASSIGNED_002").first()
    assert call_rec is None


def test_inbound_webhook_idempotency(client: TestClient, telephony_setup, db: Session):
    """Verifies that repeated webhook requests with the same CallSid do not create duplicate rows."""
    pn = telephony_setup["phone_number"]

    params = {"CallFrom": "+15558889999", "CallTo": pn.phone_number, "CallSid": "CA_IDEMPOTENT_003"}
    resp1 = client.get("/api/telephony/exotel/inbound", params=params)
    resp2 = client.get("/api/telephony/exotel/inbound", params=params)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    calls = db.query(Call).filter(Call.provider_call_id == "CA_IDEMPOTENT_003").all()
    assert len(calls) == 1


def test_inbound_status_callback_updates_call(client: TestClient, telephony_setup, db: Session):
    """Verifies that Exotel status callback updates duration and marks call COMPLETED."""
    pn = telephony_setup["phone_number"]

    client.get(
        "/api/telephony/exotel/inbound",
        params={"CallFrom": "+15558889999", "CallTo": pn.phone_number, "CallSid": "CA_STATUS_TEST_004"},
    )

    status_resp = client.post(
        "/api/telephony/exotel/status",
        data={
            "CallSid": "CA_STATUS_TEST_004",
            "Status": "completed",
            "ConversationDuration": "42",
            "RecordingUrl": "https://recordings.exotel.com/mock_recording.mp3",
        },
    )

    assert status_resp.status_code == 200
    call_rec = db.query(Call).filter(Call.provider_call_id == "CA_STATUS_TEST_004").first()
    assert call_rec is not None
    assert call_rec.status == "COMPLETED"
    assert call_rec.duration_seconds == 42
    assert call_rec.recording_url == "https://recordings.exotel.com/mock_recording.mp3"


# ===========================================================================
# 4. TELEPHONY MANAGEMENT API (NUMBERS, CALLS, OVERVIEW)
# ===========================================================================

def test_telephony_overview_api(client: TestClient, auth_headers: dict, telephony_setup):
    """Verifies GET /api/telephony/overview returns system telephony metrics."""
    resp = client.get("/api/telephony/overview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_phone_numbers" in data
    assert "active_calls_now" in data
    assert "total_calls_today" in data
    assert data["total_phone_numbers"] >= 1


def test_phone_number_readiness_check(client: TestClient, auth_headers: dict, telephony_setup):
    """Verifies GET /api/telephony/numbers/{id}/readiness checks deployment health."""
    pn_id = telephony_setup["phone_number"].id
    resp = client.get(f"/api/telephony/numbers/{pn_id}/readiness", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "ready" in data
    assert data["agent_id"] == telephony_setup["agent"].id
    assert data["agent_version_id"] == telephony_setup["version"].id


def test_calls_history_listing_and_detail(client: TestClient, auth_headers: dict, telephony_setup, db: Session):
    """Verifies operators and admins can list calls and view detailed call info."""
    call_id = generate_unique_id("call_")
    call = Call(
        id=call_id,
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        caller_number="+15557778888",
        destination_number=telephony_setup["phone_number"].phone_number,
        direction="INBOUND",
        status="COMPLETED",
        duration_seconds=35,
        provider="exotel",
        provider_call_id="CA_HIST_001",
        transcript_summary="Hello! How can I help you today?",
    )
    db.add(call)
    db.commit()

    resp = client.get("/api/telephony/calls", headers=auth_headers)
    assert resp.status_code == 200
    calls_list = resp.json()
    assert len(calls_list) >= 1

    detail_resp = client.get(f"/api/telephony/calls/{call.id}", headers=auth_headers)
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["caller_number"] == "+15557778888"
    assert detail_data["transcript_summary"] == "Hello! How can I help you today?"


def test_outbound_call_endpoint_initiation(client: TestClient, telephony_setup, auth_headers, db: Session, outbound_settings):
    """Verifies that an outbound call can be triggered via POST /api/telephony/calls/outbound."""
    pn = telephony_setup["phone_number"]

    resp = client.post(
        "/api/telephony/calls/outbound",
        headers=auth_headers,
        json={
            "phone_number_id": pn.id,
            "destination_number": "+919876543210",
            "custom_field": "test_lead_123"
        }
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["direction"] == "OUTBOUND"
    assert data["status"] == "INITIATED"
    assert data["destination_number"] == "+919876543210"
    assert data["provider_call_id"].startswith("mock_call_")

    persisted = db.query(Call).filter(Call.provider_call_id == data["provider_call_id"]).first()
    assert persisted is not None
    assert persisted.direction == "OUTBOUND"


@pytest.fixture
def outbound_settings(monkeypatch):
    """Exotel outbound configuration independent of the developer's .env."""
    monkeypatch.setattr(settings, "TELEPHONY_BASE_URL", "https://choranta.example.com", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_CALLER_ID", "08047112233", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_FLOW_ID", "123456", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "choranta_test", raising=False)


def test_outbound_call_directly_as_agent(client: TestClient, telephony_setup, auth_headers, db: Session, outbound_settings):
    """A live call placed as an agent shows the client's own number; test calls use EXOTEL_CALLER_ID."""
    body = {
        "agent_id": telephony_setup["agent"].id,
        "agent_version_id": telephony_setup["version"].id,
        "destination_number": "09876543210",
    }
    live = client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body)
    assert live.status_code == 201, live.text
    assert live.json()["caller_number"] == telephony_setup["phone_number"].phone_number

    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json={**body, "is_test": True})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["direction"] == "OUTBOUND"
    assert data["phone_number_id"] is None
    assert data["caller_number"] == "08047112233"
    assert data["agent_version_id"] == telephony_setup["version"].id

    # Customer answers: Voicebot webhook routes by CallSid even though no PhoneNumber exists
    answered = client.get(
        "/api/telephony/exotel/inbound",
        params={"CallSid": data["provider_call_id"], "CallFrom": "09876543210", "CallTo": "08047112233"},
    )
    assert "ws/telephony/exotel/media" in answered.json()["url"]
    call = db.query(Call).filter(Call.id == data["id"]).first()
    db.refresh(call)
    assert call.status == "ANSWERED"
    assert call.runtime_session_id is not None


def test_outbound_call_validates_setup(client: TestClient, telephony_setup, auth_headers, outbound_settings, monkeypatch, db: Session):
    """Missing caller ID or a non-public base URL fails fast with an actionable error."""
    body = {
        "agent_id": telephony_setup["agent"].id,
        "agent_version_id": telephony_setup["version"].id,
        "destination_number": "09876543210",
    }

    monkeypatch.setattr(settings, "EXOTEL_CALLER_ID", None, raising=False)
    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json={**body, "is_test": True})
    assert resp.status_code == 400
    assert "EXOTEL_CALLER_ID" in resp.json()["detail"]

    # Live calls need the client's own active number
    telephony_setup["phone_number"].status = "INACTIVE"
    db.commit()
    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body)
    assert resp.status_code == 400
    assert "Buy a phone number" in resp.json()["detail"]
    telephony_setup["phone_number"].status = "ACTIVE"
    db.commit()

    monkeypatch.setattr(settings, "EXOTEL_CALLER_ID", "08047112233", raising=False)
    monkeypatch.setattr(settings, "TELEPHONY_BASE_URL", "http://127.0.0.1:8000", raising=False)
    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body)
    assert resp.status_code == 400
    assert "TELEPHONY_BASE_URL" in resp.json()["detail"]

    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json={"destination_number": "09876543210"})
    assert resp.status_code == 400


def test_outbound_call_answered_starts_agent_session(client: TestClient, telephony_setup, auth_headers, db: Session, outbound_settings):
    """When the customer answers, Exotel's Voicebot webhook must start a runtime session for the outbound call."""
    pn = telephony_setup["phone_number"]
    placed = client.post(
        "/api/telephony/calls/outbound",
        headers=auth_headers,
        json={"phone_number_id": pn.id, "destination_number": "+919876543210"}
    ).json()
    assert placed["runtime_session_id"] is None

    # Exotel reports the customer as CallFrom and the ExoPhone as CallTo; routing must
    # still find the outbound call by its CallSid.
    resp = client.get(
        "/api/telephony/exotel/inbound",
        params={"CallSid": placed["provider_call_id"], "CallFrom": "09876543210", "CallTo": "08000000000"},
    )
    assert resp.status_code == 200
    assert "ws/telephony/exotel/media" in resp.json()["url"]

    calls = db.query(Call).filter(Call.provider_call_id == placed["provider_call_id"]).all()
    assert len(calls) == 1
    db.refresh(calls[0])
    assert calls[0].direction == "OUTBOUND"
    assert calls[0].status == "ANSWERED"
    assert calls[0].runtime_session_id is not None



# ===========================================================================
# 5. WEBSOCKET MEDIA SESSION & BARGE-IN PROTOCOL TESTS
# ===========================================================================


@pytest.mark.asyncio
async def test_telephony_media_session_lifecycle(db: Session, telephony_setup):
    """
    Tests TelephonyMediaSession logic:
    - initialization marks Call ACTIVE
    - assistant barge-in sends Exotel clear frame
    - close marks Call COMPLETED
    """
    mock_ws = AsyncMock()
    mock_ws.send_text = AsyncMock()

    call_id = generate_unique_id("call_")
    call_rec = Call(
        id=call_id,
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        caller_number="+15551234567",
        destination_number=telephony_setup["phone_number"].phone_number,
        direction="INBOUND",
        status="RINGING",
        provider="exotel",
        provider_call_id="CA_SESSION_TEST_101",
    )
    db.add(call_rec)
    db.commit()
    db.refresh(call_rec)

    provider = MockTelephonyProvider("mock_telephony")
    session = TelephonyMediaSession(
        websocket=mock_ws,
        call_record=call_rec,
        stream_sid="MZ_STREAM_999",
        db=db,
        telephony_provider=provider,
    )

    # 1. Initialize session
    await session.initialize()
    db.refresh(call_rec)
    assert call_rec.status == "ACTIVE"
    assert session.stream_sid == "MZ_STREAM_999"

    # 2. Simulate barge-in / clear event
    session.assistant_speaking = True
    await session.handle_barge_in()
    assert session.assistant_speaking is False
    assert mock_ws.send_text.called
    clear_raw = mock_ws.send_text.call_args[0][0]
    clear_json = json.loads(clear_raw)
    assert clear_json["event"] == "clear"
    assert clear_json["stream_sid"] == "MZ_STREAM_999"

    # 3. Close session
    await session.close("caller_hangup")
    assert session.closed is True
    db.refresh(call_rec)
    assert call_rec.status in ["COMPLETED", "TERMINATED"]


# ===========================================================================
# 6. OPT-IN REAL TELEPHONY SMOKE TEST (SAFELY SKIPPED BY DEFAULT)
# ===========================================================================

@pytest.mark.skipif(
    not getattr(settings, "RUN_REAL_TELEPHONY_TESTS", False)
    or not getattr(settings, "EXOTEL_ACCOUNT_SID", None)
    or not getattr(settings, "EXOTEL_API_KEY", None)
    or not getattr(settings, "EXOTEL_API_TOKEN", None),
    reason="Real Telephony tests disabled or Exotel credentials missing (RUN_REAL_TELEPHONY_TESTS!=true)",
)
def test_real_exotel_account_readiness_smoke():
    """
    Opt-in smoke test verifying credentials against the live Exotel API.
    Only executed when RUN_REAL_TELEPHONY_TESTS=true and credentials exist in environment.
    """
    import httpx

    url = f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{settings.EXOTEL_ACCOUNT_SID}/Calls.json"
    resp = httpx.get(url, params={"PageSize": 1}, auth=(settings.EXOTEL_API_KEY, settings.EXOTEL_API_TOKEN), timeout=15)
    assert resp.status_code == 200


# ===========================================================================
# MEDIA STREAM AUTHENTICATION (Exotel may drop the ?token= query parameter)
# ===========================================================================

def _make_call(db: Session, telephony_setup, status: str, with_session: bool) -> Call:
    session_id = None
    if with_session:
        rs = RuntimeSession(
            id=generate_unique_id("ses_"),
            client_id=telephony_setup["client"].id,
            agent_id=telephony_setup["agent"].id,
            agent_version_id=telephony_setup["version"].id,
            status="ACTIVE",
            metadata_={},
            usage_json={},
        )
        db.add(rs)
        db.commit()
        session_id = rs.id
    call = Call(
        id=generate_unique_id("call_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        caller_number="+918008538015",
        destination_number="+914045209348",
        direction="OUTBOUND",
        status=status,
        provider="exotel",
        provider_call_id=generate_unique_id("exo_"),
        runtime_session_id=session_id,
    )
    db.add(call)
    db.commit()
    return call


def _start_frame(call: Call) -> str:
    return json.dumps({
        "event": "start",
        "stream_sid": "stream_1",
        "start": {"stream_sid": "stream_1", "call_sid": call.provider_call_id, "media_format": {"encoding": "base64", "sample_rate": "8000"}},
    })


def test_media_stream_without_token_accepted_for_routed_call(client: TestClient, telephony_setup, db: Session):
    """A tokenless stream is attached when its CallSid was routed through the token-checked webhook."""
    call = _make_call(db, telephony_setup, status="ANSWERED", with_session=True)
    with patch.object(TelephonyMediaSession, "initialize", new=AsyncMock()) as init, \
         patch.object(TelephonyMediaSession, "close", new=AsyncMock()):
        with client.websocket_connect("/ws/telephony/exotel/media") as ws:
            ws.send_text(json.dumps({"event": "connected"}))
            ws.send_text(_start_frame(call))
            ws.send_text(json.dumps({"event": "stop"}))
    assert init.await_count == 1


def test_media_stream_without_token_rejected_for_unrouted_call(client: TestClient, telephony_setup, db: Session):
    """A tokenless stream for a call that never went through the webhook is refused."""
    call = _make_call(db, telephony_setup, status="INITIATED", with_session=False)
    with patch.object(TelephonyMediaSession, "initialize", new=AsyncMock()) as init:
        with client.websocket_connect("/ws/telephony/exotel/media") as ws:
            ws.send_text(_start_frame(call))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
    assert init.await_count == 0


def test_media_stream_with_wrong_token_rejected(client: TestClient, telephony_setup, db: Session, monkeypatch):
    """An explicit but wrong token is still rejected outright."""
    monkeypatch.setattr(settings, "EXOTEL_WEBHOOK_SECRET", "right_secret", raising=False)
    from app.runtime.providers.registry import default_registry
    provider = default_registry.get_telephony("exotel")
    monkeypatch.setattr(provider, "validate_webhook", lambda url, params, sig: sig == "right_secret")
    with client.websocket_connect("/ws/telephony/exotel/media?token=wrong") as ws:
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


@pytest.mark.asyncio
async def test_media_session_turns_only_on_real_speech(db: Session, telephony_setup):
    """Silence/line noise must not trigger turns; one spoken sentence triggers exactly one turn."""
    import math
    import struct
    from app.runtime.providers.telephony.exotel import ExotelTelephonyProvider

    def frame_8k(amplitude: int) -> str:
        samples = struct.pack("<160h", *(int(amplitude * math.sin(2 * math.pi * 220 * i / 8000)) for i in range(160)))
        return base64.b64encode(samples).decode("ascii")  # 20 ms of Exotel 8 kHz PCM16

    call_rec = Call(
        id=generate_unique_id("call_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        caller_number="+15551234567",
        destination_number=telephony_setup["phone_number"].phone_number,
        direction="INBOUND",
        status="ACTIVE",
        provider="exotel",
        provider_call_id=generate_unique_id("exo_"),
    )
    db.add(call_rec)
    db.commit()

    session = TelephonyMediaSession(
        websocket=AsyncMock(),
        call_record=call_rec,
        stream_sid="stream_vad",
        db=db,
        telephony_provider=ExotelTelephonyProvider(webhook_secret="x"),
    )
    turns = []

    async def fake_turn(audio, t_start=None, t_end=None):
        turns.append(len(audio))

    session.execute_turn = fake_turn

    for _ in range(150):  # 3 s of silence and hiss
        await session.handle_media_payload(frame_8k(40))
    await asyncio.sleep(0)
    assert turns == []

    for _ in range(50):   # 1 s of speech
        await session.handle_media_payload(frame_8k(4000))
    for _ in range(50):   # 1 s of silence ends the turn
        await session.handle_media_payload(frame_8k(0))
    await asyncio.sleep(0)
    assert len(turns) == 1
