import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes import public_leads
from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.campaign import CampaignRecipient, WebhookDelivery
from app.models.client import Client
from app.models.lead import Lead
from app.models.subscription import Plan
from app.services import campaigns as svc
from app.services import instant_leads, subscriptions
from app.services.outbound_calls import OutboundCallError
from test_campaigns import IN_WINDOW, OUT_OF_WINDOW, FakeDialer, _campaign, _end, _running
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers


class _SharedSession:
    """Lets post-response work use the test's session (and not close it)."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setattr(instant_leads, "rate_limiter", instant_leads.RateLimiter(instant_leads.RATE_LIMIT_PER_MIN))
    instant_leads._key_cache.clear()
    svc._caller_cache.clear()


def _trigger(db: Session, setup, **overrides):
    campaign = _campaign(db, setup, kind="TRIGGER", name="Website leads", retry_max=2, retry_intervals_min=[5, 30],
                         max_concurrent=1, **overrides)
    return svc.launch(db, campaign, "usr_test", consent=True)


def _key(db: Session, setup):
    key, raw = instant_leads.create_api_key(db, setup["client"].id, "Website", None)
    return instant_leads.KeyContext(key.id, key.client_id), raw, key


LEAD = {"phone": "98765 00101", "name": "Priya", "consent": True, "source": "contact-form", "course_enquired": "NEET"}


@pytest.fixture
def api(client: TestClient, db: Session, telephony_setup, monkeypatch):
    """Public API with post-response work running on the test session and a fake dialer."""
    dialer = FakeDialer(db, telephony_setup)
    monkeypatch.setattr(public_leads, "SESSION_FACTORY", lambda: _SharedSession(db))
    monkeypatch.setattr(public_leads, "DIAL", dialer)
    monkeypatch.setattr(svc, "in_calling_window", lambda campaign, now: True)
    campaign = _trigger(db, telephony_setup)
    ctx, raw, key = _key(db, telephony_setup)
    return {"client": client, "dialer": dialer, "campaign": campaign, "raw": raw, "key": key}


def _post(api, body=None, key="default"):
    headers = {} if key is None else {"X-API-Key": api["raw"] if key == "default" else key}
    return api["client"].post("/api/public/leads", json=body if body is not None else LEAD, headers=headers)


def test_key_auth(api, db: Session):
    assert _post(api, key=None).status_code == 401
    assert _post(api, key="chr_live_not_a_real_key").status_code == 401
    instant_leads.revoke_api_key(db, api["key"])
    response = _post(api)
    assert response.status_code == 401 and "revoked" in response.json()["error"]


def test_consent_and_phone_required(api):
    assert _post(api, {**LEAD, "consent": False}).status_code == 400
    assert _post(api, {k: v for k, v in LEAD.items() if k != "consent"}).status_code == 400
    assert _post(api, {**LEAD, "phone": "12345"}).status_code == 400


def test_lead_is_dialled_immediately_and_recorded(api, db: Session, telephony_setup):
    response = _post(api)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "accepted" and response.json()["calling"] == "now"
    assert [d[0] for d in api["dialer"].dialed] == ["+919876500101"]
    assert api["dialer"].dialed[0][2] == {"course_enquired": "NEET", "user_name": "Priya"}

    recipient = db.get(CampaignRecipient, response.json()["lead_id"])
    assert recipient.status == "DIALING" and recipient.attempts == 1 and recipient.last_call_id
    assert recipient.source == "contact-form"
    lead = db.get(Lead, recipient.lead_id)
    assert lead.phone == "+919876500101" and lead.consent_given is True and lead.consent_source == "contact-form"
    assert lead.consent_at is not None
    assert api["key"].last_used_at is not None or db.get(type(api["key"]), api["key"].id).last_used_at is not None


def test_duplicates_within_24_hours_are_ignored(api):
    first = _post(api).json()
    second = _post(api, {**LEAD, "phone": "+919876500101"}).json()
    assert second["status"] == "duplicate" and second["lead_id"] == first["lead_id"]
    assert len(api["dialer"].dialed) == 1


def test_same_person_after_24_hours_is_called_again(db: Session, telephony_setup):
    campaign = _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    first = instant_leads.accept_lead(db, ctx, LEAD, now=IN_WINDOW)
    recipient = db.get(CampaignRecipient, first["recipient_id"])
    recipient.status = "COMPLETED"
    db.commit()
    again = instant_leads.accept_lead(db, ctx, LEAD, now=IN_WINDOW + timedelta(hours=25))
    assert again["status"] == "accepted" and again["recipient_id"] == first["recipient_id"]
    assert db.get(CampaignRecipient, first["recipient_id"]).status == "DIALING"


def test_rate_limit_per_key(api, monkeypatch):
    monkeypatch.setattr(instant_leads, "rate_limiter", instant_leads.RateLimiter(2))
    assert _post(api, {**LEAD, "phone": "9876500201"}).status_code == 202
    assert _post(api, {**LEAD, "phone": "9876500202"}).status_code == 202
    assert _post(api, {**LEAD, "phone": "9876500203"}).status_code == 429


def test_night_submission_waits_for_the_window(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    accepted = instant_leads.accept_lead(db, ctx, LEAD, now=OUT_OF_WINDOW)
    assert accepted["dial_now"] is False
    instant_leads.process_lead(db, ctx, accepted, dial=dialer)
    assert dialer.dialed == []
    assert db.get(CampaignRecipient, accepted["recipient_id"]).status == "PENDING"

    assert svc.run_campaign_tick(db, OUT_OF_WINDOW, dial=dialer) == 0
    next_morning = IN_WINDOW + timedelta(days=1)  # Wednesday 11:00 IST
    assert svc.run_campaign_tick(db, next_morning, dial=dialer) == 1
    assert dialer.dialed[0][0] == "+919876500101"


def test_busy_lines_leave_the_lead_for_the_next_tick(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    accepted = instant_leads.accept_lead(db, ctx, LEAD, now=IN_WINDOW)
    dialer.error = OutboundCallError("CONCURRENCY", "Lines busy", 429)
    assert instant_leads.instant_dial(db, accepted["recipient_id"], now=IN_WINDOW, dial=dialer) == "stop"
    recipient = db.get(CampaignRecipient, accepted["recipient_id"])
    assert recipient.status == "PENDING" and recipient.attempts == 0

    dialer.error = None
    assert svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=dialer) == 1


def test_no_double_dial_between_instant_path_and_tick(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    accepted = instant_leads.accept_lead(db, ctx, LEAD, now=IN_WINDOW)

    # The dialer runs before the instant dial: the lead is already claimed, so it is left alone
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 0
    assert instant_leads.instant_dial(db, accepted["recipient_id"], now=IN_WINDOW, dial=dialer) == "placed"
    # A second instant dial and later ticks don't dial it again
    assert instant_leads.instant_dial(db, accepted["recipient_id"], now=IN_WINDOW, dial=dialer) == "skipped"
    assert svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=dialer) == 0
    assert len(dialer.dialed) == 1


def test_claimed_lead_is_released_if_the_instant_dial_never_happens(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    instant_leads.accept_lead(db, ctx, LEAD, now=IN_WINDOW)
    # (process stopped before dialling) three minutes later the dialer recovers it
    later = IN_WINDOW + timedelta(minutes=3)
    assert svc.run_campaign_tick(db, IN_WINDOW + timedelta(minutes=1), dial=dialer) == 0  # still claimed
    assert svc.run_campaign_tick(db, later, dial=dialer) == 1  # released and dialled in the same pass
    assert len(dialer.dialed) == 1


def test_instant_leads_have_priority_over_bulk(db: Session, telephony_setup):
    plan = Plan(name="Growth", monthly_price_inr=5000.0, included_minutes=1000, overage_per_minute_inr=4.0,
                max_concurrent_calls=3, is_active=True)
    db.add(plan)
    db.commit()
    subscriptions.activate_period(db, telephony_setup["client"].id, plan)

    dialer = FakeDialer(db, telephony_setup)
    bulk = _running(db, telephony_setup, csv_text="phone\n9876500301\n9876500302\n9876500303\n", max_concurrent=2)
    _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    instant_leads.accept_lead(db, ctx, LEAD, now=OUT_OF_WINDOW)  # queued (not dialled yet)

    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    phones = [d[0] for d in dialer.dialed]
    assert phones[0] == "+919876500101"  # the website lead goes first
    # 3 lines on the plan: 1 lead call + 1 bulk call, and one line kept free for the next lead
    assert len(phones) == 2
    assert sum(1 for r in db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == bulk.id) if r.status == "DIALING") == 1


def test_webhook_payload_signature_and_retries(db: Session, telephony_setup, monkeypatch):
    sent = []

    def fake_post(url, body, headers):
        sent.append((url, body, headers))
        return 200 if len(sent) > 1 else 500

    monkeypatch.setattr(svc, "post_webhook", fake_post)
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="name,phone,course\nPriya,9876500401,NEET\n",
                        webhook_url="https://crm.example.com/hooks/choranta")
    assert campaign.webhook_secret.startswith("whsec_")
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    (recipient,) = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).all()
    call = db.get(Call, recipient.last_call_id)
    call.metadata_ = {**(call.metadata_ or {}), "outputs": {"target_exam": "NEET"}, "summary": "Booked a demo."}
    db.commit()
    _end(db, recipient, "COMPLETED", duration=75)

    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=dialer)  # first delivery fails (500)
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.campaign_id == campaign.id).one()
    assert delivery.status == "PENDING" and delivery.attempts == 1
    assert delivery.next_attempt_at == IN_WINDOW + timedelta(seconds=5) + timedelta(minutes=1)

    svc.run_campaign_tick(db, IN_WINDOW + timedelta(minutes=2), dial=dialer)  # retried and accepted
    db.refresh(delivery)
    assert delivery.status == "SENT" and delivery.attempts == 2

    url, body, headers = sent[-1]
    assert url == "https://crm.example.com/hooks/choranta"
    expected = svc.sign_webhook(campaign.webhook_secret, headers["X-Choranta-Timestamp"], body)
    assert headers["X-Choranta-Signature"] == f"sha256={expected}"
    payload = json.loads(body)
    assert payload["event"] == "recipient.finished"
    assert payload["recipient"]["phone"] == "+919876500401" and payload["recipient"]["outcome"] == "answered"
    assert payload["recipient"]["attempts"] == 1 and payload["call"]["duration_seconds"] == 75.0
    assert payload["outputs"] == {"target_exam": "NEET"} and payload["summary"] == "Booked a demo."


def test_webhook_gives_up_after_retries(db: Session, telephony_setup, monkeypatch):
    def down(url, body, headers):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(svc, "post_webhook", down)
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500501\n", retry_max=0,
                        webhook_url="https://crm.example.com/hook")
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    (recipient,) = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).all()
    _end(db, recipient, "FAILED", "busy", 0)
    now = IN_WINDOW
    for _ in range(len(svc.WEBHOOK_RETRY_MIN) + 1):
        now += timedelta(hours=2)
        svc.run_campaign_tick(db, now, dial=dialer)
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.campaign_id == campaign.id).one()
    assert delivery.status == "FAILED" and delivery.attempts == len(svc.WEBHOOK_RETRY_MIN) + 1
    assert json.loads(json.dumps(delivery.payload))["recipient"]["outcome"] == "busy"


def test_trigger_campaign_rules(db: Session, telephony_setup):
    campaign = _trigger(db, telephony_setup)
    assert campaign.status == "RUNNING"
    with pytest.raises(svc.CampaignError):
        svc.add_recipients_from_csv(db, campaign, "phone\n9876500601\n")
    # Editable while running, and never completes on its own
    svc.update_campaign(db, campaign, {"max_concurrent": 2})
    svc.run_campaign_tick(db, IN_WINDOW, dial=FakeDialer(db, telephony_setup))
    db.refresh(campaign)
    assert campaign.status == "RUNNING" and campaign.max_concurrent == 2
    with pytest.raises(svc.CampaignError, match="https"):
        svc.update_campaign(db, campaign, {"webhook_url": "http://insecure.example.com"})


def test_portal_keys_and_scoping(client: TestClient, auth_headers: dict, db: Session, telephony_setup, monkeypatch):
    monkeypatch.setattr(public_leads, "SESSION_FACTORY", lambda: _SharedSession(db))
    monkeypatch.setattr(public_leads, "DIAL", FakeDialer(db, telephony_setup))
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"keys-{cid}@clinic.example.com")

    created = client.post("/api/portal/api-keys", headers=headers, json={"name": "Website form"})
    assert created.status_code == 201 and created.json()["key"].startswith("chr_live_")
    listed = client.get("/api/portal/api-keys", headers=headers).json()
    assert len(listed) == 1 and "key" not in listed[0] and listed[0]["prefix"] == created.json()["key"][:15]

    # No website-lead campaign yet
    no_campaign = client.post("/api/public/leads", headers={"X-API-Key": created.json()["key"]}, json=LEAD)
    assert no_campaign.status_code == 409
    info = client.get("/api/portal/integrations", headers=headers).json()
    assert info["leads_url"].endswith("/api/public/leads") and info["active_keys"] == 1

    other = Client(id=generate_unique_id("cli_"), name="Other Clinic", business_type="CLINIC")
    db.add(other)
    db.commit()
    other_headers = _client_headers(client, auth_headers, other.id, f"keys-{other.id}@clinic.example.com")
    assert client.delete(f"/api/portal/api-keys/{created.json()['id']}", headers=other_headers).status_code == 404
    assert client.get("/api/portal/api-keys", headers=other_headers).json() == []

    # A key can't target another client's campaign
    other_key, other_raw = instant_leads.create_api_key(db, other.id, "Other", None)
    campaign = _trigger(db, telephony_setup)
    wrong = client.post("/api/public/leads", headers={"X-API-Key": other_raw}, json={**LEAD, "campaign_id": campaign.id})
    assert wrong.status_code == 404

    revoked = client.delete(f"/api/portal/api-keys/{created.json()['id']}", headers=headers)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"]
    assert client.post("/api/public/leads", headers={"X-API-Key": created.json()["key"]}, json=LEAD).status_code == 401

    admin_keys = client.get(f"/api/clients/{cid}/api-keys", headers=auth_headers)
    assert admin_keys.status_code == 200 and len(admin_keys.json()) == 1
