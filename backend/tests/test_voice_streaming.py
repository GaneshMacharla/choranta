"""A reply is voiced as one utterance while the LLM writes it, and false interruptions resume mid-reply."""
import asyncio
import base64
import json
from typing import List

import httpx
import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.providers.registry import default_registry
from app.runtime.providers.sarvam import tts as sarvam_tts
from app.runtime.providers.tts import TextFeed
from app.runtime.telephony import session as session_module
from app.runtime.telephony.session import SEGMENT_END, FillerText, WholeText, phrase_start
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_sarvam_speech import _patch_async_client, _wav
from test_telephony_realtime import FakeLLM, FakeSTT, _session, _shutdown, _until


class FakeStreamingTTS:
    """Voices a whole TextFeed as one utterance, like Sarvam's streaming endpoint."""
    supports_text_stream = True

    def __init__(self):
        self.utterances: List[List[str]] = []   # pieces of each streamed utterance
        self.spoken: List[str] = []              # whole-text (non-streamed) requests

    async def synthesize_text_stream(self, feed, voice_id=None, speed=1.0, language=None, **kwargs):
        pieces: List[str] = []
        self.utterances.append(pieces)
        async for text in feed:
            pieces.append(text)
            yield b"\x10\x00" * 800

    async def synthesize_stream(self, text, voice_id=None, speed=1.0, **kwargs):
        self.spoken.append(text)
        yield b"\x10\x00" * 800


@pytest.fixture
def streaming(monkeypatch):
    tts, llm = FakeStreamingTTS(), FakeLLM([])
    monkeypatch.setattr(default_registry, "get_stt", lambda name: FakeSTT())
    monkeypatch.setattr(default_registry, "get_llm", lambda name: llm)
    monkeypatch.setattr(default_registry, "get_tts", lambda name: tts)
    return {"tts": tts, "llm": llm}


@pytest.mark.asyncio
async def test_a_reply_is_voiced_as_one_utterance(db: Session, telephony_setup, streaming):
    streaming["llm"].replies = ["Got it. Saturday at eleven works. Shall I book it?"]
    s = _session(db, telephony_setup)
    try:
        s._start_turn(s._respond(0.0))
        await _until(lambda: s._turn_task.done(), timeout=10)
        assert streaming["tts"].utterances == [["Got it.", "Saturday at eleven works.", "Shall I book it?"]]
        assert streaming["tts"].spoken == []
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_fillers_segment_ends_and_language_changes_start_a_new_utterance(db: Session, telephony_setup, streaming):
    s = _session(db, telephony_setup)
    queue: asyncio.Queue = asyncio.Queue()
    for item in [
        "Let me check.", SEGMENT_END,                         # lead-in before a tool: said now
        FillerText("One moment.", "tool_filler"),
        "It's free on Saturday.", "Shall I book it?",
        "సరే, శనివారం బుక్ చేస్తాను.",                          # caller switched to Telugu
        WholeText("Thanks, bye!"), None,
    ]:
        queue.put_nowait(item)
    try:
        async def play():
            await s._play_sentences(s._turn, queue)

        s._start_turn(play())
        await _until(lambda: s._turn_task.done(), timeout=10)
        tts = streaming["tts"]
        assert tts.utterances == [["Let me check."], ["It's free on Saturday.", "Shall I book it?"], ["సరే, శనివారం బుక్ చేస్తాను."]]
        assert tts.spoken == ["One moment.", "Thanks, bye!"]
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_text_feed_survives_a_cancelled_read():
    feed = TextFeed("one")
    assert await feed.get() == "one"
    reader = asyncio.create_task(feed.get())
    await asyncio.sleep(0)
    reader.cancel()
    feed.put("two")
    feed.close()
    assert [t async for t in feed] == ["two"]
    assert await feed.get() is None  # stays ended


def test_sarvam_rest_fallback_voices_the_whole_reply_in_one_request(monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"audios": [base64.b64encode(_wav(bytes([1, 0]) * 800, 8000)).decode()]})

    _patch_async_client(monkeypatch, sarvam_tts, handler)
    monkeypatch.setattr(settings, "SARVAM_TTS_STREAMING", False)
    provider = sarvam_tts.SarvamTTSProvider(api_key="k")
    assert provider.supports_text_stream

    async def run():
        feed = TextFeed("Got it.", "Shall I book it?")
        feed.close()
        return b"".join([c async for c in provider.synthesize_text_stream(feed, sample_rate=8000)])

    assert len(asyncio.run(run())) == 1600
    assert [r["text"] for r in requests] == ["Got it. Shall I book it?"]
    assert requests[0]["speech_sample_rate"] == 8000


def _tone(seconds: float, rate: int = 8000, amplitude: int = 6000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def test_resume_point_is_the_start_of_the_phrase_being_heard():
    rate = 8000
    pcm = np.concatenate([_tone(0.6), np.zeros(int(0.2 * rate), np.int16), _tone(0.8)]).tobytes()
    stopped = int(1.2 * rate) * 2                       # stopped inside the second phrase
    resume = phrase_start(pcm, stopped, rate)
    second_phrase = int(0.8 * rate) * 2
    assert second_phrase - int(0.1 * rate) * 2 <= resume <= second_phrase   # just inside the pause before it
    assert phrase_start(pcm, int(0.4 * rate) * 2, rate) == 0               # first phrase: from the start
    assert phrase_start(_tone(2.0).tobytes(), 3000, rate) == 0              # no pause at all: from the start


@pytest.mark.asyncio
async def test_false_interruption_resumes_without_repeating_the_reply(db: Session, telephony_setup, streaming, monkeypatch):
    monkeypatch.setattr(session_module, "PLAYBACK_LEAD_MS", 50)
    s = _session(db, telephony_setup)
    try:
        s._start_turn(s._speak_text("Hi Rahul, this is Apex Realty. Do you have a minute?"))
        await _until(lambda: s.assistant_speaking)
        await s.handle_barge_in()
        s._resume()
        await _until(lambda: s._turn_task.done(), timeout=10)
        assert streaming["tts"].spoken == ["Hi Rahul, this is Apex Realty. Do you have a minute?"]
    finally:
        await _shutdown(s)
