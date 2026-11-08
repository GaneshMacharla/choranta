"""
Prepaid credits.

1 credit = Rs 1 (pre-GST). Clients buy credits by recharging (online, bank transfer or UPI); the payment
issues a GST tax invoice (tax on the advance) and adds the taxable value to the wallet as bought credits,
which never expire. Until the company is GST-registered (settings.GST_REGISTERED) no GST is charged:
the full amount becomes credits and the document is a payment receipt. With settings.INVOICES_ENABLED off no document
is created at all. As soon as a call ends it costs its real cost + the admin's profit %, so tax is never
charged twice.

Clients on a monthly plan (services/subscriptions.py) use the period's plan credits first; only the rest
is taken from bought credits.
"""
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.agent_version import AgentVersion
from app.models.billing import ClientBillingProfile, ClientWallet, Invoice, WalletTransaction
from app.models.call import Call
from app.models.client import Client
from app.models.runtime_session import RuntimeSession
from app.models.subscription import CallUsage, Plan
from app.services import call_capacity, notifications, subscriptions
from app.services.call_costing import estimate_call_cost
from app.services.pricing import budget_credits_per_minute, get_pricing

logger = logging.getLogger("choranta.services.billing")


def _money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def financial_year(day: date) -> str:
    """Indian financial year label, April to March: 2026-04-01 -> '2026-27'."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def get_wallet(db: Session, client_id: str, lock: bool = False) -> ClientWallet:
    query = db.query(ClientWallet).filter(ClientWallet.client_id == client_id)
    if lock:
        query = query.with_for_update()
    wallet = query.first()
    if wallet is None:
        wallet = ClientWallet(client_id=client_id, balance_inr=0.0, low_balance_threshold_inr=500.0)
        db.add(wallet)
        db.flush()
    return wallet


# Calls in these states hold a line, until they're old enough to be treated as stuck (a lost hangup webhook, or a
# restart mid-call): a call that hasn't connected after LINE_HOLD_BEFORE_ANSWER, or one that has run past its own
# maximum length by LINE_HOLD_MARGIN. LIVE_CALL_WINDOW only narrows the query: no call can legitimately last that long.
LIVE_CALL_STATUSES = ("INITIATED", "RINGING", "ANSWERED", "ACTIVE")
UNANSWERED_STATUSES = ("INITIATED", "RINGING")
LIVE_CALL_WINDOW = timedelta(hours=3)
LINE_HOLD_BEFORE_ANSWER = timedelta(minutes=5)
LINE_HOLD_MARGIN = timedelta(minutes=5)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _holds_line(status: str, created_at: datetime, answered_at: Optional[datetime], metadata: Optional[dict],
                now: datetime) -> bool:
    if status in UNANSWERED_STATUSES:
        return now < _naive_utc(created_at) + LINE_HOLD_BEFORE_ANSWER
    max_duration_s = float((metadata or {}).get("max_duration_s") or settings.CALL_MAX_DURATION_S)
    return now < _naive_utc(answered_at or created_at) + timedelta(seconds=max_duration_s) + LINE_HOLD_MARGIN


def _live_call_metadata(db: Session, *filters) -> List[Optional[dict]]:
    """The metadata of each call holding a line, among calls matching `filters`."""
    now = subscriptions.utcnow()
    rows = (
        db.query(Call.status, Call.created_at, Call.answered_at, Call.metadata_)
        .filter(Call.status.in_(LIVE_CALL_STATUSES), Call.created_at >= now - LIVE_CALL_WINDOW, *filters)
        .all()
    )
    return [meta for status, created_at, answered_at, meta in rows if _holds_line(status, created_at, answered_at, meta, now)]


def live_call_count(db: Session, client_id: str) -> int:
    return len(_live_call_metadata(db, Call.client_id == client_id))


def platform_live_call_count(db: Session) -> int:
    return len(_live_call_metadata(db))


def vobiz_live_call_count(db: Session) -> int:
    return len(_live_call_metadata(db, Call.provider == "vobiz"))


def platform_headroom(db: Session) -> int:
    """
    Calls that may still start across all clients, counting the lines kept for inbound calls: within the speech
    providers' limits and the Vobiz account's concurrent calls (one pool for every client and sub-account).
    """
    return call_capacity.free_for_inbound(platform_live_call_count(db), vobiz_live_call_count(db))


def outbound_headroom(db: Session) -> int:
    """Outbound calls that may still start: leaves the inbound lines free, and is 0 while outbound is paused."""
    return call_capacity.free_for_outbound(platform_headroom(db))


def browser_session_allowed(db: Session) -> bool:
    """Browser test calls use no phone line but do use speech capacity: they never take the last free call."""
    total = call_capacity.total_capacity()
    return total - platform_live_call_count(db) > (1 if total > 1 else 0)


PLATFORM_BUSY_REASON = "All lines are busy right now. Please try again in a few minutes."


def call_hold_credits(db: Session, max_duration_s: Optional[float] = None) -> float:
    """Credits a full-length call can cost: the budget rate x the call's longest allowed length."""
    seconds = max(60.0, float(max_duration_s or settings.CALL_MAX_DURATION_S))
    return budget_credits_per_minute(db) * seconds / 60.0


def agent_max_call_seconds(db: Session, agent_version_id: Optional[str]) -> int:
    """The agent version's own maximum call length, else the platform default."""
    version = db.get(AgentVersion, agent_version_id) if agent_version_id else None
    config = (version.configuration_json or {}) if version else {}
    limits = (config.get("conversation") or {}).get("limits") or {}
    return int(limits.get("max_call_duration_s") or settings.CALL_MAX_DURATION_S)


def held_credits(db: Session, client_id: str) -> Tuple[int, float]:
    """Live calls and the credits their budgets hold. Calls from before budgets hold a full-length call."""
    calls = _live_call_metadata(db, Call.client_id == client_id)
    held = 0.0
    for meta in calls:
        meta = meta or {}
        if meta.get("is_test"):
            continue
        budget = meta.get("credit_budget")
        held += float(budget) if budget is not None else call_hold_credits(db)
    return len(calls), held


def _spendable(wallet: Optional[ClientWallet], sub, plan, on_plan: bool) -> float:
    """Credits a client can spend on calls: this period's plan credits plus bought credits."""
    plan_left = max(0.0, subscriptions.remaining_credits(sub, plan)) if on_plan else 0.0
    return plan_left + max(0.0, wallet.balance_inr if wallet else 0.0)


def client_concurrency_limit(db: Session, client_id: str) -> Optional[int]:
    """
    Most calls a client may have live at once: their usable plan's limit, else as many full-length calls
    as their credits cover (at least one; call budgets decide whether that one may start), up to the
    platform cap. None = unlimited.
    """
    return _wallet_or_plan_limit(db, client_id)


def _wallet_or_plan_limit(db: Session, client_id: str) -> Optional[int]:
    sub = subscriptions.get_subscription(db, client_id)
    plan = db.get(Plan, sub.plan_id) if sub else None
    if sub and plan and subscriptions.is_usable(sub):
        return plan.max_concurrent_calls or None
    if not settings.PAYG_ONLY:
        return None  # with plans on sale, clients without one aren't limited
    wallet = db.query(ClientWallet).filter(ClientWallet.client_id == client_id).first()
    hold = call_hold_credits(db)
    covered = int(_spendable(wallet, sub, plan, False) // hold) if hold > 0 else settings.MAX_CONCURRENT_CALLS_PER_CLIENT
    return min(settings.MAX_CONCURRENT_CALLS_PER_CLIENT, max(1, covered))


def call_budget(
    db: Session, client_id: Optional[str], max_duration_s: Optional[float] = None, lock: bool = False,
    inbound: bool = False,
) -> Tuple[bool, Optional[str], Optional[str], Optional[float]]:
    """
    Whether a new billable call may start, and the credits it may spend: (allowed, reason, code, budget).
    Codes: PLAN_EXPIRED, NO_BALANCE, CONCURRENCY (the client's limit or the platform's). A call's budget is a full-length call's cost, or what is
    left after the budgets of calls already live; it must cover CALL_MIN_BUDGET_MINUTES. The session hangs
    up before spending more, so the balance never goes below zero.

    With lock=True the wallet row stays locked until the caller commits: create the Call (with its
    budget) before committing, so concurrent call starts can't spend the same credits twice.

    Only inbound calls (inbound=True) may use the lines kept free for them.
    """
    if (platform_headroom(db) if inbound else outbound_headroom(db)) <= 0:
        return False, PLATFORM_BUSY_REASON, "CONCURRENCY", None
    if not settings.BILLING_ENFORCED or not client_id:
        return True, None, None, None
    if lock:
        wallet = get_wallet(db, client_id, lock=True)
    else:
        wallet = db.query(ClientWallet).filter(ClientWallet.client_id == client_id).first()
    sub = subscriptions.get_subscription(db, client_id)
    plan = db.get(Plan, sub.plan_id) if sub else None
    on_plan = bool(sub and plan and subscriptions.is_usable(sub))
    if not on_plan and sub and plan and sub.status == "PAST_DUE" and not settings.PAYG_ONLY:
        return False, f"The {plan.name} plan has expired. Renew it to resume calls.", "PLAN_EXPIRED", None

    live, held = held_credits(db, client_id)
    limit = client_concurrency_limit(db, client_id)
    if limit and live >= limit:
        if on_plan:
            return False, (f"The {plan.name} plan allows {limit} call(s) at a time. "
                           "Wait for a call to finish or upgrade the plan."), "CONCURRENCY", None
        return False, (f"Your balance covers {limit} call(s) at a time. "
                       "Wait for a call to finish, or add credits to run more calls at once."), "CONCURRENCY", None

    available = _spendable(wallet, sub, plan, on_plan) - held
    if available < budget_credits_per_minute(db) * settings.CALL_MIN_BUDGET_MINUTES:
        if held > 0:
            return False, ("Your credits are reserved for the calls already running. "
                           "Wait for a call to finish, or add credits to run more calls at once."), "CONCURRENCY", None
        if on_plan:
            return False, "This month's plan credits are used up. Buy credits to keep calling.", "NO_BALANCE", None
        hint = "Buy credits" if settings.PAYG_ONLY else "Choose a plan or buy credits"
        return False, f"You're out of credits. {hint} to resume calls.", "NO_BALANCE", None
    # Rounded down, so a budget never exceeds what is really left
    return True, None, None, math.floor(min(call_hold_credits(db, max_duration_s), available) * 100) / 100


def check_call_allowed(
    db: Session, client_id: Optional[str], max_duration_s: Optional[float] = None, inbound: bool = False,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Whether a new billable call may start, as (allowed, reason, code); see call_budget."""
    return call_budget(db, client_id, max_duration_s, inbound=inbound)[:3]


def gst_split(total_received: float, client_state_code: Optional[str]) -> Dict[str, Any]:
    """Splits a GST-inclusive amount into taxable value and CGST+SGST (same state) or IGST."""
    rate = settings.EFFECTIVE_GST_RATE_PERCENT / 100.0
    taxable = _money(total_received / (1 + rate))
    tax = _money(total_received - taxable)
    place_of_supply = (client_state_code or settings.COMPANY_STATE_CODE or "").strip()
    intra_state = place_of_supply == (settings.COMPANY_STATE_CODE or "").strip()
    cgst = _money(tax / 2) if intra_state else 0.0
    sgst = _money(tax - cgst) if intra_state else 0.0
    igst = 0.0 if intra_state else tax
    return {
        "taxable_inr": taxable,
        "cgst_inr": cgst,
        "sgst_inr": sgst,
        "igst_inr": igst,
        "total_inr": _money(total_received),
        "place_of_supply": place_of_supply,
        "intra_state": intra_state,
        "gst_registered": settings.GST_REGISTERED,
    }


def _bill_to(db: Session, client_id: str) -> Dict[str, Any]:
    profile = db.get(ClientBillingProfile, client_id)
    client = db.get(Client, client_id)
    if profile:
        return {
            "legal_name": profile.legal_name,
            "gstin": profile.gstin,
            "address": profile.address,
            "state_code": profile.state_code,
            "billing_email": profile.billing_email,
        }
    return {"legal_name": client.name if client else client_id, "gstin": None, "address": None, "state_code": None, "billing_email": None}


def _next_invoice_number(db: Session, fy: str) -> tuple:
    last = db.query(func.max(Invoice.sequence)).filter(Invoice.financial_year == fy).scalar()
    sequence = int(last or 0) + 1
    return sequence, f"{settings.INVOICE_PREFIX}/{fy}/{sequence:04d}"


def _issue_invoice(
    db: Session, client_id: str, amount_received: float, reference: Optional[str], admin_id: Optional[str],
    description: Optional[str] = None, issue_date: Optional[date] = None,
) -> Tuple[Optional[Invoice], Dict[str, Any]]:
    """Adds (does not commit) a GST tax invoice for a GST-inclusive amount received; no invoice while they're switched off."""
    if amount_received <= 0:
        raise ValidationException("Payment amount must be greater than zero.")
    bill_to = _bill_to(db, client_id)
    split = gst_split(amount_received, bill_to.get("state_code"))
    if not settings.INVOICES_ENABLED:
        return None, split
    day = issue_date or datetime.now(timezone.utc).date()
    fy = financial_year(day)
    sequence, number = _next_invoice_number(db, fy)
    invoice = Invoice(
        number=number,
        client_id=client_id,
        issue_date=day,
        financial_year=fy,
        sequence=sequence,
        taxable_inr=split["taxable_inr"],
        cgst_inr=split["cgst_inr"],
        sgst_inr=split["sgst_inr"],
        igst_inr=split["igst_inr"],
        total_inr=split["total_inr"],
        place_of_supply=split["place_of_supply"],
        payment_reference=reference,
        bill_to=json.dumps(bill_to),
        description=description,
        created_by=admin_id,
    )
    db.add(invoice)
    db.flush()
    return invoice, split


def record_payment(
    db: Session, client_id: str, amount_received: float, reference: Optional[str], admin_id: Optional[str],
    issue_date: Optional[date] = None, commit: bool = True,
) -> Dict[str, Any]:
    """Records a GST-inclusive recharge: issues the invoice and credits the taxable value."""
    invoice, split = _issue_invoice(db, client_id, amount_received, reference, admin_id, issue_date=issue_date)
    wallet = get_wallet(db, client_id, lock=True)
    wallet.balance_inr = _money(wallet.balance_inr + split["taxable_inr"])
    txn = WalletTransaction(
        client_id=client_id,
        type="CREDIT",
        amount_inr=split["taxable_inr"],
        balance_after_inr=wallet.balance_inr,
        invoice_id=invoice.id if invoice else None,
        reference=reference,
        note=f"Recharge, invoice {invoice.number}" if invoice else "Recharge",
        created_by=admin_id,
    )
    db.add(txn)
    db.flush()
    if invoice:
        invoice.transaction_id = txn.id
    notifications.notify(
        db, client_id, "CREDITS_ADDED", f"{notifications.credits_text(split['taxable_inr'])} credits added",
        f"You now have {notifications.credits_text(wallet.balance_inr)} bought credits. They never expire.",
        link="/portal/billing", level="success",
    )
    if commit:
        db.commit()
    logger.info(f"Recorded payment of Rs {amount_received} for {client_id}: wallet {wallet.balance_inr}")
    return {"invoice_id": invoice.id if invoice else None, "invoice_number": invoice.number if invoice else None,
            "balance_inr": wallet.balance_inr, **split}


def plan_price_with_gst(plan: Plan) -> float:
    return _money(plan.monthly_price_inr * (1 + settings.EFFECTIVE_GST_RATE_PERCENT / 100.0))


def pay_for_plan(
    db: Session, client_id: str, plan: Plan, reference: Optional[str], admin_id: Optional[str],
    amount_received: Optional[float] = None, commit: bool = True,
) -> Dict[str, Any]:
    """Records a plan payment (GST included): applies the period and issues its invoice. No wallet credit."""
    blocker = subscriptions.renewal_blocker(subscriptions.get_subscription(db, client_id), plan)
    if blocker:
        raise ValidationException(blocker)
    sub = subscriptions.activate_period(db, client_id, plan)
    # The invoice covers the period being paid for, which is the next one when renewing early
    if sub.renewed_ahead:
        start = sub.current_period_end
        label = f"{start:%d %b %Y} - {subscriptions.add_month(start):%d %b %Y}"
    else:
        label = subscriptions.period_label(sub)
    description = f"AI voice agent services - {plan.name} plan, {label}"
    invoice, split = _issue_invoice(
        db, client_id, amount_received if amount_received is not None else plan_price_with_gst(plan),
        reference, admin_id, description=description,
    )
    credits = notifications.credits_text(subscriptions.plan_credits(plan))
    if sub.renewed_ahead:
        notifications.notify(db, client_id, "PLAN_RENEWED", f"{plan.name} plan renewed",
                             f"Next month is paid for: {label}.", link="/portal/billing", level="success")
    elif notifications.has_ai_employee(db, client_id):
        notifications.notify(db, client_id, "PLAN_ACTIVE", f"Your {plan.name} plan is active",
                             f"{credits} credits are ready for this month.", link="/portal/billing", level="success")
    else:
        notifications.notify(db, client_id, "PLAN_ACTIVE", f"Your {plan.name} plan is active",
                             f"{credits} credits are ready. Next step: create your first AI employee.",
                             link="/portal/employees", level="success")
    if commit:
        db.commit()
    logger.info(f"Recorded {plan.name} plan payment for {client_id}")
    return {"invoice_id": invoice.id if invoice else None, "invoice_number": invoice.number if invoice else None,
            "subscription": subscriptions.subscription_out(db, client_id), **split}


def adjust_wallet(db: Session, client_id: str, amount: float, note: str, admin_id: Optional[str]) -> ClientWallet:
    """Admin correction (refund, goodwill credit, manual debit). No invoice."""
    if not amount:
        raise ValidationException("Adjustment amount can't be zero.")
    if not (note or "").strip():
        raise ValidationException("Add a note explaining the adjustment.")
    wallet = get_wallet(db, client_id, lock=True)
    wallet.balance_inr = _money(wallet.balance_inr + amount)
    db.add(WalletTransaction(
        client_id=client_id, type="ADJUSTMENT", amount_inr=_money(amount), balance_after_inr=wallet.balance_inr,
        note=note.strip(), created_by=admin_id,
    ))
    db.commit()
    return wallet


def call_charge(db: Session, call: Call) -> Optional[float]:
    """
    Credits (1 credit = Rs 1, pre-GST) a finished call costs: its real cost (carrier minutes, speech-to-text,
    text-to-speech, LLM tokens) plus the admin's profit %. None if it isn't billable.
    """
    if (call.metadata_ or {}).get("is_test") or call.status != "COMPLETED" or not call.duration_seconds:
        return None
    usage: Dict[str, Any] = {}
    if call.runtime_session_id:
        session_obj = db.get(RuntimeSession, call.runtime_session_id)
        if session_obj and isinstance(session_obj.usage_json, dict):
            usage = session_obj.usage_json
    amount = _money(estimate_call_cost(call.duration_seconds, usage, get_pricing(db))["charge_total"])
    return amount if amount > 0 else None


def billed_minutes(duration_seconds: float) -> float:
    """Call minutes billed against a plan, in the carrier's pulses (60 s pulse -> per started minute)."""
    pulse = max(1, settings.TELEPHONY_BILLING_PULSE_SECONDS)
    return math.ceil(max(0.0, float(duration_seconds)) / pulse) * pulse / 60.0


def _debit(db: Session, call: Call, amount: float) -> WalletTransaction:
    """Takes bought credits for a call. Callers never take more than the balance."""
    wallet = get_wallet(db, call.client_id, lock=True)
    wallet.balance_inr = _money(wallet.balance_inr - amount)
    txn = WalletTransaction(
        client_id=call.client_id,
        type="DEBIT",
        amount_inr=-amount,
        balance_after_inr=wallet.balance_inr,
        call_id=call.id,
        note=f"Call to {call.destination_number}" if call.direction == "OUTBOUND" else f"Call from {call.caller_number}",
    )
    db.add(txn)
    return txn


def charge_call(db: Session, call: Call) -> Optional[WalletTransaction]:
    """
    Bills a completed call once, right after it ends: real cost + profit %, in credits. Plan credits are
    used first, then bought credits (the wallet). Returns the wallet debit, if there was one.
    """
    if not call.client_id:
        return None
    if (call.metadata_ or {}).get("is_test") or call.status != "COMPLETED" or not call.duration_seconds:
        return None
    # Lock the wallet first: the session and the carrier's status callback may both try to charge the
    # call, and the second must see the first one's charge
    wallet = get_wallet(db, call.client_id, lock=True)
    already = (
        db.query(CallUsage.id).filter(CallUsage.call_id == call.id).first()
        or db.query(WalletTransaction.id).filter(WalletTransaction.call_id == call.id).first()
    )
    if already:
        db.commit()
        return None

    credits = call_charge(db, call)
    if credits is None:
        return None
    minutes = billed_minutes(call.duration_seconds)
    rate = credits / minutes if minutes else 0.0

    sub = subscriptions.get_subscription(db, call.client_id, lock=True)
    plan = db.get(Plan, sub.plan_id) if sub else None
    on_plan = bool(sub and plan and subscriptions.is_usable(sub))
    from_plan = _money(min(credits, subscriptions.remaining_credits(sub, plan))) if on_plan else 0.0
    from_wallet = _money(credits - from_plan)
    plan_left_before = subscriptions.remaining_credits(sub, plan) if on_plan else 0.0
    if on_plan:
        sub.credits_used = round(float(sub.credits_used or 0.0) + from_plan, 4)
        sub.minutes_used = round(float(sub.minutes_used or 0.0) + minutes, 4)
    wallet_before = wallet.balance_inr
    # The balance never goes below zero. Call budgets end calls before they overspend, so an unpaid
    # remainder means a budget was too small: it is recorded on the call and logged for the admin.
    paid = _money(min(from_wallet, max(0.0, wallet_before)))
    unpaid = _money(from_wallet - paid)
    if unpaid > 0:
        call.metadata_ = {**(call.metadata_ or {}), "unpaid_credits": unpaid}
        logger.error(f"Call {call.id} cost {unpaid} credits more than client {call.client_id} had; not charged")
    from_wallet = paid
    txn = _debit(db, call, from_wallet) if from_wallet > 0 else None
    _notify_low_credits(db, call.client_id, plan, plan_left_before, plan_left_before - from_plan if on_plan else 0.0,
                        wallet_before, wallet_before - from_wallet)
    plan_minutes = round(from_plan / rate, 4) if rate else 0.0
    db.add(CallUsage(
        call_id=call.id, client_id=call.client_id, plan_id=plan.id if on_plan else None, billed_minutes=minutes,
        included_minutes=plan_minutes, overage_minutes=round(minutes - plan_minutes, 4),
        overage_charge_inr=from_wallet, plan_credits=from_plan, wallet_credits=from_wallet,
    ))
    db.commit()
    logger.info(f"Charged call {call.id}: {credits} credits ({from_plan} plan, {from_wallet} bought)")
    return txn


def message_charge(db: Session, category: Optional[str]) -> float:
    """Credits one WhatsApp follow-up costs: Meta's price for its template category + the admin's profit %."""
    cost = settings.WHATSAPP_MARKETING_COST_INR if (category or "").upper() == "MARKETING" else settings.WHATSAPP_UTILITY_COST_INR
    return _money(cost * (1 + get_pricing(db).profit_percent / 100.0))


def can_afford_message(db: Session, client_id: str, credits: float) -> bool:
    if not settings.BILLING_ENFORCED:
        return True
    wallet = db.query(ClientWallet).filter(ClientWallet.client_id == client_id).first()
    sub = subscriptions.get_subscription(db, client_id)
    plan = db.get(Plan, sub.plan_id) if sub else None
    on_plan = bool(sub and plan and subscriptions.is_usable(sub))
    return _spendable(wallet, sub, plan, on_plan) >= credits


def charge_message(db: Session, client_id: str, message_id: str, credits: float, note: str) -> float:
    """
    Bills a sent WhatsApp message once: plan credits first, then bought credits (never below zero).
    Returns the credits taken. Only the message's sender (which claimed it) calls this; the caller commits.
    """
    reference = f"whatsapp:{message_id}"
    wallet = get_wallet(db, client_id, lock=True)
    if db.query(WalletTransaction.id).filter(WalletTransaction.reference == reference).first():
        return 0.0
    sub = subscriptions.get_subscription(db, client_id, lock=True)
    plan = db.get(Plan, sub.plan_id) if sub else None
    from_plan = 0.0
    if sub and plan and subscriptions.is_usable(sub):
        from_plan = _money(min(credits, subscriptions.remaining_credits(sub, plan)))
        sub.credits_used = round(float(sub.credits_used or 0.0) + from_plan, 4)
    from_wallet = _money(min(credits - from_plan, max(0.0, wallet.balance_inr)))
    if from_wallet > 0:
        wallet.balance_inr = _money(wallet.balance_inr - from_wallet)
        db.add(WalletTransaction(client_id=client_id, type="DEBIT", amount_inr=-from_wallet,
                                 balance_after_inr=wallet.balance_inr, reference=reference, note=note))
    return _money(from_plan + from_wallet)


# A finished call's session charges it within seconds; one still unbilled after this was missed (e.g.
# the server restarted mid-call and only the carrier's completed status arrived) and is charged by the sweep
UNBILLED_GRACE = timedelta(minutes=2)
UNBILLED_LOOKBACK = timedelta(days=7)


def charge_unbilled_calls(db: Session, now: Optional[datetime] = None) -> int:
    """Charges completed calls nothing has billed yet. Safe to run repeatedly; returns how many it charged."""
    now = now or subscriptions.utcnow()
    candidates = (
        db.query(Call)
        .outerjoin(CallUsage, CallUsage.call_id == Call.id)
        .outerjoin(WalletTransaction, WalletTransaction.call_id == Call.id)
        .filter(
            Call.status == "COMPLETED", Call.client_id.isnot(None), Call.duration_seconds > 0,
            Call.ended_at <= now - UNBILLED_GRACE, Call.ended_at >= now - UNBILLED_LOOKBACK,
            CallUsage.id.is_(None), WalletTransaction.id.is_(None),
        )
        .all()
    )
    charged = 0
    for call in candidates:
        if (call.metadata_ or {}).get("is_test") or (call.metadata_ or {}).get("mock"):
            continue
        try:
            charge_call(db, call)
            charged += 1
        except Exception as exc:
            db.rollback()
            logger.error(f"Could not charge unbilled call {call.id}: {type(exc).__name__}: {exc}")
    if charged:
        logger.warning(f"Charged {charged} call(s) that ended without being billed")
    return charged


def run_billing_sweep_job(session_factory) -> None:
    db = session_factory()
    try:
        charge_unbilled_calls(db)
    finally:
        db.close()


def _notify_low_credits(db: Session, client_id: str, plan: Optional[Plan], plan_before: float, plan_after: float,
                        wallet_before: float, wallet_after: float) -> None:
    """Tells the client once, at the moment a balance runs low or out (not on every call after)."""
    wallet = get_wallet(db, client_id)
    threshold = wallet.low_balance_threshold_inr
    left = max(0.0, plan_after) + max(0.0, wallet_after)
    if plan and plan_before > 0 >= plan_after:
        if wallet_after > 0:
            notifications.notify(db, client_id, "PLAN_CREDITS_USED", "This month's plan credits are used up",
                                 f"Calls now use your bought credits ({notifications.credits_text(wallet_after)} left).",
                                 link="/portal/billing", level="warning")
        else:
            notifications.notify(db, client_id, "CREDITS_OUT", "You're out of credits",
                                 "Your AI employee can't take calls until you buy credits or your plan renews.",
                                 link="/portal/billing", level="warning")
        return
    if plan_after > 0:
        return  # plan credits still cover calls
    if wallet_before > 0 >= wallet_after:
        notifications.notify(db, client_id, "CREDITS_OUT", "You're out of credits",
                             "Your AI employee can't take calls until you buy credits.",
                             link="/portal/billing", level="warning")
    elif wallet_before > threshold >= wallet_after:
        notifications.notify(db, client_id, "CREDITS_LOW", "Credits are running low",
                             f"Only {notifications.credits_text(left)} credits left. Buy more so calls aren't interrupted.",
                             link="/portal/billing", level="warning")


def amount_in_words(amount: float) -> str:
    """Indian numbering: 11800.5 -> 'Rupees Eleven Thousand Eight Hundred and Fifty Paise Only'."""
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
            "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(n: int) -> str:
        return ones[n] if n < 20 else (tens[n // 10] + (" " + ones[n % 10] if n % 10 else ""))

    def three(n: int) -> str:
        hundred, rest = divmod(n, 100)
        parts = []
        if hundred:
            parts.append(f"{ones[hundred]} Hundred")
        if rest:
            parts.append(two(rest))
        return " ".join(parts)

    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))
    words = []
    for value, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        count, rupees = divmod(rupees, value)
        if count:
            words.append(f"{three(count) if count < 1000 else amount_in_words(count).replace('Rupees ', '').replace(' Only', '')} {name}")
    if rupees:
        words.append(three(rupees))
    text = "Rupees " + (" ".join(words) or "Zero")
    if paise:
        text += f" and {two(paise)} Paise"
    return text + " Only"
