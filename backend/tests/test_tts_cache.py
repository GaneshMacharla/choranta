import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.runtime.telephony import tts_cache
from app.runtime.telephony.session import TelephonyMediaSession, _SpokenSentence
from app.runtime.usage.tracker import UsageTracker


@pytest.fixture(autouse=True)
def fresh_cache():
    tts_cache.clear()
    yield
    tts_cache.clear()


def _key(text: str, voice: str = "shubh"):
    return tts_cache.cache_key("sarvam", voice, 1.0, "hi-IN", "ExotelProvider", text)


def test_cache_returns_stored_audio_only_for_same_voice_and_text():
    tts_cache.put(_key("Hello, this is Priya."), b"\x01\x02" * 100)
    assert tts_cache.get(_key("Hello, this is Priya.")) == b"\x01\x02" * 100
    assert tts_cache.get(_key("Hello, this is Priya.", voice="anushka")) is None
    assert tts_cache.get(_key("Hello, this is Riya.")) is None


def test_cache_evicts_least_recently_used_over_size_limit(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_MB", 1)
    half = b"\x00" * (600 * 1024)
    tts_cache.put(_key("first"), half)
    tts_cache.put(_key("second"), half)  # 1.2 MB total: "first" is dropped
    assert tts_cache.get(_key("first")) is None
    assert tts_cache.get(_key("second")) == half


def test_cache_disabled_when_size_is_zero(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_MB", 0)
    tts_cache.put(_key("Hello."), b"\x01\x02")
    assert tts_cache.get(_key("Hello.")) is None


class _CountingTTS:
    def __init__(self):
        self.calls = 0

    async def synthesize_stream(self, text, voice_id=None, speed=1.0, language=None):
        self.calls += 1
        yield b"\x05\x06" * 800


def _fake_session():
    spec = SimpleNamespace(
        providers=SimpleNamespace(tts="sarvam"),
        voice=SimpleNamespace(voice_id="shubh", speed=1.0),
        languages=SimpleNamespace(primary="hi-IN"),
    )
    tracker = UsageTracker("provider", llm_provider="sarvam", stt_provider="sarvam", tts_provider="sarvam")
    return SimpleNamespace(
        context=SimpleNamespace(agent_spec=spec, usage_tracker=tracker),
        telephony_provider=SimpleNamespace(normalize_audio_outbound=lambda chunk: chunk),
    )


def test_repeated_sentence_is_replayed_without_synthesis_or_billing():
    session = _fake_session()
    tts = _CountingTTS()

    async def speak(text):
        sentence = _SpokenSentence(text)
        await TelephonyMediaSession._synthesize(session, tts, sentence)
        return sentence

    first = asyncio.run(speak("Namaste, main Priya bol rahi hoon."))
    usage_after_first = dict(session.context.usage_tracker.get_summary())
    second = asyncio.run(speak("Namaste, main Priya bol rahi hoon."))

    assert tts.calls == 1
    assert second.done and bytes(second.audio) == bytes(first.audio)
    usage = session.context.usage_tracker.get_summary()
    assert usage["tts_characters"] == usage_after_first["tts_characters"] == len("Namaste, main Priya bol rahi hoon.")
    assert usage["tts_seconds"] == usage_after_first["tts_seconds"]
