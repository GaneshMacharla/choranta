import audioop
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono PCM


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


@dataclass
class EndpointerEvent:
    kind: str                           # "speech_start", "utterance" or "speech_discarded"
    audio: bytes = b""                  # full utterance audio (pre-roll included) for "utterance"
    speech_ms: float = 0.0


class SpeechEndpointer:
    """
    Energy-based voice activity detector with hangover, for 16kHz 16-bit mono PCM frames.

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

    @property
    def in_speech(self) -> bool:
        return self._in_speech

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
        rms = float(audioop.rms(frame, 2)) if frame else 0.0
        voiced = rms > self.threshold()
        events: List[EndpointerEvent] = []

        if not self._in_speech:
            if voiced:
                self._candidate.append(frame)
                self._candidate_ms += frame_ms
                self._candidate_voiced_ms += frame_ms
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
            self._silence_ms = 0.0
        else:
            self._silence_ms += frame_ms

        if self._silence_ms >= self.config.end_silence_ms or self._utterance_ms >= self.config.max_utterance_ms:
            audio = bytes(self._utterance)
            voiced_ms = self._voiced_ms
            self._end_speech()
            if voiced_ms >= self.config.min_utterance_ms:
                events.append(EndpointerEvent(kind="utterance", audio=audio, speech_ms=voiced_ms))
            else:
                # Speech started but turned out to be a short noise burst
                events.append(EndpointerEvent(kind="speech_discarded", speech_ms=voiced_ms))
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
        self._silence_ms = 0.0
        self._pre_roll.clear()
        self._pre_roll_ms = 0.0
        self._reset_candidate()

    def _end_speech(self) -> None:
        self._in_speech = False
        self._utterance = bytearray()
        self._utterance_ms = 0.0
        self._voiced_ms = 0.0
        self._silence_ms = 0.0

    def _reset_candidate(self) -> None:
        self._candidate = []
        self._candidate_ms = 0.0
        self._candidate_voiced_ms = 0.0

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
