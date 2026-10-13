"""
Monthly plans.

A plan's fee (pre-GST) buys one month that includes a number of call minutes. Minutes beyond that are
charged from the prepaid wallet at the plan's overage rate. Clients pay each month; when a period ends
unpaid the subscription is PAST_DUE and calls keep working for SUBSCRIPTION_GRACE_DAYS. Status is worked
out whenever a subscription is read, so no scheduler is needed. Clients without a subscription stay on
pay-as-you-go wallet pricing.
"""
import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.subscription import ClientSubscription, Plan

logger = logging.getLogger("choranta.services.subscriptions")


def utcnow() -> datetime:
    """Naive UTC, matching how DateTime columns are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def add_month(dt: datetime) -> datetime:
    """Same day next month, clamped to the month's last day (31 Jan -> 28/29 Feb)."""
    year, month = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------- plans

def validate_plan_fields(name: str, monthly_price_inr: float, included_minutes: int,
                         overage_per_minute_inr: float, max_concurrent_calls: Optional[int]) -> None:
    if not (name or "").strip():
        raise ValidationException("Give the plan a name.")
    if monthly_price_inr <= 0:
        raise ValidationException("Monthly price must be greater than zero.")
    if included_minutes < 0 or overage_per_minute_inr < 0:
        raise ValidationException("Included minutes and overage rate can't be negative.")
    if max_concurrent_calls is not None and max_concurrent_calls < 1:
        raise ValidationException("Concurrent calls must be at least 1, or empty for no limit.")


# ---------------------------------------------------------------- subscriptions

def get_subscription(db: Session, client_id: str, lock: bool = False) -> Optional[ClientSubscription]:
    query = db.query(ClientSubscription).filter(ClientSubscription.client_id == client_id)
    if lock:
        query = query.with_for_update()
    sub = query.first()
    if sub:
        refresh_status(sub)
    return sub


def refresh_status(sub: ClientSubscription, now: Optional[datetime] = None) -> ClientSubscription:
    """
    Rolls an ended period into the already-paid next one, or marks it PAST_DUE (CANCELLED when it was
    set to cancel at period end).
    """
    now = now or utcnow()
    if sub.status not in ("ACTIVE", "PAST_DUE") or now < _naive(sub.current_period_end):
        return sub
    if sub.renewed_ahead:
        sub.current_period_start = _naive(sub.current_period_end)
        sub.current_period_end = add_month(sub.current_period_start)
        sub.minutes_used = 0.0
        sub.renewed_ahead = False
        sub.status = "ACTIVE"
        return refresh_status(sub, now)
    sub.status = "CANCELLED" if sub.cancel_at_period_end else "PAST_DUE"
    return sub


def in_grace(sub: ClientSubscription, now: Optional[datetime] = None) -> bool:
    now = now or utcnow()
    return sub.status == "PAST_DUE" and now < _naive(sub.current_period_end) + timedelta(days=settings.SUBSCRIPTION_GRACE_DAYS)


def is_usable(sub: Optional[ClientSubscription]) -> bool:
    """Whether calls run under the plan (active, or past due but still within the grace period)."""
    return bool(sub) and (sub.status == "ACTIVE" or in_grace(sub))


def remaining_minutes(sub: ClientSubscription, plan: Plan) -> float:
    return max(0.0, float(plan.included_minutes) - float(sub.minutes_used or 0.0))


def renewal_blocker(sub: Optional[ClientSubscription], plan: Plan) -> Optional[str]:
    """Why this plan can't be paid for right now, or None."""
    if sub and sub.renewed_ahead:
        return "Your next period is already paid for."
    return None


def activate_period(db: Session, client_id: str, plan: Plan, now: Optional[datetime] = None) -> ClientSubscription:
    """
    Applies a paid period. Renewing the same plan while it is active pays the next period, which starts
    when the current one ends. Renewing within the grace period continues from the old period's end.
    A plan change or a lapsed renewal starts now. Minutes reset with each new period (no proration).
    """
    now = now or utcnow()
    sub = get_subscription(db, client_id, lock=True)
    same_plan = sub is not None and sub.plan_id == plan.id
    if same_plan and sub.status == "ACTIVE" and not sub.cancel_at_period_end:
        sub.renewed_ahead = True
        db.flush()
        logger.info(f"Renewed {plan.name} ahead for {client_id}; next period starts {sub.current_period_end:%Y-%m-%d}")
        return sub
    if same_plan and in_grace(sub, now):
        start = _naive(sub.current_period_end)
    else:
        start = now
    if sub is None:
        sub = ClientSubscription(client_id=client_id)
        db.add(sub)
    sub.plan_id = plan.id
    sub.status = "ACTIVE"
    sub.current_period_start = start
    sub.current_period_end = add_month(start)
    sub.minutes_used = 0.0
    sub.cancel_at_period_end = False
    sub.renewed_ahead = False
    refresh_status(sub, now)  # a grace renewal that is already a month old rolls to past due again
    db.flush()
    logger.info(f"Activated {plan.name} for {client_id}: {start:%Y-%m-%d} to {sub.current_period_end:%Y-%m-%d}")
    return sub


def period_label(sub: ClientSubscription) -> str:
    return f"{_naive(sub.current_period_start):%d %b %Y} - {_naive(sub.current_period_end):%d %b %Y}"


def subscription_out(db: Session, client_id: str) -> Optional[Dict[str, Any]]:
    sub = get_subscription(db, client_id)
    if not sub:
        return None
    plan = db.get(Plan, sub.plan_id)
    now = utcnow()
    end = _naive(sub.current_period_end)
    grace_ends = end + timedelta(days=settings.SUBSCRIPTION_GRACE_DAYS)
    return {
        "plan": plan_out(plan) if plan else None,
        "status": sub.status,
        "usable": is_usable(sub),
        "in_grace": in_grace(sub),
        "grace_ends_at": grace_ends if sub.status == "PAST_DUE" else None,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "days_left": max(0, (end - now).days) if now < end else 0,
        "minutes_used": round(float(sub.minutes_used or 0.0), 2),
        "included_minutes": plan.included_minutes if plan else 0,
        "minutes_remaining": round(remaining_minutes(sub, plan), 2) if plan else 0,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "renewed_ahead": sub.renewed_ahead,
    }


def plan_out(plan: Plan) -> Dict[str, Any]:
    gst = settings.GST_RATE_PERCENT / 100.0
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "monthly_price_inr": plan.monthly_price_inr,
        "monthly_price_with_gst_inr": round(plan.monthly_price_inr * (1 + gst), 2),
        "included_minutes": plan.included_minutes,
        "overage_per_minute_inr": plan.overage_per_minute_inr,
        "max_concurrent_calls": plan.max_concurrent_calls,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
    }
