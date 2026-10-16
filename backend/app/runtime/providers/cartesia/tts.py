import asyncio
import logging
import uuid
import weakref
from typing import Any, AsyncIterator, Dict, Optional
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import AudioResult
from app.runtime.providers.tts import TTSProvider

logger = logging.getLogger("choranta.runtime.providers.cartesia.tts")

DEFAULT_CARTESIA_VOICE_ID = "4459a9a5-69d6-4680-b970-e13dc51845b6"  # Siya (Indian, multilingual)
DEFAULT_CARTESIA_MODEL_ID = "sonic-3"
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # 16-bit mono

# Languages Sonic-3 speaks (Cartesia's codes); anything else falls back to English
CARTESIA_LANGUAGES = {
    "en", "hi", "te", "ta", "kn", "ml", "mr", "bn", "gu", "pa", "or", "ur",
    "fr", "de", "es", "pt", "zh", "ja", "it", "ko", "nl", "pl", "ru", "sv", "tr", "ar", "id", "th", "vi",
}


def cartesia_language(code: Optional[str]) -> str:
    """'te-IN' -> 'te'; Odia's 'od' -> 'or'; unsupported -> 'en'."""
    base = (code or "en").split("-")[0].lower()
    base = {"od": "or"}.get(base, base)
    return base if base in CARTESIA_LANGUAGES else "en"


# Voices Cartesia says the main model can't speak ('voice_model_mismatch'): they use the fallback model from then on
_newer_model_voices: set = set()


def _is_model_mismatch(error: Exception) -> bool:
    return "voice_model_mismatch" in str(error)


# One WebSocket per event loop, shared by every call: each sentence is its own context on it
_ws_connections: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = weakref.WeakKeyDictionary()
_ws_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()
# A context that goes this long without a message is treated as a dead connection
WS_EVENT_TIMEOUT_S = 8.0


class _NoAudioYet(Exception):
    """The WebSocket failed before any audio was produced: safe to retry the sentence over HTTP."""


def _tts_options(speed: float, language: Optional[str]) -> Dict[str, Any]:
    # Sonic-3 takes speed as a multiplier (0.6-1.5) in generation_config, plus the language to speak
    return {
        "generation_config": {"speed": max(0.6, min(1.5, speed or 1.0))},
        "language": cartesia_language(language),
    }


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

    def _model_for(self, voice_id: str) -> str:
        if voice_id in _newer_model_voices:
            return settings.CARTESIA_TTS_FALLBACK_MODEL or self.model_id
        return self.model_id

    def _switch_to_fallback_model(self, voice_id: str, error: Exception) -> bool:
        """True when the voice needs the newer model and it hasn't been tried yet: the caller retries with it."""
        fallback = settings.CARTESIA_TTS_FALLBACK_MODEL
        if not fallback or fallback == self.model_id or voice_id in _newer_model_voices or not _is_model_mismatch(error):
            return False
        _newer_model_voices.add(voice_id)
        logger.info(f"Cartesia voice {voice_id} needs {fallback}; using it for this voice from now on.")
        return True

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
        emotion: Optional[str] = None,
        language: Optional[str] = None
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

        def request(model_id: str):
            return self._client.tts.bytes(
                model_id=model_id,
                transcript=text,
                voice={"id": effective_voice},
                output_format=output_format,
                **_tts_options(speed, language),
            )

        try:
            try:
                response_chunks = request(self._model_for(effective_voice))
            except Exception as e:
                if not self._switch_to_fallback_model(effective_voice, e):
                    raise
                response_chunks = request(self._model_for(effective_voice))
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
        emotion: Optional[str] = None,
        language: Optional[str] = None
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

        if settings.CARTESIA_TTS_WEBSOCKET:
            try:
                async for chunk in self._ws_stream(text, effective_voice, speed, language):
                    yield chunk
                return
            except _NoAudioYet as e:
                logger.warning(f"Cartesia TTS WebSocket unavailable ({e}); using HTTP for this sentence.")

        async def request(model_id: str):
            return await self._async_client.tts.bytes(
                model_id=model_id,
                transcript=text,
                voice={"id": effective_voice},
                output_format=output_format,
                **_tts_options(speed, language),
            )

        try:
            try:
                stream = await request(self._model_for(effective_voice))
            except Exception as e:
                if not self._switch_to_fallback_model(effective_voice, e):
                    raise
                stream = await request(self._model_for(effective_voice))
            async for chunk in stream:
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(f"Cartesia TTS streaming failed: {type(e).__name__}: {str(e)}")
            raise

    async def warm(self, voice_id: Optional[str] = None, speed: float = 1.0, language: Optional[str] = None) -> None:
        """Opens the shared WebSocket before the first sentence, so the greeting skips the handshake."""
        if not settings.CARTESIA_TTS_WEBSOCKET:
            return
        if not self._async_client:
            self.initialize({})
        try:
            await self._ws_connection()
        except Exception as e:
            logger.warning(f"Could not pre-open Cartesia TTS WebSocket: {type(e).__name__}: {e}")

    async def _ws_connection(self):
        loop = asyncio.get_running_loop()
        lock = _ws_locks.setdefault(loop, asyncio.Lock())
        async with lock:
            conn = _ws_connections.get(loop)
            if conn is None:
                conn = await self._async_client.tts.websocket_connect().enter()
                _ws_connections[loop] = conn
            else:
                # Reconnects if Cartesia closed it; must happen before a context is registered (reconnecting
                # clears the connection's context queues)
                await conn._ensure_connected()
            return conn

    async def _drop_ws_connection(self, conn) -> None:
        loop = asyncio.get_running_loop()
        if _ws_connections.get(loop) is conn:
            _ws_connections.pop(loop, None)
        try:
            await conn.close()
        except Exception:
            pass

    async def _ws_stream(self, text: str, voice_id: str, speed: float, language: Optional[str]) -> AsyncIterator[bytes]:
        """One sentence as a context on the shared WebSocket. Raises _NoAudioYet if it fails before any audio."""
        retried_model = False
        while True:
            try:
                conn = await self._ws_connection()
            except Exception as e:
                raise _NoAudioYet(f"connect failed: {type(e).__name__}: {e}")

            ctx = conn.context(str(uuid.uuid4()), timeout=WS_EVENT_TIMEOUT_S)
            got_audio = False
            finished = False
            try:
                try:
                    await ctx.send(
                        model_id=self._model_for(voice_id),
                        transcript=text,
                        voice={"id": voice_id},
                        output_format={"container": "raw", "encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE},
                        continue_=False,
                        **_tts_options(speed, language),
                    )
                except Exception as e:
                    await self._drop_ws_connection(conn)
                    raise _NoAudioYet(f"send failed: {type(e).__name__}: {e}")

                error: Optional[Exception] = None
                try:
                    async for event in ctx.receive():
                        if event.type == "chunk":
                            audio = event.audio
                            if audio:
                                got_audio = True
                                yield audio
                        elif event.type == "error":
                            error = RuntimeError(str(getattr(event, "error", None) or "Cartesia TTS error"))
                            break
                        elif event.type == "done":
                            break
                except (asyncio.TimeoutError, TimeoutError):
                    await self._drop_ws_connection(conn)
                    if got_audio:
                        raise
                    raise _NoAudioYet("no response from Cartesia")
                finished = True

                if error is not None:
                    if not got_audio and not retried_model and self._switch_to_fallback_model(voice_id, error):
                        retried_model = True
                        continue
                    if not got_audio:
                        raise _NoAudioYet(str(error))
                    raise error
                return
            finally:
                if not finished:
                    # Interrupted mid-sentence (barge-in): stop the generation so it isn't billed further
                    try:
                        await ctx.cancel()
                    except Exception:
                        pass
