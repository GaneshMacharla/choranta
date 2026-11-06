"""
Which number provider serves a request.

PHONE_NUMBER_MOCK_MODE=true -> the simulated carrier (never calls Vobiz; refused in production by config).
Otherwise the real Vobiz adapter; missing credentials surface as NotConfigured (HTTP 503), never as a fallback
to the mock.
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.providers.numbers.base import (
    InsufficientBalance, InventoryNumber, KycResult, KycStatus, NotConfigured, NumberNotFound, NumberProvider,
    NumberProviderError, NumberUnavailable, OwnedNumber, Page, ProviderAuthError, ProviderUnavailable, ProviderUncertain,
    ProviderValidationError, Subaccount, Trunk,
)


def mock_mode() -> bool:
    return bool(settings.PHONE_NUMBER_MOCK_MODE)


def number_provider(db: Session) -> NumberProvider:
    if mock_mode():
        from app.runtime.providers.numbers.mock import MockNumberProvider
        return MockNumberProvider(db)
    from app.runtime.providers.numbers.vobiz import VobizNumberProvider
    return VobizNumberProvider()


def subaccount_provider(db: Session, auth_id: str, auth_token: str) -> NumberProvider:
    """A provider acting as a client's sub-account (for what Vobiz only lets the sub-account itself do)."""
    if mock_mode():
        from app.runtime.providers.numbers.mock import MockNumberProvider
        return MockNumberProvider(db)
    from app.runtime.providers.numbers.vobiz import VobizNumberProvider
    return VobizNumberProvider(auth_id=auth_id, auth_token=auth_token)


__all__ = [
    "InsufficientBalance", "InventoryNumber", "KycResult", "KycStatus", "NotConfigured", "NumberNotFound", "NumberProvider", "NumberProviderError",
    "NumberUnavailable", "OwnedNumber", "Page", "ProviderAuthError", "ProviderUnavailable", "ProviderUncertain",
    "ProviderValidationError", "Subaccount", "Trunk", "mock_mode", "number_provider",
    "subaccount_provider",
]
