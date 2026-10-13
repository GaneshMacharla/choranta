"""
Client number buying: verify the business once (admin approves) -> pick a number -> pay setup fee + first
month -> number is READY_TO_TEST -> assign an AI employee -> test call to the client's phone -> ACTIVE.
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.billing import WalletTransaction
from app.models.call import Call
from app.models.notification import ClientNotification
from app.models.phone_number import PhoneNumber
from app.runtime.providers.registry import default_registry
from app.services import billing
from test_billing import company  # noqa: F401
from test_e2e_onboarding_outbound import FakeExotel
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

PDF = b"%PDF-1.4\n%test document\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
DETAILS = {
    "legal_name": "Smile Dental Care Pvt Ltd", "pan": "abcde1234f", "gstin": "36ABCDE1234F1Z5",
    "registered_address": "Plot 12, KPHB Colony, Kukatpally, Hyderabad 500072",
    "signatory_name": "Ganesh Macharla", "signatory_designation": "Director", "signatory_phone": "+919876500000",
}


def _files(**overrides):
    files = {"pan_card": ("pan.pdf", PDF), "gst_certificate": ("gst.pdf", PDF),
             "address_proof": ("bill.png", PNG), "signatory_id": ("aadhaar.pdf", PDF)}
    files.update(overrides)
    return {k: (v[0], io.BytesIO(v[1]), "application/octet-stream") for k, v in files.items() if v is not None}


@pytest.fixture
def kyc_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KYC_UPLOAD_DIR", str(tmp_path / "kyc"), raising=False)
    return tmp_path


@pytest.fixture
def portal(client: TestClient, auth_headers: dict, telephony_setup):
    cid = telephony_setup["client"].id
    return {"headers": _client_headers(client, auth_headers, cid, f"numbers-{cid}@clinic.example.com"), "client_id": cid}


def _verify(client, auth_headers, portal):
    resp = client.post("/api/portal/verification", headers=portal["headers"], data=DETAILS, files=_files())
    assert resp.status_code == 200, resp.text
    assert client.post(f"/api/verifications/{portal['client_id']}/approve", headers=auth_headers).status_code == 200


def test_verification_checks_and_review(client: TestClient, auth_headers: dict, operator_headers: dict, portal, db: Session, kyc_dir):
    h, cid = portal["headers"], portal["client_id"]
    assert client.get("/api/portal/verification", headers=h).json()["status"] == "NOT_STARTED"

    assert client.post("/api/portal/verification", headers=h, data={**DETAILS, "pan": "123"}, files=_files()).status_code == 422
    assert client.post("/api/portal/verification", headers=h, data={**DETAILS, "gstin": "36ZZZZZ9999Z1Z5"}, files=_files()).status_code == 422
    assert client.post("/api/portal/verification", headers=h, data=DETAILS, files=_files(address_proof=None)).status_code == 422
    assert client.post("/api/portal/verification", headers=h, data=DETAILS,
                       files=_files(pan_card=("pan.exe", b"MZ\x90\x00not a pdf"))).status_code == 422
    big = b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10)
    assert client.post("/api/portal/verification", headers=h, data=DETAILS, files=_files(pan_card=("big.pdf", big))).status_code == 422

    submitted = client.post("/api/portal/verification", headers=h, data=DETAILS, files=_files()).json()
    assert submitted["status"] == "PENDING" and submitted["pan"] == "ABCDE1234F" and len(submitted["documents"]) == 4
    assert "path" not in submitted["documents"][0]  # files never go back to the client

    # Admin queue, download, reject -> client fixes -> approve
    queue = client.get("/api/verifications", headers=operator_headers, params={"status": "PENDING"}).json()
    assert cid in [v["client_id"] for v in queue]
    doc = client.get(f"/api/verifications/{cid}/documents/0", headers=operator_headers)
    assert doc.status_code == 200 and doc.content.startswith(b"%PDF-")
    assert client.get(f"/api/verifications/{cid}/documents/0", headers=h).status_code == 403
    assert client.post(f"/api/verifications/{cid}/approve", headers=operator_headers).status_code == 403
    assert client.post(f"/api/verifications/{cid}/reject", headers=auth_headers, json={"note": "Address proof is blurry"}).status_code == 200
    assert client.get("/api/portal/verification", headers=h).json()["admin_note"] == "Address proof is blurry"

    resubmitted = client.post("/api/portal/verification", headers=h, data=DETAILS, files={"address_proof": ("new.png", io.BytesIO(PNG), "image/png")})
    assert resubmitted.status_code == 200 and resubmitted.json()["status"] == "PENDING"  # other documents kept
    assert client.post(f"/api/verifications/{cid}/approve", headers=auth_headers).json()["status"] == "APPROVED"
    kinds = {n.kind for n in db.query(ClientNotification).filter(ClientNotification.client_id == cid).all()}
    assert {"VERIFICATION_REJECTED", "VERIFICATION_APPROVED"} <= kinds


def test_buy_test_and_activate_number(client: TestClient, auth_headers: dict, portal, telephony_setup, db: Session,
                                      company, kyc_dir, monkeypatch):
    h, cid = portal["headers"], portal["client_id"]
    for name, value in {"TELEPHONY_BASE_URL": "https://choranta.example.com", "EXOTEL_FLOW_ID": "1234",
                        "EXOTEL_ACCOUNT_SID": "acct"}.items():
        monkeypatch.setattr(settings, name, value, raising=False)
    exotel = FakeExotel()
    provider = default_registry.get_telephony("exotel")
    monkeypatch.setattr(type(provider), "initiate_outbound_call", lambda self, **kwargs: exotel(self, **kwargs))

    # Setup fee set by the admin; the client has 1000 bought credits
    assert client.put("/api/number-pricing/Mobile", headers=auth_headers,
                      json={"monthly_rent_inr": 699, "setup_fee_inr": 199, "is_available": True}).status_code == 200
    billing.record_payment(db, cid, 1180, None, None)

    available = client.get("/api/portal/numbers/available", headers=h, params={"number_type": "Mobile"}).json()
    assert available and available[0]["setup_fee_inr"] == 199 and available[0]["due_now_inr"] == 898
    pick = available[0]["phone_number"]

    blocked = client.post("/api/portal/numbers", headers=h, json={"phone_number": pick, "number_type": "Mobile"})
    assert blocked.status_code == 403 and "Verify your business" in blocked.json()["error"]
    assert blocked.json()["details"]["code"] == "VERIFICATION_REQUIRED"

    _verify(client, auth_headers, portal)
    bought = client.post("/api/portal/numbers", headers=h, json={"phone_number": pick, "number_type": "Mobile"})
    assert bought.status_code == 201, bought.text
    number = bought.json()
    assert number["status"] == "READY_TO_TEST"
    assert billing.get_wallet(db, cid).balance_inr == pytest.approx(1000 - 699 - 199)
    notes = {t.note for t in db.query(WalletTransaction).filter(WalletTransaction.client_id == cid).all()}
    assert any(n and n.startswith("Number setup fee") for n in notes)
    # Not used for campaigns until tested
    from app.services.phone_numbers import client_caller_number
    assert client_caller_number(db, cid, pick) is None

    # Test needs an AI employee first
    assert client.post(f"/api/portal/numbers/{number['id']}/test", headers=h, json={"phone": "+919876500000"}).status_code == 422
    client.patch(f"/api/portal/numbers/{number['id']}", headers=h, json={"agent_id": telephony_setup["agent"].id})
    started = client.post(f"/api/portal/numbers/{number['id']}/test", headers=h, json={"phone": "+919876500000"})
    assert started.status_code == 200, started.text
    assert exotel.requests[-1]["caller_id"] == pick and exotel.requests[-1]["to"] == "+919876500000"
    call = db.get(Call, started.json()["test_call_id"])
    assert call.metadata_["number_test"] == number["id"] and call.metadata_["is_test"] is True

    # Carrier reports the test call connected -> number is Active
    status = client.post("/api/telephony/exotel/status", data={
        "CallSid": call.provider_call_id, "Status": "completed", "ConversationDuration": "12"})
    assert status.status_code == 200, status.text
    detail = client.get(f"/api/portal/numbers/{number['id']}", headers=h).json()
    assert detail["status"] == "ACTIVE" and detail["test_result"] == "CONNECTED" and detail["activated_by"] == "test_call"
    assert db.query(ClientNotification).filter(ClientNotification.client_id == cid, ClientNotification.kind == "NUMBER_ACTIVE").count() == 1


def test_skip_test_and_failed_test(client: TestClient, auth_headers: dict, portal, telephony_setup, db: Session):
    cid = portal["client_id"]
    pn = PhoneNumber(id=generate_unique_id("phn_"), client_id=cid, phone_number="+914071230000", provider="exotel",
                     provider_number_id="EXO_T", status="READY_TO_TEST", metadata_={})
    db.add(pn)
    db.commit()
    from app.services import phone_numbers
    failed_call = Call(id=generate_unique_id("call"), client_id=cid, agent_id=telephony_setup["agent"].id,
                       agent_version_id=telephony_setup["version"].id, direction="OUTBOUND", status="INITIATED", provider="exotel",
                       provider_call_id=generate_unique_id("exo"), caller_number=pn.phone_number, destination_number="+919876500000",
                       metadata_={"number_test": pn.id})
    db.add(failed_call)
    db.commit()
    phone_numbers.record_test_result(db, failed_call, connected=False, reason="NO-ANSWER")
    db.refresh(pn)
    assert pn.status == "READY_TO_TEST" and pn.metadata_["test_result"] == "NO-ANSWER"

    activated = client.post(f"/api/portal/numbers/{pn.id}/activate", headers=portal["headers"]).json()
    assert activated["status"] == "ACTIVE" and activated["activated_by"] == "skipped_test"


def test_admin_can_buy_without_client_verification(client: TestClient, auth_headers: dict, telephony_setup, db: Session, company):
    cid = telephony_setup["client"].id
    billing.record_payment(db, cid, 2360, None, None)
    available = client.get(f"/api/clients/{cid}/numbers/available", headers=auth_headers, params={"number_type": "Landline"}).json()
    resp = client.post(f"/api/clients/{cid}/numbers/buy", headers=auth_headers,
                       json={"phone_number": available[0]["phone_number"], "number_type": "Landline"})
    assert resp.status_code == 201, resp.text
