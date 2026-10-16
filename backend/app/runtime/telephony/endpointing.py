from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

import numpy as np
from scipy.signal import butter, sosfilt

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono PCM

# Loudness is measured above this frequency: breath and wind on the mic, handling noise and fans are mostly
# low rumble that would otherwise count as the caller talking. Voices keep most of their energy above it.
HIGHPASS_HZ = 250
_HIGHPASS = butter(2, HIGHPASS_HZ, "highpass", fs=SAMPLE_RATE, output="sos")
# Pitch is checked on 20 ms slices, for voices between 70 and 400 Hz
_PITCH_SLICE = SAMPLE_RATE // 50
_PITCH_LAGS = (SAMPLE_RATE // 400, SAMPLE_RATE // 70)
# Normalized autocorrelation at the pitch period above which a slice is a voice (speech ~0.65, rumble ~0.3)
PITCH_STRENGTH = 0.5


@dataclass
class EndpointerConfig:
    """Timing and energy thresholds for phone-line speech endpointing (all durations in ms)."""
    min_speech_start_ms: int = 150      # voiced audio needed before we decide the caller started talking
    end_silence_ms: int = 700           # trailing silence that ends the caller's turn
    min_utterance_ms: int = 250         # shorter voiced bursts are treated as noise and discarded
    max_utterance_ms: int = 30000       # force a turn end on very long speech
    pre_roll_ms: int = 300              # audio kept from before speech start so first syllables survive
    min_energy: float = 350.0           # absolute RMS floor for speech on 16-bit PCM
    noise_multiplier: float = 3.0       # speech must also exceed this multiple of the learned noise floor
    max_threshold: float = 2500.0       # cap so a loud noise floor can't make normal speech undetectable
    noise_adapt_rate: float = 0.05      # how fast the noise floor follows non-speech frames
    early_transcribe_ms: int = 0        # trailing silence that emits a "pause" so transcription can start
                                        # before the turn ends (0 = off)
    min_pitched_ms: int = 100           # an utterance needs this much pitched (voiced) sound, else it was noise


@dataclass
class EndpointerEvent:
    kind: str                           # "speech_start", "pause", "utterance" or "speech_discarded"
    audio: bytes = b""                  # utterance audio so far (pre-roll included) for "pause" / "utterance"
    speech_ms: float = 0.0
    same_as_pause: bool = False         # "utterance" only: no speech since the last "pause", so its audio
                                        # holds the same words (plus trailing silence)


class SpeechEndpointer:
    """
    Energy-based voice activity detector with hangover, for 16kHz 16-bit mono PCM frames. Loudness is measured
    after a high-pass filter, and pitched sound is tracked (pitched_ms) so callers can tell a voice from noise.

    Feed frames with process(); it returns "speech_start" when sustained speech begins
    (used for barge-in) and "utterance" with the complete audio once the caller has been
    silent for end_silence_ms. Silence and short noise bursts never produce an utterance.
    """

    def __init__(self, config: Optional[EndpointerConfig] = None):
        self.config = config or EndpointerConfig()
        self.noise_floor: float = 0.0
        self._pre_roll: Deque[bytes] = deque()
        self._pre_roll_ms = 0.0
        self._candidate: List[bytes] = []
        self._candidate_voiced_ms = 0.0
        self._candidate_ms = 0.0
        self._utterance = bytearray()
        self._in_speech = False
        self._voiced_ms = 0.0
        self._silence_ms = 0.0
        self._utterance_ms = 0.0
        self._paused_since_speech = False
        self._filter_state = np.zeros((_HIGHPASS.shape[0], 2))
        self._candidate_pitched_ms = 0.0
        self._pitched_ms = 0.0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def pitched_ms(self) -> float:
        """Pitched (voiced) sound in the current speech so far: a voice has it, rumble and hiss barely do."""
        return self._pitched_ms

    def threshold(self) -> float:
        return min(
            self.config.max_threshold,
            max(self.config.min_energy, self.noise_floor * self.config.noise_multiplier)
        )

    def process(self, frame: bytes) -> List[EndpointerEvent]:
        if not frame:
            return []
        if len(frame) % 2:
            frame = frame[:-1]
        frame_ms = len(frame) / BYTES_PER_SECOND * 1000.0
        filtered, self._filter_state = sosfilt(
            _HIGHPASS, np.frombuffer(frame, dtype=np.int16).astype(np.float64), zi=self._filter_state
        )
        rms = float(np.sqrt(np.mean(filtered * filtered))) if len(filtered) else 0.0
        threshold = self.threshold()
        voiced = rms > threshold
        pitched_ms = self._pitched_ms_in(filtered, threshold) if voiced else 0.0
        events: List[EndpointerEvent] = []

        if not self._in_speech:
            if voiced:
                self._candidate.append(frame)
                self._candidate_ms += frame_ms
                self._candidate_voiced_ms += frame_ms
                self._candidate_pitched_ms += pitched_ms
                if self._candidate_voiced_ms >= self.config.min_speech_start_ms:
                    self._begin_speech()
                    events.append(EndpointerEvent(kind="speech_start"))
            else:
                if self._candidate:
                    # A short blip that never became speech: fold it back into pre-roll
                    for f in self._candidate:
                        self._push_pre_roll(f, len(f) / BYTES_PER_SECOND * 1000.0)
                    self._reset_candidate()
                self._push_pre_roll(frame, frame_ms)
                self._adapt_noise(rms)
            return events

        # In speech: accumulate until enough trailing silence
        self._utterance.extend(frame)
        self._utterance_ms += frame_ms
        if voiced:
            self._voiced_ms += frame_ms
            self._pitched_ms += pitched_ms
            self._silence_ms = 0.0
            self._paused_since_speech = False
        else:
            self._silence_ms += frame_ms

        if self._silence_ms >= self.config.end_silence_ms or self._utterance_ms >= self.config.max_utterance_ms:
            audio = bytes(self._utterance)
            voiced_ms = self._voiced_ms
            pitched = self._pitched_ms
            same_as_pause = self._paused_since_speech
            self._end_speech()
            if voiced_ms >= self.config.min_utterance_ms and pitched >= self.config.min_pitched_ms:
                events.append(EndpointerEvent(kind="utterance", audio=audio, speech_ms=voiced_ms, same_as_pause=same_as_pause))
            else:
                # Speech started but turned out to be a short or unvoiced noise burst (no words to transcribe)
                events.append(EndpointerEvent(kind="speech_discarded", speech_ms=voiced_ms))
        elif (
            self.config.early_transcribe_ms
            and not self._paused_since_speech
            and self._silence_ms >= self.config.early_transcribe_ms
            and self._voiced_ms >= self.config.min_utterance_ms
        ):
            # The caller has probably finished: hand over the audio so far to start transcribing
            self._paused_since_speech = True
            events.append(EndpointerEvent(kind="pause", audio=bytes(self._utterance), speech_ms=self._voiced_ms))
        return events

    def flush(self) -> Optional[EndpointerEvent]:
        """Returns any in-progress utterance (e.g. when the call ends mid-sentence)."""
        if self._in_speech and self._voiced_ms >= self.config.min_utterance_ms:
            event = EndpointerEvent(kind="utterance", audio=bytes(self._utterance), speech_ms=self._voiced_ms)
            self._end_speech()
            return event
        self._end_speech()
        return None

    def _begin_speech(self) -> None:
        self._in_speech = True
        self._utterance = bytearray(b"".join(self._pre_roll))
        self._utterance_ms = self._pre_roll_ms
        for f in self._candidate:
            self._utterance.extend(f)
        self._utterance_ms += self._candidate_ms
        self._voiced_ms = self._candidate_voiced_ms
        self._pitched_ms = self._candidate_pitched_ms
        self._silence_ms = 0.0
        self._pre_roll.clear()
        self._pre_roll_ms = 0.0
        self._reset_candidate()

    def _end_speech(self) -> None:
        self._in_speech = False
        self._paused_since_speech = False
        self._utterance = bytearray()
        self._utterance_ms = 0.0
        self._voiced_ms = 0.0
        self._pitched_ms = 0.0
        self._silence_ms = 0.0

    def _reset_candidate(self) -> None:
        self._candidate = []
        self._candidate_ms = 0.0
        self._candidate_voiced_ms = 0.0
        self._candidate_pitched_ms = 0.0

    @staticmethod
    def _pitched_ms_in(filtered: np.ndarray, threshold: float) -> float:
        """Milliseconds of loud, pitched 20 ms slices in a (high-passed) frame."""
        lo, hi = _PITCH_LAGS
        pitched = 0
        # About 20 ms per slice; resampled carrier frames can be a few samples short of a whole slice
        slices = max(1, round(len(filtered) / _PITCH_SLICE)) if len(filtered) > hi else 0
        for piece in np.array_split(filtered, slices) if slices else []:
            energy = float(np.dot(piece, piece))
            if energy <= 0 or np.sqrt(energy / len(piece)) <= threshold:
                continue
            piece = piece - piece.mean()
            corr = np.correlate(piece, piece, "full")[len(piece) - 1:]
            if corr[0] > 0 and corr[lo:hi].max() / corr[0] >= PITCH_STRENGTH:
                pitched += len(piece)
        return pitched * 1000.0 / SAMPLE_RATE

    def _push_pre_roll(self, frame: bytes, frame_ms: float) -> None:
        self._pre_roll.append(frame)
        self._pre_roll_ms += frame_ms
        while self._pre_roll and self._pre_roll_ms - len(self._pre_roll[0]) / BYTES_PER_SECOND * 1000.0 >= self.config.pre_roll_ms:
            dropped = self._pre_roll.popleft()
            self._pre_roll_ms -= len(dropped) / BYTES_PER_SECOND * 1000.0

    def _adapt_noise(self, rms: float) -> None:
        if self.noise_floor == 0.0:
            self.noise_floor = rms
        else:
            self.noise_floor += (rms - self.noise_floor) * self.config.noise_adapt_rate
