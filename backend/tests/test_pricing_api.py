import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.pricing_settings import PricingSettings
from app.models.runtime_session import RuntimeSession
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture(autouse=True)
def clean_pricing(db: Session):
    db.query(PricingSettings).delete()
    db.commit()
    yield
    db.query(PricingSettings).delete()
    db.commit()


def _completed_call(db: Session, telephony_setup, duration: float = 120) -> Call:
    session = RuntimeSession(
        id=generate_unique_id("ses_"),
        client_id=telephony_setup["client"].id,
        agent_id=telephony_setup["agent"].id,
        agent_version_id=telephony_setup["version"].id,
        status="COMPLETED",
        metadata_={},
        usage_json={"stt_seconds": 30, "tts_seconds": 50, "llm_input_tokens": 5000, "llm_output_tokens": 200},
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
        duration_seconds=duration,
        provider="vobiz",
        provider_call_id=generate_unique_id("exo_"),
    )
    db.add(call)
    db.commit()
    return call


def test_defaults_until_admin_sets_pricing(client: TestClient, auth_headers: dict):
    data = client.get("/api/pricing", headers=auth_headers).json()
    assert data["profit_percent"] == settings.DEFAULT_PROFIT_PERCENT
    assert "infra_cost_per_minute_inr" not in data
    assert data["updated_at"] is None


def test_admin_updates_pricing_and_preview_uses_it(client: TestClient, auth_headers: dict, telephony_setup, db: Session):
    _completed_call(db, telephony_setup)
    resp = client.put("/api/pricing", headers=auth_headers, json={"profit_percent": 50})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["profit_percent"] == 50
    preview = data["preview"]
    assert preview["calls"] >= 1
    assert preview["avg_charge_per_minute"] == pytest.approx(preview["avg_cost_per_minute"] * 1.5, rel=1e-3)
    assert client.get("/api/pricing", headers=auth_headers).json()["profit_percent"] == 50


def test_profit_percent_is_required(client: TestClient, auth_headers: dict):
    assert client.put("/api/pricing", headers=auth_headers, json={}).status_code == 422


@pytest.mark.parametrize("body", [
    {"profit_percent": -5},
    {"profit_percent": 1500},
])
def test_invalid_pricing_is_rejected(client: TestClient, auth_headers: dict, body):
    assert client.put("/api/pricing", headers=auth_headers, json=body).status_code == 422


def test_operators_cannot_view_or_change_pricing(client: TestClient, operator_headers: dict):
    assert client.get("/api/pricing", headers=operator_headers).status_code == 403
    resp = client.put("/api/pricing", headers=operator_headers, json={"profit_percent": 90})
    assert resp.status_code == 403


def test_admin_sees_cost_and_margin_operator_sees_only_charge(
    client: TestClient, auth_headers: dict, operator_headers: dict, telephony_setup, db: Session
):
    call = _completed_call(db, telephony_setup)
    client.put("/api/pricing", headers=auth_headers, json={"profit_percent": 40})

    admin_cost = client.get(f"/api/telephony/calls/{call.id}", headers=auth_headers).json()["cost"]
    assert admin_cost["profit_percent"] == 40
    assert "infra" not in admin_cost["breakdown"]
    assert admin_cost["charge_total"] == pytest.approx(admin_cost["total"] * 1.4, abs=1e-3)

    operator_cost = client.get(f"/api/telephony/calls/{call.id}", headers=operator_headers).json()["cost"]
    assert set(operator_cost) == {"currency", "estimated", "duration_seconds", "billed_minutes", "charge_total", "charge_per_minute"}
    assert operator_cost["charge_total"] == admin_cost["charge_total"]

    listed = [c for c in client.get("/api/telephony/calls", headers=operator_headers).json() if c["id"] == call.id]
    assert "breakdown" not in listed[0]["cost"]
