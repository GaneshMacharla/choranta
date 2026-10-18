"""
Outbound calling campaigns: recipient import, validation, lifecycle and the dialer.

The dialer (run_campaign_tick) keeps each running campaign's calls in flight up to its concurrency
limit, inside its calling windows, retrying no-answer / busy / failed calls after a delay. All state
lives in the database, so a restart picks up where it left off; recipients are claimed atomically
before dialling so overlapping ticks can never call the same person twice.
"""
import csv
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.campaign import Campaign, CampaignAttempt, CampaignRecipient, DoNotCallEntry, WebhookDelivery
from app.models.client import Client
from app.models.lead import Lead
from app.models.phone_number import PhoneNumber
from app.models.runtime_event import RuntimeEvent
from app.services import billing, phone_numbers, subscriptions
from app.services.outbound_calls import OutboundCallError, place_outbound_call

logger = logging.getLogger("choranta.services.campaigns")

MAX_RECIPIENTS = 10_000
# Bulk campaigns only call between 09:00 and 21:00 local time. Instant outbound (TRIGGER) calls
# people who just asked for a callback, so it may run around the clock (window 00:00-24:00).
EARLIEST_MIN, LATEST_MIN = 9 * 60, 21 * 60
DAY_MIN = 24 * 60
MAX_RETRIES = 3
RETRYABLE_OUTCOMES = ("no-answer", "busy", "failed")
TERMINAL_CALL_STATUSES = ("COMPLETED", "FAILED", "TERMINATED", "CANCELLED")
# A recipient whose call never reports an outcome is given up on after this long
STALE_DIAL_AFTER = timedelta(hours=3)
# How long an answered call's recipient waits for the post-call extraction of the agent's outputs
OUTPUTS_WAIT = timedelta(minutes=2)
# Don't call someone again for this long after another campaign of the same client reached them
RECENTLY_REACHED = timedelta(hours=24)
ACTIVE_STATUSES = ("SCHEDULED", "RUNNING", "STOPPING")
# A recipient claimed for dialling whose dial never happened (e.g. a crash) goes back in the queue
CLAIM_TIMEOUT = timedelta(minutes=2)
# Instant website leads: default retries (minutes) when the form submitter doesn't answer
TRIGGER_RETRY_INTERVALS = [5, 30]
# Results webhooks: wait (minutes) before each retry; given up after the last one
WEBHOOK_RETRY_MIN = [1, 5, 15, 60]
WEBHOOK_TIMEOUT_S = 10.0
# Validated caller numbers are reused briefly so instant dials skip their lookups
CALLER_CACHE_TTL_S = 60.0
_caller_cache: Dict[str, Tuple[float, Optional[SimpleNamespace]]] = {}
# Errors that block every call in the campaign until someone fixes the cause
PAUSING_ERRORS = ("NO_BALANCE", "PLAN_EXPIRED", "NOT_READY", "CONFIG", "CALLER_UNAVAILABLE", "NOT_FOUND", "NOT_ALLOWED")

PHONE_COLUMNS = ("phone", "phone_number", "mobile", "mobile_number", "number", "contact_number", "contact", "to_number")
NAME_COLUMNS = ("name", "full_name", "user_name", "customer_name", "student_name", "lead_name")


class CampaignError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def utcnow() -> datetime:
    return subscriptions.utcnow()


# ---------------------------------------------------------------- recipients


def normalize_phone(raw: Any) -> Optional[str]:
    """E.164 for a phone number; bare Indian mobile numbers (10 digits, 0- or 91-prefixed) get +91."""
    text = str(raw or "").strip()
    if not text:
        return None
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if plus:
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if digits.startswith("00"):
        digits = digits[2:]
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        return f"+91{digits[1:]}"
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    return None


def _column_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")


@dataclass
class ParsedRecipients:
    rows: List[Dict[str, Any]] = field(default_factory=list)       # {"phone", "name", "variables", "line"}
    invalid: List[Dict[str, Any]] = field(default_factory=list)    # {"line", "value", "reason"}
    duplicates: int = 0
    phone_column: Optional[str] = None
    variable_names: List[str] = field(default_factory=list)


def parse_recipients_csv(text: str) -> ParsedRecipients:
    """
    Reads a recipient CSV. One column holds the phone number (phone / mobile / number / contact_number);
    a name column becomes `user_name`, and every other column becomes an agent variable.
    """
    result = ParsedRecipients()
    text = (text or "").lstrip("﻿")
    if not text.strip():
        raise CampaignError("The CSV file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(reader)
    except StopIteration:
        raise CampaignError("The CSV file is empty.")
    keys = [_column_key(h) for h in header]

    phone_idx = next((keys.index(k) for k in PHONE_COLUMNS if k in keys), None)
    if phone_idx is None:
        raise CampaignError("No phone column found. Name one column 'phone' (or mobile / number / contact_number).")
    name_idx = next((keys.index(k) for k in NAME_COLUMNS if k in keys), None)
    result.phone_column = header[phone_idx].strip()
    variable_idx = [i for i, k in enumerate(keys) if k and i not in (phone_idx, name_idx)]
    result.variable_names = (["user_name"] if name_idx is not None else []) + [keys[i] for i in variable_idx]

    seen = set()
    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        raw_phone = row[phone_idx] if phone_idx < len(row) else ""
        phone = normalize_phone(raw_phone)
        if not phone:
            result.invalid.append({"line": line_no, "value": raw_phone, "reason": "Not a valid phone number"})
            continue
        if phone in seen:
            result.duplicates += 1
            continue
        if len(result.rows) >= MAX_RECIPIENTS:
            raise CampaignError(f"A campaign can have at most {MAX_RECIPIENTS:,} recipients.")
        seen.add(phone)
        name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else ""
        variables = {keys[i]: row[i].strip() for i in variable_idx if i < len(row) and row[i].strip()}
        if name:
            variables["user_name"] = name
        result.rows.append({"phone": phone, "name": name or None, "variables": variables, "line": line_no})
    return result


def lead_variables(lead: Lead) -> Dict[str, Any]:
    """The agent variables a lead provides (same mapping as answered outbound calls)."""
    variables: Dict[str, Any] = {"user_name": lead.name, "lead_id": lead.id}
    for attr in ("property_viewed", "enquiry_location", "enquiry_budget", "enquiry_bhk"):
        value = getattr(lead, attr, None)
        if value:
            variables[attr] = value
    return variables


def _add_recipients(db: Session, campaign: Campaign, rows: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    """Adds recipients, skipping numbers already in the campaign. Returns (added, already_present)."""
    existing = {p for (p,) in db.query(CampaignRecipient.phone).filter(CampaignRecipient.campaign_id == campaign.id)}
    position = len(existing)
    added = skipped = 0
    for row in rows:
        if row["phone"] in existing:
            skipped += 1
            continue
        if position >= MAX_RECIPIENTS:
            raise CampaignError(f"A campaign can have at most {MAX_RECIPIENTS:,} recipients.")
        existing.add(row["phone"])
        db.add(CampaignRecipient(
            campaign_id=campaign.id,
            client_id=campaign.client_id,
            phone=row["phone"],
            name=row.get("name"),
            variables=row.get("variables") or {},
            lead_id=row.get("lead_id"),
            position=position,
        ))
        position += 1
        added += 1
    db.commit()
    return added, skipped


def add_recipients_from_csv(db: Session, campaign: Campaign, text: str) -> Dict[str, Any]:
    _require_bulk(campaign)
    _require_editable(campaign)
    parsed = parse_recipients_csv(text)
    added, already = _add_recipients(db, campaign, parsed.rows)
    return {"added": added, "already_present": already, "invalid": parsed.invalid[:50],
            "invalid_count": len(parsed.invalid), "duplicates": parsed.duplicates}


def add_recipients_from_leads(db: Session, campaign: Campaign, lead_ids: List[str]) -> Dict[str, Any]:
    _require_bulk(campaign)
    _require_editable(campaign)
    leads = db.query(Lead).filter(Lead.id.in_(lead_ids), Lead.client_id == campaign.client_id).all()
    rows, invalid = [], []
    for lead in leads:
        phone = normalize_phone(lead.phone)
        if not phone:
            invalid.append({"line": None, "value": lead.phone, "reason": f"Lead '{lead.name}' has no valid phone number"})
            continue
        rows.append({"phone": phone, "name": lead.name, "variables": lead_variables(lead), "lead_id": lead.id})
    added, already = _add_recipients(db, campaign, rows)
    return {"added": added, "already_present": already, "invalid": invalid, "invalid_count": len(invalid), "duplicates": 0}


def remove_recipient(db: Session, campaign: Campaign, recipient_id: str) -> None:
    _require_editable(campaign)
    deleted = db.query(CampaignRecipient).filter(
        CampaignRecipient.id == recipient_id, CampaignRecipient.campaign_id == campaign.id
    ).delete(synchronize_session=False)
    db.commit()
    if not deleted:
        raise CampaignError("Recipient not found.", 404)


# ---------------------------------------------------------------- configuration


def _zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Kolkata")


def concurrency_cap(db: Session, client_id: str) -> Optional[int]:
    """Most simultaneous campaign calls allowed: the client's call limit, keeping one line free for inbound calls."""
    limit = billing.client_concurrency_limit(db, client_id)
    if not limit:
        return None
    return max(1, limit - 1)


def validate_config(db: Session, campaign: Campaign) -> None:
    """Raises CampaignError describing the first problem with the campaign's settings."""
    if campaign.kind not in ("BULK", "TRIGGER"):
        raise CampaignError("Campaign type must be BULK or TRIGGER.")
    if campaign.webhook_url and not str(campaign.webhook_url).startswith("https://"):
        raise CampaignError("The results webhook URL must start with https://")
    agent = db.get(Agent, campaign.agent_id)
    if not agent or agent.client_id != campaign.client_id:
        raise CampaignError("Choose an AI Employee that belongs to this client.")
    version = db.get(AgentVersion, campaign.agent_version_id)
    if not version or version.agent_id != agent.id:
        raise CampaignError("Choose a version of the selected AI Employee.")
    if version.status != "PUBLISHED":
        raise CampaignError("Only published versions can make campaign calls.")

    if not campaign.caller_number_ids:
        raise CampaignError("Choose at least one phone number to call from.")
    for number_id in campaign.caller_number_ids:
        number = db.get(PhoneNumber, number_id)
        if not number or number.client_id != campaign.client_id:
            raise CampaignError("A selected phone number doesn't belong to this client.")
        if number.status != "ACTIVE":
            raise CampaignError(f"Phone number {number.phone_number} is not active.")
        blocked = phone_numbers.blocked_reason(db, number)
        if blocked:
            raise CampaignError(f"Phone number {number.phone_number}: {blocked}")

    windows = campaign.windows or []
    if not windows:
        raise CampaignError("Add at least one calling window.")
    earliest, latest = (0, DAY_MIN) if campaign.kind == "TRIGGER" else (EARLIEST_MIN, LATEST_MIN)
    for w in windows:
        start, end = int(w.get("start_min", -1)), int(w.get("end_min", -1))
        if not (earliest <= start < end <= latest):
            if campaign.kind == "TRIGGER":
                raise CampaignError("Each calling window must end after it starts.")
            raise CampaignError("Calling windows must be between 09:00 and 21:00 and end after they start.")
    days = campaign.days or []
    if not days or any(d not in range(7) for d in days):
        raise CampaignError("Choose at least one calling day.")
    try:
        ZoneInfo(campaign.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise CampaignError(f"Unknown timezone '{campaign.timezone}'.")

    if campaign.max_concurrent < 1:
        raise CampaignError("Concurrent calls must be at least 1.")
    cap = concurrency_cap(db, campaign.client_id)
    if cap is not None and campaign.max_concurrent > cap:
        raise CampaignError(f"This client's call limit allows at most {cap} concurrent campaign call(s) "
                            "(one line is kept free for incoming calls).")
    if not 0 <= campaign.retry_max <= MAX_RETRIES:
        raise CampaignError(f"Retries must be between 0 and {MAX_RETRIES}.")
    if campaign.retry_max and not campaign.retry_intervals_min:
        raise CampaignError("Set how long to wait before retrying.")
    if any(not 5 <= int(m) <= 24 * 60 for m in campaign.retry_intervals_min or []):
        raise CampaignError("Retry intervals must be between 5 minutes and 24 hours.")
    if any(o not in RETRYABLE_OUTCOMES for o in campaign.retry_on or []):
        raise CampaignError("Only no-answer, busy and failed calls can be retried.")


def version_campaign_inputs(version: Optional[AgentVersion]) -> List[Dict[str, Any]]:
    """The agent version's inputs typed once per campaign (e.g. the course and demo timings of a batch
    announcement), as name, description, example and whether it is required."""
    from app.services.agent_templates_business import CAMPAIGN_SOURCE

    inputs = (((version.configuration_json or {}) if version else {}).get("variables") or {}).get("inputs") or []
    return [
        {"name": v["name"], "description": v.get("description") or v["name"], "required": bool(v.get("required")),
         "example": (v.get("extraction_instructions") or "").removeprefix("e.g. ")}
        for v in inputs if v.get("source") == CAMPAIGN_SOURCE and v.get("name")
    ]


def campaign_inputs(db: Session, campaign: Campaign) -> List[Dict[str, Any]]:
    return version_campaign_inputs(db.get(AgentVersion, campaign.agent_version_id))


def _clean_variables(values: Optional[Dict[str, Any]]) -> Dict[str, str]:
    return {str(k): str(v).strip() for k, v in (values or {}).items() if v is not None and str(v).strip()}


def _require_campaign_details(db: Session, campaign: Campaign) -> None:
    missing = [v["description"] for v in campaign_inputs(db, campaign)
               if v.get("required") and not (campaign.variables or {}).get(v["name"])]
    if missing:
        raise CampaignError("Fill in the campaign details before launching: " + ", ".join(missing) + ".")


def _require_editable(campaign: Campaign) -> None:
    if campaign.status != "DRAFT":
        raise CampaignError("Only draft campaigns can be changed.", 409)


def _require_bulk(campaign: Campaign) -> None:
    if campaign.kind == "TRIGGER":
        raise CampaignError("Website-lead campaigns receive recipients from the leads API, not uploads.", 409)


def _ensure_webhook_secret(campaign: Campaign) -> None:
    if campaign.webhook_url and not campaign.webhook_secret:
        campaign.webhook_secret = "whsec_" + secrets.token_hex(24)


def create_campaign(db: Session, client_id: str, data: Dict[str, Any], created_by: Optional[str]) -> Campaign:
    client = db.get(Client, client_id)
    if not client:
        raise CampaignError("Client not found.", 404)
    data = dict(data)
    if not data.get("timezone"):
        data["timezone"] = client.timezone if client.timezone and client.timezone != "UTC" else "Asia/Kolkata"
    data["variables"] = _clean_variables(data.get("variables"))
    campaign = Campaign(client_id=client_id, created_by=created_by, **{k: v for k, v in data.items() if v is not None})
    campaign.kind = campaign.kind or "BULK"
    _ensure_webhook_secret(campaign)
    validate_config(db, campaign)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def update_campaign(db: Session, campaign: Campaign, data: Dict[str, Any]) -> Campaign:
    """Bulk campaigns can be changed while drafts; website-lead campaigns any time before they end."""
    if campaign.kind == "TRIGGER":
        if campaign.status in ("STOPPING", "COMPLETED", "CANCELLED"):
            raise CampaignError("This campaign has ended.", 409)
    else:
        _require_editable(campaign)
    data = dict(data)
    if data.pop("kind", None) not in (None, campaign.kind):
        raise CampaignError("A campaign's type can't be changed.", 409)
    if "webhook_url" in data and not data["webhook_url"]:
        campaign.webhook_url = None
        data.pop("webhook_url")
    if data.get("variables") is not None:
        data["variables"] = _clean_variables(data["variables"])
    for key, value in data.items():
        if value is not None:
            setattr(campaign, key, value)
    _ensure_webhook_secret(campaign)
    validate_config(db, campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def delete_campaign(db: Session, campaign: Campaign) -> None:
    if campaign.status not in ("DRAFT", "CANCELLED", "COMPLETED"):
        raise CampaignError("Stop the campaign before deleting it.", 409)
    db.delete(campaign)
    db.commit()


# ---------------------------------------------------------------- lifecycle


def _recipient_count(db: Session, campaign_id: str, statuses: Optional[Tuple[str, ...]] = None) -> int:
    q = db.query(func.count(CampaignRecipient.id)).filter(CampaignRecipient.campaign_id == campaign_id)
    if statuses:
        q = q.filter(CampaignRecipient.status.in_(statuses))
    return q.scalar() or 0


def launch(db: Session, campaign: Campaign, user_id: Optional[str], consent: bool) -> Campaign:
    if campaign.status != "DRAFT":
        raise CampaignError("This campaign has already been launched.", 409)
    if not consent:
        raise CampaignError("Confirm that recipients agreed to be contacted before launching.")
    if campaign.kind == "BULK" and not _recipient_count(db, campaign.id):
        raise CampaignError("Add recipients before launching.")
    validate_config(db, campaign)
    _require_campaign_details(db, campaign)
    now = utcnow()
    campaign.consent_ack_by = user_id
    campaign.consent_ack_at = now
    campaign.launched_at = now
    campaign.pause_reason = None
    campaign.status = "SCHEDULED" if campaign.start_at and campaign.start_at > now else "RUNNING"
    db.commit()
    db.refresh(campaign)
    return campaign


def pause(db: Session, campaign: Campaign, reason: str = "Paused by user") -> Campaign:
    if campaign.status not in ("SCHEDULED", "RUNNING"):
        raise CampaignError("Only scheduled or running campaigns can be paused.", 409)
    campaign.status = "PAUSED"
    campaign.pause_reason = reason
    db.commit()
    db.refresh(campaign)
    return campaign


def resume(db: Session, campaign: Campaign) -> Campaign:
    if campaign.status != "PAUSED":
        raise CampaignError("Only paused campaigns can be resumed.", 409)
    validate_config(db, campaign)
    campaign.status = "SCHEDULED" if campaign.start_at and campaign.start_at > utcnow() else "RUNNING"
    campaign.pause_reason = None
    db.commit()
    db.refresh(campaign)
    return campaign


def stop(db: Session, campaign: Campaign) -> Campaign:
    """No new calls; calls in progress finish, then the campaign completes."""
    if campaign.status not in ("SCHEDULED", "RUNNING", "PAUSED"):
        raise CampaignError("This campaign isn't running.", 409)
    campaign.status = "STOPPING"
    _skip_remaining(db, campaign, "stopped")
    _finish_if_done(db, campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def cancel(db: Session, campaign: Campaign) -> Campaign:
    if campaign.status not in ("DRAFT", "SCHEDULED"):
        raise CampaignError("Only draft or scheduled campaigns can be cancelled; stop a running campaign instead.", 409)
    campaign.status = "CANCELLED"
    _skip_remaining(db, campaign, "cancelled")
    campaign.completed_at = utcnow()
    db.commit()
    db.refresh(campaign)
    return campaign


def _skip_remaining(db: Session, campaign: Campaign, outcome: str) -> None:
    db.query(CampaignRecipient).filter(
        CampaignRecipient.campaign_id == campaign.id,
        CampaignRecipient.status.in_(("PENDING", "RETRY_WAIT")),
    ).update({"status": "SKIPPED", "outcome": outcome, "next_attempt_at": None}, synchronize_session=False)


def _finish_if_done(db: Session, campaign: Campaign) -> None:
    if campaign.kind == "TRIGGER" and campaign.status != "STOPPING":
        return  # always on: new leads can arrive at any time
    open_statuses = ("DIALING",) if campaign.status == "STOPPING" else ("PENDING", "RETRY_WAIT", "DIALING")
    if not _recipient_count(db, campaign.id, open_statuses):
        campaign.status = "COMPLETED"
        campaign.completed_at = utcnow()


# ---------------------------------------------------------------- do-not-call


def add_do_not_call(db: Session, client_id: str, phone: str, source: str = "manual", note: Optional[str] = None) -> Optional[DoNotCallEntry]:
    normalized = normalize_phone(phone)
    if not normalized:
        raise CampaignError("Not a valid phone number.")
    entry = db.query(DoNotCallEntry).filter(DoNotCallEntry.client_id == client_id, DoNotCallEntry.phone == normalized).first()
    if entry:
        return entry
    entry = DoNotCallEntry(client_id=client_id, phone=normalized, source=source, note=note)
    db.add(entry)
    db.commit()
    return entry


def remove_do_not_call(db: Session, client_id: str, entry_id: str) -> None:
    deleted = db.query(DoNotCallEntry).filter(DoNotCallEntry.id == entry_id, DoNotCallEntry.client_id == client_id).delete()
    db.commit()
    if not deleted:
        raise CampaignError("Entry not found.", 404)


def _suppression_reason(db: Session, campaign: Campaign, recipient: CampaignRecipient, now: datetime) -> Optional[str]:
    """Why this person must not be called right now (opted out, or already reached recently). One query."""
    lead_filter = [Lead.client_id == campaign.client_id, Lead.call_disposition == "DO_NOT_CALL"]
    lead_filter.append(Lead.id == recipient.lead_id if recipient.lead_id else Lead.phone.endswith(recipient.phone[-10:]))
    on_dnc, opted_out, reached = db.execute(select(
        exists().where(DoNotCallEntry.client_id == campaign.client_id, DoNotCallEntry.phone == recipient.phone),
        exists().where(*lead_filter),
        exists().where(
            CampaignRecipient.client_id == campaign.client_id,
            CampaignRecipient.phone == recipient.phone,
            CampaignRecipient.campaign_id != campaign.id,
            CampaignRecipient.outcome == "answered",
            CampaignRecipient.updated_at >= now - RECENTLY_REACHED,
        ),
    )).one()
    if on_dnc:
        return "On the do-not-call list"
    if opted_out:
        return "Lead asked not to be called"
    if reached:
        return "Reached by another campaign in the last 24 hours"
    return None


# ---------------------------------------------------------------- dialer


def in_calling_window(campaign: Campaign, now: datetime) -> bool:
    local = now.replace(tzinfo=timezone.utc).astimezone(_zone(campaign.timezone))
    if local.weekday() not in (campaign.days or []):
        return False
    minute = local.hour * 60 + local.minute
    return any(int(w["start_min"]) <= minute < int(w["end_min"]) for w in campaign.windows or [])


# Lead dispositions (set by lead tools during the call) mapped to the extracted interest values
LEAD_DISPOSITION_INTEREST = {
    "INTERESTED": "interested",
    "CALLBACK_REQUESTED": "callback",
    "NOT_INTERESTED": "not_interested",
    "DO_NOT_CALL": "do_not_call",
}


def _call_result(db: Session, call: Call, recipient: CampaignRecipient) -> Dict[str, Any]:
    """What the agent did on the call: tool actions with their arguments, and the lead's outcome."""
    result: Dict[str, Any] = {}
    metadata = call.metadata_ or {}
    if isinstance(metadata.get("outputs"), dict):
        result["outputs"] = metadata["outputs"]
    if metadata.get("summary"):
        result["summary"] = metadata["summary"]
    if metadata.get("interest"):
        result["interest"] = metadata["interest"]
    if metadata.get("callback_time"):
        result["callback_time"] = metadata["callback_time"]
    if call.runtime_session_id:
        actions = []
        events = (
            db.query(RuntimeEvent)
            .filter(RuntimeEvent.session_id == call.runtime_session_id, RuntimeEvent.event_type == "TOOL_CALL_STARTED")
            .order_by(RuntimeEvent.timestamp).all()
        )
        for event in events:
            payload = event.payload_json or {}
            if payload.get("tool_name") and payload.get("tool_name") != "end_call":
                actions.append({"tool": payload.get("tool_name"), "arguments": payload.get("arguments") or {}})
        if actions:
            result["actions"] = actions
    lead = db.get(Lead, recipient.lead_id) if recipient.lead_id else None
    if lead:
        result["lead"] = {
            "qualification_status": lead.lead_qualification_status,
            "call_disposition": lead.call_disposition,
            "next_action": lead.next_action,
        }
        # What the agent recorded on the lead is more reliable than reading the transcript
        disposition_interest = LEAD_DISPOSITION_INTEREST.get((lead.call_disposition or "").upper())
        if disposition_interest:
            result["interest"] = disposition_interest
    return result


def _caller_opted_out(result: Dict[str, Any]) -> bool:
    if result.get("interest") == "do_not_call":
        return True
    if (result.get("lead") or {}).get("call_disposition") == "DO_NOT_CALL":
        return True
    for action in result.get("actions") or []:
        args = action.get("arguments") or {}
        if args.get("call_disposition") == "DO_NOT_CALL" or args.get("lead_qualification_status") == "DO_NOT_CALL":
            return True
    return False


def _record_attempt(db: Session, campaign: Campaign, recipient: CampaignRecipient, call: Optional[Call],
                    status: str, outcome: str, error: Optional[str], now: datetime) -> None:
    db.add(CampaignAttempt(
        campaign_id=campaign.id,
        recipient_id=recipient.id,
        call_id=call.id if call else recipient.last_call_id,
        attempt_no=recipient.attempts,
        caller_number=call.caller_number if call else None,
        status=status,
        outcome=outcome,
        duration_seconds=float(call.duration_seconds or 0.0) if call else 0.0,
        error=error,
        started_at=recipient.last_dialed_at,
        ended_at=now,
    ))


def _fail_attempt(db: Session, campaign: Campaign, recipient: CampaignRecipient, outcome: str,
                  error: Optional[str], now: datetime, call: Optional[Call] = None) -> None:
    """Records a failed dial and schedules a retry when the outcome and attempt count allow it."""
    _record_attempt(db, campaign, recipient, call, "FAILED", outcome, error, now)
    recipient.outcome = outcome
    recipient.error = error
    retryable = outcome in (campaign.retry_on or []) and recipient.attempts <= campaign.retry_max
    if retryable and campaign.status != "STOPPING":
        intervals = campaign.retry_intervals_min or [30]
        wait = int(intervals[min(recipient.attempts - 1, len(intervals) - 1)])
        recipient.status = "RETRY_WAIT"
        recipient.next_attempt_at = now + timedelta(minutes=wait)
    else:
        recipient.status = "FAILED"
        recipient.next_attempt_at = None
        queue_webhook(db, campaign, recipient, call, now)


def _call_outcome(call: Call) -> str:
    reason = (call.termination_reason or "").strip().lower().replace("_", "-")
    if reason in ("no-answer", "busy", "canceled", "cancelled"):
        return "no-answer" if reason.startswith("cancel") else reason
    return "failed"


def _sync_dialing(db: Session, campaign: Campaign, now: datetime) -> None:
    """Moves recipients whose call has ended to their outcome."""
    dialing = db.query(CampaignRecipient).filter(
        CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "DIALING"
    ).all()
    for recipient in dialing:
        call = db.get(Call, recipient.last_call_id) if recipient.last_call_id else None
        if call and call.status in TERMINAL_CALL_STATUSES:
            if call.status == "COMPLETED" and _outputs_pending(call, recipient, now):
                continue  # the agent's outputs are still being extracted from the transcript
            if call.status == "COMPLETED":
                recipient.result = _call_result(db, call, recipient)
                recipient.status = "COMPLETED"
                recipient.outcome = "answered"
                recipient.error = None
                recipient.next_attempt_at = None
                _record_attempt(db, campaign, recipient, call, "COMPLETED", "answered", None, now)
                if _caller_opted_out(recipient.result):
                    add_do_not_call(db, campaign.client_id, recipient.phone, source="caller_request",
                                    note=f"Asked not to be called during campaign '{campaign.name}'")
                queue_webhook(db, campaign, recipient, call, now)
            else:
                _fail_attempt(db, campaign, recipient, _call_outcome(call), call.termination_reason, now, call)
        elif call is None and recipient.last_dialed_at and now - recipient.last_dialed_at > CLAIM_TIMEOUT:
            # Claimed but never dialled (the process stopped in between): put it back in the queue
            recipient.status = "PENDING" if recipient.attempts == 0 else "RETRY_WAIT"
            recipient.next_attempt_at = now if recipient.attempts else None
        elif recipient.last_dialed_at and now - recipient.last_dialed_at > STALE_DIAL_AFTER:
            _fail_attempt(db, campaign, recipient, "failed", "No call outcome was reported", now, call)
    db.commit()


def _outputs_pending(call: Call, recipient: CampaignRecipient, now: datetime) -> bool:
    if (call.metadata_ or {}).get("outputs_status") != "pending":
        return False
    ended = call.ended_at or recipient.last_dialed_at
    if ended is None:
        return False
    if ended.tzinfo is not None:
        ended = ended.astimezone(timezone.utc).replace(tzinfo=None)
    return now - ended < OUTPUTS_WAIT


def _claim(db: Session, recipient: CampaignRecipient, now: datetime) -> bool:
    """Marks the recipient DIALING only if nobody else has; committed before the carrier is called."""
    claimed = db.query(CampaignRecipient).filter(
        CampaignRecipient.id == recipient.id, CampaignRecipient.status == recipient.status
    ).update({"status": "DIALING", "last_dialed_at": now}, synchronize_session=False)
    db.commit()
    if claimed:
        db.refresh(recipient)
    return bool(claimed)


def _release(db: Session, recipient: CampaignRecipient, previous_status: str) -> None:
    recipient.status = previous_status
    db.commit()


def _usable_caller(db: Session, number_id: str) -> Optional[SimpleNamespace]:
    """The number if it can place calls (active, rent paid), cached for CALLER_CACHE_TTL_S."""
    cached = _caller_cache.get(number_id)
    if cached and time.monotonic() - cached[0] < CALLER_CACHE_TTL_S:
        return cached[1]
    number = db.get(PhoneNumber, number_id)
    usable = None
    if number and number.status == "ACTIVE" and not phone_numbers.blocked_reason(db, number):
        usable = SimpleNamespace(id=number.id, phone_number=number.phone_number, provider=number.provider or "exotel")
    _caller_cache[number_id] = (time.monotonic(), usable)
    return usable


def _next_caller(db: Session, campaign: Campaign) -> Optional[SimpleNamespace]:
    ids = campaign.caller_number_ids or []
    for _ in range(len(ids)):
        number_id = ids[(campaign.next_caller_index or 0) % len(ids)]
        campaign.next_caller_index = ((campaign.next_caller_index or 0) + 1) % len(ids)
        number = _usable_caller(db, number_id)
        if number:
            return number
    return None


def dials_in_last_minute(db: Session, now: datetime) -> int:
    return db.query(func.count(CampaignRecipient.id)).filter(
        CampaignRecipient.last_dialed_at >= now - timedelta(minutes=1)
    ).scalar() or 0


def _dial_campaign(db: Session, campaign: Campaign, now: datetime, budget: int,
                   dial: Callable[..., Call]) -> int:
    """Places calls for one running campaign; returns how many were placed."""
    live = _recipient_count(db, campaign.id, ("DIALING",))
    free = min(campaign.max_concurrent - live, budget)
    if free > 0 and campaign.kind == "BULK":
        free = min(free, _bulk_headroom(db, campaign))
    if free <= 0:
        return 0
    candidates = (
        db.query(CampaignRecipient)
        .filter(
            CampaignRecipient.campaign_id == campaign.id,
            (CampaignRecipient.status == "PENDING")
            | ((CampaignRecipient.status == "RETRY_WAIT") & (CampaignRecipient.next_attempt_at <= now)),
        )
        .order_by(CampaignRecipient.attempts, CampaignRecipient.position)
        .limit(free * 3)
        .all()
    )
    placed = 0
    for recipient in candidates:
        if placed >= free:
            break
        previous_status = recipient.status
        if not _claim(db, recipient, now):
            continue
        result = dial_claimed(db, campaign, recipient, previous_status, now, dial)
        if result == "placed":
            placed += 1
        elif result == "stop":
            break
    return placed


def dial_claimed(db: Session, campaign: Campaign, recipient: CampaignRecipient, previous_status: str,
                 now: datetime, dial: Callable[..., Call] = place_outbound_call) -> str:
    """
    Dials a recipient already claimed (status DIALING, no call yet). Returns "placed", "skipped",
    "failed", "released" (put back for a later attempt) or "stop" (no more dials this pass).
    """
    reason = _suppression_reason(db, campaign, recipient, now)
    if reason:
        recipient.status = "SKIPPED"
        recipient.outcome = "suppressed"
        recipient.error = reason
        queue_webhook(db, campaign, recipient, None, now)
        db.commit()
        return "skipped"

    caller = _next_caller(db, campaign)
    if not caller:
        _release(db, recipient, previous_status)
        pause(db, campaign, "None of the campaign's phone numbers can place calls right now.")
        return "stop"

    try:
        call = dial(
            db,
            destination_number=recipient.phone,
            agent_id=campaign.agent_id,
            agent_version_id=campaign.agent_version_id,
            caller_id=caller.phone_number,
            custom_field=f"campaign:{campaign.id}",
            variables={**(campaign.variables or {}), **(recipient.variables or {})},
            extra_metadata={"campaign_id": campaign.id, "campaign_recipient_id": recipient.id},
            caller_record=caller,
            client_id=campaign.client_id,
        )
    except OutboundCallError as e:
        if e.code == "CONCURRENCY":
            # The client's lines are busy (e.g. inbound calls): try again on the next tick
            _release(db, recipient, previous_status)
            return "stop"
        if e.code in PAUSING_ERRORS:
            _release(db, recipient, previous_status)
            pause(db, campaign, e.message)
            return "stop"
        recipient.attempts += 1
        _fail_attempt(db, campaign, recipient, "failed", e.message, now)
        db.commit()
        return "failed"
    recipient.attempts += 1
    recipient.last_call_id = call.id
    db.commit()
    return "placed"


def _bulk_headroom(db: Session, campaign: Campaign) -> int:
    """
    Lines a bulk campaign may use right now. While the client has a running website-lead campaign,
    one line stays free for instant leads (on plans with a concurrency limit).
    """
    has_trigger = db.query(Campaign.id).filter(
        Campaign.client_id == campaign.client_id, Campaign.kind == "TRIGGER", Campaign.status == "RUNNING"
    ).first()
    if not has_trigger:
        return campaign.max_concurrent
    limit = billing.client_concurrency_limit(db, campaign.client_id)
    if not limit:
        return campaign.max_concurrent
    return limit - billing.live_call_count(db, campaign.client_id) - 1


def run_campaign_tick(db: Session, now: Optional[datetime] = None,
                      dial: Callable[..., Call] = place_outbound_call) -> int:
    """One pass of the dialer over every active campaign. Returns the number of calls placed."""
    now = now or utcnow()
    placed = 0
    budget = max(0, settings.CAMPAIGN_MAX_DIALS_PER_MIN - dials_in_last_minute(db, now))
    # Website-lead (TRIGGER) campaigns first: instant leads take priority over bulk lists
    campaign_ids = [
        cid for (cid, _kind) in sorted(
            db.query(Campaign.id, Campaign.kind).filter(Campaign.status.in_(ACTIVE_STATUSES)).all(),
            key=lambda row: 0 if row[1] == "TRIGGER" else 1,
        )
    ]
    for campaign_id in campaign_ids:
        campaign = db.get(Campaign, campaign_id)
        try:
            if campaign.status == "SCHEDULED":
                if campaign.start_at and campaign.start_at > now:
                    continue
                campaign.status = "RUNNING"
                db.commit()
            _sync_dialing(db, campaign, now)
            if campaign.status == "RUNNING" and in_calling_window(campaign, now) and budget > 0:
                count = _dial_campaign(db, campaign, now, budget, dial)
                placed += count
                budget -= count
            if campaign.status in ("RUNNING", "STOPPING"):
                _finish_if_done(db, campaign)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(f"Campaign {campaign_id} tick failed")
    try:
        deliver_due_webhooks(db, now)
    except Exception:
        db.rollback()
        logger.exception("Webhook delivery failed")
    return placed


def run_campaign_job(session_factory) -> int:
    db = session_factory()
    try:
        return run_campaign_tick(db)
    finally:
        db.close()


# ---------------------------------------------------------------- reporting


def stats(db: Session, campaign: Campaign) -> Dict[str, Any]:
    by_status = dict(
        db.query(CampaignRecipient.status, func.count(CampaignRecipient.id))
        .filter(CampaignRecipient.campaign_id == campaign.id)
        .group_by(CampaignRecipient.status).all()
    )
    by_outcome = dict(
        db.query(CampaignRecipient.outcome, func.count(CampaignRecipient.id))
        .filter(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.outcome.isnot(None))
        .group_by(CampaignRecipient.outcome).all()
    )
    attempts, seconds = db.query(func.count(CampaignAttempt.id), func.coalesce(func.sum(CampaignAttempt.duration_seconds), 0.0)).filter(
        CampaignAttempt.campaign_id == campaign.id
    ).one()
    total = sum(by_status.values())
    answered = by_outcome.get("answered", 0)
    collected = count_outputs(result for (result,) in db.query(CampaignRecipient.result).filter(
        CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "COMPLETED"
    ))
    finished = by_status.get("COMPLETED", 0) + by_status.get("FAILED", 0)
    return {
        "total": total,
        "pending": by_status.get("PENDING", 0),
        "dialing": by_status.get("DIALING", 0),
        "retry_wait": by_status.get("RETRY_WAIT", 0),
        "completed": by_status.get("COMPLETED", 0),
        "failed": by_status.get("FAILED", 0),
        "skipped": by_status.get("SKIPPED", 0),
        "answered": answered,
        "outcomes": by_outcome,
        "answer_rate": round(answered / finished, 3) if finished else None,
        "attempts": attempts or 0,
        "minutes": round(float(seconds or 0.0) / 60.0, 1),
        "done": by_status.get("COMPLETED", 0) + by_status.get("FAILED", 0) + by_status.get("SKIPPED", 0),
        "collected": collected,
    }


def count_outputs(results: Iterable[Optional[Dict[str, Any]]], top: int = 8) -> Dict[str, Dict[str, int]]:
    """{variable: {value: count}} over recipients' collected outputs, most common values first."""
    collected: Dict[str, Dict[str, int]] = {}
    for result in results:
        for name, value in ((result or {}).get("outputs") or {}).items():
            if value is None or value == "":
                continue
            label = ("Yes" if value else "No") if isinstance(value, bool) else str(value)[:60]
            counts = collected.setdefault(name, {})
            counts[label] = counts.get(label, 0) + 1
    return {name: dict(sorted(counts.items(), key=lambda kv: -kv[1])[:top]) for name, counts in collected.items()}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def export_results_csv(db: Session, campaign: Campaign) -> str:
    recipients = (
        db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id)
        .order_by(CampaignRecipient.position).all()
    )
    variable_names: List[str] = []
    for r in recipients:
        for key in (r.variables or {}):
            if key not in variable_names and key not in ("user_name", "lead_id"):
                variable_names.append(key)
    output_names: List[str] = []
    for r in recipients:
        for key in ((r.result or {}).get("outputs") or {}):
            if key not in output_names:
                output_names.append(key)
    calls = {
        c.id: c for c in db.query(Call).filter(Call.id.in_([r.last_call_id for r in recipients if r.last_call_id])).all()
    } if recipients else {}

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["phone", "name", *variable_names, "status", "outcome", "attempts", "last_call_id",
                     "duration_seconds", *output_names, "summary", "qualification_status", "call_disposition",
                     "agent_actions", "error"])
    for r in recipients:
        call = calls.get(r.last_call_id)
        lead = (r.result or {}).get("lead") or {}
        actions = "; ".join(
            f"{a.get('tool')}({', '.join(f'{k}={v}' for k, v in (a.get('arguments') or {}).items())})"
            for a in (r.result or {}).get("actions") or []
        )
        writer.writerow([
            r.phone, r.name or "", *[(r.variables or {}).get(k, "") for k in variable_names],
            r.status, r.outcome or "", r.attempts, r.last_call_id or "",
            round(float(call.duration_seconds or 0.0)) if call else "",
            *[_cell(((r.result or {}).get("outputs") or {}).get(k)) for k in output_names],
            (r.result or {}).get("summary") or "",
            lead.get("qualification_status") or "", lead.get("call_disposition") or "", actions, r.error or "",
        ])
    return out.getvalue()


# ---------------------------------------------------------------- results webhooks


def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over "<timestamp>.<body>", hex encoded (header X-Choranta-Signature: sha256=<hex>)."""
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def webhook_payload(campaign: Campaign, recipient: CampaignRecipient, call: Optional[Call], now: datetime) -> Dict[str, Any]:
    result = recipient.result or {}
    recording = None
    if call is not None:
        recording = call.recording_url or (
            f"{(settings.TELEPHONY_BASE_URL or '').rstrip('/')}/api/portal/calls/{call.id}/recording" if call.runtime_session_id else None
        )
    return {
        "event": "recipient.finished",
        "campaign": {"id": campaign.id, "name": campaign.name, "kind": campaign.kind},
        "recipient": {
            "id": recipient.id,
            "phone": recipient.phone,
            "name": recipient.name,
            "source": recipient.source,
            "variables": recipient.variables or {},
            "status": recipient.status,
            "outcome": recipient.outcome,
            "attempts": recipient.attempts,
            "error": recipient.error,
        },
        "call": {
            "id": call.id,
            "duration_seconds": round(float(call.duration_seconds or 0.0), 1),
            "recording_url": recording,
        } if call is not None else None,
        "summary": result.get("summary"),
        "outputs": result.get("outputs") or {},
        "lead": result.get("lead"),
        "finished_at": now.replace(tzinfo=timezone.utc).isoformat(),
    }


def queue_webhook(db: Session, campaign: Campaign, recipient: CampaignRecipient, call: Optional[Call], now: datetime) -> None:
    """Queues the results webhook for a recipient that reached a final state (no-op without a URL)."""
    if not campaign.webhook_url:
        return
    if call is None and recipient.last_call_id:
        call = db.get(Call, recipient.last_call_id)
    db.add(WebhookDelivery(
        campaign_id=campaign.id,
        recipient_id=recipient.id,
        url=campaign.webhook_url,
        payload=webhook_payload(campaign, recipient, call, now),
        next_attempt_at=now,
    ))


def post_webhook(url: str, body: bytes, headers: Dict[str, str]) -> int:
    response = httpx.post(url, content=body, headers=headers, timeout=WEBHOOK_TIMEOUT_S)
    return response.status_code


def deliver_due_webhooks(db: Session, now: datetime, limit: int = 20) -> int:
    """Sends pending webhooks; failed ones are retried after WEBHOOK_RETRY_MIN. Returns the number sent."""
    due = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.status == "PENDING", WebhookDelivery.next_attempt_at <= now)
        .order_by(WebhookDelivery.created_at).limit(limit).all()
    )
    sent = 0
    for delivery in due:
        campaign = db.get(Campaign, delivery.campaign_id)
        secret = (campaign.webhook_secret if campaign else None) or ""
        body = json.dumps(delivery.payload, separators=(",", ":"), default=str).encode()
        timestamp = str(int(now.replace(tzinfo=timezone.utc).timestamp()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Choranta-Webhooks/1.0",
            "X-Choranta-Event": "recipient.finished",
            "X-Choranta-Delivery": delivery.id,
            "X-Choranta-Timestamp": timestamp,
            "X-Choranta-Signature": f"sha256={sign_webhook(secret, timestamp, body)}",
        }
        delivery.attempts += 1
        try:
            code = post_webhook(delivery.url, body, headers)
            delivery.last_status_code = code
            ok = 200 <= code < 300
            delivery.last_error = None if ok else f"HTTP {code}"
        except Exception as e:
            ok = False
            delivery.last_error = f"{type(e).__name__}: {e}"[:300]
        if ok:
            delivery.status = "SENT"
            delivery.sent_at = now
            sent += 1
        elif delivery.attempts > len(WEBHOOK_RETRY_MIN):
            delivery.status = "FAILED"
        else:
            delivery.next_attempt_at = now + timedelta(minutes=WEBHOOK_RETRY_MIN[delivery.attempts - 1])
        db.commit()
    return sent


def rotate_webhook_secret(db: Session, campaign: Campaign) -> Campaign:
    campaign.webhook_secret = "whsec_" + secrets.token_hex(24)
    db.commit()
    db.refresh(campaign)
    return campaign
