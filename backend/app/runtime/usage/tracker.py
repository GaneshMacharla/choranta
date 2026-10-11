from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SessionUsage(BaseModel):
    mode: str = "mock"
    simulated: bool = True
    llm_provider: Optional[str] = None
    stt_seconds: float = 0.0
    tts_seconds: float = 0.0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    session_duration_seconds: float = 0.0


class UsageTracker:
    """
    Accumulates runtime operational metrics for a voice session.
    Tracks raw usage without calculating financial costs/pricing.
    """

    def __init__(self, mode: str = "mock", llm_provider: Optional[str] = None):
        normalized_mode = "real" if mode == "provider" else mode
        self.usage = SessionUsage(
            mode=normalized_mode,
            simulated=normalized_mode == "mock",
            llm_provider=llm_provider
        )

    def record_stt(self, duration_seconds: float) -> None:
        self.usage.stt_seconds = round(self.usage.stt_seconds + max(0.0, duration_seconds), 2)

    def record_tts(self, duration_seconds: float) -> None:
        self.usage.tts_seconds = round(self.usage.tts_seconds + max(0.0, duration_seconds), 2)

    def record_llm(self, input_tokens: int, output_tokens: int) -> None:
        self.usage.llm_input_tokens += max(0, input_tokens)
        self.usage.llm_output_tokens += max(0, output_tokens)

    def record_session_duration(self, duration_seconds: float) -> None:
        self.usage.session_duration_seconds = round(max(0.0, duration_seconds), 2)

    def get_summary(self) -> Dict[str, Any]:
        return self.usage.model_dump()
