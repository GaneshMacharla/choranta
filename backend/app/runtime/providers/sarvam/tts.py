import base64
import io
import logging
import re
import wave
from typing import Any, AsyncIterator, Dict, Optional

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

    async def _ws_stream(self, text, voice_id, speed, language) -> AsyncIterator[bytes]:
        from sarvamai import AsyncSarvamAI

        client = AsyncSarvamAI(api_subscription_key=self._api_key)
        async with client.text_to_speech_streaming.connect(
            model=settings.SARVAM_TTS_MODEL, send_completion_event=True
        ) as ws:
            await ws.configure(
                target_language_code=self._language(language),
                speaker=self._speaker(voice_id),
                pace=max(0.5, min(2.0, speed or 1.0)),
                speech_sample_rate=SAMPLE_RATE,
                output_audio_codec="linear16",
            )
            await ws.convert(text)
            await ws.flush()
            header_checked = False
            async for message in ws:
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
                    break  # completion event: all audio has been sent
                elif kind == "error":
                    raise RuntimeError(f"Sarvam TTS stream error: {getattr(data, 'message', data)}")

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
