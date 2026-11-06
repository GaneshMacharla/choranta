"""
Each client's Vobiz sub-account: created when they start business verification, KYC'd by Vobiz in the client's own
name (kyc_mode customer_use; see services/verifications.py), then holding their numbers and placing their calls.

A sub-account can't use the main account's applications, so each gets its own inbound application pointing at
Choranta's answer URL, and the client's numbers are attached to it. Lines and CPS are still the main account's,
shared by everyone (billing.platform_headroom, wait_for_dial_slot). Vobiz bills the main account; Choranta charges
the client's wallet as before.

Numbers move in only once the client is verified (an unverified sub-account's calls are blocked); until then a
number staff gave the client stays on the main account. Moving a number out is refused for 15 days after its last
call (Vobiz's cool-off): it stays where it is (ProviderNumber.subaccount_auth_id) and can't go to another client.
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
from app.models.verification import ClientVerification
from app.runtime.providers.numbers import (
    NotConfigured, NumberNotFound, NumberProvider, NumberProviderError, ProviderUncertain, subaccount_provider,
)
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


def ensure(db: Session, provider: NumberProvider, client: Client, actor: svc.Actor, *, email: str,
           business_type: str) -> CarrierSubaccount:
    """The client's sub-account, created at the carrier the first time. Raises NumberProviderError."""
    existing = for_client(db, client.id)
    if existing:
        return existing
    kyc_mode = settings.VOBIZ_SUBACCOUNT_KYC_MODE or "customer_use"
    op = _op(db, None, "CREATE_SUBACCOUNT", actor, client.id, {"kyc_mode": kyc_mode, "business_type": business_type})
    try:
        created = provider.create_subaccount(
            name=client.name, email=email, phone=client.contact_phone,
            description=f"Choranta client {client.client_code or client.id}", kyc_mode=kyc_mode,
            business_type=business_type,
        )
    except NumberProviderError as exc:
        op.operation_status = "UNCERTAIN" if isinstance(exc, ProviderUncertain) else "FAILED"
        op.error_code, op.error_message = exc.code, exc.message
        db.commit()
        raise
    row = CarrierSubaccount(client_id=client.id, provider="vobiz", auth_id=created.auth_id,
                            auth_token_enc=secrets_box.encrypt(created.auth_token), kyc_mode=created.kyc_mode or kyc_mode,
                            business_type=business_type, is_mock=provider.is_mock, created_by=actor.label)
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
    logger.info("%s created sub-account %s (%s, %s) for client %s", actor.label, created.auth_id, kyc_mode,
                business_type, client.id)
    return row


def token(sub: CarrierSubaccount) -> str:
    return secrets_box.decrypt(sub.auth_token_enc)


def _answer_url() -> str:
    base = (settings.TELEPHONY_BASE_URL or "").rstrip("/")
    if not base:
        raise NotConfigured("TELEPHONY_BASE_URL isn't set, so Vobiz has no address to send inbound calls to.")
    from app.services.outbound_calls import with_webhook_token  # outbound_calls imports this module
    return with_webhook_token(f"{base}/api/telephony/vobiz/answer", "vobiz")


def _close(provider: NumberProvider) -> None:
    close = getattr(provider, "close", None)
    if close:
        close()


def ensure_application(db: Session, sub: CarrierSubaccount, actor: svc.Actor) -> str:
    """The sub-account's own inbound application, created the first time. Raises NumberProviderError."""
    if sub.application_id:
        return sub.application_id
    answer_url = "https://mock.invalid/api/telephony/vobiz/answer" if sub.is_mock else _answer_url()
    op = _op(db, None, "CREATE_APPLICATION", actor, sub.client_id, {"sub_auth_id": sub.auth_id})
    provider = subaccount_provider(db, sub.auth_id, token(sub))
    try:
        app_id = provider.create_application(name=f"Choranta {sub.auth_id}", answer_url=answer_url)
    except NumberProviderError as exc:
        op.operation_status = "UNCERTAIN" if isinstance(exc, ProviderUncertain) else "FAILED"
        op.error_code, op.error_message = exc.code, exc.message
        db.commit()
        raise
    finally:
        _close(provider)
    sub.application_id = app_id
    op.operation_status = "SUCCEEDED"
    op.result = {"application_id": app_id}
    db.commit()
    return app_id


def _verified(db: Session, client_id: str) -> bool:
    return (db.query(ClientVerification.id)
            .filter(ClientVerification.client_id == client_id, ClientVerification.is_mock.is_(svc.mock_mode()),
                    ClientVerification.status == "VERIFIED").first() is not None)


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


def move_in(db: Session, provider: NumberProvider, pn: ProviderNumber, client: Client, actor: svc.Actor) -> bool:
    """
    Puts the number in the verified client's sub-account and routes its inbound calls to the sub-account's
    application. True when it's there. False when it stays on the main account: the client isn't verified yet, or
    the move failed (flagged for staff; the main account's routing keeps working). Refused (409) while the number
    is still held in another client's sub-account.
    """
    sub = for_client(db, client.id)
    if pn.subaccount_auth_id and (not sub or pn.subaccount_auth_id != sub.auth_id) and not move_out(db, provider, pn, actor):
        raise svc.NumberServiceError(409, "subaccount_cool_off", pn.attention)
    if not sub or not _verified(db, client.id):
        return False
    if pn.subaccount_auth_id != sub.auth_id:
        op = _op(db, pn, "ASSIGN_SUBACCOUNT", actor, client.id, {"sub_auth_id": sub.auth_id})
        try:
            provider.assign_subaccount(pn.e164, sub.auth_id)
        except NumberProviderError as exc:
            op.operation_status = "UNCERTAIN" if isinstance(exc, ProviderUncertain) else "FAILED"
            op.error_code, op.error_message = exc.code, exc.message
            pn.attention = (f"Couldn't move the number into {client.name}'s Vobiz sub-account ({exc.message}); it "
                            "stays on the main account for now. Re-assign the number to try again.")
            db.commit()
            return False
        pn.subaccount_auth_id = sub.auth_id
        op.operation_status = "SUCCEEDED"
        db.commit()
    try:
        app_id = ensure_application(db, sub, actor)
        sub_provider = subaccount_provider(db, sub.auth_id, token(sub))
        try:
            sub_provider.attach_application(pn.e164, app_id)
        finally:
            _close(sub_provider)
    except NumberProviderError as exc:
        pn.attention = (f"Inbound calls to this number won't reach Choranta: couldn't attach it to {client.name}'s "
                        f"Vobiz application ({exc.message}). Re-assign the number to try again.")
        db.commit()
        return True
    pn.application_id = app_id
    if pn.attention and ("sub-account" in pn.attention or "Inbound" in pn.attention):
        pn.attention = None
    db.commit()
    return True


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
