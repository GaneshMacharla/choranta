"""
Vobiz number management, against the published API contract (https://www.vobiz.ai/openapi.json, checked Oct 2026).

All under {VOBIZ_API_BASE}/Account/{auth_id}, headers X-Auth-ID / X-Auth-Token:
  GET    /inventory/numbers?country&search&page&per_page   numbers for sale
  POST   /numbers/purchase-from-inventory {e164, currency}  buy (debits setup + first month; 404 = not in inventory)
  GET    /numbers?limit&offset                              numbers we own
  DELETE /numbers/{e164 without +}                          release (a release fee applies)
  POST   /numbers/{+e164}/application {application_id}      route inbound calls to our answer URL (docs page;
                                                            not in the OpenAPI file; no detach endpoint exists)
  POST   /numbers/{+e164}/assign {trunk_group_id}           SIP trunk; DELETE unassigns
  GET    /trunks
  POST   /accounts/{auth_id}/sub-accounts/ {name, email, phone, description, kyc_mode, business_type}   token only here
  PUT    /accounts/{auth_id}/sub-accounts/{sub_auth_id} {name, enabled, kyc_mode, business_type}
  POST   /account/{auth_id}/numbers/{+e164}/assign-subaccount {sub_account_id}; DELETE moves it back (15-day cool-off)
  POST   /Application/ {app_name, answer_url, answer_method}  as the sub-account itself (they can't use ours)
  GET    /balance/{currency}
Customer KYC of a sub-account, as the parent, under {VOBIZ_API_BASE}/sub-accounts/{sub_auth_id} (VOBIZ_KYC_TEST_MODE
uses Vobiz's mock endpoints, /sub-accounts/test/{sub_auth_id}, driven by magic inputs such as TESTSUCCESS0001):
  POST   /kyc/verify-pan {pan}, /kyc/verify-gst {gstin}            -> {status: verified|failed|pending, kyc_calls_blocked}
  POST   /kyc/cin/search {company_name} -> {matches}, /kyc/cin/confirm {company_name, selected_cin}
  POST   /kyc/digilocker/initiate {redirect_url, oauth_state} -> {auth_url, access_request_id}
  POST   /kyc/digilocker/verify {access_request_id}
  GET    /kyc/status -> {overall_status, kyc_calls_blocked, verifications}   (real path in test mode too)
Errors are {api_id, error, message}. Every URL is built here from settings; nothing from a request picks the host.
"""
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.runtime.providers.numbers.base import (
    InsufficientBalance, InventoryNumber, KycResult, KycStatus, NotConfigured, NumberNotFound, NumberProvider,
    NumberUnavailable, OwnedNumber, Page, ProviderAuthError, ProviderUnavailable, ProviderUncertain, ProviderValidationError,
    Subaccount, Trunk,
)

logger = logging.getLogger("choranta.runtime.numbers.vobiz")

TIMEOUT = httpx.Timeout(20.0, connect=8.0)


def _float(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _owned(item: Dict[str, Any]) -> OwnedNumber:
    return OwnedNumber(
        e164=item.get("e164") or "", provider_number_id=item.get("id"), country=item.get("country"),
        region=item.get("region"), capabilities=dict(item.get("capabilities") or {}), status=item.get("status"),
        setup_fee=_float(item.get("setup_fee")), monthly_fee=_float(item.get("monthly_fee")), currency=item.get("currency"),
        application_id=item.get("application_id") or None, trunk_id=item.get("trunk_group_id") or item.get("trunk_id") or None,
        purchased_at=item.get("purchased_at"), next_billing_date=item.get("next_billing_date"),
        raw={k: v for k, v in item.items() if k in (
            "status", "is_blocked", "is_trial_number", "voice_enabled", "aadhaar_verification_required",
            "aadhaar_verified", "minimum_commitment_months", "source", "last_billing_date", "next_billing_date", "tags")},
    )


class VobizNumberProvider(NumberProvider):
    name = "vobiz"

    def __init__(self, auth_id: Optional[str] = None, auth_token: Optional[str] = None, base_url: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self._auth_id = auth_id or settings.VOBIZ_AUTH_ID
        self._auth_token = auth_token or settings.VOBIZ_AUTH_TOKEN
        self._base = (base_url or settings.VOBIZ_API_BASE or "").rstrip("/")
        self._transport = transport  # tests pass httpx.MockTransport

    # ------------------------------------------------------------ http

    def _account(self) -> str:
        if not (self._auth_id and self._auth_token and self._base):
            raise NotConfigured("Vobiz isn't configured: set VOBIZ_AUTH_ID and VOBIZ_AUTH_TOKEN.")
        return f"{self._base}/Account/{quote(self._auth_id, safe='')}"

    def _request(self, method: str, url: str, *, mutating: bool, params: Optional[Dict[str, Any]] = None,
                 json: Optional[Dict[str, Any]] = None, not_found=NumberNotFound) -> Any:
        headers = {"X-Auth-ID": self._auth_id or "", "X-Auth-Token": self._auth_token or "", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
                response = client.request(method, url, params=params, json=json, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The connection never opened, so Vobiz can't have acted on it
            raise ProviderUnavailable(f"Couldn't reach Vobiz ({type(exc).__name__}).") from exc
        except httpx.HTTPError as exc:
            if mutating:
                raise ProviderUncertain(f"Vobiz didn't answer in time ({type(exc).__name__}); the change may or may not "
                                        "have gone through.") from exc
            raise ProviderUnavailable(f"Vobiz didn't answer in time ({type(exc).__name__}).") from exc
        return self._check(response, mutating=mutating, not_found=not_found)

    @staticmethod
    def _check(response: httpx.Response, *, mutating: bool, not_found) -> Any:
        if response.status_code < 400:
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {}
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        code = str(body.get("error") or "") or None
        message = str(body.get("message") or body.get("error") or response.reason_phrase or "")[:300]
        text = f"{code or ''} {message}".lower()
        status = response.status_code
        detail = f"Vobiz: {message or status}"
        if status in (401, 403):
            raise ProviderAuthError("Vobiz rejected Choranta's credentials (check VOBIZ_AUTH_ID / VOBIZ_AUTH_TOKEN).",
                                    provider_code=code)
        if status == 402 or "insufficient" in text or "low balance" in text:
            raise InsufficientBalance(f"{detail}. Top up the Vobiz account balance.", provider_code=code)
        if status == 404:
            raise not_found(detail, provider_code=code)
        if status == 429:
            raise ProviderUnavailable(f"{detail} (rate limited; try again shortly).", provider_code=code)
        if status >= 500:
            if mutating:
                raise ProviderUncertain(f"{detail} (the change may or may not have gone through).", provider_code=code)
            raise ProviderUnavailable(detail, provider_code=code)
        raise ProviderValidationError(detail, provider_code=code, details={k: v for k, v in body.items()
                                                                            if k in ("cool_off_until", "cool_off_remaining_seconds")})

    @staticmethod
    def _plus(e164: str) -> str:
        return quote(e164, safe="")  # "+" must travel as %2B

    # ------------------------------------------------------------ operations

    def search_inventory(self, *, country=None, search=None, page=1, per_page=25) -> Page:
        params = {"page": page, "per_page": min(max(per_page, 1), 100)}
        if country:
            params["country"] = country
        if search:
            params["search"] = search
        body = self._request("GET", f"{self._account()}/inventory/numbers", mutating=False, params=params)
        items = [
            InventoryNumber(e164=i.get("e164") or "", country=i.get("country"), region=i.get("region"),
                            provider_number_id=i.get("id"), setup_fee=_float(i.get("setup_fee")),
                            monthly_fee=_float(i.get("monthly_fee")), currency=i.get("currency"), status=i.get("status"))
            for i in (body.get("items") or []) if i.get("e164")
        ]
        return Page(items, int(body.get("page") or page), int(body.get("per_page") or params["per_page"]), body.get("total"))

    def list_owned(self, *, page=1, per_page=100) -> Page:
        per_page = min(max(per_page, 1), 100)
        body = self._request("GET", f"{self._account()}/numbers", mutating=False,
                             params={"limit": per_page, "offset": (page - 1) * per_page})
        items = [_owned(i) for i in (body.get("items") or []) if i.get("e164")]
        return Page(items, page, per_page, body.get("total"))

    def purchase(self, e164: str, currency: str) -> OwnedNumber:
        body = self._request("POST", f"{self._account()}/numbers/purchase-from-inventory", mutating=True,
                             json={"e164": e164, "currency": currency}, not_found=NumberUnavailable)
        number = body.get("number") or {}
        if not number.get("e164"):
            # A 2xx without the number: treat as unknown rather than success
            raise ProviderUncertain("Vobiz accepted the purchase but didn't return the number.")
        logger.info("Bought %s on Vobiz (%s)", number.get("e164"), number.get("id"))
        return _owned(number)

    def release(self, e164: str) -> None:
        self._request("DELETE", f"{self._account()}/numbers/{quote(e164.lstrip('+'), safe='')}", mutating=True)
        logger.info("Released %s on Vobiz", e164)

    def attach_application(self, e164: str, application_id: str) -> None:
        self._request("POST", f"{self._account()}/numbers/{self._plus(e164)}/application", mutating=True,
                      json={"application_id": application_id})

    def assign_trunk(self, e164: str, trunk_id: str) -> None:
        self._request("POST", f"{self._account()}/numbers/{self._plus(e164)}/assign", mutating=True,
                      json={"trunk_group_id": trunk_id})

    def unassign_trunk(self, e164: str) -> None:
        self._request("DELETE", f"{self._account()}/numbers/{self._plus(e164)}/assign", mutating=True)

    def list_trunks(self) -> List[Trunk]:
        body = self._request("GET", f"{self._account()}/trunks", mutating=False)
        return [Trunk(id=t["trunk_id"], name=t.get("name") or t["trunk_id"]) for t in (body.get("objects") or []) if t.get("trunk_id")]

    def create_subaccount(self, *, name, email, phone, description, kyc_mode, business_type=None) -> Subaccount:
        self._account()
        body = {"name": name[:100], "description": description, "kyc_mode": kyc_mode, "enabled": True}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if business_type:
            body["business_type"] = business_type
        result = self._request("POST", f"{self._base}/accounts/{quote(self._auth_id, safe='')}/sub-accounts/",
                               mutating=True, json=body)
        creds = result.get("auth_credentials") or result.get("sub_account") or {}
        if not (creds.get("auth_id") and creds.get("auth_token")):
            raise ProviderUncertain("Vobiz accepted the sub-account but didn't return its credentials.")
        logger.info("Created Vobiz sub-account %s (%s)", creds["auth_id"], kyc_mode)
        return Subaccount(auth_id=creds["auth_id"], auth_token=creds["auth_token"],
                          kyc_mode=(result.get("sub_account") or {}).get("kyc_mode") or kyc_mode)

    def update_subaccount(self, sub_auth_id, *, business_type=None, enabled=None) -> None:
        self._account()
        body = {k: v for k, v in (("business_type", business_type), ("enabled", enabled)) if v is not None}
        self._request("PUT", f"{self._base}/accounts/{quote(self._auth_id, safe='')}/sub-accounts/{quote(sub_auth_id, safe='')}",
                      mutating=True, json=body)

    def create_application(self, *, name, answer_url) -> str:
        body = self._request("POST", f"{self._account()}/Application/", mutating=True,
                             json={"app_name": name[:100], "answer_url": answer_url, "answer_method": "POST"})
        app_id = body.get("app_id")
        if not app_id:
            raise ProviderUncertain("Vobiz accepted the application but didn't return its id.")
        return str(app_id)

    # ------------------------------------------------------------ customer KYC

    def _kyc(self, sub_auth_id: str, step: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self._account()
        test = "test/" if settings.VOBIZ_KYC_TEST_MODE else ""
        url = f"{self._base}/sub-accounts/{test}{quote(sub_auth_id, safe='')}/kyc/{step}"
        # Re-running a check is harmless, so a lost answer is just "try again"
        return self._request("POST", url, mutating=False, json=body)

    @staticmethod
    def _result(kind: str, body: Dict[str, Any]) -> KycResult:
        blocked = body.get("kyc_calls_blocked")
        return KycResult(kind=kind, status=str(body.get("status") or "pending").lower(),
                         calls_blocked=blocked if isinstance(blocked, bool) else None,
                         name=body.get("registered_name") or body.get("legal_name") or body.get("company_name"),
                         message=body.get("message"))

    def kyc_verify_pan(self, sub_auth_id, pan) -> KycResult:
        return self._result("pan", self._kyc(sub_auth_id, "verify-pan", {"pan": pan}))

    def kyc_verify_gst(self, sub_auth_id, gstin) -> KycResult:
        return self._result("gst", self._kyc(sub_auth_id, "verify-gst", {"gstin": gstin}))

    def kyc_cin_search(self, sub_auth_id, company_name) -> List[Dict[str, str]]:
        body = self._kyc(sub_auth_id, "cin/search", {"company_name": company_name})
        return [{"cin": m["cin"], "company_name": m.get("company_name") or "", "status": m.get("status") or ""}
                for m in (body.get("matches") or []) if m.get("cin")]

    def kyc_cin_confirm(self, sub_auth_id, company_name, cin) -> KycResult:
        return self._result("cin", self._kyc(sub_auth_id, "cin/confirm", {"company_name": company_name, "selected_cin": cin}))

    def kyc_digilocker_initiate(self, sub_auth_id, redirect_url, state) -> Dict[str, str]:
        body = self._kyc(sub_auth_id, "digilocker/initiate", {"redirect_url": redirect_url, "oauth_state": state})
        if not (body.get("auth_url") and body.get("access_request_id")):
            raise ProviderUnavailable("Vobiz didn't return a DigiLocker link. Try again.")
        return {"auth_url": body["auth_url"], "access_request_id": body["access_request_id"]}

    def kyc_digilocker_verify(self, sub_auth_id, access_request_id) -> KycResult:
        return self._result("aadhaar", self._kyc(sub_auth_id, "digilocker/verify", {"access_request_id": access_request_id}))

    def kyc_status(self, sub_auth_id) -> Optional[KycStatus]:
        self._account()
        body = self._request("GET", f"{self._base}/sub-accounts/{quote(sub_auth_id, safe='')}/kyc/status", mutating=False)
        return KycStatus(overall=str(body.get("overall_status") or "not_started"),
                         calls_blocked=bool(body.get("kyc_calls_blocked", True)),
                         checks={k: str(v) for k, v in (body.get("verifications") or {}).items()})

    def _subaccount_url(self, e164: str) -> str:
        self._account()
        return f"{self._base}/account/{quote(self._auth_id, safe='')}/numbers/{self._plus(e164)}/assign-subaccount"

    def assign_subaccount(self, e164: str, sub_auth_id: str) -> None:
        self._request("POST", self._subaccount_url(e164), mutating=True, json={"sub_account_id": sub_auth_id})

    def unassign_subaccount(self, e164: str) -> None:
        self._request("DELETE", self._subaccount_url(e164), mutating=True)

    def balance(self, currency: str) -> Optional[float]:
        body = self._request("GET", f"{self._account()}/balance/{quote(currency, safe='')}", mutating=False)
        return _float(body.get("available_balance", body.get("balance")))
