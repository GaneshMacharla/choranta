import io
import os
import wave

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.call import Call
from app.runtime.telephony.recorder import CallRecorder
from test_phase3c_telephony import telephony_setup  # noqa: F401


def _frames(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())


def test_recorder_aligns_agent_audio_and_separates_channels():
    rec = CallRecorder(start_time=100.0)
    rec.add_caller_audio(b"\x01\x00" * 8000)            # 1 s of caller audio
    rec.add_agent_audio(b"\x02\x00" * 800, play_start=100.5)  # 100 ms of agent audio at t=0.5 s

    channels, rate, data = _frames(rec.to_wav())
    assert (channels, rate) == (2, 8000)
    samples = [int.from_bytes(data[i:i + 2], "little", signed=True) for i in range(0, len(data), 2)]
    left, right = samples[0::2], samples[1::2]
    assert set(left[:8000]) == {1}
    assert right[3999] == 0 and right[4000] == 2 and right[4799] == 2 and right[4800] == 0


def test_recorder_drops_agent_audio_flushed_by_barge_in():
    rec = CallRecorder(start_time=0.0)
    rec.add_agent_audio(b"\x05\x00" * 8000, play_start=0.0)  # 1 s queued
    rec.discard_agent_after(0.25)
    assert rec.duration_seconds == 0.25


def test_recording_endpoint_serves_wav_and_requires_auth(client: TestClient, auth_headers: dict, telephony_setup, db: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RECORDINGS_DIR", str(tmp_path), raising=False)
    call = Call(
        id=generate_unique_id("call_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        caller_number="+918008538015",
        destination_number="+914045209348",
        direction="OUTBOUND",
        status="COMPLETED",
        provider="exotel",
        provider_call_id=generate_unique_id("exo_"),
        metadata_={"recording_file": "rec_test.wav"},
    )
    db.add(call)
    db.commit()

    rec = CallRecorder(start_time=0.0)
    rec.add_caller_audio(b"\x00\x00" * 800)
    (tmp_path / "rec_test.wav").write_bytes(rec.to_wav())

    assert client.get(f"/api/telephony/calls/{call.id}/recording").status_code in (401, 403)
    resp = client.get(f"/api/telephony/calls/{call.id}/recording", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert _frames(resp.content)[0] == 2

    detail = client.get(f"/api/telephony/calls/{call.id}", headers=auth_headers).json()
    assert detail["has_recording"] is True

    os.remove(tmp_path / "rec_test.wav")
    assert client.get(f"/api/telephony/calls/{call.id}/recording", headers=auth_headers).status_code == 404
