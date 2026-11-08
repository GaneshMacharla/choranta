"""
Razorpay online payments for plan periods and wallet top-ups.

The portal creates an order here, the browser pays it with Razorpay Checkout and sends back the signed
payment, which we verify and fulfil. Razorpay's webhook fulfils the same order if the browser never
comes back; fulfilment runs once per order.
"""
import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.subscription import PaymentOrder, Plan
from app.services import billing, subscriptions

logger = logging.getLogger("choranta.services.razorpay")

RAZORPAY_API = "https://api.razorpay.com/v1"


class RazorpayError(Exception):
    pass


SIMULATED_PREFIX = "sim_"


def is_configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def is_simulated() -> bool:
    """Testing mode: no Razorpay keys, and payments are confirmed in-app (never in production)."""
    return bool(settings.SIMULATED_PAYMENTS) and not is_configured() and settings.ENVIRONMENT != "production"


def online_enabled() -> bool:
    return is_configured() or is_simulated()


def _create_razorpay_order(amount_paise: int, receipt: str, notes: Dict[str, str]) -> Dict[str, Any]:
    try:
        response = httpx.post(
            f"{RAZORPAY_API}/orders",
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise RazorpayError(f"Couldn't reach Razorpay: {exc}") from exc
    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("description") if response.content else None
        raise RazorpayError(f"Razorpay rejected the order: {detail or response.status_code}")
    return response.json()


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, signature: str) -> bool:
    expected = _hmac_hex(settings.RAZORPAY_KEY_SECRET, f"{razorpay_order_id}|{razorpay_payment_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    return hmac.compare_digest(_hmac_hex(settings.RAZORPAY_WEBHOOK_SECRET, body), signature or "")


def create_order(
    db: Session, client_id: str, purpose: str, user_id: Optional[str],
    plan_id: Optional[str] = None, amount_inr: Optional[float] = None,
) -> Dict[str, Any]:
    """Creates a Razorpay order for a plan period (price + GST) or a wallet top-up (GST-inclusive amount)."""
    simulated = is_simulated()
    if not (is_configured() or simulated):
        raise ValidationException("Online payments aren't set up yet. Please contact Choranta.")
    if purpose == "SUBSCRIPTION":
        plan = db.get(Plan, plan_id) if plan_id else None
        if not plan or not plan.is_active:
            raise ValidationException("Choose an available plan.")
        blocker = subscriptions.renewal_blocker(subscriptions.get_subscription(db, client_id), plan)
        if blocker:
            raise ValidationException(blocker)
        amount = billing.plan_price_with_gst(plan)
        description = f"{plan.name} plan - 1 month"
    elif purpose == "WALLET_TOPUP":
        if amount_inr is None or amount_inr < settings.MIN_WALLET_TOPUP_INR:
            raise ValidationException(f"The minimum top-up is Rs {settings.MIN_WALLET_TOPUP_INR:,.0f}.")
        amount = round(float(amount_inr), 2)
        plan = None
        description = "Wallet top-up"
    else:
        raise ValidationException("Unknown payment purpose.")

    order = PaymentOrder(client_id=client_id, purpose=purpose, plan_id=plan.id if plan else None,
                         amount_inr=amount, created_by=user_id)
    db.add(order)
    db.flush()
    amount_paise = int(round(amount * 100))
    if simulated:
        rp = {"id": f"{SIMULATED_PREFIX}{order.id}"}
    else:
        rp = _create_razorpay_order(amount_paise, order.id, {"client_id": client_id, "purpose": purpose})
    order.razorpay_order_id = rp["id"]
    db.commit()
    return {
        "simulated": simulated,
        "order_id": order.id,
        "razorpay_order_id": rp["id"],
        "amount_paise": amount_paise,
        "currency": "INR",
        "key_id": settings.RAZORPAY_KEY_ID,
        "company_name": settings.COMPANY_LEGAL_NAME,
        "description": description,
    }


def fulfil_order(db: Session, order: PaymentOrder, razorpay_payment_id: str) -> PaymentOrder:
    """Applies a paid order (plan period or wallet credit) and issues its invoice, if invoices are on. Safe to call twice."""
    order = db.query(PaymentOrder).filter(PaymentOrder.id == order.id).with_for_update().first()
    if order.status == "PAID":
        return order
    simulated = razorpay_payment_id.startswith(SIMULATED_PREFIX)
    reference = f"TEST - simulated payment {razorpay_payment_id}" if simulated else f"Razorpay {razorpay_payment_id}"
    plan = db.get(Plan, order.plan_id) if order.purpose == "SUBSCRIPTION" else None
    blocker = subscriptions.renewal_blocker(subscriptions.get_subscription(db, order.client_id), plan) if plan else None
    if plan and not blocker:
        result = billing.pay_for_plan(db, order.client_id, plan, reference, order.created_by,
                                      amount_received=order.amount_inr, commit=False)
    else:
        if plan:  # e.g. the next period was paid twice: keep the money as wallet credit
            logger.warning(f"Order {order.id} can't apply {plan.name} ({blocker}); crediting the wallet instead")
        result = billing.record_payment(db, order.client_id, order.amount_inr, reference, order.created_by, commit=False)
    order.status = "PAID"
    order.razorpay_payment_id = razorpay_payment_id
    order.invoice_id = result["invoice_id"]
    db.commit()
    logger.info(f"Fulfilled payment order {order.id} ({order.purpose}) for {order.client_id}")
    return order


def simulate_payment(db: Session, order: PaymentOrder) -> PaymentOrder:
    """Testing mode: marks a simulated order paid, exactly as a verified Razorpay payment would."""
    if not is_simulated() or not (order.razorpay_order_id or "").startswith(SIMULATED_PREFIX):
        raise ValidationException("Simulated payments are turned off.")
    return fulfil_order(db, order, f"{SIMULATED_PREFIX}pay_{order.id}")


def handle_webhook(db: Session, event: Dict[str, Any]) -> Optional[PaymentOrder]:
    """Fulfils the order behind a payment.captured / order.paid event."""
    if event.get("event") not in ("payment.captured", "order.paid"):
        return None
    payment = (event.get("payload", {}).get("payment") or {}).get("entity") or {}
    razorpay_order_id = payment.get("order_id")
    if not razorpay_order_id:
        return None
    order = db.query(PaymentOrder).filter(PaymentOrder.razorpay_order_id == razorpay_order_id).first()
    if not order:
        logger.warning(f"Razorpay webhook for unknown order {razorpay_order_id}")
        return None
    if int(payment.get("amount") or 0) != int(round(order.amount_inr * 100)):
        logger.error(f"Razorpay amount mismatch on order {order.id}: {payment.get('amount')}")
        return None
    return fulfil_order(db, order, payment.get("id"))
