import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.client import Client
from app.services import billing, sarvam_voices
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers, portal  # noqa: F401

CO = {"company_name": "Request Test Clinic", "business_type": "CLINIC", "languages": ["en-IN"]}


def _paid(db: Session, client_id: str) -> None:
    billing.record_payment(db, client_id, 1180, "UTR-REQ", None)


def test_clients_get_sequential_unique_codes(client: TestClient, auth_headers: dict, db: Session):
    first = client.post("/api/clients", headers=auth_headers, json={"name": "Code Clinic A", "business_type": "CLINIC"}).json()
    second = client.post("/api/clients", headers=auth_headers, json={"name": "Code Clinic B", "business_type": "CLINIC"}).json()
    assert first["client_code"].startswith("CL-") and second["client_code"].startswith("CL-")
    assert int(second["client_code"][3:]) == int(first["client_code"][3:]) + 1
    found = client.get("/api/clients", headers=auth_headers, params={"search": second["client_code"]}).json()["items"]
    assert [c["id"] for c in found] == [second["id"]]


def test_portal_summary_shows_client_code(client: TestClient, portal, db: Session):
    code = db.get(Client, portal["client_id"]).client_code
    assert code and client.get("/api/portal/summary", headers=portal["headers"]).json()["client_code"] == code


def test_voices_listed_and_preview_cached(client: TestClient, portal, monkeypatch):
    voices = client.get("/api/portal/voices", headers=portal["headers"]).json()
    assert {"id": "priya", "name": "Priya"}.items() <= next(v for v in voices if v["id"] == "priya").items()

    calls = []
    monkeypatch.setattr(sarvam_voices.settings, "SARVAM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sarvam_voices, "_synthesize", lambda voice: calls.append(voice) or b"\x01\x00" * 1600)
    sarvam_voices._previews.clear()
    for _ in range(2):
        resp = client.get("/api/portal/voices/priya/preview", headers=portal["headers"])
        assert resp.status_code == 200 and resp.headers["content-type"] == "audio/wav"
    assert calls == ["priya"]  # second listen is free
    assert client.get("/api/portal/voices/not-a-voice/preview", headers=portal["headers"]).status_code == 404


def test_request_needs_payment_and_unique_name(client: TestClient, portal, db: Session, company):
    headers = portal["headers"]
    body = {**CO, "name": "Priya", "voice_id": "priya"}
    listing = client.get("/api/portal/agent-requests", headers=headers).json()
    assert listing["can_request"] is False
    assert client.post("/api/portal/agent-requests", headers=headers, json=body).status_code == 402

    _paid(db, portal["client_id"])
    assert client.get("/api/portal/agent-requests", headers=headers).json()["can_request"] is True
    created = client.post("/api/portal/agent-requests", headers=headers, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "PENDING" and created.json()["client_code"]

    assert client.post("/api/portal/agent-requests", headers=headers, json={**CO, "name": " priya ", "voice_id": "neha"}).status_code == 409
    assert client.post("/api/portal/agent-requests", headers=headers, json={**CO, "name": "Neha", "voice_id": "nobody"}).status_code == 422

    # Cancelling frees the name
    assert client.delete(f"/api/portal/agent-requests/{created.json()['id']}", headers=headers).json()["status"] == "CANCELLED"
    assert client.post("/api/portal/agent-requests", headers=headers, json=body).status_code == 201


def test_admin_builds_agent_from_request(client: TestClient, auth_headers: dict, operator_headers: dict, portal,
                                         telephony_setup, db: Session, company):
    _paid(db, portal["client_id"])
    req = client.post("/api/portal/agent-requests", headers=portal["headers"], json={**CO, "name": "Kavya", "voice_id": "kavya"}).json()

    queue = client.get("/api/agent-requests", headers=operator_headers, params={"status": "OPEN"}).json()
    assert req["id"] in [r["id"] for r in queue]
    assert client.get("/api/agent-requests/count", headers=operator_headers).json()["pending"] >= 1
    assert client.post(f"/api/agent-requests/{req['id']}/start", headers=operator_headers).status_code == 403

    assert client.post(f"/api/agent-requests/{req['id']}/start", headers=auth_headers).json()["status"] == "IN_PROGRESS"
    # The agent must belong to the requesting client
    other = client.post("/api/clients", headers=auth_headers, json={"name": "Other Co Requests", "business_type": "CLINIC"}).json()
    foreign = client.post("/api/agents", headers=auth_headers, json={"client_id": other["id"], "name": "Kavya", "role": "Receptionist"})
    assert foreign.status_code in (200, 201), foreign.text
    assert client.post(f"/api/agent-requests/{req['id']}/complete", headers=auth_headers,
                       json={"agent_id": foreign.json()["id"]}).status_code == 422

    done = client.post(f"/api/agent-requests/{req['id']}/complete", headers=auth_headers,
                       json={"agent_id": telephony_setup["agent"].id}).json()
    assert done["status"] == "COMPLETED" and done["agent_id"] == telephony_setup["agent"].id
    mine = client.get("/api/portal/agent-requests", headers=portal["headers"]).json()["requests"]
    assert next(r for r in mine if r["id"] == req["id"])["agent_name"] == telephony_setup["agent"].name


def test_admin_rejects_with_reason(client: TestClient, auth_headers: dict, portal, db: Session, company):
    _paid(db, portal["client_id"])
    req = client.post("/api/portal/agent-requests", headers=portal["headers"], json={**CO, "name": "Rohan", "voice_id": "rohan"}).json()
    assert client.post(f"/api/agent-requests/{req['id']}/reject", headers=auth_headers, json={"note": " "}).status_code == 422
    rejected = client.post(f"/api/agent-requests/{req['id']}/reject", headers=auth_headers, json={"note": "Duplicate of Priya"}).json()
    assert rejected["status"] == "REJECTED" and rejected["admin_note"] == "Duplicate of Priya"


def test_portal_me_returns_client_code(client: TestClient, portal, db: Session):
    me = client.get("/api/portal/me", headers=portal["headers"]).json()
    assert me["client_id"] == portal["client_id"] and me["client_code"] == db.get(Client, portal["client_id"]).client_code


def test_request_with_name_only(client: TestClient, portal, db: Session, company):
    _paid(db, portal["client_id"])
    created = client.post("/api/portal/agent-requests", headers=portal["headers"], json={**CO, "name": "Anika"})
    assert created.status_code == 201, created.text
    assert created.json()["voice_id"] is None and created.json()["voice_name"] is None


def test_request_collects_company_and_type_and_updates_profile(client: TestClient, portal, db: Session, company):
    _paid(db, portal["client_id"])
    options = client.get("/api/portal/agent-requests/options", headers=portal["headers"]).json()
    assert {"id": "CLINIC", "label": "Clinic"} in options["business_types"]
    assert options["company_name"] == db.get(Client, portal["client_id"]).name

    body = {"company_name": "  Smile   Dental Care ", "business_type": "clinic", "name": "Meera", "languages": ["te", "en-IN"]}
    created = client.post("/api/portal/agent-requests", headers=portal["headers"], json=body)
    assert created.status_code == 201, created.text
    out = created.json()
    assert (out["company_name"], out["business_type"], out["business_type_label"]) == ("Smile Dental Care", "CLINIC", "Clinic")
    assert out["languages"] == ["te", "en-IN"] and out["language_labels"] == ["Telugu", "English"]
    assert {"id": "te", "label": "Telugu"} in options["languages"]
    profile = db.get(Client, portal["client_id"])
    db.refresh(profile)
    assert (profile.name, profile.business_type) == ("Smile Dental Care", "CLINIC")

    assert client.post("/api/portal/agent-requests", headers=portal["headers"],
                       json={**body, "name": "Asha", "business_type": "SPACESHIP"}).status_code == 422
    assert client.post("/api/portal/agent-requests", headers=portal["headers"],
                       json={"business_type": "CLINIC", "name": "Asha"}).status_code == 422  # company name required


def test_company_name_used_by_another_client_keeps_profile_name(client: TestClient, auth_headers: dict, portal,
                                                                db: Session, company):
    _paid(db, portal["client_id"])
    other = client.post("/api/clients", headers=auth_headers, json={"name": "Taken Name Pvt Ltd", "business_type": "HOTEL"}).json()
    before = db.get(Client, portal["client_id"]).name
    resp = client.post("/api/portal/agent-requests", headers=portal["headers"],
                       json={"company_name": "taken name pvt ltd", "business_type": "HOTEL", "name": "Ravi", "languages": ["hi"]})
    assert resp.status_code == 201 and resp.json()["company_name"] == "taken name pvt ltd"
    profile = db.get(Client, portal["client_id"])
    db.refresh(profile)
    assert profile.name == before and profile.business_type == "HOTEL" and other["id"] != profile.id


def test_request_needs_a_valid_language(client: TestClient, portal, db: Session, company):
    _paid(db, portal["client_id"])
    base = {"company_name": "Lang Test Co", "business_type": "OTHER", "name": "Lingo"}
    assert client.post("/api/portal/agent-requests", headers=portal["headers"], json=base).status_code == 422
    assert client.post("/api/portal/agent-requests", headers=portal["headers"], json={**base, "languages": ["xx"]}).status_code == 422
    assert client.post("/api/portal/agent-requests", headers=portal["headers"], json={**base, "languages": ["kn"]}).status_code == 201


def test_studio_lists_sarvam_voices_with_preview(client: TestClient, auth_headers: dict, monkeypatch):
    voices = client.get("/api/catalogs/sarvam-voices", headers=auth_headers).json()
    assert len(voices) == len(sarvam_voices.SARVAM_VOICES) and all(v["provider"] == "sarvam" for v in voices)
    monkeypatch.setattr(sarvam_voices.settings, "SARVAM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sarvam_voices, "_synthesize", lambda voice: b"\x01\x00" * 1600)
    sarvam_voices._previews.clear()
    resp = client.get("/api/catalogs/sarvam-voices/neha/preview", headers=auth_headers)
    assert resp.status_code == 200 and resp.headers["content-type"] == "audio/wav"
