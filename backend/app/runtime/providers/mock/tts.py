import asyncio
from typing import Any, Dict, Optional
from app.runtime.providers.tts import TTSProvider
from app.runtime.providers.base import AudioResult


class MockTTSProvider(TTSProvider):
    """
    Deterministic Mock Text-to-Speech provider for testing runtime orchestration.
    DOES NOT generate fake MP3 files pretending to be real TTS.
    ENVIRONMENT: development/test
    """

    def __init__(self, name: str = "mock_tts"):
        self._name = name
        self._initialized = False
        self._chunk_delay_seconds = 0.0
        self._error_message: Optional[str] = None
        self._empty_audio = False

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
        self._chunk_delay_seconds = max(0.0, float(config.get("chunk_delay_seconds", self._chunk_delay_seconds)))
        self._error_message = config.get("error_message")
        self._empty_audio = bool(config.get("empty_audio", self._empty_audio))

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None
    ) -> AudioResult:
        if self._error_message:
            raise RuntimeError(self._error_message)
        if self._empty_audio:
            return AudioResult(audio_bytes=b"", format="pcm_s16le", duration_seconds=0.0)
        import math
        import struct
        word_count = len(text.split()) if text else 1
        # Approx 150 words per minute -> 2.5 words per sec
        duration = max(0.5, round((word_count / 2.5) / max(speed, 0.5), 2))
        num_samples = int(16000 * duration)
        samples = [
            int(3000 * math.sin(2 * math.pi * 440 * (i / 16000)))
            for i in range(num_samples)
        ]
        mock_payload = struct.pack(f"<{len(samples)}h", *samples)

        return AudioResult(
            audio_bytes=mock_payload,
            format="pcm_s16le",
            duration_seconds=duration
        )

    async def synthesize_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None
    ):
        if self._error_message:
            raise RuntimeError(self._error_message)
        result = self.synthesize(text, voice_id=voice_id, speed=speed, pitch=pitch, emotion=emotion)
        chunk_size = max(1024, len(result.audio_bytes) // 4)
        for i in range(0, len(result.audio_bytes), chunk_size):
            if self._chunk_delay_seconds:
                await asyncio.sleep(self._chunk_delay_seconds)
            yield result.audio_bytes[i:i + chunk_size]

    def close(self) -> None:
        self._initialized = False
