"""Exotel's real per-call price vs Choranta's phone-line estimate."""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.call import Call
from app.services import carrier_costs, subscriptions
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def rates(monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_RATE_PER_MINUTE_INR", 1.0, raising=False)
    monkeypatch.setattr(settings, "TELEPHONY_BILLING_PULSE_SECONDS", 60, raising=False)
    monkeypatch.setattr(settings, "GST_REGISTERED", False, raising=False)
    monkeypatch.setattr(settings, "GST_RATE_PERCENT", 18.0, raising=False)
    monkeypatch.setattr(settings, "EXOTEL_PRICE_INCLUDES_GST", False, raising=False)
    monkeypatch.setattr(settings, "CARRIER_COST_ALERT_PERCENT", 5.0, raising=False)


def _ended_call(db: Session, setup, minutes_ago: float, duration: float = 90.0, **metadata) -> Call:
    call = Call(id=generate_unique_id("call_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
                agent_version_id=setup["version"].id, caller_number="+914045209348",
                destination_number="+918008538015", direction="OUTBOUND", status="COMPLETED", provider="exotel",
                provider_call_id=generate_unique_id("exo_"), duration_seconds=duration,
                ended_at=subscriptions.utcnow() - timedelta(minutes=minutes_ago), metadata_=metadata)
    db.add(call)
    db.commit()
    return call


def test_prices_are_fetched_once_exotel_has_them(db: Session, telephony_setup, rates):
    fresh = _ended_call(db, telephony_setup, minutes_ago=1)       # too soon: Exotel may not have priced it
    ready = _ended_call(db, telephony_setup, minutes_ago=5)
    pending = _ended_call(db, telephony_setup, minutes_ago=5)     # Exotel hasn't priced it yet
    prices = {ready.provider_call_id: {"price": 2.0, "duration": 92.0}}

    assert carrier_costs.record_carrier_prices(db, fetch=prices.get) == 1
    for call in (fresh, ready, pending):
        db.refresh(call)
    assert "carrier_price_inr" not in fresh.metadata_
    assert ready.metadata_["carrier_price_inr"] == 2.0 and ready.metadata_["carrier_duration_s"] == 92.0
    assert pending.metadata_["carrier_price_checks"] == 1

    # A call Exotel never prices is given up after a few checks; priced calls aren't fetched again
    for _ in range(carrier_costs.MAX_PRICE_CHECKS + 2):
        carrier_costs.record_carrier_prices(db, fetch=prices.get)
    db.refresh(pending)
    assert pending.metadata_["carrier_price_checks"] == carrier_costs.MAX_PRICE_CHECKS


def test_report_flags_a_rate_below_what_exotel_charges(db: Session, telephony_setup, rates):
    # Two 90-second calls: Choranta estimates 2 billed minutes x Rs 1 = Rs 2 each
    _ended_call(db, telephony_setup, 10, carrier_price_inr=2.0, carrier_duration_s=90.0)
    _ended_call(db, telephony_setup, 10, carrier_price_inr=2.0, carrier_duration_s=90.0)
    report = carrier_costs.carrier_cost_report(db)
    # Exotel's Rs 2 + 18% GST = Rs 2.36: 18% more than estimated
    assert report["calls_priced"] == 2 and report["estimated_total_inr"] == 4.0 and report["actual_total_inr"] == 4.72
    assert report["gap_percent"] == 18.0 and report["rate_too_low"] is True
    assert report["matching_rate_per_minute_inr"] == 1.18


def test_report_is_quiet_when_the_rate_matches(db: Session, telephony_setup, rates, monkeypatch):
    monkeypatch.setattr(settings, "TELEPHONY_RATE_PER_MINUTE_INR", 1.18, raising=False)
    _ended_call(db, telephony_setup, 10, carrier_price_inr=2.0, carrier_duration_s=90.0)
    _ended_call(db, telephony_setup, 10)  # not priced yet: left out
    report = carrier_costs.carrier_cost_report(db)
    assert report["calls_priced"] == 1 and report["gap_percent"] == 0.0 and report["rate_too_low"] is False


def test_exotel_price_is_read_from_call_details(monkeypatch):
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "acct", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_API_KEY", "key", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_API_TOKEN", "token", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_SUBDOMAIN", "api.exotel.com", raising=False)
    seen = {}

    def fake_get(url, auth, timeout):
        seen["url"] = url
        body = {"Call": {"Sid": "CA1", "Price": "1.500", "Duration": "75"}} if "CA1" in url else {"Call": {"Price": None}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(carrier_costs.httpx, "get", fake_get)
    assert carrier_costs.fetch_exotel_price("CA1") == {"price": 1.5, "duration": 75.0}
    assert seen["url"] == "https://api.exotel.com/v1/Accounts/acct/Calls/CA1.json"
    assert carrier_costs.fetch_exotel_price("CA2") is None


def test_carrier_check_endpoint_is_admin_only(client, auth_headers, operator_headers, telephony_setup, rates):
    assert client.get("/api/pricing/carrier-check", headers=operator_headers).status_code == 403
    report = client.get("/api/pricing/carrier-check?days=7", headers=auth_headers).json()
    assert report["days"] == 7 and report["calls_priced"] == 0 and report["rate_too_low"] is False
