"""
End-to-end: a new client pays, asks for an AI employee, Choranta builds it from a template and publishes it,
then it calls a bulk campaign list and an instant website lead.

Everything goes through the real API and the real dialer (place_outbound_call); only the carrier's HTTP API is
replaced, so the test records exactly what Choranta would send to Vobiz. No real calls are made.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes import public_leads
from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.campaign import CampaignRecipient
from app.models.notification import ClientNotification
from app.models.phone_number import PhoneNumber
from app.runtime.providers.registry import default_registry
from app.services import billing, instant_leads, subscriptions
from app.services import campaigns as campaign_svc
from test_campaigns import IN_WINDOW
from test_instant_leads import _SharedSession
from test_portal import _client_headers


class FakeCarrier:
    """Records outbound call requests."""

    def __init__(self):
        self.requests = []

    def __call__(self, provider, customer_number, caller_id, flow_url, status_callback_url=None, custom_field=None, **_):
        self.requests.append({"to": customer_number, "caller_id": caller_id, "flow_url": flow_url,
                              "status_callback": status_callback_url, "custom_field": custom_field})
        return {"Call": {"Sid": generate_unique_id("carrier_sid"), "Status": "in-progress"}}


@pytest.fixture
def live_like(monkeypatch, db: Session):
    """Settings as in a real deployment: billing enforced, simulated payments, Vobiz configured."""
    for name, value in {
        "BILLING_ENFORCED": True, "SIMULATED_PAYMENTS": True, "RAZORPAY_KEY_ID": "", "RAZORPAY_KEY_SECRET": "",
        "TELEPHONY_BASE_URL": "https://choranta.example.com",
        "AGENT_REQUEST_REQUIRES_DOCUMENTS": True,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)
    carrier = FakeCarrier()
    provider = default_registry.get_telephony("vobiz")
    monkeypatch.setattr(type(provider), "initiate_outbound_call", lambda self, **kwargs: carrier(self, **kwargs))
    # Website leads: the API's after-response work runs on the test session, dialling for real
    monkeypatch.setattr(public_leads, "SESSION_FACTORY", lambda: _SharedSession(db))
    monkeypatch.setattr(campaign_svc, "in_calling_window", lambda campaign, now: True)
    instant_leads.rate_limiter = instant_leads.RateLimiter(instant_leads.RATE_LIMIT_PER_MIN)
    instant_leads._key_cache.clear()
    campaign_svc._caller_cache.clear()
    return carrier


def _ok(resp, code=200):
    assert resp.status_code == code, f"{resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text}"
    return resp.json()


def test_onboarding_to_bulk_and_instant_outbound(client: TestClient, auth_headers: dict, db: Session, live_like):
    carrier = live_like

    # ---- 1. Admin creates the client; the client logs in to the portal
    company = _ok(client.post("/api/clients", headers=auth_headers,
                              json={"name": "E2E Smile Dental", "business_type": "OTHER"}), 201)
    assert company["client_code"].startswith("CL-")
    portal = _client_headers(client, auth_headers, company["id"], "owner@e2e-smile.example.com")
    assert _ok(client.get("/api/portal/agent-requests", headers=portal))["can_request"] is False

    # ---- 2. Client buys a plan (simulated payment) and is told to create their first AI employee
    plan = _ok(client.post("/api/plans", headers=auth_headers,
                           json={"name": "E2E Starter", "monthly_price_inr": 2999, "monthly_credits": 3500,
                                 "max_concurrent_calls": 3}), 201)
    info = _ok(client.get("/api/portal/subscription", headers=portal))
    assert info["online_payments"] and info["simulated_payments"]
    order = _ok(client.post("/api/portal/payments/orders", headers=portal,
                            json={"purpose": "SUBSCRIPTION", "plan_id": plan["id"]}), 201)
    paid = _ok(client.post(f"/api/portal/payments/orders/{order['order_id']}/simulate", headers=portal))
    assert paid["status"] == "PAID" and paid["subscription"]["credits_remaining"] == 3500
    assert _ok(client.get("/api/portal/me", headers=portal))["has_ai_employee"] is False
    notes = _ok(client.get("/api/portal/notifications", headers=portal))["items"]
    assert any(n["kind"] == "PLAN_ACTIVE" and n["link"] == "/portal/employees" for n in notes)

    # ---- 3. Client uploads files about the business, then requests an AI employee (company, type, languages, name)
    ask = {"company_name": "Smile Dental Care", "business_type": "CLINIC", "languages": ["te", "en-IN"], "name": "Meera"}
    assert _ok(client.get("/api/portal/agent-requests/options", headers=portal))["needs_documents"] is True
    assert client.post("/api/portal/agent-requests", headers=portal, json=ask).status_code == 422
    _ok(client.post("/api/portal/knowledge/upload", headers=portal,
                    files=[("files", ("services.txt", b"Root canal Rs 4500. Open 9am-8pm, Mon-Sat.", "text/plain"))]), 201)
    assert _ok(client.get("/api/portal/agent-requests/options", headers=portal))["needs_documents"] is False
    request = _ok(client.post("/api/portal/agent-requests", headers=portal, json=ask), 201)
    assert _ok(client.get("/api/portal/me", headers=portal))["has_ai_employee"] is True
    assert _ok(client.get("/api/portal/me", headers=portal))["client_name"] == "Smile Dental Care"

    # ---- 4. Admin builds it from the recommended template, the way the wizard does, and publishes it
    queue = _ok(client.get("/api/agent-requests", headers=auth_headers, params={"status": "OPEN"}))
    assert request["id"] in [r["id"] for r in queue]
    _ok(client.post(f"/api/agent-requests/{request['id']}/start", headers=auth_headers))
    # The clinic template is hidden from the gallery but still loads by id
    template = _ok(client.get("/api/catalogs/agent-templates/clinic_receptionist", headers=auth_headers))
    assert "CLINIC" in template["business_types"]

    config = template["default_config"]
    config["identity"].update(name="Meera", organization="Smile Dental Care")
    config["business_context"]["business_name"] = "Smile Dental Care"
    config["languages"] = {"primary": "te", "supported": ["te", "en-IN"]}
    config["voice"].update(provider="sarvam", voice_id="priya", language="te")
    agent = _ok(client.post("/api/agents", headers=auth_headers, json={
        "client_id": company["id"], "name": "Meera", "role": template["role"], "description": template["description"],
    }), 201)
    _ok(client.put(f"/api/agents/{agent['id']}/configuration", headers=auth_headers, json=config))
    version = _ok(client.post(f"/api/agents/{agent['id']}/versions", headers=auth_headers), 201)
    assert version["status"] == "PUBLISHED"
    done = _ok(client.post(f"/api/agent-requests/{request['id']}/complete", headers=auth_headers,
                           json={"agent_id": agent["id"]}))
    assert done["status"] == "COMPLETED"
    kinds = {n["kind"] for n in _ok(client.get("/api/portal/notifications", headers=portal))["items"]}
    assert {"EMPLOYEE_SETUP", "EMPLOYEE_READY"} <= kinds

    # ---- 5. The client's own number (bought from Choranta; created directly since buying talks to Vobiz)
    number = PhoneNumber(id=generate_unique_id("phn_"), client_id=company["id"], phone_number="+914071234567",
                         provider="vobiz", provider_number_id="EXO_E2E", status="ACTIVE")
    db.add(number)
    db.commit()
    _ok(client.patch(f"/api/portal/numbers/{number.id}", headers=portal, json={"agent_id": agent["id"]}))

    # ---- 6. Bulk campaign from the portal: CSV -> launch -> dialer places real (faked-carrier) calls
    settings_body = {"agent_id": agent["id"], "agent_version_id": version["id"], "caller_number_ids": [number.id],
                     "max_concurrent": 2, "retry_max": 0, "retry_intervals_min": []}
    bulk = _ok(client.post("/api/portal/campaigns", headers=portal, json={**settings_body, "name": "Recall list"}), 201)
    imported = _ok(client.post(f"/api/portal/campaigns/{bulk['id']}/recipients/csv", headers=portal,
                               json={"csv_text": "Name,Phone,Treatment\nAsha,9876500011,Cleaning\nRavi,09876500012,Braces\n"}))
    assert imported["added"] == 2
    assert client.post(f"/api/portal/campaigns/{bulk['id']}/launch", headers=portal, json={"consent": False}).status_code == 400
    assert _ok(client.post(f"/api/portal/campaigns/{bulk['id']}/launch", headers=portal, json={"consent": True}))["status"] in ("RUNNING", "SCHEDULED")

    placed = campaign_svc.run_campaign_tick(db, IN_WINDOW)
    assert placed == 2, carrier.requests
    assert sorted(r["to"] for r in carrier.requests) == ["+919876500011", "+919876500012"]
    for r in carrier.requests:
        assert r["caller_id"] == "+914071234567"  # the client's own number
        assert r["flow_url"].startswith("https://choranta.example.com/api/telephony/vobiz/answer")
        assert r["status_callback"].startswith("https://choranta.example.com/api/telephony/vobiz/hangup")
    calls = db.query(Call).filter(Call.client_id == company["id"]).all()
    assert len(calls) == 2 and all(c.status == "INITIATED" and c.agent_id == agent["id"] for c in calls)
    asha = next(c for c in calls if c.destination_number == "+919876500011")
    assert asha.metadata_["variables"].get("treatment") == "Cleaning"

    # A call ends: it is charged real cost + profit from plan credits, right away
    asha.status, asha.duration_seconds = "COMPLETED", 95.0
    db.commit()
    expected = billing.call_charge(db, asha)
    billing.charge_call(db, asha)
    sub = subscriptions.get_subscription(db, company["id"])
    assert expected > 0 and sub.credits_used == pytest.approx(expected)
    assert billing.get_wallet(db, company["id"]).balance_inr == 0  # bought credits untouched

    # ---- 7. Instant outbound: website-lead campaign + API key -> a form submission is dialled immediately
    trigger = _ok(client.post("/api/portal/campaigns", headers=portal, json={
        **settings_body, "name": "Website enquiries", "kind": "TRIGGER", "retry_max": 1, "retry_intervals_min": [5],
    }), 201)
    _ok(client.post(f"/api/portal/campaigns/{trigger['id']}/launch", headers=portal, json={"consent": True}))
    key = _ok(client.post("/api/portal/api-keys", headers=portal, json={"name": "Website"}), 201)
    raw_key = key.get("key") or key.get("api_key") or key.get("raw_key")
    assert raw_key, key

    before = len(carrier.requests)
    lead = client.post("/api/public/leads", headers={"X-API-Key": raw_key}, json={
        "phone": "98765 00099", "name": "Kiran", "consent": True, "source": "website-form", "treatment": "Implants",
    })
    assert lead.status_code in (200, 201, 202), lead.text
    assert len(carrier.requests) == before + 1, "website lead was not dialled straight away"
    assert carrier.requests[-1]["to"] == "+919876500099" and carrier.requests[-1]["caller_id"] == "+914071234567"
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == trigger["id"]).one()
    assert recipient.phone == "+919876500099" and recipient.attempts == 1

    # Same person again within 24 h is not called twice
    again = client.post("/api/public/leads", headers={"X-API-Key": raw_key}, json={
        "phone": "+91 98765 00099", "name": "Kiran", "consent": True,
    })
    assert again.status_code in (200, 201, 202) and len(carrier.requests) == before + 1

    # Everything the client got told along the way
    told = {n.kind for n in db.query(ClientNotification).filter(ClientNotification.client_id == company["id"]).all()}
    assert {"PLAN_ACTIVE", "EMPLOYEE_SETUP", "EMPLOYEE_READY"} <= told
