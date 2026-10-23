import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.call import Call
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony.vobiz import VobizTelephonyProvider, vobiz_call_status
from test_phase3c_telephony import telephony_setup  # noqa: F401  (fixture)


def test_vobiz_answer_xml_streams_to_media_websocket():
    xml = VobizTelephonyProvider().generate_connect_response("wss://x.example.com/ws?token=a&call=b", "b")
    assert '<Stream bidirectional="true" keepCallAlive="true" audioTrack="inbound"' in xml
    assert 'contentType="audio/x-l16;rate=8000"' in xml
    # The URL's & must be escaped, and the call ends once we close the stream
    assert "wss://x.example.com/ws?token=a&amp;call=b</Stream><Hangup/>" in xml


def test_vobiz_reject_xml_speaks_then_hangs_up():
    xml = VobizTelephonyProvider().generate_reject_response("Closed <today>")
    assert "<Speak>Closed &lt;today&gt;</Speak><Hangup/>" in xml


def test_vobiz_stream_messages():
    provider = VobizTelephonyProvider()
    assert provider.parse_stream_start({"event": "start", "streamId": "s1", "start": {"callId": "c1"}}) == ("s1", "c1")
    assert provider.parse_stream_start({"event": "start", "start": {"streamId": "s2", "callUUID": "c2"}}) == ("s2", "c2")

    play = json.loads(provider.build_media_message("s1", b"\x01\x02"))
    assert play == {"event": "playAudio", "streamId": "s1",
                    "media": {"contentType": "audio/x-l16", "sampleRate": 8000,
                              "payload": base64.b64encode(b"\x01\x02").decode()}}
    assert json.loads(provider.build_clear_message("s1")) == {"event": "clearAudio", "streamId": "s1"}


def test_vobiz_inbound_params_normalized():
    payload = VobizTelephonyProvider().parse_inbound_call_webhook(
        {"CallUUID": "uuid-1", "From": "919876543210", "To": "+918071234567"})
    assert (payload.provider_call_id, payload.caller_number, payload.destination_number, payload.provider) == (
        "uuid-1", "+919876543210", "+918071234567", "vobiz")


@pytest.mark.parametrize("params, expected", [
    ({"CallStatus": "completed", "Duration": "42"}, ("completed", 42.0)),
    ({"CallStatus": "timeout"}, ("no-answer", 0.0)),
    ({"CallStatus": "busy"}, ("busy", 0.0)),
    ({"HangupCause": "USER_BUSY"}, ("busy", 0.0)),
    ({"HangupCause": "NO_ANSWER"}, ("no-answer", 0.0)),
    ({"HangupCause": "NORMAL_CLEARING", "Duration": "12"}, ("completed", 12.0)),
    ({"HangupCause": "UNALLOCATED_NUMBER"}, ("failed", 0.0)),
])
def test_vobiz_call_status(params, expected):
    assert vobiz_call_status(params) == expected


@pytest.fixture
def vobiz_carrier(monkeypatch):
    """The real Vobiz adapter (with its HTTP call to Vobiz faked), and Vobiz as the default carrier."""
    provider = VobizTelephonyProvider(auth_id="MA_TEST", auth_token="tok", webhook_secret="vobiz_secret")
    dialed = []

    def fake_dial(customer_number, caller_id, flow_url, status_callback_url=None, custom_field=None):
        dialed.append({"to": customer_number, "from": caller_id, "answer_url": flow_url, "hangup_url": status_callback_url})
        return {"api_id": "api-1", "message": "call fired", "request_uuid": "req-123"}

    monkeypatch.setattr(provider, "initiate_outbound_call", fake_dial)
    monkeypatch.setitem(default_registry._telephony_providers, "vobiz", provider)
    for name, value in {"TELEPHONY_PROVIDER": "vobiz", "TELEPHONY_BASE_URL": "https://choranta.example.com",
                        "VOBIZ_AUTH_ID": "MA_TEST", "VOBIZ_AUTH_TOKEN": "tok", "VOBIZ_WEBHOOK_SECRET": "vobiz_secret",
                        "VOBIZ_CALLER_ID": "+918071234567"}.items():
        monkeypatch.setattr(settings, name, value, raising=False)
    return dialed


def test_vobiz_outbound_call_answered_and_hung_up(
    client: TestClient, telephony_setup, auth_headers, db: Session, vobiz_carrier,  # noqa: F811
):
    body = {
        "agent_id": telephony_setup["agent"].id,
        "agent_version_id": telephony_setup["version"].id,
        "destination_number": "09876543210",
        "is_test": True,
    }
    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["provider"] == "vobiz"
    assert data["caller_number"] == "+918071234567"
    assert data["provider_call_id"] == "req-123"

    # Vobiz is given webhook URLs carrying our secret and the Call's id
    answer_url = urlparse(vobiz_carrier[0]["answer_url"])
    assert answer_url.path == "/api/telephony/vobiz/answer"
    assert parse_qs(answer_url.query) == {"token": ["vobiz_secret"], "call_id": [data["id"]]}
    assert urlparse(vobiz_carrier[0]["hangup_url"]).path == "/api/telephony/vobiz/hangup"

    # A webhook without the secret is refused
    assert client.post("/api/telephony/vobiz/answer", params={"call_id": data["id"]},
                       data={"CallUUID": "uuid-9"}).status_code == 403

    # The customer answers: the Call takes Vobiz's CallUUID and the agent's session starts
    answered = client.post(f"{answer_url.path}?{answer_url.query}",
                           data={"CallUUID": "uuid-9", "From": "+918071234567", "To": "919876543210",
                                 "Direction": "outbound"})
    assert answered.status_code == 200
    assert answered.headers["content-type"].startswith("application/xml")
    assert "wss://choranta.example.com/ws/telephony/vobiz/media?token=vobiz_secret&amp;call=uuid-9" in answered.text
    call = db.get(Call, data["id"])
    db.refresh(call)
    assert call.provider_call_id == "uuid-9"
    assert call.status == "ANSWERED"
    assert call.runtime_session_id is not None

    hangup_url = urlparse(vobiz_carrier[0]["hangup_url"])
    ended = client.post(f"{hangup_url.path}?{hangup_url.query}",
                        data={"CallUUID": "uuid-9", "CallStatus": "completed", "Duration": "37",
                              "HangupCause": "NORMAL_CLEARING"})
    assert ended.json() == {"status": "processed", "call_id": data["id"]}
    db.refresh(call)
    assert call.status == "COMPLETED"
    assert call.duration_seconds == 37


def test_vobiz_unanswered_call_marked_failed(
    client: TestClient, telephony_setup, auth_headers, db: Session, vobiz_carrier,  # noqa: F811
):
    resp = client.post("/api/telephony/calls/outbound", headers=auth_headers, json={
        "agent_id": telephony_setup["agent"].id,
        "agent_version_id": telephony_setup["version"].id,
        "destination_number": "09876543210",
        "is_test": True,
    })
    call_id = resp.json()["id"]
    hangup_url = urlparse(vobiz_carrier[0]["hangup_url"])
    client.post(f"{hangup_url.path}?{hangup_url.query}",
                data={"RequestUUID": "req-123", "CallStatus": "timeout", "HangupCause": "NO_ANSWER"})
    call = db.get(Call, call_id)
    db.refresh(call)
    assert (call.status, call.termination_reason) == ("FAILED", "no-answer")


def test_vobiz_inbound_call_routed_by_number(
    client: TestClient, telephony_setup, db: Session, vobiz_carrier,  # noqa: F811
):
    pn = telephony_setup["phone_number"]
    pn.provider = "vobiz"
    db.commit()
    resp = client.post("/api/telephony/vobiz/answer?token=vobiz_secret",
                       data={"CallUUID": "uuid-in-1", "From": "919876543210", "To": pn.phone_number.lstrip("+")})
    assert resp.status_code == 200
    assert "/ws/telephony/vobiz/media" in resp.text
    call = db.query(Call).filter(Call.provider_call_id == "uuid-in-1").first()
    assert call is not None
    assert (call.provider, call.direction, call.caller_number) == ("vobiz", "INBOUND", "+919876543210")

    # An unknown number is told so, then hung up on
    resp = client.post("/api/telephony/vobiz/answer?token=vobiz_secret",
                       data={"CallUUID": "uuid-in-2", "From": "919876543210", "To": "918000000000"})
    assert "<Speak>" in resp.text and "<Hangup/>" in resp.text
