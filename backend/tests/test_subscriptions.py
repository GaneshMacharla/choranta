import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.billing import Invoice, WalletTransaction
from app.models.call import Call
from app.models.subscription import CallUsage, PaymentOrder, Plan
from app.services import billing, razorpay_gateway, subscriptions
from test_billing import _completed_call, company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers


@pytest.fixture
def plan(db: Session) -> Plan:
    # 70 credits = 10 minutes at the default 7 credits per minute
    p = Plan(name="Growth", monthly_price_inr=5000.0, included_minutes=10, overage_per_minute_inr=7.0,
             monthly_credits=70.0, max_concurrent_calls=1, is_active=True)
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def razorpay(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_key", raising=False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "secret123", raising=False)
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsecret", raising=False)
    created = []

    def fake_order(amount_paise, receipt, notes):
        created.append(amount_paise)
        return {"id": f"order_{receipt}", "amount": amount_paise}

    monkeypatch.setattr(razorpay_gateway, "_create_razorpay_order", fake_order)
    return created


def _sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _subscribe(db: Session, client_id: str, plan: Plan):
    billing.pay_for_plan(db, client_id, plan, "UTR-PLAN", None)
    return subscriptions.get_subscription(db, client_id)


# ---------------------------------------------------------------- call charging

def test_call_costs_real_cost_plus_profit_from_plan_then_bought_credits(db: Session, telephony_setup, plan, company):
    from app.services.call_costing import estimate_call_cost
    from app.services.pricing import get_pricing
    cid = telephony_setup["client"].id
    _subscribe(db, cid, plan)
    billing.record_payment(db, cid, 1180, None, None)  # 1000 bought credits

    first = _completed_call(db, telephony_setup, duration=2 * 60)
    credits = billing.call_charge(db, first)
    from app.models.runtime_session import RuntimeSession
    usage = db.get(RuntimeSession, first.runtime_session_id).usage_json if first.runtime_session_id else {}
    assert credits == round(estimate_call_cost(first.duration_seconds, usage, get_pricing(db))["charge_total"], 2)
    assert billing.charge_call(db, first) is None  # all from plan credits
    sub = subscriptions.get_subscription(db, cid)
    assert sub.credits_used == pytest.approx(credits)
    assert billing.get_wallet(db, cid).balance_inr == 1000.0

    # Leave 1 plan credit: the next call takes it, and the rest from bought credits
    sub.credits_used = plan.monthly_credits - 1
    db.commit()
    second = _completed_call(db, telephony_setup, duration=5 * 60 + 10)
    cost = billing.call_charge(db, second)
    txn = billing.charge_call(db, second)
    assert txn.amount_inr == pytest.approx(-(cost - 1), abs=0.01)
    usage = db.query(CallUsage).filter(CallUsage.call_id == second.id).one()
    assert usage.plan_credits == 1 and usage.wallet_credits == pytest.approx(cost - 1, abs=0.01)
    assert subscriptions.get_subscription(db, cid).credits_used == plan.monthly_credits
    assert billing.get_wallet(db, cid).balance_inr == pytest.approx(1000 - (cost - 1), abs=0.01)

    assert billing.charge_call(db, second) is None  # billed once
    assert db.query(CallUsage).filter(CallUsage.call_id == second.id).count() == 1


def test_client_without_plan_keeps_pay_as_you_go(db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    billing.record_payment(db, cid, 1180, None, None)
    call = _completed_call(db, telephony_setup)
    expected = billing.call_charge(db, call)
    txn = billing.charge_call(db, call)
    assert txn.amount_inr == -expected
    assert db.query(CallUsage).filter(CallUsage.call_id == call.id).one().plan_id is None


# ---------------------------------------------------------------- call gating

def test_check_call_allowed_rules(db: Session, telephony_setup, plan, company, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True, raising=False)
    cid = telephony_setup["client"].id
    sub = _subscribe(db, cid, plan)
    assert billing.check_call_allowed(db, cid)[0]  # plan credits, no bought credits

    sub.credits_used = plan.monthly_credits
    db.commit()
    allowed, _, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "NO_BALANCE"
    billing.record_payment(db, cid, 118, None, None)
    assert billing.check_call_allowed(db, cid)[0]  # bought credits cover the rest

    live = Call(id=generate_unique_id("call_"), client_id=cid, agent_id=telephony_setup["agent"].id,
                agent_version_id=telephony_setup["version"].id, caller_number="+914045209348",
                destination_number="+918008538015", direction="OUTBOUND", status="ACTIVE", provider="exotel",
                provider_call_id=generate_unique_id("exo_"))
    db.add(live)
    db.commit()
    allowed, _, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "CONCURRENCY"
    live.status = "COMPLETED"
    db.commit()

    # Period ended: allowed during grace, blocked after it
    now = subscriptions.utcnow()
    sub.current_period_end = now - timedelta(days=1)
    db.commit()
    assert billing.check_call_allowed(db, cid)[0]
    assert subscriptions.get_subscription(db, cid).status == "PAST_DUE"
    sub.current_period_end = now - timedelta(days=settings.SUBSCRIPTION_GRACE_DAYS + 1)
    db.commit()
    allowed, _, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "PLAN_EXPIRED"


def test_outbound_call_concurrency_returns_429(client: TestClient, auth_headers: dict, telephony_setup, db: Session,
                                               plan, company, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True, raising=False)
    monkeypatch.setattr(settings, "TELEPHONY_BASE_URL", "https://choranta.example.com", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_CALLER_ID", "04045209348", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_FLOW_ID", "1", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "acct", raising=False)
    _subscribe(db, telephony_setup["client"].id, plan)
    body = {"agent_id": telephony_setup["agent"].id, "agent_version_id": telephony_setup["version"].id,
            "destination_number": "09876543210"}
    assert client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body).status_code == 201
    second = client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body)
    assert second.status_code == 429 and "at a time" in second.json()["detail"]


# ---------------------------------------------------------------- periods

def test_renewals(db: Session, telephony_setup, plan, company):
    cid = telephony_setup["client"].id
    sub = _subscribe(db, cid, plan)
    first_end = sub.current_period_end

    # Early renewal pays the next period; it starts when the current one ends
    billing.pay_for_plan(db, cid, plan, None, None)
    sub = subscriptions.get_subscription(db, cid)
    assert sub.renewed_ahead and sub.current_period_end == first_end
    with pytest.raises(Exception):
        billing.pay_for_plan(db, cid, plan, None, None)  # can't pay two periods ahead
    sub.minutes_used = 7
    subscriptions.refresh_status(sub, now=first_end + timedelta(minutes=1))
    assert sub.current_period_start == first_end and sub.minutes_used == 0 and not sub.renewed_ahead

    # Renewal within grace continues from the old end; after lapse it starts now
    end = sub.current_period_end
    subscriptions.refresh_status(sub, now=end + timedelta(days=1))
    assert sub.status == "PAST_DUE"
    subscriptions.activate_period(db, cid, plan, now=end + timedelta(days=1))
    assert sub.current_period_start == end and sub.status == "ACTIVE"
    lapsed_at = sub.current_period_end + timedelta(days=30)
    subscriptions.refresh_status(sub, now=lapsed_at)
    subscriptions.activate_period(db, cid, plan, now=lapsed_at)
    assert sub.current_period_start == lapsed_at


def test_plan_invoice_has_plan_description(db: Session, telephony_setup, plan, company):
    cid = telephony_setup["client"].id
    result = billing.pay_for_plan(db, cid, plan, "UTR", None)
    invoice = db.get(Invoice, result["invoice_id"])
    assert "Growth plan" in invoice.description and invoice.total_inr == 5900.0 and invoice.taxable_inr == 5000.0
    assert billing.get_wallet(db, cid).balance_inr == 0.0  # plan fees don't credit the wallet


# ---------------------------------------------------------------- Razorpay

def test_portal_razorpay_plan_checkout(client: TestClient, auth_headers: dict, telephony_setup, db: Session,
                                       plan, razorpay, company):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"pay-{cid}@clinic.example.com")

    plans = client.get("/api/plans", headers=headers).json()
    assert any(p["id"] == plan.id and p["monthly_price_with_gst_inr"] == 5900.0 for p in plans)

    order = client.post("/api/portal/payments/orders", headers=headers,
                        json={"purpose": "SUBSCRIPTION", "plan_id": plan.id})
    assert order.status_code == 201, order.text
    order = order.json()
    assert order["amount_paise"] == 590000 and razorpay == [590000]

    bad = client.post(f"/api/portal/payments/orders/{order['order_id']}/verify", headers=headers,
                      json={"razorpay_payment_id": "pay_1", "razorpay_signature": "nope"})
    assert bad.status_code == 400

    sig = _sign("secret123", f"{order['razorpay_order_id']}|pay_1")
    ok = client.post(f"/api/portal/payments/orders/{order['order_id']}/verify", headers=headers,
                     json={"razorpay_payment_id": "pay_1", "razorpay_signature": sig})
    assert ok.status_code == 200 and ok.json()["subscription"]["status"] == "ACTIVE"

    # The webhook for the same payment changes nothing
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_1", "order_id": order["razorpay_order_id"], "amount": 590000}}}}
    body = json.dumps(event).encode()
    hook = client.post("/api/billing/razorpay/webhook", content=body,
                       headers={"X-Razorpay-Signature": _sign("whsecret", body.decode()), "Content-Type": "application/json"})
    assert hook.status_code == 200
    assert db.query(Invoice).filter(Invoice.client_id == cid).count() == 1
    assert client.post("/api/billing/razorpay/webhook", content=body,
                       headers={"X-Razorpay-Signature": "bad"}).status_code == 400

    sub = client.get("/api/portal/subscription", headers=headers).json()
    assert sub["subscription"]["plan"]["name"] == "Growth" and sub["online_payments"] is True


def test_wallet_topup_via_webhook(client: TestClient, auth_headers: dict, telephony_setup, db: Session, razorpay, company):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"top-{cid}@clinic.example.com")
    too_small = client.post("/api/portal/payments/orders", headers=headers, json={"purpose": "WALLET_TOPUP", "amount_inr": 10})
    assert too_small.status_code == 422
    order = client.post("/api/portal/payments/orders", headers=headers,
                        json={"purpose": "WALLET_TOPUP", "amount_inr": 1180}).json()

    event = {"event": "order.paid", "payload": {"payment": {"entity": {
        "id": "pay_top", "order_id": order["razorpay_order_id"], "amount": 118000}}}}
    body = json.dumps(event).encode()
    resp = client.post("/api/billing/razorpay/webhook", content=body,
                       headers={"X-Razorpay-Signature": _sign("whsecret", body.decode())})
    assert resp.status_code == 200
    assert db.get(PaymentOrder, order["order_id"]).status == "PAID"
    assert billing.get_wallet(db, cid).balance_inr == 1000.0
    assert db.query(WalletTransaction).filter(WalletTransaction.client_id == cid, WalletTransaction.type == "CREDIT").count() == 1


def test_admin_plan_api(client: TestClient, auth_headers: dict, operator_headers: dict, telephony_setup, company):
    body = {"name": "Starter", "monthly_price_inr": 2000, "monthly_credits": 2100}
    assert client.post("/api/plans", headers=operator_headers, json=body).status_code == 403
    created = client.post("/api/plans", headers=auth_headers, json=body)
    assert created.status_code == 201
    pid = created.json()["id"]
    updated = client.put(f"/api/plans/{pid}", headers=auth_headers, json={**body, "max_concurrent_calls": 2}).json()
    assert updated["max_concurrent_calls"] == 2

    cid = telephony_setup["client"].id
    assigned = client.post(f"/api/clients/{cid}/subscription", headers=auth_headers,
                           json={"plan_id": pid, "reference": "UTR55"})
    assert assigned.status_code == 200, assigned.text
    got = client.get(f"/api/clients/{cid}/subscription", headers=operator_headers).json()["subscription"]
    assert got["plan"]["name"] == "Starter" and got["credits_remaining"] == 2100
    assert got["plan"]["approx_minutes"] == 300  # 2100 credits at 7 per minute
    cancelled = client.put(f"/api/clients/{cid}/subscription", headers=auth_headers, json={"cancel_at_period_end": True})
    assert cancelled.json()["subscription"]["cancel_at_period_end"] is True


def test_minute_plans_migrate_to_credits(db: Session):
    from app.db.init_db import _migrate_to_credits
    rate = settings.DEFAULT_CREDITS_PER_MINUTE
    cheap = Plan(name="Old Starter", monthly_price_inr=2999.0, included_minutes=300, overage_per_minute_inr=6.0, is_active=True)
    rich = Plan(name="Old Pro", monthly_price_inr=14999.0, included_minutes=2500, overage_per_minute_inr=4.0, is_active=True)
    db.add_all([cheap, rich])
    db.commit()
    _migrate_to_credits(db.connection(), set())
    db.commit()
    db.refresh(cheap)
    db.refresh(rich)
    assert cheap.monthly_credits == 2999.0           # never fewer credits than the price paid
    assert rich.monthly_credits == 2500 * rate      # never fewer minutes than before


# ---------------------------------------------------------------- simulated payments (testing)

@pytest.fixture
def simulated(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "", raising=False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "SIMULATED_PAYMENTS", True, raising=False)
    monkeypatch.setattr(razorpay_gateway, "_create_razorpay_order",
                        lambda *a, **k: pytest.fail("Razorpay must not be called in simulated mode"))


def test_simulated_plan_and_topup_payments(client: TestClient, auth_headers: dict, telephony_setup, plan, company, db: Session, simulated):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"sim-{cid}@clinic.example.com")
    info = client.get("/api/portal/subscription", headers=headers).json()
    assert info["online_payments"] is True and info["simulated_payments"] is True

    order = client.post("/api/portal/payments/orders", headers=headers, json={"purpose": "SUBSCRIPTION", "plan_id": plan.id}).json()
    assert order["simulated"] is True and order["razorpay_order_id"].startswith("sim_")
    paid = client.post(f"/api/portal/payments/orders/{order['order_id']}/simulate", headers=headers).json()
    assert paid["status"] == "PAID" and paid["subscription"]["plan"]["id"] == plan.id
    invoice = db.get(Invoice, paid["invoice_id"])
    assert invoice.payment_reference.startswith("TEST - simulated payment")

    topup = client.post("/api/portal/payments/orders", headers=headers, json={"purpose": "WALLET_TOPUP", "amount_inr": 1180}).json()
    client.post(f"/api/portal/payments/orders/{topup['order_id']}/simulate", headers=headers)
    assert billing.get_wallet(db, cid).balance_inr == 1000.0


def test_simulated_payments_off_by_default(client: TestClient, auth_headers: dict, telephony_setup, plan, company, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "", raising=False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "SIMULATED_PAYMENTS", False, raising=False)
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"nosim-{cid}@clinic.example.com")
    assert client.get("/api/portal/subscription", headers=headers).json()["online_payments"] is False
    assert client.post("/api/portal/payments/orders", headers=headers, json={"purpose": "SUBSCRIPTION", "plan_id": plan.id}).status_code == 422


def test_simulated_payments_refused_in_production():
    from app.core.config import Settings
    with pytest.raises(ValueError, match="SIMULATED_PAYMENTS"):
        Settings(ENVIRONMENT="production", SIMULATED_PAYMENTS=True,
                 DATABASE_URL="postgresql://u:p@localhost/db", JWT_SECRET_KEY="x" * 40, RUNTIME_MODE="mock",
                 CORS_ORIGINS=["https://app.example.com"])
