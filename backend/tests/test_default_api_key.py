from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.api_key import ApiKey
from app.services import instant_leads
from app.services.auth_service import AuthService
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers


def _active(db: Session, client_id: str):
    return db.query(ApiKey).filter(ApiKey.client_id == client_id, ApiKey.revoked_at.is_(None)).all()


def test_google_sign_up_creates_a_default_key(db: Session):
    user = AuthService(db)._sign_up_client("new-centre@example.com", "New Centre")
    from app.models.billing import ClientUser
    client_id = db.get(ClientUser, user.id).client_id
    keys = _active(db, client_id)
    assert len(keys) == 1 and keys[0].is_default
    raw = instant_leads.reveal_key(keys[0])
    assert raw.startswith(instant_leads.KEY_PREFIX) and raw not in keys[0].key_enc
    assert instant_leads.authenticate(db, raw).client_id == client_id


def test_admin_created_client_gets_a_default_key(client: TestClient, auth_headers: dict, db: Session):
    created = client.post("/api/clients", headers=auth_headers, json={"name": "Bright Minds Academy", "business_type": "COACHING"})
    assert created.status_code == 201, created.text
    assert [k.is_default for k in _active(db, created.json()["id"])] == [True]


def test_dashboard_setup_reveal_and_regenerate(client: TestClient, auth_headers: dict, db: Session, telephony_setup):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"owner-{cid}@instant.example.com")

    # A client from before automatic keys gets one when the dashboard opens
    setup = client.get("/api/portal/instant-setup", headers=headers).json()
    assert setup["key"]["prefix"].startswith(instant_leads.KEY_PREFIX)
    assert setup["leads_url"].endswith("/api/public/leads") and setup["running"] is False
    assert client.get("/api/portal/instant-setup", headers=headers).json()["key"]["id"] == setup["key"]["id"]

    old = client.post("/api/portal/instant-setup/key", headers=headers).json()["key"]
    assert old.startswith(setup["key"]["prefix"])

    renewed = client.post("/api/portal/instant-setup/key/regenerate", headers=headers).json()
    assert renewed["key"]["id"] != setup["key"]["id"]
    new = client.post("/api/portal/instant-setup/key", headers=headers).json()["key"]
    assert new != old
    instant_leads._key_cache.clear()
    assert instant_leads.authenticate(db, new).client_id == cid
    try:
        instant_leads.authenticate(db, old)
        raise AssertionError("the replaced key still works")
    except instant_leads.LeadError:
        pass


def test_hand_made_keys_are_never_shown_again(db: Session, telephony_setup):
    key, _ = instant_leads.create_api_key(db, telephony_setup["client"].id, "Zapier", None)
    assert key.key_enc is None
    try:
        instant_leads.reveal_key(key)
        raise AssertionError("revealed a hand-made key")
    except instant_leads.LeadError:
        pass
