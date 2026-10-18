"""
Checks Choranta's phone-line cost estimates against what Exotel actually charged.

After a call ends, Exotel's call details (v1 Calls/<CallSid>.json) report its Price. The billing sweep
fetches it for recent calls and stores it on the call; the admin report compares it with the telephony
part of Choranta's estimate, so a wrong TELEPHONY_RATE_PER_MINUTE_INR shows up after a few calls.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.call import Call
from app.services import subscriptions
from app.services.billing import billed_minutes
from app.services.call_costing import estimate_call_cost

logger = logging.getLogger("choranta.services.carrier_costs")

# Exotel fills in a call's price shortly after it ends; check calls this long after, a few times, then give up
PRICE_DELAY = timedelta(minutes=2)
PRICE_LOOKBACK = timedelta(days=7)
MAX_PRICE_CHECKS = 5
PRICES_PER_RUN = 50


def fetch_exotel_price(provider_call_id: str) -> Optional[Dict[str, float]]:
    """Exotel's charge for one call as {"price", "duration"}, or None while Exotel hasn't priced it yet."""
    sid = settings.EXOTEL_ACCOUNT_SID
    if not (sid and settings.EXOTEL_API_KEY and settings.EXOTEL_API_TOKEN):
        raise RuntimeError("Exotel isn't configured.")
    url = f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{sid}/Calls/{provider_call_id}.json"
    response = httpx.get(url, auth=(settings.EXOTEL_API_KEY, settings.EXOTEL_API_TOKEN), timeout=15.0)
    if response.status_code >= 400:
        raise RuntimeError(f"Exotel call details failed ({response.status_code}): {response.text[:200]}")
    call = (response.json() or {}).get("Call") or {}
    if call.get("Price") in (None, ""):
        return None
    return {"price": float(call["Price"]), "duration": float(call.get("Duration") or 0)}


def real_price(price: float) -> float:
    """What a carrier price really costs Choranta: plus GST while it can't be claimed back."""
    if settings.EXOTEL_PRICE_INCLUDES_GST or settings.GST_REGISTERED:
        return price
    return price * (1 + settings.GST_RATE_PERCENT / 100.0)


def record_carrier_prices(
    db: Session, now: Optional[datetime] = None,
    fetch: Callable[[str], Optional[Dict[str, float]]] = fetch_exotel_price,
) -> int:
    """Stores Exotel's price on recently ended calls that don't have it yet. Returns how many it priced."""
    if settings.ENVIRONMENT == "test" and fetch is fetch_exotel_price:
        return 0
    now = now or subscriptions.utcnow()
    calls = (
        db.query(Call)
        .filter(
            Call.provider == "exotel", Call.status == "COMPLETED", Call.duration_seconds > 0,
            Call.ended_at <= now - PRICE_DELAY, Call.ended_at >= now - PRICE_LOOKBACK,
        )
        .order_by(Call.ended_at)
        .all()
    )
    priced = 0
    for call in calls:
        meta = call.metadata_ or {}
        if "carrier_price_inr" in meta or int(meta.get("carrier_price_checks") or 0) >= MAX_PRICE_CHECKS:
            continue
        if meta.get("mock") or (call.provider_call_id or "").startswith("pending"):
            continue
        if priced >= PRICES_PER_RUN:
            break
        try:
            result = fetch(call.provider_call_id)
        except Exception as exc:
            result = None
            logger.warning(f"Couldn't fetch Exotel's price for call {call.id}: {exc}")
        meta = dict(meta)
        if result is None:
            meta["carrier_price_checks"] = int(meta.get("carrier_price_checks") or 0) + 1
        else:
            meta["carrier_price_inr"] = result["price"]
            meta["carrier_duration_s"] = result["duration"]
            priced += 1
        call.metadata_ = meta
        db.commit()
    return priced


def carrier_cost_report(db: Session, days: int = 30, limit: int = 20) -> Dict[str, Any]:
    """
    Choranta's phone-line estimate vs what Exotel charged, over calls Exotel has priced. Flags the rate
    when Exotel cost more than the estimate by over CARRIER_COST_ALERT_PERCENT.
    """
    since = subscriptions.utcnow() - timedelta(days=days)
    calls = (
        db.query(Call)
        .filter(Call.provider == "exotel", Call.status == "COMPLETED", Call.ended_at >= since)
        .order_by(Call.ended_at.desc())
        .all()
    )
    rows: List[Dict[str, Any]] = []
    estimated_total = actual_total = minutes_total = 0.0
    for call in calls:
        meta = call.metadata_ or {}
        if "carrier_price_inr" not in meta:
            continue
        duration = float(meta.get("carrier_duration_s") or call.duration_seconds or 0)
        estimated = estimate_call_cost(duration, {})["breakdown"]["telephony"]
        actual = real_price(float(meta["carrier_price_inr"]))
        estimated_total += estimated
        actual_total += actual
        minutes_total += billed_minutes(duration)
        rows.append({
            "call_id": call.id,
            "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            "direction": call.direction,
            "is_test": bool(meta.get("is_test")),
            "duration_seconds": round(duration, 1),
            "estimated_inr": round(estimated, 4),
            "exotel_price_inr": float(meta["carrier_price_inr"]),
            "actual_inr": round(actual, 4),
            "gap_inr": round(actual - estimated, 4),
        })
    gap_percent = round((actual_total - estimated_total) / estimated_total * 100, 1) if estimated_total else None
    too_low = gap_percent is not None and gap_percent > settings.CARRIER_COST_ALERT_PERCENT
    # The per-minute rate that would have matched Exotel exactly over these calls
    matching_rate = round(actual_total / minutes_total, 4) if minutes_total else None
    rows.sort(key=lambda r: r["gap_inr"], reverse=True)
    return {
        "days": days,
        "calls_priced": len(rows),
        "estimated_total_inr": round(estimated_total, 2),
        "actual_total_inr": round(actual_total, 2),
        "gap_percent": gap_percent,
        "alert_percent": settings.CARRIER_COST_ALERT_PERCENT,
        "rate_too_low": too_low,
        "current_rate_per_minute_inr": settings.TELEPHONY_RATE_PER_MINUTE_INR,
        "matching_rate_per_minute_inr": matching_rate,
        "gst_added": not (settings.EXOTEL_PRICE_INCLUDES_GST or settings.GST_REGISTERED),
        "calls": rows[:limit],
    }
