"""
Client number buying: verify the business once (Vobiz checks the documents) -> pick a number -> pay setup fee + first
month -> number is READY_TO_TEST -> assign an AI employee -> test call to the client's phone -> ACTIVE.
"""
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.billing import WalletTransaction
from app.models.call import Call
from app.models.notification import ClientNotification
from app.models.numbers import CarrierSubaccount, ProviderNumber
from app.models.phone_number import PhoneNumber
from app.services import billing
from test_billing import company  # noqa: F401
from test_vobiz_telephony import vobiz_carrier  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers


@pytest.fixture
def portal(client: TestClient, auth_headers: dict, telephony_setup):
    cid = telephony_setup["client"].id
    return {"headers": _client_headers(client, auth_headers, cid, f"numbers-{cid}@clinic.example.com"), "client_id": cid}


def _verify(client, portal):
    h = portal["headers"]
    assert client.post("/api/portal/verification/start", headers=h,
                       json={"kyc_type": "BUSINESS", "email": "owner@smile.in"}).status_code == 200
    client.post("/api/portal/verification/pan", headers=h, json={"pan": "ABCDE1234F"})
    done = client.post("/api/portal/verification/gst", headers=h, json={"gstin": "36ABCDE1234F1Z5"})
    assert done.json()["status"] == "VERIFIED", done.text


def test_buy_test_and_activate_number(client: TestClient, auth_headers: dict, portal, telephony_setup, db: Session,
                                      company, vobiz_carrier):
    h, cid = portal["headers"], portal["client_id"]

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

    _verify(client, portal)
    bought = client.post("/api/portal/numbers", headers=h, json={"phone_number": pick, "number_type": "Mobile"})
    assert bought.status_code == 201, bought.text
    number = bought.json()
    assert number["status"] == "READY_TO_TEST"
    # It sits in the client's own (KYC'd) Vobiz sub-account
    sub = db.query(CarrierSubaccount).filter(CarrierSubaccount.client_id == cid).one()
    assert db.query(ProviderNumber).filter(ProviderNumber.e164 == pick).one().subaccount_auth_id == sub.auth_id
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
    # The number was bought on Vobiz, so its test call goes out through Vobiz with it as caller ID
    assert vobiz_carrier[-1]["from"] == pick and vobiz_carrier[-1]["to"] == "+919876500000"
    call = db.get(Call, started.json()["test_call_id"])
    assert call.metadata_["number_test"] == number["id"] and call.metadata_["is_test"] is True

    # Carrier reports the test call connected -> number is Active
    hangup = urlparse(vobiz_carrier[-1]["hangup_url"])
    status = client.post(f"{hangup.path}?{hangup.query}", data={
        "CallUUID": call.provider_call_id or "uuid-test", "CallStatus": "completed", "Duration": "12"})
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
