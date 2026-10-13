"""
Outbound insights for the client dashboard: how campaigns and instant website-lead calls went over
a period, across all of a client's campaigns. Built from campaign recipients and their attempts;
the interest of each answered call comes from post-call extraction (see call_outputs).
"""
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.campaign import Campaign, CampaignAttempt, CampaignRecipient
from app.services.campaigns import _zone, count_outputs

PERIODS = (7, 30, 90)
HOT_INTERESTS = ("interested", "callback")
HOT_LEADS_LIMIT = 25
# A website lead first dialled later than this waited for calling hours to open
QUEUED_AFTER = timedelta(minutes=15)
CALLING_HOURS = range(9, 21)


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 3) if whole else None


def _interest(recipient: CampaignRecipient) -> Optional[str]:
    return (recipient.result or {}).get("interest") if recipient.status == "COMPLETED" else None


def insights(db: Session, client_id: str, days: int = 30, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(days=days)
    campaigns = {c.id: c for c in db.query(Campaign).filter(Campaign.client_id == client_id).all()}
    out: Dict[str, Any] = {"days": days, "has_outbound": bool(campaigns)}

    recipients = db.query(CampaignRecipient).filter(
        CampaignRecipient.client_id == client_id, CampaignRecipient.last_dialed_at >= since
    ).all() if campaigns else []
    attempts = db.query(CampaignAttempt).filter(
        CampaignAttempt.campaign_id.in_(list(campaigns)), CampaignAttempt.ended_at >= since
    ).all() if campaigns else []

    # ------------------------------------------------ funnel
    answered = [r for r in recipients if r.status == "COMPLETED" and r.outcome == "answered"]
    interests = [_interest(r) for r in answered]
    talk = [a.duration_seconds or 0.0 for a in attempts if a.status == "COMPLETED"]
    out["funnel"] = {
        "called": len(recipients),
        "answered": len(answered),
        "interested": sum(1 for i in interests if i in HOT_INTERESTS),
        "callbacks": interests.count("callback"),
        "not_interested": interests.count("not_interested"),
        "do_not_call": interests.count("do_not_call"),
        "answer_rate": _rate(len(answered), sum(1 for r in recipients if r.status in ("COMPLETED", "FAILED"))),
        "avg_talk_seconds": round(sum(talk) / len(talk)) if talk else None,
        "minutes": round(sum(a.duration_seconds or 0.0 for a in attempts) / 60.0, 1),
    }

    # ------------------------------------------------ hot leads
    hot = [r for r in answered if _interest(r) in HOT_INTERESTS and not (r.result or {}).get("followed_up_at")]
    hot.sort(key=lambda r: r.last_dialed_at, reverse=True)
    out["hot_leads"] = [
        {
            "recipient_id": r.id,
            "name": r.name,
            "phone": r.phone,
            "campaign_id": r.campaign_id,
            "campaign_name": campaigns[r.campaign_id].name,
            "campaign_kind": campaigns[r.campaign_id].kind,
            "interest": _interest(r),
            "summary": (r.result or {}).get("summary"),
            "callback_time": (r.result or {}).get("callback_time"),
            "call_id": r.last_call_id,
            "called_at": r.last_dialed_at,
        }
        for r in hot[:HOT_LEADS_LIMIT]
    ]
    out["hot_leads_total"] = len(hot)

    # ------------------------------------------------ instant website leads
    trigger_ids = [cid for cid, c in campaigns.items() if c.kind == "TRIGGER"]
    out["instant"] = _instant(db, trigger_ids, since) if trigger_ids else None

    # ------------------------------------------------ collected answers and best hours
    out["top_answers"] = count_outputs(r.result for r in answered)
    by_hour = {h: {"attempts": 0, "answered": 0} for h in CALLING_HOURS}
    for a in attempts:
        started = a.started_at or a.ended_at
        hour = started.replace(tzinfo=timezone.utc).astimezone(_zone(campaigns[a.campaign_id].timezone)).hour
        if hour in by_hour:
            by_hour[hour]["attempts"] += 1
            by_hour[hour]["answered"] += a.outcome == "answered"
    out["best_hours"] = [
        {"hour": h, **v, "answer_rate": _rate(v["answered"], v["attempts"])} for h, v in by_hour.items()
    ]

    # ------------------------------------------------ per campaign
    answered_ids = {r.id for r in answered}
    rows: Dict[str, Dict[str, Any]] = {}
    for r in recipients:
        row = rows.setdefault(r.campaign_id, {"called": 0, "finished": 0, "answered": 0, "interested": 0, "seconds": 0.0})
        row["called"] += 1
        row["finished"] += r.status in ("COMPLETED", "FAILED")
        row["answered"] += r.id in answered_ids
        row["interested"] += _interest(r) in HOT_INTERESTS
    for a in attempts:
        if a.campaign_id in rows:
            rows[a.campaign_id]["seconds"] += a.duration_seconds or 0.0
    out["campaigns"] = sorted(
        (
            {
                "id": cid,
                "name": campaigns[cid].name,
                "kind": campaigns[cid].kind,
                "status": campaigns[cid].status,
                "called": row["called"],
                "answered": row["answered"],
                "answer_rate": _rate(row["answered"], row["finished"]),
                "interested": row["interested"],
                "minutes": round(row["seconds"] / 60.0, 1),
            }
            for cid, row in rows.items()
        ),
        key=lambda row: -row["called"],
    )
    return out


def _instant(db: Session, trigger_ids: List[str], since: datetime) -> Dict[str, Any]:
    """Website leads received in the period: how fast they were called and how many were reached."""
    leads = db.query(CampaignRecipient).filter(
        CampaignRecipient.campaign_id.in_(trigger_ids), CampaignRecipient.created_at >= since
    ).all()
    first_dial: Dict[str, datetime] = {}
    if leads:
        for recipient_id, started in db.query(CampaignAttempt.recipient_id, CampaignAttempt.started_at).filter(
            CampaignAttempt.recipient_id.in_([r.id for r in leads]), CampaignAttempt.attempt_no == 1
        ):
            if started:
                first_dial[recipient_id] = started
    delays, queued = [], 0
    for r in leads:
        # A first dial still on the line has no attempt yet: its claim time is the dial time
        dialled = first_dial.get(r.id) or (r.last_dialed_at if r.attempts == 1 else None)
        if dialled is None:
            continue
        delay = max(0.0, (dialled - r.created_at).total_seconds())
        if delay > QUEUED_AFTER.total_seconds():
            queued += 1
        else:
            delays.append(delay)
    reached = [r for r in leads if r.status == "COMPLETED" and r.outcome == "answered"]
    return {
        "leads": len(leads),
        "reached": len(reached),
        "interested": sum(1 for r in reached if _interest(r) in HOT_INTERESTS),
        "median_seconds_to_call": round(median(delays), 1) if delays else None,
        "called_within_60s_pct": _rate(sum(1 for d in delays if d <= 60), len(delays)),
        "queued_for_hours": queued,
    }


def mark_followed_up(db: Session, client_id: str, recipient_id: str, now: Optional[datetime] = None) -> bool:
    """Takes a hot lead off the follow-up list. False when it isn't this client's recipient."""
    recipient = db.get(CampaignRecipient, recipient_id)
    if not recipient or recipient.client_id != client_id:
        return False
    recipient.result = {**(recipient.result or {}),
                        "followed_up_at": (now or datetime.now(timezone.utc)).isoformat()}
    flag_modified(recipient, "result")
    db.commit()
    return True
