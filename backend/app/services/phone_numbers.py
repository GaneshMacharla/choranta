"""
Phone numbers clients buy from Choranta.

Clients verify their business once (services/verifications.py). Buying then buys the number on Choranta's
Vobiz account (services/number_service.py), assigns it to the client (services/number_assignments.py) and debits
the one-time setup fee and the first month's rent from the client's wallet. The number starts READY_TO_TEST: once an AI employee is assigned,
a test call to the client's phone that connects (or the client skipping the test) makes it ACTIVE. A background cycle renews the rent from the wallet each
month; if the balance can't cover it the number is PAST_DUE, and after NUMBER_GRACE_DAYS it goes back to Choranta's
pool (flagged for staff to resell or release).
Numbers registered without a rental (before numbers were sold) are free.
"""
import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.billing import WalletTransaction
from app.models.phone_number import PhoneNumber
from app.models.subscription import NumberPricing, NumberRental
from app.services import notifications, number_assignments, number_service, verifications
from app.services.billing import _money, get_wallet
from app.services.subscriptions import add_month, utcnow

logger = logging.getLogger("choranta.services.phone_numbers")


class InsufficientBalance(ValidationException):
    def __init__(self, needed: float, balance: float):
        super().__init__(
            f"You need {needed:,.2f} credits for the setup fee and first month's rent (you have {balance:,.2f}). Buy credits and try again.",
            details={"needed_inr": needed, "balance_inr": balance},
        )
        self.status_code = 402


def _label(start: datetime, end: datetime) -> str:
    return f"{start:%d %b} - {end:%d %b %Y}"


def display_number(pn: PhoneNumber) -> str:
    return (pn.metadata_ or {}).get("released_number") or pn.phone_number


def get_pricing(db: Session) -> List[NumberPricing]:
    return db.query(NumberPricing).order_by(NumberPricing.monthly_rent_inr).all()


def pricing_out(p: NumberPricing) -> Dict[str, Any]:
    gst = settings.EFFECTIVE_GST_RATE_PERCENT / 100.0
    setup = float(getattr(p, "setup_fee_inr", 0) or 0)
    return {"number_type": p.number_type, "monthly_rent_inr": p.monthly_rent_inr,
            "monthly_rent_with_gst_inr": _money(p.monthly_rent_inr * (1 + gst)), "setup_fee_inr": setup,
            "due_now_inr": _money(p.monthly_rent_inr + setup), "is_available": p.is_available}


def rental_for(db: Session, phone_number_id: str) -> Optional[NumberRental]:
    return db.query(NumberRental).filter(NumberRental.phone_number_id == phone_number_id).first()


def rental_out(rental: Optional[NumberRental]) -> Dict[str, Any]:
    if not rental:
        return {"monthly_rent_inr": None, "rental_status": None, "current_period_end": None,
                "cancel_at_period_end": False, "grace_ends_at": None}
    return {
        "monthly_rent_inr": rental.monthly_rent_inr,
        "rental_status": rental.status,
        "current_period_end": rental.current_period_end,
        "cancel_at_period_end": rental.cancel_at_period_end,
        "grace_ends_at": rental.current_period_end + timedelta(days=settings.NUMBER_GRACE_DAYS)
        if rental.status == "PAST_DUE" else None,
    }


def _debit_rent(db: Session, rental: NumberRental, number: str, start: datetime, end: datetime, user_id: Optional[str]) -> None:
    wallet = get_wallet(db, rental.client_id, lock=True)
    wallet.balance_inr = _money(wallet.balance_inr - rental.monthly_rent_inr)
    db.add(WalletTransaction(
        client_id=rental.client_id, type="DEBIT", amount_inr=-rental.monthly_rent_inr,
        balance_after_inr=wallet.balance_inr, note=f"Rent for {number}, {_label(start, end)}", created_by=user_id,
    ))


# ---------------------------------------------------------------- buying

def _refusal(exc: number_service.NumberServiceError) -> ValidationException:
    err = ValidationException(exc.message, details={"code": exc.code})
    err.status_code = exc.status_code if exc.status_code < 500 else 502
    return err


def search(db: Session, number_type: str, region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Numbers a client can rent, at Choranta's price for the type (never the carrier's cost)."""
    price = db.get(NumberPricing, number_type)
    if not price or not price.is_available:
        raise ValidationException(f"{number_type} numbers aren't available right now.")
    try:
        found = number_service.search_inventory(db, country="IN", number_type=number_type, region=region, per_page=100)
    except number_service.NumberServiceError as exc:
        raise _refusal(exc)
    taken = {n for (n,) in db.query(PhoneNumber.phone_number).all()}
    out = pricing_out(price)
    return [
        {"phone_number": item["e164"], "region": item["region"], "number_type": number_type,
         "monthly_rent_inr": out["monthly_rent_inr"], "monthly_rent_with_gst_inr": out["monthly_rent_with_gst_inr"],
         "setup_fee_inr": out["setup_fee_inr"], "due_now_inr": out["due_now_inr"]}
        for item in found["items"]
        if item["e164"] not in taken and not item["scenario"]  # mock failure scenarios are for staff testing
    ]


def buy_number(db: Session, client_id: str, phone_number: str, number_type: str, user_id: Optional[str],
               require_verification: bool = True) -> PhoneNumber:
    """Buys the number on Vobiz, gives it to the client and charges the setup fee + first month's rent."""
    if require_verification:
        verifications.require_verified(db, client_id)
    price = db.get(NumberPricing, number_type)
    if not price or not price.is_available:
        raise ValidationException(f"{number_type} numbers aren't available right now.")
    number = phone_number.strip().replace(" ", "").replace("-", "")
    if db.query(PhoneNumber.id).filter(PhoneNumber.phone_number == number).first():
        raise ValidationException("That number is already taken. Pick another one.")
    # Checked without a lock: the purchase below can take seconds, and call charges must not wait on it
    setup_fee = float(price.setup_fee_inr or 0)
    due_now = _money(price.monthly_rent_inr + setup_fee)
    balance = get_wallet(db, client_id).balance_inr
    if balance < due_now:
        raise InsufficientBalance(due_now, balance)

    actor = number_service.Actor(f"CLIENT {client_id}" if require_verification else f"TEAM for {client_id}", user_id)
    try:
        op = number_service.purchase(db, number, idempotency_key=f"rent-{uuid.uuid4().hex}", actor=actor, client_id=client_id)
    except number_service.NumberServiceError as exc:
        raise _refusal(exc)
    if op.operation_status not in number_service.DONE_STATUSES:
        err = ValidationException("We couldn't confirm that number with the carrier. You haven't been charged; "
                                  "our team is checking it. Please pick another number for now.")
        err.status_code = 502
        raise err
    try:
        pn = number_assignments.assign(db, op.provider_number_id, client_id=client_id, actor=actor)
    except number_service.NumberServiceError as exc:
        raise _refusal(exc)

    try:
        start = utcnow()
        end = add_month(start)
        rental = NumberRental(
            phone_number_id=pn.id, client_id=client_id, number_type=number_type, monthly_rent_inr=price.monthly_rent_inr,
            status="ACTIVE", current_period_start=start, current_period_end=end, created_by=user_id,
        )
        db.add(rental)
        _debit_rent(db, rental, pn.phone_number, start, end, user_id)
        if setup_fee > 0:
            wallet = get_wallet(db, client_id, lock=True)
            wallet.balance_inr = _money(wallet.balance_inr - setup_fee)
            db.add(WalletTransaction(client_id=client_id, type="DEBIT", amount_inr=-setup_fee,
                                     balance_after_inr=wallet.balance_inr, note=f"Number setup fee, {pn.phone_number}",
                                     created_by=user_id))
        notifications.notify(db, client_id, "NUMBER_READY", f"{pn.phone_number} is ready to test",
                             "Assign an AI employee and place a test call to start using it.", link="/portal/numbers")
        db.commit()
    except Exception:
        db.rollback()
        # Releasing at the carrier costs a fee, so the number stays in Choranta's pool; the client paid nothing
        logger.exception(f"Charging for {number} failed; returning it to the pool")
        number_assignments.unassign(db, op.provider_number_id, actor=number_service.SYSTEM, reason="CHARGE_FAILED")
        raise
    logger.info(f"Client {client_id} rented {pn.phone_number} ({number_type}) for Rs {price.monthly_rent_inr}/month")
    return pn


# ---------------------------------------------------------------- renewing & releasing

def release(db: Session, rental: NumberRental, now: Optional[datetime] = None, reason: str = "LAPSED") -> bool:
    """
    Ends the client's rental. The number returns to Choranta's pool (flagged for staff). False if that couldn't be
    done right now (retried next cycle).
    """
    from app.models.numbers import NumberAssignment
    pn = db.get(PhoneNumber, rental.phone_number_id)
    assignment = (db.query(NumberAssignment)
                  .filter(NumberAssignment.phone_number_id == rental.phone_number_id, NumberAssignment.status == "ACTIVE")
                  .first())
    if assignment:
        try:
            number_assignments.unassign(db, assignment.provider_number_id, actor=number_service.SYSTEM, reason=reason)
        except number_service.NumberServiceError as exc:
            logger.error(f"Returning {display_number(pn) if pn else rental.phone_number_id} to the pool failed: {exc.message}")
            return False
        db.refresh(rental)
        rental.released_at = now or utcnow()
        db.commit()
        logger.info(f"Rental of {display_number(pn) if pn else rental.phone_number_id} for {rental.client_id} ended ({reason})")
        return True
    rental.status = "RELEASED"
    rental.released_at = now or utcnow()
    if pn:
        original = pn.phone_number
        pn.metadata_ = {**(pn.metadata_ or {}), "released_number": original}
        pn.phone_number = f"{original}~{rental.id[-8:]}"  # frees the number in case it's bought again
        pn.status = "RELEASED"
        pn.agent_id = None
        pn.agent_version_id = None
    db.commit()
    logger.info(f"Released {display_number(pn) if pn else rental.phone_number_id} for {rental.client_id}")
    return True


def _remind_once(db: Session, rental: NumberRental, key: str, title: str, body: str) -> None:
    """Sends a rent notification unless this one (for this rent date) was already sent."""
    key = f"{rental.current_period_end.date().isoformat()}:{key}"
    if key in (rental.reminders_sent or []):
        return
    rental.reminders_sent = [*(rental.reminders_sent or []), key]
    notifications.notify(db, rental.client_id, "NUMBER_RENT", title, body, link="/portal/numbers", level="warning")
    db.commit()


def remind_upcoming_rent(db: Session, rental: NumberRental, now: datetime) -> None:
    """Daily warnings in the days before a rent the wallet can't cover; nothing when it can."""
    if rental.status != "ACTIVE" or rental.cancel_at_period_end or now >= rental.current_period_end:
        return
    days_left = math.ceil((rental.current_period_end - now) / timedelta(days=1))
    if not 1 <= days_left <= settings.NUMBER_RENT_REMINDER_DAYS:
        return
    balance = get_wallet(db, rental.client_id).balance_inr
    if balance >= rental.monthly_rent_inr:
        return
    pn = db.get(PhoneNumber, rental.phone_number_id)
    number = display_number(pn) if pn else "your number"
    when = "tomorrow" if days_left == 1 else f"in {days_left} days"
    _remind_once(db, rental, f"before-{days_left}", f"Rent for {number} is due {when}",
                 f"Rent of Rs {rental.monthly_rent_inr:g} is due on {rental.current_period_end:%d %b}, and your wallet "
                 f"has Rs {balance:g}. Top up so you don't lose the number.")


def _past_grace(rental: NumberRental, now: datetime) -> bool:
    return now >= rental.current_period_end + timedelta(days=settings.NUMBER_GRACE_DAYS)


def renew_or_lapse(db: Session, rental: NumberRental, now: Optional[datetime] = None) -> str:
    """Brings one rental up to date. Returns its status afterwards."""
    now = now or utcnow()
    while rental.status in ("ACTIVE", "PAST_DUE") and now >= rental.current_period_end:
        if rental.cancel_at_period_end:
            release(db, rental, now)
            break
        wallet = get_wallet(db, rental.client_id, lock=True)
        if wallet.balance_inr >= rental.monthly_rent_inr:
            start = rental.current_period_end
            end = add_month(start)
            pn = db.get(PhoneNumber, rental.phone_number_id)
            _debit_rent(db, rental, display_number(pn) if pn else "number", start, end, None)
            rental.current_period_start, rental.current_period_end = start, end
            rental.status = "ACTIVE"
            db.commit()
            continue
        pn = db.get(PhoneNumber, rental.phone_number_id)
        number = display_number(pn) if pn else "your number"
        removal = rental.current_period_end + timedelta(days=settings.NUMBER_GRACE_DAYS)
        if rental.status != "PAST_DUE":
            rental.status = "PAST_DUE"
            db.commit()
            logger.warning(f"Number rent unpaid for {rental.phone_number_id} ({rental.client_id}); past due")
        if _past_grace(rental, now):
            if release(db, rental, now):
                notifications.notify(db, rental.client_id, "NUMBER_RENT", f"{number} has been removed",
                                     "Its rent wasn't paid, so it's no longer yours. You can buy a new number any time.",
                                     link="/portal/numbers", level="warning")
                db.commit()
            break
        if now >= removal - timedelta(days=1):
            _remind_once(db, rental, "final", f"Last day to keep {number}",
                         f"Rent of Rs {rental.monthly_rent_inr:g} is still unpaid. Top up today or the number is "
                         f"removed on {removal:%d %b}.")
        else:
            _remind_once(db, rental, "due", f"Rent for {number} couldn't be charged",
                         f"Your wallet didn't cover the Rs {rental.monthly_rent_inr:g} rent. Calls on this number are "
                         f"paused; top up by {removal:%d %b} or the number will be removed.")
        break
    return rental.status


def run_rental_cycle(db: Session, now: Optional[datetime] = None) -> int:
    """Warns about upcoming rent the wallet can't cover, then renews, marks past due or releases every rental whose
    period has ended. Safe to run repeatedly."""
    now = now or utcnow()
    upcoming = (
        db.query(NumberRental)
        .filter(NumberRental.status == "ACTIVE", NumberRental.current_period_end > now,
                NumberRental.current_period_end <= now + timedelta(days=settings.NUMBER_RENT_REMINDER_DAYS))
        .all()
    )
    for rental in upcoming:
        try:
            remind_upcoming_rent(db, rental, now)
        except Exception:
            db.rollback()
            logger.exception(f"Rent reminder failed for {rental.id}")
    due = (
        db.query(NumberRental)
        .filter(NumberRental.status.in_(("ACTIVE", "PAST_DUE")), NumberRental.current_period_end <= now)
        .all()
    )
    for rental in due:
        try:
            renew_or_lapse(db, rental, now)
        except Exception:
            db.rollback()
            logger.exception(f"Rental cycle failed for {rental.id}")
    return len(due)


def run_rental_cycle_job(session_factory) -> None:
    db = session_factory()
    try:
        run_rental_cycle(db)
    finally:
        db.close()


def blocked_reason(db: Session, phone_number: PhoneNumber) -> Optional[str]:
    """Why calls on this number are refused because of rent, or None."""
    rental = rental_for(db, phone_number.id)
    if not rental:
        return None
    if rental.status == "RELEASED":
        return "This number has been released."
    if rental.status == "PAST_DUE" and _past_grace(rental, utcnow()):
        return "Rent for this number is overdue."
    return None


# ---------------------------------------------------------------- caller ID & agent assignment

def client_caller_number(db: Session, client_id: str, requested: Optional[str] = None) -> Optional[PhoneNumber]:
    """The client's own active number to show as caller ID (the requested one, if it is theirs)."""
    numbers = (
        db.query(PhoneNumber)
        .filter(PhoneNumber.client_id == client_id, PhoneNumber.status == "ACTIVE")
        .order_by(PhoneNumber.created_at).all()
    )
    numbers = [n for n in numbers if not blocked_reason(db, n)]
    if requested:
        wanted = requested.strip().replace(" ", "").replace("-", "")
        return next((n for n in numbers if n.phone_number == wanted or n.phone_number.endswith(wanted.lstrip("0"))), None)
    return numbers[0] if numbers else None


def assign_agent(db: Session, pn: PhoneNumber, agent_id: Optional[str]) -> PhoneNumber:
    """Routes the number to one of the client's AI employees, pinned to its latest published version."""
    if not agent_id:
        pn.agent_id = None
        pn.agent_version_id = None
        db.commit()
        return pn
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.client_id == pn.client_id).first()
    if not agent:
        raise ValidationException("That AI employee doesn't belong to your account.")
    version = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "PUBLISHED")
        .order_by(AgentVersion.version_number.desc()).first()
    )
    if not version:
        raise ValidationException(f"{agent.name} has no published version yet.")
    pn.agent_id = agent.id
    pn.agent_version_id = version.id
    db.commit()
    return pn


# ---------------------------------------------------------------- test & activate

TESTABLE_STATUSES = ("READY_TO_TEST", "ACTIVE")


def _activate(db: Session, pn: PhoneNumber, how: str) -> PhoneNumber:
    if pn.status == "ACTIVE":
        return pn
    pn.status = "ACTIVE"
    meta = dict(pn.metadata_ or {})
    meta["activated_by"] = how
    meta["activated_at"] = utcnow().isoformat()
    pn.metadata_ = meta
    notifications.notify(db, pn.client_id, "NUMBER_ACTIVE", f"{pn.phone_number} is active",
                         "Your AI employee now answers this number and can call from it.", link="/portal/numbers",
                         level="success")
    db.commit()
    return pn


def activate_without_test(db: Session, pn: PhoneNumber) -> PhoneNumber:
    """The client chose to skip the test call."""
    if pn.status not in TESTABLE_STATUSES:
        raise ValidationException("This number can't be activated.")
    return _activate(db, pn, "skipped_test")


def start_test_call(db: Session, pn: PhoneNumber, to_number: str):
    """Calls the client's phone from the new number with its AI employee; a connected call activates it."""
    from app.services.outbound_calls import place_outbound_call
    # Test calls are free, so they are only for a number that isn't active yet, short and few
    if pn.status != "READY_TO_TEST":
        raise ValidationException("Only a new number can be tested. This one is already active.")
    if not pn.agent_id or not pn.agent_version_id:
        raise ValidationException("Assign an AI employee to this number first.")
    attempts = int((pn.metadata_ or {}).get("test_attempts") or 0)
    if attempts >= settings.NUMBER_TEST_MAX_ATTEMPTS:
        raise ValidationException("This number has used all its test calls. Activate it without a test instead.")
    to = (to_number or "").strip()
    if len("".join(ch for ch in to if ch.isdigit())) < 10:
        raise ValidationException("Enter the phone number to call for the test.")
    call = place_outbound_call(db, destination_number=to, phone_number_id=pn.id, is_test=True,
                               extra_metadata={"number_test": pn.id,
                                               "max_duration_s": settings.NUMBER_TEST_MAX_DURATION_S})
    meta = dict(pn.metadata_ or {})
    meta.update(test_call_id=call.id, test_started_at=utcnow().isoformat(), test_result=None,
                test_attempts=attempts + 1)
    pn.metadata_ = meta
    db.commit()
    return call


def record_test_result(db: Session, call: Any, connected: bool, reason: Optional[str] = None) -> None:
    """Called from the carrier status callback for a test call."""
    number_id = (call.metadata_ or {}).get("number_test")
    pn = db.get(PhoneNumber, number_id) if number_id else None
    if not pn:
        return
    meta = dict(pn.metadata_ or {})
    meta["test_result"] = "CONNECTED" if connected else (reason or "NOT_CONNECTED")
    pn.metadata_ = meta
    db.commit()
    if connected:
        _activate(db, pn, "test_call")


def test_state(db: Session, pn: PhoneNumber) -> Dict[str, Any]:
    from app.models.call import Call
    meta = pn.metadata_ or {}
    call = db.get(Call, meta["test_call_id"]) if meta.get("test_call_id") else None
    return {"test_call_id": meta.get("test_call_id"), "test_call_status": call.status if call else None,
            "test_result": meta.get("test_result"), "activated_by": meta.get("activated_by")}
