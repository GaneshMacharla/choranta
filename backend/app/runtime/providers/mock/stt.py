import asyncio
from typing import Any, Callable, Dict, Optional
from app.runtime.providers.stt import STTProvider
from app.runtime.providers.base import TranscriptResult


class MockSTTStreamingSession:
    """Simulates real-time STT streaming with incremental partial transcripts for testing."""

    def __init__(
        self,
        target_text: str = "Hello, I want to book an appointment.",
        on_partial: Optional[Callable[[str], Any]] = None,
        on_final: Optional[Callable[[str], Any]] = None,
        partial_delay_seconds: float = 0.0,
        error_message: Optional[str] = None
    ):
        self._target_text = target_text
        self._on_partial = on_partial
        self._on_final = on_final
        self._bytes_received = 0
        self._closed = False
        self._words = target_text.split()
        self._step = 0
        self._partial_delay_seconds = partial_delay_seconds
        self._error_message = error_message

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._closed or not pcm_bytes:
            return
        if self._error_message:
            raise RuntimeError(self._error_message)
        if self._partial_delay_seconds:
            await asyncio.sleep(self._partial_delay_seconds)
        self._bytes_received += len(pcm_bytes)
        self._step += 1
        if self._words and self._on_partial:
            num_words = min(len(self._words), max(1, self._step))
            partial_text = " ".join(self._words[:num_words])
            res = self._on_partial(partial_text)
            if asyncio.iscoroutine(res):
                await res

    async def finish(self) -> TranscriptResult:
        if self._error_message:
            raise RuntimeError(self._error_message)
        if self._on_final:
            res = self._on_final(self._target_text)
            if asyncio.iscoroutine(res):
                await res
        return TranscriptResult(text=self._target_text, is_final=True, confidence=0.98)

    async def close(self) -> None:
        self._closed = True


class MockSTTProvider(STTProvider):
    """
    Deterministic Mock Speech-to-Text provider for testing runtime orchestration.
    ENVIRONMENT: development/test
    """

    def __init__(self, name: str = "mock_stt"):
        self._name = name
        self._initialized = False
        self._is_streaming = False
        self._buffered_text = "Hello, I want to book an appointment."
        self._partial_delay_seconds = 0.0
        self._error_message: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def environment(self) -> str:
        return "development/test"

    def initialize(self, config: Dict[str, Any]) -> None:
        self._initialized = True
        self.configure(config)

    def configure(self, config: Dict[str, Any]) -> None:
        if "transcript" in config:
            self._buffered_text = str(config["transcript"])
        self._partial_delay_seconds = max(0.0, float(config.get("partial_delay_seconds", self._partial_delay_seconds)))
        self._error_message = config.get("error_message")

    def start_stream(self) -> None:
        self._is_streaming = True

    def set_mock_transcript(self, text: str) -> None:
        """Helper for unit tests to inject desired transcript."""
        self._buffered_text = text

    def process_audio(self, audio_data: Any) -> TranscriptResult:
        if self._error_message:
            raise RuntimeError(self._error_message)
        if isinstance(audio_data, (bytes, bytearray)) and not audio_data:
            return TranscriptResult(text="", is_final=True, confidence=0.0)
        if isinstance(audio_data, str) and audio_data.strip():
            text = audio_data.strip()
        else:
            text = self._buffered_text
        return TranscriptResult(text=text, is_final=True, confidence=0.98)

    def end_stream(self) -> TranscriptResult:
        self._is_streaming = False
        return TranscriptResult(text=self._buffered_text, is_final=True, confidence=0.98)

    async def create_stream(
        self,
        on_partial: Optional[Callable[[str], Any]] = None,
        on_final: Optional[Callable[[str], Any]] = None
    ) -> MockSTTStreamingSession:
        return MockSTTStreamingSession(
            target_text=self._buffered_text,
            on_partial=on_partial,
            on_final=on_final,
            partial_delay_seconds=self._partial_delay_seconds,
            error_message=self._error_message
        )

    def close(self) -> None:
        self._is_streaming = False
        self._initialized = False
