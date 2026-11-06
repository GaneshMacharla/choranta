"""
Business verification (KYC) for renting phone numbers, the way Vobiz recommends for resellers (2026-11-03): each
client is verified by Vobiz in their own name, on their own Vobiz sub-account (kyc_mode customer_use), without
leaving Choranta. The client types their documents' numbers here and Choranta passes each one to Vobiz's KYC API;
nothing is uploaded.

Vobiz offers two kinds of KYC today:
- INDIVIDUAL (anyone without a business PAN, sole proprietors included): PAN + Aadhaar through DigiLocker
- BUSINESS (a business PAN): PAN + GSTIN, or PAN + CIN (found by company name)

Vobiz decides when the client is through: it unblocks the sub-account's calls (kyc_calls_blocked false), and the
client can buy numbers from then on. Where Vobiz doesn't say (the mock carrier), the required checks above decide.
Documents can be retried as often as needed; a "pending" one is re-checked with Vobiz when the page is refreshed.
"""
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ChorantaException, NotFoundException, ValidationException
from app.models.client import Client
from app.models.verification import ClientVerification
from app.runtime.providers.numbers import KycResult, NumberProvider, NumberProviderError, mock_mode
from app.services import carrier_subaccounts, notifications, number_service

logger = logging.getLogger("choranta.services.verifications")

KYC_TYPES: Dict[str, Dict[str, Any]] = {
    "INDIVIDUAL": {"label": "Individual", "business_type": "individual",
                   "hint": "No business PAN, or a sole proprietorship: your PAN and Aadhaar."},
    "BUSINESS": {"label": "Business", "business_type": "private_limited",
                 "hint": "Your business has its own PAN: business PAN plus GSTIN or company registration (CIN)."},
}
CHECK_LABELS = {"pan": "PAN", "gst": "GSTIN", "cin": "Company registration (CIN)", "aadhaar": "Aadhaar (DigiLocker)"}
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerificationRequired(ChorantaException):
    def __init__(self, status: Optional[str]):
        message = {
            None: "Verify your business before buying a number. It's a one-time step required by telecom rules.",
            "IN_PROGRESS": "Finish verifying your business to buy numbers.",
        }.get(status, "Verify your business before buying a number.")
        super().__init__(message, status_code=403, details={"code": "VERIFICATION_REQUIRED", "status": status})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get(db: Session, client_id: str) -> Optional[ClientVerification]:
    return (db.query(ClientVerification)
            .filter(ClientVerification.client_id == client_id, ClientVerification.is_mock.is_(mock_mode())).first())


def _require(db: Session, client_id: str) -> ClientVerification:
    v = get(db, client_id)
    if not v:
        raise ValidationException("Choose Individual or Business first.")
    return v


def require_verified(db: Session, client_id: str) -> None:
    v = get(db, client_id)
    if not v or v.status != "VERIFIED":
        raise VerificationRequired(v.status if v else None)


def _carrier_error(exc: NumberProviderError) -> ChorantaException:
    return ChorantaException(f"Verification service: {exc.message}", status_code=exc.status_code,
                             details={"code": exc.code})


# ---------------------------------------------------------------- state

def _required_done(v: ClientVerification) -> bool:
    done = {k for k, c in (v.checks or {}).items() if c.get("status") == "verified"}
    if v.kyc_type == "INDIVIDUAL":
        return {"pan", "aadhaar"} <= done
    return "pan" in done and bool({"gst", "cin"} & done)


def _settle(db: Session, v: ClientVerification, calls_blocked: Optional[bool]) -> None:
    """Vobiz's verdict when it gives one, else the required checks; tells the client the moment they're through."""
    blocked = calls_blocked if calls_blocked is not None else not _required_done(v)
    was = v.status
    v.calls_blocked = blocked
    v.status = "IN_PROGRESS" if blocked else "VERIFIED"
    if v.status == "VERIFIED" and was != "VERIFIED":
        v.verified_at = _now()
        notifications.notify(db, v.client_id, "VERIFICATION_APPROVED", "Your business is verified",
                             "You can now get phone numbers for your AI employees.", link="/portal/numbers", level="success")
        logger.info("Client %s verified (%s)", v.client_id, v.kyc_type)
    db.commit()


def _record(db: Session, v: ClientVerification, result: KycResult, value: Optional[str]) -> ClientVerification:
    checks = dict(v.checks or {})
    checks[result.kind] = {"status": result.status, "value": value, "name": result.name,
                           "message": result.message if result.status != "verified" else None,
                           "checked_at": _now().isoformat()}
    v.checks = checks
    _settle(db, v, result.calls_blocked)
    return v


def _editable(v: ClientVerification) -> None:
    if v.status == "VERIFIED":
        raise ValidationException("Your business is already verified.")


# ---------------------------------------------------------------- steps

def start(db: Session, client_id: str, kyc_type: str, email: str, actor: number_service.Actor) -> ClientVerification:
    """Chooses Individual or Business and opens the client's Vobiz sub-account to verify on."""
    kyc_type = (kyc_type or "").upper()
    if kyc_type not in KYC_TYPES:
        raise ValidationException("Choose Individual or Business.")
    email = (email or "").strip()
    if not EMAIL_RE.match(email):
        raise ValidationException("Enter a valid email address.")
    client = db.get(Client, client_id)
    if not client:
        raise NotFoundException("Client", client_id)
    business_type = KYC_TYPES[kyc_type]["business_type"]
    v = get(db, client_id)
    if v:
        _editable(v)
        if v.kyc_type != kyc_type and any(c.get("status") == "verified" for c in (v.checks or {}).values()):
            raise ValidationException("Some documents are already verified, so the type can't change now. "
                                      "Contact support if you chose the wrong one.")

    with number_service.carrier(db) as provider:
        try:
            sub = carrier_subaccounts.ensure(db, provider, client, actor, email=email, business_type=business_type)
            if sub.business_type != business_type:
                provider.update_subaccount(sub.auth_id, business_type=business_type)
                sub.business_type = business_type
        except NumberProviderError as exc:
            raise _carrier_error(exc)

    if not v:
        v = ClientVerification(client_id=client_id, is_mock=mock_mode(), checks={})
        db.add(v)
    if v.kyc_type != kyc_type:
        v.checks = {}
        v.digilocker = None
    v.client_name = client.name
    v.kyc_type, v.email, v.sub_auth_id = kyc_type, email, sub.auth_id
    v.status, v.calls_blocked = "IN_PROGRESS", True
    db.commit()
    return v


def _check(db: Session, client_id: str, step: str, call) -> ClientVerification:
    v = _require(db, client_id)
    _editable(v)
    with number_service.carrier(db) as provider:
        try:
            return call(v, provider)
        except NumberProviderError as exc:
            logger.warning("KYC %s for client %s failed at the carrier: %s", step, client_id, exc.message)
            raise _carrier_error(exc)


def _test_inputs() -> bool:
    """Vobiz's KYC test mode takes magic inputs (TESTSUCCESS0001...) that aren't real document numbers."""
    return bool(settings.VOBIZ_KYC_TEST_MODE) and not mock_mode()


def verify_pan(db: Session, client_id: str, pan: str) -> ClientVerification:
    pan = (pan or "").strip().upper()
    if not PAN_RE.match(pan) and not _test_inputs():
        raise ValidationException("Enter a valid PAN (e.g. ABCDE1234F).")

    def call(v: ClientVerification, provider: NumberProvider):
        if v.kyc_type == "BUSINESS" and PAN_RE.match(pan) and pan[3] == "P":
            raise ValidationException("That's a personal PAN. Choose Individual instead, or enter your business's PAN.")
        return _record(db, v, provider.kyc_verify_pan(v.sub_auth_id, pan), pan)
    return _check(db, client_id, "pan", call)


def verify_gst(db: Session, client_id: str, gstin: str) -> ClientVerification:
    gstin = (gstin or "").strip().upper()
    if not GSTIN_RE.match(gstin) and not _test_inputs():
        raise ValidationException("Enter a valid 15-character GSTIN.")

    def call(v: ClientVerification, provider: NumberProvider):
        if v.kyc_type != "BUSINESS":
            raise ValidationException("GSTIN is for Business verification.")
        pan = ((v.checks or {}).get("pan") or {}).get("value")
        if pan and PAN_RE.match(pan) and gstin[2:12] != pan:
            raise ValidationException("This GSTIN belongs to a different PAN (characters 3-12 of a GSTIN are the PAN).")
        return _record(db, v, provider.kyc_verify_gst(v.sub_auth_id, gstin), gstin)
    return _check(db, client_id, "gst", call)


def cin_search(db: Session, client_id: str, company_name: str) -> List[Dict[str, str]]:
    company_name = " ".join((company_name or "").split())
    if len(company_name) < 3:
        raise ValidationException("Enter your registered company name.")

    def call(v: ClientVerification, provider: NumberProvider):
        if v.kyc_type != "BUSINESS":
            raise ValidationException("Company registration is for Business verification.")
        return provider.kyc_cin_search(v.sub_auth_id, company_name)
    return _check(db, client_id, "cin search", call)


def cin_confirm(db: Session, client_id: str, company_name: str, cin: str) -> ClientVerification:
    company_name = " ".join((company_name or "").split())
    cin = (cin or "").strip().upper()
    if (not CIN_RE.match(cin) and not _test_inputs()) or len(company_name) < 3:
        raise ValidationException("Pick your company from the search results.")

    def call(v: ClientVerification, provider: NumberProvider):
        if v.kyc_type != "BUSINESS":
            raise ValidationException("Company registration is for Business verification.")
        return _record(db, v, provider.kyc_cin_confirm(v.sub_auth_id, company_name, cin), cin)
    return _check(db, client_id, "cin", call)


def _check_return_url(url: str) -> str:
    """DigiLocker sends the client back here, so it must be one of Choranta's own web addresses."""
    parsed = urlparse(url or "")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.scheme not in ("http", "https") or origin not in [o.rstrip("/") for o in settings.CORS_ORIGINS]:
        raise ValidationException("Invalid return address.")
    return url


def aadhaar_start(db: Session, client_id: str, return_url: str) -> Dict[str, str]:
    """Where to send the client to approve sharing their Aadhaar from DigiLocker."""
    return_url = _check_return_url(return_url)

    def call(v: ClientVerification, provider: NumberProvider):
        if v.kyc_type != "INDIVIDUAL":
            raise ValidationException("Aadhaar is for Individual verification.")
        state = secrets.token_urlsafe(24)
        started = provider.kyc_digilocker_initiate(v.sub_auth_id, return_url, state)
        v.digilocker = {"state": state, "access_request_id": started["access_request_id"]}
        db.commit()
        return {"auth_url": started["auth_url"]}
    return _check(db, client_id, "digilocker initiate", call)


def aadhaar_complete(db: Session, client_id: str, state: str) -> ClientVerification:
    """The client is back from DigiLocker: has Vobiz got their Aadhaar?"""
    def call(v: ClientVerification, provider: NumberProvider):
        pending = v.digilocker or {}
        if not state or not secrets.compare_digest(str(pending.get("state") or ""), state):
            raise ValidationException("This DigiLocker session has expired. Start the Aadhaar step again.")
        result = provider.kyc_digilocker_verify(v.sub_auth_id, pending["access_request_id"])
        v.digilocker = None
        return _record(db, v, result, None)
    return _check(db, client_id, "digilocker verify", call)


def refresh(db: Session, client_id: str) -> ClientVerification:
    """Re-reads the client's KYC from Vobiz (pending documents settle there)."""
    def call(v: ClientVerification, provider: NumberProvider):
        status = provider.kyc_status(v.sub_auth_id)
        if status is None:
            return v
        checks = dict(v.checks or {})
        for kind, state in status.checks.items():
            if kind in checks and state in ("verified", "failed", "pending") and checks[kind].get("status") != state:
                checks[kind] = {**checks[kind], "status": state, "checked_at": _now().isoformat()}
        v.checks = checks
        _settle(db, v, status.calls_blocked)
        return v
    v = _require(db, client_id)
    if v.status == "VERIFIED":
        return v
    return _check(db, client_id, "status", call)


# ---------------------------------------------------------------- output

def out(db: Session, v: Optional[ClientVerification]) -> Dict[str, Any]:
    types = {k: {"label": t["label"], "hint": t["hint"]} for k, t in KYC_TYPES.items()}
    if not v:
        return {"status": "NOT_STARTED", "kyc_types": types, "mock": mock_mode(), "test_inputs": _test_inputs()}
    client = db.get(Client, v.client_id) if v.client_id else None
    return {
        "client_id": v.client_id,
        "client_name": client.name if client else v.client_name,
        "client_code": client.client_code if client else None,
        "status": v.status,
        "kyc_type": v.kyc_type,
        "email": v.email,
        "calls_blocked": v.calls_blocked,
        "checks": {k: {**c, "label": CHECK_LABELS.get(k, k)} for k, c in (v.checks or {}).items()},
        "verified_at": v.verified_at,
        "updated_at": v.updated_at,
        "created_at": v.created_at,
        "kyc_types": types,
        "mock": v.is_mock,
        "test_inputs": _test_inputs(),
    }


def list_all(db: Session, status: Optional[str] = None) -> List[Dict[str, Any]]:
    query = db.query(ClientVerification).filter(ClientVerification.is_mock.is_(mock_mode()))
    if status:
        query = query.filter(ClientVerification.status == status)
    return [out(db, v) for v in query.order_by(ClientVerification.updated_at.desc()).all()]
