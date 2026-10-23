from abc import abstractmethod
from typing import Any, Callable, Optional
from app.runtime.providers.base import BaseProvider, TranscriptResult


class STTProvider(BaseProvider):
    """Abstract interface for Speech-to-Text providers."""

    @abstractmethod
    def start_stream(self) -> None:
        """Start audio streaming session."""
        pass

    @abstractmethod
    def process_audio(self, audio_data: Any) -> TranscriptResult:
        """Process incoming audio frame/chunk and return transcription result."""
        pass

    @abstractmethod
    def end_stream(self) -> TranscriptResult:
        """End streaming and return final transcript."""
        pass

    async def process_audio_async(self, audio_data: Any) -> TranscriptResult:
        """Asynchronously process audio data and return transcript result."""
        return self.process_audio(audio_data)

    async def create_stream(
        self,
        on_partial: Optional[Callable[[str], Any]] = None,
        on_final: Optional[Callable[[str], Any]] = None
    ) -> Any:
        """
        Creates an active realtime streaming session if supported by provider.
        Returns a streaming session object with send_audio, finish, and close methods,
        or None to fall back to buffered audio processing.
        """
        return None
