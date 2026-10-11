import logging
from typing import Any, AsyncIterator, Dict, Optional
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import AudioResult
from app.runtime.providers.tts import TTSProvider

logger = logging.getLogger("choranta.runtime.providers.cartesia.tts")

DEFAULT_CARTESIA_VOICE_ID = "a0e99841-438c-4a64-b679-ae501e7d6091"
DEFAULT_CARTESIA_MODEL_ID = "sonic-3"
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # 16-bit mono


class CartesiaTTSProvider(TTSProvider):
    """
    Cartesia Text-to-Speech provider adapter.
    Streams ultra-low latency PCM 16-bit 16kHz audio from text.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        default_voice_id: str = DEFAULT_CARTESIA_VOICE_ID
    ):
        self._api_key = api_key if api_key is not None else settings.CARTESIA_API_KEY
        self.model_id = model_id or settings.CARTESIA_TTS_MODEL
        self.default_voice_id = default_voice_id
        self._client = None
        self._async_client = None

    @property
    def provider_name(self) -> str:
        return "cartesia"

    @property
    def environment(self) -> str:
        return "production"

    def initialize(self, config: Dict[str, Any]) -> None:
        key = self._api_key or config.get("api_key")
        if not key:
            raise ProviderUnavailable("TTS", "Cartesia: Missing CARTESIA_API_KEY")
        self._api_key = key
        try:
            import cartesia
            self._client = cartesia.Cartesia(api_key=self._api_key)
            self._async_client = cartesia.AsyncCartesia(api_key=self._api_key)
        except Exception as e:
            logger.error(f"Failed to initialize Cartesia TTS client: {type(e).__name__}")
            raise ProviderUnavailable("TTS", f"Cartesia TTS initialization failed: {str(e)}")

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._async_client = None

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None
    ) -> AudioResult:
        """
        Synthesizes text into raw PCM 16-bit 16kHz mono audio bytes synchronously.
        """
        if not self._client:
            self.initialize({})

        effective_voice = voice_id or self.default_voice_id
        output_format = {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": SAMPLE_RATE
        }

        try:
            response_chunks = self._client.tts.bytes(
                model_id=self.model_id,
                transcript=text,
                voice={"id": effective_voice},
                output_format=output_format,
                speed=max(0.5, min(2.0, speed))
            )
            audio_bytes = b"".join(response_chunks)
            duration = len(audio_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
            return AudioResult(
                audio_bytes=audio_bytes,
                format="pcm_s16le",
                duration_seconds=duration
            )
        except Exception as e:
            logger.error(f"Cartesia TTS synthesis failed: {type(e).__name__}: {str(e)}")
            raise

    async def synthesize_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None
    ) -> AsyncIterator[bytes]:
        """
        Asynchronously streams raw PCM chunks directly from Cartesia.
        """
        if not self._async_client:
            self.initialize({})

        effective_voice = voice_id or self.default_voice_id
        output_format = {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": SAMPLE_RATE
        }

        try:
            stream = await self._async_client.tts.bytes(
                model_id=self.model_id,
                transcript=text,
                voice={"id": effective_voice},
                output_format=output_format,
                speed=max(0.5, min(2.0, speed))
            )
            async for chunk in stream:
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(f"Cartesia TTS streaming failed: {type(e).__name__}: {str(e)}")
            raise
