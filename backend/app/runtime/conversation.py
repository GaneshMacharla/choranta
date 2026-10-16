import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Raw tool results are kept for this many recent caller turns (follow-ups like "and the second one?" need them)
KEEP_TOOL_TURNS = 3
# Agent replies older than this many caller turns are cut to their first sentence (only matters on long calls)
KEEP_FULL_TURNS = 10

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s")


def _first_sentence(text: str) -> str:
    return _SENTENCE_END.split((text or "").strip(), maxsplit=1)[0]


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        pruned = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in pruned.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def compact_json(data: Any) -> str:
    """A tool result as the model reads it: no empty fields or padding, and Indian-language text as-is
    (escaped \\uXXXX text costs several times the tokens)."""
    return json.dumps(_prune(data), ensure_ascii=False, separators=(",", ":"), default=str)


class ConversationRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ConversationMessage(BaseModel):
    role: ConversationRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ConversationState:
    """
    Maintains the ephemeral conversation history for an active RuntimeSession.
    Does NOT mutate or persist back into the immutable AgentSpec.
    """

    def __init__(self, system_instruction: str = ""):
        self.system_instruction = system_instruction
        self.messages: List[ConversationMessage] = []
        if system_instruction.strip():
            self.messages.append(
                ConversationMessage(
                    role=ConversationRole.SYSTEM,
                    content=system_instruction.strip()
                )
            )

    def add_user_message(self, content: str) -> ConversationMessage:
        msg = ConversationMessage(
            role=ConversationRole.USER,
            content=content
        )
        self.messages.append(msg)
        return msg

    def add_assistant_message(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None
    ) -> ConversationMessage:
        msg = ConversationMessage(
            role=ConversationRole.ASSISTANT,
            content=content or "",
            tool_calls=tool_calls
        )
        self.messages.append(msg)
        return msg

    def add_tool_result(self, tool_call_id: str, content: str, tool_name: Optional[str] = None) -> ConversationMessage:
        msg = ConversationMessage(
            role=ConversationRole.TOOL,
            content=content,
            name=tool_name,
            tool_call_id=tool_call_id
        )
        self.messages.append(msg)
        return msg

    def to_llm_messages(self) -> List[Dict[str, Any]]:
        """
        The history sent with each reply, kept lean because every message is paid for again on every turn:
        - Tool calls and their raw results from before the last KEEP_TOOL_TURNS caller turns are dropped (what the
          agent said about them stays, as it was spoken).
        - On long calls, the agent's replies from before the last KEEP_FULL_TURNS caller turns are cut to their
          first sentence. Everything the caller said is always kept word for word.
        """
        user_positions = [i for i, m in enumerate(self.messages) if m.role == ConversationRole.USER]
        tool_boundary = user_positions[-KEEP_TOOL_TURNS] if len(user_positions) >= KEEP_TOOL_TURNS else 0
        full_boundary = user_positions[-KEEP_FULL_TURNS] if len(user_positions) > KEEP_FULL_TURNS else 0

        result = []
        for i, m in enumerate(self.messages):
            if i < tool_boundary and m.role == ConversationRole.TOOL:
                continue
            if i < tool_boundary and m.role == ConversationRole.ASSISTANT and m.tool_calls:
                if m.content.strip():
                    result.append({"role": m.role.value, "content": _first_sentence(m.content) if i < full_boundary else m.content})
                continue
            if i < full_boundary and m.role == ConversationRole.ASSISTANT:
                result.append({"role": m.role.value, "content": _first_sentence(m.content)})
                continue
            item: Dict[str, Any] = {
                "role": m.role.value,
                "content": m.content,
            }
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
            if m.tool_calls:
                item["tool_calls"] = m.tool_calls
            result.append(item)
        return result
