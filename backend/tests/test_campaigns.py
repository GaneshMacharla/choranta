from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.campaign import Campaign, CampaignAttempt, CampaignRecipient, DoNotCallEntry
from app.models.client import Client
from app.models.lead import Lead
from app.services import campaigns as svc
from app.services.outbound_calls import OutboundCallError
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

# Tuesday 2026-10-13 11:00 IST (05:30 UTC): inside the default 10:00-19:00 Mon-Sat window
IN_WINDOW = datetime(2026, 10, 13, 5, 30)
# Same day 20:00 IST
OUT_OF_WINDOW = datetime(2026, 10, 13, 14, 30)
# Sunday 2026-10-18 11:00 IST
SUNDAY = datetime(2026, 10, 18, 5, 30)

CSV = "Name,Phone,Course Enquired\nPriya,9876543210,NEET\nRahul,09876543211,JEE\nDup,+919876543210,x\nBad,12345,y\n"


class FakeDialer:
    """Stands in for place_outbound_call: records dials, creates INITIATED calls, or raises."""

    def __init__(self, db: Session, setup):
        self.db, self.setup = db, setup
        self.dialed = []
        self.error = None

    def __call__(self, db, *, destination_number, agent_id, agent_version_id, caller_id, custom_field, variables, extra_metadata, **kwargs):
        if self.error:
            raise self.error
        call = Call(
            id=generate_unique_id("call"), client_id=self.setup["client"].id, agent_id=agent_id,
            agent_version_id=agent_version_id, caller_number=caller_id, destination_number=destination_number,
            direction="OUTBOUND", status="INITIATED", provider="exotel", provider_call_id=generate_unique_id("exo"),
            metadata_={"variables": variables, **extra_metadata},
        )
        db.add(call)
        db.commit()
        self.dialed.append((destination_number, caller_id, variables))
        return call


def _end(db: Session, recipient: CampaignRecipient, status: str, reason: str = None, duration: float = 60.0):
    call = db.get(Call, recipient.last_call_id)
    call.status = status
    call.termination_reason = reason
    call.duration_seconds = duration
    db.commit()


def _campaign(db: Session, setup, **overrides) -> Campaign:
    data = dict(
        name="NEET enquiries", agent_id=setup["agent"].id, agent_version_id=setup["version"].id,
        caller_number_ids=[setup["phone_number"].id], timezone="Asia/Kolkata",
        windows=[{"start_min": 600, "end_min": 1140}], days=[0, 1, 2, 3, 4, 5],
        max_concurrent=2, retry_max=1, retry_intervals_min=[30], retry_on=["no-answer", "busy", "failed"],
    )
    data.update(overrides)
    return svc.create_campaign(db, setup["client"].id, data, created_by="usr_test")


def _running(db: Session, setup, csv_text: str = CSV, **overrides) -> Campaign:
    campaign = _campaign(db, setup, **overrides)
    svc.add_recipients_from_csv(db, campaign, csv_text)
    return svc.launch(db, campaign, "usr_test", consent=True)


def _recipients(db: Session, campaign: Campaign):
    return db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).order_by(CampaignRecipient.position).all()


def test_normalize_phone():
    assert svc.normalize_phone("98765 43210") == "+919876543210"
    assert svc.normalize_phone("09876543210") == "+919876543210"
    assert svc.normalize_phone("919876543210") == "+919876543210"
    assert svc.normalize_phone("+1 (415) 555-2671") == "+14155552671"
    assert svc.normalize_phone("12345") is None
    assert svc.normalize_phone("") is None


def test_parse_csv_maps_columns_to_variables_and_reports_problems():
    parsed = svc.parse_recipients_csv("﻿" + CSV)
    assert [r["phone"] for r in parsed.rows] == ["+919876543210", "+919876543211"]
    assert parsed.rows[0]["variables"] == {"course_enquired": "NEET", "user_name": "Priya"}
    assert parsed.duplicates == 1
    assert parsed.invalid == [{"line": 5, "value": "12345", "reason": "Not a valid phone number"}]
    assert parsed.variable_names == ["user_name", "course_enquired"]

    with pytest.raises(svc.CampaignError):
        svc.parse_recipients_csv("name,email\nPriya,p@example.com\n")


def test_validation_rejects_bad_settings(db: Session, telephony_setup):
    with pytest.raises(svc.CampaignError, match="between 09:00 and 21:00"):
        _campaign(db, telephony_setup, windows=[{"start_min": 480, "end_min": 600}])
    other = Client(id=generate_unique_id("cli_"), name="Other", business_type="CLINIC")
    db.add(other)
    db.commit()
    with pytest.raises(svc.CampaignError, match="belongs to this client"):
        svc.create_campaign(db, other.id, dict(
            name="x", agent_id=telephony_setup["agent"].id, agent_version_id=telephony_setup["version"].id,
            caller_number_ids=[telephony_setup["phone_number"].id], windows=[{"start_min": 600, "end_min": 1140}],
            days=[0], max_concurrent=1, retry_max=0, retry_intervals_min=[], retry_on=[],
        ), created_by=None)

    campaign = _campaign(db, telephony_setup)
    with pytest.raises(svc.CampaignError, match="Add recipients"):
        svc.launch(db, campaign, "usr_test", consent=True)
    svc.add_recipients_from_csv(db, campaign, CSV)
    with pytest.raises(svc.CampaignError, match="Confirm"):
        svc.launch(db, campaign, "usr_test", consent=False)


def test_instant_outbound_may_call_24_7_but_bulk_may_not(db: Session, telephony_setup):
    round_the_clock = dict(windows=[{"start_min": 0, "end_min": 1440}], days=[0, 1, 2, 3, 4, 5, 6])
    with pytest.raises(svc.CampaignError, match="between 09:00 and 21:00"):
        _campaign(db, telephony_setup, **round_the_clock)

    campaign = _campaign(db, telephony_setup, name="Website enquiries", kind="TRIGGER", **round_the_clock)
    assert svc.in_calling_window(campaign, datetime(2026, 10, 17, 21, 30))  # Sunday 03:00 IST
    assert svc.in_calling_window(campaign, OUT_OF_WINDOW)


def test_dials_only_inside_window_and_respects_concurrency(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500001\n9876500002\n9876500003\n", max_concurrent=2)

    assert svc.run_campaign_tick(db, OUT_OF_WINDOW, dial=dialer) == 0
    assert svc.run_campaign_tick(db, SUNDAY, dial=dialer) == 0

    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 2
    assert [d[0] for d in dialer.dialed] == ["+919876500001", "+919876500002"]
    assert dialer.dialed[0][1] == telephony_setup["phone_number"].phone_number
    # Lines are full: a second tick places nothing and never re-dials the claimed recipients
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 0
    assert len(dialer.dialed) == 2

    # One call ends: the next recipient is dialled straight away (sliding window)
    first = _recipients(db, campaign)[0]
    _end(db, first, "COMPLETED")
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 1
    assert dialer.dialed[-1][0] == "+919876500003"
    db.refresh(first)
    assert first.status == "COMPLETED" and first.outcome == "answered"


def test_variables_reach_the_dial_and_campaign_completes(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="name,phone,course\nPriya,9876500011,NEET\n")
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert dialer.dialed[0][2] == {"course": "NEET", "user_name": "Priya"}

    (recipient,) = _recipients(db, campaign)
    _end(db, recipient, "COMPLETED", duration=90)
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    db.refresh(campaign)
    assert campaign.status == "COMPLETED"
    stats = svc.stats(db, campaign)
    assert stats["answered"] == 1 and stats["answer_rate"] == 1.0 and stats["minutes"] == 1.5
    assert "Priya" in svc.export_results_csv(db, campaign)


def _with_campaign_inputs(db: Session, setup):
    """Gives the setup's agent version the batch announcement's campaign inputs (course, timings, demo...)."""
    from app.services.agent_templates import get_agent_template_by_id

    tpl = get_agent_template_by_id("course_batch_announcement")
    version = setup["version"]
    config = dict(version.configuration_json or {})
    config["variables"] = {**(config.get("variables") or {}), "inputs": tpl["default_config"]["variables"]["inputs"]}
    version.configuration_json = config
    db.commit()


BATCH = {"course_name": "Snowflake and DBT", "batch_start_date": "Monday, 19 October",
         "batch_timings": "Weekdays 7 to 9 pm", "demo_class": "Saturday, 25 October at 11 am"}


def test_campaign_details_reach_every_call_and_recipient_values_win(db: Session, telephony_setup):
    _with_campaign_inputs(db, telephony_setup)
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="name,phone,course_name\nPriya,9876500011,\nRahul,9876500012,Azure\n",
                        variables={**BATCH, "course_fees": "  ", "extra": None})
    assert campaign.variables == BATCH  # blanks dropped, values trimmed
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    by_phone = {phone: variables for phone, _, variables in dialer.dialed}
    assert by_phone["+919876500011"]["demo_class"] == "Saturday, 25 October at 11 am"
    assert by_phone["+919876500011"]["course_name"] == "Snowflake and DBT"
    assert by_phone["+919876500012"]["course_name"] == "Azure" and by_phone["+919876500012"]["user_name"] == "Rahul"


def test_launch_requires_the_agents_campaign_details(db: Session, telephony_setup):
    _with_campaign_inputs(db, telephony_setup)
    campaign = _campaign(db, telephony_setup, variables={"course_name": "Snowflake and DBT"})
    svc.add_recipients_from_csv(db, campaign, CSV)
    with pytest.raises(svc.CampaignError) as err:
        svc.launch(db, campaign, "usr_test", consent=True)
    assert "When the new batch starts" in err.value.message and "When the free demo class is" in err.value.message
    svc.update_campaign(db, campaign, {"variables": BATCH})
    assert svc.launch(db, campaign, "usr_test", consent=True).status == "RUNNING"


def test_campaign_options_list_the_versions_campaign_inputs(client: TestClient, auth_headers: dict, db: Session, telephony_setup):
    _with_campaign_inputs(db, telephony_setup)
    options = client.get(f"/api/campaigns/options?client_id={telephony_setup['client'].id}", headers=auth_headers).json()
    (version,) = [v for a in options["agents"] for v in a["versions"] if v["id"] == telephony_setup["version"].id]
    inputs = {i["name"]: i for i in version["campaign_inputs"]}
    assert inputs["course_name"]["required"] and inputs["course_name"]["example"] == "Snowflake and DBT"
    assert not inputs["course_fees"]["required"] and "company_name" not in inputs


def test_no_answer_is_retried_after_interval_then_fails(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500021\n", retry_max=1, retry_intervals_min=[30])
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    (recipient,) = _recipients(db, campaign)

    _end(db, recipient, "FAILED", "no-answer", 0)
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    db.refresh(recipient)
    assert recipient.status == "RETRY_WAIT" and recipient.outcome == "no-answer"
    assert recipient.next_attempt_at == IN_WINDOW + timedelta(minutes=30)
    assert len(dialer.dialed) == 1

    later = IN_WINDOW + timedelta(minutes=31)
    assert svc.run_campaign_tick(db, later, dial=dialer) == 1
    db.refresh(recipient)
    assert recipient.attempts == 2

    _end(db, recipient, "FAILED", "busy", 0)
    svc.run_campaign_tick(db, later, dial=dialer)
    db.refresh(recipient)
    db.refresh(campaign)
    assert recipient.status == "FAILED" and recipient.outcome == "busy"
    assert campaign.status == "COMPLETED"
    assert db.query(CampaignAttempt).filter(CampaignAttempt.recipient_id == recipient.id).count() == 2


def test_no_balance_pauses_campaign_and_concurrency_waits(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500031\n")

    dialer.error = OutboundCallError("CONCURRENCY", "Lines busy", 429)
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 0
    db.refresh(campaign)
    (recipient,) = _recipients(db, campaign)
    assert campaign.status == "RUNNING" and recipient.status == "PENDING" and recipient.attempts == 0

    dialer.error = OutboundCallError("NO_BALANCE", "Wallet balance is exhausted.", 402)
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    db.refresh(campaign)
    db.refresh(recipient)
    assert campaign.status == "PAUSED" and "Wallet" in campaign.pause_reason
    assert recipient.status == "PENDING"

    dialer.error = None
    svc.resume(db, campaign)
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 1


def test_suppressed_numbers_are_skipped(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    client_id = telephony_setup["client"].id
    svc.add_do_not_call(db, client_id, "9876500041")
    db.add(Lead(id=generate_unique_id("lead"), client_id=client_id, name="Opted out", phone="+919876500042",
                call_disposition="DO_NOT_CALL"))
    db.commit()
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500041\n9876500042\n9876500043\n", max_concurrent=3)

    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 1
    assert [d[0] for d in dialer.dialed] == ["+919876500043"]
    skipped = [r for r in _recipients(db, campaign) if r.status == "SKIPPED"]
    assert {r.outcome for r in skipped} == {"suppressed"} and len(skipped) == 2


def test_caller_opt_out_is_added_to_do_not_call(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    client_id = telephony_setup["client"].id
    lead = Lead(id=generate_unique_id("lead"), client_id=client_id, name="Asha", phone="+919876500051")
    db.add(lead)
    db.commit()
    campaign = _campaign(db, telephony_setup)
    svc.add_recipients_from_leads(db, campaign, [lead.id])
    svc.launch(db, campaign, "usr_test", consent=True)
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert dialer.dialed[0][2]["user_name"] == "Asha"

    lead.call_disposition = "DO_NOT_CALL"
    (recipient,) = _recipients(db, campaign)
    _end(db, recipient, "COMPLETED")
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert db.query(DoNotCallEntry).filter(DoNotCallEntry.client_id == client_id, DoNotCallEntry.phone == "+919876500051").count() == 1


def test_stop_lets_live_calls_finish(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500061\n9876500062\n", max_concurrent=1)
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    svc.stop(db, campaign)
    first, second = _recipients(db, campaign)
    assert campaign.status == "STOPPING" and first.status == "DIALING" and second.status == "SKIPPED"

    _end(db, first, "COMPLETED")
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 0
    db.refresh(campaign)
    assert campaign.status == "COMPLETED"


def test_scheduled_start(db: Session, telephony_setup):
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500071\n", start_at=IN_WINDOW + timedelta(hours=1))
    # launched before start_at (utcnow is real time, start_at is in 2026-10-13): stays scheduled until then
    campaign.status = "SCHEDULED"
    db.commit()
    assert svc.run_campaign_tick(db, IN_WINDOW, dial=dialer) == 0
    assert svc.run_campaign_tick(db, IN_WINDOW + timedelta(hours=1, minutes=1), dial=dialer) == 1


def test_campaign_api_admin_and_portal_scoping(client: TestClient, auth_headers: dict, db: Session, telephony_setup):
    cid = telephony_setup["client"].id
    options = client.get(f"/api/campaigns/options?client_id={cid}", headers=auth_headers)
    assert options.status_code == 200, options.text
    assert options.json()["agents"][0]["versions"][0]["id"] == telephony_setup["version"].id

    preview = client.post("/api/campaigns/preview-csv", headers=auth_headers, json={"csv_text": CSV})
    assert preview.json()["valid"] == 2 and preview.json()["invalid_count"] == 1

    body = {
        "client_id": cid, "name": "API campaign", "agent_id": telephony_setup["agent"].id,
        "agent_version_id": telephony_setup["version"].id, "caller_number_ids": [telephony_setup["phone_number"].id],
    }
    created = client.post("/api/campaigns", headers=auth_headers, json=body)
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    assert created.json()["timezone"] == "Asia/Kolkata" and created.json()["windows"] == [{"start_min": 600, "end_min": 1140}]

    imported = client.post(f"/api/campaigns/{campaign_id}/recipients/csv", headers=auth_headers, json={"csv_text": CSV})
    assert imported.json()["added"] == 2
    recipients = client.get(f"/api/campaigns/{campaign_id}/recipients", headers=auth_headers).json()
    assert recipients["total"] == 2

    assert client.post(f"/api/campaigns/{campaign_id}/launch", headers=auth_headers, json={"consent": False}).status_code == 400
    launched = client.post(f"/api/campaigns/{campaign_id}/launch", headers=auth_headers, json={"consent": True})
    assert launched.json()["status"] == "RUNNING" and launched.json()["stats"]["pending"] == 2
    assert client.patch(f"/api/campaigns/{campaign_id}", headers=auth_headers, json={"name": "x"}).status_code == 409
    assert client.post(f"/api/campaigns/{campaign_id}/pause", headers=auth_headers).json()["status"] == "PAUSED"

    # The owning client sees it in the portal; another client gets 404
    portal_headers = _client_headers(client, auth_headers, cid, f"campaigns-{cid}@clinic.example.com")
    mine = client.get("/api/portal/campaigns", headers=portal_headers)
    assert [c["id"] for c in mine.json()] == [campaign_id]
    assert client.get("/api/portal/campaigns/options", headers=portal_headers).status_code == 200

    other = Client(id=generate_unique_id("cli_"), name="Other Clinic", business_type="CLINIC")
    db.add(other)
    db.commit()
    other_headers = _client_headers(client, auth_headers, other.id, f"campaigns-{other.id}@clinic.example.com")
    assert client.get(f"/api/portal/campaigns/{campaign_id}", headers=other_headers).status_code == 404
    assert client.post(f"/api/portal/campaigns/{campaign_id}/resume", headers=other_headers).status_code == 404
    assert client.get("/api/portal/campaigns", headers=other_headers).json() == []

    exported = client.get(f"/api/portal/campaigns/{campaign_id}/export.csv", headers=portal_headers)
    assert exported.status_code == 200 and "course_enquired" in exported.text


def test_deleting_an_agent_removes_its_campaigns(db: Session, telephony_setup):
    from app.models.agent import Agent
    from app.services.agent_service import AgentService

    campaign = _running(db, telephony_setup)
    agent_id, campaign_id = campaign.agent_id, campaign.id
    assert _recipients(db, campaign)
    AgentService(db).delete_agent(agent_id)  # used to fail: campaigns still referenced the agent's version
    assert db.get(Agent, agent_id) is None
    assert db.query(Campaign).filter(Campaign.agent_id == agent_id).count() == 0
    assert db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign_id).count() == 0
