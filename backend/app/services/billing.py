"""
Prepaid credits.

1 credit = Rs 1 (pre-GST). Clients buy credits by recharging (online, bank transfer or UPI); the payment
issues a GST tax invoice (tax on the advance) and adds the taxable value to the wallet as bought credits,
which never expire. Each completed call costs billed minutes x credits per minute, so tax is never
charged twice.

Clients on a monthly plan (services/subscriptions.py) use the period's plan credits first; only the rest
is taken from bought credits.
"""
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.billing import ClientBillingProfile, ClientWallet, Invoice, WalletTransaction
from app.models.call import Call
from app.models.client import Client
from app.models.subscription import CallUsage, Plan
from app.services import subscriptions
from app.services.pricing import get_pricing

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


# Calls in these states hold a line; older rows are treated as stuck and don't count
LIVE_CALL_STATUSES = ("INITIATED", "RINGING", "ANSWERED", "ACTIVE")
LIVE_CALL_WINDOW = timedelta(hours=3)


def live_call_count(db: Session, client_id: str) -> int:
    since = subscriptions.utcnow() - LIVE_CALL_WINDOW
    return (
        db.query(func.count(Call.id))
        .filter(Call.client_id == client_id, Call.status.in_(LIVE_CALL_STATUSES), Call.created_at >= since)
        .scalar() or 0
    )


def check_call_allowed(db: Session, client_id: Optional[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Whether a new billable call may start, as (allowed, reason, code). Codes: PLAN_EXPIRED, NO_BALANCE,
    CONCURRENCY. Plan clients need plan credits or bought credits; others need bought credits.
    """
    if not settings.BILLING_ENFORCED or not client_id:
        return True, None, None
    wallet = db.query(ClientWallet).filter(ClientWallet.client_id == client_id).first()
    has_balance = bool(wallet and wallet.balance_inr > 0)
    sub = subscriptions.get_subscription(db, client_id)
    plan = db.get(Plan, sub.plan_id) if sub else None

    if sub and plan and subscriptions.is_usable(sub):
        if subscriptions.remaining_credits(sub, plan) <= 0 and not has_balance:
            return False, "This month's plan credits are used up. Buy credits to keep calling.", "NO_BALANCE"
        if plan.max_concurrent_calls and live_call_count(db, client_id) >= plan.max_concurrent_calls:
            return False, (f"The {plan.name} plan allows {plan.max_concurrent_calls} call(s) at a time. "
                           "Wait for a call to finish or upgrade the plan."), "CONCURRENCY"
        return True, None, None
    if sub and plan and sub.status == "PAST_DUE":
        return False, f"The {plan.name} plan has expired. Renew it to resume calls.", "PLAN_EXPIRED"
    # No plan, or a cancelled one: bought credits only
    if not has_balance:
        return False, "You're out of credits. Choose a plan or buy credits to resume calls.", "NO_BALANCE"
    return True, None, None


def can_place_call(db: Session, client_id: Optional[str]) -> bool:
    """New billable calls need plan minutes or a positive balance (when balance enforcement is on)."""
    return check_call_allowed(db, client_id)[0]


def gst_split(total_received: float, client_state_code: Optional[str]) -> Dict[str, Any]:
    """Splits a GST-inclusive amount into taxable value and CGST+SGST (same state) or IGST."""
    rate = settings.GST_RATE_PERCENT / 100.0
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
) -> Tuple[Invoice, Dict[str, Any]]:
    """Adds (does not commit) a GST tax invoice for a GST-inclusive amount received."""
    if amount_received <= 0:
        raise ValidationException("Payment amount must be greater than zero.")
    bill_to = _bill_to(db, client_id)
    split = gst_split(amount_received, bill_to.get("state_code"))
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
        invoice_id=invoice.id,
        reference=reference,
        note=f"Recharge, invoice {invoice.number}",
        created_by=admin_id,
    )
    db.add(txn)
    db.flush()
    invoice.transaction_id = txn.id
    if commit:
        db.commit()
    logger.info(f"Recorded payment of Rs {amount_received} for {client_id}: invoice {invoice.number}, wallet {wallet.balance_inr}")
    return {"invoice_id": invoice.id, "invoice_number": invoice.number, "balance_inr": wallet.balance_inr, **split}


def plan_price_with_gst(plan: Plan) -> float:
    return _money(plan.monthly_price_inr * (1 + settings.GST_RATE_PERCENT / 100.0))


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
    if commit:
        db.commit()
    logger.info(f"Recorded {plan.name} plan payment for {client_id}: invoice {invoice.number}")
    return {"invoice_id": invoice.id, "invoice_number": invoice.number,
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
    """Credits (1 credit = Rs 1, pre-GST) a finished call costs, or None if it isn't billable."""
    if (call.metadata_ or {}).get("is_test") or call.status != "COMPLETED" or not call.duration_seconds:
        return None
    amount = _money(billed_minutes(call.duration_seconds) * get_pricing(db).credits_per_minute)
    return amount if amount > 0 else None


def billed_minutes(duration_seconds: float) -> float:
    """Call minutes billed against a plan, in the carrier's pulses (60 s pulse -> per started minute)."""
    pulse = max(1, settings.TELEPHONY_BILLING_PULSE_SECONDS)
    return math.ceil(max(0.0, float(duration_seconds)) / pulse) * pulse / 60.0


def _debit(db: Session, call: Call, amount: float) -> WalletTransaction:
    """Takes bought credits for a call; the balance may dip below zero for the call that ran it out."""
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
    Bills a completed call once: billed minutes x credits per minute. Plan credits are used first, then
    bought credits (the wallet). Returns the wallet debit, if there was one.
    """
    if not call.client_id:
        return None
    already = (
        db.query(CallUsage.id).filter(CallUsage.call_id == call.id).first()
        or db.query(WalletTransaction.id).filter(WalletTransaction.call_id == call.id).first()
    )
    if already:
        return None
    if (call.metadata_ or {}).get("is_test") or call.status != "COMPLETED" or not call.duration_seconds:
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
    if on_plan:
        sub.credits_used = round(float(sub.credits_used or 0.0) + from_plan, 4)
        sub.minutes_used = round(float(sub.minutes_used or 0.0) + minutes, 4)
    txn = _debit(db, call, from_wallet) if from_wallet > 0 else None
    plan_minutes = round(from_plan / rate, 4) if rate else 0.0
    db.add(CallUsage(
        call_id=call.id, client_id=call.client_id, plan_id=plan.id if on_plan else None, billed_minutes=minutes,
        included_minutes=plan_minutes, overage_minutes=round(minutes - plan_minutes, 4),
        overage_charge_inr=from_wallet, plan_credits=from_plan, wallet_credits=from_wallet,
    ))
    db.commit()
    logger.info(f"Charged call {call.id}: {credits} credits ({from_plan} plan, {from_wallet} bought)")
    return txn


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
