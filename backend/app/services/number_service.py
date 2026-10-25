"""
Phone numbers on Choranta's carrier account: search what's for sale, buy, release, and report what we own.
Assigning numbers to clients is services/number_assignments.py; catching up with the carrier is
services/number_reconciliation.py. The carrier is reached only through runtime/providers/numbers.

Buying is never assumed to have worked:
1. The same idempotency key returns the first attempt's operation instead of buying again; a second purchase of a
   number whose first one is still open or uncertain is refused.
2. The number must still be for sale at the price staff confirmed, and the carrier balance must cover it.
3. A PENDING operation is committed before the carrier is called.
4. A timeout or 5xx is UNCERTAIN: the carrier's owned list is read (never a blind retry) and the number is
   recorded only if it's really there (RECOVERED).
5. If the carrier bought it but our own save fails, the operation is marked NEEDS_RECONCILIATION in a fresh
   session, with what the carrier returned, and sync adopts the number later. It is not reported as failed.
"""
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.client import Client
from app.models.numbers import NumberAssignment, NumberOperation, ProviderNumber
from app.runtime.providers.numbers import (
    NumberNotFound, NumberProvider, NumberProviderError, OwnedNumber, ProviderUncertain, mock_mode, number_provider,
)
from app.runtime.providers.numbers.mock import SCENARIO_LABELS

logger = logging.getLogger("choranta.services.number_service")

E164 = re.compile(r"^\+[1-9]\d{6,14}$")
OPEN_STATUSES = ("PENDING", "UNCERTAIN", "NEEDS_RECONCILIATION")
DONE_STATUSES = ("SUCCEEDED", "RECOVERED")
NUMBER_TYPES = ("Landline", "Mobile", "TollFree")


class NumberServiceError(Exception):
    """A refusal or failure with an HTTP status, a stable code and a message safe to show staff."""

    def __init__(self, status_code: int, code: str, message: str, operation: Optional[NumberOperation] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message
        self.operation, self.details = operation, details or {}


@dataclass
class Actor:
    label: str                     # "ADMIN a@b.com", "CLIENT owner@x.com", "SYSTEM"
    user_id: Optional[str] = None

    @classmethod
    def of(cls, user: Any) -> "Actor":
        return cls(f"{user.role} {user.email}", user.id)


SYSTEM = Actor("SYSTEM")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_e164(value: str) -> str:
    number = re.sub(r"[\s\-().]", "", value or "")
    if not E164.match(number):
        raise NumberServiceError(400, "invalid_number", "Give the number in E.164 format, e.g. +918045678901.")
    return number


def derive_type(e164: str) -> Optional[str]:
    """India only (the carrier doesn't say): 1800 is toll-free, 6-9 starts a mobile, anything else is a landline."""
    if not e164.startswith("+91"):
        return None
    rest = e164[3:]
    if rest.startswith("1800") or rest.startswith("180"):
        return "TollFree"
    return "Mobile" if rest[:1] in "6789" else "Landline"


@contextmanager
def carrier(db: Session) -> Iterator[NumberProvider]:
    provider = number_provider(db)
    try:
        yield provider
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()


def _fail(exc: NumberProviderError, operation: Optional[NumberOperation] = None) -> NumberServiceError:
    return NumberServiceError(exc.status_code, exc.code, exc.message, operation, exc.details)


# ---------------------------------------------------------------- serialising

def operation_out(op: NumberOperation) -> Dict[str, Any]:
    return {
        "id": op.id, "operation_type": op.operation_type, "operation_status": op.operation_status, "e164": op.e164,
        "provider": op.provider, "provider_number_id": op.provider_number_id, "client_id": op.client_id,
        "error_code": op.error_code, "error_message": op.error_message, "actor": op.actor, "is_mock": op.is_mock,
        "request": op.request or {}, "result": op.result or {}, "created_at": op.created_at, "updated_at": op.updated_at,
    }


def active_assignment(db: Session, number_id: str) -> Optional[NumberAssignment]:
    return (db.query(NumberAssignment)
            .filter(NumberAssignment.provider_number_id == number_id, NumberAssignment.status == "ACTIVE").first())


def assignment_out(db: Session, a: NumberAssignment) -> Dict[str, Any]:
    client = db.get(Client, a.client_id)
    agent = db.get(Agent, a.agent_id) if a.agent_id else None
    return {
        "id": a.id, "client_id": a.client_id, "client_name": client.name if client else None,
        "agent_id": a.agent_id, "agent_name": agent.name if agent else None, "trunk_id": a.trunk_id,
        "phone_number_id": a.phone_number_id, "status": a.status, "assigned_by": a.assigned_by, "ended_by": a.ended_by,
        "end_reason": a.end_reason, "assigned_at": a.assigned_at, "released_at": a.released_at,
    }


def number_out(db: Session, pn: ProviderNumber, detail: bool = False) -> Dict[str, Any]:
    current = active_assignment(db, pn.id)
    out = {
        "id": pn.id, "provider": pn.provider, "provider_number_id": pn.provider_number_id, "e164": pn.e164,
        "country": pn.country, "region": pn.region, "number_type": pn.number_type,
        "number_type_derived": pn.number_type_derived, "capabilities": pn.capabilities or {},
        "provider_status": pn.provider_status, "internal_status": pn.internal_status,
        "monthly_cost": pn.monthly_cost, "setup_cost": pn.setup_cost, "currency": pn.currency,
        "application_id": pn.application_id, "trunk_id": pn.trunk_id, "is_mock": pn.is_mock, "attention": pn.attention,
        "purchased_at": pn.purchased_at, "last_synced_at": pn.last_synced_at, "released_at": pn.released_at,
        "created_at": pn.created_at, "assignment": assignment_out(db, current) if current else None,
        "next_billing_date": (pn.raw or {}).get("next_billing_date"),
        "aadhaar_verification_required": bool((pn.raw or {}).get("aadhaar_verification_required")),
    }
    if detail:
        out["assignments"] = [assignment_out(db, a) for a in db.query(NumberAssignment)
                              .filter(NumberAssignment.provider_number_id == pn.id)
                              .order_by(NumberAssignment.assigned_at.desc()).all()]
        out["operations"] = [operation_out(o) for o in db.query(NumberOperation)
                             .filter((NumberOperation.provider_number_id == pn.id)
                                     | ((NumberOperation.e164 == pn.e164) & NumberOperation.provider_number_id.is_(None)))
                             .order_by(NumberOperation.created_at.desc()).limit(100).all()]
        out["raw"] = pn.raw or {}
    return out


# ---------------------------------------------------------------- reading

def provider_status(db: Session) -> Dict[str, Any]:
    status: Dict[str, Any] = {"mock_mode": mock_mode(), "provider": "vobiz", "configured": True, "balance": None,
                              "currency": settings.NUMBER_PURCHASE_CURRENCY,
                              "application_attached": bool(settings.VOBIZ_APPLICATION_ID) or mock_mode(), "error": None}
    try:
        with carrier(db) as provider:
            status["balance"] = provider.balance(settings.NUMBER_PURCHASE_CURRENCY)
    except NumberProviderError as exc:
        status["configured"] = exc.code != "not_configured"
        status["error"] = exc.message
    return status


def search_inventory(db: Session, *, country: Optional[str] = None, search: Optional[str] = None,
                     number_type: Optional[str] = None, region: Optional[str] = None,
                     page: int = 1, per_page: int = 25) -> Dict[str, Any]:
    """
    Numbers for sale. Country and number search are applied by the carrier; number type (worked out from the
    prefix) and region are filtered on the page the carrier returned, so a filtered page can be shorter.
    """
    if number_type and number_type not in NUMBER_TYPES:
        raise NumberServiceError(400, "invalid_number_type", f"Number type must be one of {', '.join(NUMBER_TYPES)}.")
    digits = re.sub(r"\D", "", search or "") or None
    try:
        with carrier(db) as provider:
            result = provider.search_inventory(country=(country or None) and country.upper(), search=digits,
                                               page=page, per_page=per_page)
            is_mock = provider.is_mock
    except NumberProviderError as exc:
        raise _fail(exc)
    owned = {e for (e,) in db.query(ProviderNumber.e164).filter(ProviderNumber.internal_status != "RELEASED").all()}
    items = []
    for n in result.items:
        kind = derive_type(n.e164)
        if n.e164 in owned or (number_type and kind != number_type):
            continue
        if region and region.lower() not in (n.region or "").lower():
            continue
        items.append({
            "e164": n.e164, "country": n.country, "region": n.region, "number_type": kind, "number_type_derived": True,
            "setup_fee": n.setup_fee, "monthly_fee": n.monthly_fee, "currency": n.currency, "available": True,
            "provider_number_id": n.provider_number_id, "is_mock": is_mock,
            "scenario": SCENARIO_LABELS.get(n.scenario) if n.scenario else None,
        })
    return {"items": items, "page": result.page, "per_page": result.per_page, "total": result.total, "mock_mode": is_mock}


def list_numbers(db: Session, *, status: Optional[str] = None, client_id: Optional[str] = None,
                 search: Optional[str] = None, capability: Optional[str] = None,
                 page: int = 1, per_page: int = 25) -> Dict[str, Any]:
    q = db.query(ProviderNumber)
    if status:
        q = q.filter(ProviderNumber.internal_status == status)
    else:
        q = q.filter(ProviderNumber.internal_status != "RELEASED")
    if client_id:
        q = q.join(NumberAssignment, (NumberAssignment.provider_number_id == ProviderNumber.id)
                   & (NumberAssignment.status == "ACTIVE")).filter(NumberAssignment.client_id == client_id)
    if search:
        q = q.filter(ProviderNumber.e164.contains(re.sub(r"[^\d+]", "", search)))
    rows = q.order_by(ProviderNumber.created_at.desc()).all()
    if capability:
        rows = [r for r in rows if (r.capabilities or {}).get(capability)]
    total = len(rows)
    start = (page - 1) * per_page
    return {"items": [number_out(db, r) for r in rows[start:start + per_page]], "page": page, "per_page": per_page,
            "total": total}


def get_number(db: Session, number_id: str) -> ProviderNumber:
    pn = db.get(ProviderNumber, number_id)
    if not pn:
        raise NumberServiceError(404, "not_found", "Phone number not found.")
    return pn


def list_operations(db: Session, *, status: Optional[str] = None, operation_type: Optional[str] = None,
                    e164: Optional[str] = None, page: int = 1, per_page: int = 50) -> Dict[str, Any]:
    q = db.query(NumberOperation)
    if status:
        q = q.filter(NumberOperation.operation_status == status)
    if operation_type:
        q = q.filter(NumberOperation.operation_type == operation_type)
    if e164:
        q = q.filter(NumberOperation.e164.contains(e164))
    total = q.count()
    rows = q.order_by(NumberOperation.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"items": [operation_out(o) for o in rows], "page": page, "per_page": per_page, "total": total}


# ---------------------------------------------------------------- recording what the carrier owns

def upsert_owned(db: Session, provider_name: str, owned: OwnedNumber, is_mock: bool) -> ProviderNumber:
    """Records (or refreshes) a number the carrier says Choranta owns. Never touches its assignment."""
    pn = db.query(ProviderNumber).filter(ProviderNumber.provider == provider_name, ProviderNumber.e164 == owned.e164).first()
    if pn is None:
        pn = ProviderNumber(id=generate_unique_id("pnm"), provider=provider_name, e164=owned.e164, is_mock=is_mock,
                            internal_status="AVAILABLE", number_type=derive_type(owned.e164), number_type_derived=True)
        db.add(pn)
    elif pn.internal_status in ("RELEASED", "NEEDS_RECONCILIATION"):
        assigned = active_assignment(db, pn.id) if pn.id else None
        pn.internal_status = "ASSIGNED" if assigned else "AVAILABLE"
        pn.released_at = None
        pn.attention = None
    pn.provider_number_id = owned.provider_number_id or pn.provider_number_id
    pn.country, pn.region = owned.country or pn.country, owned.region or pn.region
    pn.capabilities = owned.capabilities or pn.capabilities or {}
    pn.provider_status = owned.status or "active"
    pn.setup_cost = owned.setup_fee if owned.setup_fee is not None else pn.setup_cost
    pn.monthly_cost = owned.monthly_fee if owned.monthly_fee is not None else pn.monthly_cost
    pn.currency = owned.currency or pn.currency
    pn.application_id = owned.application_id or pn.application_id
    pn.trunk_id = owned.trunk_id if owned.trunk_id is not None else pn.trunk_id
    pn.raw = owned.raw or pn.raw or {}
    if owned.purchased_at and not pn.purchased_at:
        try:
            pn.purchased_at = datetime.fromisoformat(owned.purchased_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    pn.purchased_at = pn.purchased_at or utcnow()
    pn.last_synced_at = utcnow()
    db.flush()
    return pn


def _owned_result(owned: OwnedNumber) -> Dict[str, Any]:
    return {"e164": owned.e164, "provider_number_id": owned.provider_number_id, "status": owned.status,
            "setup_fee": owned.setup_fee, "monthly_fee": owned.monthly_fee, "currency": owned.currency}


def application_id(provider: NumberProvider) -> Optional[str]:
    if provider.is_mock:
        from app.runtime.providers.numbers.mock import MOCK_APPLICATION_ID
        return MOCK_APPLICATION_ID
    return settings.VOBIZ_APPLICATION_ID or None


def attach_application(db: Session, provider: NumberProvider, pn: ProviderNumber, actor: Actor) -> None:
    """Points the number's inbound calls at Choranta's answer URL. A failure is flagged, not fatal."""
    app_id = application_id(provider)
    if not app_id:
        pn.attention = "VOBIZ_APPLICATION_ID isn't set, so inbound calls to this number won't reach Choranta yet."
        db.commit()
        return
    op = NumberOperation(provider_number_id=pn.id, provider=pn.provider, e164=pn.e164, operation_type="ATTACH_APP",
                         actor=actor.label, actor_user_id=actor.user_id, is_mock=pn.is_mock,
                         request={"application_id": app_id})
    db.add(op)
    try:
        provider.attach_application(pn.e164, app_id)
        pn.application_id = app_id
        op.operation_status = "SUCCEEDED"
        if pn.attention and "inbound" in pn.attention:
            pn.attention = None
    except NumberProviderError as exc:
        op.operation_status = "UNCERTAIN" if isinstance(exc, ProviderUncertain) else "FAILED"
        op.error_code, op.error_message = exc.code, exc.message
        pn.attention = f"Couldn't route inbound calls to Choranta: {exc.message} Re-assign the number to try again."
    db.commit()


# ---------------------------------------------------------------- buying

def _mark_needs_reconciliation(db: Session, op_id: str, owned: OwnedNumber, error: Exception) -> None:
    """In a fresh session: the carrier bought it, our save didn't stick."""
    with Session(bind=db.get_bind()) as fresh:
        op = fresh.get(NumberOperation, op_id)
        if op:
            op.operation_status = "NEEDS_RECONCILIATION"
            op.error_code = "local_save_failed"
            op.error_message = f"Bought at the carrier, but saving it in Choranta failed ({type(error).__name__}). Sync to adopt it."
            op.result = _owned_result(owned)
            fresh.commit()


def purchase(db: Session, e164: str, *, idempotency_key: str, actor: Actor, currency: Optional[str] = None,
             expected_monthly_cost: Optional[float] = None, expected_setup_cost: Optional[float] = None,
             client_id: Optional[str] = None) -> NumberOperation:
    """
    Buys a number into Choranta's pool. Returns the PURCHASE operation: SUCCEEDED or RECOVERED (bought), UNCERTAIN
    (check again later) or NEEDS_RECONCILIATION (bought; sync adopts it). Refusals and failures raise.
    """
    e164 = normalize_e164(e164)
    currency = (currency or settings.NUMBER_PURCHASE_CURRENCY).upper()
    key = (idempotency_key or "").strip()
    if not key or len(key) > 128:
        raise NumberServiceError(400, "idempotency_key_required", "An idempotency key (up to 128 characters) is required.")

    earlier = db.query(NumberOperation).filter(NumberOperation.idempotency_key == key).first()
    if earlier:
        if earlier.operation_type != "PURCHASE" or earlier.e164 != e164:
            raise NumberServiceError(409, "idempotency_key_reused", "That idempotency key was used for a different request.")
        return earlier  # the same request again: nothing is bought twice
    open_op = (db.query(NumberOperation).filter(NumberOperation.operation_type == "PURCHASE", NumberOperation.e164 == e164,
                                               NumberOperation.operation_status.in_(OPEN_STATUSES)).first())
    if open_op:
        raise NumberServiceError(409, "purchase_in_progress",
                                 f"A purchase of {e164} is already {open_op.operation_status.lower().replace('_', ' ')}. "
                                 "Check that operation before trying again.", open_op)
    if db.query(ProviderNumber.id).filter(ProviderNumber.e164 == e164, ProviderNumber.internal_status != "RELEASED").first():
        raise NumberServiceError(409, "already_owned", f"Choranta already owns {e164}.")

    with carrier(db) as provider:
        # Still for sale, at the price that was confirmed?
        try:
            listing = provider.search_inventory(search=e164.lstrip("+"), page=1, per_page=100)
            balance = provider.balance(currency)
        except NumberProviderError as exc:
            raise _fail(exc)
        item = next((n for n in listing.items if n.e164 == e164), None)
        if not item:
            raise NumberServiceError(409, "number_unavailable", f"{e164} is no longer available to buy.")
        changed = [name for name, expected, now in (("monthly fee", expected_monthly_cost, item.monthly_fee),
                                                   ("setup fee", expected_setup_cost, item.setup_fee))
                   if expected is not None and now is not None and abs(float(expected) - float(now)) > 0.005]
        if changed or (item.currency and item.currency.upper() != currency):
            raise NumberServiceError(409, "price_changed", f"The {' and '.join(changed) or 'currency'} changed. Review the new price and confirm again.",
                                     details={"monthly_fee": item.monthly_fee, "setup_fee": item.setup_fee, "currency": item.currency})
        due = (item.setup_fee or 0) + (item.monthly_fee or 0)
        if balance is not None and balance < due:
            raise NumberServiceError(402, "insufficient_balance",
                                     f"The Vobiz balance ({balance:,.2f} {currency}) doesn't cover the setup fee and first month ({due:,.2f}).")

        op = NumberOperation(provider=provider.name, e164=e164, operation_type="PURCHASE", operation_status="PENDING",
                             idempotency_key=key, actor=actor.label, actor_user_id=actor.user_id, client_id=client_id,
                             is_mock=provider.is_mock,
                             request={"e164": e164, "currency": currency, "monthly_fee": item.monthly_fee,
                                      "setup_fee": item.setup_fee})
        db.add(op)
        db.commit()

        try:
            owned = provider.purchase(e164, currency)
        except ProviderUncertain as exc:
            op.operation_status, op.error_code, op.error_message = "UNCERTAIN", exc.code, exc.message
            db.commit()
            logger.warning("Purchase of %s uncertain (%s); checking the carrier", e164, exc.message)
            from app.services.number_reconciliation import reconcile_operation
            return reconcile_operation(db, op, provider, actor)
        except NumberProviderError as exc:
            op.operation_status, op.error_code, op.error_message = "FAILED", exc.code, exc.message
            db.commit()
            raise _fail(exc, op)

        try:
            pn = upsert_owned(db, provider.name, owned, provider.is_mock)
            op.provider_number_id = pn.id
            op.provider_request_id = owned.provider_number_id
            op.operation_status = "SUCCEEDED"
            op.result = _owned_result(owned)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Bought %s at the carrier but couldn't save it", e164)
            _mark_needs_reconciliation(db, op.id, owned, exc)
            db.expire_all()
            return db.get(NumberOperation, op.id)

        attach_application(db, provider, pn, actor)
        logger.info("%s bought %s (%s)", actor.label, e164, "mock" if provider.is_mock else provider.name)
        return op


# ---------------------------------------------------------------- releasing

def _provider_for(db: Session, pn: ProviderNumber):
    if pn.provider == "exotel":
        from contextlib import nullcontext
        from app.runtime.providers.numbers.exotel import ExotelNumberProvider
        return nullcontext(ExotelNumberProvider(pn.provider_number_id or ""))
    return carrier(db)


def release(db: Session, number_id: str, *, confirm_e164: str, idempotency_key: str, actor: Actor) -> NumberOperation:
    """Gives a number back to the carrier (a release fee may apply). It must not be assigned to a client."""
    pn = get_number(db, number_id)
    key = (idempotency_key or "").strip()
    if not key:
        raise NumberServiceError(400, "idempotency_key_required", "An idempotency key is required.")
    earlier = db.query(NumberOperation).filter(NumberOperation.idempotency_key == key).first()
    if earlier:
        if earlier.operation_type != "RELEASE" or earlier.provider_number_id != pn.id:
            raise NumberServiceError(409, "idempotency_key_reused", "That idempotency key was used for a different request.")
        return earlier
    if re.sub(r"[\s\-]", "", confirm_e164 or "") != pn.e164:
        raise NumberServiceError(400, "confirmation_mismatch", f"Type {pn.e164} exactly to confirm releasing it.")
    if pn.internal_status == "RELEASED":
        raise NumberServiceError(409, "already_released", f"{pn.e164} has already been released.")
    if active_assignment(db, pn.id):
        raise NumberServiceError(409, "assigned", f"{pn.e164} is assigned to a client. Unassign it first.")
    if pn.is_mock != mock_mode() and pn.provider != "exotel":
        raise NumberServiceError(409, "wrong_mode", "This number belongs to the other mode (mock vs real); switch modes to release it.")

    previous = pn.internal_status
    op = NumberOperation(provider_number_id=pn.id, provider=pn.provider, e164=pn.e164, operation_type="RELEASE",
                         idempotency_key=key, actor=actor.label, actor_user_id=actor.user_id, is_mock=pn.is_mock)
    db.add(op)
    pn.internal_status = "RELEASING"
    db.commit()

    with _provider_for(db, pn) as provider:
        try:
            provider.release(pn.e164)
        except NumberNotFound:
            pass  # already gone at the carrier: confirmed below by marking it released
        except ProviderUncertain as exc:
            op.operation_status, op.error_code, op.error_message = "UNCERTAIN", exc.code, exc.message
            db.commit()
            from app.services.number_reconciliation import reconcile_operation
            return reconcile_operation(db, op, provider, actor)
        except NumberProviderError as exc:
            op.operation_status, op.error_code, op.error_message = "FAILED", exc.code, exc.message
            pn.internal_status = previous
            db.commit()
            raise _fail(exc, op)
    mark_released(pn)
    op.operation_status = "SUCCEEDED"
    db.commit()
    logger.info("%s released %s", actor.label, pn.e164)
    return op


def mark_released(pn: ProviderNumber) -> None:
    pn.internal_status = "RELEASED"
    pn.provider_status = "released"
    pn.released_at = utcnow()
    pn.trunk_id = None
    pn.attention = None
