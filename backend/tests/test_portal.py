import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, generate_unique_id
from app.models.call import Call
from app.models.client import Client
from app.models.user import User
from app.services import billing
from test_phase3c_telephony import telephony_setup  # noqa: F401


def _client_headers(client: TestClient, auth_headers: dict, client_id: str, email: str) -> dict:
    invited = client.post(f"/api/clients/{client_id}/users", headers=auth_headers, json={"email": email, "name": "Portal User"})
    assert invited.status_code == 201, invited.text
    token = create_access_token(subject=invited.json()["id"], claims={"email": email, "role": "CLIENT", "name": "Portal User"})
    return {"Authorization": f"Bearer {token}"}


def _call(db: Session, client_id: str, setup, status="COMPLETED") -> Call:
    call = Call(
        id=generate_unique_id("call_"), client_id=client_id, agent_id=setup["agent"].id,
        agent_version_id=setup["version"].id, caller_number="+914045209348", destination_number="+918008538015",
        direction="OUTBOUND", status=status, duration_seconds=90, provider="exotel",
        provider_call_id=generate_unique_id("exo_"),
    )
    db.add(call)
    db.commit()
    return call


@pytest.fixture
def portal(client: TestClient, auth_headers: dict, telephony_setup, db: Session):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"owner-{cid}@clinic.example.com")
    return {"headers": headers, "client_id": cid}


def test_client_account_cannot_use_internal_apis(client: TestClient, portal):
    h = portal["headers"]
    for method, path in [("get", "/api/agents"), ("get", "/api/clients"), ("get", "/api/telephony/calls"),
                         ("get", "/api/pricing"), ("get", "/api/dashboard/summary")]:
        assert getattr(client, method)(path, headers=h).status_code == 403, path
    me = client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "CLIENT"


def test_portal_shows_only_own_data_and_charge_only(client: TestClient, portal, telephony_setup, db: Session):
    own = _call(db, portal["client_id"], telephony_setup)
    other_client = Client(id=generate_unique_id("cli_"), name="Someone Else", business_type="CLINIC")
    db.add(other_client)
    db.commit()
    foreign = _call(db, other_client.id, telephony_setup)

    listed = client.get("/api/portal/calls", headers=portal["headers"]).json()
    ids = [c["id"] for c in listed]
    assert own.id in ids and foreign.id not in ids
    cost = next(c for c in listed if c["id"] == own.id)["cost"]
    assert "charge_total" in cost and "breakdown" not in cost and "profit" not in cost

    assert client.get(f"/api/portal/calls/{foreign.id}", headers=portal["headers"]).status_code == 404
    detail = client.get(f"/api/portal/calls/{own.id}", headers=portal["headers"]).json()
    assert detail["events"] == [] and detail["usage"] == {}
    assert client.get(f"/api/portal/calls/{foreign.id}/recording", headers=portal["headers"]).status_code == 404


def test_portal_wallet_invoices_and_summary(client: TestClient, auth_headers: dict, portal, db: Session, monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_UPI_ID", "choranta@upi", raising=False)
    billing.record_payment(db, portal["client_id"], 1180, "UTR5", None)

    summary = client.get("/api/portal/summary", headers=portal["headers"]).json()
    assert summary["wallet"]["balance_inr"] == 1000.0
    assert len(summary["daily"]) == 30

    invoices = client.get("/api/portal/invoices", headers=portal["headers"]).json()
    assert len(invoices) == 1
    pdf = client.get(f"/api/portal/invoices/{invoices[0]['id']}/pdf", headers=portal["headers"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # Another client's invoice is invisible
    other = Client(id=generate_unique_id("cli_"), name="Other", business_type="CLINIC")
    db.add(other)
    db.commit()
    foreign = billing.record_payment(db, other.id, 1180, None, None)
    assert client.get(f"/api/portal/invoices/{foreign['invoice_id']}/pdf", headers=portal["headers"]).status_code == 404

    assert client.get("/api/portal/payment-instructions", headers=portal["headers"]).json()["upi_id"] == "choranta@upi"


def test_internal_users_cannot_use_portal_and_invites_are_validated(client: TestClient, auth_headers: dict, telephony_setup):
    assert client.get("/api/portal/summary", headers=auth_headers).status_code == 403
    cid = telephony_setup["client"].id
    # An internal staff email can't be turned into a client login
    resp = client.post(f"/api/clients/{cid}/users", headers=auth_headers, json={"email": settings.INITIAL_ADMIN_EMAIL})
    assert resp.status_code == 409


def test_removed_client_login_is_deactivated(client: TestClient, auth_headers: dict, portal, db: Session):
    users = client.get(f"/api/clients/{portal['client_id']}/users", headers=auth_headers).json()
    assert client.delete(f"/api/clients/{portal['client_id']}/users/{users[0]['id']}", headers=auth_headers).status_code == 204
    assert db.get(User, users[0]["id"]).status == "INACTIVE"
