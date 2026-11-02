"""
Each client's Vobiz sub-account: created on their first number, holding their numbers and placing their calls.

Off by default (VOBIZ_SUBACCOUNTS_ENABLED). Vobiz confirmed on 2026-11-02 that sub-accounts get no lines of their
own: they share the main account's concurrent calls and CPS. They also can't use the main account's applications
or SIP trunks, so a number moved into one loses the inbound application attached to it. Kept for if Vobiz changes
that. Clients never see it: with kyc_mode personal_use the sub-account runs on Choranta's KYC and is billed to
Choranta's main account, and Choranta charges the client's wallet as before.

Moving a number out of a sub-account is refused for 15 days after its last call (Vobiz's cool-off). Until then the
number stays where it is (ProviderNumber.subaccount_auth_id) and can't go to another client.
"""
import logging
import threading
import time
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import secrets_box
from app.core.config import settings
from app.models.client import Client
from app.models.numbers import CarrierSubaccount, NumberOperation, ProviderNumber
from app.runtime.providers.numbers import NumberNotFound, NumberProvider, NumberProviderError, ProviderUncertain
from app.services import number_service as svc

logger = logging.getLogger("choranta.services.carrier_subaccounts")


def enabled() -> bool:
    return bool(settings.VOBIZ_SUBACCOUNTS_ENABLED)


def for_client(db: Session, client_id: str) -> Optional[CarrierSubaccount]:
    return (db.query(CarrierSubaccount)
            .filter(CarrierSubaccount.client_id == client_id, CarrierSubaccount.provider == "vobiz",
                    CarrierSubaccount.is_mock.is_(svc.mock_mode())).first())


def _op(db: Session, pn: Optional[ProviderNumber], kind: str, actor: svc.Actor, client_id: Optional[str],
        request: dict) -> NumberOperation:
    op = NumberOperation(provider_number_id=pn.id if pn else None, provider="vobiz", e164=pn.e164 if pn else None,
                         operation_type=kind, actor=actor.label, actor_user_id=actor.user_id, client_id=client_id,
                         is_mock=svc.mock_mode(), request=request)
    db.add(op)
    db.commit()
    return op


def ensure(db: Session, provider: NumberProvider, client: Client, actor: svc.Actor) -> CarrierSubaccount:
    """The client's sub-account, created at the carrier the first time. Raises NumberProviderError."""
    existing = for_client(db, client.id)
    if existing:
        return existing
    kyc_mode = settings.VOBIZ_SUBACCOUNT_KYC_MODE or "personal_use"
    op = _op(db, None, "CREATE_SUBACCOUNT", actor, client.id, {"kyc_mode": kyc_mode})
    try:
        created = provider.create_subaccount(
            name=client.name, email=client.contact_email, phone=client.contact_phone,
            description=f"Choranta client {client.client_code or client.id}", kyc_mode=kyc_mode,
        )
    except NumberProviderError as exc:
        op.operation_status = "UNCERTAIN" if isinstance(exc, ProviderUncertain) else "FAILED"
        op.error_code, op.error_message = exc.code, exc.message
        db.commit()
        raise
    row = CarrierSubaccount(client_id=client.id, provider="vobiz", auth_id=created.auth_id,
                            auth_token_enc=secrets_box.encrypt(created.auth_token), kyc_mode=created.kyc_mode or kyc_mode,
                            is_mock=provider.is_mock, created_by=actor.label)
    db.add(row)
    op.operation_status = "SUCCEEDED"
    op.result = {"sub_auth_id": created.auth_id}
    try:
        db.commit()
    except IntegrityError:
        # Another request created one for this client at the same moment; keep theirs
        db.rollback()
        logger.warning("Sub-account %s for client %s was created twice; %s is unused at Vobiz",
                       created.auth_id, client.id, created.auth_id)
        return for_client(db, client.id)
    logger.info("%s created sub-account %s for client %s", actor.label, created.auth_id, client.id)
    return row


def move_out(db: Session, provider: NumberProvider, pn: ProviderNumber, actor: svc.Actor) -> bool:
    """
    Moves the number back to Choranta's main account. False when Vobiz refuses for now (cool-off): the number
    stays in the sub-account and is flagged for staff. Other carrier errors are raised.
    """
    if not pn.subaccount_auth_id:
        return True
    op = _op(db, pn, "UNASSIGN_SUBACCOUNT", actor, None, {"sub_auth_id": pn.subaccount_auth_id})
    try:
        provider.unassign_subaccount(pn.e164)
    except NumberNotFound:
        pass  # not in a sub-account at the carrier
    except NumberProviderError as exc:
        op.operation_status, op.error_code, op.error_message = "FAILED", exc.code, exc.message
        until = exc.details.get("cool_off_until")
        if until:
            pn.attention = (f"Still in the previous client's Vobiz sub-account until {until} (Vobiz's 15-day cool-off "
                            "after a number's last call). It can't go to another client before then.")
            db.commit()
            return False
        db.commit()
        raise
    pn.subaccount_auth_id = None
    op.operation_status = "SUCCEEDED"
    db.commit()
    return True


def move_in(db: Session, provider: NumberProvider, pn: ProviderNumber, client: Client, actor: svc.Actor) -> None:
    """
    Puts the number in the client's sub-account. Refused (409) while it is still held in another client's
    sub-account. Any other failure leaves it on the main account, where it still works, and flags it for staff.
    """
    sub = for_client(db, client.id)
    if sub and pn.subaccount_auth_id == sub.auth_id:
        return
    if pn.subaccount_auth_id and not move_out(db, provider, pn, actor):
        raise svc.NumberServiceError(409, "subaccount_cool_off", pn.attention)
    try:
        sub = ensure(db, provider, client, actor)
    except NumberProviderError as exc:
        pn.attention = (f"Couldn't create {client.name}'s Vobiz sub-account ({exc.message}); its calls use the main "
                        "account's lines for now. Re-assign the number to try again.")
        db.commit()
        return
    op = _op(db, pn, "ASSIGN_SUBACCOUNT", actor, client.id, {"sub_auth_id": sub.auth_id})
    try:
        provider.assign_subaccount(pn.e164, sub.auth_id)
    except NumberProviderError as exc:
        op.operation_status = "UNCERTAIN" if isinstance(exc, ProviderUncertain) else "FAILED"
        op.error_code, op.error_message = exc.code, exc.message
        pn.attention = (f"Couldn't move the number into {client.name}'s Vobiz sub-account ({exc.message}); its calls "
                        "use the main account's lines for now. Re-assign the number to try again.")
        db.commit()
        return
    pn.subaccount_auth_id = sub.auth_id
    if pn.attention and "sub-account" in pn.attention:
        pn.attention = None
    op.operation_status = "SUCCEEDED"
    db.commit()


def caller_credentials(db: Session, e164: str) -> Optional[Tuple[str, str]]:
    """(auth_id, auth_token) of the sub-account a real number sits in, or None to call from the main account."""
    row = (db.query(CarrierSubaccount)
           .join(ProviderNumber, ProviderNumber.subaccount_auth_id == CarrierSubaccount.auth_id)
           .filter(ProviderNumber.e164 == e164, ProviderNumber.provider == "vobiz",
                   ProviderNumber.internal_status == "ASSIGNED", ProviderNumber.is_mock.is_(False),
                   CarrierSubaccount.is_mock.is_(False)).first())
    if not row:
        return None
    try:
        return row.auth_id, secrets_box.decrypt(row.auth_token_enc)
    except ValueError:
        logger.error("Can't decrypt the token of sub-account %s; calling from the main account", row.auth_id)
        return None


# ---------------------------------------------------------------- pacing

_pace_lock = threading.Lock()
_next_slot = 0.0


def wait_for_dial_slot() -> None:
    """
    Spaces new Vobiz calls to VOBIZ_CPS per second (Vobiz rejects faster dialing). One queue for the whole
    account: sub-accounts share the main account's CPS. Per process, so run one worker that dials.
    """
    global _next_slot
    cps = float(settings.VOBIZ_CPS or 0)
    if cps <= 0:
        return
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + 1.0 / cps
    if slot > now:
        time.sleep(slot - now)
