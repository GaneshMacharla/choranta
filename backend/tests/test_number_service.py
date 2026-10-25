"""Number management against the simulated carrier: search, buy, recover, assign, sync, release. No network."""
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.core.security import generate_unique_id
from app.db.session import Base
from app.models.client import Client
from app.models.numbers import MockCarrierNumber, NumberAssignment, NumberOperation, ProviderNumber
from app.models.phone_number import PhoneNumber
from app.repositories.phone_number_repository import PhoneNumberRepository
from app.runtime.providers.numbers.mock import MockNumberProvider
from app.services import number_reconciliation, number_service
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers

API = "/api/numbers"


def _key() -> str:
    return f"test-{uuid.uuid4().hex}"


def _listing(client: TestClient, headers: dict, e164: str) -> dict:
    items = client.get(f"{API}/inventory", headers=headers, params={"search": e164.lstrip("+"), "per_page": 100}).json()["items"]
    return next(i for i in items if i["e164"] == e164)


def _buy(client: TestClient, headers: dict, e164: str, key: str = None, **extra):
    item = _listing(client, headers, e164) if "expected_monthly_cost" not in extra else {}
    body = {"e164": e164, "idempotency_key": key or _key(), "confirm": True,
            "expected_monthly_cost": item.get("monthly_fee"), "expected_setup_cost": item.get("setup_fee"), **extra}
    return client.post(f"{API}/purchase", headers=headers, json=body)


def _first(client: TestClient, headers: dict, **params) -> str:
    items = client.get(f"{API}/inventory", headers=headers, params={"per_page": 100, **params}).json()["items"]
    return next(i["e164"] for i in items if not i["scenario"])


# ---------------------------------------------------------------- inventory

def test_inventory_search_filters_and_pages(client: TestClient, auth_headers: dict):
    everything = client.get(f"{API}/inventory", headers=auth_headers, params={"per_page": 100}).json()
    assert everything["mock_mode"] is True and everything["total"] >= 40
    assert all(i["is_mock"] and i["currency"] == "INR" and i["monthly_fee"] is not None for i in everything["items"])

    toll_free = client.get(f"{API}/inventory", headers=auth_headers, params={"number_type": "TollFree"}).json()["items"]
    assert toll_free and all(i["e164"].startswith("+911800") and i["number_type"] == "TollFree" for i in toll_free)
    hyderabad = client.get(f"{API}/inventory", headers=auth_headers, params={"search": "4071", "per_page": 100}).json()["items"]
    assert hyderabad and all("4071" in i["e164"] for i in hyderabad)
    karnataka = client.get(f"{API}/inventory", headers=auth_headers, params={"region": "karnataka", "per_page": 100}).json()["items"]
    assert karnataka and all(i["region"] == "Karnataka" for i in karnataka)
    us = client.get(f"{API}/inventory", headers=auth_headers, params={"country": "US"}).json()["items"]
    assert us and all(i["country"] == "US" for i in us)

    first, second = (client.get(f"{API}/inventory", headers=auth_headers, params={"per_page": 5, "page": p}).json() for p in (1, 2))
    assert len(first["items"]) == 5 and not {i["e164"] for i in first["items"]} & {i["e164"] for i in second["items"]}
    scenario = next(i for i in everything["items"] if i["e164"] == "+918040000402")
    assert "insufficient" in scenario["scenario"].lower()
    assert client.get(f"{API}/inventory", headers=auth_headers, params={"number_type": "Fax"}).status_code == 422


# ---------------------------------------------------------------- buying

def test_buy_a_number(client: TestClient, auth_headers: dict, db: Session):
    e164 = _first(client, auth_headers)
    bought = _buy(client, auth_headers, e164)
    assert bought.status_code == 200, bought.text
    body = bought.json()
    assert body["operation"]["operation_status"] == "SUCCEEDED" and body["operation"]["is_mock"] is True
    number = body["number"]
    assert number["e164"] == e164 and number["internal_status"] == "AVAILABLE" and number["provider_status"] == "active"
    assert number["application_id"] == "mock_app_choranta" and number["monthly_cost"] is not None

    listed = client.get(API, headers=auth_headers).json()
    assert e164 in [n["e164"] for n in listed["items"]]
    assert e164 not in [i["e164"] for i in client.get(f"{API}/inventory", headers=auth_headers, params={"per_page": 100}).json()["items"]]
    detail = client.get(f"{API}/{number['id']}", headers=auth_headers).json()
    assert sorted(o["operation_type"] for o in detail["operations"]) == ["ATTACH_APP", "PURCHASE"]
    assert _buy(client, auth_headers, e164, expected_monthly_cost=None).json()["code"] == "already_owned"


def test_the_same_request_never_buys_twice(client: TestClient, auth_headers: dict, db: Session):
    e164 = _first(client, auth_headers)
    key = _key()
    first = _buy(client, auth_headers, e164, key).json()
    again = client.post(f"{API}/purchase", headers=auth_headers, json={"e164": e164, "idempotency_key": key, "confirm": True})
    assert again.status_code == 200 and again.json()["operation"]["id"] == first["operation"]["id"]
    assert db.query(ProviderNumber).filter(ProviderNumber.e164 == e164).count() == 1
    other = _first(client, auth_headers)
    reused = client.post(f"{API}/purchase", headers=auth_headers, json={"e164": other, "idempotency_key": key, "confirm": True})
    assert reused.status_code == 409 and reused.json()["code"] == "idempotency_key_reused"


def test_purchase_needs_confirmation_and_the_confirmed_price(client: TestClient, auth_headers: dict):
    e164 = _first(client, auth_headers)
    unconfirmed = client.post(f"{API}/purchase", headers=auth_headers, json={"e164": e164, "idempotency_key": _key(), "confirm": False})
    assert unconfirmed.status_code == 400 and unconfirmed.json()["code"] == "confirmation_required"
    stale = _buy(client, auth_headers, e164, expected_monthly_cost=1.0, expected_setup_cost=0.0)
    assert stale.status_code == 409 and stale.json()["code"] == "price_changed"
    assert stale.json()["details"]["monthly_fee"] is not None
    assert client.post(f"{API}/purchase", headers=auth_headers,
                       json={"e164": "080400001", "idempotency_key": _key(), "confirm": True}).status_code == 400


@pytest.mark.parametrize("e164,status,code", [
    ("+918040000402", 402, "insufficient_balance"),
    ("+918040000404", 409, "number_unavailable"),
    ("+918040000401", 502, "provider_auth_failed"),
])
def test_carrier_refusals_are_recorded_and_shown(client: TestClient, auth_headers: dict, db: Session, e164, status, code):
    refused = _buy(client, auth_headers, e164)
    assert refused.status_code == status and refused.json()["code"] == code
    op = refused.json()["operation"]
    assert op["operation_status"] == "FAILED" and op["error_message"]
    assert db.query(ProviderNumber).filter(ProviderNumber.e164 == e164).count() == 0


def test_timeout_without_purchase_is_settled_as_not_bought(client: TestClient, auth_headers: dict, db: Session):
    result = _buy(client, auth_headers, "+918040000408").json()
    assert result["operation"]["operation_status"] == "FAILED" and result["operation"]["error_code"] == "not_purchased"
    assert result["number"] is None
    # Settled, so buying it can be tried again (never automatically)
    assert db.query(NumberOperation).filter(NumberOperation.e164 == "+918040000408",
                                            NumberOperation.operation_status.in_(number_service.OPEN_STATUSES)).count() == 0


def test_timeout_that_did_buy_is_recovered(client: TestClient, auth_headers: dict, db: Session):
    result = _buy(client, auth_headers, "+918040000409").json()
    assert result["operation"]["operation_status"] == "RECOVERED"
    assert result["number"]["e164"] == "+918040000409" and result["number"]["internal_status"] == "AVAILABLE"


def test_unknown_outcome_stays_uncertain_until_checked(client: TestClient, auth_headers: dict, db: Session, monkeypatch):
    # The carrier can't tell us yet: not listed as ours, not listed for sale
    real_get, real_search = MockNumberProvider.get_owned, MockNumberProvider.search_inventory
    monkeypatch.setattr(MockNumberProvider, "get_owned", lambda self, e164: None)
    listing = _listing(client, auth_headers, "+918040000409")
    calls = {"n": 0}

    def search(self, **kw):
        calls["n"] += 1
        page = real_search(self, **kw)
        if calls["n"] > 1:  # the first search is the pre-purchase check
            page.items = []
        return page
    monkeypatch.setattr(MockNumberProvider, "search_inventory", search)
    result = client.post(f"{API}/purchase", headers=auth_headers, json={
        "e164": "+918040000409", "idempotency_key": _key(), "confirm": True,
        "expected_monthly_cost": listing["monthly_fee"], "expected_setup_cost": listing["setup_fee"]}).json()
    op = result["operation"]
    assert op["operation_status"] == "UNCERTAIN"

    blocked = _buy(client, auth_headers, "+918040000409", expected_monthly_cost=None)
    assert blocked.status_code == 409 and blocked.json()["code"] == "purchase_in_progress"

    monkeypatch.setattr(MockNumberProvider, "get_owned", real_get)
    monkeypatch.setattr(MockNumberProvider, "search_inventory", real_search)
    checked = client.post(f"{API}/operations/{op['id']}/reconcile", headers=auth_headers).json()
    assert checked["operation"]["operation_status"] == "RECOVERED" and checked["number"]["e164"] == "+918040000409"
    uncertain = client.get(f"{API}/operations", headers=auth_headers, params={"status": "UNCERTAIN"}).json()
    assert op["id"] not in [o["id"] for o in uncertain["items"]]


def test_save_failing_after_the_carrier_bought_is_recoverable(tmp_path, monkeypatch):
    """Needs real commits (the shared test session rolls everything back), so it uses its own database."""
    engine = create_engine(f"sqlite:///{tmp_path / 'numbers.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        provider = MockNumberProvider(db)
        e164 = next(i.e164 for i in provider.search_inventory(page=1, per_page=100).items if not i.scenario)
        provider.close()

        real = number_service.upsert_owned
        monkeypatch.setattr(number_service, "upsert_owned", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
        op = number_service.purchase(db, e164, idempotency_key=_key(), actor=number_service.SYSTEM)
        assert op.operation_status == "NEEDS_RECONCILIATION" and op.error_code == "local_save_failed"
        assert db.query(ProviderNumber).filter(ProviderNumber.e164 == e164).count() == 0
        assert db.get(MockCarrierNumber, e164).owned is True  # the carrier did buy it

        monkeypatch.setattr(number_service, "upsert_owned", real)
        summary = number_reconciliation.sync(db, number_service.SYSTEM)
        assert summary["adopted"] == 1 and summary["operations_settled"] == 1
        db.refresh(op)
        assert op.operation_status == "RECOVERED"
        assert db.query(ProviderNumber).filter(ProviderNumber.e164 == e164).one().internal_status == "AVAILABLE"
    finally:
        db.close()
        engine.dispose()


def test_mock_mode_never_calls_the_network(db: Session, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("mock mode made an HTTP request")
    monkeypatch.setattr(httpx.Client, "send", no_network)
    found = number_service.search_inventory(db, per_page=100)
    e164 = next(i["e164"] for i in found["items"] if not i["scenario"])
    op = number_service.purchase(db, e164, idempotency_key=_key(), actor=number_service.SYSTEM)
    assert op.operation_status == "SUCCEEDED" and op.is_mock
    number_reconciliation.sync(db, number_service.SYSTEM)
    pn = db.query(ProviderNumber).filter(ProviderNumber.e164 == e164).one()
    number_service.release(db, pn.id, confirm_e164=e164, idempotency_key=_key(), actor=number_service.SYSTEM)


# ---------------------------------------------------------------- assigning

def _owned(client: TestClient, headers: dict) -> dict:
    return _buy(client, headers, _first(client, headers)).json()["number"]


def test_assign_and_unassign(client: TestClient, auth_headers: dict, operator_headers: dict, db: Session, telephony_setup):
    cid, agent = telephony_setup["client"].id, telephony_setup["agent"]
    number = _owned(client, auth_headers)
    assigned = client.post(f"{API}/{number['id']}/assign", headers=operator_headers,
                           json={"client_id": cid, "agent_id": agent.id, "trunk_id": "00000000-0000-4000-8000-000000000001"})
    assert assigned.status_code == 200, assigned.text
    detail = assigned.json()
    assert detail["internal_status"] == "ASSIGNED" and detail["assignment"]["client_id"] == cid
    assert detail["assignment"]["agent_name"] == agent.name and detail["trunk_id"].endswith("0001")

    # Inbound calls find the AI employee; the client sees the number in their portal
    routing = PhoneNumberRepository(db).get_by_e164(number["e164"])
    assert routing.client_id == cid and routing.agent_id == agent.id and routing.agent_version_id == telephony_setup["version"].id
    assert routing.status == "READY_TO_TEST" and routing.provider == "vobiz"
    h = _client_headers(client, auth_headers, cid, f"numbers-{cid}@example.com")
    assert number["e164"] in [n["phone_number"] for n in client.get("/api/portal/numbers", headers=h).json()["numbers"]]

    again = client.post(f"{API}/{number['id']}/assign", headers=operator_headers, json={"client_id": cid})
    assert again.status_code == 409 and again.json()["code"] == "already_assigned"
    assert client.post(f"{API}/{number['id']}/release", headers=auth_headers,
                       json={"confirm_e164": number["e164"], "idempotency_key": _key()}).json()["code"] == "assigned"

    unassigned = client.post(f"{API}/{number['id']}/unassign", headers=operator_headers)
    assert unassigned.status_code == 200 and unassigned.json()["internal_status"] == "AVAILABLE"
    assert unassigned.json()["trunk_id"] is None
    assert PhoneNumberRepository(db).get_by_e164(number["e164"]) is None  # inbound calls no longer routed
    history = unassigned.json()["assignments"]
    assert len(history) == 1 and history[0]["status"] == "ENDED" and history[0]["released_at"]
    assert number["e164"] not in [n["phone_number"] for n in client.get("/api/portal/numbers", headers=h).json()["numbers"]
                                  if n["status"] != "RELEASED"]

    # It can go to another client afterwards, and the first assignment stays in the history
    other = Client(id=generate_unique_id("cli_"), name="Second Clinic", business_type="CLINIC")
    db.add(other)
    db.commit()
    reassigned = client.post(f"{API}/{number['id']}/assign", headers=operator_headers, json={"client_id": other.id}).json()
    assert reassigned["assignment"]["client_id"] == other.id and len(reassigned["assignments"]) == 2


def test_assignment_checks(client: TestClient, auth_headers: dict, operator_headers: dict, db: Session, telephony_setup):
    number = _owned(client, auth_headers)
    other = Client(id=generate_unique_id("cli_"), name="Elsewhere", business_type="CLINIC")
    db.add(other)
    db.commit()
    wrong_agent = client.post(f"{API}/{number['id']}/assign", headers=operator_headers,
                              json={"client_id": other.id, "agent_id": telephony_setup["agent"].id})
    assert wrong_agent.status_code == 400 and wrong_agent.json()["code"] == "agent_not_found"
    assert client.post(f"{API}/{number['id']}/assign", headers=operator_headers,
                       json={"client_id": "cli_missing"}).status_code == 404
    bad_trunk = client.post(f"{API}/{number['id']}/assign", headers=operator_headers,
                            json={"client_id": other.id, "trunk_id": "not-a-trunk"})
    assert bad_trunk.status_code == 404 and bad_trunk.json()["operation"]["operation_status"] == "FAILED"
    assert client.post(f"{API}/{number['id']}/unassign", headers=operator_headers).json()["code"] == "not_assigned"
    # One active assignment per number, even if two requests race
    pn = db.get(ProviderNumber, number["id"])
    db.add(NumberAssignment(provider_number_id=pn.id, client_id=other.id, status="ACTIVE"))
    db.commit()
    with pytest.raises(Exception):
        db.add(NumberAssignment(provider_number_id=pn.id, client_id=other.id, status="ACTIVE"))
        db.commit()
    db.rollback()


def test_portal_clients_only_see_their_own_numbers(client: TestClient, auth_headers: dict, operator_headers: dict,
                                                    db: Session, telephony_setup):
    number = _owned(client, auth_headers)
    client.post(f"{API}/{number['id']}/assign", headers=operator_headers, json={"client_id": telephony_setup["client"].id})
    other = Client(id=generate_unique_id("cli_"), name="Nosy Clinic", business_type="CLINIC")
    db.add(other)
    db.commit()
    h = _client_headers(client, auth_headers, other.id, f"nosy-{other.id}@example.com")
    assert number["e164"] not in [n["phone_number"] for n in client.get("/api/portal/numbers", headers=h).json()["numbers"]]
    routing = PhoneNumberRepository(db).get_by_e164(number["e164"])
    assert client.get(f"/api/portal/numbers/{routing.id}", headers=h).status_code == 404
    assert client.get(API, headers=h).status_code == 403


# ---------------------------------------------------------------- releasing and syncing

def test_release(client: TestClient, auth_headers: dict, db: Session):
    number = _owned(client, auth_headers)
    mismatch = client.post(f"{API}/{number['id']}/release", headers=auth_headers,
                           json={"confirm_e164": "+910000000000", "idempotency_key": _key()})
    assert mismatch.status_code == 400 and mismatch.json()["code"] == "confirmation_mismatch"
    key = _key()
    released = client.post(f"{API}/{number['id']}/release", headers=auth_headers,
                           json={"confirm_e164": number["e164"], "idempotency_key": key})
    assert released.status_code == 200 and released.json()["number"]["internal_status"] == "RELEASED"
    repeat = client.post(f"{API}/{number['id']}/release", headers=auth_headers,
                         json={"confirm_e164": number["e164"], "idempotency_key": key})
    assert repeat.json()["operation"]["id"] == released.json()["operation"]["id"]
    assert number["e164"] in [i["e164"] for i in client.get(f"{API}/inventory", headers=auth_headers, params={"per_page": 100}).json()["items"]]
    assert number["e164"] not in [n["e164"] for n in client.get(API, headers=auth_headers).json()["items"]]


def test_sync_adopts_and_flags(client: TestClient, auth_headers: dict, db: Session):
    ours = _owned(client, auth_headers)
    # Bought in the Vobiz console (Choranta doesn't know it), and one of ours released there
    outside = _first(client, auth_headers)
    provider = MockNumberProvider(db)
    provider._db.get(MockCarrierNumber, outside).owned = True
    provider._db.get(MockCarrierNumber, ours["e164"]).owned = False
    provider._db.commit()
    provider.close()

    synced = client.post(f"{API}/sync", headers=auth_headers)
    assert synced.status_code == 200, synced.text
    assert synced.json()["adopted"] >= 1 and synced.json()["missing"] >= 1
    adopted = db.query(ProviderNumber).filter(ProviderNumber.e164 == outside).one()
    assert adopted.internal_status == "AVAILABLE" and adopted.last_synced_at
    flagged = client.get(f"{API}/{ours['id']}", headers=auth_headers).json()
    assert flagged["provider_status"] == "MISSING" and flagged["internal_status"] == "NEEDS_RECONCILIATION" and flagged["attention"]


# ---------------------------------------------------------------- access, limits and configuration

def test_roles(client: TestClient, auth_headers: dict, operator_headers: dict, telephony_setup):
    number = _owned(client, auth_headers)
    e164 = _first(client, operator_headers)
    assert client.get(f"{API}/inventory", headers=operator_headers).status_code == 200
    assert _buy(client, operator_headers, e164).status_code == 403
    assert client.post(f"{API}/{number['id']}/release", headers=operator_headers,
                       json={"confirm_e164": number["e164"], "idempotency_key": _key()}).status_code == 403
    assert client.post(f"{API}/sync", headers=operator_headers).status_code == 403
    h = _client_headers(client, auth_headers, telephony_setup["client"].id, f"roles-{uuid.uuid4().hex[:6]}@example.com")
    for method, path in (("get", f"{API}/inventory"), ("post", f"{API}/sync"), ("get", f"{API}/operations")):
        assert getattr(client, method)(path, headers=h).status_code == 403
    assert client.get(f"{API}/inventory").status_code in (401, 403)


def test_purchases_are_rate_limited(client: TestClient, auth_headers: dict, monkeypatch):
    monkeypatch.setattr(settings, "NUMBER_PURCHASES_PER_HOUR", 1)
    assert _buy(client, auth_headers, _first(client, auth_headers)).status_code == 200
    limited = _buy(client, auth_headers, _first(client, auth_headers))
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_missing_vobiz_credentials_fail_safely(client: TestClient, auth_headers: dict, monkeypatch):
    for name, value in {"PHONE_NUMBER_MOCK_MODE": False, "VOBIZ_AUTH_ID": None, "VOBIZ_AUTH_TOKEN": None}.items():
        monkeypatch.setattr(settings, name, value)
    inventory = client.get(f"{API}/inventory", headers=auth_headers)
    assert inventory.status_code == 503 and inventory.json()["code"] == "not_configured"
    status = client.get(f"{API}/provider-status", headers=auth_headers).json()
    assert status["mock_mode"] is False and status["configured"] is False
    assert _buy(client, auth_headers, "+914071100000", expected_monthly_cost=300).status_code == 503


def test_production_refuses_mock_numbers():
    with pytest.raises(Exception, match="PHONE_NUMBER_MOCK_MODE"):
        Settings(_env_file=None, ENVIRONMENT="production", RUNTIME_MODE="mock", PHONE_NUMBER_MOCK_MODE=True,
                 DATABASE_URL="postgresql://u:p@db.example.com/choranta", JWT_SECRET_KEY="x" * 40, CORS_ORIGINS=["https://app.example.com"],
                 SIMULATED_PAYMENTS=False)
