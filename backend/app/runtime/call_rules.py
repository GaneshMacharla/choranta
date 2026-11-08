"""
Rules every AI employee follows on every channel (phone, browser voice, test chat): stay on the business's
topic, and end the conversation with the end_call tool, both when it is complete and as soon as the caller
talks about something unrelated to the business.
"""
import re
from typing import Any, Dict, List, Optional

END_CALL_TOOL_NAME = "end_call"

# The caller is wrapping up (English, Telugu, Hindi and their Romanised forms): hanging up then is fine
_CLOSING = re.compile(
    r"\b(bye|goodbye|good bye|not interested|no thanks|no thank you|don'?t call|stop calling|that'?s all|nothing else|"
    r"thank you|thanks|later|busy|vaddu|chalu|dhanyavad\w*|shukriya|nahi chahiye|bas)\b"
    r"|బై|ధన్యవాద|థాంక్స్|వద్దు|అవసరం లేదు|చాలు|తర్వాత|बाय|धन्यवाद|शुक्रिया|नहीं चाहिए|बस|बाद में",
    re.IGNORECASE,
)
# Told to the AI employee when it tries to hang up on a caller who hasn't finished (it may hang up next time)
END_CALL_REFUSED = (
    "Not ended: the caller hasn't said goodbye or asked to stop. In one or two short sentences tell them what happens "
    "next (for example, our team will call to confirm) and ask if there's anything else. If they were off topic or "
    "abusive, just say a brief goodbye and call end_call again."
)
END_CALL_TOOL: Dict[str, Any] = {
    "name": END_CALL_TOOL_NAME,
    "id": END_CALL_TOOL_NAME,
    "description": "Hang up the call. Use right after a one-sentence goodbye: when the conversation is complete, "
                   "the caller asks to end it, or the caller talks about something unrelated to the business.",
    "input_schema": {"type": "object", "properties": {"reason": {"type": "string", "description": "Why the call is ending (e.g. completed, caller_request, off_topic)"}}},
}

RULES_MARKER = "Staying on topic and ending calls:"
DEFAULT_GOODBYE = "Thank you for calling. Goodbye!"


def business_name(spec: Any) -> str:
    """The business the AI employee works for, for use in the rules."""
    for value in (
        getattr(getattr(spec, "business_context", None), "business_name", None),
        getattr(getattr(spec, "identity", None), "organization", None),
    ):
        if value and "{{" not in str(value):
            return str(value)
    return "this business"


def rules_text(spec: Any) -> str:
    business = business_name(spec)
    return (
        "\n\nEvery reply:\n"
        "- Reply in the language of the caller's last message: English gets an English reply, Hindi a Hindi reply, "
        "Telugu a Telugu reply.\n"
        "- At most two short sentences and only one question, like a telecaller on the phone: the key fact in one "
        "sentence (\"It's Rs 30,000, and the next batch starts 17 November.\"), then your question. Leave extras such "
        "as EMI or exact timings until they ask.\n"
        "- Answer what the caller just asked first (or say you'll check with the team), then ask your next question. "
        "Asked several things at once: give the two that matter most and offer the rest (\"Shall I tell you the "
        "timings too?\").\n"
        "- Fees, dates and timings: copy them exactly from the line for that same course and batch in your Business "
        "knowledge. Never carry a date, fee or timing over from a different course or batch.\n"
        "- If the course, batch or option the caller asks for isn't listed (e.g. a weekend batch for a course that "
        "only has a weekday one), say plainly there isn't one, then offer what is listed. Never adapt another listing "
        "to fit.\n"
        "- Never ask again for something the caller already told you on this call: if they said \"I'm a fresher\" or "
        "named the course, don't ask whether they are a student or which course; use it and move on.\n"
        f"- Only if the caller asks whether you are a person, a bot or an AI: say honestly that you are {business}'s AI "
        "assistant, never human. Otherwise don't bring it up.\n"
        "- If the caller asks for a real person: never say you are one; offer the handoff from your Call Flow "
        "(a team member will call them back).\n"
        "- Before any goodbye, tell the caller what happens next (e.g. our team will call to confirm their demo). "
        "Agreeing to a booking or registration is not a reason to hang up without saying that.\n"
        "\n" + RULES_MARKER + "\n"
        f"- Only talk about {business} and how it can help. Small talk and questions about you: a few friendly words, "
        "then steer back.\n"
        f"- Unrelated requests: don't answer; say kindly you can only help with {business} enquiries, steer back once.\n"
        "- Still off topic after that, abusive, or no sense after one request to repeat: one polite goodbye, then call "
        f"{END_CALL_TOOL_NAME}.\n"
        f"- When done or the caller wants to stop: a brief goodbye, then call {END_CALL_TOOL_NAME}; never continue after it."
    )


def apply_rules(conversation: Any, spec: Any) -> None:
    """Adds the rules to the conversation's system instruction once."""
    if RULES_MARKER in (conversation.system_instruction or ""):
        return
    conversation.system_instruction = (conversation.system_instruction or "") + rules_text(spec)
    messages = getattr(conversation, "messages", None)
    if messages and getattr(messages[0], "role", None) is not None and str(getattr(messages[0].role, "value", messages[0].role)).lower() == "system":
        messages[0].content = conversation.system_instruction.strip()


def with_end_call(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    tools = list(tools or [])
    if not any((t.get("name") or t.get("id")) == END_CALL_TOOL_NAME for t in tools):
        tools.append(END_CALL_TOOL)
    return tools


def wants_to_end(tool_calls: Optional[List[Any]]) -> bool:
    return any(getattr(tc, "tool_name", None) == END_CALL_TOOL_NAME for tc in (tool_calls or []))


def last_caller_text(conversation: Any) -> str:
    for message in reversed(getattr(conversation, "messages", None) or []):
        if str(getattr(message.role, "value", message.role)).lower() == "user":
            return message.content or ""
    return ""


def caller_is_closing(text: str) -> bool:
    return bool(_CLOSING.search(text or ""))


def refuse_early_end(conversation: Any, already_refused: bool, said: Optional[str] = None) -> bool:
    """
    Sarvam sometimes hangs up without a word mid-conversation (e.g. right after "online, weekends suit me"), losing
    the lead. Such a silent hang-up, while the caller isn't wrapping up, is refused once so the AI employee says what
    happens next. A hang-up with its own words (e.g. a polite goodbye to an off-topic caller) is left alone, and a
    second attempt always goes through, so a call can never be kept open against the agent's will.
    """
    if already_refused or (said or "").strip():
        return False
    return not caller_is_closing(last_caller_text(conversation))


def refuse_end_call(conversation: Any, text: Optional[str], tool_calls: List[Any]) -> None:
    """Records the refused hang-up in the conversation, so the next reply knows what to say instead."""
    import json

    conversation.add_assistant_message(content=text, tool_calls=[tc.model_dump() for tc in tool_calls])
    for tc in tool_calls:
        result = {"ok": False, "error": END_CALL_REFUSED} if tc.tool_name == END_CALL_TOOL_NAME else \
            {"ok": False, "error": "Not run: the call is still going. Ask for it again if you still need it."}
        conversation.add_tool_result(tool_call_id=tc.id, content=json.dumps(result), tool_name=tc.tool_name)


def goodbye_text(spec: Any, said: Optional[str] = None) -> str:
    """What the AI employee says when hanging up: its own words, else the agent's farewell."""
    if said and said.strip():
        return said.strip()
    farewell = getattr(getattr(spec, "conversation", None), "farewell", None)
    return (farewell or "").strip() or DEFAULT_GOODBYE
