"""Browser test calls over WebRTC: free test calls that run the real phone-call pipeline."""
import asyncio
from typing import Any, Dict, List

import pytest
from sqlalchemy.orm import Session

from app.api.routes.webrtc_audio import (
    FRAME_BYTES, FRAME_SAMPLES, AgentAudioTrack, BrowserCallRequest, BrowserMediaSession, _create_call_record,
)
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.models.user import User
from app.runtime.context import RuntimeContext, TEST_CALL_PHONE
from app.runtime.providers.telephony.browser import BrowserTelephonyProvider
from app.services.billing import charge_call
from test_phase3c_telephony import _build_test_agent_spec, telephony_setup  # noqa: F401
from test_telephony_realtime import _until, fakes  # noqa: F401


def _request(setup, **overrides) -> BrowserCallRequest:
    return BrowserCallRequest(
        agent_id=setup["agent"].id, agent_version_id=setup["version"].id, sdp="v=0", **overrides
    )


def test_browser_call_requires_auth(client):
    res = client.post("/api/telephony/browser-calls", json={"agent_id": "a", "agent_version_id": "v", "sdp": "v=0"})
    assert res.status_code == 401


def test_browser_call_unknown_version(client, auth_headers):
    res = client.post(
        "/api/telephony/browser-calls",
        json={"agent_id": "age_missing", "agent_version_id": "agv_missing", "sdp": "v=0"},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_browser_call_is_a_free_test_call_in_the_call_log(db: Session, telephony_setup):
    user = db.query(User).filter(User.role == "ADMIN").first()
    call = _create_call_record(db, _request(telephony_setup, user_name="Rahul"), user)

    assert call.provider == "browser"
    assert call.direction == "INBOUND" and call.caller_number == TEST_CALL_PHONE
    assert call.metadata_["is_test"] is True and call.metadata_["channel"] == "browser"
    session = db.get(RuntimeSession, call.runtime_session_id)
    assert session.metadata_["origin"] == "telephony_inbound" and session.metadata_["user_name"] == "Rahul"

    call.status, call.duration_seconds = "COMPLETED", 42.0
    assert charge_call(db, call) is None  # never billed


def test_outbound_agents_are_tested_as_outbound_calls(db: Session, telephony_setup):
    version = telephony_setup["version"]
    config = dict(version.configuration_json)
    config["business_context"] = {**(config.get("business_context") or {}), "call_direction": "outbound"}
    version.configuration_json = config
    db.commit()
    user = db.query(User).filter(User.role == "ADMIN").first()

    call = _create_call_record(db, _request(telephony_setup), user)
    assert call.direction == "OUTBOUND" and call.destination_number == TEST_CALL_PHONE
    assert db.get(RuntimeSession, call.runtime_session_id).metadata_["origin"] == "telephony_outbound"


def test_browser_carrier_keeps_full_16khz_audio():
    # The agent's voice reaches the browser untouched, so it sounds the same as the voice picker's preview
    carrier = BrowserTelephonyProvider()
    pcm16k = b"\x10\x00" * 1600  # 100 ms at 16kHz
    assert carrier.carrier_sample_rate == 16000
    assert carrier.normalize_audio_outbound(pcm16k) == pcm16k
    assert carrier.normalize_audio_inbound(pcm16k) == pcm16k
    assert carrier.outbound_frame_bytes == 3200  # 100 ms frames


@pytest.mark.asyncio
async def test_agent_audio_track_plays_buffered_audio_then_silence():
    track = AgentAudioTrack()
    track.write(b"\x01\x00" * FRAME_SAMPLES + b"\x02\x00" * 10)
    first = await track.recv()
    second = await track.recv()
    third = await track.recv()
    assert first.samples == FRAME_SAMPLES and first.sample_rate == 16000
    assert bytes(first.planes[0])[:FRAME_BYTES] == b"\x01\x00" * FRAME_SAMPLES
    assert bytes(second.planes[0])[:FRAME_BYTES] == b"\x02\x00" * 10 + b"\x00" * (FRAME_BYTES - 20)
    assert bytes(third.planes[0])[:FRAME_BYTES] == b"\x00" * FRAME_BYTES
    assert third.pts == 2 * FRAME_SAMPLES
    track.stop()


def _browser_session(db: Session, setup) -> Dict[str, Any]:
    call = Call(
        client_id=setup["client"].id, agent_id=setup["agent"].id, agent_version_id=setup["version"].id,
        caller_number=TEST_CALL_PHONE, destination_number="browser", direction="INBOUND", status="ACTIVE",
        provider="browser", provider_call_id="web_test_1", metadata_={"is_test": True},
    )
    db.add(call)
    db.commit()
    track = AgentAudioTrack()
    notes: List[Dict[str, Any]] = []
    hang_ups: List[str] = []
    s = BrowserMediaSession(call, db, track, notes.append, hang_ups.append)
    spec = _build_test_agent_spec(setup["agent"].id)
    s.context = RuntimeContext("ses_web", call.agent_id, call.client_id, call.agent_version_id, spec, {})
    s.runtime_session = type("RS", (), {"id": "ses_web"})()
    s.emitter.start_buffering()
    s._utterance_worker = asyncio.create_task(s._utterance_loop())
    return {"session": s, "track": track, "notes": notes, "hang_ups": hang_ups}


@pytest.mark.asyncio
async def test_browser_session_speaks_over_webrtc_and_hangs_up(db: Session, telephony_setup, fakes):
    b = _browser_session(db, telephony_setup)
    s, track = b["session"], b["track"]
    fakes["stt"].transcripts[640] = "What are your timings?"
    fakes["llm"].replies = ["We are open from nine to six."]
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: any(n["type"] == "agent_text" for n in b["notes"]))

        assert fakes["tts"].spoken  # the reply was synthesized and sent to the browser track
        assert any(n["type"] == "caller_text" and n["text"] == "What are your timings?" for n in b["notes"])
        assert any(n["type"] == "agent_speaking" for n in b["notes"])

        track.write(b"\x01\x00" * 800)
        await s._clear_carrier_playback()  # barge-in flushes queued agent audio
        assert bytes((await track.recv()).planes[0])[:FRAME_BYTES] == b"\x00" * FRAME_BYTES

        await s._disconnect_carrier()  # the agent's end_call ends the browser call
        assert b["hang_ups"] == ["agent_ended"]
    finally:
        s._utterance_worker.cancel()
        track.stop()
