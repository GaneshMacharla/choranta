from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TranscriptResult(BaseModel):
    text: str
    is_final: bool = True
    confidence: float = 1.0


class ToolCallRequest(BaseModel):
    id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    thought_signature: Optional[str] = None


class LLMResult(BaseModel):
    text: Optional[str] = None
    tool_calls: List[ToolCallRequest] = Field(default_factory=list)
    finish_reason: str = "stop"  # "stop", "tool_calls", "length"
    usage: Dict[str, Any] = Field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


class AudioResult(BaseModel):
    audio_bytes: bytes = b""
    format: str = "pcm_s16le"
    duration_seconds: float = 0.0


class BaseProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def environment(self) -> str:
        """development/test or production"""
        pass

    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass
