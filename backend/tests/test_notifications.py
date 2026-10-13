import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.notification import ClientNotification
from app.models.subscription import Plan
from app.services import billing
from test_billing import _completed_call, company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers, portal  # noqa: F401


def _kinds(db: Session, client_id: str):
    return [n.kind for n in db.query(ClientNotification).filter(ClientNotification.client_id == client_id)
            .order_by(ClientNotification.created_at).all()]


@pytest.fixture
def plan(db: Session) -> Plan:
    p = Plan(name="Starter", monthly_price_inr=2999.0, included_minutes=10, overage_per_minute_inr=7.0,
             monthly_credits=50.0, max_concurrent_calls=2, is_active=True)
    db.add(p)
    db.commit()
    return p


def test_plan_purchase_nudges_first_ai_employee(client: TestClient, portal, plan, db: Session, company):
    cid = portal["client_id"]
    db.query(ClientNotification).filter(ClientNotification.client_id == cid).delete()
    db.commit()
    me = client.get("/api/portal/me", headers=portal["headers"]).json()

    billing.pay_for_plan(db, cid, plan, "UTR-N1", None)
    note = db.query(ClientNotification).filter(ClientNotification.client_id == cid, ClientNotification.kind == "PLAN_ACTIVE").one()
    if me["has_ai_employee"]:
        assert note.link == "/portal/billing"
    else:
        assert note.link == "/portal/employees" and "first AI employee" in note.body

    listed = client.get("/api/portal/notifications", headers=portal["headers"]).json()
    assert listed["unread"] >= 1 and listed["items"][0]["title"] == "Your Starter plan is active"
    after = client.post("/api/portal/notifications/read", headers=portal["headers"]).json()
    assert after["unread"] == 0 and all(i["read"] for i in after["items"])


def test_first_employee_link_when_client_has_none(db: Session, plan, company):
    from app.models.client import Client
    client = Client(id="cli_notif_fresh", name="Fresh Notif Co", business_type="OTHER", status="ACTIVE")
    db.add(client)
    db.commit()
    billing.pay_for_plan(db, client.id, plan, "UTR-N2", None)
    note = db.query(ClientNotification).filter(ClientNotification.client_id == client.id).one()
    assert note.kind == "PLAN_ACTIVE" and note.link == "/portal/employees"


def test_credits_added_and_running_low_then_out(db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    db.query(ClientNotification).filter(ClientNotification.client_id == cid).delete()
    db.commit()
    billing.record_payment(db, cid, 1180, None, None)  # 1000 bought credits
    assert _kinds(db, cid) == ["CREDITS_ADDED"]

    wallet = billing.get_wallet(db, cid)
    wallet.balance_inr = 501.0  # just above the 500 alert line
    db.commit()
    billing.charge_call(db, _completed_call(db, telephony_setup, duration=120))
    assert _kinds(db, cid).count("CREDITS_LOW") == 1
    billing.charge_call(db, _completed_call(db, telephony_setup, duration=120))
    assert _kinds(db, cid).count("CREDITS_LOW") == 1  # told once, not on every call

    wallet = billing.get_wallet(db, cid)
    wallet.balance_inr = 1.0
    db.commit()
    billing.charge_call(db, _completed_call(db, telephony_setup, duration=120))
    assert _kinds(db, cid).count("CREDITS_OUT") == 1


def test_employee_ready_notification(client: TestClient, auth_headers: dict, portal, telephony_setup, db: Session, company):
    cid = portal["client_id"]
    billing.record_payment(db, cid, 1180, "UTR-N3", None)
    req = client.post("/api/portal/agent-requests", headers=portal["headers"], json={"company_name": "Notify Clinic", "business_type": "CLINIC", "name": "Notify Bot", "languages": ["en-IN"]}).json()
    client.post(f"/api/agent-requests/{req['id']}/start", headers=auth_headers)
    client.post(f"/api/agent-requests/{req['id']}/complete", headers=auth_headers, json={"agent_id": telephony_setup["agent"].id})
    # Rows made within the same clock tick can share a timestamp, so look them up by kind, not position
    kinds = _kinds(db, cid)
    assert "EMPLOYEE_SETUP" in kinds and "EMPLOYEE_READY" in kinds
    items = client.get("/api/portal/notifications", headers=portal["headers"]).json()["items"]
    ready = next(i for i in items if i["kind"] == "EMPLOYEE_READY")
    assert ready["title"] == "Notify Bot is ready!" and ready["link"] == "/portal/numbers"
    # Marking one read only affects that one
    out = client.post(f"/api/portal/notifications/{ready['id']}/read", headers=portal["headers"]).json()
    assert next(i for i in out["items"] if i["id"] == ready["id"])["read"] is True
