import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.pricing_settings import PricingSettings

PRICING_ROW_ID = "default"
MAX_PROFIT_PERCENT = 1000.0
# Plan cards estimate minutes from what recent calls actually cost per minute (recomputed at most this often)
ESTIMATE_WINDOW_DAYS = 30
ESTIMATE_CACHE_S = 600


@dataclass(frozen=True)
class PricingSnapshot:
    profit_percent: float
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


def get_pricing(db: Session) -> PricingSnapshot:
    """Current admin pricing, or the configured defaults if it has never been set."""
    row = db.get(PricingSettings, PRICING_ROW_ID)
    if row is None:
        return PricingSnapshot(profit_percent=settings.DEFAULT_PROFIT_PERCENT)
    return PricingSnapshot(
        profit_percent=row.profit_percent,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


_estimate: Dict[str, Any] = {"value": None, "at": 0.0}
_estimate_lock = threading.Lock()


def recent_charge_per_minute(db: Session, pricing: Optional[PricingSnapshot] = None) -> Dict[str, Any]:
    """Average client charge and cost per conversation minute over recent completed calls."""
    from app.models.call import Call
    from app.models.runtime_session import RuntimeSession
    from app.services.call_costing import estimate_call_cost

    pricing = pricing or get_pricing(db)
    since = datetime.now(timezone.utc) - timedelta(days=ESTIMATE_WINDOW_DAYS)
    calls = db.query(Call).filter(Call.status == "COMPLETED", Call.duration_seconds > 0, Call.created_at >= since).all()
    sessions = {
        s.id: s for s in db.query(RuntimeSession).filter(
            RuntimeSession.id.in_([c.runtime_session_id for c in calls if c.runtime_session_id])
        ).all()
    } if calls else {}
    seconds = cost = charge = 0.0
    for call in calls:
        session_obj = sessions.get(call.runtime_session_id)
        usage = session_obj.usage_json if session_obj and isinstance(session_obj.usage_json, dict) else {}
        result = estimate_call_cost(call.duration_seconds, usage, pricing)
        seconds += call.duration_seconds
        cost += result["total"]
        charge += result["charge_total"]
    minutes = seconds / 60.0
    return {
        "window_days": ESTIMATE_WINDOW_DAYS,
        "calls": len(calls),
        "minutes": round(minutes, 2),
        "avg_cost_per_minute": round(cost / minutes, 4) if minutes else None,
        "avg_charge_per_minute": round(charge / minutes, 4) if minutes else None,
        "avg_profit_per_minute": round((charge - cost) / minutes, 4) if minutes else None,
    }


def estimated_credits_per_minute(db: Session) -> float:
    """
    Typical credits one call minute costs, for showing "about N minutes" on plans. Calls are charged
    their real cost + profit, so this is the recent average (a default until there are calls).
    """
    now = time.monotonic()
    with _estimate_lock:
        if _estimate["value"] is not None and now - _estimate["at"] < ESTIMATE_CACHE_S:
            return _estimate["value"]
    average = recent_charge_per_minute(db)["avg_charge_per_minute"]
    value = round(average, 2) if average else settings.DEFAULT_CREDITS_PER_MINUTE
    with _estimate_lock:
        _estimate.update(value=value, at=now)
    return value


# Suggested credit top-ups by business size, so clients know how much to buy (1 credit = Rs 1, pre-GST)
CREDIT_PACKS = [
    {"key": "starter", "name": "Starter", "credits": 1000, "suits": "Trying it out, or a few calls a day"},
    {"key": "growth", "name": "Growth", "credits": 3000, "suits": "About 7 calls a day for a month", "recommended": True},
    {"key": "business", "name": "Business", "credits": 7500, "suits": "About 18 calls a day for a month"},
    {"key": "scale", "name": "Scale", "credits": 20000, "suits": "Campaigns, 45+ calls a day"},
    {"key": "enterprise", "name": "Enterprise", "credits": 50000, "suits": "Large teams and call centres, 120+ calls a day"},
]
AVG_CALL_MINUTES = 2  # typical call length for the "about N calls" estimate


def credit_packs_out(db: Session) -> list:
    """The credit packs with about how many minutes and calls each buys at the current per-minute rate."""
    rate = estimated_credits_per_minute(db)
    gst = settings.EFFECTIVE_GST_RATE_PERCENT / 100.0
    packs = []
    for pack in CREDIT_PACKS:
        minutes = int(pack["credits"] // rate) if rate > 0 else 0
        packs.append({
            **pack,
            "recommended": pack.get("recommended", False),
            "price_with_gst_inr": round(pack["credits"] * (1 + gst), 2),
            "approx_minutes": minutes,
            "approx_calls": minutes // AVG_CALL_MINUTES,
        })
    return packs


_budget_rate: Dict[str, Any] = {"value": None, "at": 0.0}


def budget_credits_per_minute(db: Session) -> float:
    """
    Credits per minute used to size call budgets. Errs high: the recent average counts only once
    enough calls back it, and never goes below the configured default.
    """
    now = time.monotonic()
    with _estimate_lock:
        if _budget_rate["value"] is not None and now - _budget_rate["at"] < ESTIMATE_CACHE_S:
            return _budget_rate["value"]
    recent = recent_charge_per_minute(db)
    value = settings.DEFAULT_CREDITS_PER_MINUTE
    if recent["calls"] >= settings.BUDGET_MIN_CALLS_FOR_AVERAGE and recent["avg_charge_per_minute"]:
        value = max(value, round(recent["avg_charge_per_minute"], 2))
    with _estimate_lock:
        _budget_rate.update(value=value, at=now)
    return value


def clear_estimate_cache() -> None:
    with _estimate_lock:
        _estimate.update(value=None, at=0.0)
        _budget_rate.update(value=None, at=0.0)


def update_pricing(db: Session, profit_percent: float, user_id: Optional[str]) -> PricingSnapshot:
    if not 0 <= profit_percent <= MAX_PROFIT_PERCENT:
        raise ValidationException(f"Profit percent must be between 0 and {MAX_PROFIT_PERCENT:.0f}.")

    row = db.get(PricingSettings, PRICING_ROW_ID)
    if row is None:
        row = PricingSettings(id=PRICING_ROW_ID)
        db.add(row)
    row.profit_percent = float(profit_percent)
    row.infra_cost_per_minute_inr = 0.0  # infra cost no longer used; column kept for existing databases
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    clear_estimate_cache()
    return get_pricing(db)
