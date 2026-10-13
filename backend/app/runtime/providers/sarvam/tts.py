import asyncio
import base64
import io
import logging
import re
import time
import wave
import weakref
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import AudioResult
from app.runtime.providers.sarvam.common import SARVAM_REST_BASE_URL, sarvam_language
from app.runtime.providers.tts import TTSProvider

logger = logging.getLogger("choranta.runtime.providers.sarvam.tts")

SAMPLE_RATE = 16000  # Choranta's canonical PCM rate
_SPEAKER = re.compile(r"^[a-z]+(_[a-z0-9]+)*$")


def _wav_to_pcm(data: bytes) -> bytes:
    """Returns raw 16-bit PCM from a WAV payload (or the bytes unchanged if not WAV)."""
    if not data.startswith(b"RIFF"):
        return data
    with wave.open(io.BytesIO(data)) as wav:
        return wav.readframes(wav.getnframes())


# Open streaming connections are reused across sentences and calls: a new WebSocket costs
# 0.5-1 s of handshake before the first audio
_IDLE_TTL_S = 45.0
_MAX_IDLE_PER_VOICE = 4


class _TTSConnection:
    def __init__(self, manager: Any, ws: Any):
        self.manager = manager
        self.ws = ws
        self.last_used = time.monotonic()

    async def close(self) -> None:
        try:
            await self.manager.__aexit__(None, None, None)
        except Exception:
            pass


_idle_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[tuple, List[_TTSConnection]]]" = weakref.WeakKeyDictionary()


def _idle_pool() -> Dict[tuple, List[_TTSConnection]]:
    loop = asyncio.get_running_loop()
    pool = _idle_pools.get(loop)
    if pool is None:
        pool = {}
        _idle_pools[loop] = pool
    return pool


class SarvamTTSProvider(TTSProvider):
    """
    Sarvam Bulbul text-to-speech. Streams over Sarvam's TTS WebSocket (linear16, 16 kHz) so
    the agent starts talking on the first audio chunk; falls back to the REST endpoint if the
    stream fails. Billed per character.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.SARVAM_API_KEY

    @property
    def provider_name(self) -> str:
        return "sarvam"

    @property
    def environment(self) -> str:
        return "production"

    def initialize(self, config: Dict[str, Any]) -> None:
        if not (self._api_key or config.get("api_key")):
            raise ProviderUnavailable("TTS", "Sarvam: Missing SARVAM_API_KEY")
        self._api_key = self._api_key or config.get("api_key")

    def close(self) -> None:
        pass

    @staticmethod
    def _speaker(voice_id: Optional[str]) -> str:
        # Agent voice ids from other providers (e.g. Cartesia UUIDs) aren't Sarvam speakers
        if voice_id and _SPEAKER.match(voice_id):
            return voice_id
        return settings.SARVAM_TTS_SPEAKER

    @staticmethod
    def _language(language: Optional[str]) -> str:
        override = (settings.SARVAM_TTS_LANGUAGE or "").strip()
        return sarvam_language(override or language, default="en-IN")

    def _rest_payload(self, text: str, voice_id: Optional[str], speed: float, language: Optional[str]) -> Dict[str, Any]:
        return {
            "text": text,
            "language_code": self._language(language),
            "model": settings.SARVAM_TTS_MODEL,
            "speaker": self._speaker(voice_id),
            "pace": max(0.5, min(2.0, speed or 1.0)),
            "speech_sample_rate": SAMPLE_RATE,
            "output_audio_codec": "wav",
        }

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None,
        language: Optional[str] = None,
    ) -> AudioResult:
        if not self._api_key:
            self.initialize({})
        response = httpx.post(
            f"{SARVAM_REST_BASE_URL}/text-to-speech",
            headers={"api-subscription-key": self._api_key},
            json=self._rest_payload(text, voice_id, speed, language),
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        if response.status_code >= 400:
            logger.error(f"Sarvam TTS failed ({response.status_code}): {response.text[:300]}")
            raise RuntimeError(f"Sarvam TTS error {response.status_code}")
        pcm = b"".join(_wav_to_pcm(base64.b64decode(a)) for a in response.json().get("audios") or [])
        return AudioResult(audio_bytes=pcm, format="pcm_s16le", duration_seconds=len(pcm) / (SAMPLE_RATE * 2))

    async def _rest_stream(self, text, voice_id, speed, language) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = await client.post(
                f"{SARVAM_REST_BASE_URL}/text-to-speech",
                headers={"api-subscription-key": self._api_key},
                json=self._rest_payload(text, voice_id, speed, language),
            )
        if response.status_code >= 400:
            logger.error(f"Sarvam TTS failed ({response.status_code}): {response.text[:300]}")
            raise RuntimeError(f"Sarvam TTS error {response.status_code}")
        for audio in response.json().get("audios") or []:
            pcm = _wav_to_pcm(base64.b64decode(audio))
            for i in range(0, len(pcm), 3200):
                yield pcm[i:i + 3200]

    def _ws_key(self, voice_id, speed, language) -> Tuple[str, str, str, float]:
        return (settings.SARVAM_TTS_MODEL, self._language(language), self._speaker(voice_id), max(0.5, min(2.0, speed or 1.0)))

    async def _open(self, key) -> _TTSConnection:
        from sarvamai import AsyncSarvamAI

        model, language, speaker, pace = key
        client = AsyncSarvamAI(api_subscription_key=self._api_key)
        manager = client.text_to_speech_streaming.connect(model=model, send_completion_event=True)
        ws = await manager.__aenter__()
        conn = _TTSConnection(manager, ws)
        try:
            await ws.configure(
                target_language_code=language,
                speaker=speaker,
                pace=pace,
                speech_sample_rate=SAMPLE_RATE,
                output_audio_codec="linear16",
            )
        except BaseException:
            await conn.close()
            raise
        return conn

    async def _acquire(self, key) -> Tuple[_TTSConnection, bool]:
        """An idle open connection for these voice settings (reused=True), or a new one."""
        idle = _idle_pool().get(key) or []
        now = time.monotonic()
        while idle:
            conn = idle.pop()
            if now - conn.last_used < _IDLE_TTL_S:
                return conn, True
            asyncio.ensure_future(conn.close())
        return await self._open(key), False

    @staticmethod
    def _release(key, conn: _TTSConnection) -> None:
        conn.last_used = time.monotonic()
        idle = _idle_pool().setdefault(key, [])
        if len(idle) < _MAX_IDLE_PER_VOICE:
            idle.append(conn)
        else:
            asyncio.ensure_future(conn.close())

    async def warm(self, voice_id: Optional[str] = None, speed: float = 1.0, language: Optional[str] = None) -> None:
        """Opens a streaming connection before the first sentence, so the greeting skips the handshake."""
        if not settings.SARVAM_TTS_STREAMING:
            return
        if not self._api_key:
            self.initialize({})
        key = self._ws_key(voice_id, speed, language)
        if _idle_pool().get(key):
            return
        try:
            self._release(key, await self._open(key))
        except Exception as e:
            logger.warning(f"Could not pre-open Sarvam TTS stream: {type(e).__name__}: {e}")

    async def _ws_stream(self, text, voice_id, speed, language) -> AsyncIterator[bytes]:
        key = self._ws_key(voice_id, speed, language)
        conn, reused = await self._acquire(key)
        finished = False
        try:
            try:
                await conn.ws.convert(text)
                await conn.ws.flush()
            except Exception:
                if not reused:
                    raise
                # Sarvam closed the idle connection: retry once on a fresh one
                asyncio.ensure_future(conn.close())
                conn = await self._open(key)
                await conn.ws.convert(text)
                await conn.ws.flush()
            header_checked = False
            async for message in conn.ws:
                kind = getattr(message, "type", "")
                data = getattr(message, "data", None)
                if kind == "audio" and data is not None:
                    chunk = base64.b64decode(data.audio)
                    if not header_checked:
                        header_checked = True
                        if chunk.startswith(b"RIFF"):
                            chunk = chunk[44:]
                    if chunk:
                        yield chunk
                elif kind == "event":
                    finished = True  # completion event: all audio has been sent
                    break
                elif kind == "error":
                    raise RuntimeError(f"Sarvam TTS stream error: {getattr(data, 'message', data)}")
        finally:
            # Only a connection that finished its sentence is clean enough to reuse
            if finished:
                self._release(key, conn)
            else:
                asyncio.ensure_future(conn.close())

    async def synthesize_stream(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None,
        language: Optional[str] = None,
    ) -> AsyncIterator[bytes]:
        """Yields 16 kHz 16-bit mono PCM chunks."""
        if not self._api_key:
            self.initialize({})
        emitted = False
        if settings.SARVAM_TTS_STREAMING:
            try:
                async for chunk in self._ws_stream(text, voice_id, speed, language):
                    emitted = True
                    yield chunk
                return
            except Exception as e:
                if emitted:
                    raise
                logger.warning(f"Sarvam TTS stream failed ({type(e).__name__}: {e}); using REST.")
        async for chunk in self._rest_stream(text, voice_id, speed, language):
            yield chunk
