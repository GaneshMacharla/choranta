"""
Stores the capacity counters by day and turns them into the Finance page's capacity card: current limits, what's holding
calls back, and whether the data supports buying more lines or a bigger Sarvam plan.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.call_capacity import CapacityDaily
from app.services import billing, call_capacity, subscriptions

logger = logging.getLogger("choranta.services.capacity_stats")

COUNTERS = (
    "inbound_refused_busy", "callbacks_queued", "callbacks_connected", "callbacks_expired", "campaign_wait_seconds",
    "vobiz_limit_rejections", "sarvam_llm_requests", "sarvam_llm_limited", "sarvam_429", "sarvam_503",
    "sarvam_ws_rejected", "gemini_fallbacks", "live_call_minutes",
)
SARVAM_REJECTIONS = ("sarvam_llm_limited", "sarvam_429", "sarvam_503", "sarvam_ws_rejected")
REPORT_DAYS = 30
# Too few call minutes make requests-per-minute meaningless; too few days don't show lines are spare
MIN_MINUTES_TO_MEASURE = 10.0
MIN_DAYS_FOR_SPARE_LINES = 7
INDIA = ZoneInfo("Asia/Kolkata")


def _today(now: Optional[datetime] = None) -> date:
    now = now or subscriptions.utcnow()
    return now.replace(tzinfo=timezone.utc).astimezone(INDIA).date()


def flush(db: Session, now: Optional[datetime] = None) -> None:
    """Adds what's been counted in memory to today's row. If it can't be saved, the counts stay for the next try."""
    counters, peak = call_capacity.take_counters()
    if not counters and not peak:
        return
    try:
        day = _today(now)
        row = db.get(CapacityDaily, day)
        if row is None:
            row = CapacityDaily(day=day, peak_live_calls=0, **{name: 0 for name in COUNTERS})
            db.add(row)
        row.peak_live_calls = max(row.peak_live_calls or 0, peak)
        for name, amount in counters.items():
            if name in COUNTERS:
                setattr(row, name, (getattr(row, name) or 0) + amount)
        db.commit()
    except Exception:
        db.rollback()
        call_capacity.restore_counters(counters, peak)
        raise


def run_capacity_stats_job(session_factory) -> None:
    db = session_factory()
    try:
        flush(db)
    finally:
        db.close()


def _totals(rows: List[CapacityDaily]) -> Dict[str, float]:
    totals = {name: float(sum(getattr(row, name) or 0 for row in rows)) for name in COUNTERS}
    totals["peak_live_calls"] = max((row.peak_live_calls or 0 for row in rows), default=0)
    totals["sarvam_rejections"] = sum(totals[name] for name in SARVAM_REJECTIONS)
    return totals


def _bottleneck() -> str:
    speech = call_capacity.speech_capacity()
    usable = call_capacity.line_capacity()
    if settings.VOBIZ_MAX_CONCURRENT_CALLS > 0 and settings.VOBIZ_MAX_CONCURRENT_CALLS == usable:
        return "vobiz"
    return "sarvam" if speech == usable else "platform"


def _hints(totals: Dict[str, float], days_of_data: int) -> List[Dict[str, str]]:
    hints: List[Dict[str, str]] = []
    days = f"the last {REPORT_DAYS} days"
    refused = int(totals["inbound_refused_busy"])
    if refused:
        hints.append({"level": "warning", "text": f"{refused} inbound call{'s were' if refused != 1 else ' was'} refused "
                                                  f"because every line was busy in {days}: you need more lines."})
    wait_minutes = totals["campaign_wait_seconds"] / 60.0
    if wait_minutes >= 60:
        hints.append({"level": "info", "text": f"Campaigns waited about {wait_minutes / 60.0:.0f} campaign-hours for a free "
                                               f"line in {days}: more lines would finish them faster."})
    rejections = int(totals["sarvam_rejections"])
    if rejections:
        hints.append({"level": "warning", "text": f"Sarvam's limits were hit {rejections} time{'s' if rejections != 1 else ''} "
                                                  f"in {days}: upgrade the Sarvam plan, or lower the calls allowed."})
    lines = settings.VOBIZ_MAX_CONCURRENT_CALLS
    peak = int(totals["peak_live_calls"])
    # A Vobiz account starts with 3 lines, so more than that means some were bought
    if lines > 3 and days_of_data >= MIN_DAYS_FOR_SPARE_LINES and peak < lines and not refused:
        hints.append({"level": "info", "text": f"Peak was {peak} of {lines} lines over the last {days_of_data} days: "
                                               "consider dropping purchased lines at renewal."})
    return hints


def capacity_report(db: Session, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything the capacity card shows. Saves pending counts first, so it's up to the minute."""
    flush(db, now)
    today = _today(now)
    rows = db.query(CapacityDaily).filter(CapacityDaily.day > today - timedelta(days=REPORT_DAYS)).all()
    totals = _totals(rows)
    today_rows = [row for row in rows if row.day == today]
    minutes = totals["live_call_minutes"]
    measured = totals["sarvam_llm_requests"] / minutes if minutes >= MIN_MINUTES_TO_MEASURE else None
    return {
        "limits": {
            "vobiz_lines": settings.VOBIZ_MAX_CONCURRENT_CALLS,
            "platform_cap": settings.MAX_CONCURRENT_CALLS_PLATFORM,
            "sarvam_calls": call_capacity.speech_capacity(),
            "usable_calls": call_capacity.line_capacity(),
            "reserved_for_inbound": call_capacity.reserved_lines(),
            "outbound_lines": call_capacity.outbound_line_capacity(),
        },
        "bottleneck": _bottleneck(),
        "live": {
            "calls": billing.platform_live_call_count(db),
            "free_inbound": billing.platform_headroom(db),
            "free_outbound": billing.outbound_headroom(db),
            "outbound_paused_s": round(call_capacity.outbound_pause_left()),
        },
        "llm_requests_per_call_minute": {
            "assumed": settings.SARVAM_LLM_REQUESTS_PER_CALL,
            "measured": round(measured, 1) if measured is not None else None,
        },
        "today": _totals(today_rows),
        "last_30_days": totals,
        "hints": _hints(totals, len(rows)),
    }
