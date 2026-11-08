"""Phone call cost controls: reply cap, no unheard synthesis, text cleanup, agent hang-up, silence handling."""
import asyncio

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.call_limits import DEFAULT_MAX_TOOL_ROUNDS, resolve_call_limits
from app.runtime.providers.base import LLMResult, ToolCallRequest
from app.runtime.providers.registry import default_registry
from app.runtime.telephony import session as session_module
from app.runtime.telephony.speech_text import clean_for_speech
from app.schemas.agent_spec import CallLimitsSpec
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
async def test_capped_reply_still_ends_on_its_question(db: Session, telephony_setup, fakes, monkeypatch):
    """Like a telecaller: past the cap the extras are skipped, but the question after them is still asked."""
    monkeypatch.setattr(settings, "VOICE_MAX_REPLY_CHARS", 40, raising=False)
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["We have a lovely flat in Whitefield today. It has two bedrooms. It also has a pool. "
                            "Would you like to visit this Saturday?"]
    fakes["stt"].transcripts[640] = "Tell me everything"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        heard = "We have a lovely flat in Whitefield today. Would you like to visit this Saturday?"
        assert " ".join(fakes["tts"].spoken) == heard
        assert _assistant_messages(s)[-1] == heard  # the skipped extras aren't remembered as said
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_capped_question_is_not_searched_for_forever(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_MAX_REPLY_CHARS", 40, raising=False)
    monkeypatch.setattr(settings, "VOICE_QUESTION_SEARCH_CHARS", 30, raising=False)
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["We have a lovely flat in Whitefield today. It has two bedrooms and a balcony. "
                            "It also has a pool and a gym. Would you like to visit?"]
    fakes["stt"].transcripts[640] = "Tell me everything"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert fakes["tts"].spoken == ["We have a lovely flat in Whitefield today."]
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
        from app.runtime.telephony import phrases
        assert fakes["tts"].spoken[0] in phrases.variants("reprompt", s._language())
        assert s._end_reason == "caller_silent"
    finally:
        watchdog.cancel()
        await _shutdown(s)


@pytest.mark.asyncio
async def test_noise_after_the_reprompt_does_not_keep_the_call_alive(db: Session, telephony_setup, fakes, monkeypatch):
    """Line noise (sound with no words) mustn't re-arm the reprompt: one "still there?", then goodbye."""
    monkeypatch.setattr(settings, "CALL_SILENCE_REPROMPT_S", 0.3, raising=False)
    monkeypatch.setattr(settings, "CALL_SILENCE_HANGUP_S", 0.6, raising=False)
    s = _session(db, telephony_setup)
    s.websocket = ClosableWebSocket()
    s._last_activity = 0.0
    watchdog = asyncio.create_task(s._watchdog())
    try:
        await _until(lambda: s._reprompted, timeout=10)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        # A noise burst on the line: the endpointer briefly thinks it's speech, then drops it
        from app.runtime.telephony.endpointing import EndpointerEvent
        bursts = iter([[EndpointerEvent(kind="speech_start")], [EndpointerEvent(kind="speech_discarded")]])
        monkeypatch.setattr(s.endpointer, "process", lambda pcm: next(bursts, []))
        await s.handle_carrier_audio(b"\x01\x00" * 160)
        await s.handle_carrier_audio(b"\x01\x00" * 160)
        await s.execute_turn(b"\x01\x00" * 320)  # noise that reached transcription: no words
        await _until(lambda: s.websocket.closed, timeout=10)
        from app.runtime.telephony import phrases
        reprompts = [t for t in fakes["tts"].spoken if t in phrases.variants("reprompt", s._language())]
        assert len(reprompts) == 1
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


# ---------------------------------------------------------------------------
# Per-agent call limits (conversation.limits) override the platform defaults
# ---------------------------------------------------------------------------

def _set_limits(s, **values):
    # model_construct skips the dashboard bounds so tests can use sub-second timings
    s.context.agent_spec.conversation.limits = CallLimitsSpec.model_construct(**values)


def test_call_limits_fall_back_to_settings(monkeypatch):
    monkeypatch.setattr(settings, "CALL_MAX_DURATION_S", 600, raising=False)
    monkeypatch.setattr(settings, "VOICE_MAX_REPLY_CHARS", 280, raising=False)
    defaults = resolve_call_limits(None)
    assert (defaults.max_call_duration_s, defaults.max_reply_chars, defaults.max_tool_rounds) == (600, 280, DEFAULT_MAX_TOOL_ROUNDS)
    assert defaults.end_call_phrases == ()


def test_end_call_phrase_matching():
    limits = resolve_call_limits(None).__class__(600, 8, 8, 280, 4, ("not interested", "bye"))
    assert limits.matches_end_call_phrase("Not interested!")
    assert limits.matches_end_call_phrase("okay bye")
    assert not limits.matches_end_call_phrase("I am not interested in 2BHK, show me 3BHK instead")
    assert not limits.matches_end_call_phrase("byepass road")


@pytest.mark.asyncio
async def test_agent_silence_limits_override_settings(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "CALL_SILENCE_REPROMPT_S", 999, raising=False)
    monkeypatch.setattr(settings, "CALL_SILENCE_HANGUP_S", 999, raising=False)
    s = _session(db, telephony_setup)
    _set_limits(s, silence_reprompt_s=0.3, silence_hangup_s=0.3)
    s.websocket = ClosableWebSocket()
    s._last_activity = 0.0
    watchdog = asyncio.create_task(s._watchdog())
    try:
        await _until(lambda: s.websocket.closed, timeout=10)
        assert s._end_reason == "caller_silent"
    finally:
        watchdog.cancel()
        await _shutdown(s)


@pytest.mark.asyncio
async def test_agent_max_call_duration_ends_call(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "CALL_MAX_DURATION_S", 0, raising=False)
    s = _session(db, telephony_setup)
    _set_limits(s, max_call_duration_s=60)
    s.websocket = ClosableWebSocket()
    s.t_call_start -= 120
    watchdog = asyncio.create_task(s._watchdog())
    try:
        await _until(lambda: s.websocket.closed, timeout=10)
        assert s._end_reason == "max_duration"
    finally:
        watchdog.cancel()
        await _shutdown(s)


@pytest.mark.asyncio
async def test_end_call_phrase_hangs_up_without_llm(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    _set_limits(s, end_call_phrases=["not interested"])
    s.websocket = ClosableWebSocket()
    fakes["stt"].transcripts[640] = "Sorry, not interested."
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s.websocket.closed, timeout=10)
        assert s._end_reason == "end_call_phrase"
        assert fakes["llm"].calls == []
        assert " ".join(fakes["tts"].spoken) == s._farewell()  # spoken sentence by sentence
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_long_sentence_with_end_call_phrase_keeps_talking(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    _set_limits(s, end_call_phrases=["not interested"])
    fakes["llm"].replies = ["Sure, let me check 3BHK options."]
    fakes["stt"].transcripts[640] = "I am not interested in 2BHK, show me 3BHK options please"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert len(fakes["llm"].calls) == 1
        assert s._end_reason is None
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_agent_reply_cap_overrides_settings(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_MAX_REPLY_CHARS", 1000, raising=False)
    s = _session(db, telephony_setup)
    _set_limits(s, max_reply_chars=40)
    fakes["llm"].replies = ["We have a lovely flat in Whitefield today. It has two bedrooms. It also has a pool."]
    fakes["stt"].transcripts[640] = "Tell me everything"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert fakes["tts"].spoken == ["We have a lovely flat in Whitefield today."]
    finally:
        await _shutdown(s)


class ToolLoopLLM(FakeLLM):
    """Keeps asking for a tool while tools are offered; answers in text once they're withheld."""
    def generate_stream(self, system_instruction, messages, available_tools=None, temperature=0.7, model=None):
        self.calls.append(messages)
        if available_tools:
            yield LLMResult(text="", finish_reason="tool_calls", usage={},
                            tool_calls=[ToolCallRequest(id=f"t{len(self.calls)}", tool_name="lookup", arguments={})])
        else:
            yield "Here is what I found. "
            yield LLMResult(text="Here is what I found.", finish_reason="stop", usage={})


@pytest.mark.asyncio
async def test_agent_max_tool_rounds_limits_llm_calls(db: Session, telephony_setup, fakes, monkeypatch):
    llm = ToolLoopLLM([])
    monkeypatch.setattr(default_registry, "get_llm", lambda name: llm)
    s = _session(db, telephony_setup)
    _set_limits(s, max_tool_rounds=1)
    fakes["stt"].transcripts[640] = "Find me a flat"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert len(llm.calls) == 2  # one tool round, then a final answer without tools
        # A filler covers the silence while the tool runs, then the answer
        from app.runtime.telephony import phrases
        filler, answer = fakes["tts"].spoken
        assert filler in phrases.variants("tool_filler", s._language()) and answer == "Here is what I found."
        assert filler not in " ".join(_assistant_messages(s))  # fillers never enter the conversation history
    finally:
        await _shutdown(s)
