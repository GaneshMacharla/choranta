"""
Client trial: before an AI employee goes live, the team sends it to the client, who tries it once with a short,
free browser call. The client only tests; the team still decides when it goes live.

WebRTC itself is replaced by a fake call, so these tests cover who may call, how many times, and what's recorded.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes import webrtc_audio
from app.core.config import settings
from app.models.agent_request import AgentRequest
from app.models.call import Call
from app.models.notification import ClientNotification
from app.services import agent_requests as svc
from app.services import billing
from test_agent_requests import CO, _paid
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers, portal  # noqa: F401

OFFER = {"sdp": "v=0", "type": "offer"}


class FakeBrowserCall:
    """Stands in for the WebRTC call: answers the offer, and ends by calling the end hook like the real one."""
    db: Session = None
    fail_connect = False
    instances: list = []

    def __init__(self, call_id, on_end=None):
        self.call_id, self.on_end, self._started = call_id, on_end, True
        FakeBrowserCall.instances.append(self)

    async def connect(self, offer):
        if FakeBrowserCall.fail_connect:
            raise RuntimeError("bad SDP")
        return SimpleNamespace(sdp="v=0 answer", type="answer")

    async def end(self, reason, connected_seconds=None):
        webrtc_audio.active_browser_calls.pop(self.call_id, None)
        if self.on_end:
            self.on_end(FakeBrowserCall.db, reason, connected_seconds)


@pytest.fixture
def trial(client: TestClient, auth_headers: dict, portal, telephony_setup, db: Session, company, monkeypatch):
    """A request built and linked to a published AI employee, not yet sent to the client."""
    FakeBrowserCall.db, FakeBrowserCall.fail_connect, FakeBrowserCall.instances = db, False, []
    monkeypatch.setattr(webrtc_audio, "BrowserCall", FakeBrowserCall)
    monkeypatch.setattr(webrtc_audio, "CONNECT_TIMEOUT_S", 0)
    monkeypatch.setattr(settings, "CLIENT_TRIAL_CALLS", 1)
    monkeypatch.setattr(settings, "CLIENT_TRIAL_MAX_DURATION_S", 180)
    _paid(db, portal["client_id"])
    req = client.post("/api/portal/agent-requests", headers=portal["headers"], json={**CO, "name": "Tara"}).json()
    linked = client.post(f"/api/agent-requests/{req['id']}/link", headers=auth_headers,
                         json={"agent_id": telephony_setup["agent"].id})
    assert linked.status_code == 200, linked.text
    return {"id": req["id"], "portal": portal["headers"], "admin": auth_headers}


def _send(client, t):
    resp = client.post(f"/api/agent-requests/{t['id']}/send-for-trial", headers=t["admin"])
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trial(client, t):
    return client.post(f"/api/portal/agent-requests/{t['id']}/trial-call", headers=t["portal"], json=OFFER)


def _used(db, t) -> int:
    db.expire_all()
    return db.get(AgentRequest, t["id"]).trial_calls_used


def test_client_tries_it_once_and_the_team_makes_it_live(client: TestClient, trial, operator_headers: dict, db: Session):
    t = trial
    assert _trial(client, t).status_code == 422  # not sent to them yet
    assert client.post(f"/api/agent-requests/{t['id']}/send-for-trial", headers=operator_headers).status_code == 403

    sent = _send(client, t)
    assert sent["status"] == "CLIENT_TRIAL" and sent["trial_calls_used"] == 0 and sent["trial_calls_allowed"] == 1
    assert sent["trial_max_minutes"] == 3
    assert db.query(ClientNotification).filter(ClientNotification.kind == "EMPLOYEE_TRIAL").count() == 1

    started = _trial(client, t)
    assert started.status_code == 201, started.text
    call = db.get(Call, started.json()["call_id"])
    assert call.metadata_["is_test"] is True  # never billed
    assert call.metadata_["max_duration_s"] == 180 and call.metadata_["trial_request_id"] == t["id"]
    assert _used(db, t) == 1

    # One call only; a real conversation keeps it used up
    second = _trial(client, t)
    assert second.status_code == 409 and "already tried" in second.json()["error"]
    FakeBrowserCall.instances[-1].on_end(db, "caller_hangup", 95.0)
    assert _used(db, t) == 1
    mine = client.get("/api/portal/agent-requests", headers=t["portal"]).json()["requests"]
    assert next(r for r in mine if r["id"] == t["id"])["trial_calls_used"] == 1

    # Ending it is checked against the client and the request
    hangup = f"/api/portal/agent-requests/{t['id']}/trial-call/{call.id}/hangup"
    assert client.post(hangup, headers=t["portal"]).status_code == 200
    assert client.post(f"/api/portal/agent-requests/other/trial-call/{call.id}/hangup", headers=t["portal"]).status_code == 404

    # Sending it again gives a fresh call
    assert _send(client, t)["trial_calls_used"] == 0
    assert _trial(client, t).status_code == 201

    # The team still decides when it goes live: completing works straight from the trial
    done = client.post(f"/api/agent-requests/{t['id']}/complete", headers=t["admin"], json={"agent_id": call.agent_id})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"


def test_a_call_that_never_connected_is_given_back(client: TestClient, trial, db: Session):
    t = trial
    _send(client, t)
    assert _trial(client, t).status_code == 201
    FakeBrowserCall.instances[-1].on_end(db, "connection_timeout", None)
    assert _used(db, t) == 0

    assert _trial(client, t).status_code == 201
    FakeBrowserCall.instances[-1].on_end(db, "connection_failed", 4.0)  # dropped straight away
    assert _used(db, t) == 0


def test_failed_setup_gives_the_call_back(client: TestClient, trial, db: Session, monkeypatch):
    t = trial
    _send(client, t)
    FakeBrowserCall.fail_connect = True
    assert _trial(client, t).status_code == 400
    assert _used(db, t) == 0

    FakeBrowserCall.fail_connect = False
    def not_ready(*args, **kwargs):
        raise HTTPException(status_code=422, detail="Not ready")
    monkeypatch.setattr(webrtc_audio, "_create_call_record", not_ready)
    assert _trial(client, t).status_code == 422
    assert _used(db, t) == 0


def test_busy_lines_refuse_a_trial_without_using_it(client: TestClient, trial, db: Session, monkeypatch):
    t = trial
    _send(client, t)
    monkeypatch.setattr(billing, "browser_session_allowed", lambda db: False)
    assert _trial(client, t).status_code == 429
    assert _used(db, t) == 0


def test_other_clients_cannot_try_it(client: TestClient, trial, auth_headers: dict):
    t = trial
    _send(client, t)
    other = client.post("/api/clients", headers=auth_headers, json={"name": "Trial Outsider Co", "business_type": "CLINIC"}).json()
    outsider = _client_headers(client, auth_headers, other["id"], "owner@trial-outsider.example.com")
    assert client.post(f"/api/portal/agent-requests/{t['id']}/trial-call", headers=outsider, json=OFFER).status_code == 404
    assert client.post(f"/api/agent-requests/{t['id']}/send-for-trial", headers=outsider).status_code in (401, 403)


def test_sending_needs_a_built_employee(client: TestClient, auth_headers: dict, portal, db: Session, company):
    _paid(db, portal["client_id"])
    req = client.post("/api/portal/agent-requests", headers=portal["headers"], json={**CO, "name": "Ira"}).json()
    client.post(f"/api/agent-requests/{req['id']}/start", headers=auth_headers)
    resp = client.post(f"/api/agent-requests/{req['id']}/send-for-trial", headers=auth_headers)
    assert resp.status_code == 422 and "Build the AI employee" in resp.json()["error"]


def test_real_browser_call_reports_how_it_ended(monkeypatch):
    """The end hook the trial relies on: a call that never connected reports None for its connected time."""
    import asyncio
    from unittest.mock import MagicMock
    db = MagicMock()
    monkeypatch.setattr(webrtc_audio, "SessionLocal", lambda: db)
    ended = []
    call = webrtc_audio.BrowserCall("call_hook_test", on_end=lambda s, reason, secs: ended.append((s, reason, secs)))
    asyncio.run(call.end("connection_timeout"))
    assert ended == [(db, "connection_timeout", None)]
    assert db.close.called


def test_which_ended_calls_use_up_the_trial():
    assert svc.trial_call_counts("caller_hangup", 60.0) is True
    assert svc.trial_call_counts("max_duration", 180.0) is True
    assert svc.trial_call_counts("connection_timeout", None) is False
    assert svc.trial_call_counts("connection_failed", 5.0) is False
    assert svc.trial_call_counts("connection_failed", 90.0) is True
