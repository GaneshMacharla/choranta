import io
import wave
import asyncio
import logging
from typing import Any, Callable, Dict, Optional
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import TranscriptResult
from app.runtime.providers.stt import STTProvider

logger = logging.getLogger("choranta.runtime.providers.cartesia.stt")


def _pcm_to_wav_buffer(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> io.BytesIO:
    """Wraps raw PCM 16-bit little-endian audio in standard RIFF WAV header for provider consumption."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_out:
        wav_out.setnchannels(channels)
        wav_out.setsampwidth(sample_width)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(pcm_bytes)
    buf.seek(0)
    buf.name = "audio.wav"
    return buf


class CartesiaSTTStreamingSession:
    """
    Manages an active real-time streaming WebSocket connection to Cartesia STT (auto_finalize).
    Accepts incremental 16kHz PCM frames and dispatches live partial and final transcripts.
    """

    def __init__(
        self,
        connection: Any,
        on_partial: Optional[Callable[[str], Any]] = None,
        on_final: Optional[Callable[[str], Any]] = None
    ):
        self._connection = connection
        self._on_partial = on_partial
        self._on_final = on_final
        self._dispatch_task: Optional[asyncio.Task] = None
        self._closed = False
        self._latest_transcript = ""

    async def start(self) -> None:
        """Starts background event loop dispatching Cartesia STT turn events."""
        async def _event_loop():
            try:
                async for event in self._connection:
                    event_type = getattr(event, "type", "")
                    transcript = getattr(event, "transcript", "") or ""

                    if event_type in ("turn.update", "turn_update"):
                        if transcript:
                            self._latest_transcript = transcript
                            if self._on_partial:
                                res = self._on_partial(transcript)
                                if asyncio.iscoroutine(res):
                                    await res

                    elif event_type in ("turn.end", "turn_end", "turn.eager_end", "turn_eager_end"):
                        final_text = transcript or self._latest_transcript
                        if final_text:
                            self._latest_transcript = final_text
                            if self._on_final:
                                res = self._on_final(final_text)
                                if asyncio.iscoroutine(res):
                                    await res
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Cartesia STT stream event loop ended: {e}")

        self._dispatch_task = asyncio.create_task(_event_loop())

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._closed or not self._connection or not pcm_bytes:
            return
        try:
            await self._connection.send_raw(pcm_bytes)
        except Exception as e:
            logger.warning(f"Error streaming audio frame to Cartesia STT: {e}")

    async def finish(self) -> TranscriptResult:
        await self.close()
        return TranscriptResult(
            text=self._latest_transcript.strip(),
            is_final=True,
            confidence=0.98
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._dispatch_task and not self._dispatch_task.done():
            self._dispatch_task.cancel()
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass


DEFAULT_CARTESIA_STT_MODEL = "ink-whisper"


class CartesiaSTTProvider(STTProvider):
    """
    Cartesia Speech-to-Text provider adapter.
    Converts streaming PCM 16-bit 16kHz audio into high-fidelity transcripts
    via both real-time streaming WebSocket (auto_finalize) and fallback batch WAV processing.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, language: str = "en"):
        self._api_key = api_key if api_key is not None else settings.CARTESIA_API_KEY
        self.model = model or settings.CARTESIA_STT_MODEL
        self.language = language
        self._client = None
        self._async_client = None
        self._stream_buffer = bytearray()

    @property
    def provider_name(self) -> str:
        return "cartesia"

    @property
    def environment(self) -> str:
        return "production"

    def initialize(self, config: Dict[str, Any]) -> None:
        key = self._api_key or config.get("api_key")
        if not key:
            raise ProviderUnavailable("STT", "Cartesia: Missing CARTESIA_API_KEY")
        self._api_key = key
        try:
            import cartesia
            self._client = cartesia.Cartesia(api_key=self._api_key)
            self._async_client = cartesia.AsyncCartesia(api_key=self._api_key)
        except Exception as e:
            logger.error(f"Failed to initialize Cartesia STT client: {type(e).__name__}")
            raise ProviderUnavailable("STT", f"Cartesia initialization failed: {str(e)}")

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._async_client = None
        self._stream_buffer.clear()

    def start_stream(self) -> None:
        self._stream_buffer.clear()

    async def create_stream(
        self,
        on_partial: Optional[Callable[[str], Any]] = None,
        on_final: Optional[Callable[[str], Any]] = None
    ) -> Optional[CartesiaSTTStreamingSession]:
        """
        Creates an active real-time streaming STT session via Cartesia WebSocket (auto_finalize).
        """
        if not self._async_client:
            self.initialize({})

        try:
            conn_mgr = self._async_client.stt.auto_finalize.websocket(
                encoding="pcm_s16le",
                sample_rate=16000,
                model=self.model
            )
            connection = await conn_mgr.enter()
            session = CartesiaSTTStreamingSession(
                connection=connection,
                on_partial=on_partial,
                on_final=on_final
            )
            await session.start()
            return session
        except Exception as e:
            logger.warning(f"Could not initialize Cartesia streaming STT WebSocket: {e}")
            return None

    def process_audio(self, audio_data: Any) -> TranscriptResult:
        """
        Transcribes audio data (bytes or bytearray) via batch API.
        """
        if not self._client:
            self.initialize({})

        if isinstance(audio_data, (bytes, bytearray)):
            audio_bytes = bytes(audio_data)
        elif isinstance(audio_data, str):
            return TranscriptResult(text=audio_data, is_final=True, confidence=1.0)
        else:
            audio_bytes = bytes(audio_data)

        if len(audio_bytes) == 0:
            return TranscriptResult(text="", is_final=True, confidence=0.0)

        if audio_bytes.startswith(b"RIFF"):
            wav_file = io.BytesIO(audio_bytes)
            wav_file.name = "audio.wav"
        else:
            wav_file = _pcm_to_wav_buffer(audio_bytes, sample_rate=16000)

        try:
            response = self._client.stt.transcribe(
                file=wav_file,
                model=self.model,
                language=self.language
            )
            transcript_text = getattr(response, "text", "") or getattr(response, "transcript", "") or ""
            return TranscriptResult(
                text=transcript_text.strip(),
                is_final=True,
                confidence=getattr(response, "confidence", 1.0) or 1.0
            )
        except Exception as e:
            logger.error(f"Cartesia STT transcription error: {type(e).__name__}: {str(e)}")
            raise

    async def process_audio_async(self, audio_data: Any) -> TranscriptResult:
        """
        Asynchronously transcribes audio data (bytes or bytearray).
        """
        if not self._async_client:
            self.initialize({})

        if isinstance(audio_data, (bytes, bytearray)):
            audio_bytes = bytes(audio_data)
        elif isinstance(audio_data, str):
            return TranscriptResult(text=audio_data, is_final=True, confidence=1.0)
        else:
            audio_bytes = bytes(audio_data)

        if len(audio_bytes) == 0:
            return TranscriptResult(text="", is_final=True, confidence=0.0)

        if audio_bytes.startswith(b"RIFF"):
            wav_file = io.BytesIO(audio_bytes)
            wav_file.name = "audio.wav"
        else:
            wav_file = _pcm_to_wav_buffer(audio_bytes, sample_rate=16000)

        try:
            response = await self._async_client.stt.transcribe(
                file=wav_file,
                model=self.model,
                language=self.language
            )
            transcript_text = getattr(response, "text", "") or getattr(response, "transcript", "") or ""
            return TranscriptResult(
                text=transcript_text.strip(),
                is_final=True,
                confidence=getattr(response, "confidence", 1.0) or 1.0
            )
        except Exception as e:
            logger.error(f"Cartesia async STT error: {type(e).__name__}: {str(e)}")
            raise

    def end_stream(self) -> TranscriptResult:
        if len(self._stream_buffer) == 0:
            return TranscriptResult(text="", is_final=True, confidence=1.0)
        res = self.process_audio(bytes(self._stream_buffer))
        self._stream_buffer.clear()
        return res
