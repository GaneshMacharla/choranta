"""
In-memory cache of synthesized call audio, shared by all calls in this process.

TTS is billed per character, and agents repeat themselves across calls: the same greeting,
farewell, "Are you still there?" and common short replies. A repeated sentence in the same
voice is played from here instead of being synthesized (and billed) again.
"""
import threading
from collections import OrderedDict
from typing import Optional, Tuple

from app.core.config import settings

CacheKey = Tuple[str, str, float, str, str, str]

_entries: "OrderedDict[CacheKey, bytes]" = OrderedDict()
_size_bytes = 0
_lock = threading.Lock()


def cache_key(tts_provider: str, voice_id: Optional[str], speed: float, language: Optional[str], audio_format: str, text: str) -> CacheKey:
    """Audio is reusable only for the same words, voice, speed, language and carrier audio format."""
    return (tts_provider or "", voice_id or "", round(float(speed or 1.0), 2), language or "", audio_format, text.strip())


def _max_bytes() -> int:
    return max(0, settings.VOICE_TTS_CACHE_MB) * 1024 * 1024


def get(key: CacheKey) -> Optional[bytes]:
    with _lock:
        audio = _entries.get(key)
        if audio is not None:
            _entries.move_to_end(key)
        return audio


def put(key: CacheKey, audio: bytes) -> None:
    global _size_bytes
    limit = _max_bytes()
    if not audio or len(audio) > limit:
        return
    with _lock:
        old = _entries.pop(key, None)
        if old is not None:
            _size_bytes -= len(old)
        _entries[key] = audio
        _size_bytes += len(audio)
        while _size_bytes > limit and _entries:
            _, evicted = _entries.popitem(last=False)
            _size_bytes -= len(evicted)


def clear() -> None:
    global _size_bytes
    with _lock:
        _entries.clear()
        _size_bytes = 0
