import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.lead import Lead
from app.models.qualification import LeadQualificationSetup
from app.services import call_outputs, outbound_insights
from app.services import lead_qualification as svc
from test_call_outputs import FakeLLM, TURNS, _call_with_transcript
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

OUTPUTS = [
    {"name": "target_exam", "description": "Exam the student prepares for", "data_type": "string"},
    {"name": "demo_class_booked", "description": "Whether a demo class was booked", "data_type": "boolean"},
    {"name": "student_class", "description": "Class the student is in", "data_type": "number"},
]
RULES = [
    [{"field": "demo_class_booked", "op": "is_true"}],
    [{"field": "target_exam", "op": "in", "value": ["NEET", "JEE"]}, {"field": "student_class", "op": "gte", "value": 11}],
]


@pytest.fixture
def setup(db: Session, telephony_setup):
    version = telephony_setup["version"]
    config = dict(version.configuration_json)
    config["variables"] = {**(config.get("variables") or {}), "outputs": OUTPUTS}
    version.configuration_json = config
    flag_modified(version, "configuration_json")
    db.commit()
    return telephony_setup


def _rules_setup(rules=RULES, criteria=None) -> LeadQualificationSetup:
    return LeadQualificationSetup(rules=rules, ai_criteria=criteria)


@pytest.mark.parametrize("outputs,interest,status", [
    ({"demo_class_booked": True}, "unclear", "qualified"),
    ({"demo_class_booked": False, "target_exam": "neet", "student_class": 12}, "interested", "qualified"),
    ({"demo_class_booked": False, "target_exam": "CA", "student_class": 12}, "interested", "not_qualified"),
    ({"demo_class_booked": False, "target_exam": "NEET", "student_class": 9}, "interested", "not_qualified"),
    # Class wasn't collected: the rules can't tell
    ({"demo_class_booked": False, "target_exam": "NEET", "student_class": None}, "interested", "unknown"),
    # Asking never to be called again always wins
    ({"demo_class_booked": True}, "do_not_call", "not_qualified"),
])
def test_rules(outputs, interest, status):
    assert svc.qualify(_rules_setup(), outputs, interest)["status"] == status


def test_rule_reason_names_what_matched():
    result = svc.qualify(_rules_setup(), {"demo_class_booked": False, "target_exam": "NEET", "student_class": 12}, "interested")
    assert result["source"] == "rules" and "NEET" in result["reason"] and "at least 11" in result["reason"]


def test_ai_test_decides_when_rules_cannot():
    setup = _rules_setup(criteria="Plans to join this year")
    ai = {"status": "qualified", "reason": "Said she wants to join the June batch"}
    result = svc.qualify(setup, {"target_exam": "NEET", "student_class": None}, "interested", ai=ai)
    assert result == {"status": "qualified", "reason": ai["reason"], "source": "ai"}
    # A clear answer from the rules is not overridden by the AI
    assert svc.qualify(setup, {"demo_class_booked": False, "target_exam": "CA", "student_class": 12}, "interested",
                       ai=ai)["status"] == "not_qualified"


def test_without_setup_interest_decides():
    assert svc.qualify(None, {}, "callback", summary="Call back tomorrow")["status"] == "qualified"
    assert svc.qualify(None, {}, "not_interested")["status"] == "not_qualified"
    assert svc.qualify(None, {}, "unclear")["status"] == "unknown"


def test_interest_field_in_rules():
    rules = [[{"field": "interest", "op": "in", "value": ["interested"]}, {"field": "demo_class_booked", "op": "is_true"}]]
    assert svc.qualify(_rules_setup(rules), {"demo_class_booked": True}, "interested")["status"] == "qualified"
    assert svc.qualify(_rules_setup(rules), {"demo_class_booked": True}, "callback")["status"] == "not_qualified"


def test_validation(db: Session, setup):
    fields = svc.fields_for_agent(db, setup["agent"].id)
    with pytest.raises(svc.QualificationError):
        svc.validate_rules([[{"field": "nonexistent", "op": "is_true"}]], fields)
    with pytest.raises(svc.QualificationError):
        svc.validate_rules([[{"field": "demo_class_booked", "op": "gte", "value": 3}]], fields)
    with pytest.raises(svc.QualificationError):
        svc.validate_rules([[{"field": "student_class", "op": "gte", "value": "eleven"}]], fields)
    assert svc.validate_rules(RULES, fields)[1][1]["value"] == 11.0


def test_suggestions_use_booking_fields(db: Session, setup):
    suggestion = svc.suggested_rules(svc.fields_for_agent(db, setup["agent"].id))
    assert suggestion == [[{"field": "demo_class_booked", "op": "is_true"}]]


def test_extraction_applies_rules_and_ai_test_in_one_call(db: Session, setup):
    svc.save_setup(db, setup["client"].id, setup["agent"].id, RULES, "Plans to join this year")
    call = _call_with_transcript(db, setup, TURNS)
    call.direction = "INBOUND"
    db.commit()
    llm = FakeLLM(json.dumps({
        "outputs": {"target_exam": "NEET", "demo_class_booked": None, "student_class": None},
        "summary": "NEET aspirant", "interest": "interested", "callback_time": None,
        "qualified": "yes", "qualified_reason": "Wants to join this year",
    }))
    assert call_outputs.mark_pending(db, call) is True
    call_outputs.run_extraction(db, call.id, llm=llm)
    db.refresh(call)
    assert "Plans to join this year" in llm.prompts[0][0]
    assert call.metadata_["qualification"] == {"status": "qualified", "reason": "Wants to join this year", "source": "ai"}


def test_inbound_calls_are_analysed_without_outputs(db: Session, telephony_setup):
    call = _call_with_transcript(db, telephony_setup, TURNS)
    call.direction = "INBOUND"
    db.commit()
    assert call_outputs.mark_pending(db, call) is True


def test_qualified_inbound_caller_is_a_hot_lead(db: Session, setup):
    client_id = setup["client"].id
    db.add(Lead(client_id=client_id, name="Meena", phone="+919811112222"))
    call = Call(
        id=generate_unique_id("call_"), client_id=client_id, agent_id=setup["agent"].id,
        agent_version_id=setup["version"].id, caller_number="+919811112222", destination_number="+914000000000",
        direction="INBOUND", status="COMPLETED", provider="vobiz", provider_call_id=generate_unique_id("exo_"),
        created_at=datetime.utcnow(),
        metadata_={"outputs_status": "done", "interest": "interested", "summary": "Wants NEET coaching",
                   "qualification": {"status": "qualified", "reason": "Demo class booked", "source": "rules"}},
    )
    db.add(call)
    db.commit()
    data = outbound_insights.insights(db, client_id, 30)
    hot = [h for h in data["hot_leads"] if h["kind"] == "inbound"]
    assert [(h["name"], h["reason"]) for h in hot] == [("Meena", "Demo class booked")]
    assert outbound_insights.mark_followed_up(db, client_id, call.id) is True
    assert not [h for h in outbound_insights.insights(db, client_id, 30)["hot_leads"] if h["kind"] == "inbound"]


def test_qualification_marks_pending_lead(db: Session, setup):
    client_id = setup["client"].id
    lead = Lead(client_id=client_id, name="Arjun", phone="+919876543210")
    db.add(lead)
    db.commit()
    call = _call_with_transcript(db, setup, TURNS)
    svc.record_on_lead(db, call, {"status": "qualified"})
    db.refresh(lead)
    assert lead.lead_qualification_status == "QUALIFIED"
    # A status set by the agent or the client isn't overwritten
    svc.record_on_lead(db, call, {"status": "not_qualified"})
    db.refresh(lead)
    assert lead.lead_qualification_status == "QUALIFIED"


def test_reevaluate_applies_new_rules_to_recent_calls(db: Session, setup):
    call = _call_with_transcript(db, setup, TURNS)
    call.created_at = datetime.utcnow()
    call.metadata_ = {"outputs_status": "done", "interest": "interested",
                      "outputs": {"demo_class_booked": False, "target_exam": "CA", "student_class": 12},
                      "qualification": {"status": "qualified", "reason": "Interested", "source": "interest"}}
    db.commit()
    svc.save_setup(db, setup["client"].id, setup["agent"].id, RULES, None)
    assert svc.reevaluate(db, setup["client"].id, setup["agent"].id) == 1
    db.refresh(call)
    assert call.metadata_["qualification"]["status"] == "not_qualified"


def test_portal_api(client: TestClient, auth_headers: dict, db: Session, setup):
    cid = setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"owner-{cid}@quals.example.com")
    listed = client.get("/api/portal/qualification", headers=headers)
    assert listed.status_code == 200
    assert {f["name"] for f in listed.json()[0]["fields"]} >= {"interest", "demo_class_booked"}

    saved = client.put(f"/api/portal/qualification/{setup['agent'].id}", headers=headers,
                       json={"rules": RULES, "ai_criteria": "Plans to join this year"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] and saved.json()["ai_criteria"] == "Plans to join this year"

    bad = client.put(f"/api/portal/qualification/{setup['agent'].id}", headers=headers,
                     json={"rules": [[{"field": "nope", "op": "is_true"}]]})
    assert bad.status_code == 400

    other = _client_headers(client, auth_headers, telephony_setup_other(db), "other@quals.example.com")
    assert client.put(f"/api/portal/qualification/{setup['agent'].id}", headers=other,
                      json={"rules": []}).status_code == 404
    assert client.post(f"/api/portal/qualification/{setup['agent'].id}/reevaluate", headers=headers).status_code == 200


def telephony_setup_other(db: Session) -> str:
    from app.models.client import Client
    other = Client(id=generate_unique_id("cli_"), name="Other Centre", business_type="COACHING")
    db.add(other)
    db.commit()
    return other.id
