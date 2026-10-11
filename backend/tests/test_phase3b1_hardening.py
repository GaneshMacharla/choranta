import os
import json
import time
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.websockets import WebSocketDisconnect
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.cartesia.stt import CartesiaSTTProvider, CartesiaSTTStreamingSession
from app.runtime.providers.cartesia.tts import CartesiaTTSProvider
from app.runtime.providers.gemini.llm import GeminiLLMProvider
from app.runtime.providers.mock.stt import MockSTTProvider, MockSTTStreamingSession
from app.runtime.providers.registry import ProviderRegistry
from app.api.routes.websocket_audio import _is_voice_energy, active_audio_sessions
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
    ProvidersSpec
)
from app.models.client import Client
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.runtime_session import RuntimeSession
from app.runtime.events.types import RuntimeEventType
from app.repositories.runtime_event_repository import RuntimeEventRepository


# ---------------------------------------------------------------------------
# 1. GEMINI SDK MIGRATION (google-genai) TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_async_generate_with_google_genai():
    """Verifies GeminiLLMProvider executes asynchronous generate_async with google-genai."""
    provider = GeminiLLMProvider(api_key="mock_gemini_key")

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_cand = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "Hello from Google GenAI!"
    mock_part.function_call = None
    mock_cand.content.parts = [mock_part]
    mock_resp.candidates = [mock_cand]
    mock_resp.usage_metadata.prompt_token_count = 12
    mock_resp.usage_metadata.candidates_token_count = 8

    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        provider.initialize({})

        result = await provider.generate_async(
            system_instruction="You are a clinical receptionist.",
            messages=[{"role": "user", "content": "Hello"}],
            available_tools=None
        )

        assert result.text == "Hello from Google GenAI!"
        assert result.finish_reason == "stop"
        assert result.usage["input_tokens"] == 12
        assert result.usage["output_tokens"] == 8


@pytest.mark.asyncio
async def test_gemini_async_tool_calling_with_google_genai():
    """Verifies GeminiLLMProvider extracts function calls via google-genai."""
    provider = GeminiLLMProvider(api_key="mock_gemini_key")

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_cand = MagicMock()
    mock_part = MagicMock()
    mock_part.text = None

    mock_fc = MagicMock()
    mock_fc.name = "check_availability"
    mock_fc.args = {"date": "2026-10-20", "service": "Dental Cleaning"}
    mock_part.function_call = mock_fc
    mock_cand.content.parts = [mock_part]

    mock_resp.candidates = [mock_cand]
    mock_resp.usage_metadata = None

    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        provider.initialize({})

        result = await provider.generate_async(
            system_instruction="You are a dental receptionist.",
            messages=[{"role": "user", "content": "Check cleaning on Oct 20"}],
            available_tools=[{"name": "check_availability"}]
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "check_availability"
        assert result.tool_calls[0].arguments["date"] == "2026-10-20"
        assert result.finish_reason == "tool_calls"


# ---------------------------------------------------------------------------
# 2. CARTESIA STT STREAMING & PARTIAL TRANSCRIPT TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cartesia_stt_streaming_session():
    """Verifies CartesiaSTTStreamingSession yields partial and final turn transcripts."""
    partials_received = []
    finals_received = []

    async def on_partial(text: str):
        partials_received.append(text)

    async def on_final(text: str):
        finals_received.append(text)

    # Simulated async event generator from Cartesia WebSocket
    class MockTurnUpdate:
        type = "turn_update"
        transcript = "Hello I would"

    class MockTurnEnd:
        type = "turn_end"
        transcript = "Hello I would like to schedule."

    async def mock_event_iterator():
        yield MockTurnUpdate()
        yield MockTurnEnd()

    mock_connection = AsyncMock()
    mock_connection.__aiter__ = lambda self: mock_event_iterator()
    mock_connection.send_raw = AsyncMock()
    mock_connection.close = AsyncMock()

    session = CartesiaSTTStreamingSession(
        connection=mock_connection,
        on_partial=on_partial,
        on_final=on_final
    )
    await session.start()

    # Stream audio frame
    sample_pcm = b"\x00\x02" * 320
    await session.send_audio(sample_pcm)
    mock_connection.send_raw.assert_called_with(sample_pcm)

    # Yield control to let event loop process the mock generator
    await asyncio.sleep(0.05)

    assert "Hello I would" in partials_received
    assert "Hello I would like to schedule." in finals_received

    final_res = await session.finish()
    assert final_res.text == "Hello I would like to schedule."
    assert final_res.is_final is True
    mock_connection.close.assert_called()


@pytest.mark.asyncio
async def test_mock_stt_streaming_session():
    """Verifies MockSTTStreamingSession emits progressive partial transcripts."""
    partials = []
    finals = []

    async def on_partial(t: str):
        partials.append(t)

    async def on_final(t: str):
        finals.append(t)

    provider = MockSTTProvider()
    provider.set_mock_transcript("Book doctor appointment now")

    stream = await provider.create_stream(on_partial=on_partial, on_final=on_final)

    # Sending 3 audio chunks
    await stream.send_audio(b"\x01\x00" * 160)
    await stream.send_audio(b"\x01\x00" * 160)
    await stream.send_audio(b"\x01\x00" * 160)

    assert len(partials) >= 3
    assert partials[0] == "Book"
    assert partials[1] == "Book doctor"
    assert partials[2] == "Book doctor appointment"

    res = await stream.finish()
    assert res.text == "Book doctor appointment now"
    assert len(finals) == 1
    assert finals[0] == "Book doctor appointment now"


# ---------------------------------------------------------------------------
# 3. BARGE-IN AUDIO DETECTION & VOICE ENERGY
# ---------------------------------------------------------------------------

def test_voice_energy_detection():
    """Verifies _is_voice_energy discriminates silence from active voice frames."""
    # Complete silence
    silence = b"\x00\x00" * 320
    assert _is_voice_energy(silence, threshold=600) is False

    # Low noise under threshold (amplitude 100)
    import struct
    low_noise = struct.pack("<320h", *([100] * 320))
    assert _is_voice_energy(low_noise, threshold=600) is False

    # High voice amplitude (amplitude 2000)
    loud_speech = struct.pack("<320h", *([2000] * 320))
    assert _is_voice_energy(loud_speech, threshold=600) is True


# ---------------------------------------------------------------------------
# 4. WEBSOCKET REALTIME AUDIO HARNESS & RESOURCE SAFETY
# ---------------------------------------------------------------------------

@pytest.fixture
def active_test_session(db):
    """Sets up a client, published agent version, and active session."""
    client = Client(
        id="cli_p3b1_harden",
        name="Phase 3B1 Clinic",
        business_type="Healthcare",
        status="ACTIVE"
    )
    db.add(client)

    agent = Agent(
        id="ag_p3b1_harden",
        client_id="cli_p3b1_harden",
        name="Receptionist",
        role="Clinic Receptionist",
        status="ACTIVE"
    )
    db.add(agent)

    canonical_spec = CanonicalAgentSpec(
        schema_version="1.0",
        agent=AgentMetaSpec(id="ag_p3b1_harden", name="Receptionist", role="Clinic Receptionist"),
        identity=IdentitySpec(name="Sarah", persona="Receptionist"),
        business_context=BusinessContextSpec(business_name="Phase 3B1 Clinic"),
        instructions=InstructionsSpec(primary_goal="Help patients schedule visits.", constraints=["Be concise"]),
        conversation=ConversationSpec(
            greeting="Hello, thank you for calling Phase 3B1 Clinic.",
            fallback_response="I can help you with scheduling."
        ),
        languages=LanguagesSpec(primary="en", supported=["en"]),
        knowledge=KnowledgeSpec(),
        tools=ToolsSpec(enabled=["check_availability"]),
        integrations=IntegrationsSpec(),
        voice=VoiceSpec(provider="cartesia", voice_id="test_voice", speed=1.0),
        providers=ProvidersSpec(stt="cartesia", llm="gemini", tts="cartesia")
    )

    version = AgentVersion(
        id="ver_p3b1_harden",
        agent_id="ag_p3b1_harden",
        version_number=1,
        status="PUBLISHED",
        configuration_json=canonical_spec.model_dump(),
        created_by="usr_admin"
    )
    db.add(version)

    runtime_session = RuntimeSession(
        id="sess_p3b1_harden",
        client_id="cli_p3b1_harden",
        agent_id="ag_p3b1_harden",
        agent_version_id="ver_p3b1_harden",
        status="ACTIVE"
    )
    db.add(runtime_session)
    db.commit()

    return runtime_session


def test_websocket_barge_in_and_latency_instrumentation(client, auth_headers, active_test_session, db):
    """Verifies WebSocket real-time audio turn, barge-in cancellation, and latency metrics."""
    session_id = active_test_session.id
    token = auth_headers["Authorization"].split(" ")[1]
    ws_url = f"/ws/runtime/sessions/{session_id}/audio?token={token}"

    with client.websocket_connect(ws_url) as ws:
        # Drain initial greeting messages
        greeting_text = ""
        for _ in range(20):
            msg = ws.receive()
            if "text" in msg and msg["text"]:
                p = json.loads(msg["text"])
                if p.get("type") == "assistant_text":
                    greeting_text = p.get("text", "")
                if p.get("type") == "turn_complete":
                    break
        assert len(greeting_text) > 0

        # 1. Start conversational turn
        ws.send_json({"type": "start"})

        # Send speech audio frame with voice energy
        import struct
        loud_chunk = struct.pack("<800h", *([1500] * 800))  # 50ms at 16kHz
        ws.send_bytes(loud_chunk)

        # Receive partial transcript from streaming STT
        partial_msg = None
        for _ in range(10):
            msg = ws.receive()
            if "text" in msg and msg["text"]:
                p = json.loads(msg["text"])
                if p.get("type") == "transcript" and not p.get("final"):
                    partial_msg = p
                    break
        assert partial_msg is not None
        assert partial_msg["final"] is False
        assert len(partial_msg["text"]) > 0

        # Stop speech turn
        ws.send_json({"type": "stop"})

        # Receive turn response: final transcript, assistant text, and latency metrics
        final_msg = None
        asst_msg = None
        latency_msg = None
        for _ in range(25):
            msg = ws.receive()
            if "text" in msg and msg["text"]:
                p = json.loads(msg["text"])
                if p.get("type") == "transcript" and p.get("final"):
                    final_msg = p
                elif p.get("type") == "assistant_text":
                    asst_msg = p
                elif p.get("type") == "latency_metrics":
                    latency_msg = p
                elif p.get("type") == "turn_complete":
                    break

        assert final_msg is not None and final_msg["final"] is True
        assert asst_msg is not None
        assert latency_msg is not None
        metrics = latency_msg["metrics"]
        assert "stt_ms" in metrics
        assert "llm_ms" in metrics
        assert "tts_ttfb_ms" in metrics
        assert "round_trip_ms" in metrics

        # 2. Test Real Voice Barge-In:
        # Trigger barge-in signal directly or via loud frames while speaking
        ws.send_json({"type": "interrupt"})
        interrupt_reply = ws.receive_json()
        assert interrupt_reply["type"] == "interrupted"

    # Verify session disconnect cleans up active_audio_sessions tracker
    assert session_id not in active_audio_sessions

    # Verify runtime events in DB include ASSISTANT_INTERRUPTED and AUDIO_SESSION_DISCONNECTED
    event_repo = RuntimeEventRepository(db)
    events = event_repo.list_by_session(session_id)
    event_types = [e.event_type for e in events]

    assert RuntimeEventType.AUDIO_SESSION_CONNECTED.value in event_types
    assert RuntimeEventType.USER_TRANSCRIPT_PARTIAL.value in event_types
    assert RuntimeEventType.USER_TRANSCRIPT_FINAL.value in event_types
    assert RuntimeEventType.ASSISTANT_INTERRUPTED.value in event_types
    assert RuntimeEventType.AUDIO_SESSION_DISCONNECTED.value in event_types


# ---------------------------------------------------------------------------
# 5. OPT-IN REAL PROVIDER SMOKE TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_real_provider_end_to_end_smoke():
    """
    Opt-in end-to-end smoke test against real provider APIs (Cartesia + Gemini).
    Only executes if RUN_REAL_PROVIDER_TESTS=true and valid API keys are configured.
    """
    run_real = os.environ.get("RUN_REAL_PROVIDER_TESTS", "").strip().lower() in ("true", "1")
    cartesia_key = settings.CARTESIA_API_KEY
    gemini_key = settings.GEMINI_API_KEY

    has_real_keys = bool(
        cartesia_key and
        gemini_key and
        not cartesia_key.startswith("mock") and
        not gemini_key.startswith("mock")
    )

    if not run_real or not has_real_keys:
        pytest.skip("Skipping real provider smoke test: RUN_REAL_PROVIDER_TESTS not enabled or real API keys missing.")

    # 1. Real Cartesia TTS Test
    real_tts = CartesiaTTSProvider(api_key=cartesia_key)
    real_tts.initialize({})
    tts_result = real_tts.synthesize("Hello from Choranta runtime smoke test.")
    assert len(tts_result.audio_bytes) > 0
    assert tts_result.duration_seconds > 0.1
    real_tts.close()

    # 2. Real Gemini LLM Test
    real_llm = GeminiLLMProvider(api_key=gemini_key)
    real_llm.initialize({})
    llm_result = await real_llm.generate_async(
        system_instruction="You are a helpful test assistant. Respond in 5 words or less.",
        messages=[{"role": "user", "content": "What is 2 + 2?"}]
    )
    assert llm_result.text is not None
    assert len(llm_result.text.strip()) > 0
    assert llm_result.usage["input_tokens"] > 0
    real_llm.close()

    # 3. Real Cartesia STT Test
    real_stt = CartesiaSTTProvider(api_key=cartesia_key)
    real_stt.initialize({})
    # Transcribe the audio generated in step 1
    stt_result = await real_stt.process_audio_async(tts_result.audio_bytes)
    assert stt_result.text is not None
    assert len(stt_result.text.strip()) > 0
    real_stt.close()
