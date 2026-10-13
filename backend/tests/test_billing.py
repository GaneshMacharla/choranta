from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.billing import ClientBillingProfile, Invoice, WalletTransaction
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.services import billing
from app.services.pricing import update_pricing
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def company(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_STATE_CODE", "36", raising=False)
    monkeypatch.setattr(settings, "GST_RATE_PERCENT", 18.0, raising=False)
    monkeypatch.setattr(settings, "INVOICE_PREFIX", "CHR", raising=False)


def _completed_call(db: Session, setup, duration=120, is_test=False) -> Call:
    session = RuntimeSession(
        id=generate_unique_id("ses_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
        agent_version_id=setup["version"].id, status="COMPLETED", metadata_={},
        usage_json={"stt_seconds": 30, "tts_seconds": 50, "llm_input_tokens": 4000, "llm_output_tokens": 150},
    )
    db.add(session)
    call = Call(
        id=generate_unique_id("call_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
        agent_version_id=setup["version"].id, runtime_session_id=session.id, caller_number="+914045209348",
        destination_number="+918008538015", direction="OUTBOUND", status="COMPLETED", duration_seconds=duration,
        provider="exotel", provider_call_id=generate_unique_id("exo_"), metadata_={"is_test": is_test},
    )
    db.add(call)
    db.commit()
    return call


def test_gst_split_intra_and_inter_state(company):
    same = billing.gst_split(11800, "36")
    assert (same["taxable_inr"], same["cgst_inr"], same["sgst_inr"], same["igst_inr"]) == (10000.0, 900.0, 900.0, 0.0)
    other = billing.gst_split(11800, "29")
    assert (other["taxable_inr"], other["igst_inr"], other["cgst_inr"]) == (10000.0, 1800.0, 0.0)


def test_record_payment_issues_sequential_invoices_and_credits_taxable_value(db: Session, telephony_setup, company):
    client_id = telephony_setup["client"].id
    db.add(ClientBillingProfile(client_id=client_id, legal_name="Downtown Medical Clinic Pvt Ltd", state_code="29"))
    db.commit()

    first = billing.record_payment(db, client_id, 11800, "UTR123", None, issue_date=date(2026, 10, 12))
    second = billing.record_payment(db, client_id, 5900, "UTR124", None, issue_date=date(2026, 10, 13))
    assert first["invoice_number"].endswith("/2026-27/" + first["invoice_number"][-4:])
    assert int(second["invoice_number"][-4:]) == int(first["invoice_number"][-4:]) + 1
    assert first["igst_inr"] == 1800.0  # Karnataka client, Telangana company
    assert billing.get_wallet(db, client_id).balance_inr == 15000.0

    # A new financial year restarts numbering
    april = billing.record_payment(db, client_id, 1180, None, None, issue_date=date(2027, 4, 1))
    assert april["invoice_number"].startswith("CHR/2027-28/")


def test_call_is_charged_once_and_test_calls_are_free(db: Session, telephony_setup, company):
    client_id = telephony_setup["client"].id
    update_pricing(db, 40.0, None)
    billing.record_payment(db, client_id, 1180, None, None)  # Rs 1000 wallet
    call = _completed_call(db, telephony_setup)

    txn = billing.charge_call(db, call)
    assert txn is not None and txn.amount_inr < 0
    assert billing.charge_call(db, call) is None  # idempotent
    assert db.query(WalletTransaction).filter(WalletTransaction.call_id == call.id).count() == 1
    assert billing.get_wallet(db, client_id).balance_inr == pytest.approx(1000 + txn.amount_inr)

    test_call = _completed_call(db, telephony_setup, is_test=True)
    assert billing.charge_call(db, test_call) is None


def test_calls_blocked_when_wallet_empty(client: TestClient, auth_headers: dict, telephony_setup, db: Session, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True, raising=False)
    monkeypatch.setattr(settings, "TELEPHONY_BASE_URL", "https://choranta.example.com", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_CALLER_ID", "04045209348", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_FLOW_ID", "1", raising=False)
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "acct", raising=False)
    body = {"agent_id": telephony_setup["agent"].id, "agent_version_id": telephony_setup["version"].id,
            "destination_number": "09876543210"}

    blocked = client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body)
    assert blocked.status_code == 402 and "out of credits" in blocked.json()["detail"]
    # Test calls from the Tests step are never blocked
    assert client.post("/api/telephony/calls/outbound", headers=auth_headers, json={**body, "is_test": True}).status_code == 201

    # Inbound calls on an empty wallet get the reject response
    resp = client.get("/api/telephony/exotel/inbound", params={
        "CallSid": "CA_BLOCKED_1", "CallFrom": "09876543210", "CallTo": telephony_setup["phone_number"].phone_number})
    assert resp.json()["url"] == ""

    client.post(f"/api/clients/{telephony_setup['client'].id}/wallet/payments", headers=auth_headers,
                json={"amount_received_inr": 1180, "reference": "UTR9"})
    assert client.post("/api/telephony/calls/outbound", headers=auth_headers, json=body).status_code == 201


def test_admin_billing_api_and_invoice_pdf(client: TestClient, auth_headers: dict, operator_headers: dict, telephony_setup, company):
    cid = telephony_setup["client"].id
    profile = {"legal_name": "Downtown Medical Clinic Pvt Ltd", "gstin": "36abcde1234f1z5", "state_code": "36"}
    assert client.put(f"/api/clients/{cid}/billing-profile", headers=operator_headers, json=profile).status_code == 403
    saved = client.put(f"/api/clients/{cid}/billing-profile", headers=auth_headers, json=profile).json()
    assert saved["gstin"] == "36ABCDE1234F1Z5"

    preview = client.post(f"/api/clients/{cid}/wallet/payments/preview", headers=auth_headers, json={"amount_received_inr": 11800}).json()
    assert (preview["cgst_inr"], preview["sgst_inr"]) == (900.0, 900.0)

    paid = client.post(f"/api/clients/{cid}/wallet/payments", headers=auth_headers, json={"amount_received_inr": 11800, "reference": "UTR1"})
    assert paid.status_code == 201
    wallet = client.get(f"/api/clients/{cid}/wallet", headers=operator_headers).json()
    assert wallet["balance_inr"] == 10000.0 and wallet["transactions"][0]["type"] == "CREDIT"

    adj = client.post(f"/api/clients/{cid}/wallet/adjustments", headers=auth_headers, json={"amount_inr": -500, "note": "Refund"}).json()
    assert adj["balance_inr"] == 9500.0

    invoices = client.get(f"/api/clients/{cid}/invoices", headers=auth_headers).json()
    pdf = client.get(f"/api/invoices/{invoices[0]['id']}/pdf", headers=auth_headers)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
