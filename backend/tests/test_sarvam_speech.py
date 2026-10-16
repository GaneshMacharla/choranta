import asyncio
import base64
import io
import json
import wave

import httpx
import pytest

from app.core.config import settings
from app.runtime.providers.sarvam import stt as sarvam_stt
from app.runtime.providers.sarvam import tts as sarvam_tts
from app.runtime.providers.sarvam.common import sarvam_language
from app.runtime.providers.overrides import apply_provider_overrides
from app.services.call_costing import estimate_call_cost


def _wav(pcm: bytes, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _patch_async_client(monkeypatch, module, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def test_language_mapping():
    assert sarvam_language("hi") == "hi-IN"
    assert sarvam_language("en-in") == "en-IN"
    assert sarvam_language("te") == "te-IN"
    assert sarvam_language(None) == "en-IN"
    assert sarvam_language("unknown") == "unknown"


def test_stt_sends_wav_and_returns_transcript(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("api-subscription-key")
        seen["body"] = request.content
        return httpx.Response(200, json={"transcript": " Mujhe 2BHK chahiye ", "language_code": "hi-IN", "language_probability": 0.97})

    _patch_async_client(monkeypatch, sarvam_stt, handler)
    provider = sarvam_stt.SarvamSTTProvider(api_key="sk_test")
    result = asyncio.run(provider.process_audio_async(b"\x01\x00" * 1600))
    assert result.text == "Mujhe 2BHK chahiye"
    assert seen["url"].endswith("/speech-to-text")
    assert seen["key"] == "sk_test"
    assert b"RIFF" in seen["body"] and settings.SARVAM_STT_MODEL.encode() in seen["body"]


def test_tts_rest_returns_16k_pcm_and_uses_sarvam_speaker(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_TTS_STREAMING", False, raising=False)
    pcm = b"\x10\x00" * 8000  # 0.5 s
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"audios": [base64.b64encode(_wav(pcm)).decode()]})

    _patch_async_client(monkeypatch, sarvam_tts, handler)
    provider = sarvam_tts.SarvamTTSProvider(api_key="sk_test")

    async def collect():
        return b"".join([c async for c in provider.synthesize_stream(
            "Namaste Rahul", voice_id="a0e99841-438c-4a64-b679-ae501e7d6091", language="hi")])

    audio = asyncio.run(collect())
    assert audio == pcm
    body = seen["body"]
    assert body["speech_sample_rate"] == 16000
    assert body["language_code"] == "hi-IN"
    assert body["speaker"] == settings.SARVAM_TTS_SPEAKER  # Cartesia UUID replaced by a Sarvam speaker
    assert body["model"] == settings.SARVAM_TTS_MODEL


def test_tts_falls_back_to_rest_when_stream_fails(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_TTS_STREAMING", True, raising=False)
    pcm = b"\x20\x00" * 1600

    async def broken_ws(self, *args, **kwargs):
        raise ConnectionError("ws down")
        yield b""  # pragma: no cover

    monkeypatch.setattr(sarvam_tts.SarvamTTSProvider, "_ws_stream", broken_ws)
    _patch_async_client(monkeypatch, sarvam_tts, lambda r: httpx.Response(200, json={"audios": [base64.b64encode(_wav(pcm)).decode()]}))
    provider = sarvam_tts.SarvamTTSProvider(api_key="sk_test")

    async def collect():
        return b"".join([c async for c in provider.synthesize_stream("Hello", voice_id="shubh")])

    assert asyncio.run(collect()) == pcm


def test_provider_override_switches_agent_to_sarvam(monkeypatch):
    from test_phase3c_telephony import _build_test_agent_spec

    spec = _build_test_agent_spec()
    assert spec.providers.tts == "cartesia"
    for kind in ("STT", "TTS", "LLM"):
        monkeypatch.setattr(settings, f"{kind}_PROVIDER_OVERRIDE", "sarvam", raising=False)
    overridden = apply_provider_overrides(spec)
    assert (overridden.providers.stt, overridden.providers.tts, overridden.providers.llm) == ("sarvam", "sarvam", "sarvam")
    assert overridden.voice.provider == "sarvam"
    assert spec.providers.tts == "cartesia"  # original spec untouched

    for kind in ("STT", "TTS", "LLM"):
        monkeypatch.setattr(settings, f"{kind}_PROVIDER_OVERRIDE", "", raising=False)
    assert apply_provider_overrides(spec) is spec


def test_sarvam_speech_costs_in_rupees(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_STT_INR_PER_HOUR", 30.0, raising=False)
    monkeypatch.setattr(settings, "SARVAM_TTS_INR_PER_10K_CHARS", 30.0, raising=False)
    cost = estimate_call_cost(60, {
        "stt_provider": "sarvam", "tts_provider": "sarvam",
        "stt_seconds": 3600, "tts_seconds": 40, "tts_characters": 10_000,
    })
    assert cost["breakdown"]["speech_to_text"] == 30.0
    assert cost["breakdown"]["text_to_speech"] == 30.0
    assert (cost["stt_provider"], cost["tts_provider"]) == ("sarvam", "sarvam")


def test_voice_preview_is_spoken_in_the_agent_language(monkeypatch):
    from app.services import sarvam_voices

    calls = []
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(sarvam_voices, "_previews", {})
    monkeypatch.setattr(sarvam_voices, "_synthesize", lambda voice, lang: calls.append((voice, lang)) or b"\x01\x00" * 10)

    sarvam_voices.preview_wav("ishita", "te")
    sarvam_voices.preview_wav("ishita", "te-IN")   # same language: served from the cache
    sarvam_voices.preview_wav("ishita")            # no language: English
    sarvam_voices.preview_wav("ishita", "xx")      # no sample sentence for it: English (cached)
    assert calls == [("ishita", "te"), ("ishita", "en")]


def test_browser_test_calls_send_the_agent_language_to_tts():
    import inspect
    from app.api.routes import websocket_audio
    from app.runtime.telephony import session

    # The audio WebSocket runs on the phone session, which speaks in the agent's language
    assert issubclass(websocket_audio.WebSocketMediaSession, session.TelephonyMediaSession)
    assert "language=spec.languages.primary" in inspect.getsource(session.TelephonyMediaSession._synthesize)


def test_voices_carry_gender_and_put_sarvam_language_picks_first():
    from app.services import sarvam_voices

    voices = sarvam_voices.list_voices("te-IN")
    assert len(voices) == len(sarvam_voices.SARVAM_VOICES)
    by_id = {v["id"]: v for v in voices}
    assert by_id["priya"]["gender"] == "female" and by_id["shubh"]["gender"] == "male"
    assert by_id["ishita"]["tier"] == 1 and "te" in by_id["neha"]["recommended_languages"]
    assert [v["id"] for v in voices[:4]] == ["priya", "shubh", "ratan", "neha"]  # Sarvam's Telugu picks, best tier first
    assert voices[4]["id"] == "ishita"                                           # then the top-rated voices
    assert sarvam_voices.list_voices()[0]["tier"] == 1 and sarvam_voices.list_voices()[0]["id"] != "varun"
