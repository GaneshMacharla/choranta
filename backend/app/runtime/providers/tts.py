from abc import abstractmethod
from typing import Any, Dict, Optional
from app.runtime.providers.base import BaseProvider, AudioResult


class TTSProvider(BaseProvider):
    """Abstract interface for Text-to-Speech synthesis providers."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None,
        language: Optional[str] = None
    ) -> AudioResult:
        """Synthesize text into audio representation."""
        pass

    async def synthesize_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None,
        language: Optional[str] = None
    ):
        """Asynchronously stream raw audio bytes chunks for the synthesized speech."""
        result = self.synthesize(text, voice_id=voice_id, speed=speed, pitch=pitch, emotion=emotion)
        chunk_size = 1024
        for i in range(0, len(result.audio_bytes), chunk_size):
            yield result.audio_bytes[i:i + chunk_size]

