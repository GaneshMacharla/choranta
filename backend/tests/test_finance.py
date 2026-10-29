from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import WalletTransaction
from app.models.numbers import NumberAssignment, ProviderNumber
from app.services import billing
from app.services.call_costing import estimate_call_cost
from app.services.finance import finance_summary, period_range
from test_billing import _completed_call
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def company(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_STATE_CODE", "36", raising=False)
    monkeypatch.setattr(settings, "GST_RATE_PERCENT", 18.0, raising=False)


def _debit(db: Session, client_id: str, amount: float, note: str):
    db.add(WalletTransaction(client_id=client_id, type="DEBIT", amount_inr=-amount, balance_after_inr=0.0, note=note))
    db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_finance_summary_money_in_revenue_cost_and_profit(db: Session, telephony_setup, company):
    client_id = telephony_setup["client"].id
    billing.record_payment(db, client_id, 1180, "UTR1", None)  # Rs 1000 credits + Rs 180 GST
    call = _completed_call(db, telephony_setup)
    charged = -billing.charge_call(db, call).amount_inr
    _completed_call(db, telephony_setup, is_test=True)  # not billed, not costed
    _debit(db, client_id, 499.0, "Rent for +914000000001, 01 Oct - 31 Oct")
    _debit(db, client_id, 100.0, "Number setup fee, +914000000001")

    start, end = period_range("7d")
    data = finance_summary(db, start, end)

    assert data["money_in"] == {"total": 1180.0, "taxable": 1000.0, "gst": 180.0, "adjustments": 0.0}
    assert data["revenue"]["calls"] == pytest.approx(charged, abs=0.01)
    assert data["revenue"]["number_rent"] == 499.0 and data["revenue"]["number_setup"] == 100.0
    assert data["revenue"]["total"] == pytest.approx(charged + 599.0, abs=0.01)

    # Same usage _completed_call records on the session
    cost = estimate_call_cost(call.duration_seconds, {
        "stt_seconds": 30, "tts_seconds": 50, "llm_input_tokens": 4000, "llm_output_tokens": 150})
    assert data["calls"]["count"] == 1
    assert data["cost"]["telephony"] == pytest.approx(cost["breakdown"]["telephony"], abs=0.01)
    assert data["cost"]["total"] == pytest.approx(cost["total"], abs=0.02)
    assert data["profit"] == pytest.approx(data["revenue"]["total"] - data["cost"]["total"], abs=0.01)
    assert data["margin_pct"] == pytest.approx(data["profit"] / data["revenue"]["total"] * 100, abs=0.1)

    [row] = data["clients"]
    assert row["client_id"] == client_id and row["money_in"] == 1180.0
    assert row["revenue"] == data["revenue"]["total"] and row["wallet_balance"] == billing.get_wallet(db, client_id).balance_inr

    assert data["granularity"] == "day" and len(data["trend"]) == 7
    assert sum(b["revenue"] for b in data["trend"]) == pytest.approx(data["revenue"]["total"], abs=0.05)
    assert data["trend"][-1]["money_in"] == 1180.0


def test_finance_number_rent_is_split_by_assignment(db: Session, telephony_setup):
    client_id = telephony_setup["client"].id
    bought = _now() - timedelta(days=20)
    number = ProviderNumber(provider="vobiz", e164="+914000000002", internal_status="ASSIGNED",
                            monthly_cost=300.0, setup_cost=50.0, purchased_at=bought)
    db.add(number)
    db.flush()
    db.add(NumberAssignment(provider_number_id=number.id, client_id=client_id, assigned_at=bought))
    db.commit()

    start, end = period_range("7d")
    data = finance_summary(db, start, end)
    held_days = (_now() - start).total_seconds() / 86400.0
    assert data["cost"]["number_rent"] == pytest.approx(10.0 * held_days, abs=0.05)  # Rs 300/month, no setup (bought earlier)
    assert data["clients"][0]["cost"] == pytest.approx(10.0 * held_days, abs=0.05)

    # Bought inside the period: setup counts towards the total, not the client
    month = finance_summary(db, *period_range("custom", (bought - timedelta(days=1)).date(), date.today()))
    assert month["cost"]["number_rent"] - month["clients"][0]["cost"] == pytest.approx(50.0, abs=0.05)

    # One client's view leaves out other clients' and pool costs
    only = finance_summary(db, start, end, client_id=client_id)
    assert only["cost"]["number_rent"] == pytest.approx(10.0 * held_days, abs=0.05)


def test_finance_period_ranges():
    today = date(2026, 10, 25)
    assert period_range("month", today=today) == (datetime(2026, 10, 1), datetime(2026, 10, 26))
    assert period_range("7d", today=today) == (datetime(2026, 10, 19), datetime(2026, 10, 26))
    assert period_range("custom", date(2026, 1, 1), date(2026, 6, 30)) == (datetime(2026, 1, 1), datetime(2026, 7, 1))
    with pytest.raises(ValueError):
        period_range("custom", date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        period_range("forever")


def test_finance_api_is_admin_only_and_buckets_long_ranges_by_month(client: TestClient, auth_headers, operator_headers):
    res = client.get("/api/finance/summary?period=custom&start=2026-01-01&end=2026-06-30", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["granularity"] == "month" and [b["bucket"] for b in body["trend"]][:2] == ["2026-01", "2026-02"]
    assert len(body["trend"]) == 6

    assert client.get("/api/finance/summary?period=bad", headers=auth_headers).status_code == 422
    assert client.get("/api/finance/summary", headers=operator_headers).status_code == 403
