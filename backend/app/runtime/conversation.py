from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
        result = []
        for m in self.messages:
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
