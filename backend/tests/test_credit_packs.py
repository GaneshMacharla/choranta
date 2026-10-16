"""Suggested credit packs by business size (public landing page and the client portal)."""
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.pricing import CREDIT_PACKS, clear_estimate_cache
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers


def test_public_credit_packs_need_no_login_and_estimate_minutes(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "GST_REGISTERED", False, raising=False)
    clear_estimate_cache()
    data = client.get("/api/public/credit-packs").json()
    rate = data["avg_credits_per_minute"]
    assert [p["credits"] for p in data["packs"]] == [p["credits"] for p in CREDIT_PACKS]
    assert [p["key"] for p in data["packs"] if p["recommended"]] == ["growth"]
    for pack in data["packs"]:
        assert pack["approx_minutes"] == int(pack["credits"] // rate)
        assert pack["approx_calls"] == pack["approx_minutes"] // 2
        assert pack["price_with_gst_inr"] == pack["credits"]


def test_pack_prices_include_gst_when_registered(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "GST_REGISTERED", True, raising=False)
    starter = client.get("/api/public/credit-packs").json()["packs"][0]
    assert starter["price_with_gst_inr"] == round(1000 * (1 + settings.GST_RATE_PERCENT / 100), 2)


def test_portal_subscription_includes_credit_packs(client: TestClient, auth_headers: dict, telephony_setup, company):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"packs-{cid}@clinic.example.com")
    info = client.get("/api/portal/subscription", headers=headers).json()
    assert len(info["credit_packs"]) == len(CREDIT_PACKS)
