"""Real-time phone conversation behaviour: streaming replies, barge-in, false interruptions, backchannels."""
import asyncio
import json
from typing import Any, Dict, List

import pytest
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.call import Call
from app.runtime.context import RuntimeContext
from app.runtime.providers.base import LLMResult, TranscriptResult
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony.exotel import ExotelTelephonyProvider
from app.runtime.telephony import session as session_module
from app.runtime.telephony.session import TelephonyMediaSession
from app.runtime.telephony.speech_text import SentenceChunker, is_backchannel
from test_phase3c_telephony import _build_test_agent_spec, telephony_setup  # noqa: F401


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

class FakeWebSocket:
    def __init__(self):
        self.sent: List[Dict[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def media_frames(self) -> int:
        return sum(1 for m in self.sent if m["event"] == "media")

    def clears(self) -> int:
        return sum(1 for m in self.sent if m["event"] == "clear")


class FakeSTT:
    """Transcribes an utterance by looking up its byte length."""
    def __init__(self):
        self.transcripts: Dict[int, str] = {}

    async def process_audio_async(self, audio):
        return TranscriptResult(text=self.transcripts.get(len(audio), ""), is_final=True, confidence=0.9)


class FakeLLM:
    def __init__(self, replies: List[str]):
        self.replies = list(replies)
        self.calls: List[List[Dict[str, Any]]] = []

    def generate_stream(self, system_instruction, messages, available_tools=None, temperature=0.7, model=None):
        self.calls.append(messages)
        reply = self.replies.pop(0) if self.replies else "Okay."
        for word in reply.split(" "):
            yield word + " "
        yield LLMResult(text=reply, tool_calls=[], finish_reason="stop", usage={"input_tokens": 10, "output_tokens": 5})


class FakeTTS:
    """Each sentence becomes `ms_per_char` ms of 16kHz PCM, streamed in 100 ms chunks."""
    def __init__(self, ms_per_char: float = 1.0):
        self.ms_per_char = ms_per_char
        self.spoken: List[str] = []

    async def synthesize_stream(self, text, voice_id=None, speed=1.0, **kwargs):
        self.spoken.append(text)
        total = int(len(text) * self.ms_per_char * 32)  # 32 bytes/ms at 16kHz 16-bit
        total -= total % 2
        chunk = 3200
        for i in range(0, total, chunk):
            await asyncio.sleep(0)
            yield b"\x10\x00" * (min(chunk, total - i) // 2)


@pytest.fixture
def fakes(monkeypatch):
    stt, tts = FakeSTT(), FakeTTS()
    llm = FakeLLM([])
    monkeypatch.setattr(default_registry, "get_stt", lambda name: stt)
    monkeypatch.setattr(default_registry, "get_llm", lambda name: llm)
    monkeypatch.setattr(default_registry, "get_tts", lambda name: tts)
    return {"stt": stt, "llm": llm, "tts": tts}


def _session(db: Session, telephony_setup) -> TelephonyMediaSession:
    call = Call(
        id=generate_unique_id("call_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        caller_number="+918008538015",
        destination_number="+914045209348",
        direction="OUTBOUND",
        status="ACTIVE",
        provider="exotel",
        provider_call_id=generate_unique_id("exo_"),
    )
    db.add(call)
    db.commit()
    ws = FakeWebSocket()
    s = TelephonyMediaSession(
        websocket=ws, call_record=call, stream_sid="stream_rt", db=db,
        telephony_provider=ExotelTelephonyProvider(webhook_secret="x"),
    )
    spec = _build_test_agent_spec(telephony_setup["agent"].id)
    s.context = RuntimeContext("ses_rt", call.agent_id, call.client_id, call.agent_version_id, spec, {})
    s.runtime_session = type("RS", (), {"id": "ses_rt"})()
    s.emitter.start_buffering()
    s._utterance_worker = asyncio.create_task(s._utterance_loop())
    return s


def _events(s: TelephonyMediaSession, event_type: str) -> List[Dict[str, Any]]:
    return [r.payload_json for r in (s.emitter._buffer or []) if r.event_type == event_type]


def _assistant_messages(s: TelephonyMediaSession) -> List[str]:
    return [m.content for m in s.context.conversation.messages if m.role.value == "assistant"]


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def _shutdown(s: TelephonyMediaSession) -> None:
    for task in (s._turn_task, s._utterance_worker):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def test_sentence_chunker_streams_sentences_and_keeps_abbreviations():
    chunker = SentenceChunker()
    out = []
    for piece in ["Hi Rahul! I found ", "a flat with Dr. Rao ", "nearby. It costs Rs. 75 lakhs. Want ", "details?"]:
        out += chunker.feed(piece)
    out += chunker.flush()
    assert out == ["Hi Rahul!", "I found a flat with Dr. Rao nearby.", "It costs Rs. 75 lakhs.", "Want details?"]


def test_sentence_chunker_breaks_long_first_clause_early():
    chunker = SentenceChunker(first_clause_min_chars=20)
    assert chunker.feed("Thanks for calling Apex Realty, I can help ") == ["Thanks for calling Apex Realty,"]


def test_backchannel_detection():
    for text in ["Okay.", "hmm", "Haan ji", "Uh-huh", "Theek hai"]:
        assert is_backchannel(text), text
    assert not is_backchannel("Okay, what is the price?")


# --------------------------------------------------------------------------
# Conversation behaviour
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reply_streams_sentence_by_sentence(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["Sure, I can help. We have three flats in Whitefield. Which budget suits you?"]
    fakes["stt"].transcripts[640] = "Do you have flats in Whitefield?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done())
        assert fakes["tts"].spoken == [
            "Sure, I can help.", "We have three flats in Whitefield.", "Which budget suits you?"
        ]
        assert s.websocket.media_frames() > 0
        assert _assistant_messages(s)[-1].startswith("Sure, I can help.")
        assert _events(s, "ASSISTANT_RESPONSE")[-1]["interrupted"] is False
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_barge_in_keeps_only_what_the_caller_heard(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(session_module, "PLAYBACK_LEAD_MS", 50)
    fakes["tts"].ms_per_char = 40  # long audio so the reply is still playing
    s = _session(db, telephony_setup)
    fakes["llm"].replies = [
        "Our first option is a two bedroom flat. The second option is a villa with a garden. The third is a penthouse.",
        "The villa costs one crore.",
    ]
    fakes["stt"].transcripts[640] = "Tell me the options"
    fakes["stt"].transcripts[960] = "How much is the villa?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s.assistant_speaking)
        await asyncio.sleep(0.4)

        await s.handle_barge_in()
        assert s.websocket.clears() == 1
        await s.execute_turn(b"\x00\x00" * 480)
        await _until(lambda: len(_events(s, "ASSISTANT_RESPONSE")) >= 2, timeout=10)

        interrupted = [m for m in _assistant_messages(s) if "[interrupted by caller]" in m]
        assert len(interrupted) == 1
        heard = interrupted[0].replace("... [interrupted by caller]", "")
        assert heard and "penthouse" not in heard
        assert "Our first option is a two bedroom flat.".startswith(heard) or heard.startswith("Our first option")
        # The follow-up question was answered with the interruption in context
        assert fakes["llm"].calls[-1][-1]["content"] == "How much is the villa?"
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_backchannel_resumes_instead_of_interrupting(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(session_module, "PLAYBACK_LEAD_MS", 50)
    fakes["tts"].ms_per_char = 15
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["The flat has two bedrooms. It is close to the metro station."]
    fakes["stt"].transcripts[640] = "Tell me about the flat"
    fakes["stt"].transcripts[160] = "Okay."
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s.assistant_speaking)
        await s.handle_barge_in()
        assert s._paused
        await s.execute_turn(b"\x00\x00" * 80)  # caller says "okay"
        await _until(lambda: s._turn_task.done(), timeout=10)
        assert not _events(s, "ASSISTANT_RESPONSE")[-1]["interrupted"]
        assert len(fakes["llm"].calls) == 1  # no new LLM turn for a backchannel
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_noise_burst_resumes_paused_reply(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(session_module, "PLAYBACK_LEAD_MS", 50)
    fakes["tts"].ms_per_char = 15
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["Let me tell you about the amenities. There is a pool and a gym."]
    fakes["stt"].transcripts[640] = "What amenities?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s.assistant_speaking)
        await s.handle_barge_in()
        assert s._paused
        s._resume()  # what a "speech_discarded" endpointer event triggers
        await _until(lambda: s._turn_task.done(), timeout=10)
        assert _events(s, "ASSISTANT_RESPONSE")[-1]["interrupted"] is False
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_speech_during_thinking_is_merged_into_one_question(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["First answer.", "Combined answer."]
    fakes["stt"].transcripts[640] = "I want a flat"
    fakes["stt"].transcripts[960] = "in Whitefield"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await s.execute_turn(b"\x00\x00" * 480)  # arrives before the first reply was heard
        await _until(lambda: s._turn_task is not None and s._turn_task.done() and s._utterance_queue.empty(), timeout=10)
        await asyncio.sleep(0.05)
        users = [m.content for m in s.context.conversation.messages if m.role.value == "user"]
        assert users[-1] == "I want a flat in Whitefield"
    finally:
        await _shutdown(s)
