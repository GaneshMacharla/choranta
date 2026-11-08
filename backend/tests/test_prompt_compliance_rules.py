"""
Prompt fixes from the Sarvam prompt-compliance test (Ananya, 45 conversations):
- naming a tool the agent can't use made Sarvam return empty replies (refunds, complaints)
- English callers were answered in Telugu ("switch only if the caller clearly speaks it")
- the agent claimed to be human, re-asked what the caller had said, and asked several questions per reply
"""
from app.runtime import call_rules
from app.runtime.context import RuntimeContext, without_unavailable_tools
from app.schemas.agent_spec import LanguagesSpec, ToolsSpec
from test_phase3c_telephony import _build_test_agent_spec


def _context(spec):
    return RuntimeContext("s", "a", "c", "v", spec, {"origin": "internal_test_lab", "is_test": True})


def test_unusable_tools_are_not_named_in_the_prompt():
    text = ("- For refunds or complaints, book a callback with a senior counsellor using schedule_callback.\n"
            "- Before ending, save the enquiry with create_lead: background and goal.\n"
            "- Use `get_lead_details` when needed.")
    cleaned = without_unavailable_tools(text, live_tools=[], enabled_tools=["schedule_callback", "create_lead"])
    assert "schedule_callback" not in cleaned and "create_lead" not in cleaned and "get_lead_details" not in cleaned
    assert "book a callback with a senior counsellor." in cleaned
    assert "save the enquiry: background and goal." in cleaned
    assert "get lead details" in cleaned


def test_tools_the_agent_can_use_stay_named():
    text = "Book it with knowledge_lookup."
    assert without_unavailable_tools(text, live_tools=["knowledge_lookup"], enabled_tools=["knowledge_lookup"]) == text


def test_agent_without_booking_tools_is_told_the_team_confirms():
    spec = _build_test_agent_spec()
    spec.instructions.escalation_rules = ["For refunds, book a callback with a senior counsellor using schedule_callback."]
    spec.tools = ToolsSpec(enabled=["schedule_callback", "create_lead"])  # both switched off platform-wide
    prompt = _context(spec).conversation.system_instruction
    assert "schedule_callback" not in prompt and "create_lead" not in prompt
    assert "you can't book, register or save anything yourself" in prompt
    assert "Never say it is already booked" in prompt


def test_caller_language_is_followed():
    spec = _build_test_agent_spec()
    spec.languages = LanguagesSpec(primary="te", supported=["te", "hi", "en-IN"])
    prompt = _context(spec).conversation.system_instruction
    assert "Language: your greeting is in Telugu" in prompt
    assert "always reply in the language of the caller's latest message (Telugu, Hindi, English)" in prompt
    assert "clearly speaks" not in prompt


def test_english_agent_with_other_languages_also_follows_the_caller():
    spec = _build_test_agent_spec()
    spec.languages = LanguagesSpec(primary="en", supported=["en", "te"])
    assert "latest message (English, Telugu)" in _context(spec).conversation.system_instruction


def test_caller_language_is_detected():
    from app.runtime.greeting_language import detect_language
    assert detect_language("I want to learn data science, which course is good for me?") == "en"
    assert detect_language("నాకు Python course గురించి తెలుసుకోవాలి") == "te"
    assert detect_language("मुझे Java course के बारे में जानना है") == "hi"
    assert detect_language("naaku python course gurinchi telusukovali") is None  # romanised Telugu isn't English
    assert detect_language("ok") is None  # too short to tell


def test_each_reply_names_the_callers_language_when_supported():
    spec = _build_test_agent_spec()
    spec.languages = LanguagesSpec(primary="te", supported=["te", "hi", "en-IN"])
    ctx = _context(spec)
    ctx.conversation.add_user_message("I want to learn data science, which course is good for me?")
    assert ctx.instruction_for_turn().rstrip().endswith("The caller's latest message is in English: reply in English.")
    ctx.conversation.add_user_message("மேலும் சொல்லுங்கள்")  # Tamil: not one of this agent's languages
    assert "The caller's latest message is in" not in ctx.instruction_for_turn()


def test_sarvam_empty_reply_is_asked_again(monkeypatch):
    from app.runtime.providers.base import LLMResult
    from app.runtime.providers.sarvam.llm import SarvamLLMProvider
    replies = iter([
        [LLMResult(text=None, tool_calls=[], usage={"input_tokens": 100, "output_tokens": 20})],
        ["Hello", LLMResult(text="Hello", tool_calls=[], usage={"input_tokens": 100, "output_tokens": 5})],
    ])
    provider = SarvamLLMProvider(api_key="test")
    monkeypatch.setattr(provider, "_stream_once", lambda *a, **k: iter(next(replies)))
    items = list(provider.generate_stream("system", [{"role": "user", "content": "refund please"}]))
    assert items[0] == "Hello" and items[-1].text == "Hello"
    assert items[-1].usage == {"input_tokens": 200, "output_tokens": 25}  # both attempts are counted


def test_sarvam_gives_up_after_one_retry(monkeypatch):
    from app.runtime.providers.base import LLMResult
    from app.runtime.providers.sarvam.llm import SarvamLLMProvider
    calls = []
    provider = SarvamLLMProvider(api_key="test")
    monkeypatch.setattr(provider, "_stream_once", lambda *a, **k: calls.append(1) or iter([LLMResult(text=None, tool_calls=[])]))
    items = list(provider.generate_stream("system", [{"role": "user", "content": "hi"}]))
    assert len(calls) == 2 and items[-1].text is None  # the runtime's fallback line takes over


def test_sarvam_uses_the_configured_temperature(monkeypatch):
    from app.core.config import settings
    from app.runtime.providers.sarvam.llm import SarvamLLMProvider
    sent = {}
    provider = SarvamLLMProvider(api_key="test")
    monkeypatch.setattr(settings, "SARVAM_TEMPERATURE", 0.3)
    monkeypatch.setattr(provider, "_open_stream", lambda payload: sent.update(payload) or (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr(provider, "initialize", lambda config: None)
    monkeypatch.setattr(SarvamLLMProvider, "_can_fall_back", staticmethod(lambda: False))
    try:
        list(provider.generate_stream("system", [{"role": "user", "content": "hi"}]))
    except RuntimeError:
        pass
    assert sent["temperature"] == 0.3


def test_english_only_agent_gets_no_language_line():
    assert "Language:" not in _context(_build_test_agent_spec()).conversation.system_instruction


def test_every_reply_rules_cover_length_honesty_and_handoff():
    text = call_rules.rules_text(_build_test_agent_spec())
    assert "Reply in the language of the caller's last message" in text
    assert "Before any goodbye, tell the caller what happens next" in text
    assert "Otherwise don't bring it up" in text
    assert "At most two short sentences and only one question" in text
    assert "give the two that matter most and offer the rest" in text
    assert "Never carry a date, fee or timing over from a different course or batch" in text
    assert "Never adapt another listing to fit" in text
    assert "Answer what the caller just asked first" in text
    assert "Never ask again for something the caller already told you" in text
    assert "you are Choranta Health's AI assistant, never human" in text
    assert "If the caller asks for a real person: never say you are one" in text
    assert call_rules.RULES_MARKER in text
