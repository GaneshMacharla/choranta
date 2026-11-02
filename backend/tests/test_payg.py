"""Pay-as-you-go only (PAYG_ONLY) and no GST (company not GST-registered yet)."""
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.db.init_db import retire_plans
from app.models.billing import Invoice
from app.models.call import Call
from app.models.subscription import ClientSubscription, Plan
from app.services import billing, campaigns, subscriptions
from app.services.invoice_pdf import render_invoice_pdf
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def payg(monkeypatch):
    monkeypatch.setattr(settings, "PAYG_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "GST_REGISTERED", False, raising=False)
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True, raising=False)


def _live_calls(db: Session, setup, count: int, provider: str = "exotel") -> None:
    for _ in range(count):
        db.add(Call(id=generate_unique_id("call_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
                    agent_version_id=setup["version"].id, caller_number="+914045209348",
                    destination_number="+918008538015", direction="OUTBOUND", status="ACTIVE", provider=provider,
                    provider_call_id=generate_unique_id("exo_")))
    db.commit()


def test_without_gst_the_full_payment_becomes_credits_with_a_receipt(db: Session, telephony_setup, company, payg):
    cid = telephony_setup["client"].id
    split = billing.gst_split(1000, "36")
    assert split["taxable_inr"] == 1000 and split["cgst_inr"] == split["sgst_inr"] == split["igst_inr"] == 0
    assert split["gst_registered"] is False

    result = billing.record_payment(db, cid, 1000, "UTR-1", None)
    assert result["balance_inr"] == 1000.0
    invoice = db.query(Invoice).filter(Invoice.client_id == cid).one()
    assert invoice.total_inr == invoice.taxable_inr == 1000.0
    assert render_invoice_pdf(invoice).startswith(b"%PDF")


def test_pay_as_you_go_calls_at_a_time_follow_the_wallet(db: Session, telephony_setup, company, payg, monkeypatch):
    # 7 credits a minute x 10-minute calls: each live call holds 70 credits
    monkeypatch.setattr(billing, "budget_credits_per_minute", lambda db: 7.0)
    monkeypatch.setattr(settings, "CALL_MAX_DURATION_S", 600, raising=False)
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PER_CLIENT", 50, raising=False)
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PLATFORM", 100, raising=False)
    cid = telephony_setup["client"].id
    assert billing.call_hold_credits(db) == 70.0

    billing.record_payment(db, cid, 500, None, None)
    assert billing.client_concurrency_limit(db, cid) == 7
    assert campaigns.concurrency_cap(db, cid) == 6  # one line kept free for inbound calls

    _live_calls(db, telephony_setup, 7)
    allowed, reason, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "CONCURRENCY" and "add credits" in reason

    # Adding credits allows more calls at once
    billing.record_payment(db, cid, 500, None, None)
    assert billing.client_concurrency_limit(db, cid) == 14
    assert billing.check_call_allowed(db, cid)[0]

    # Never above the platform cap
    billing.record_payment(db, cid, 10000, None, None)
    assert billing.client_concurrency_limit(db, cid) == 50

    # A balance too small for a short call starts none (2 minutes x 7 = 14 credits needed)
    db.query(Call).filter(Call.client_id == cid).delete()
    wallet = billing.get_wallet(db, cid)
    wallet.balance_inr = 13.0
    db.commit()
    assert billing.client_concurrency_limit(db, cid) == 1
    assert campaigns.concurrency_cap(db, cid) == 1  # never below one campaign line
    assert billing.check_call_allowed(db, cid)[2] == "NO_BALANCE"


def test_platform_cap_blocks_calls_across_all_clients(db: Session, telephony_setup, company, payg, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PLATFORM", 3, raising=False)
    cid = telephony_setup["client"].id
    billing.record_payment(db, cid, 10000, None, None)
    _live_calls(db, telephony_setup, 2)
    assert billing.platform_headroom(db) == 1
    assert billing.check_call_allowed(db, cid)[0]

    # Live calls of any client count, test calls included
    _live_calls(db, telephony_setup, 1)
    db.query(Call).filter(Call.client_id == cid).first().client_id = "cli_other"
    db.commit()
    assert billing.platform_headroom(db) == 0
    allowed, reason, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "CONCURRENCY" and reason == billing.PLATFORM_BUSY_REASON


def test_vobiz_account_lines_are_shared_by_all_clients(db: Session, telephony_setup, company, payg, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PLATFORM", 10, raising=False)
    monkeypatch.setattr(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 3)
    cid = telephony_setup["client"].id
    billing.record_payment(db, cid, 10000, None, None)
    _live_calls(db, telephony_setup, 4)  # Exotel calls don't use Vobiz lines
    _live_calls(db, telephony_setup, 2, provider="vobiz")
    assert billing.platform_headroom(db) == 1

    # Another client's Vobiz call takes the last line, inbound or outbound
    _live_calls(db, telephony_setup, 1, provider="vobiz")
    db.query(Call).filter(Call.client_id == cid, Call.provider == "vobiz").first().client_id = "cli_other"
    db.commit()
    assert billing.platform_headroom(db) == 0
    allowed, reason, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "CONCURRENCY" and reason == billing.PLATFORM_BUSY_REASON


def test_ended_plan_falls_back_to_credits_instead_of_blocking(db: Session, telephony_setup, company, payg):
    cid = telephony_setup["client"].id
    plan = Plan(name="Starter", monthly_price_inr=2999.0, included_minutes=300, overage_per_minute_inr=7.0,
                monthly_credits=2999.0, max_concurrent_calls=1, is_active=True)
    db.add(plan)
    db.commit()
    subscriptions.activate_period(db, cid, plan)
    sub = subscriptions.get_subscription(db, cid)
    sub.current_period_end = subscriptions.utcnow() - timedelta(days=settings.SUBSCRIPTION_GRACE_DAYS + 1)
    db.commit()

    allowed, reason, code = billing.check_call_allowed(db, cid)
    assert not allowed and code == "NO_BALANCE" and "Choose a plan" not in reason
    billing.record_payment(db, cid, 500, None, None)
    assert billing.check_call_allowed(db, cid)[0]


def test_retire_plans_is_idempotent(db: Session, telephony_setup, payg):
    cid = telephony_setup["client"].id
    plan = Plan(name="Pro", monthly_price_inr=14999.0, included_minutes=2500, overage_per_minute_inr=7.0,
                monthly_credits=17500.0, max_concurrent_calls=10, is_active=True)
    db.add(plan)
    db.commit()
    subscriptions.activate_period(db, cid, plan)

    retire_plans(db)
    retire_plans(db)
    db.refresh(plan)
    assert plan.is_active is False
    sub = db.get(ClientSubscription, cid)
    assert sub.cancel_at_period_end is True and sub.status == "ACTIVE"  # runs to the end of its period

    sub.current_period_end = subscriptions.utcnow() - timedelta(days=1)
    db.commit()
    assert subscriptions.get_subscription(db, cid).status == "CANCELLED"
