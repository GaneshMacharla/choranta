from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    return datetime.now(timezone.utc)


class Plan(Base):
    """Monthly plan: a fixed fee (pre-GST) that includes minutes, with a per-minute overage rate."""
    __tablename__ = "plans"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("plan_"))
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    monthly_price_inr = Column(Float, nullable=False)
    included_minutes = Column(Integer, nullable=False)        # legacy: derived from monthly_credits
    overage_per_minute_inr = Column(Float, nullable=False)    # legacy: calls now cost the platform credit rate
    monthly_credits = Column(Float, nullable=True)            # credits granted each period (1 credit = Rs 1)
    max_concurrent_calls = Column(Integer, nullable=True)  # None = unlimited
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class ClientSubscription(Base):
    """A client's current plan and billing period (one row per client)."""
    __tablename__ = "client_subscriptions"

    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    plan_id = Column(String(64), ForeignKey("plans.id"), nullable=False)
    status = Column(String(16), nullable=False, default="ACTIVE")  # ACTIVE / PAST_DUE / CANCELLED
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    minutes_used = Column(Float, nullable=False, default=0.0)
    credits_used = Column(Float, nullable=False, default=0.0)  # plan credits used this period
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    renewed_ahead = Column(Boolean, nullable=False, default=False)  # next period already paid
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class CallUsage(Base):
    """How one billed call was paid for: plan credits and/or bought (wallet) credits. One row per call."""
    __tablename__ = "call_usage"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("use_"))
    call_id = Column(String(64), nullable=False, unique=True, index=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = Column(String(64), nullable=True)  # None = pay-as-you-go
    billed_minutes = Column(Float, nullable=False, default=0.0)
    included_minutes = Column(Float, nullable=False, default=0.0)
    overage_minutes = Column(Float, nullable=False, default=0.0)
    overage_charge_inr = Column(Float, nullable=False, default=0.0)  # = wallet_credits (1 credit = Rs 1)
    plan_credits = Column(Float, nullable=False, default=0.0)
    wallet_credits = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)


class PaymentOrder(Base):
    """A Razorpay order a client is paying: a plan period or a wallet top-up."""
    __tablename__ = "payment_orders"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("pord_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(16), nullable=False)  # SUBSCRIPTION / WALLET_TOPUP
    plan_id = Column(String(64), nullable=True)
    amount_inr = Column(Float, nullable=False)  # GST included
    razorpay_order_id = Column(String(64), nullable=True, unique=True, index=True)
    razorpay_payment_id = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="CREATED")  # CREATED / PAID / FAILED
    invoice_id = Column(String(64), nullable=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class NumberPricing(Base):
    """Monthly rent (pre-GST) Choranta charges for a phone number of each type."""
    __tablename__ = "number_pricing"

    number_type = Column(String(16), primary_key=True)  # Landline / Mobile / TollFree
    monthly_rent_inr = Column(Float, nullable=False)
    setup_fee_inr = Column(Float, nullable=False, default=0.0)  # one-time, charged with the first month
    is_available = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class NumberRental(Base):
    """A phone number a client bought from Choranta, rented monthly from the wallet. Numbers without one are free."""
    __tablename__ = "number_rentals"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("rent_"))
    phone_number_id = Column(String(64), ForeignKey("phone_numbers.id", ondelete="CASCADE"), nullable=False, unique=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    number_type = Column(String(16), nullable=False)
    monthly_rent_inr = Column(Float, nullable=False)  # fixed when bought
    status = Column(String(16), nullable=False, default="ACTIVE", index=True)  # ACTIVE / PAST_DUE / RELEASED
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False, index=True)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    released_at = Column(DateTime, nullable=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
