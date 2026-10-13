"""
Sarvam Bulbul v3 voices clients pick for a new AI employee, with short spoken previews.

Speaker ids from Sarvam's Bulbul v3 model docs (docs.sarvam.ai/api/getting-started/models/bulbul).
Previews are synthesized once per voice and kept in memory, so listening again costs nothing.
"""
import io
import logging
import threading
import wave
from typing import Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger("choranta.services.sarvam_voices")

SARVAM_VOICES: List[str] = [
    "shubh", "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran", "kavya", "amit", "dev",
    "ishita", "shreya", "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan", "ashutosh", "advait",
    "anand", "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha",
    "rehan", "soham", "rupali",
]
PREVIEW_TEXT = "Hello! Thank you for calling. I'm your AI employee, and I'm happy to help you today."
PREVIEW_LANGUAGE = "en-IN"
SAMPLE_RATE = 16000

_previews: Dict[str, bytes] = {}
_lock = threading.Lock()


class VoicePreviewUnavailable(Exception):
    pass


def is_voice(voice_id: Optional[str]) -> bool:
    return (voice_id or "") in SARVAM_VOICES


def list_voices() -> List[Dict[str, object]]:
    return [
        {"id": v, "name": v.capitalize(), "provider": "sarvam", "is_default": v == settings.SARVAM_TTS_SPEAKER}
        for v in SARVAM_VOICES
    ]


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _synthesize(voice_id: str) -> bytes:
    from app.runtime.providers.sarvam.tts import SarvamTTSProvider
    result = SarvamTTSProvider(api_key=settings.SARVAM_API_KEY).synthesize(
        text=PREVIEW_TEXT, voice_id=voice_id, speed=1.0, language=PREVIEW_LANGUAGE,
    )
    return result.audio_bytes


def preview_wav(voice_id: str) -> bytes:
    """WAV preview of a Sarvam voice; raises VoicePreviewUnavailable if Sarvam can't be reached."""
    if not is_voice(voice_id):
        raise ValueError(f"Unknown voice '{voice_id}'.")
    with _lock:
        cached = _previews.get(voice_id)
    if cached is not None:
        return cached
    if not settings.SARVAM_API_KEY:
        raise VoicePreviewUnavailable("Voice previews need a Sarvam API key.")
    try:
        pcm = _synthesize(voice_id)
    except Exception as e:
        logger.warning(f"Sarvam preview failed for '{voice_id}': {type(e).__name__}: {e}")
        raise VoicePreviewUnavailable("Couldn't generate the preview right now. Try again in a moment.")
    if not pcm:
        raise VoicePreviewUnavailable("Couldn't generate the preview right now. Try again in a moment.")
    audio = _wav(pcm)
    with _lock:
        _previews[voice_id] = audio
    return audio
