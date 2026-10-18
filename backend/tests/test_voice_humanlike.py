"""Human-like phone conversations: waiting for the caller to finish, speakable text, fillers, localized lines."""
import asyncio
import inspect

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.conversation import ConversationState
from app.runtime.speech_style import VOICE_STYLE_MARKER, apply_voice_style
from app.runtime.telephony import phrases
from app.runtime.telephony.session import TelephonyMediaSession
from app.runtime.telephony.speech_text import clean_for_speech, looks_incomplete, normalize_for_speech
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_telephony_realtime import (  # noqa: F401
    SlowLLM, _assistant_messages, _events, _session, _shutdown, _until, fakes,
)


# ---------------------------------------------------------------------------
# Has the caller finished?
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["my budget is", "నా నంబర్ 98480", "ante…", "I was thinking, um", "aur", "Sure,"])
def test_trailing_off_looks_incomplete(text):
    assert looks_incomplete(text)


@pytest.mark.parametrize("text", ["yes, Tuesday works", "9848012345", "theek hai", "Monday at 5", "in 2026", ""])
def test_finished_thoughts_look_complete(text):
    assert not looks_incomplete(text)


# ---------------------------------------------------------------------------
# Speakable text
# ---------------------------------------------------------------------------

def test_amounts_phone_numbers_and_dates_are_speakable():
    assert normalize_for_speech("Price is ₹75,00,000 only.") == "Price is 75 lakh rupees only."
    assert normalize_for_speech("₹2,50,00,000") == "2.5 crore rupees"
    assert normalize_for_speech("Fee is Rs. 1,500.") == "Fee is 1,500 rupees."
    assert normalize_for_speech("Rs 75 lakhs") == "75 lakh rupees"
    assert normalize_for_speech("Call +91 98480 12345") == "Call 9 8 4 8 0, 1 2 3 4 5"
    assert normalize_for_speech("Starts 19/10/2026") == "Starts 19 October 2026"
    assert normalize_for_speech("Starts 2026-10-19") == "Starts 19 October 2026"
    assert normalize_for_speech("50% off & free demo") == "50 percent off and free demo"
    assert normalize_for_speech("Budget is 60 - 80 lakh.") == "Budget is 60 - 80 lakh."
    assert clean_for_speech("**Fee:** ₹1,500") == "Fee: 1,500 rupees"


# ---------------------------------------------------------------------------
# Localized, varied lines
# ---------------------------------------------------------------------------

def test_phrases_follow_the_agent_language_and_never_repeat_back_to_back():
    assert phrases.pick("reprompt", "te-IN") in phrases.PHRASES["reprompt"]["te"]
    assert phrases.pick("reprompt", "hi") in phrases.PHRASES["reprompt"]["hi"]
    assert phrases.pick("reprompt", "xx") in phrases.PHRASES["reprompt"]["en"]  # unknown language: English
    history = {}
    said = [phrases.pick("tool_filler", "en", history) for _ in range(30)]
    assert all(a != b for a, b in zip(said, said[1:]))


def test_voice_style_is_added_once_and_used_by_browser_test_calls():
    from app.api.routes import websocket_audio

    conversation = ConversationState(system_instruction="You are Anjali.")
    spec = type("Spec", (), {"business_context": None, "identity": None})()
    apply_voice_style(conversation, spec)
    apply_voice_style(conversation, spec)
    assert conversation.system_instruction.count(VOICE_STYLE_MARKER) == 1
    assert "contractions" in conversation.system_instruction
    # The audio WebSocket runs on the phone session, which applies the voice style
    assert issubclass(websocket_audio.WebSocketMediaSession, TelephonyMediaSession)
    assert "apply_voice_style(self.context.conversation" in inspect.getsource(TelephonyMediaSession)


# ---------------------------------------------------------------------------
# Phone session behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_waits_when_caller_trails_off_and_answers_the_whole_thought(
    db: Session, telephony_setup, fakes, monkeypatch
):
    monkeypatch.setattr(settings, "VOICE_INCOMPLETE_HOLD_MS", 400, raising=False)
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["Got it, fifty lakh."]
    fakes["stt"].transcripts[640] = "My budget is"
    fakes["stt"].transcripts[960] = "around fifty lakh"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await asyncio.sleep(0.15)                  # still holding: nothing said yet
        assert fakes["llm"].calls == [] and fakes["tts"].spoken == []
        await s.execute_turn(b"\x00\x00" * 480)    # the caller carries on
        await _until(lambda: bool(fakes["tts"].spoken) and s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert len(fakes["llm"].calls) == 1
        users = [m.content for m in s.context.conversation.messages if m.role.value == "user"]
        assert users[-1] == "My budget is around fifty lakh"
        assert fakes["tts"].spoken == ["Got it, fifty lakh."]
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_complete_answer_gets_a_reply_without_waiting(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_INCOMPLETE_HOLD_MS", 5000, raising=False)
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["Okay, Tuesday it is."]
    fakes["stt"].transcripts[640] = "Tuesday works for me."
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=2)
        assert fakes["tts"].spoken == ["Okay, Tuesday it is."]
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_slow_reply_gets_a_short_acknowledgement_kept_out_of_history(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_SLOW_REPLY_ACK_MS", 100, raising=False)
    llm = SlowLLM([])
    from app.runtime.providers.registry import default_registry
    monkeypatch.setattr(default_registry, "get_llm", lambda name: llm)
    s = _session(db, telephony_setup)
    fakes["stt"].transcripts[640] = "What are the fees?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        ack, answer = fakes["tts"].spoken
        assert ack in phrases.variants("slow_ack", s._language()) and answer == "Here you go."
        assert _assistant_messages(s)[-1] == "Here you go."
        assert _events(s, "TTS_STARTED")[-1]["first_audio_filler"] == "slow_ack"
        assert s.conversation_quality()["fillers_played"]["slow_ack"] == 1
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_fast_reply_has_no_acknowledgement_and_logs_latency(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_SLOW_REPLY_ACK_MS", 2000, raising=False)
    s = _session(db, telephony_setup)
    fakes["llm"].replies = ["Sure, the fee is 1,500 rupees."]
    fakes["stt"].transcripts[640] = "What are the fees?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: s._turn_task is not None and s._turn_task.done(), timeout=10)
        assert fakes["tts"].spoken == ["Sure, the fee is 1,500 rupees."]
        started = _events(s, "TTS_STARTED")[-1]
        assert started["first_audio_filler"] == "none" and started["response_latency_ms"] is not None
        quality = s.conversation_quality()
        assert quality["turns"] == 1 and quality["avg_response_latency_ms"] is not None
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_telugu_agent_reprompts_in_telugu(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "CALL_SILENCE_REPROMPT_S", 0.2, raising=False)
    monkeypatch.setattr(settings, "CALL_SILENCE_HANGUP_S", 999, raising=False)
    s = _session(db, telephony_setup)
    s.context.agent_spec.languages.primary = "te"
    s._last_activity = 0.0
    watchdog = asyncio.create_task(s._watchdog())
    try:
        await _until(lambda: bool(fakes["tts"].spoken), timeout=10)
        assert fakes["tts"].spoken[0] in phrases.PHRASES["reprompt"]["te"]
    finally:
        watchdog.cancel()
        await _shutdown(s)


def test_every_agent_follows_greet_goal_close_and_knows_its_greeting_was_said():
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    spec = _build_test_agent_spec("agt_flow")
    spec.conversation.greeting = "Hello, I'm calling from {{company_name}} about our new batch. Do you have a minute?"
    spec.conversation.farewell = "Thanks, bye!"
    prompt = RuntimeContext("s", "a", "c", "v", spec, {"company_name": "Kundhanasai"}).conversation.system_instruction
    flow = prompt.split("Call Flow", 1)[1]
    assert "ALREADY DONE" in flow and "calling from Kundhanasai about our new batch" in flow
    steps = ["1. Greeting", "2. Reason", "3. Understand", "4. Offer", "5. Questions", "6. Next step", "7. Confirm and close"]
    assert [flow.index(step) for step in steps] == sorted(flow.index(step) for step in steps)
    assert "at most two choices" in flow and "read the booked details back" in flow
    assert "Thanks, bye!" in flow

    spec.conversation.greeting = ""
    prompt = RuntimeContext("s", "a", "c", "v", spec, {}).conversation.system_instruction
    assert "greet the caller once" in prompt.split("Call Flow", 1)[1]


@pytest.mark.parametrize("metadata, phone", [
    ({"origin": "telephony_outbound", "destination": "+918008538015", "caller": "+914045209348"}, "+918008538015"),
    ({"origin": "telephony_inbound", "caller": "+919848012345", "destination": "+914045209348"}, "+919848012345"),
    ({"origin": "internal_test_lab"}, "+910000000000"),
])
def test_phone_calls_never_ask_for_the_known_number(metadata, phone):
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    ctx = RuntimeContext("s", "a", "c", "v", _build_test_agent_spec("agt_phone"), {**metadata, "user_name": "Ravi"})
    prompt = ctx.instruction_for_turn()  # what the LLM is sent
    assert f"Phone number: {phone}. Never ask the caller for their phone number" in prompt
    assert "Name: Ravi. Don't ask for their name again" in prompt
    # The number (and name) fill booking / lead tools when the agent leaves them out
    assert ctx.with_contact_details("book_appointment", {"slot": "Mon 9 AM"}) == {
        "slot": "Mon 9 AM", "contact_phone": phone, "phone": phone, "customer_name": "Ravi", "name": "Ravi",
    }
    assert ctx.with_contact_details("create_lead", {"name": "R", "phone": "+911111111111"})["phone"] == "+911111111111"
    assert ctx.with_contact_details("check_availability", {"date": "Mon"}) == {"date": "Mon"}


def test_text_chat_without_a_call_has_no_contact_section():
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    ctx = RuntimeContext("s", "a", "c", "v", _build_test_agent_spec("agt_phone"), {})
    assert ctx.contact_phone is None and "Caller Contact" not in ctx.conversation.system_instruction


def test_outbound_calls_check_the_time_and_handoff_matches_the_agents_tools():
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    spec = _build_test_agent_spec("agt_outbound")
    spec.tools.enabled = ["schedule_callback"]
    outbound = RuntimeContext("s", "a", "c", "v", spec, {"origin": "telephony_outbound", "destination": "+918008538015",
                                                          "course_enquired": "Snowflake"})
    prompt = outbound.conversation.system_instruction
    assert "2. Good time?" in prompt and "2. Reason" not in prompt
    assert "book a callback with the team instead of guessing" in prompt

    spec.tools.enabled = []
    inbound = RuntimeContext("s", "a", "c", "v", spec, {"origin": "telephony_inbound", "caller": "+919848012345"})
    assert "say a team member will call them back" in inbound.conversation.system_instruction


def test_voice_style_limits_choices_and_confirms_before_booking():
    from app.runtime.speech_style import VOICE_STYLE_INSTRUCTIONS

    assert "at most two choices" in VOICE_STYLE_INSTRUCTIONS
    assert "read the key details back" in VOICE_STYLE_INSTRUCTIONS


@pytest.mark.parametrize("text, hint", [
    ("అంతే ఒకసారి కౌన్సిలర్ని.", "weak"),   # speech-to-text's full stop is ignored; the verb is still to come
    ("office ko", "weak"),
    ("my budget is.", "strong"),
    ("అంటే", "strong"),
    ("Fresher.", None),
    ("Okay. Thank you.", None),
    ("చెప్పండి.", None),
])
def test_pause_hint_strength(text, hint):
    from app.runtime.telephony.speech_text import pause_hint
    assert pause_hint(text) == hint


def test_tools_offer_two_well_spaced_choices():
    from app.runtime.tools.executor import offer_two_choices

    out = offer_two_choices({"date": "Mon", "slots": ["9 AM", "10 AM", "2:30 PM"], "notes": ["a", "b", "c"]})
    assert out["slots"] == ["9 AM", "2:30 PM"] and out["slots_only_if_asked"] == ["10 AM"]
    assert out["notes"] == ["a", "b", "c"]  # not a list of choices
    assert offer_two_choices({"slots": ["9 AM", "2 PM"]}) == {"slots": ["9 AM", "2 PM"]}


def test_farewell_is_said_in_the_call_language(monkeypatch):
    from app.runtime import context as context_module
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    monkeypatch.setattr(context_module, "localize_greeting",
                        lambda text, lang, keep=(): f"[{lang}] {text}" if lang == "te" else text)
    spec = _build_test_agent_spec("agt_bye")
    spec.languages.primary = "te"
    spec.languages.supported = ["te", "en-IN"]
    spec.conversation.farewell = "Thanks for your time, {{company_name}} wishes you well!"
    ctx = RuntimeContext("s", "a", "c", "v", spec, {"company_name": "Kundhanasai"})
    assert ctx.resolved_farewell == "[te] Thanks for your time, Kundhanasai wishes you well!"
    assert ctx.resolved_farewell in ctx.conversation.system_instruction


def test_call_script_drives_understand_offer_and_next_step():
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    spec = _build_test_agent_spec("agt_script")
    spec.instructions.discovery_questions = ["Online or classroom?", "Weekday or weekend?"]
    spec.instructions.offer_points = ["Batch starts Monday", "Real projects"]
    spec.instructions.next_step = "Book a free demo class"
    flow = RuntimeContext("s", "a", "c", "v", spec, {}).conversation.system_instruction.split("Call Flow", 1)[1]
    assert '"Online or classroom?" | "Weekday or weekend?"' in flow
    assert "Batch starts Monday | Real projects" in flow
    assert "6. Next step - propose: Book a free demo class." in flow

    spec.instructions.discovery_questions, spec.instructions.offer_points, spec.instructions.next_step = [], [], ""
    flow = RuntimeContext("s", "a", "c", "v", spec, {}).conversation.system_instruction.split("Call Flow", 1)[1]
    assert "Core Responsibilities need" in flow  # no script: the general wording


def test_every_template_has_a_valid_call_script():
    from app.schemas.agent_spec import AgentConfigurationData
    from app.services.agent_templates import get_all_agent_templates

    for tpl in get_all_agent_templates(include_hidden=True):
        cfg = AgentConfigurationData(**tpl["default_config"])
        assert cfg.instructions.discovery_questions and cfg.instructions.next_step, tpl["id"]
