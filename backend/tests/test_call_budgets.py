"""Call credit budgets: the wallet never goes below zero, whatever calls run at once."""
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.core.security import generate_unique_id
from app.models.billing import WalletTransaction
from app.models.call import Call
from app.runtime.telephony.session import TelephonyMediaSession
from app.runtime.providers.registry import default_registry
from app.services import billing, phone_numbers, pricing
from app.services.call_status import apply_call_status
from app.services.outbound_calls import OutboundCallError, place_outbound_call
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def budgets(monkeypatch):
    monkeypatch.setattr(settings, "PAYG_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True, raising=False)
    monkeypatch.setattr(settings, "CALL_MAX_DURATION_S", 600, raising=False)
    monkeypatch.setattr(settings, "CALL_MIN_BUDGET_MINUTES", 2.0, raising=False)
    monkeypatch.setattr(billing, "budget_credits_per_minute", lambda db: 7.0)  # 70 credits per 10-minute call


def _call(db: Session, setup, status: str = "ACTIVE", **metadata) -> Call:
    call = Call(id=generate_unique_id("call_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
                agent_version_id=setup["version"].id, caller_number="+914045209348",
                destination_number="+918008538015", direction="OUTBOUND", status=status, provider="vobiz",
                provider_call_id=generate_unique_id("exo_"), metadata_=metadata)
    db.add(call)
    db.commit()
    return call


def _fund(db: Session, client_id: str, amount: float) -> None:
    billing.get_wallet(db, client_id).balance_inr = amount
    db.commit()


def test_budget_rate_uses_the_average_only_when_enough_calls_back_it(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_CREDITS_PER_MINUTE", 7.0, raising=False)
    monkeypatch.setattr(settings, "BUDGET_MIN_CALLS_FOR_AVERAGE", 20, raising=False)
    cases = [(1, 3.42, 7.0), (19, 12.0, 7.0), (25, 3.42, 7.0), (25, 9.5, 9.5), (0, None, 7.0)]
    for calls, average, expected in cases:
        monkeypatch.setattr(pricing, "recent_charge_per_minute",
                            lambda db, calls=calls, average=average: {"calls": calls, "avg_charge_per_minute": average})
        pricing.clear_estimate_cache()
        assert pricing.budget_credits_per_minute(db) == expected
    pricing.clear_estimate_cache()


def test_live_calls_reserve_their_budgets_so_credits_are_never_spent_twice(db: Session, telephony_setup, budgets):
    cid = telephony_setup["client"].id
    _fund(db, cid, 250.0)  # covers 3 calls at a time

    allowed, _, _, first = billing.call_budget(db, cid, 1800, lock=True)
    assert allowed and first == 210.0  # a full 30-minute call
    _call(db, telephony_setup, credit_budget=first)

    allowed, _, _, second = billing.call_budget(db, cid, lock=True)
    assert allowed and second == 40.0  # only what the first call left
    _call(db, telephony_setup, credit_budget=second)

    allowed, reason, code, budget = billing.call_budget(db, cid)
    assert not allowed and code == "CONCURRENCY" and "reserved" in reason and budget is None
    assert billing.held_credits(db, cid) == (2, 250.0)

    # Lines follow the balance too: 100 credits cover one call at a time
    _fund(db, cid, 100.0)
    db.query(Call).filter(Call.client_id == cid).delete()
    db.commit()
    assert billing.call_budget(db, cid)[3] == 70.0
    _call(db, telephony_setup, credit_budget=70.0)
    assert billing.check_call_allowed(db, cid)[2] == "CONCURRENCY"


def test_a_balance_below_a_short_call_starts_nothing(db: Session, telephony_setup, budgets):
    cid = telephony_setup["client"].id
    _fund(db, cid, 13.99)  # 2 minutes x 7 = 14 needed
    assert billing.check_call_allowed(db, cid)[2] == "NO_BALANCE"
    _fund(db, cid, 14.0)
    assert billing.call_budget(db, cid)[3] == 14.0


def test_budgets_cover_the_agents_own_maximum_call_length(db: Session, telephony_setup, budgets):
    version = telephony_setup["version"]
    config = dict(version.configuration_json)
    config["conversation"] = {**config["conversation"], "limits": {"max_call_duration_s": 1800}}
    version.configuration_json = config
    db.commit()
    assert billing.agent_max_call_seconds(db, version.id) == 1800
    _fund(db, telephony_setup["client"].id, 1000.0)
    assert billing.call_budget(db, telephony_setup["client"].id, 1800)[3] == 210.0  # 30 minutes x 7


def test_charging_never_takes_the_wallet_below_zero(db: Session, telephony_setup, budgets):
    cid = telephony_setup["client"].id
    _fund(db, cid, 5.0)
    call = _call(db, telephony_setup, status="COMPLETED")
    call.duration_seconds = 600.0  # costs more than the 5 credits left
    db.commit()

    billing.charge_call(db, call)
    assert billing.get_wallet(db, cid).balance_inr == 0.0
    db.refresh(call)
    assert call.metadata_["unpaid_credits"] > 0

    billing.charge_call(db, call)  # a second attempt charges nothing
    assert db.query(WalletTransaction).filter(WalletTransaction.call_id == call.id).count() == 1


def test_the_sweep_charges_calls_that_ended_without_being_billed(db: Session, telephony_setup, budgets):
    cid = telephony_setup["client"].id
    _fund(db, cid, 500.0)
    orphaned = _call(db, telephony_setup)  # e.g. the server restarted mid-call
    apply_call_status(db, orphaned, "completed", 120)  # only the carrier's status arrives
    test_call = _call(db, telephony_setup, is_test=True)
    apply_call_status(db, test_call, "completed", 120)
    ended = orphaned.ended_at.replace(tzinfo=None)

    # Within the grace period the session may still be charging it
    assert billing.charge_unbilled_calls(db, now=ended + timedelta(seconds=30)) == 0
    assert billing.charge_unbilled_calls(db, now=ended + timedelta(minutes=3)) == 1
    assert db.query(WalletTransaction).filter(WalletTransaction.call_id == orphaned.id).count() == 1
    assert billing.charge_unbilled_calls(db, now=ended + timedelta(minutes=4)) == 0  # never twice
    assert db.query(WalletTransaction).filter(WalletTransaction.call_id == test_call.id).count() == 0


def test_a_failed_dial_releases_its_budget(db: Session, telephony_setup, budgets, monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_BASE_URL", "https://choranta.example.com", raising=False)
    cid = telephony_setup["client"].id
    _fund(db, cid, 100.0)

    def carrier_down(self, **kwargs):
        raise RuntimeError("carrier down")

    provider = default_registry.get_telephony("vobiz")
    monkeypatch.setattr(type(provider), "initiate_outbound_call", carrier_down)
    with pytest.raises(OutboundCallError):
        place_outbound_call(db, destination_number="+918008538015", phone_number_id=telephony_setup["phone_number"].id)
    failed = db.query(Call).filter(Call.client_id == cid).one()
    assert failed.status == "FAILED" and failed.metadata_["credit_budget"] == 70.0
    assert billing.held_credits(db, cid) == (0, 0.0)


def test_number_test_calls_are_only_for_new_numbers_and_limited(db: Session, telephony_setup, budgets):
    pn = telephony_setup["phone_number"]
    with pytest.raises(ValidationException, match="already active"):
        phone_numbers.start_test_call(db, pn, "+918008538015")

    pn.status = "READY_TO_TEST"
    pn.metadata_ = {"test_attempts": settings.NUMBER_TEST_MAX_ATTEMPTS}
    db.commit()
    with pytest.raises(ValidationException, match="used all its test calls"):
        phone_numbers.start_test_call(db, pn, "+918008538015")


def _guarded_session(db: Session, budget: float, elapsed_s: float, tts_characters: int = 0) -> TelephonyMediaSession:
    usage = {"tts_characters": tts_characters, "tts_provider": "sarvam", "stt_provider": "sarvam", "llm_provider": "sarvam"}
    guarded = TelephonyMediaSession.__new__(TelephonyMediaSession)
    guarded.db = db
    guarded.call_record = SimpleNamespace(metadata_={"credit_budget": budget})
    guarded.context = SimpleNamespace(usage_tracker=SimpleNamespace(get_summary=lambda: usage))
    guarded.t_call_start = time.perf_counter() - elapsed_s
    guarded._budget_pricing = SimpleNamespace(profit_percent=0.0)
    return guarded


def test_the_session_wraps_up_before_a_call_overspends_its_budget(db: Session, monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_RATE_PER_MINUTE_INR", 1.0, raising=False)
    monkeypatch.setattr(settings, "TELEPHONY_BILLING_PULSE_SECONDS", 60, raising=False)
    # Budget of 5 credits at Rs 1 a carrier minute
    assert _guarded_session(db, 5.0, 30)._budget_state() is None
    assert _guarded_session(db, 5.0, 225)._budget_state() == "near"  # minute 4 ends soon; leave time for goodbye
    assert _guarded_session(db, 5.0, 241)._budget_state() == "over"  # 5 minutes billed
    # Speech-heavy calls count too: 10,000 characters of Bulbul speech is Rs 30
    assert _guarded_session(db, 20.0, 30, tts_characters=10_000)._budget_state() == "over"
    # Calls without a budget (tests, billing off) are never limited
    unlimited = _guarded_session(db, 5.0, 3000)
    unlimited.call_record.metadata_ = {}
    assert unlimited._budget_state() is None
