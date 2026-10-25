from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.billing import WalletTransaction
from app.models.client import Client
from app.models.phone_number import PhoneNumber
from app.models.subscription import NumberRental
from app.services import billing, exotel_numbers, phone_numbers
from app.services.subscriptions import utcnow
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import _client_headers


@pytest.fixture
def exotel(monkeypatch):
    """Records Exotel purchases and releases instead of calling Exotel."""
    calls = {"purchased": [], "released": [], "fail_purchase": False, "fail_release": False}

    def purchase(number, friendly_name):
        if calls["fail_purchase"]:
            raise exotel_numbers.ExotelNumberError("Number no longer available")
        calls["purchased"].append(number)
        return {"sid": f"sid_{number.lstrip('+')}", "phone_number": number}

    def release(sid):
        if calls["fail_release"]:
            raise exotel_numbers.ExotelNumberError("Exotel down")
        calls["released"].append(sid)

    monkeypatch.setattr(exotel_numbers, "purchase", purchase)
    monkeypatch.setattr(exotel_numbers, "release", release)
    return calls


@pytest.fixture(autouse=True)
def verified_business(request, db: Session):
    """These tests are about renting; the client has already passed business verification."""
    if "telephony_setup" not in request.fixturenames:
        return
    from app.models.verification import ClientVerification
    cid = request.getfixturevalue("telephony_setup")["client"].id
    if not db.get(ClientVerification, cid):
        db.add(ClientVerification(client_id=cid, status="APPROVED", legal_name="Test Clinic", pan="ABCDE1234F",
                                  registered_address="Hyderabad", signatory_name="Owner", documents=[]))
        db.commit()


def _number(db: Session, i: int = 0) -> str:
    """A landline the (simulated) carrier is selling."""
    return phone_numbers.search(db, "Landline")[i]["phone_number"]


def _owned(db: Session, e164: str):
    from app.models.numbers import ProviderNumber
    return db.query(ProviderNumber).filter(ProviderNumber.e164 == e164).first()


def _fund(db: Session, client_id: str, amount_with_gst: float) -> None:
    billing.record_payment(db, client_id, amount_with_gst, None, None)


def _rent_debits(db: Session, client_id: str):
    return db.query(WalletTransaction).filter(
        WalletTransaction.client_id == client_id, WalletTransaction.note.like("Rent for%")).all()


def test_buy_needs_balance_and_charges_first_month(db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    number = _number(db)
    with pytest.raises(phone_numbers.InsufficientBalance):
        phone_numbers.buy_number(db, cid, number, "Landline", None)
    assert _owned(db, number) is None  # nothing bought without the rent

    _fund(db, cid, 1180)  # Rs 1000 wallet
    pn = phone_numbers.buy_number(db, cid, number, "Landline", None)
    rental = phone_numbers.rental_for(db, pn.id)
    assert pn.status == "READY_TO_TEST" and pn.provider == "vobiz" and pn.provider_number_id == f"mock-{number.lstrip('+')}"
    assert _owned(db, number).internal_status == "ASSIGNED"
    assert rental.monthly_rent_inr == 499.0 and rental.status == "ACTIVE"
    assert billing.get_wallet(db, cid).balance_inr == 501.0
    assert len(_rent_debits(db, cid)) == 1

    with pytest.raises(Exception):
        phone_numbers.buy_number(db, cid, number, "Landline", None)  # already taken


def test_failed_purchase_charges_nothing(db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    _fund(db, cid, 1180)
    number = "+918040000404"  # the simulated carrier sells it to someone else first
    with pytest.raises(Exception):
        phone_numbers.buy_number(db, cid, number, "Landline", None)
    assert billing.get_wallet(db, cid).balance_inr == 1000.0
    assert db.query(PhoneNumber).filter(PhoneNumber.phone_number == number).count() == 0


def test_rental_cycle_renews_lapses_and_returns_to_pool(db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    _fund(db, cid, 1180)
    number = _number(db)
    pn = phone_numbers.buy_number(db, cid, number, "Landline", None)
    rental = phone_numbers.rental_for(db, pn.id)
    first_end = rental.current_period_end

    # Month ends with Rs 501 in the wallet: renews
    phone_numbers.run_rental_cycle(db, now=first_end + timedelta(minutes=1))
    assert rental.status == "ACTIVE" and rental.current_period_start == first_end
    assert billing.get_wallet(db, cid).balance_inr == 2.0
    second_end = rental.current_period_end

    # Next month: Rs 2 can't cover it -> past due, then back after a top-up within grace
    phone_numbers.run_rental_cycle(db, now=second_end + timedelta(hours=1))
    assert rental.status == "PAST_DUE"
    phone_numbers.run_rental_cycle(db, now=second_end + timedelta(hours=2))
    assert rental.status == "PAST_DUE" and len(_rent_debits(db, cid)) == 2  # no extra debit while past due
    _fund(db, cid, 590)
    phone_numbers.run_rental_cycle(db, now=second_end + timedelta(days=1))
    assert rental.status == "ACTIVE" and rental.current_period_start == second_end

    # Unpaid past the grace period: back in Choranta's pool (not released at the carrier) and retired here
    third_end = rental.current_period_end
    phone_numbers.run_rental_cycle(db, now=third_end + timedelta(days=settings.NUMBER_GRACE_DAYS + 1))
    assert rental.status == "RELEASED"
    db.refresh(pn)
    assert pn.status == "RELEASED" and pn.agent_id is None and phone_numbers.display_number(pn) == number
    pooled = _owned(db, number)
    assert pooled.internal_status == "AVAILABLE" and "rent lapsed" in pooled.attention
    debits = len(_rent_debits(db, cid))
    phone_numbers.run_rental_cycle(db, now=third_end + timedelta(days=60))
    assert rental.status == "RELEASED" and len(_rent_debits(db, cid)) == debits


def test_legacy_exotel_number_is_released_on_exotel(db: Session, telephony_setup, exotel, company):
    from app.models.subscription import NumberRental as Rental
    cid = telephony_setup["client"].id
    pn = PhoneNumber(id=generate_unique_id("phn_"), client_id=cid, phone_number="+914071239999", provider="exotel",
                     provider_number_id="sid_legacy", country_code="IN", status="ACTIVE")
    db.add(pn)
    db.flush()
    rental = Rental(phone_number_id=pn.id, client_id=cid, number_type="Landline", monthly_rent_inr=499, status="PAST_DUE",
                    current_period_start=utcnow() - timedelta(days=40), current_period_end=utcnow() - timedelta(days=10))
    db.add(rental)
    db.commit()
    exotel["fail_release"] = True
    phone_numbers.run_rental_cycle(db)
    assert rental.status == "PAST_DUE"  # Exotel failed: kept, retried next cycle
    exotel["fail_release"] = False
    phone_numbers.run_rental_cycle(db)
    assert rental.status == "RELEASED" and exotel["released"] == ["sid_legacy"]


def test_free_numbers_are_never_charged(db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    _fund(db, cid, 1180)
    phone_numbers.run_rental_cycle(db, now=utcnow() + timedelta(days=400))
    assert billing.get_wallet(db, cid).balance_inr == 1000.0
    assert phone_numbers.rental_for(db, telephony_setup["phone_number"].id) is None


def test_inbound_call_to_overdue_number_is_rejected(client: TestClient, db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    _fund(db, cid, 1180)
    pn = phone_numbers.buy_number(db, cid, _number(db), "Landline", None)
    phone_numbers.assign_agent(db, pn, telephony_setup["agent"].id)
    rental = phone_numbers.rental_for(db, pn.id)
    rental.status = "PAST_DUE"
    rental.current_period_end = utcnow() - timedelta(days=settings.NUMBER_GRACE_DAYS + 1)
    db.commit()
    resp = client.get("/api/telephony/exotel/inbound",
                      params={"CallSid": "CA_RENT_1", "CallFrom": "09876543210", "CallTo": pn.phone_number})
    assert resp.json()["url"] == ""


def test_portal_numbers_flow(client: TestClient, auth_headers: dict, db: Session, telephony_setup, company):
    cid = telephony_setup["client"].id
    headers = _client_headers(client, auth_headers, cid, f"numbers-{cid}@clinic.example.com")

    available = client.get("/api/portal/numbers/available?number_type=Landline", headers=headers)
    assert available.status_code == 200 and available.json()[0]["monthly_rent_with_gst_inr"] == 588.82

    number = available.json()[0]["phone_number"]
    short = client.post("/api/portal/numbers", headers=headers, json={"phone_number": number, "number_type": "Landline"})
    assert short.status_code == 402

    _fund(db, cid, 1180)
    bought = client.post("/api/portal/numbers", headers=headers, json={"phone_number": number, "number_type": "Landline"})
    assert bought.status_code == 201, bought.text
    nid = bought.json()["id"]

    agents = client.get("/api/portal/agents", headers=headers).json()
    assert agents[0]["published"] is True
    assigned = client.patch(f"/api/portal/numbers/{nid}", headers=headers, json={"agent_id": agents[0]["id"]}).json()
    assert assigned["agent_name"] == telephony_setup["agent"].name

    later = client.delete(f"/api/portal/numbers/{nid}", headers=headers).json()
    assert later["cancel_at_period_end"] is True and later["status"] == "READY_TO_TEST"
    assert client.post(f"/api/portal/numbers/{nid}/keep", headers=headers).json()["cancel_at_period_end"] is False

    listed = client.get("/api/portal/numbers", headers=headers).json()
    assert {n["id"] for n in listed["numbers"]} >= {nid, telephony_setup["phone_number"].id}

    # Another client's number is invisible
    other = Client(id=generate_unique_id("cli_"), name="Other Clinic", business_type="CLINIC")
    db.add(other)
    db.commit()
    other_headers = _client_headers(client, auth_headers, other.id, f"numbers-{other.id}@clinic.example.com")
    assert client.delete(f"/api/portal/numbers/{nid}?now=true", headers=other_headers).status_code == 404

    released = client.delete(f"/api/portal/numbers/{nid}?now=true", headers=headers).json()
    assert released["status"] == "RELEASED" and released["phone_number"] == number


def test_admin_number_pricing(client: TestClient, auth_headers: dict, operator_headers: dict):
    assert client.put("/api/number-pricing/Mobile", headers=operator_headers,
                      json={"monthly_rent_inr": 799}).status_code == 403
    updated = client.put("/api/number-pricing/Mobile", headers=auth_headers, json={"monthly_rent_inr": 799, "is_available": False})
    assert updated.json()["monthly_rent_inr"] == 799 and updated.json()["is_available"] is False
    listed = client.get("/api/number-pricing", headers=auth_headers).json()
    assert any(p["number_type"] == "Mobile" and p["monthly_rent_inr"] == 799 for p in listed)
