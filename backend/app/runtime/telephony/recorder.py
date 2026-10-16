import audioop
import io
import wave
from typing import Optional

SAMPLE_RATE = 8000          # carrier audio: 8 kHz, 16-bit mono (phone lines); browser test calls use 16 kHz


class CallRecorder:
    """
    Records both sides of a phone call into one time-aligned stereo WAV (caller left, agent right).

    The caller track is the continuous inbound stream, which also serves as the call's clock.
    Agent audio is placed at the time it was scheduled to play, and anything the carrier
    discarded when the caller interrupted is cut, so the recording matches what was heard.
    """

    def __init__(self, start_time: float, sample_rate: int = SAMPLE_RATE):
        self.start_time = start_time
        self.sample_rate = sample_rate
        self._caller = bytearray()
        self._agent = bytearray()

    def add_caller_audio(self, carrier_bytes: bytes) -> None:
        if carrier_bytes:
            self._caller.extend(carrier_bytes[: len(carrier_bytes) - len(carrier_bytes) % 2])

    def add_agent_audio(self, carrier_bytes: bytes, play_start: float) -> None:
        if not carrier_bytes:
            return
        data = carrier_bytes[: len(carrier_bytes) - len(carrier_bytes) % 2]
        offset = self._offset(play_start)
        end = offset + len(data)
        if len(self._agent) < end:
            self._agent.extend(b"\x00" * (end - len(self._agent)))
        self._agent[offset:end] = data

    def discard_agent_after(self, when: float) -> None:
        """Drops agent audio scheduled after `when` (flushed by the carrier on barge-in)."""
        offset = self._offset(when)
        if offset < len(self._agent):
            del self._agent[offset:]

    @property
    def duration_seconds(self) -> float:
        return max(len(self._caller), len(self._agent)) / (self.sample_rate * 2)

    def to_wav(self) -> Optional[bytes]:
        length = max(len(self._caller), len(self._agent))
        if length == 0:
            return None
        caller = bytes(self._caller) + b"\x00" * (length - len(self._caller))
        agent = bytes(self._agent) + b"\x00" * (length - len(self._agent))
        stereo = audioop.add(audioop.tostereo(caller, 2, 1, 0), audioop.tostereo(agent, 2, 0, 1), 2)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(stereo)
        return buffer.getvalue()

    def _offset(self, when: float) -> int:
        offset = int(max(0.0, when - self.start_time) * self.sample_rate) * 2
        return offset
