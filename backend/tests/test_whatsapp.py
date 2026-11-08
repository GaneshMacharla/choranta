import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.billing import WalletTransaction
from app.models.call import Call
from app.models.campaign import DoNotCallEntry
from app.models.notification import ClientNotification
from app.models.whatsapp import WhatsAppAccount, WhatsAppFollowup, WhatsAppMessage
from app.runtime.providers.messaging import MessagingError
from app.services import billing, whatsapp, whatsapp_followups
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

MESSAGE = "Hi {name}, thanks for your interest in {target_exam} coaching at {centre}. Fees are Rs 25,000 and the batch starts soon."
OUTPUTS = [{"name": "target_exam", "description": "Exam the student prepares for", "data_type": "string"}]


@pytest.fixture
def mock_whatsapp():
    provider = whatsapp.provider()
    provider.reset()
    yield provider
    provider.reset()


@pytest.fixture
def setup(db: Session, telephony_setup, mock_whatsapp):
    version = telephony_setup["version"]
    config = dict(version.configuration_json)
    config["variables"] = {**(config.get("variables") or {}), "outputs": OUTPUTS}
    version.configuration_json = config
    flag_modified(version, "configuration_json")
    db.commit()
    return telephony_setup


def _connect(db: Session, setup) -> WhatsAppAccount:
    return whatsapp.connect_account(db, setup["client"].id, "1111", "2222", "token-abc", app_secret="client-app-secret")


def _save(db: Session, setup, **kwargs) -> WhatsAppFollowup:
    args = {"enabled": True, "message": MESSAGE, "send_when": ["interested"]}
    args.update(kwargs)
    return whatsapp.save_followup(db, setup["client"].id, setup["agent"].id, **args)


def _call(db: Session, setup, interest="interested", **metadata) -> Call:
    call = Call(
        id=generate_unique_id("call_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
        agent_version_id=setup["version"].id, caller_number="+914045209348", destination_number="+919876543210",
        direction="OUTBOUND", status="COMPLETED", duration_seconds=60, provider="vobiz",
        provider_call_id=generate_unique_id("exo_"),
        metadata_={"interest": interest, "outputs": {"target_exam": "NEET"},
                   "variables": {"user_name": "Priya Sharma"}, **metadata},
    )
    db.add(call)
    db.commit()
    return call


def test_token_is_stored_encrypted(db: Session, setup):
    account = _connect(db, setup)
    assert "token-abc" not in account.access_token_enc
    assert whatsapp.credentials(account).access_token == "token-abc"
    assert account.display_phone and account.status == "ACTIVE"


def test_bad_token_is_refused(db: Session, setup):
    with pytest.raises(whatsapp.WhatsAppError):
        whatsapp.connect_account(db, setup["client"].id, "1111", "2222", "bad-token")
    assert whatsapp.get_account(db, setup["client"].id) is None


def test_message_becomes_template(db: Session, setup, mock_whatsapp):
    _connect(db, setup)
    followup = _save(db, setup)
    spec = mock_whatsapp.submitted[-1]
    assert spec.body.startswith("Hi {{1}}, thanks for your interest in {{2}} coaching at {{3}}.")
    assert followup.template_placeholders == ["name", "target_exam", "centre"]
    assert followup.template_status == "APPROVED" and followup.approved_template_name == spec.name


def test_saving_before_connecting_submits_on_connect(db: Session, setup, mock_whatsapp):
    followup = _save(db, setup)
    assert followup.template_status is None and not mock_whatsapp.submitted
    _connect(db, setup)
    db.refresh(followup)
    assert followup.template_status == "APPROVED"


@pytest.mark.parametrize("message", [
    "{name}, thanks for calling us today about the course details.",
    "Thanks for calling us today about the course, {name}.",
    "Hi {unknown_thing}, thanks for calling us today about the course.",
])
def test_invalid_messages_are_refused(db: Session, setup, message):
    with pytest.raises(whatsapp.WhatsAppError):
        _save(db, setup, message=message)


def test_edit_keeps_sending_approved_version_until_new_one_is_approved(db: Session, setup, mock_whatsapp):
    _connect(db, setup)
    first = _save(db, setup).approved_template_name
    mock_whatsapp.auto_approve = False
    followup = _save(db, setup, message=MESSAGE.replace("soon", "on Monday"))
    assert followup.template_status == "PENDING"
    assert followup.approved_template_name == first and followup.template_name != first


def test_interested_call_queues_and_sends_followup(db: Session, setup, mock_whatsapp):
    _connect(db, setup)
    _save(db, setup)
    call = _call(db, setup)
    message = whatsapp_followups.queue_for_call(db, call)
    assert message and message.status == "QUEUED"
    assert message.params == ["Priya Sharma", "NEET", "Downtown Medical Clinic"]
    assert "Hi Priya Sharma, thanks for your interest in NEET coaching" in message.body
    # Only one follow-up per call
    assert whatsapp_followups.queue_for_call(db, call) is None

    assert whatsapp_followups.deliver_due_messages(db) == 1
    db.refresh(message)
    assert message.status == "SENT" and message.wa_message_id
    assert mock_whatsapp.sent[-1]["to"] == "+919876543210"


@pytest.mark.parametrize("interest,metadata", [
    ("not_interested", {}),
    ("unclear", {}),
    ("interested", {"is_test": True}),
])
def test_no_followup_when_not_wanted(db: Session, setup, interest, metadata):
    _connect(db, setup)
    _save(db, setup)
    assert whatsapp_followups.queue_for_call(db, _call(db, setup, interest, **metadata)) is None


def test_no_followup_to_do_not_call_number(db: Session, setup):
    _connect(db, setup)
    _save(db, setup)
    db.add(DoNotCallEntry(client_id=setup["client"].id, phone="+919876543210"))
    db.commit()
    assert whatsapp_followups.queue_for_call(db, _call(db, setup)) is None


def test_no_followup_when_disabled_or_not_connected(db: Session, setup):
    _save(db, setup, enabled=False)
    _connect(db, setup)
    assert whatsapp_followups.queue_for_call(db, _call(db, setup)) is None


def test_callback_interest_when_chosen(db: Session, setup):
    _connect(db, setup)
    _save(db, setup, send_when=["interested", "callback"])
    assert whatsapp_followups.queue_for_call(db, _call(db, setup, "callback")) is not None


def test_temporary_failure_is_retried_permanent_is_not(db: Session, setup, mock_whatsapp):
    _connect(db, setup)
    _save(db, setup)
    message = whatsapp_followups.queue_for_call(db, _call(db, setup))
    mock_whatsapp.fail_next.append(MessagingError("Rate limited", code=130429, permanent=False))
    whatsapp_followups.deliver_due_messages(db)
    db.refresh(message)
    assert message.status == "QUEUED" and message.attempts == 1 and message.next_attempt_at

    mock_whatsapp.fail_next.append(MessagingError("Template does not exist", code=132001, permanent=True))
    whatsapp_followups.deliver_due_messages(db, now=message.next_attempt_at + timedelta(seconds=1))
    db.refresh(message)
    assert message.status == "FAILED" and "Template" in message.error


def test_rejected_token_pauses_account(db: Session, setup, mock_whatsapp):
    account = _connect(db, setup)
    _save(db, setup)
    message = whatsapp_followups.queue_for_call(db, _call(db, setup))
    mock_whatsapp.fail_next.append(MessagingError("Token expired", code=190, permanent=True, auth=True))
    whatsapp_followups.deliver_due_messages(db)
    db.refresh(message)
    db.refresh(account)
    assert message.status == "FAILED" and account.status == "INVALID"
    assert db.query(ClientNotification).filter(ClientNotification.client_id == setup["client"].id,
                                               ClientNotification.kind == "WHATSAPP_DISCONNECTED").count() == 1


def test_sent_message_is_billed_once(db: Session, setup, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True)
    _connect(db, setup)
    _save(db, setup)
    wallet = billing.get_wallet(db, setup["client"].id)
    wallet.balance_inr = 10.0
    db.commit()
    message = whatsapp_followups.queue_for_call(db, _call(db, setup))
    whatsapp_followups.deliver_due_messages(db)
    db.refresh(message)
    debits = db.query(WalletTransaction).filter(WalletTransaction.reference == f"whatsapp:{message.id}").all()
    assert len(debits) == 1 and debits[0].amount_inr < 0
    assert message.charged_credits == -debits[0].amount_inr
    assert billing.charge_message(db, setup["client"].id, message.id, 1.0, "again") == 0.0


def test_no_credits_skips_message(db: Session, setup, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True)
    _connect(db, setup)
    _save(db, setup)
    billing.get_wallet(db, setup["client"].id).balance_inr = 0.0
    db.commit()
    message = whatsapp_followups.queue_for_call(db, _call(db, setup))
    whatsapp_followups.deliver_due_messages(db)
    db.refresh(message)
    assert message.status == "SKIPPED"


def test_prompt_offers_whatsapp_only_when_live(db: Session, setup):
    assert whatsapp.prompt_line(db, setup["agent"].id) == ""
    _connect(db, setup)
    _save(db, setup)
    assert "WhatsApp" in whatsapp.prompt_line(db, setup["agent"].id)


# ---------------------------------------------------------------- webhook


def _signed(body: dict, secret: str):
    raw = json.dumps(body).encode()
    return raw, {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
                 "Content-Type": "application/json"}


def _messages_event(value: dict) -> dict:
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "1111", "changes": [{"field": "messages", "value": {
                "messaging_product": "whatsapp", "metadata": {"phone_number_id": "2222"}, **value}}]}]}


def test_webhook_rejects_bad_signature(client: TestClient, db: Session, setup):
    _connect(db, setup)
    raw, headers = _signed(_messages_event({}), "wrong-secret")
    assert client.post("/api/whatsapp/webhook", content=raw, headers=headers).status_code == 403


def test_webhook_verification(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_VERIFY_TOKEN", "verify-me")
    ok = client.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                     "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                                      "hub.challenge": "1"})
    assert bad.status_code == 403


def test_webhook_status_and_reply(client: TestClient, db: Session, setup):
    _connect(db, setup)
    _save(db, setup)
    message = whatsapp_followups.queue_for_call(db, _call(db, setup))
    whatsapp_followups.deliver_due_messages(db)
    db.refresh(message)

    for state in ("read", "delivered"):  # a late "delivered" mustn't undo "read"
        raw, headers = _signed(_messages_event({"statuses": [{"id": message.wa_message_id, "status": state}]}),
                               "client-app-secret")
        assert client.post("/api/whatsapp/webhook", content=raw, headers=headers).status_code == 200
    db.refresh(message)
    assert message.status == "READ"

    reply = {"contacts": [{"wa_id": "919876543210", "profile": {"name": "Priya"}}],
             "messages": [{"from": "919876543210", "id": "wamid.in1", "type": "text", "text": {"body": "What are the timings?"}}]}
    raw, headers = _signed(_messages_event(reply), "client-app-secret")
    client.post("/api/whatsapp/webhook", content=raw, headers=headers)
    client.post("/api/whatsapp/webhook", content=raw, headers=headers)  # Meta retries
    replies = db.query(WhatsAppMessage).filter(WhatsAppMessage.direction == "IN",
                                               WhatsAppMessage.client_id == setup["client"].id).all()
    assert len(replies) == 1 and replies[0].body == "What are the timings?"
    thread = whatsapp_followups.thread_for_call(db, setup["client"].id, message.call_id)
    assert [m["direction"] for m in thread] == ["OUT", "IN"]


def test_stop_reply_adds_do_not_call(client: TestClient, db: Session, setup):
    _connect(db, setup)
    reply = {"messages": [{"from": "919876543210", "id": "wamid.stop1", "type": "text", "text": {"body": "STOP"}}]}
    raw, headers = _signed(_messages_event(reply), "client-app-secret")
    client.post("/api/whatsapp/webhook", content=raw, headers=headers)
    assert db.query(DoNotCallEntry).filter(DoNotCallEntry.client_id == setup["client"].id,
                                           DoNotCallEntry.phone == "+919876543210").first()


def test_webhook_template_rejection(client: TestClient, db: Session, setup, mock_whatsapp):
    _connect(db, setup)
    mock_whatsapp.auto_approve = False
    followup = _save(db, setup)
    event = {"entry": [{"id": "1111", "changes": [{"field": "message_template_status_update", "value": {
        "event": "REJECTED", "message_template_name": followup.template_name, "reason": "PROMOTIONAL"}}]}]}
    raw, headers = _signed(event, "client-app-secret")
    client.post("/api/whatsapp/webhook", content=raw, headers=headers)
    db.refresh(followup)
    assert followup.template_status == "REJECTED" and "advert" in followup.template_detail
    assert followup.approved_template_name is None


# ---------------------------------------------------------------- portal API


def test_portal_connect_and_save(client: TestClient, auth_headers: dict, db: Session, setup):
    cid = setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"owner-{cid}@wa.example.com")
    overview = client.get("/api/portal/whatsapp", headers=headers)
    assert overview.status_code == 200 and overview.json()["account"]["connected"] is False
    keys = {p["key"] for p in overview.json()["followups"][0]["placeholders"]}
    assert {"name", "centre", "target_exam"} <= keys

    connected = client.put("/api/portal/whatsapp/account", headers=headers,
                           json={"waba_id": "1111", "phone_number_id": "2222", "access_token": "token-abc"})
    assert connected.status_code == 200, connected.text
    assert "token-abc" not in connected.text

    saved = client.put(f"/api/portal/whatsapp/followups/{setup['agent'].id}", headers=headers,
                       json={"message": MESSAGE, "send_when": ["interested"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["template_status"] == "APPROVED"

    bad = client.put(f"/api/portal/whatsapp/followups/{setup['agent'].id}", headers=headers,
                     json={"message": "{name}", "send_when": ["interested"]})
    assert bad.status_code == 422 or bad.status_code == 400


def test_extraction_queues_followup_for_inbound_agent_without_outputs(db: Session, telephony_setup, mock_whatsapp):
    """An agent with no output variables still gets its callers' interest worked out once follow-ups are on."""
    from app.services import call_outputs
    from test_call_outputs import FakeLLM, TURNS, _call_with_transcript

    setup = telephony_setup
    _connect(db, setup)
    _save(db, setup, message="Hi {name}, thanks for calling {centre}. Our team will share the full details with you here.")
    call = _call_with_transcript(db, setup, TURNS)
    call.direction, call.caller_number = "INBOUND", "+919876543210"
    db.commit()
    assert call_outputs.mark_pending(db, call) is True
    llm = FakeLLM(json.dumps({"outputs": {}, "summary": "Wants NEET coaching", "interest": "interested",
                              "callback_time": None}))
    call_outputs.run_extraction(db, call.id, llm=llm)
    sent = db.query(WhatsAppMessage).filter(WhatsAppMessage.call_id == call.id).one()
    assert sent.phone == "+919876543210" and sent.status == "QUEUED"
