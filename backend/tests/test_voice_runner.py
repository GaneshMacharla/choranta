"""Voice test runs: a scripted caller talks to an agent through the real call engine (mock providers)."""
import pytest
from sqlalchemy.orm import Session

from app.models.test_scenario import TestScenario
from app.runtime.telephony.endpointing import EndpointerConfig, SpeechEndpointer
from app.runtime.testing import voice_runner
from app.runtime.testing.caller_audio import FRAME_BYTES, synthetic_voice
from app.runtime.testing.evaluation_engine import voice_assertions
from app.runtime.testing.voice_runner import VoiceScenarioRunner, normalize_turns, transcript_accuracy
from app.core.exceptions import ValidationException
from test_phase3c_telephony import telephony_setup  # noqa: F401


def test_synthetic_caller_voice_is_heard_as_one_utterance():
    endpointer = SpeechEndpointer(EndpointerConfig(end_silence_ms=450, min_energy=150))
    audio = b"\0" * FRAME_BYTES * 25 + synthetic_voice("I am looking for a two BHK flat") + b"\0" * FRAME_BYTES * 40
    kinds = []
    for i in range(0, len(audio) - FRAME_BYTES + 1, FRAME_BYTES):
        kinds += [e.kind for e in endpointer.process(audio[i:i + FRAME_BYTES])]
    assert kinds == ["speech_start", "utterance"]


def test_turns_are_normalized_and_validated():
    turns = normalize_turns(["Hello?", {"text": "wait", "behavior": "INTERRUPT", "after_s": 1}, {"behavior": "silence"}])
    assert [t["behavior"] for t in turns] == ["normal", "interrupt", "silence"]
    with pytest.raises(ValidationException):
        normalize_turns([{"behavior": "dance"}])
    with pytest.raises(ValidationException):
        normalize_turns([{"behavior": "interrupt"}])  # nothing to say


def test_transcript_accuracy_is_word_level():
    assert transcript_accuracy("I want a 2 BHK flat", "i want a 2 bhk flat.") == 1.0
    assert transcript_accuracy("my budget is eighty lakhs", "my budget is eighty") == 0.8
    assert transcript_accuracy("hello", "") == 0.0


def test_voice_assertions_flag_slow_replies_and_unstopped_interruptions():
    turns = [
        {"turn_number": 1, "behavior": "normal", "response_gap_ms": 900},
        {"turn_number": 2, "behavior": "interrupt", "agent_was_speaking": True, "interrupt_stop_ms": None,
         "response_gap_ms": 3100},
    ]
    metrics = {"response_gaps_ms": [900, 3100], "avg_response_gap_ms": 2000, "unanswered_turns": [],
               "talk_over_ms": 0, "provider_mode": "real", "call_ended_by": "caller"}
    results = {a.name: a.status for a in voice_assertions({}, metrics, turns)}
    assert results["voice:max_response_gap"] == "FAIL"
    assert results["voice:avg_response_gap"] == "FAIL"
    assert results["voice:interrupt_stop:turn_2"] == "FAIL"
    assert results["voice:every_turn_answered"] == "PASS"
    # A scenario can relax a threshold
    relaxed = {a.name: a.status for a in voice_assertions({"max_response_gap_ms": 4000, "avg_response_gap_ms": 2500},
                                                          metrics, turns)}
    assert relaxed["voice:max_response_gap"] == "PASS"


@pytest.mark.asyncio
async def test_mock_voice_run_times_turns_and_handles_interruptions(db: Session, telephony_setup, monkeypatch):
    async def never_cancelled(run_id):
        return False
    monkeypatch.setattr(VoiceScenarioRunner, "_cancelled", staticmethod(never_cancelled))
    monkeypatch.setattr(voice_runner, "RESPONSE_TIMEOUT_S", 5.0)

    scenario = TestScenario(
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        name="Voice flow",
        turns_json=[
            "I would like to book an appointment with the doctor for tomorrow morning please",
            {"text": "sorry, one question", "behavior": "interrupt", "after_s": 0.6},
            "Thank you, bye",
        ],
        expected_json={},
        provider_config_json={},
        max_turns=5,
    )
    db.add(scenario)
    db.commit()

    run = await VoiceScenarioRunner(db).run(scenario, provider_mode="mock")

    summary, metrics = run.summary_json, run.metrics_json
    assert summary["error"] is None
    assert metrics["channel"] == "voice"
    assert metrics["is_simulated_latency"] is False
    turns = summary["turns"]
    assert [t["behavior"] for t in turns] == ["normal", "interrupt", "normal"]
    assert turns[0]["heard"].startswith("I would like to book")
    # Every line was answered, after the engine's end-of-turn silence (450 ms) and well within the limits
    assert metrics["unanswered_turns"] == []
    assert all(300 <= gap <= 1500 for gap in metrics["response_gaps_ms"])
    # The agent stopped for the interruption about as fast as it can recognise a voice
    if turns[1]["agent_was_speaking"]:
        assert turns[1]["interrupt_stop_ms"] is not None and turns[1]["interrupt_stop_ms"] < 600
    assert metrics["call_id"] and metrics["recording_file"]
    names = {a["name"] for a in summary["assertions"]}
    assert {"voice:every_turn_answered", "voice:max_response_gap", "voice:no_talking_over_caller"} <= names
    assert not any(n.startswith("quality:") for n in names)  # English keyword checks are off for voice runs
