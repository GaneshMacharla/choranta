"""
The simulated caller's voice for voice test runs: scripted lines as 16kHz 16-bit mono PCM, plus the line
conditions real callers bring (background noise, a narrow phone line).

Mock runs use a synthetic voice (pitched like speech, so the call engine treats it as a caller talking).
Real runs speak each line with Sarvam once and replay it from a disk cache, so reruns cost nothing extra
and every run hears exactly the same audio.
"""
import audioop
import hashlib
import logging
import os
from typing import Optional

import numpy as np

from app.core.config import settings

logger = logging.getLogger("choranta.testing.caller_audio")

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2

CACHE_DIR = os.path.join(settings.RECORDINGS_DIR, "voice_test_cache")
NOISE_KINDS = ("white", "hum", "babble")


def synthetic_voice(text: str, seed: int = 0) -> bytes:
    """A speech-like signal as long as `text` would take to say: a gliding pitch with harmonics,
    shaped into syllables. It has no words; mock runs pair it with a speech-to-text that knows the line."""
    words = max(1, len(text.split()))
    duration = 0.25 + words * 0.32
    n = int(duration * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    rng = np.random.default_rng(seed)
    f0 = 140.0 + 25.0 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, np.pi))
    phase = 2 * np.pi * np.cumsum(f0) / SAMPLE_RATE
    signal = sum(np.sin(k * phase) / k for k in range(1, 12))
    syllables = 0.65 + 0.35 * np.abs(np.sin(np.pi * 4.0 * t))   # stays loud enough to read as one phrase
    fade = np.minimum(1.0, np.minimum(t, duration - t) / 0.03)
    pcm = signal * syllables * fade
    pcm = pcm / (np.abs(pcm).max() or 1.0) * 9000.0
    return pcm.astype(np.int16).tobytes()


async def spoken_line(text: str, language: Optional[str] = None, voice: Optional[str] = None) -> bytes:
    """`text` spoken by a Sarvam voice at 16kHz, from the disk cache when it was spoken before."""
    from app.runtime.providers.registry import default_registry

    language = language or "en-IN"
    voice = voice or "priya"
    key = hashlib.sha256(f"{voice}|{language}|{text}".encode("utf-8")).hexdigest()[:24]
    path = os.path.join(CACHE_DIR, f"{key}.pcm")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()

    tts = default_registry.get_tts("sarvam")
    audio = bytearray()
    async for chunk in tts.synthesize_stream(text=text, voice_id=voice, language=language, sample_rate=SAMPLE_RATE):
        audio.extend(chunk)
    if not audio:
        raise RuntimeError(f"Sarvam returned no audio for caller line '{text[:40]}'")
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(audio)
    return bytes(audio)


def phone_line(pcm: bytes) -> bytes:
    """`pcm` as it arrives over a phone line: 8kHz narrowband and mu-law companded, back at 16kHz."""
    if not pcm:
        return pcm
    narrow, _ = audioop.ratecv(pcm, 2, 1, SAMPLE_RATE, 8000, None)
    narrow = audioop.ulaw2lin(audioop.lin2ulaw(narrow, 2), 2)
    wide, _ = audioop.ratecv(narrow, 2, 1, 8000, SAMPLE_RATE, None)
    return wide


class LineNoise:
    """Continuous background noise under the caller's line (also while they are silent), at `level`
    (0-1, as a fraction of a normal speaking level)."""

    def __init__(self, kind: str = "white", level: float = 0.1, seed: int = 0):
        if kind not in NOISE_KINDS:
            raise ValueError(f"Unknown noise '{kind}'; use one of {', '.join(NOISE_KINDS)}.")
        self.kind = kind
        self.amplitude = max(0.0, min(1.0, level)) * 9000.0
        self.rng = np.random.default_rng(seed)
        self._pos = 0
        self._hum_state = 0.0
        self._voices = self.rng.uniform(110, 260, size=4)

    def frame(self, samples: int) -> np.ndarray:
        if self.kind == "white":
            noise = self.rng.normal(0, 0.35, samples)
        elif self.kind == "hum":
            # Fan, traffic or engine rumble: low-passed noise with a mains hum
            raw = self.rng.normal(0, 1, samples)
            out = np.empty(samples)
            state = self._hum_state
            for i, x in enumerate(raw):
                state += (x - state) * 0.02
                out[i] = state
            self._hum_state = state
            t = (self._pos + np.arange(samples)) / SAMPLE_RATE
            noise = out * 4.0 + 0.3 * np.sin(2 * np.pi * 50 * t)
        else:
            # Other people talking in the room: several faint, wandering voices
            t = (self._pos + np.arange(samples)) / SAMPLE_RATE
            noise = np.zeros(samples)
            for i, f0 in enumerate(self._voices):
                envelope = 0.5 + 0.5 * np.sin(2 * np.pi * (0.3 + 0.17 * i) * t + i)
                noise += np.sin(2 * np.pi * f0 * t + 3 * np.sin(2 * np.pi * 0.5 * t)) * envelope
            noise /= len(self._voices)
        self._pos += samples
        return noise * self.amplitude

    def mix(self, pcm: bytes) -> bytes:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        mixed = samples + self.frame(len(samples))
        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()
