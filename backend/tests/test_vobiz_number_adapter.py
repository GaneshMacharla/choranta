"""
The real Vobiz number adapter, against the published contract (vobiz.ai/openapi.json), with HTTP faked by
httpx.MockTransport: no credentials, no network, nothing bought.
"""
import json

import httpx
import pytest

from app.runtime.providers.numbers import (
    InsufficientBalance, NotConfigured, NumberNotFound, NumberUnavailable, ProviderAuthError, ProviderUnavailable,
    ProviderUncertain, ProviderValidationError,
)
from app.runtime.providers.numbers.vobiz import VobizNumberProvider

BASE = "https://api.vobiz.ai/api/v1"
OWNED = {
    "id": "aabbccdd-1234", "account_id": "MA_TEST", "e164": "+919876543210", "country": "IN", "region": "Karnataka",
    "capabilities": {"voice": True, "sms": False}, "status": "active", "setup_fee": 100, "monthly_fee": 300,
    "currency": "INR", "application_id": "20577609616603585", "purchased_at": "2026-03-25T06:58:38Z",
    "next_billing_date": "2026-04-25T06:58:38Z", "aadhaar_verification_required": False,
}


def _adapter(handler):
    seen = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)
    return VobizNumberProvider(auth_id="MA_TEST", auth_token="secret-token", base_url=BASE,
                               transport=httpx.MockTransport(record)), seen


def test_every_request_carries_the_auth_headers_and_a_fixed_host():
    provider, seen = _adapter(lambda r: httpx.Response(200, json={"items": [], "page": 1, "per_page": 25, "total": 0}))
    provider.search_inventory(country="IN", search="80", page=2, per_page=50)
    request = seen[0]
    assert request.headers["X-Auth-ID"] == "MA_TEST" and request.headers["X-Auth-Token"] == "secret-token"
    assert request.url.host == "api.vobiz.ai"
    assert request.url.path == "/api/v1/Account/MA_TEST/inventory/numbers"
    assert dict(request.url.params) == {"country": "IN", "search": "80", "page": "2", "per_page": "50"}


def test_inventory_and_owned_numbers_are_parsed():
    def handler(request):
        if request.url.path.endswith("/inventory/numbers"):
            return httpx.Response(200, json={"items": [{"id": "550e", "e164": "+14155551234", "country": "US", "region": "CA",
                                                        "status": "active", "setup_fee": 0, "monthly_fee": 1, "currency": "INR"}],
                                             "page": 1, "per_page": 25, "total": 500})
        return httpx.Response(200, json={"items": [OWNED], "page": 1, "per_page": 25, "total": 1})
    provider, seen = _adapter(handler)
    page = provider.search_inventory()
    assert page.total == 500 and page.items[0].e164 == "+14155551234" and page.items[0].monthly_fee == 1.0
    owned = provider.list_owned(page=3, per_page=20)
    assert dict(seen[1].url.params) == {"limit": "20", "offset": "40"}
    number = owned.items[0]
    assert number.e164 == "+919876543210" and number.capabilities["voice"] is True
    assert number.application_id == "20577609616603585" and number.raw["next_billing_date"].startswith("2026-04")


def test_purchase_posts_the_documented_body():
    provider, seen = _adapter(lambda r: httpx.Response(200, json={"message": "Number purchased successfully", "number": OWNED}))
    owned = provider.purchase("+919876543210", "INR")
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/api/v1/Account/MA_TEST/numbers/purchase-from-inventory"
    assert json.loads(request.content) == {"e164": "+919876543210", "currency": "INR"}
    assert owned.provider_number_id == "aabbccdd-1234" and owned.monthly_fee == 300.0


def test_routing_and_release_paths():
    provider, seen = _adapter(lambda r: httpx.Response(204) if r.method != "GET" else httpx.Response(200, json={
        "meta": {"total": 1}, "objects": [{"trunk_id": "e3e55a78", "name": "Main"}]}))
    provider.attach_application("+919876543210", "app_1")
    provider.assign_trunk("+919876543210", "e3e55a78")
    provider.unassign_trunk("+919876543210")
    provider.release("+919876543210")
    provider.assign_subaccount("+919876543210", "SA_1")
    trunks = provider.list_trunks()
    paths = [(r.method, r.url.raw_path.decode()) for r in seen]
    assert paths[:5] == [
        ("POST", "/api/v1/Account/MA_TEST/numbers/%2B919876543210/application"),
        ("POST", "/api/v1/Account/MA_TEST/numbers/%2B919876543210/assign"),
        ("DELETE", "/api/v1/Account/MA_TEST/numbers/%2B919876543210/assign"),
        ("DELETE", "/api/v1/Account/MA_TEST/numbers/919876543210"),  # release takes the number without "+"
        ("POST", "/api/v1/account/MA_TEST/numbers/%2B919876543210/assign-subaccount"),
    ]
    assert json.loads(seen[0].content) == {"application_id": "app_1"}
    assert json.loads(seen[1].content) == {"trunk_group_id": "e3e55a78"}
    assert json.loads(seen[4].content) == {"sub_account_id": "SA_1"}
    assert trunks[0].id == "e3e55a78" and trunks[0].name == "Main"


def test_balance():
    provider, seen = _adapter(lambda r: httpx.Response(200, json={"currency": "INR", "balance": 23906.83, "available_balance": 23000.5}))
    assert provider.balance("INR") == 23000.5
    assert seen[0].url.path == "/api/v1/Account/MA_TEST/balance/INR"


@pytest.mark.parametrize("status,body,error", [
    (401, {"error": "unauthorized", "message": "Invalid auth"}, ProviderAuthError),
    (403, {"message": "Forbidden"}, ProviderAuthError),
    (402, {"message": "Payment required"}, InsufficientBalance),
    (400, {"error": "insufficient_balance", "message": "Insufficient balance"}, InsufficientBalance),
    (404, {"error": "not_found", "message": "Number not found in inventory"}, NumberUnavailable),
    (400, {"error": "bad_request", "message": "Invalid e164"}, ProviderValidationError),
    (500, {"error": "server_error", "message": "Failed to purchase number"}, ProviderUncertain),
    (429, {"message": "Slow down"}, ProviderUnavailable),
])
def test_purchase_errors_are_mapped(status, body, error):
    provider, _ = _adapter(lambda r: httpx.Response(status, json=body))
    with pytest.raises(error) as raised:
        provider.purchase("+919876543210", "INR")
    assert "secret-token" not in raised.value.message


def test_a_timeout_after_sending_is_uncertain_but_a_refused_connection_is_not():
    def read_timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)
    with pytest.raises(ProviderUncertain):
        _adapter(read_timeout)[0].purchase("+919876543210", "INR")
    with pytest.raises(ProviderUnavailable):
        _adapter(refused)[0].purchase("+919876543210", "INR")
    with pytest.raises(ProviderUnavailable):  # a read can always be repeated
        _adapter(read_timeout)[0].list_owned()


def test_a_success_without_the_number_is_not_treated_as_bought():
    provider, _ = _adapter(lambda r: httpx.Response(200, json={"message": "ok"}))
    with pytest.raises(ProviderUncertain):
        provider.purchase("+919876543210", "INR")


def test_other_errors_and_missing_credentials(monkeypatch):
    provider, _ = _adapter(lambda r: httpx.Response(404, json={"message": "Number not found"}))
    with pytest.raises(NumberNotFound):
        provider.release("+919876543210")
    cool_off = _adapter(lambda r: httpx.Response(409, json={"error": "did_cool_off_in_effect", "message": "Cool-off",
                                                             "cool_off_remaining_seconds": 3600}))[0]
    with pytest.raises(ProviderValidationError) as raised:
        cool_off.unassign_subaccount("+919876543210")
    assert raised.value.provider_code == "did_cool_off_in_effect" and raised.value.details["cool_off_remaining_seconds"] == 3600
    from app.core.config import settings
    monkeypatch.setattr(settings, "VOBIZ_AUTH_ID", None)
    monkeypatch.setattr(settings, "VOBIZ_AUTH_TOKEN", None)
    with pytest.raises(NotConfigured):
        VobizNumberProvider(base_url=BASE).search_inventory()
