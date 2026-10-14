"""
Every AI employee knows today's date in its client's timezone, so "tomorrow", "this Saturday" and whether a batch
or offer date has passed come out right.
"""
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

# Clients are created with timezone "UTC" unless someone sets it; Choranta's callers are in India, so UTC means unset
DEFAULT_TIMEZONE = "Asia/Kolkata"


def client_zone(db: Session, client_id: Optional[str]) -> ZoneInfo:
    from app.models.client import Client

    client = db.get(Client, client_id) if client_id else None
    name = (client.timezone or "").strip() if client else ""
    if not name or name.upper() == "UTC":
        name = DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def client_today(db: Session, client_id: Optional[str], now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(client_zone(db, client_id)).date()


def spoken_date(day: date) -> str:
    """e.g. "Thursday 15 October 2026": weekday and year included, so nothing is left to guess."""
    return f"{day:%A} {day.day} {day:%B %Y}"


def today_line(today: date) -> str:
    return (
        f"\n\nToday's date: {spoken_date(today)}. Use it for \"today\", \"tomorrow\" and \"this weekend\", "
        "and to tell whether a date has already passed."
    )
