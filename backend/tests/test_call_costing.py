import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.services.call_costing import estimate_call_cost
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def rates(monkeypatch):
    for key, value in {
        "TELEPHONY_RATE_PER_MINUTE_INR": 1.0,
        "TELEPHONY_BILLING_PULSE_SECONDS": 60,
        "STT_USD_PER_MINUTE": 0.01,
        "TTS_USD_PER_MINUTE": 0.05,
        "LLM_INPUT_USD_PER_MILLION_TOKENS": 1.0,
        "LLM_OUTPUT_USD_PER_MILLION_TOKENS": 2.0,
        "USD_TO_INR": 100.0,
        "DEFAULT_PROFIT_PERCENT": 0.0,
    }.items():
        monkeypatch.setattr(settings, key, value, raising=False)


def test_cost_breakdown_and_per_minute(rates):
    cost = estimate_call_cost(120, {
        "stt_seconds": 60, "tts_seconds": 30, "llm_input_tokens": 1_000_000, "llm_output_tokens": 500_000,
    })
    assert cost["currency"] == "INR"
    assert cost["breakdown"] == {"telephony": 2.0, "speech_to_text": 1.0, "text_to_speech": 2.5, "llm": 200.0}
    assert cost["total"] == 205.5
    assert cost["per_minute"] == 102.75


def test_telephony_bills_whole_pulses(rates):
    cost = estimate_call_cost(61, {})
    assert cost["billed_minutes"] == 2.0
    assert cost["breakdown"]["telephony"] == 2.0
    assert estimate_call_cost(0, {})["per_minute"] is None


def test_completed_call_includes_cost(client: TestClient, auth_headers: dict, telephony_setup, db: Session, rates):
    session = RuntimeSession(
        id=generate_unique_id("ses_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        status="COMPLETED",
        metadata_={},
        usage_json={"stt_seconds": 30, "tts_seconds": 60, "llm_input_tokens": 0, "llm_output_tokens": 0},
    )
    db.add(session)
    call = Call(
        id=generate_unique_id("call_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        runtime_session_id=session.id,
        caller_number="+918008538015",
        destination_number="+914045209348",
        direction="OUTBOUND",
        status="COMPLETED",
        duration_seconds=90,
        provider="exotel",
        provider_call_id=generate_unique_id("exo_"),
    )
    db.add(call)
    db.commit()

    detail = client.get(f"/api/telephony/calls/{call.id}", headers=auth_headers).json()
    assert detail["cost"]["breakdown"] == {"telephony": 2.0, "speech_to_text": 0.5, "text_to_speech": 5.0, "llm": 0.0}
    assert detail["cost"]["per_minute"] == 5.0

    listed = [c for c in client.get("/api/telephony/calls", headers=auth_headers).json() if c["id"] == call.id]
    assert listed[0]["cost"]["total"] == 7.5


def test_client_charge_is_real_cost_plus_profit(rates):
    from app.services.pricing import PricingSnapshot
    # 2 min call: telephony Rs2 cost (no infra); +40% profit = Rs2.80 charge (= 2.80 credits)
    cost = estimate_call_cost(120, {}, PricingSnapshot(profit_percent=40.0))
    assert "infra" not in cost["breakdown"]
    assert cost["total"] == 2.0
    assert cost["profit_percent"] == 40.0
    assert cost["profit"] == 0.8
    assert cost["charge_total"] == 2.8
    assert cost["charge_per_minute"] == 1.4
    assert estimate_call_cost(0, {})["charge_per_minute"] is None
    assert estimate_call_cost(0, {})["charge_per_minute"] is None
