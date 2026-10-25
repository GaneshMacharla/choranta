"""
Outbound insights for the client dashboard: how campaigns and instant website-lead calls went over
a period, across all of a client's campaigns. Built from campaign recipients and their attempts;
the interest of each answered call comes from post-call extraction (see call_outputs).

Hot leads are the qualified callers (services/lead_qualification.py) not yet followed up: campaign recipients
and inbound callers alike.
"""
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.call import Call
from app.models.campaign import Campaign, CampaignAttempt, CampaignRecipient
from app.services.campaigns import _zone, count_outputs
from app.services.lead_qualification import is_qualified

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


def _naive(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.min
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _reason(result: Dict[str, Any]) -> Optional[str]:
    qualification = result.get("qualification") if isinstance(result.get("qualification"), dict) else {}
    return qualification.get("reason")


def _inbound_hot(db: Session, client_id: str, since: datetime) -> List[Dict[str, Any]]:
    """Qualified inbound callers in the period, not yet followed up."""
    from app.services.whatsapp_followups import _lead_for, lead_phone
    calls = db.query(Call).filter(
        Call.client_id == client_id, Call.direction == "INBOUND", Call.status == "COMPLETED", Call.created_at >= since,
    ).order_by(Call.created_at.desc()).limit(2000).all()
    out = []
    for call in calls:
        metadata = call.metadata_ or {}
        if metadata.get("is_test") or metadata.get("followed_up_at") or not metadata.get("qualification"):
            continue
        if not is_qualified(metadata):
            continue
        phone = lead_phone(call) or call.caller_number
        lead = _lead_for(db, call, phone) if phone else None
        out.append({
            "recipient_id": call.id, "kind": "inbound", "name": lead.name if lead else None, "phone": phone,
            "campaign_id": None, "campaign_name": "Inbound call", "campaign_kind": None,
            "interest": metadata.get("interest"), "summary": metadata.get("summary"),
            "reason": _reason(metadata), "callback_time": metadata.get("callback_time"),
            "call_id": call.id, "called_at": _naive(call.created_at),
        })
    return out


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
        "qualified": sum(1 for r in answered if is_qualified(r.result)),
        "callbacks": interests.count("callback"),
        "not_interested": interests.count("not_interested"),
        "do_not_call": interests.count("do_not_call"),
        "answer_rate": _rate(len(answered), sum(1 for r in recipients if r.status in ("COMPLETED", "FAILED"))),
        "avg_talk_seconds": round(sum(talk) / len(talk)) if talk else None,
        "minutes": round(sum(a.duration_seconds or 0.0 for a in attempts) / 60.0, 1),
    }

    # ------------------------------------------------ hot leads
    hot_recipients = [r for r in answered if is_qualified(r.result) and not (r.result or {}).get("followed_up_at")]
    hot = [
        {
            "recipient_id": r.id,
            "kind": "campaign",
            "name": r.name,
            "phone": r.phone,
            "campaign_id": r.campaign_id,
            "campaign_name": campaigns[r.campaign_id].name,
            "campaign_kind": campaigns[r.campaign_id].kind,
            "interest": _interest(r),
            "summary": (r.result or {}).get("summary"),
            "reason": _reason(r.result or {}),
            "callback_time": (r.result or {}).get("callback_time"),
            "call_id": r.last_call_id,
            "called_at": _naive(r.last_dialed_at),
        }
        for r in hot_recipients
    ] + _inbound_hot(db, client_id, since)
    hot.sort(key=lambda h: h["called_at"], reverse=True)
    out["hot_leads"] = hot[:HOT_LEADS_LIMIT]
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


def mark_followed_up(db: Session, client_id: str, lead_id: str, now: Optional[datetime] = None) -> bool:
    """
    Takes a hot lead off the follow-up list: a campaign recipient, or an inbound call (by call id).
    False when it isn't this client's.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    recipient = db.get(CampaignRecipient, lead_id)
    if recipient:
        if recipient.client_id != client_id:
            return False
        recipient.result = {**(recipient.result or {}), "followed_up_at": stamp}
        flag_modified(recipient, "result")
        db.commit()
        return True
    call = db.get(Call, lead_id)
    if not call or call.client_id != client_id or call.direction != "INBOUND":
        return False
    call.metadata_ = {**(call.metadata_ or {}), "followed_up_at": stamp}
    flag_modified(call, "metadata_")
    db.commit()
    return True
