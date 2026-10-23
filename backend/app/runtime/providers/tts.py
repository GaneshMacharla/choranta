import asyncio
from abc import abstractmethod
from typing import AsyncIterator, Optional
from app.runtime.providers.base import BaseProvider, AudioResult


class TextFeed:
    """
    The text of one utterance arriving in pieces, e.g. an LLM reply sentence by sentence as it is written.
    Ends at close(). Safe to read again after a cancelled read: nothing is lost, so a provider can retry.
    """

    def __init__(self, *texts: str):
        self._queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        self._ended = False
        self.closed = False
        for text in texts:
            self.put(text)

    def put(self, text: str) -> None:
        if not self.closed:
            self._queue.put_nowait(text)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._queue.put_nowait(None)

    async def get(self) -> Optional[str]:
        """The next piece of text, or None once the utterance is complete."""
        if self._ended:
            return None
        text = await self._queue.get()
        if text is None:
            self._ended = True
        return text

    def __aiter__(self) -> "TextFeed":
        return self

    async def __anext__(self) -> str:
        text = await self.get()
        if text is None:
            raise StopAsyncIteration
        return text


class TTSProvider(BaseProvider):
    """Abstract interface for Text-to-Speech synthesis providers."""

    # Sample rates synthesize_stream can produce directly when passed `sample_rate` (16-bit mono PCM). Asking
    # for the carrier's own rate (8kHz on phone lines) skips our resampling, which loses clarity.
    native_sample_rates: tuple = ()

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
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ):
        """Asynchronously stream raw audio bytes chunks for the synthesized speech (16kHz PCM unless
        `sample_rate` is one of native_sample_rates)."""
        result = self.synthesize(text, voice_id=voice_id, speed=speed, pitch=pitch, emotion=emotion)
        chunk_size = 1024
        for i in range(0, len(result.audio_bytes), chunk_size):
            yield result.audio_bytes[i:i + chunk_size]

    # True when synthesize_text_stream speaks all of a feed as one utterance (intonation carries across its
    # sentences, no gaps between them); the default below speaks each piece on its own
    supports_text_stream: bool = False

    async def synthesize_text_stream(
        self,
        feed: TextFeed,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        language: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> AsyncIterator[bytes]:
        """Streams audio for text that is still being written, as it arrives."""
        rate = {"sample_rate": sample_rate} if sample_rate else {}
        async for text in feed:
            async for chunk in self.synthesize_stream(text, voice_id=voice_id, speed=speed, language=language, **rate):
                yield chunk

    async def warm(
        self, voice_id: Optional[str] = None, speed: float = 1.0, language: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> None:
        """Opens provider connections ahead of the first synthesis, where the provider supports it."""
        return None

