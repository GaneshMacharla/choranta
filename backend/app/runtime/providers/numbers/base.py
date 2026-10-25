"""
Phone number provisioning at a carrier: what Choranta can buy, what it owns, and how numbers are routed.

Every carrier adapter (Vobiz, the mock, legacy Exotel) implements NumberProvider and raises only the errors
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
class Trunk:
    id: str
    name: str


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

    def assign_subaccount(self, e164: str, sub_auth_id: str) -> None:
        raise NotImplementedError

    def unassign_subaccount(self, e164: str) -> None:
        raise NotImplementedError

    def balance(self, currency: str) -> Optional[float]:
        """Available balance, or None when the carrier doesn't report one."""
        return None
