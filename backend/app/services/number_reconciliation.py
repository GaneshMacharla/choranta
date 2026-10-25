"""
Bringing Choranta's record of its numbers in line with the carrier's.

- reconcile_operation: settles one PURCHASE or RELEASE whose outcome isn't known (a timeout, a 5xx, or our own
  save failing after the carrier acted) by reading the carrier's state. It never repeats the request.
  * Purchase: owned at the carrier -> recorded (RECOVERED); still for sale -> it didn't happen (FAILED);
    neither -> still UNCERTAIN (try again later).
  * Release: no longer owned -> released (RECOVERED); still owned -> it didn't happen (FAILED).
- sync: reads every number the carrier says we own, records the ones we didn't know about (bought in the console,
  or saves that failed), flags ours that the carrier no longer has (MISSING, never deleted), and settles open
  operations.
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.numbers import NumberOperation, ProviderNumber
from app.runtime.providers.numbers import NumberProvider, NumberProviderError
from app.services import number_service as svc

logger = logging.getLogger("choranta.services.number_reconciliation")

SETTLEABLE = ("PENDING", "UNCERTAIN", "NEEDS_RECONCILIATION")


def _settle_purchase(db: Session, op: NumberOperation, provider: NumberProvider, actor: svc.Actor) -> None:
    owned = provider.get_owned(op.e164)
    if owned:
        pn = svc.upsert_owned(db, provider.name, owned, provider.is_mock)
        op.provider_number_id = pn.id
        op.provider_request_id = owned.provider_number_id
        op.result = {**(op.result or {}), "e164": owned.e164, "provider_number_id": owned.provider_number_id,
                     "recovered_by": actor.label}
        op.operation_status = "RECOVERED" if op.operation_status != "PENDING" else "SUCCEEDED"
        db.commit()
        if not pn.application_id:
            svc.attach_application(db, provider, pn, actor)
        return
    listing = provider.search_inventory(search=op.e164.lstrip("+"), page=1, per_page=100)
    if any(n.e164 == op.e164 for n in listing.items):
        op.operation_status = "FAILED"
        op.error_code = "not_purchased"
        op.error_message = f"Checked with the carrier: {op.e164} was not bought (it's still for sale). Nothing was charged."
    else:
        op.operation_status = "UNCERTAIN"
        op.error_message = (f"Checked with the carrier: {op.e164} isn't on Choranta's account and isn't for sale either. "
                            "Check again in a few minutes.")
    db.commit()


def _settle_release(db: Session, op: NumberOperation, provider: NumberProvider) -> None:
    pn = db.get(ProviderNumber, op.provider_number_id) if op.provider_number_id else None
    if provider.get_owned(op.e164):
        op.operation_status = "FAILED"
        op.error_code = "not_released"
        op.error_message = f"Checked with the carrier: {op.e164} is still on Choranta's account."
        if pn and pn.internal_status == "RELEASING":
            pn.internal_status = "AVAILABLE"
    else:
        op.operation_status = "RECOVERED"
        if pn:
            svc.mark_released(pn)
    db.commit()


def reconcile_operation(db: Session, op: NumberOperation, provider: Optional[NumberProvider] = None,
                        actor: svc.Actor = svc.SYSTEM) -> NumberOperation:
    if op.operation_status not in SETTLEABLE or op.operation_type not in ("PURCHASE", "RELEASE"):
        return op
    if op.is_mock != svc.mock_mode():
        raise svc.NumberServiceError(409, "wrong_mode", "This operation belongs to the other mode (mock vs real).", op)

    def settle(p: NumberProvider) -> None:
        if op.operation_type == "PURCHASE":
            _settle_purchase(db, op, p, actor)
        else:
            _settle_release(db, op, p)

    try:
        if provider is not None:
            settle(provider)
        else:
            with svc.carrier(db) as p:
                settle(p)
    except NumberProviderError as exc:
        db.rollback()
        logger.warning("Couldn't check %s %s with the carrier: %s", op.operation_type, op.e164, exc.message)
        op = db.get(NumberOperation, op.id)
        op.error_message = f"Couldn't check with the carrier yet: {exc.message}"
        db.commit()
    db.refresh(op)
    return op


def sync(db: Session, actor: svc.Actor) -> Dict[str, Any]:
    """Reads every owned number at the carrier and lines up Choranta's records. Returns what changed."""
    summary = {"seen": 0, "adopted": 0, "updated": 0, "missing": 0, "operations_settled": 0}
    sync_op = NumberOperation(provider="vobiz", operation_type="SYNC", actor=actor.label, actor_user_id=actor.user_id,
                              is_mock=svc.mock_mode())
    db.add(sync_op)
    db.commit()
    try:
        with svc.carrier(db) as provider:
            seen = set()
            page = 1
            while True:
                result = provider.list_owned(page=page, per_page=100)
                for owned in result.items:
                    seen.add(owned.e164)
                    known = db.query(ProviderNumber.id).filter(ProviderNumber.provider == provider.name,
                                                               ProviderNumber.e164 == owned.e164,
                                                               ProviderNumber.internal_status != "RELEASED").first()
                    svc.upsert_owned(db, provider.name, owned, provider.is_mock)
                    summary["updated" if known else "adopted"] += 1
                if len(result.items) < result.per_page or page >= 100:
                    break
                page += 1
            summary["seen"] = len(seen)
            ours = (db.query(ProviderNumber)
                    .filter(ProviderNumber.provider == provider.name, ProviderNumber.is_mock.is_(provider.is_mock),
                            ProviderNumber.internal_status.notin_(("RELEASED",))).all())
            for pn in ours:
                if pn.e164 not in seen:
                    pn.provider_status = "MISSING"
                    if pn.internal_status != "RELEASING":
                        pn.internal_status = "NEEDS_RECONCILIATION"
                    pn.attention = ("The carrier no longer lists this number on Choranta's account. Check the Vobiz "
                                    "console; if it was released there, release it here too.")
                    summary["missing"] += 1
            db.commit()
            open_ops = (db.query(NumberOperation)
                        .filter(NumberOperation.operation_status.in_(SETTLEABLE),
                                NumberOperation.operation_type.in_(("PURCHASE", "RELEASE")),
                                NumberOperation.is_mock.is_(provider.is_mock), NumberOperation.id != sync_op.id).all())
            for op in open_ops:
                before = op.operation_status
                if reconcile_operation(db, op, provider, actor).operation_status != before:
                    summary["operations_settled"] += 1
    except NumberProviderError as exc:
        db.rollback()
        sync_op = db.get(NumberOperation, sync_op.id)
        sync_op.operation_status, sync_op.error_code, sync_op.error_message = "FAILED", exc.code, exc.message
        db.commit()
        raise svc.NumberServiceError(exc.status_code, exc.code, exc.message, sync_op)
    sync_op.operation_status = "SUCCEEDED"
    sync_op.result = summary
    db.commit()
    logger.info("Number sync by %s: %s", actor.label, summary)
    return {**summary, "operation": svc.operation_out(sync_op)}
