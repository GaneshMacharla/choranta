"""
Business verification: the client picks Individual or Business, types their documents' numbers in the portal, and
Choranta has Vobiz check each one on the client's own sub-account. Runs against the simulated carrier, where a PAN
whose digits are 0000 fails.
"""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.client import Client
from app.models.notification import ClientNotification
from app.models.numbers import CarrierSubaccount
from app.models.verification import ClientVerification
from app.runtime.providers.numbers.vobiz import VobizNumberProvider
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

V = "/api/portal/verification"
RETURN_URL = f"{settings.CORS_ORIGINS[0]}/portal/verification?digilocker=1"


@pytest.fixture
def portal(client: TestClient, auth_headers: dict, telephony_setup):
    cid = telephony_setup["client"].id
    return {"headers": _client_headers(client, auth_headers, cid, f"kyc-{cid}@clinic.example.com"), "client_id": cid}


def test_business_verification_with_pan_and_gst(client: TestClient, operator_headers: dict, portal, db: Session):
    h, cid = portal["headers"], portal["client_id"]
    assert client.get(V, headers=h).json()["status"] == "NOT_STARTED"
    assert client.post(f"{V}/pan", headers=h, json={"pan": "ABCDE1234F"}).status_code == 422  # type first
    assert client.post(f"{V}/start", headers=h, json={"kyc_type": "TRUST", "email": "a@b.in"}).status_code == 422
    assert client.post(f"{V}/start", headers=h, json={"kyc_type": "BUSINESS", "email": "not-an-email"}).status_code == 422

    started = client.post(f"{V}/start", headers=h, json={"kyc_type": "business", "email": "owner@smile.in"})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "IN_PROGRESS" and started.json()["kyc_type"] == "BUSINESS"
    sub = db.query(CarrierSubaccount).filter(CarrierSubaccount.client_id == cid).one()
    assert sub.kyc_mode == "customer_use" and sub.business_type == "private_limited"

    # Format checked here; a personal PAN isn't a business's
    assert client.post(f"{V}/pan", headers=h, json={"pan": "12345"}).status_code == 422
    assert "personal PAN" in client.post(f"{V}/pan", headers=h, json={"pan": "ABCPE1234F"}).json()["error"]

    # Vobiz finds no record: shown as failed, can be retried
    failed = client.post(f"{V}/pan", headers=h, json={"pan": "ABCDE0000F"}).json()
    assert failed["checks"]["pan"]["status"] == "failed" and failed["checks"]["pan"]["message"]
    passed = client.post(f"{V}/pan", headers=h, json={"pan": "abcde1234f"}).json()
    assert passed["checks"]["pan"]["status"] == "verified" and passed["checks"]["pan"]["value"] == "ABCDE1234F"
    assert passed["status"] == "IN_PROGRESS"  # GSTIN or CIN still needed

    assert "different PAN" in client.post(f"{V}/gst", headers=h, json={"gstin": "36ZZZZZ9999Z1Z5"}).json()["error"]
    done = client.post(f"{V}/gst", headers=h, json={"gstin": "36ABCDE1234F1Z5"}).json()
    assert done["status"] == "VERIFIED" and done["calls_blocked"] is False
    assert db.query(ClientNotification).filter(ClientNotification.client_id == cid,
                                               ClientNotification.kind == "VERIFICATION_APPROVED").count() == 1

    # Done is done
    assert client.post(f"{V}/start", headers=h, json={"kyc_type": "INDIVIDUAL", "email": "owner@smile.in"}).status_code == 422
    # Staff see it, read-only
    listed = client.get("/api/verifications", headers=operator_headers, params={"status": "VERIFIED"}).json()
    assert cid in [v["client_id"] for v in listed]
    assert client.get("/api/verifications", headers=h).status_code == 403


def test_business_verification_with_cin(client: TestClient, portal):
    h = portal["headers"]
    client.post(f"{V}/start", headers=h, json={"kyc_type": "BUSINESS", "email": "owner@smile.in"})
    client.post(f"{V}/pan", headers=h, json={"pan": "ABCDE1234F"})
    assert client.post(f"{V}/cin/search", headers=h, json={"company_name": "Fail Dental"}).json()["matches"] == []
    matches = client.post(f"{V}/cin/search", headers=h, json={"company_name": "Smile Dental"}).json()["matches"]
    assert matches[0]["cin"] and "SMILE DENTAL" in matches[0]["company_name"]
    assert client.post(f"{V}/cin", headers=h, json={"company_name": "Smile Dental", "cin": "nonsense"}).status_code == 422
    done = client.post(f"{V}/cin", headers=h, json={"company_name": matches[0]["company_name"], "cin": matches[0]["cin"]})
    assert done.json()["status"] == "VERIFIED" and done.json()["checks"]["cin"]["status"] == "verified"


def test_individual_verification_with_digilocker(client: TestClient, portal, db: Session):
    h, cid = portal["headers"], portal["client_id"]
    client.post(f"{V}/start", headers=h, json={"kyc_type": "INDIVIDUAL", "email": "owner@tutor.in"})
    assert client.post(f"{V}/gst", headers=h, json={"gstin": "36ABCDE1234F1Z5"}).status_code == 422  # Business only
    assert client.post(f"{V}/pan", headers=h, json={"pan": "ABCPE1234F"}).json()["status"] == "IN_PROGRESS"

    # DigiLocker only sends people back to Choranta's own pages
    assert client.post(f"{V}/aadhaar/start", headers=h, json={"return_url": "https://evil.example.com/x"}).status_code == 422
    started = client.post(f"{V}/aadhaar/start", headers=h, json={"return_url": RETURN_URL})
    assert started.status_code == 200, started.text
    state = parse_qs(urlparse(started.json()["auth_url"]).query)["state"][0]

    assert client.post(f"{V}/aadhaar/complete", headers=h, json={"state": "forged"}).status_code == 422
    done = client.post(f"{V}/aadhaar/complete", headers=h, json={"state": state}).json()
    assert done["status"] == "VERIFIED" and done["checks"]["aadhaar"]["status"] == "verified"
    # The DigiLocker session is used up
    assert client.post(f"{V}/aadhaar/complete", headers=h, json={"state": state}).status_code == 422


def test_type_can_change_until_something_is_verified(client: TestClient, portal, db: Session):
    h, cid = portal["headers"], portal["client_id"]
    client.post(f"{V}/start", headers=h, json={"kyc_type": "BUSINESS", "email": "owner@smile.in"})
    client.post(f"{V}/pan", headers=h, json={"pan": "ABCDE0000F"})  # failed, so nothing verified yet
    switched = client.post(f"{V}/start", headers=h, json={"kyc_type": "INDIVIDUAL", "email": "owner@smile.in"}).json()
    assert switched["kyc_type"] == "INDIVIDUAL" and switched["checks"] == {}
    assert db.query(CarrierSubaccount).filter(CarrierSubaccount.client_id == cid).one().business_type == "individual"

    client.post(f"{V}/pan", headers=h, json={"pan": "ABCPE1234F"})
    refused = client.post(f"{V}/start", headers=h, json={"kyc_type": "BUSINESS", "email": "owner@smile.in"})
    assert refused.status_code == 422 and "already verified" in refused.json()["error"]


def test_record_outlives_the_client(client: TestClient, portal, db: Session):
    h, cid = portal["headers"], portal["client_id"]
    client.post(f"{V}/start", headers=h, json={"kyc_type": "BUSINESS", "email": "owner@smile.in"})
    name = db.get(Client, cid).name
    db.execute(ClientVerification.__table__.update().where(ClientVerification.client_id == cid).values(client_id=None))
    db.commit()  # what ON DELETE SET NULL does when the client goes
    kept = db.query(ClientVerification).filter(ClientVerification.client_name == name).one()
    assert kept.email == "owner@smile.in"


def test_vobiz_test_values_skip_format_checks_only_against_vobiz(monkeypatch):
    from app.services import verifications
    monkeypatch.setattr(settings, "VOBIZ_KYC_TEST_MODE", True)
    assert not verifications._test_inputs()  # the simulated carrier has its own rules
    monkeypatch.setattr(settings, "PHONE_NUMBER_MOCK_MODE", False)
    assert verifications._test_inputs()
    monkeypatch.setattr(settings, "VOBIZ_KYC_TEST_MODE", False)
    assert not verifications._test_inputs()


def test_vobiz_kyc_adapter_paths_and_results(monkeypatch):
    seen = []
    replies = {
        "verify-pan": {"verification_type": "pan", "status": "verified", "registered_name": "ACME PRIVATE LIMITED",
                       "kyc_calls_blocked": True},
        "verify-gst": {"verification_type": "gst", "status": "pending", "legal_name": "ACME PRIVATE LIMITED"},
        "search": {"matches": [{"cin": "U72900KA2024PTC123456", "company_name": "ACME PRIVATE LIMITED", "status": "Active"}]},
        "initiate": {"auth_url": "https://api.digitallocker.gov.in/x", "access_request_id": "AR_1"},
        "status": {"overall_status": "verified", "kyc_calls_blocked": False, "verifications": {"pan": "verified", "gst": "verified"}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = next(k for k in replies if request.url.path.endswith(k))
        return httpx.Response(200, json=replies[key])

    adapter = VobizNumberProvider(auth_id="MA_TEST", auth_token="t", base_url="https://api.vobiz.ai/api/v1",
                                  transport=httpx.MockTransport(handler))
    pan = adapter.kyc_verify_pan("SA_1", "ABCDE1234F")
    assert (pan.status, pan.calls_blocked, pan.name) == ("verified", True, "ACME PRIVATE LIMITED")
    assert str(seen[-1].url) == "https://api.vobiz.ai/api/v1/sub-accounts/SA_1/kyc/verify-pan"
    assert seen[-1].headers["X-Auth-ID"] == "MA_TEST"  # KYC is driven as the parent
    gst = adapter.kyc_verify_gst("SA_1", "29AAJCN5983D1Z0")
    assert gst.status == "pending" and gst.calls_blocked is None
    assert adapter.kyc_cin_search("SA_1", "Acme")[0]["cin"] == "U72900KA2024PTC123456"
    assert adapter.kyc_digilocker_initiate("SA_1", "https://app/x", "st")["access_request_id"] == "AR_1"
    assert json.loads(seen[-1].content) == {"redirect_url": "https://app/x", "oauth_state": "st"}
    status = adapter.kyc_status("SA_1")
    assert status.calls_blocked is False and status.checks["gst"] == "verified"

    # Test mode uses Vobiz's mock endpoints for the checks
    monkeypatch.setattr(settings, "VOBIZ_KYC_TEST_MODE", True)
    adapter.kyc_verify_pan("SA_1", "TESTSUCCESS0001")
    assert str(seen[-1].url) == "https://api.vobiz.ai/api/v1/sub-accounts/test/SA_1/kyc/verify-pan"
