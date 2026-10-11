"""Phone call cost controls: reply cap, no unheard synthesis, text cleanup, agent hang-up, silence handling."""
import asyncio

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.providers.base import LLMResult, ToolCallRequest
from app.runtime.providers.registry import default_registry
from app.runtime.telephony import session as session_module
from app.runtime.telephony.speech_text import clean_for_speech
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_telephony_realtime import (  # noqa: F401
    FakeLLM, FakeWebSocket, _assistant_messages, _session, _shutdown, _until, fakes,
)


class ClosableWebSocket(FakeWebSocket):
    def __init__(self):
        super().__init__()
        self.closed = False

    async def close(self, code: int = 1000):
        self.closed = True


def test_clean_for_speech_strips_unspeakable_text():
    assert clean_for_speech("**Great!** \U0001F60A\n- see https://x.com") == "Great! see"
    assert clean_for_speech("Budget is 60 - 80 lakh.") == "Budget is 60 - 80 lakh."
    assert clean_for_speech("Sure... [interrupted by caller]") == "Sure..."
    assert clean_for_speech("...") == ""


@pytest.mark.asyncio
async def test_long_reply_is_capped(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_MAX_REPLY_CHARS", 40, raising=False)
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["We have a lovely flat in Whitefield today. It has two bedrooms. It also has a pool. And a gym."]
    fakes["stt"].transcripts[640] = "Tell me everything"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert fakes["tts"].spoken == ["We have a lovely flat in Whitefield today."]
        assert _assistant_messages(s)[-1] == "We have a lovely flat in Whitefield today."
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_interrupted_reply_does_not_synthesize_unheard_sentences(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(session_module, "PLAYBACK_LEAD_MS", 50)
    fakes["tts"].ms_per_char = 30
    s = _session(db, telephony_setup)
    fakes["llm"].replies = [
        "First point here. Second point here. Third point here. Fourth point here. Fifth point here.",
        "Okay.",
    ]
    fakes["stt"].transcripts[640] = "Go on"
    fakes["stt"].transcripts[960] = "Stop, what is the price?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s.assistant_speaking)
        await s.handle_barge_in()
        await s.execute_turn(b"\x00\x00" * 480)
        await _until(lambda: len(fakes["llm"].calls) == 2 and s._turn_task.done(), timeout=10)
        first_reply = [t for t in fakes["tts"].spoken if "point" in t]
        assert len(first_reply) <= 2  # the playing sentence plus one prefetched, not all five
    finally:
        await _shutdown(s)


class EndCallLLM(FakeLLM):
    def generate_stream(self, system_instruction, messages, available_tools=None, temperature=0.7, model=None):
        self.calls.append(messages)
        assert any(t["name"] == "end_call" for t in (available_tools or []))
        yield "Thanks Rahul, goodbye! "
        yield LLMResult(text="Thanks Rahul, goodbye!", finish_reason="tool_calls", usage={},
                        tool_calls=[ToolCallRequest(id="c1", tool_name="end_call", arguments={})])


@pytest.mark.asyncio
async def test_agent_can_end_the_call(db: Session, telephony_setup, fakes, monkeypatch):
    llm = EndCallLLM([])
    monkeypatch.setattr(default_registry, "get_llm", lambda name: llm)
    s = _session(db, telephony_setup)
    s.websocket = ClosableWebSocket()
    fakes["stt"].transcripts[640] = "That is all, thanks"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s.websocket.closed, timeout=10)
        assert fakes["tts"].spoken == ["Thanks Rahul, goodbye!"]
        assert s._end_reason == "agent_ended"
        assert len(llm.calls) == 1  # no extra LLM round after end_call
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_silent_caller_is_reprompted_then_hung_up(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "CALL_SILENCE_REPROMPT_S", 0.3, raising=False)
    monkeypatch.setattr(settings, "CALL_SILENCE_HANGUP_S", 0.3, raising=False)
    s = _session(db, telephony_setup)
    s.websocket = ClosableWebSocket()
    s._last_activity = 0.0
    watchdog = asyncio.create_task(s._watchdog())
    try:
        await _until(lambda: s.websocket.closed, timeout=10)
        assert fakes["tts"].spoken[0] == session_module.SILENCE_REPROMPT_TEXT
        assert s._end_reason == "caller_silent"
    finally:
        watchdog.cancel()
        await _shutdown(s)


@pytest.mark.asyncio
async def test_phone_style_instructions_are_added_once(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    try:
        s._apply_phone_style()
        s._apply_phone_style()
        instructions = s.context.conversation.system_instruction
        assert instructions.count(session_module.PHONE_STYLE_MARKER) == 1
        assert "end_call" in instructions
    finally:
        await _shutdown(s)
