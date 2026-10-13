from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.security import generate_unique_id
from app.models.call import Call
from app.models.campaign import CampaignRecipient
from app.models.runtime_event import RuntimeEvent
from app.models.runtime_session import RuntimeSession
from app.runtime.providers.base import LLMResult
from app.services import call_outputs
from app.services import campaigns as svc
from test_campaigns import IN_WINDOW, FakeDialer, _running
from test_phase3c_telephony import telephony_setup  # noqa: F401

OUTPUTS = [
    {"name": "target_exam", "description": "Exam the student prepares for", "data_type": "string"},
    {"name": "demo_class_booked", "description": "Whether a demo class was booked", "data_type": "boolean"},
    {"name": "student_class", "description": "Class the student is in", "data_type": "number"},
]


class FakeLLM:
    def __init__(self, text: str):
        self.text = text
        self.prompts = []

    def generate(self, system_instruction, messages, available_tools=None, temperature=0.7, model=None):
        self.prompts.append((system_instruction, messages))
        return LLMResult(text=self.text)


def _with_outputs(db: Session, setup) -> None:
    version = setup["version"]
    config = dict(version.configuration_json)
    config["variables"] = {**(config.get("variables") or {}), "outputs": OUTPUTS}
    version.configuration_json = config
    flag_modified(version, "configuration_json")
    db.commit()


def _call_with_transcript(db: Session, setup, turns, call: Call = None) -> Call:
    session = RuntimeSession(
        id=generate_unique_id("ses"), client_id=setup["client"].id, agent_id=setup["agent"].id,
        agent_version_id=setup["version"].id, status="COMPLETED", metadata_={},
    )
    db.add(session)
    if call is None:
        call = Call(
            id=generate_unique_id("call"), client_id=setup["client"].id, agent_id=setup["agent"].id,
            agent_version_id=setup["version"].id, caller_number="+914045209348", destination_number="+919876543210",
            direction="OUTBOUND", status="COMPLETED", provider="exotel", provider_call_id=generate_unique_id("exo"),
            metadata_={},
        )
        db.add(call)
    call.runtime_session_id = session.id
    start = datetime(2026, 10, 13, 5, 0)
    for i, (kind, text) in enumerate(turns):
        db.add(RuntimeEvent(
            id=generate_unique_id("evt"), session_id=session.id, client_id=setup["client"].id,
            agent_id=setup["agent"].id, agent_version_id=setup["version"].id, event_type=kind,
            payload_json={"text": text}, timestamp=start + timedelta(seconds=i),
        ))
    db.commit()
    return call


TURNS = [
    ("ASSISTANT_RESPONSE", "Hello, am I speaking with Priya?"),
    ("USER_TRANSCRIPT_FINAL", "Yes. I'm in class 12 and preparing for NEET."),
    ("ASSISTANT_RESPONSE", "Great! Shall I book a free demo class on Saturday at 10?"),
    ("USER_TRANSCRIPT_FINAL", "Haan, book it."),
]


def test_extraction_fills_outputs_with_types(db: Session, telephony_setup):
    _with_outputs(db, telephony_setup)
    call = _call_with_transcript(db, telephony_setup, TURNS)
    assert call_outputs.mark_pending(db, call) is True
    assert call.metadata_["outputs_status"] == "pending"

    llm = FakeLLM('```json\n{"outputs": {"target_exam": "NEET", "demo_class_booked": "yes", "student_class": "12", '
                  '"unknown": 1}, "summary": "Priya (class 12, NEET) booked a Saturday demo."}\n```')
    call_outputs.run_extraction(db, call.id, llm=llm)
    db.refresh(call)
    assert call.metadata_["outputs"] == {"target_exam": "NEET", "demo_class_booked": True, "student_class": 12}
    assert call.metadata_["summary"].startswith("Priya")
    assert call.metadata_["outputs_status"] == "done"
    system, messages = llm.prompts[0]
    assert "demo_class_booked (boolean)" in system
    assert "Caller: Haan, book it." in messages[0]["content"]


def test_extraction_skips_calls_where_caller_never_spoke_and_records_failures(db: Session, telephony_setup):
    _with_outputs(db, telephony_setup)
    silent = _call_with_transcript(db, telephony_setup, [("ASSISTANT_RESPONSE", "Hello?")])
    call_outputs.run_extraction(db, silent.id, llm=FakeLLM("{}"))
    db.refresh(silent)
    assert silent.metadata_["outputs_status"] == "skipped"
    assert silent.metadata_["outputs"] == {"target_exam": None, "demo_class_booked": None, "student_class": None}

    broken = _call_with_transcript(db, telephony_setup, TURNS)
    call_outputs.run_extraction(db, broken.id, llm=FakeLLM("not json"))
    db.refresh(broken)
    assert broken.metadata_["outputs_status"] == "failed"


def test_agent_without_outputs_needs_no_extraction(db: Session, telephony_setup):
    call = _call_with_transcript(db, telephony_setup, TURNS)
    assert call_outputs.mark_pending(db, call) is False


def test_campaign_waits_for_outputs_then_reports_them(db: Session, telephony_setup):
    _with_outputs(db, telephony_setup)
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="name,phone\nPriya,9876500081\n")
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).one()

    # Call ended; extraction still running: the recipient stays on the line briefly
    call = db.get(Call, recipient.last_call_id)
    call.status = "COMPLETED"
    call.ended_at = IN_WINDOW
    _call_with_transcript(db, telephony_setup, TURNS, call=call)
    call_outputs.mark_pending(db, call)
    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=10), dial=dialer)
    db.refresh(recipient)
    assert recipient.status == "DIALING"

    call_outputs.run_extraction(db, call.id, llm=FakeLLM(
        '{"outputs": {"target_exam": "NEET", "demo_class_booked": true, "student_class": 12}, "summary": "Booked a demo."}'
    ))
    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=15), dial=dialer)
    db.refresh(recipient)
    assert recipient.status == "COMPLETED"
    assert recipient.result["outputs"]["demo_class_booked"] is True
    assert recipient.result["summary"] == "Booked a demo."

    stats = svc.stats(db, campaign)
    assert stats["collected"]["target_exam"] == {"NEET": 1}
    assert stats["collected"]["demo_class_booked"] == {"Yes": 1}
    exported = svc.export_results_csv(db, campaign)
    header, row = exported.strip().splitlines()[:2]
    assert "target_exam" in header and "demo_class_booked" in header and ",yes," in row


def test_campaign_stops_waiting_for_stuck_extraction(db: Session, telephony_setup):
    _with_outputs(db, telephony_setup)
    dialer = FakeDialer(db, telephony_setup)
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500091\n")
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).one()
    call = db.get(Call, recipient.last_call_id)
    call.status = "COMPLETED"
    call.ended_at = IN_WINDOW
    db.commit()
    call_outputs.mark_pending(db, call)

    svc.run_campaign_tick(db, IN_WINDOW + timedelta(minutes=3), dial=dialer)
    db.refresh(recipient)
    assert recipient.status == "COMPLETED" and recipient.outcome == "answered"


def _campaign_call(db: Session, setup, campaign) -> Call:
    """A dialled, ended call of the campaign's only recipient, with a transcript."""
    dialer = FakeDialer(db, setup)
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).one()
    call = db.get(Call, recipient.last_call_id)
    call.status = "COMPLETED"
    call.ended_at = IN_WINDOW
    return _call_with_transcript(db, setup, TURNS, call=call)


def _extraction_prompt(db: Session, setup) -> str:
    llm = FakeLLM('{"outputs": {}, "summary": ""}')
    call_outputs.run_extraction(db, _call_with_transcript(db, setup, TURNS).id, llm=llm)
    return llm.prompts[0][0]


def test_interest_and_callback_time_are_extracted(db: Session, telephony_setup):
    _with_outputs(db, telephony_setup)
    call = _call_with_transcript(db, telephony_setup, TURNS)
    call_outputs.run_extraction(db, call.id, llm=FakeLLM(
        '{"outputs": {}, "summary": "Wants a call back.", "interest": "Callback", "callback_time": "tomorrow 6pm"}'
    ))
    db.refresh(call)
    assert call.metadata_["interest"] == "callback"
    assert call.metadata_["callback_time"] == "tomorrow 6pm"
    assert "do_not_call" in _extraction_prompt(db, telephony_setup)

    other = _call_with_transcript(db, telephony_setup, TURNS)
    call_outputs.run_extraction(db, other.id, llm=FakeLLM('{"outputs": {}, "summary": "x", "interest": "maybe"}'))
    db.refresh(other)
    assert other.metadata_["interest"] == "unclear"
    assert other.metadata_["callback_time"] is None


def test_campaign_calls_are_extracted_even_without_agent_outputs(db: Session, telephony_setup):
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500111\n")
    call = _campaign_call(db, telephony_setup, campaign)
    assert call_outputs.mark_pending(db, call) is True

    call_outputs.run_extraction(db, call.id, llm=FakeLLM('{"outputs": {}, "summary": "Keen on NEET.", "interest": "interested"}'))
    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=FakeDialer(db, telephony_setup))
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).one()
    assert recipient.result["interest"] == "interested"
    assert recipient.result["summary"] == "Keen on NEET."


def test_lead_disposition_overrides_extracted_interest(db: Session, telephony_setup):
    from app.models.lead import Lead
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500121\n")
    call = _campaign_call(db, telephony_setup, campaign)
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).one()
    lead = Lead(client_id=telephony_setup["client"].id, name="Priya", phone=recipient.phone, call_disposition="CALLBACK_REQUESTED")
    db.add(lead)
    db.flush()
    recipient.lead_id = lead.id
    call.metadata_ = {**call.metadata_, "interest": "not_interested"}
    db.commit()

    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=FakeDialer(db, telephony_setup))
    db.refresh(recipient)
    assert recipient.result["interest"] == "callback"


def test_do_not_call_interest_adds_number_to_do_not_call_list(db: Session, telephony_setup):
    from app.models.campaign import DoNotCallEntry
    campaign = _running(db, telephony_setup, csv_text="phone\n9876500131\n")
    call = _campaign_call(db, telephony_setup, campaign)
    call.metadata_ = {**call.metadata_, "interest": "do_not_call"}
    db.commit()

    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=FakeDialer(db, telephony_setup))
    assert db.query(DoNotCallEntry).filter(DoNotCallEntry.phone == "+919876500131").count() == 1
