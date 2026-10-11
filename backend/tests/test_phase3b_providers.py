import io
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.websockets import WebSocketDisconnect
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.cartesia.stt import CartesiaSTTProvider, _pcm_to_wav_buffer
from app.runtime.providers.cartesia.tts import CartesiaTTSProvider
from app.runtime.providers.gemini.llm import GeminiLLMProvider
from app.runtime.providers.registry import ProviderRegistry
from app.runtime.readiness.checker import RuntimeReadinessChecker
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
from app.runtime.runtime import AgentRuntime
from app.runtime.events.types import RuntimeEventType
from app.repositories.runtime_event_repository import RuntimeEventRepository


# ---------------------------------------------------------------------------
# 1. CARTESIA STT ADAPTER TESTS
# ---------------------------------------------------------------------------

def test_cartesia_stt_missing_api_key_raises_error():
    provider = CartesiaSTTProvider(api_key="")
    with pytest.raises(ProviderUnavailable) as exc:
        provider.initialize({})
    assert "Missing CARTESIA_API_KEY" in str(exc.value)


def test_pcm_to_wav_buffer_creates_valid_wav_header():
    pcm_samples = b"\x00\x00" * 320  # 20ms of silence at 16kHz
    wav_buf = _pcm_to_wav_buffer(pcm_samples, sample_rate=16000)
    wav_bytes = wav_buf.getvalue()
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:16]


@pytest.mark.asyncio
async def test_cartesia_stt_process_audio_mocked():
    provider = CartesiaSTTProvider(api_key="mock_cartesia_key")
    mock_response = MagicMock()
    mock_response.text = "Hello, I would like to book a table."
    mock_response.confidence = 0.98

    mock_client = MagicMock()
    mock_client.stt.transcribe.return_value = mock_response

    mock_async_client = MagicMock()
    mock_async_client.stt.transcribe = AsyncMock(return_value=mock_response)

    with patch("cartesia.Cartesia", return_value=mock_client), \
         patch("cartesia.AsyncCartesia", return_value=mock_async_client):
        provider.initialize({})

        # Test sync process_audio
        pcm_bytes = b"\x01\x00" * 800
        result = provider.process_audio(pcm_bytes)
        assert result.text == "Hello, I would like to book a table."
        assert result.confidence == 0.98
        assert result.is_final is True

        # Test async process_audio_async
        async_result = await provider.process_audio_async(pcm_bytes)
        assert async_result.text == "Hello, I would like to book a table."

        provider.close()


# ---------------------------------------------------------------------------
# 2. CARTESIA TTS ADAPTER TESTS
# ---------------------------------------------------------------------------

def test_cartesia_tts_missing_api_key_raises_error():
    provider = CartesiaTTSProvider(api_key="")
    with pytest.raises(ProviderUnavailable) as exc:
        provider.initialize({})
    assert "Missing CARTESIA_API_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_cartesia_tts_synthesize_mocked():
    provider = CartesiaTTSProvider(api_key="mock_cartesia_key")
    synthetic_pcm_chunks = [b"\x00\x01" * 1600, b"\x00\x02" * 1600]  # total 6400 bytes -> 0.2s

    mock_client = MagicMock()
    mock_client.tts.bytes.return_value = iter(synthetic_pcm_chunks)

    async def async_chunks_gen(*args, **kwargs):
        for c in synthetic_pcm_chunks:
            yield c

    mock_async_client = MagicMock()
    mock_async_client.tts.bytes = AsyncMock(return_value=async_chunks_gen())

    with patch("cartesia.Cartesia", return_value=mock_client), \
         patch("cartesia.AsyncCartesia", return_value=mock_async_client):
        provider.initialize({})

        # Batch synthesize
        audio_res = provider.synthesize(text="Thank you for calling.")
        assert len(audio_res.audio_bytes) == 6400
        assert audio_res.format == "pcm_s16le"
        assert audio_res.duration_seconds == 0.2

        # Streaming synthesize_stream
        streamed_chunks = []
        async for chunk in provider.synthesize_stream(text="Thank you for calling."):
            streamed_chunks.append(chunk)

        assert len(b"".join(streamed_chunks)) == 6400
        provider.close()


# ---------------------------------------------------------------------------
# 3. GEMINI LLM ADAPTER TESTS
# ---------------------------------------------------------------------------

def test_gemini_llm_missing_api_key_raises_error():
    provider = GeminiLLMProvider(api_key="")
    with pytest.raises(ProviderUnavailable) as exc:
        provider.initialize({})
    assert "Missing GEMINI_API_KEY" in str(exc.value)


def test_gemini_llm_generate_text_and_tool_call():
    provider = GeminiLLMProvider(api_key="mock_gemini_key")

    mock_client = MagicMock()

    # Mock standard conversational response
    mock_cand = MagicMock()
    mock_part_text = MagicMock()
    mock_part_text.text = "I would be happy to help check availability."
    mock_part_text.function_call = None
    mock_cand.content.parts = [mock_part_text]

    mock_resp = MagicMock()
    mock_resp.candidates = [mock_cand]
    mock_resp.usage_metadata.prompt_token_count = 25
    mock_resp.usage_metadata.candidates_token_count = 15
    mock_client.models.generate_content.return_value = mock_resp

    with patch("google.genai.Client", return_value=mock_client) as mock_client_cls:
        provider.initialize({})
        mock_client_cls.assert_called_once()
        client_kwargs = mock_client_cls.call_args.kwargs
        assert client_kwargs["api_key"] == "mock_gemini_key"
        assert client_kwargs["http_options"].retry_options.attempts == 1
        assert client_kwargs["http_options"].timeout == 30000

        # Test text generation
        res = provider.generate(
            system_instruction="You are a salon assistant.",
            messages=[{"role": "user", "content": "Hi"}],
            available_tools=[{"name": "check_availability"}]
        )
        assert res.text == "I would be happy to help check availability."
        assert res.finish_reason == "stop"
        assert res.usage["input_tokens"] == 25
        assert res.usage["output_tokens"] == 15

        # Mock tool call response
        mock_fc = MagicMock()
        mock_fc.name = "check_availability"
        mock_fc.args = {"date": "2026-10-15", "service": "Haircut"}

        mock_cand_tool = MagicMock()
        mock_part_fc = MagicMock(spec=["function_call"])
        mock_part_fc.function_call = mock_fc
        mock_cand_tool.content.parts = [mock_part_fc]

        mock_resp_tool = MagicMock()
        mock_resp_tool.candidates = [mock_cand_tool]
        mock_resp_tool.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_resp_tool

        res_tool = provider.generate(
            system_instruction="You are a salon assistant.",
            messages=[{"role": "user", "content": "Check haircut on Oct 15"}],
            available_tools=[{"name": "check_availability"}]
        )
        assert len(res_tool.tool_calls) == 1
        assert res_tool.tool_calls[0].tool_name == "check_availability"
        assert res_tool.tool_calls[0].arguments == {"date": "2026-10-15", "service": "Haircut"}
        assert res_tool.finish_reason == "tool_calls"


# ---------------------------------------------------------------------------
# 4. PROVIDER REGISTRY TESTS
# ---------------------------------------------------------------------------

def test_provider_registry_modes():
    mock_reg = ProviderRegistry(mode="mock")
    assert mock_reg.get_stt("cartesia").environment == "development/test"
    assert mock_reg.get_tts("cartesia").environment == "development/test"
    assert mock_reg.get_llm("gemini").environment == "development/test"

    # Switch to real
    mock_reg.enable_real_providers()
    assert mock_reg.get_stt("cartesia").environment == "production"
    assert mock_reg.get_tts("cartesia").environment == "production"
    assert mock_reg.get_llm("gemini").environment == "production"

    # Switch back to mock
    mock_reg.enable_mock_providers()
    assert mock_reg.get_stt("cartesia").environment == "development/test"


# ---------------------------------------------------------------------------
# 5. WEBSOCKET REALTIME AUDIO TESTS
# ---------------------------------------------------------------------------

@pytest.fixture
def published_agent_and_session(db):
    """Sets up a client, published agent, and active runtime session."""
    client = Client(
        id="cli_p3b_test",
        name="Phase 3B Dental Clinic",
        business_type="Healthcare",
        status="ACTIVE"
    )
    db.add(client)

    agent = Agent(
        id="ag_p3b_test",
        client_id="cli_p3b_test",
        name="P3B Voice Agent",
        role="Dental Receptionist",
        status="ACTIVE"
    )
    db.add(agent)

    spec = CanonicalAgentSpec(
        schema_version="1.0",
        agent=AgentMetaSpec(id="ag_p3b_test", name="P3B Voice Agent", role="Dental Receptionist"),
        identity=IdentitySpec(name="P3B Voice Agent", persona="Receptionist"),
        business_context=BusinessContextSpec(business_name="Phase 3B Dental Clinic"),
        instructions=InstructionsSpec(primary_goal="Answer calls and schedule dental consultations."),
        conversation=ConversationSpec(greeting="Hello! Dental Clinic here. How can I assist you today?"),
        languages=LanguagesSpec(primary="en", supported=["en"]),
        knowledge=KnowledgeSpec(),
        tools=ToolsSpec(enabled=["check_availability", "book_appointment"]),
        integrations=IntegrationsSpec(),
        voice=VoiceSpec(provider="cartesia", voice_id="test_voice", speed=1.0),
        providers=ProvidersSpec(stt="cartesia", llm="gemini", tts="cartesia")
    )

    version = AgentVersion(
        id="agv_p3b_test_published",
        agent_id="ag_p3b_test",
        version_number=1,
        status="PUBLISHED",
        configuration_json=spec.model_dump()
    )
    db.add(version)
    db.commit()

    runtime = AgentRuntime(db)
    session = runtime.start_session(agent_id="ag_p3b_test", agent_version_id="agv_p3b_test_published")
    return {"client": client, "agent": agent, "version": version, "session": session}


def test_websocket_rejects_unauthorized_token(client, published_agent_and_session):
    session_id = published_agent_and_session["session"].id
    # No token provided
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/runtime/sessions/{session_id}/audio"):
            pass
    assert exc.value.code == 1008

    # Invalid token provided
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/runtime/sessions/{session_id}/audio?token=invalid_jwt"):
            pass
    assert exc.value.code == 1008


def test_websocket_rejects_nonexistent_session(client, auth_headers):
    token = auth_headers["Authorization"].split(" ")[1]
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/runtime/sessions/nonexistent_ses/audio?token={token}"):
            pass
    assert exc.value.code == 1008


def test_websocket_full_turn_and_barge_in_flow(client, db, auth_headers, published_agent_and_session):
    session_id = published_agent_and_session["session"].id
    token = auth_headers["Authorization"].split(" ")[1]

    with client.websocket_connect(f"/ws/runtime/sessions/{session_id}/audio?token={token}") as ws:
        # 1. Drain greeting messages (assistant_text, audio chunks, turn_complete)
        greeting_text = ""
        for _ in range(20):
            msg = ws.receive()
            if "text" in msg and msg["text"]:
                parsed = json.loads(msg["text"])
                if parsed.get("type") == "assistant_text":
                    greeting_text = parsed.get("text", "")
                if parsed.get("type") == "turn_complete":
                    break
            elif "bytes" in msg and msg["bytes"]:
                assert len(msg["bytes"]) > 0

        assert "Dental Clinic" in greeting_text

        # 2. Ping-Pong keepalive test
        ws.send_json({"type": "ping"})
        pong_msg = ws.receive_json()
        assert pong_msg["type"] == "pong"

        # 3. Send binary audio frames (simulated PCM frame)
        pcm_frame = b"\x00\x00" * 320
        ws.send_bytes(pcm_frame)

        # 4. Turn execution via text input
        ws.send_json({
            "type": "text_input",
            "text": "What are your clinic hours?"
        })

        received_types = []
        for _ in range(20):
            res = ws.receive()
            if "text" in res and res["text"]:
                parsed = json.loads(res["text"])
                received_types.append(parsed.get("type"))
                if parsed.get("type") == "turn_complete":
                    break
            elif "bytes" in res and res["bytes"]:
                pass

        assert "assistant_text" in received_types

        # 5. Barge-in / Interrupt signal test
        ws.send_json({"type": "interrupt"})
        interrupt_reply = ws.receive_json()
        assert interrupt_reply["type"] == "interrupted"

    # Verify runtime events in DB
    event_repo = RuntimeEventRepository(db)
    events = event_repo.list_by_session(session_id)
    event_types = [e.event_type for e in events]

    assert RuntimeEventType.AUDIO_SESSION_CONNECTED in event_types
    assert RuntimeEventType.AUDIO_SESSION_DISCONNECTED in event_types
    assert RuntimeEventType.ASSISTANT_INTERRUPTED in event_types
