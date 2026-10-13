"""
Exotel ExoPhone provisioning: search, buy and release numbers on Choranta's Exotel account.

Uses the v2_beta IncomingPhoneNumbers API (form-encoded, basic auth with the API key and token).
Every Exotel URL and payload lives here, so a switch to Exotel's newer /v2 format touches only this file.
In the test environment, or with EXOTEL_NUMBERS_MOCK=true, it returns fake numbers and never calls Exotel.
"""
import logging
import random
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("choranta.services.exotel_numbers")

NUMBER_TYPES = ("Landline", "Mobile", "TollFree")


class ExotelNumberError(Exception):
    pass


def _mock() -> bool:
    return settings.ENVIRONMENT == "test" or bool(getattr(settings, "EXOTEL_NUMBERS_MOCK", False))


def _base() -> str:
    sid = settings.EXOTEL_ACCOUNT_SID
    if not (sid and settings.EXOTEL_API_KEY and settings.EXOTEL_API_TOKEN):
        raise ExotelNumberError("Exotel isn't configured: set EXOTEL_ACCOUNT_SID, EXOTEL_API_KEY and EXOTEL_API_TOKEN.")
    return f"https://{settings.EXOTEL_SUBDOMAIN}/v2_beta/Accounts/{sid}"


def _auth():
    return (settings.EXOTEL_API_KEY, settings.EXOTEL_API_TOKEN)


def _check(response: httpx.Response, action: str) -> Any:
    if response.status_code >= 400:
        try:
            body = response.json()
            detail = (body.get("RestException") or {}).get("Message") or body.get("message") or response.text
        except ValueError:
            detail = response.text
        raise ExotelNumberError(f"Exotel couldn't {action}: {detail or response.status_code}")
    return response.json() if response.content else {}


def flow_voice_url() -> str:
    """The Exotel flow (with our Voicebot applet) that inbound calls to a number should run."""
    return f"http://my.exotel.com/{settings.EXOTEL_ACCOUNT_SID}/exoml/start_voice/{settings.EXOTEL_FLOW_ID}"


def _field(item: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if item.get(name) not in (None, ""):
            return item[name]
    return None


def search_available(country: str = "IN", number_type: str = "Landline", region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Numbers Exotel can sell right now: [{phone_number, region, number_type, exotel_monthly_rental}]."""
    if number_type not in NUMBER_TYPES:
        raise ExotelNumberError(f"Number type must be one of {', '.join(NUMBER_TYPES)}.")
    if _mock():
        prefix = {"Landline": "+9140", "Mobile": "+9198", "TollFree": "+91180"}[number_type]
        digits = 13 - len(prefix)  # +91 and 10 digits
        return [
            {"phone_number": f"{prefix}{random.randint(0, 10**digits - 1):0{digits}d}",
             "region": region or "TG", "number_type": number_type, "exotel_monthly_rental": None}
            for _ in range(6)
        ]
    params = {"InRegion": region} if region else {}
    try:
        response = httpx.get(f"{_base()}/AvailablePhoneNumbers/{country}/{number_type}", params=params, auth=_auth(), timeout=20.0)
    except httpx.HTTPError as exc:
        raise ExotelNumberError(f"Couldn't reach Exotel: {exc}") from exc
    body = _check(response, "list available numbers")
    items = body if isinstance(body, list) else (body.get("available_phone_numbers") or body.get("AvailablePhoneNumbers") or [])
    results = []
    for item in items:
        number = _field(item, "phone_number", "PhoneNumber")
        if number:
            results.append({
                "phone_number": number,
                "region": _field(item, "region", "Region", "in_region"),
                "number_type": number_type,
                "exotel_monthly_rental": _field(item, "rental_price", "RentalPrice", "monthly_rental"),
            })
    return results


def purchase(phone_number: str, friendly_name: str) -> Dict[str, Any]:
    """Buys a number on our Exotel account and points it at the voice flow. Returns {sid, phone_number}."""
    if _mock():
        return {"sid": f"mock_{phone_number.lstrip('+')}", "phone_number": phone_number}
    data = {"PhoneNumber": phone_number, "VoiceUrl": flow_voice_url(), "FriendlyName": friendly_name[:64]}
    try:
        response = httpx.post(f"{_base()}/IncomingPhoneNumbers", data=data, auth=_auth(), timeout=30.0)
    except httpx.HTTPError as exc:
        raise ExotelNumberError(f"Couldn't reach Exotel: {exc}") from exc
    body = _check(response, "buy this number")
    item = body.get("incoming_phone_number") or body.get("IncomingPhoneNumber") or body.get("response", {}).get("data") or body
    sid = _field(item, "sid", "Sid")
    if not sid:
        raise ExotelNumberError("Exotel didn't return the new number's id.")
    logger.info(f"Bought ExoPhone {phone_number} ({sid})")
    return {"sid": sid, "phone_number": _field(item, "phone_number", "PhoneNumber") or phone_number}


def release(exophone_sid: str) -> None:
    """Returns a number to Exotel so we stop paying for it."""
    if _mock() or not exophone_sid or exophone_sid.startswith("mock_"):
        return
    try:
        response = httpx.delete(f"{_base()}/IncomingPhoneNumbers/{exophone_sid}", auth=_auth(), timeout=20.0)
    except httpx.HTTPError as exc:
        raise ExotelNumberError(f"Couldn't reach Exotel: {exc}") from exc
    if response.status_code == 404:
        return  # already gone
    _check(response, "release this number")
    logger.info(f"Released ExoPhone {exophone_sid}")
