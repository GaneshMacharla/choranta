import pytest
from app.models.client import Client
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.runtime_session import RuntimeSession
from app.schemas.agent_spec import CanonicalAgentSpec, IdentitySpec, InstructionsSpec, ConversationSpec, VoiceSpec, ProvidersSpec
from app.runtime.lifecycle import SessionStatus


def test_webrtc_offer_requires_auth(client):
    res = client.post("/api/runtime/sessions/ses_mock123/webrtc/offer", json={"sdp": "v=0...", "type": "offer"})
    assert res.status_code == 401


def test_webrtc_offer_nonexistent_session(client, auth_headers):
    res = client.post(
        "/api/runtime/sessions/ses_nonexistent/webrtc/offer",
        json={"sdp": "v=0...", "type": "offer"},
        headers=auth_headers
    )
    assert res.status_code == 404


def test_webrtc_close_endpoint(client, auth_headers):
    res = client.post("/api/runtime/sessions/ses_mock123/webrtc/close", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "closed"
