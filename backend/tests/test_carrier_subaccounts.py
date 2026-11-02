"""Each client's Vobiz sub-account: created on their first number, holding their numbers, placing their calls."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import secrets_box
from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.client import Client
from app.models.numbers import CarrierSubaccount, NumberOperation, ProviderNumber
from app.runtime.providers.numbers import ProviderValidationError
from app.runtime.providers.numbers.mock import MockNumberProvider
from app.runtime.providers.numbers.vobiz import VobizNumberProvider
from app.services import billing, carrier_subaccounts
from test_number_service import API, _owned
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture(autouse=True)
def subaccounts_on(monkeypatch):
    monkeypatch.setattr(settings, "VOBIZ_SUBACCOUNTS_ENABLED", True)


def _assign(client: TestClient, headers: dict, number_id: str, client_id: str):
    return client.post(f"{API}/{number_id}/assign", headers=headers, json={"client_id": client_id})


def test_first_number_creates_the_clients_subaccount(client: TestClient, auth_headers: dict, operator_headers: dict,
                                                     db: Session, telephony_setup):
    cid = telephony_setup["client"].id
    first, second = _owned(client, auth_headers), _owned(client, auth_headers)
    assert _assign(client, operator_headers, first["id"], cid).status_code == 200

    sub = db.query(CarrierSubaccount).filter(CarrierSubaccount.client_id == cid).one()
    assert sub.auth_id.startswith("SA_MOCK") and sub.kyc_mode == "personal_use" and sub.is_mock
    assert secrets_box.decrypt(sub.auth_token_enc)  # token kept, encrypted
    assert db.get(ProviderNumber, first["id"]).subaccount_auth_id == sub.auth_id

    # The client's next number joins the same sub-account
    assert _assign(client, operator_headers, second["id"], cid).status_code == 200
    assert db.query(CarrierSubaccount).filter(CarrierSubaccount.client_id == cid).count() == 1
    assert db.get(ProviderNumber, second["id"]).subaccount_auth_id == sub.auth_id
    kinds = [op.operation_type for op in db.query(NumberOperation).filter(NumberOperation.client_id == cid)]
    assert kinds.count("CREATE_SUBACCOUNT") == 1 and kinds.count("ASSIGN_SUBACCOUNT") == 2

    # Unassigning moves it back to Choranta's main account
    assert client.post(f"{API}/{first['id']}/unassign", headers=operator_headers).status_code == 200
    db.expire_all()
    assert db.get(ProviderNumber, first["id"]).subaccount_auth_id is None


def test_cool_off_keeps_a_number_from_another_client(client: TestClient, auth_headers: dict, operator_headers: dict,
                                                     db: Session, telephony_setup, monkeypatch):
    cid = telephony_setup["client"].id
    number = _owned(client, auth_headers)
    assert _assign(client, operator_headers, number["id"], cid).status_code == 200
    held_in = db.get(ProviderNumber, number["id"]).subaccount_auth_id

    def cool_off(self, e164):
        raise ProviderValidationError("Vobiz: did_cool_off_in_effect", provider_code="did_cool_off_in_effect",
                                      details={"cool_off_until": "2026-11-12T10:00:00Z"})
    monkeypatch.setattr(MockNumberProvider, "unassign_subaccount", cool_off)

    # The client loses it, but it stays in their sub-account and staff are told why
    assert client.post(f"{API}/{number['id']}/unassign", headers=operator_headers).status_code == 200
    db.expire_all()
    pn = db.get(ProviderNumber, number["id"])
    assert pn.internal_status == "AVAILABLE" and pn.subaccount_auth_id == held_in and "2026-11-12" in pn.attention

    other = Client(id=generate_unique_id("cli_"), name="Second Clinic", business_type="CLINIC")
    db.add(other)
    db.commit()
    refused = _assign(client, operator_headers, number["id"], other.id)
    assert refused.status_code == 409 and refused.json()["code"] == "subaccount_cool_off"
    assert client.post(f"{API}/{number['id']}/release", headers=auth_headers,
                       json={"confirm_e164": number["e164"], "idempotency_key": "cool-off-release"}).json()["code"] \
        == "subaccount_cool_off"

    # The same client can have it back
    assert _assign(client, operator_headers, number["id"], cid).status_code == 200


def test_a_subaccount_adds_no_lines_of_its_own(client: TestClient, auth_headers: dict, operator_headers: dict,
                                               db: Session, telephony_setup, monkeypatch):
    # Sub-accounts share the main account's pool, so the client's limit doesn't change with one
    cid = telephony_setup["client"].id
    monkeypatch.setattr(billing, "_wallet_or_plan_limit", lambda db, client_id: 10)
    _assign(client, operator_headers, _owned(client, auth_headers)["id"], cid)
    assert billing.client_concurrency_limit(db, cid) == 10


def test_real_numbers_call_from_their_subaccount(db: Session, telephony_setup):
    cid = telephony_setup["client"].id
    db.add(CarrierSubaccount(client_id=cid, provider="vobiz", auth_id="SA_REAL1", auth_token_enc=secrets_box.encrypt("tok"),
                             kyc_mode="personal_use", is_mock=False))
    db.add(ProviderNumber(provider="vobiz", e164="+918069990001", internal_status="ASSIGNED",
                          subaccount_auth_id="SA_REAL1", is_mock=False))
    db.add(ProviderNumber(provider="vobiz", e164="+918069990002", internal_status="ASSIGNED", is_mock=False))
    db.commit()
    assert carrier_subaccounts.caller_credentials(db, "+918069990001") == ("SA_REAL1", "tok")
    assert carrier_subaccounts.caller_credentials(db, "+918069990002") is None  # still on the main account


def test_dials_are_spaced_across_the_whole_account(monkeypatch):
    # Every client's calls share the account's CPS, sub-account or not
    waits = []
    monkeypatch.setattr(settings, "VOBIZ_CPS", 1.0)
    monkeypatch.setattr(carrier_subaccounts.time, "sleep", waits.append)
    monkeypatch.setattr(carrier_subaccounts, "_next_slot", 0.0)
    for _ in range(3):
        carrier_subaccounts.wait_for_dial_slot()
    assert len(waits) == 2 and 0.9 < waits[0] <= 1.0 and 1.9 < waits[1] <= 2.0


def test_subaccounts_are_off_by_default():
    assert type(settings).model_fields["VOBIZ_SUBACCOUNTS_ENABLED"].default is False


def test_vobiz_adapter_creates_a_subaccount():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={
            "message": "Sub-account created successfully",
            "sub_account": {"auth_id": "SA_NEW", "auth_token": "secret", "kyc_mode": "personal_use"},
            "auth_credentials": {"auth_id": "SA_NEW", "auth_token": "secret"},
        })

    adapter = VobizNumberProvider(auth_id="MA_TEST", auth_token="t", base_url="https://api.vobiz.ai/api/v1",
                                  transport=httpx.MockTransport(handler))
    created = adapter.create_subaccount(name="Sunrise Coaching", email="owner@sunrise.in", phone="+919800000000",
                                        description="Choranta client CH-0001", kyc_mode="personal_use")
    assert (created.auth_id, created.auth_token, created.kyc_mode) == ("SA_NEW", "secret", "personal_use")
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://api.vobiz.ai/api/v1/accounts/MA_TEST/sub-accounts/"
    body = json.loads(request.content)
    assert body["kyc_mode"] == "personal_use" and body["email"] == "owner@sunrise.in" and "password" not in body
