import asyncio
import io
import logging
import wave
import weakref
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import TranscriptResult
from app.runtime.providers.sarvam.common import (
    CONNECT_RETRIES, CONNECT_TIMEOUT_S, KEEPALIVE_S, SARVAM_REST_BASE_URL, sarvam_headers, sarvam_language,
)
from app.runtime.providers.stt import STTProvider

logger = logging.getLogger("choranta.runtime.providers.sarvam.stt")

SAMPLE_RATE = 16000

# One keep-alive client per event loop: a fresh TLS handshake costs ~500 ms on every utterance
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def _client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=SARVAM_REST_BASE_URL,
            timeout=httpx.Timeout(15.0, connect=CONNECT_TIMEOUT_S),
            limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
            transport=httpx.AsyncHTTPTransport(retries=CONNECT_RETRIES),  # retries failed connects only
        )
        _clients[loop] = client
    return client


def _wav(pcm16: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm16)
    return buffer.getvalue()


class SarvamSTTProvider(STTProvider):
    """
    Sarvam speech-to-text (REST, saaras:v4 by default). Choranta sends one complete caller
    utterance at a time (already endpointed), so the REST endpoint fits the call pipeline.
    Billed per second of audio sent.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.SARVAM_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def provider_name(self) -> str:
        return "sarvam"

    @property
    def environment(self) -> str:
        return "production"

    def initialize(self, config: Dict[str, Any]) -> None:
        if not (self._api_key or config.get("api_key")):
            raise ProviderUnavailable("STT", "Sarvam: Missing SARVAM_API_KEY")
        self._api_key = self._api_key or config.get("api_key")

    def close(self) -> None:
        self._client = None

    def start_stream(self) -> None:
        pass

    def end_stream(self) -> TranscriptResult:
        return TranscriptResult(text="", is_final=True, confidence=0.0)

    def process_audio(self, audio_data: Any) -> TranscriptResult:
        if isinstance(audio_data, str):
            return TranscriptResult(text=audio_data, is_final=True, confidence=1.0)
        return asyncio.run(self.process_audio_async(audio_data))

    async def warm(self) -> None:
        """Opens the connection ahead of the first utterance (any response will do)."""
        try:
            await _client().head("/")
        except Exception as e:
            logger.debug(f"Sarvam STT warm-up failed: {type(e).__name__}: {e}")

    async def process_audio_async(self, audio_data: Any, language: Optional[str] = None) -> TranscriptResult:
        """`language` (e.g. 'te') overrides SARVAM_STT_LANGUAGE for this request."""
        if isinstance(audio_data, str):
            return TranscriptResult(text=audio_data, is_final=True, confidence=1.0)
        audio = bytes(audio_data or b"")
        if not audio:
            return TranscriptResult(text="", is_final=True, confidence=0.0)
        if not self._api_key:
            self.initialize({})

        wav_bytes = audio if audio.startswith(b"RIFF") else _wav(audio[: len(audio) - len(audio) % 2])
        data = {
            "model": settings.SARVAM_STT_MODEL,
            "language_code": sarvam_language(language or settings.SARVAM_STT_LANGUAGE, default="unknown"),
        }
        headers = {"api-subscription-key": self._api_key}
        response = await _client().post(
            "/speech-to-text",
            headers=headers,
            data=data,
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
        )
        if response.status_code >= 400:
            logger.error(f"Sarvam STT failed ({response.status_code}): {response.text[:300]}")
            raise RuntimeError(f"Sarvam STT error {response.status_code}")
        body = response.json()
        return TranscriptResult(
            text=(body.get("transcript") or "").strip(),
            is_final=True,
            confidence=float(body.get("language_probability") or 0.9),
        )


__all__ = ["SarvamSTTProvider", "sarvam_headers"]
