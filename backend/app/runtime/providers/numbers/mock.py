"""
Simulated carrier for PHONE_NUMBER_MOCK_MODE: sample inventory, purchases, routing and release, persisted in the
mock_carrier_numbers table. It never makes a network call.

It keeps its own state in its own session, like a real carrier would: a purchase it "completed" stays completed
even when Choranta's own save afterwards fails, so recovery paths can be exercised.

Buying one of the SCENARIO_NUMBERS reproduces a failure (shown in the inventory so staff know what they're picking).

Customer KYC: every well-formed document verifies, except a PAN (or the PAN inside a GSTIN) whose four digits are
0000, which fails. A company name containing "fail" finds no CIN. The mock keeps no KYC state of its own
(kyc_status is None), so Choranta decides from its own record which checks are done.
"""
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.models.numbers import MockCarrierNumber
from app.runtime.providers.numbers.base import (
    InsufficientBalance, InventoryNumber, KycResult, NumberNotFound, NumberProvider, NumberUnavailable, OwnedNumber,
    Page, ProviderAuthError, ProviderUncertain, ProviderValidationError, Subaccount, Trunk,
)

MOCK_BALANCE = 5000.0
MOCK_APPLICATION_ID = "mock_app_choranta"
TRUNKS = [Trunk(id="00000000-0000-4000-8000-000000000001", name="Mock trunk: Hyderabad"),
          Trunk(id="00000000-0000-4000-8000-000000000002", name="Mock trunk: Mumbai")]

SCENARIO_NUMBERS = {
    "+918040000401": "auth_error",            # Vobiz rejects the credentials
    "+918040000402": "insufficient_balance",  # the account can't cover setup + first month
    "+918040000404": "unavailable",           # someone else bought it a moment ago
    "+918040000408": "timeout_not_bought",    # no answer in time, and the purchase did NOT happen
    "+918040000409": "timeout_but_bought",    # no answer in time, but the purchase DID happen
}
SCENARIO_LABELS = {
    "auth_error": "Simulates: Vobiz credentials rejected",
    "insufficient_balance": "Simulates: insufficient Vobiz balance",
    "unavailable": "Simulates: number taken by someone else",
    "timeout_not_bought": "Simulates: timeout, not bought",
    "timeout_but_bought": "Simulates: timeout, but bought",
}


def _seed_rows() -> List[MockCarrierNumber]:
    rows = []
    # Hyderabad / Bengaluru / Mumbai landlines, mobiles and toll-free, then a few US numbers; fees in INR like Vobiz's
    for city, prefix, region in (("HYD", "+914071", "Telangana"), ("BLR", "+918061", "Karnataka"), ("BOM", "+912262", "Maharashtra")):
        for i in range(12):
            rows.append(MockCarrierNumber(e164=f"{prefix}{1000 + i * 7:04d}{i:02d}", country="IN", region=region,
                                          setup_fee=100, monthly_fee=300, currency="INR"))
    for i in range(10):
        rows.append(MockCarrierNumber(e164=f"+91987650{1000 + i * 3:04d}", country="IN", region="Telangana",
                                      setup_fee=100, monthly_fee=450, currency="INR"))
    for i in range(4):
        rows.append(MockCarrierNumber(e164=f"+9118002{1000 + i:04d}{i:02d}", country="IN", region="National",
                                      setup_fee=500, monthly_fee=1500, currency="INR"))
    for i in range(3):
        rows.append(MockCarrierNumber(e164=f"+1415555{2000 + i:04d}", country="US", region="CA",
                                      setup_fee=0, monthly_fee=95, currency="INR"))
    for e164, scenario in SCENARIO_NUMBERS.items():
        rows.append(MockCarrierNumber(e164=e164, country="IN", region="Karnataka", setup_fee=100, monthly_fee=300,
                                      currency="INR", scenario=scenario))
    return rows


def seed(db: Session) -> None:
    """Fills the simulated carrier's inventory once."""
    if db.query(MockCarrierNumber.e164).first() is None:
        db.add_all(_seed_rows())
        db.commit()


def reset(db: Session) -> None:
    """Back to the initial sample inventory (tests)."""
    db.query(MockCarrierNumber).delete()
    db.commit()
    seed(db)


class MockNumberProvider(NumberProvider):
    name = "vobiz"
    is_mock = True

    def __init__(self, db: Session):
        # Its own session on the same database: the carrier's state never rolls back with Choranta's
        self._db = Session(bind=db.get_bind())
        seed(self._db)

    def close(self) -> None:
        self._db.close()

    def _row(self, e164: str) -> Optional[MockCarrierNumber]:
        return self._db.get(MockCarrierNumber, e164)

    def _owned_row(self, e164: str) -> MockCarrierNumber:
        row = self._row(e164)
        if not row or not row.owned:
            raise NumberNotFound(f"Mock carrier: {e164} isn't on the account.")
        return row

    @staticmethod
    def _owned(row: MockCarrierNumber) -> OwnedNumber:
        return OwnedNumber(
            e164=row.e164, provider_number_id=f"mock-{row.e164.lstrip('+')}", country=row.country, region=row.region,
            capabilities={"voice": True, "sms": False, "mms": False, "fax": False}, status="active",
            setup_fee=row.setup_fee, monthly_fee=row.monthly_fee, currency=row.currency,
            application_id=row.application_id, trunk_id=row.trunk_id,
            purchased_at=row.purchased_at.isoformat() if row.purchased_at else None, raw={"mock": True},
        )

    def search_inventory(self, *, country=None, search=None, page=1, per_page=25) -> Page:
        q = self._db.query(MockCarrierNumber).filter(MockCarrierNumber.owned.is_(False))
        if country:
            q = q.filter(MockCarrierNumber.country == country.upper())
        if search:
            q = q.filter(MockCarrierNumber.e164.contains(search))
        rows = q.order_by(MockCarrierNumber.e164).all()
        start = (page - 1) * per_page
        items = [InventoryNumber(e164=r.e164, country=r.country, region=r.region, provider_number_id=f"mock-{r.e164.lstrip('+')}",
                                 setup_fee=r.setup_fee, monthly_fee=r.monthly_fee, currency=r.currency, status="active",
                                 scenario=r.scenario)
                 for r in rows[start:start + per_page]]
        return Page(items, page, per_page, len(rows))

    def list_owned(self, *, page=1, per_page=100) -> Page:
        rows = (self._db.query(MockCarrierNumber).filter(MockCarrierNumber.owned.is_(True))
                .order_by(MockCarrierNumber.e164).all())
        start = (page - 1) * per_page
        return Page([self._owned(r) for r in rows[start:start + per_page]], page, per_page, len(rows))

    def purchase(self, e164: str, currency: str) -> OwnedNumber:
        row = self._row(e164)
        if not row or row.owned:
            raise NumberUnavailable(f"Mock carrier: {e164} is no longer in inventory.")
        scenario = row.scenario
        if scenario == "auth_error":
            raise ProviderAuthError("Mock carrier: credentials rejected (simulated).")
        if scenario == "insufficient_balance":
            raise InsufficientBalance("Mock carrier: balance too low for setup fee + first month (simulated).")
        if scenario == "unavailable":
            raise NumberUnavailable("Mock carrier: someone else bought this number (simulated).")
        if scenario == "timeout_not_bought":
            raise ProviderUncertain("Mock carrier: no answer in time (simulated; the number was not bought).")
        row.owned = True
        row.purchased_at = datetime.now(timezone.utc)
        self._db.commit()
        if scenario == "timeout_but_bought":
            raise ProviderUncertain("Mock carrier: no answer in time (simulated; the number WAS bought).")
        return self._owned(row)

    def release(self, e164: str) -> None:
        row = self._owned_row(e164)
        row.owned, row.application_id, row.trunk_id, row.purchased_at = False, None, None, None
        row.scenario = None  # back in inventory as an ordinary number
        self._db.commit()

    def attach_application(self, e164: str, application_id: str) -> None:
        self._owned_row(e164).application_id = application_id
        self._db.commit()

    def assign_trunk(self, e164: str, trunk_id: str) -> None:
        row = self._owned_row(e164)
        if trunk_id not in {t.id for t in TRUNKS}:
            raise NumberNotFound("Mock carrier: no such trunk.")
        if row.trunk_id:
            raise ProviderValidationError("Mock carrier: the number is already assigned to a trunk.")
        row.trunk_id = trunk_id
        self._db.commit()

    def unassign_trunk(self, e164: str) -> None:
        self._owned_row(e164).trunk_id = None
        self._db.commit()

    def list_trunks(self) -> List[Trunk]:
        return list(TRUNKS)

    def create_subaccount(self, *, name, email, phone, description, kyc_mode, business_type=None) -> Subaccount:
        if kyc_mode == "customer_use" and not email:
            raise ProviderValidationError("Mock carrier: customer_use sub-accounts need an email.")
        return Subaccount(auth_id=f"SA_MOCK{secrets.token_hex(5).upper()}", auth_token=secrets.token_urlsafe(24),
                          kyc_mode=kyc_mode)

    def update_subaccount(self, sub_auth_id, *, business_type=None, enabled=None) -> None:
        pass

    def create_application(self, *, name, answer_url) -> str:
        return f"mock_app_{secrets.token_hex(4)}"

    @staticmethod
    def _pan_result(kind: str, pan: str, name: str) -> KycResult:
        if pan[5:9] == "0000":
            return KycResult(kind=kind, status="failed", message="Mock carrier: no record found (simulated).")
        return KycResult(kind=kind, status="verified", name=name)

    def kyc_verify_pan(self, sub_auth_id, pan) -> KycResult:
        return self._pan_result("pan", pan, "MOCK BUSINESS OWNER")

    def kyc_verify_gst(self, sub_auth_id, gstin) -> KycResult:
        return self._pan_result("gst", gstin[2:12], "MOCK BUSINESS PRIVATE LIMITED")

    def kyc_cin_search(self, sub_auth_id, company_name) -> List[Dict[str, str]]:
        if "fail" in company_name.lower():
            return []
        return [{"cin": "U72900TG2024PTC000001", "company_name": f"{company_name.upper()} PRIVATE LIMITED", "status": "Active"},
                {"cin": "U72900TG2019PTC000002", "company_name": f"{company_name.upper()} SERVICES LLP", "status": "Strike Off"}]

    def kyc_cin_confirm(self, sub_auth_id, company_name, cin) -> KycResult:
        return KycResult(kind="cin", status="verified", name=company_name)

    def kyc_digilocker_initiate(self, sub_auth_id, redirect_url, state) -> Dict[str, str]:
        # Straight back to Choranta, as if the customer had approved on DigiLocker
        sep = "&" if "?" in redirect_url else "?"
        return {"auth_url": f"{redirect_url}{sep}{urlencode({'state': state})}",
                "access_request_id": f"AR_MOCK{secrets.token_hex(4).upper()}"}

    def kyc_digilocker_verify(self, sub_auth_id, access_request_id) -> KycResult:
        return KycResult(kind="aadhaar", status="verified")

    def assign_subaccount(self, e164: str, sub_auth_id: str) -> None:
        self._owned_row(e164)

    def unassign_subaccount(self, e164: str) -> None:
        self._owned_row(e164)

    def balance(self, currency: str) -> Optional[float]:
        return MOCK_BALANCE
