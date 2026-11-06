import asyncio
import base64
import io
import logging
import wave
import weakref
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import TranscriptResult
from app.runtime.providers.sarvam import limits
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
    Sarvam speech-to-text (saaras:v4 by default). Calls transcribe live over the streaming
    endpoint (live_transcriber); the REST endpoint takes one complete utterance and is the
    fallback. Billed per second of audio sent.
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

    def live_transcriber(self, language: Optional[str] = None) -> "SarvamLiveTranscriber":
        """A call's live speech-to-text connection (see SarvamLiveTranscriber)."""
        if not self._api_key:
            self.initialize({})
        return SarvamLiveTranscriber(self._api_key, language)


# Sarvam's end-of-speech detection for live transcription: silence frames needed within the window to end a
# segment. Tuned so the transcript lands just before Choranta's own endpointer ends the turn (the server
# default finishes ~0.5 s later).
LIVE_NEGATIVE_FRAMES = "6"
LIVE_NEGATIVE_WINDOW = "8"
# Longest wait for Sarvam to finish an utterance's transcript before falling back to REST
LIVE_FINAL_WAIT_S = 1.0


class _ServerSpeech:
    """One speech segment Sarvam detected (numbered in arrival order), and its transcript once final."""

    def __init__(self, number: int):
        self.number = number
        self.text: Optional[str] = None


class LiveSegment:
    """One caller utterance being transcribed live: the audio sent so far and the connection it went to."""

    def __init__(self, first_speech: int):
        self.first_speech = first_speech  # Sarvam segments numbered from here on belong to this utterance
        self.audio = bytearray()
        self.connection: Optional[int] = None  # connection number its audio went to
        self.failed = False


class SarvamLiveTranscriber:
    """
    A call's live connection to Sarvam's streaming speech-to-text. The call sends caller audio only while the
    caller is speaking (pre-roll included), so it is billed for the same seconds as per-utterance REST, but
    Sarvam transcribes as the words arrive: the transcript is usually ready when the turn ends instead of
    ~0.5 s later. Sarvam may split one utterance into several segments; their texts are joined.

    finish() returns None whenever the live result can't be trusted (connection failed or dropped, or the
    transcript is late), and the caller then transcribes the utterance over REST.
    """

    def __init__(self, api_key: Optional[str], language: Optional[str] = None, connect: Optional[Callable[[], Any]] = None):
        self._api_key = api_key
        self._language = sarvam_language(language or settings.SARVAM_STT_LANGUAGE, default="unknown")
        self._connect_fn = connect or self._sarvam_connect
        self._manager: Any = None
        self._ws: Any = None
        self._connection = 0
        self._speech: List[_ServerSpeech] = []
        self._speech_count = 0
        self._changed = asyncio.Event()
        self._queue: "asyncio.Queue[Tuple[Optional[LiveSegment], Any]]" = asyncio.Queue()
        self._sender: Optional[asyncio.Task] = None
        self._receiver: Optional[asyncio.Task] = None
        self._closed = False

    def _sarvam_connect(self) -> Any:
        from sarvamai import AsyncSarvamAI

        client = AsyncSarvamAI(api_subscription_key=self._api_key)
        return client.speech_to_text_streaming.connect(
            language_code=self._language,
            model=settings.SARVAM_STT_MODEL,
            sample_rate=str(SAMPLE_RATE),
            input_audio_codec="pcm_s16le",
            vad_signals="true",
            flush_signal="true",
            negative_frames_count=LIVE_NEGATIVE_FRAMES,
            negative_frames_window=LIVE_NEGATIVE_WINDOW,
        )

    # -- public API (call from the event loop) --

    def start(self) -> None:
        """Starts the sender and opens the connection ahead of the first utterance."""
        if self._sender is None:
            self._sender = asyncio.create_task(self._send_loop())
            self._queue.put_nowait((None, "connect"))

    def begin(self, audio: bytes) -> LiveSegment:
        """The caller started speaking: `audio` is the utterance so far (pre-roll included)."""
        segment = LiveSegment(self._speech_count)
        self.send(segment, audio)
        return segment

    def send(self, segment: LiveSegment, pcm16: bytes) -> None:
        """More of the utterance's audio (16 kHz 16-bit mono). Never blocks the audio path."""
        if pcm16 and not segment.failed and not self._closed:
            self._queue.put_nowait((segment, pcm16))

    async def finish(self, segment: LiveSegment) -> Optional[TranscriptResult]:
        """The utterance ended: its transcript, or None to fall back to REST."""
        if segment.failed or self._closed:
            return None
        self._queue.put_nowait((segment, "flush"))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + LIVE_FINAL_WAIT_S
        while True:
            self._changed.clear()
            if segment.failed or (
                segment.connection is not None and (segment.connection != self._connection or self._ws is None)
            ):
                return None  # the connection failed, dropped or was replaced mid-utterance
            mine = [s for s in self._speech if s.number >= segment.first_speech]
            sent = segment.connection is not None
            if sent and mine and all(s.text is not None for s in mine):
                text = " ".join(s.text for s in mine if s.text).strip()
                return TranscriptResult(text=text, is_final=True, confidence=0.9)
            remaining = deadline - loop.time()
            if remaining <= 0:
                if sent and not mine:
                    # Sarvam heard no speech in it (noise, or too quiet): the REST pass decides
                    logger.info("Live transcription found no speech; transcribing the utterance over REST.")
                else:
                    logger.info("Live transcript was late; transcribing the utterance over REST.")
                return None
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except asyncio.TimeoutError:
                pass

    async def close(self) -> None:
        self._closed = True
        if self._sender:
            self._sender.cancel()
        await self._disconnect()

    # -- internals --

    async def _send_loop(self) -> None:
        try:
            while True:
                segment, item = await self._queue.get()
                try:
                    if item == "connect":
                        if self._ws is None:
                            await self._open()
                        continue
                    if segment is None or segment.failed:
                        continue
                    if item == "flush":
                        if self._ws is not None and segment.connection == self._connection:
                            await self._ws.flush()
                        continue
                    segment.audio.extend(item)
                    payload = item
                    if self._ws is None or segment.connection not in (None, self._connection):
                        if segment.connection is not None:
                            segment.failed = True  # dropped mid-utterance: REST takes this one
                            continue
                        await self._open()
                        payload = bytes(segment.audio)  # a fresh connection needs the utterance so far
                    segment.connection = self._connection
                    await self._ws.transcribe(
                        audio=base64.b64encode(payload).decode(), encoding="audio/wav", sample_rate=SAMPLE_RATE
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Live transcription send failed ({type(e).__name__}: {e}); using REST.")
                    limits.note_ws_failure(e)
                    if segment is not None:
                        segment.failed = True
                    self._changed.set()
                    await self._disconnect()
        except asyncio.CancelledError:
            pass

    async def _open(self) -> None:
        await limits.wait_for_ws_open()
        manager = self._connect_fn()
        ws = await manager.__aenter__()
        self._manager, self._ws = manager, ws
        self._connection += 1
        self._receiver = asyncio.create_task(self._receive_loop(ws))

    async def _disconnect(self) -> None:
        manager, self._manager, self._ws = self._manager, None, None
        if self._receiver:
            self._receiver.cancel()
            self._receiver = None
        self._changed.set()
        if manager is not None:
            try:
                await manager.__aexit__(None, None, None)
            except Exception:
                pass

    def _add_speech(self) -> _ServerSpeech:
        speech = _ServerSpeech(self._speech_count)
        self._speech_count += 1
        self._speech.append(speech)
        return speech

    async def _receive_loop(self, ws: Any) -> None:
        try:
            async for message in ws:
                kind = getattr(message, "type", "")
                data = getattr(message, "data", None)
                if kind == "events" and getattr(data, "signal_type", "") == "START_SPEECH":
                    self._add_speech()
                elif kind == "data":
                    text = (getattr(data, "transcript", "") or "").strip()
                    pending = next((s for s in self._speech if s.text is None), None)
                    if pending is None:
                        pending = self._add_speech()  # a transcript without a start signal
                    pending.text = text
                elif kind == "error":
                    logger.warning(f"Live transcription error from Sarvam: {getattr(data, 'message', data)}")
                    limits.note_ws_failure(getattr(data, "message", data))
                del self._speech[:-20]  # older segments belong to finished utterances
                self._changed.set()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.info(f"Live transcription connection ended ({type(e).__name__}: {e}).")
            limits.note_ws_failure(e)
        if self._ws is ws:
            self._ws = None
        self._changed.set()


__all__ = ["SarvamSTTProvider", "SarvamLiveTranscriber", "sarvam_headers"]
