import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User


@pytest.fixture
def google(monkeypatch):
    """Replaces Google's token verification with a lookup of fake credentials."""
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com", raising=False)
    tokens = {}

    def verify(credential, request, audience):
        assert audience == settings.GOOGLE_CLIENT_ID
        if credential not in tokens:
            raise ValueError("bad token")
        return tokens[credential]

    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    return tokens


def test_invited_user_signs_in_with_google(client: TestClient, google):
    google["good"] = {"email": "Operator@Choranta.internal", "email_verified": True}
    resp = client.post("/api/auth/google", json={"credential": "good"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["role"] == "OPERATOR"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.json()["email"] == "operator@choranta.internal"


@pytest.mark.parametrize("claims,expected", [
    ({"email": "operator@choranta.internal", "email_verified": False}, "isn't verified"),
])
def test_google_sign_in_rejections(client: TestClient, google, claims, expected):
    google["t"] = claims
    resp = client.post("/api/auth/google", json={"credential": "t"})
    assert resp.status_code == 401 and expected in resp.json()["error"]


def test_new_google_user_signs_up_as_client(client: TestClient, google, db: Session, monkeypatch):
    google["new"] = {"email": "Owner@NewClinic.example.com", "email_verified": True, "name": "Asha Rao"}
    resp = client.post("/api/auth/google", json={"credential": "new"})
    assert resp.status_code == 200, resp.text
    user = resp.json()["user"]
    assert user["role"] == "CLIENT" and user["email"] == "owner@newclinic.example.com"
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert client.get("/api/portal/summary", headers=headers).json()["client_name"] == "Asha Rao"
    assert client.get("/api/agents", headers=headers).status_code == 403  # no internal access

    # Signing in again reuses the same account
    again = client.post("/api/auth/google", json={"credential": "new"}).json()
    assert again["user"]["id"] == user["id"]

    monkeypatch.setattr(settings, "CLIENT_SELF_SIGNUP", False, raising=False)
    google["stranger"] = {"email": "stranger@gmail.com", "email_verified": True}
    blocked = client.post("/api/auth/google", json={"credential": "stranger"})
    assert blocked.status_code == 401 and "hasn't been invited" in blocked.json()["error"]


def test_invalid_google_token_and_inactive_user(client: TestClient, google, db: Session):
    assert client.post("/api/auth/google", json={"credential": "forged"}).status_code == 401
    db.add(User(id="usr_gone", email="gone@choranta.internal", name="Gone", role="OPERATOR", status="INACTIVE"))
    db.commit()
    google["gone"] = {"email": "gone@choranta.internal", "email_verified": True}
    assert client.post("/api/auth/google", json={"credential": "gone"}).status_code == 401


def test_password_login_only_for_initial_admin(client: TestClient):
    ok = client.post("/api/auth/login", json={"email": settings.INITIAL_ADMIN_EMAIL, "password": settings.INITIAL_ADMIN_PASSWORD})
    assert ok.status_code == 200
    blocked = client.post("/api/auth/login", json={"email": "operator@choranta.internal", "password": "operatorPass2026!"})
    assert blocked.status_code == 401 and "Google" in blocked.json()["error"]


def test_google_not_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "", raising=False)
    resp = client.post("/api/auth/google", json={"credential": "x"})
    assert resp.status_code == 401 and "GOOGLE_CLIENT_ID" in resp.json()["error"]
    assert client.get("/api/auth/config").json() == {"google_client_id": None}
