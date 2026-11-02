from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.call import Call
from app.models.campaign import CampaignRecipient
from app.models.client import Client
from app.services import campaigns as svc
from app.services import instant_leads, outbound_insights
from test_campaigns import IN_WINDOW, OUT_OF_WINDOW, FakeDialer, _recipients, _running
from test_instant_leads import _key, _trigger
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

LATER = IN_WINDOW + timedelta(days=2)


@pytest.fixture(autouse=True)
def enough_vobiz_lines(monkeypatch):
    # _bulk_run dials four at once; the default Vobiz account has three lines
    monkeypatch.setattr(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 10)


def _answer(db: Session, recipient: CampaignRecipient, interest=None, summary=None, duration=60.0, outputs=None):
    call = db.get(Call, recipient.last_call_id)
    call.status = "COMPLETED"
    call.duration_seconds = duration
    call.metadata_ = {**(call.metadata_ or {}), "interest": interest, "summary": summary,
                      "callback_time": "Friday evening" if interest == "callback" else None, "outputs": outputs or {}}
    db.commit()


def _no_answer(db: Session, recipient: CampaignRecipient):
    call = db.get(Call, recipient.last_call_id)
    call.status = "FAILED"
    call.termination_reason = "no-answer"
    db.commit()


def _bulk_run(db: Session, setup, now=IN_WINDOW):
    """Four recipients: interested, callback, not interested, no answer (no retries)."""
    dialer = FakeDialer(db, setup)
    campaign = _running(db, setup, csv_text="name,phone\nAsha,9876500201\nRavi,9876500202\nMeena,9876500203\nKiran,9876500204\n",
                        max_concurrent=4, retry_max=0)
    svc.run_campaign_tick(db, now, dial=dialer)
    asha, ravi, meena, kiran = _recipients(db, campaign)
    _answer(db, asha, "interested", "Wants NEET coaching.", 120, {"course": "NEET"})
    _answer(db, ravi, "callback", "Call back later.", 60, {"course": "JEE"})
    _answer(db, meena, "not_interested", "Not interested.", 30, {"course": "NEET"})
    _no_answer(db, kiran)
    svc.run_campaign_tick(db, now + timedelta(seconds=5), dial=dialer)
    return campaign, (asha, ravi, meena, kiran)


def test_funnel_hot_leads_answers_and_campaign_rows(db: Session, telephony_setup):
    campaign, (asha, ravi, _, _) = _bulk_run(db, telephony_setup)
    data = outbound_insights.insights(db, telephony_setup["client"].id, 7, now=LATER)

    assert data["has_outbound"] is True
    funnel = data["funnel"]
    assert (funnel["called"], funnel["answered"], funnel["interested"], funnel["callbacks"]) == (4, 3, 2, 1)
    assert funnel["not_interested"] == 1 and funnel["answer_rate"] == 0.75
    assert funnel["avg_talk_seconds"] == 70 and funnel["minutes"] == 3.5

    by_name = {h["name"]: h for h in data["hot_leads"]}
    assert set(by_name) == {"Asha", "Ravi"} and data["hot_leads_total"] == 2
    assert by_name["Ravi"]["callback_time"] == "Friday evening"
    assert by_name["Asha"]["summary"] == "Wants NEET coaching." and by_name["Asha"]["call_id"] == asha.last_call_id

    assert data["top_answers"] == {"course": {"NEET": 2, "JEE": 1}}
    (row,) = data["campaigns"]
    assert (row["id"], row["called"], row["answered"], row["interested"], row["answer_rate"]) == (campaign.id, 4, 3, 2, 0.75)
    assert data["instant"] is None

    # Outside the period nothing counts
    assert outbound_insights.insights(db, telephony_setup["client"].id, 7, now=IN_WINDOW + timedelta(days=8))["funnel"]["called"] == 0


def test_followed_up_leads_leave_the_list_and_scoping(db: Session, telephony_setup):
    _, (asha, _, _, _) = _bulk_run(db, telephony_setup)
    client_id = telephony_setup["client"].id
    assert outbound_insights.mark_followed_up(db, "cli_someone_else", asha.id) is False
    assert outbound_insights.mark_followed_up(db, client_id, asha.id) is True

    data = outbound_insights.insights(db, client_id, 7, now=LATER)
    assert [h["name"] for h in data["hot_leads"]] == ["Ravi"]
    assert data["hot_leads_total"] == 1
    assert data["funnel"]["interested"] == 2  # still counted, just not on the follow-up list
    assert outbound_insights.insights(db, "cli_someone_else", 7, now=LATER)["has_outbound"] is False


def test_best_hours_use_the_campaign_timezone(db: Session, telephony_setup):
    _bulk_run(db, telephony_setup)  # IN_WINDOW is 11:00 in Asia/Kolkata
    hours = {h["hour"]: h for h in outbound_insights.insights(db, telephony_setup["client"].id, 7, now=LATER)["best_hours"]}
    assert list(hours) == list(range(9, 21))
    assert (hours[11]["attempts"], hours[11]["answered"], hours[11]["answer_rate"]) == (4, 3, 0.75)
    assert hours[10]["attempts"] == 0 and hours[10]["answer_rate"] is None


def test_instant_lead_speed_and_queued_leads(db: Session, telephony_setup):
    _trigger(db, telephony_setup)
    ctx, _, _ = _key(db, telephony_setup)
    dialer = FakeDialer(db, telephony_setup)

    fast = instant_leads.accept_lead(db, ctx, {"phone": "9876500301", "name": "Priya", "consent": True}, now=IN_WINDOW)
    instant_leads.instant_dial(db, fast["recipient_id"], now=IN_WINDOW, dial=dialer)
    # Arrives at 20:00 IST, outside calling hours: called when the window opens next morning
    _answer(db, db.get(CampaignRecipient, fast["recipient_id"]), "interested", "Booked a demo.")
    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=dialer)
    late = instant_leads.accept_lead(db, ctx, {"phone": "9876500302", "name": "Arjun", "consent": True}, now=OUT_OF_WINDOW)
    next_morning = IN_WINDOW + timedelta(days=1)
    svc.run_campaign_tick(db, next_morning, dial=dialer)
    _no_answer(db, db.get(CampaignRecipient, late["recipient_id"]))
    svc.run_campaign_tick(db, next_morning + timedelta(seconds=5), dial=dialer)

    instant = outbound_insights.insights(db, telephony_setup["client"].id, 7, now=LATER)["instant"]
    assert (instant["leads"], instant["reached"], instant["interested"]) == (2, 1, 1)
    assert instant["median_seconds_to_call"] == 0.0 and instant["called_within_60s_pct"] == 1.0
    assert instant["queued_for_hours"] == 1


def test_portal_endpoints_are_client_scoped(client: TestClient, auth_headers: dict, db: Session, telephony_setup, monkeypatch):
    monkeypatch.setattr(svc, "in_calling_window", lambda campaign, now: True)
    now = datetime.utcnow()
    _, (asha, _, _, _) = _bulk_run(db, telephony_setup, now=now)
    headers = _client_headers(client, auth_headers, telephony_setup["client"].id, f"insights-{telephony_setup['client'].id}@clinic.example.com")

    assert client.get("/api/portal/insights?days=12", headers=headers).status_code == 400
    data = client.get("/api/portal/insights?days=7", headers=headers).json()
    assert data["funnel"]["called"] == 4 and len(data["hot_leads"]) == 2

    other = Client(id="cli_other_insights", name="Other Co", business_type="CLINIC")
    db.add(other)
    db.commit()
    other_headers = _client_headers(client, auth_headers, other.id, "insights-other@clinic.example.com")
    assert client.get("/api/portal/insights", headers=other_headers).json()["has_outbound"] is False
    assert client.post(f"/api/portal/insights/hot-leads/{asha.id}/followed-up", headers=other_headers).status_code == 404

    assert client.post(f"/api/portal/insights/hot-leads/{asha.id}/followed-up", headers=headers).status_code == 204
    assert len(client.get("/api/portal/insights", headers=headers).json()["hot_leads"]) == 1
