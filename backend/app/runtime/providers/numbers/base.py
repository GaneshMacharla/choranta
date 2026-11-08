"""
Phone number provisioning at a carrier: what Choranta can buy, what it owns, and how numbers are routed.

Every carrier adapter (Vobiz, the mock) implements NumberProvider and raises only the errors
below, so services/number_service.py handles every carrier the same way. Synchronous like the rest of the
request path (SQLAlchemy sessions); FastAPI runs these endpoints in its worker threads.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------- errors

class NumberProviderError(Exception):
    """Base error. `code` is stable for the API; `message` is safe to show to staff (no secrets)."""
    code = "provider_error"
    status_code = 502

    def __init__(self, message: str, *, provider_code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.provider_code = provider_code
        self.details = details or {}


class NotConfigured(NumberProviderError):
    code, status_code = "not_configured", 503


class ProviderAuthError(NumberProviderError):
    code, status_code = "provider_auth_failed", 502


class InsufficientBalance(NumberProviderError):
    code, status_code = "insufficient_balance", 402


class NumberUnavailable(NumberProviderError):
    code, status_code = "number_unavailable", 409


class NumberNotFound(NumberProviderError):
    code, status_code = "number_not_found", 404


class ProviderValidationError(NumberProviderError):
    code, status_code = "provider_rejected", 400


class ProviderUnavailable(NumberProviderError):
    """The carrier couldn't be reached and the request was certainly not processed (safe to try again)."""
    code, status_code = "provider_unreachable", 503


class ProviderUncertain(NumberProviderError):
    """
    The request may or may not have taken effect (timeout after sending, or a 5xx). Never retry blindly:
    read the carrier's state first (services/number_reconciliation.py).
    """
    code, status_code = "provider_uncertain", 504


# ---------------------------------------------------------------- data

@dataclass
class InventoryNumber:
    e164: str
    country: Optional[str] = None
    region: Optional[str] = None
    provider_number_id: Optional[str] = None
    setup_fee: Optional[float] = None
    monthly_fee: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    # Mock only: which failure buying this number simulates (shown in the UI)
    scenario: Optional[str] = None


@dataclass
class OwnedNumber:
    e164: str
    provider_number_id: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    capabilities: Dict[str, bool] = field(default_factory=dict)
    status: Optional[str] = None
    setup_fee: Optional[float] = None
    monthly_fee: Optional[float] = None
    currency: Optional[str] = None
    application_id: Optional[str] = None
    trunk_id: Optional[str] = None
    purchased_at: Optional[str] = None
    next_billing_date: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Page:
    items: List[Any]
    page: int
    per_page: int
    total: Optional[int] = None


@dataclass
class Subaccount:
    auth_id: str
    auth_token: str
    kyc_mode: Optional[str] = None


@dataclass
class Trunk:
    id: str
    name: str


@dataclass
class KycResult:
    """One document checked by the carrier. calls_blocked is None when the carrier doesn't say."""
    kind: str                          # pan, gst, cin, aadhaar
    status: str                        # verified, failed, pending
    calls_blocked: Optional[bool] = None
    name: Optional[str] = None         # the name the government record holds (PAN holder, GST legal name)
    message: Optional[str] = None


@dataclass
class KycStatus:
    overall: str                       # not_started, pending, verified, failed
    calls_blocked: bool
    checks: Dict[str, str] = field(default_factory=dict)  # pan/gst/cin/aadhaar -> not_started/pending/verified/failed


# ---------------------------------------------------------------- interface

class NumberProvider:
    name = "base"
    is_mock = False

    def search_inventory(self, *, country: Optional[str] = None, search: Optional[str] = None,
                         page: int = 1, per_page: int = 25) -> Page:
        raise NotImplementedError

    def list_owned(self, *, page: int = 1, per_page: int = 100) -> Page:
        raise NotImplementedError

    def get_owned(self, e164: str) -> Optional[OwnedNumber]:
        """The owned number, read from the owned list (the carriers have no single-number read)."""
        page = 1
        while True:
            result = self.list_owned(page=page, per_page=100)
            for item in result.items:
                if item.e164 == e164:
                    return item
            if len(result.items) < result.per_page:
                return None
            page += 1

    def purchase(self, e164: str, currency: str) -> OwnedNumber:
        raise NotImplementedError

    def release(self, e164: str) -> None:
        raise NotImplementedError

    def attach_application(self, e164: str, application_id: str) -> None:
        raise NotImplementedError

    def assign_trunk(self, e164: str, trunk_id: str) -> None:
        raise NotImplementedError

    def unassign_trunk(self, e164: str) -> None:
        raise NotImplementedError

    def list_trunks(self) -> List[Trunk]:
        return []

    def create_subaccount(self, *, name: str, email: Optional[str], phone: Optional[str], description: str,
                          kyc_mode: str, business_type: Optional[str] = None) -> Subaccount:
        """A new sub-account; its token is in the result only (the carrier never shows it again)."""
        raise NotImplementedError

    def update_subaccount(self, sub_auth_id: str, *, business_type: Optional[str] = None,
                          enabled: Optional[bool] = None) -> None:
        raise NotImplementedError

    def create_application(self, *, name: str, answer_url: str) -> str:
        """An inbound-call application on the account the provider authenticates as; returns its id."""
        raise NotImplementedError

    # KYC of a customer sub-account, authenticated as the parent account

    def kyc_verify_pan(self, sub_auth_id: str, pan: str) -> KycResult:
        raise NotImplementedError

    def kyc_verify_gst(self, sub_auth_id: str, gstin: str) -> KycResult:
        raise NotImplementedError

    def kyc_cin_search(self, sub_auth_id: str, company_name: str) -> List[Dict[str, str]]:
        """Companies matching the name: [{cin, company_name, status}]."""
        raise NotImplementedError

    def kyc_cin_confirm(self, sub_auth_id: str, company_name: str, cin: str) -> KycResult:
        raise NotImplementedError

    def kyc_digilocker_initiate(self, sub_auth_id: str, redirect_url: str, state: str) -> Dict[str, str]:
        """{auth_url, access_request_id}: send the customer to auth_url; DigiLocker returns them to redirect_url."""
        raise NotImplementedError

    def kyc_digilocker_verify(self, sub_auth_id: str, access_request_id: str) -> KycResult:
        raise NotImplementedError

    def kyc_status(self, sub_auth_id: str) -> Optional[KycStatus]:
        """The carrier's view of the sub-account's KYC, or None when it keeps none (the mock)."""
        return None

    def assign_subaccount(self, e164: str, sub_auth_id: str) -> None:
        raise NotImplementedError

    def unassign_subaccount(self, e164: str) -> None:
        raise NotImplementedError

    def balance(self, currency: str) -> Optional[float]:
        """Available balance, or None when the carrier doesn't report one."""
        return None
