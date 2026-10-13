"""
Rules every AI employee follows on every channel (phone, browser voice, test chat): stay on the business's
topic, and end the conversation with the end_call tool, both when it is complete and as soon as the caller
talks about something unrelated to the business.
"""
from typing import Any, Dict, List, Optional

END_CALL_TOOL_NAME = "end_call"
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
        "\n\n" + RULES_MARKER + "\n"
        f"- Only talk about {business} and how it can help the caller. Greetings, small pleasantries and questions "
        "about who you are are fine.\n"
        f"- If the caller talks about anything unrelated to {business} (other topics, jokes, requests you can't serve, "
        "abuse, or meaningless input after you have asked once to repeat), do not answer it. Say one short sentence, "
        f"for example \"Sorry, I can only help with {business} enquiries. Goodbye!\", and immediately call the "
        f"{END_CALL_TOOL_NAME} tool.\n"
        f"- When the conversation is complete or the caller wants to stop, say a brief goodbye and call the "
        f"{END_CALL_TOOL_NAME} tool. After saying goodbye, never keep the conversation going."
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


def goodbye_text(spec: Any, said: Optional[str] = None) -> str:
    """What the AI employee says when hanging up: its own words, else the agent's farewell."""
    if said and said.strip():
        return said.strip()
    farewell = getattr(getattr(spec, "conversation", None), "farewell", None)
    return (farewell or "").strip() or DEFAULT_GOODBYE
