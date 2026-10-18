import math
import struct

from app.runtime.telephony.endpointing import SpeechEndpointer, EndpointerConfig

FRAME_MS = 20
SAMPLES_PER_FRAME = 16000 * FRAME_MS // 1000


def _tone(amplitude: int, freq: float = 220.0) -> bytes:
    return struct.pack(
        f"<{SAMPLES_PER_FRAME}h",
        *(int(amplitude * math.sin(2 * math.pi * freq * i / 16000)) for i in range(SAMPLES_PER_FRAME))
    )


SILENCE = b"\x00\x00" * SAMPLES_PER_FRAME
NOISE = _tone(60)      # quiet line hiss
SPEECH = _tone(4000)   # clearly voiced


def _feed(ep: SpeechEndpointer, frame: bytes, ms: int):
    events = []
    for _ in range(ms // FRAME_MS):
        events.extend(ep.process(frame))
    return events


def test_silence_and_line_noise_never_produce_turns():
    ep = SpeechEndpointer()
    events = _feed(ep, SILENCE, 3000) + _feed(ep, NOISE, 5000)
    assert events == []


def test_short_click_is_not_speech():
    ep = SpeechEndpointer()
    events = _feed(ep, SILENCE, 500) + _feed(ep, SPEECH, 60) + _feed(ep, SILENCE, 2000)
    assert events == []


def test_one_sentence_produces_exactly_one_utterance_after_trailing_silence():
    ep = SpeechEndpointer()
    _feed(ep, NOISE, 1000)
    events = _feed(ep, SPEECH, 1200)
    assert [e.kind for e in events] == ["speech_start"]

    # Not finished during a short pause
    assert _feed(ep, NOISE, 400) == []
    events = _feed(ep, NOISE, 600)
    utterances = [e for e in events if e.kind == "utterance"]
    assert len(utterances) == 1
    utt = utterances[0]
    assert utt.speech_ms >= 1100
    # Includes pre-roll, the speech and the trailing silence, at 32 bytes per ms
    assert len(utt.audio) >= (1200 + 700) * 32


def test_pauses_inside_a_sentence_keep_one_turn():
    ep = SpeechEndpointer()
    events = []
    for _ in range(3):
        events += _feed(ep, SPEECH, 500) + _feed(ep, SILENCE, 400)
    events += _feed(ep, SILENCE, 800)
    assert [e.kind for e in events].count("utterance") == 1
    assert [e.kind for e in events].count("speech_start") == 1


def test_pre_roll_keeps_audio_from_before_speech_start():
    config = EndpointerConfig(pre_roll_ms=300)
    ep = SpeechEndpointer(config)
    _feed(ep, NOISE, 1000)
    events = _feed(ep, SPEECH, 600) + _feed(ep, SILENCE, 800)
    utt = [e for e in events if e.kind == "utterance"][0]
    assert len(utt.audio) >= (300 + 600 + 700) * 32


def test_flush_returns_speech_cut_off_by_hangup():
    ep = SpeechEndpointer()
    _feed(ep, SPEECH, 800)
    event = ep.flush()
    assert event is not None and event.kind == "utterance"
    assert ep.flush() is None


def test_pause_event_lets_transcription_start_before_the_turn_ends():
    ep = SpeechEndpointer(EndpointerConfig(end_silence_ms=600, early_transcribe_ms=250))
    _feed(ep, NOISE, 1000)
    _feed(ep, SPEECH, 1000)
    events = _feed(ep, SILENCE, 300)
    assert [e.kind for e in events] == ["pause"]
    pause_audio = events[0].audio
    assert pause_audio

    events = _feed(ep, SILENCE, 400)
    assert [e.kind for e in events] == ["utterance"]
    assert events[0].same_as_pause is True
    # The utterance only adds trailing silence after the paused audio
    assert events[0].audio.startswith(pause_audio)


def test_speech_after_pause_invalidates_early_transcript():
    ep = SpeechEndpointer(EndpointerConfig(end_silence_ms=600, early_transcribe_ms=250))
    _feed(ep, NOISE, 1000)
    _feed(ep, SPEECH, 800)
    assert [e.kind for e in _feed(ep, SILENCE, 300)] == ["pause"]
    # Caller carries on talking: a second pause is allowed, and the final turn reflects the latest one
    _feed(ep, SPEECH, 600)
    events = _feed(ep, SILENCE, 300) + _feed(ep, SILENCE, 400)
    assert [e.kind for e in events] == ["pause", "utterance"]
    assert events[1].same_as_pause is True


def test_utterance_without_pause_is_not_marked_same_as_pause():
    ep = SpeechEndpointer(EndpointerConfig(end_silence_ms=600))
    _feed(ep, NOISE, 1000)
    _feed(ep, SPEECH, 1000)
    events = _feed(ep, SILENCE, 800)
    assert [e.kind for e in events] == ["utterance"]
    assert events[0].same_as_pause is False


def test_quiet_phone_line_voice_is_heard_with_call_settings():
    # Speech on a phone line can arrive at RMS ~200 over a near-silent floor: the call settings must hear it
    from app.runtime.telephony.session import _endpointer_config

    quiet_speech = _tone(350, freq=300.0)
    assert [e.kind for e in _feed(SpeechEndpointer(EndpointerConfig()), quiet_speech, 800)] == []  # old 350 floor
    ep = SpeechEndpointer(_endpointer_config())
    _feed(ep, NOISE, 1000)
    events = _feed(ep, quiet_speech, 800) + _feed(ep, SILENCE, 1000)
    assert "speech_start" in [e.kind for e in events]
    assert [e for e in events if e.kind == "utterance"]
