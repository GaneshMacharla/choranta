"""
Prepaid wallet billing.

Clients recharge by bank transfer / UPI; an admin records the payment, which issues a GST tax
invoice (tax on the advance) and credits the wallet with the taxable value. Each completed call
is then debited at its client charge (pre-GST `charge_total`), so tax is never charged twice.
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.billing import ClientBillingProfile, ClientWallet, Invoice, WalletTransaction
from app.models.call import Call
from app.models.client import Client
from app.models.runtime_session import RuntimeSession
from app.services.call_costing import estimate_call_cost
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


def can_place_call(db: Session, client_id: Optional[str]) -> bool:
    """New billable calls need a positive balance (when balance enforcement is on)."""
    if not settings.BILLING_ENFORCED or not client_id:
        return True
    wallet = db.query(ClientWallet).filter(ClientWallet.client_id == client_id).first()
    return bool(wallet and wallet.balance_inr > 0)


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


def record_payment(
    db: Session, client_id: str, amount_received: float, reference: Optional[str], admin_id: Optional[str],
    issue_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Records a GST-inclusive recharge: issues the invoice and credits the taxable value."""
    if amount_received <= 0:
        raise ValidationException("Payment amount must be greater than zero.")
    bill_to = _bill_to(db, client_id)
    split = gst_split(amount_received, bill_to.get("state_code"))
    day = issue_date or datetime.now(timezone.utc).date()
    fy = financial_year(day)
    sequence, number = _next_invoice_number(db, fy)

    wallet = get_wallet(db, client_id, lock=True)
    wallet.balance_inr = _money(wallet.balance_inr + split["taxable_inr"])
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
        created_by=admin_id,
    )
    db.add(invoice)
    db.flush()
    txn = WalletTransaction(
        client_id=client_id,
        type="CREDIT",
        amount_inr=split["taxable_inr"],
        balance_after_inr=wallet.balance_inr,
        invoice_id=invoice.id,
        reference=reference,
        note=f"Recharge, invoice {number}",
        created_by=admin_id,
    )
    db.add(txn)
    db.flush()
    invoice.transaction_id = txn.id
    db.commit()
    logger.info(f"Recorded payment of Rs {amount_received} for {client_id}: invoice {number}, wallet {wallet.balance_inr}")
    return {"invoice_id": invoice.id, "invoice_number": number, "balance_inr": wallet.balance_inr, **split}


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
    """Client charge (pre-GST, INR) for a finished call, or None if it isn't billable."""
    if (call.metadata_ or {}).get("is_test") or call.status != "COMPLETED" or not call.duration_seconds:
        return None
    usage: Dict[str, Any] = {}
    if call.runtime_session_id:
        session_obj = db.get(RuntimeSession, call.runtime_session_id)
        if session_obj and isinstance(session_obj.usage_json, dict):
            usage = session_obj.usage_json
    amount = estimate_call_cost(call.duration_seconds, usage, get_pricing(db))["charge_total"]
    return _money(amount) if amount > 0 else None


def charge_call(db: Session, call: Call) -> Optional[WalletTransaction]:
    """Debits a completed call's charge from the client's wallet, once per call."""
    if not call.client_id:
        return None
    if db.query(WalletTransaction.id).filter(WalletTransaction.call_id == call.id).first():
        return None
    amount = call_charge(db, call)
    if amount is None:
        return None
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
    db.commit()
    logger.info(f"Charged call {call.id}: Rs {amount}, wallet now {wallet.balance_inr}")
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
