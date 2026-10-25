"""
Who counts as a qualified lead, decided per AI employee by the client.

After a call, the post-call extraction (services/call_outputs.py) fills the agent's output variables and the
caller's interest, and, when the client wrote one, applies their plain-language test ("plans to join this
year") with a one-line reason. qualify() then decides, in this order:

1. The caller asked never to be called again: not qualified.
2. The client's rules over the collected details (any group whose conditions all hold qualifies). A clear
   yes or no from the rules wins, because it rests on what the caller actually said.
3. The rules can't tell (a detail wasn't collected) or there are none: the AI's test, if written.
4. Nothing configured: interested or asked for a callback, as before.

The result {"status": qualified / not_qualified / unknown, "reason", "source": rules / ai / interest} is kept in
Call.metadata["qualification"] and drives hot leads, the WhatsApp follow-up and the lead's qualification status.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ChorantaException
from app.models.agent import Agent
from app.models.call import Call
from app.models.qualification import LeadQualificationSetup

QUALIFIED, NOT_QUALIFIED, UNKNOWN = "qualified", "not_qualified", "unknown"
STATUSES = (QUALIFIED, NOT_QUALIFIED, UNKNOWN)
INTEREST_FIELD = "interest"
HOT_INTERESTS = ("interested", "callback")
INTEREST_LABELS = {"interested": "Interested", "callback": "Asked for a callback", "not_interested": "Not interested",
                   "do_not_call": "Asked not to be called", "unclear": "Unclear"}

# Operators per data type; "is_set" works on any field
OPS: Dict[str, Tuple[str, ...]] = {
    "boolean": ("is_true", "is_false", "is_set"),
    "number": ("gte", "lte", "eq", "is_set"),
    "string": ("in", "contains", "is_set"),
    "interest": ("in",),
}
MAX_GROUPS, MAX_CONDITIONS, MAX_CRITERIA_CHARS = 10, 10, 500
REEVALUATE_DAYS = 30


class QualificationError(ChorantaException):
    pass


def _label(name: str) -> str:
    return name.replace("_", " ")


# ---------------------------------------------------------------- the agent's fields


def fields_for_agent(db: Session, agent_id: str) -> List[Dict[str, str]]:
    """Details rules can test: the agent's output variables, and the caller's interest."""
    from app.services.whatsapp import latest_version
    version = latest_version(db, agent_id)
    outputs = (((version.configuration_json or {}) if version else {}).get("variables") or {}).get("outputs") or []
    fields = [{"name": INTEREST_FIELD, "label": "Caller's interest", "data_type": "interest"}]
    for o in outputs:
        if isinstance(o, dict) and o.get("name") and o["name"] != INTEREST_FIELD:
            data_type = (o.get("data_type") or "string").lower()
            fields.append({"name": o["name"], "label": o.get("description") or _label(o["name"]),
                           "data_type": data_type if data_type in OPS else "string"})
    return fields


def suggested_rules(fields: List[Dict[str, str]]) -> List[List[Dict[str, Any]]]:
    """A starting point: anyone who booked something (demo, visit, appointment...) is qualified."""
    booked = [f for f in fields if f["data_type"] == "boolean"
              and any(w in f["name"].lower() for w in ("book", "schedul", "regist", "confirm", "enrol", "visit"))]
    if booked:
        return [[{"field": f["name"], "op": "is_true"}] for f in booked]
    return [[{"field": INTEREST_FIELD, "op": "in", "value": list(HOT_INTERESTS)}]]


# ---------------------------------------------------------------- rules


def validate_rules(rules: Any, fields: List[Dict[str, str]]) -> List[List[Dict[str, Any]]]:
    """Checks and normalises rules against the agent's fields."""
    if not isinstance(rules, list):
        raise QualificationError("Rules must be a list of groups.")
    if len(rules) > MAX_GROUPS:
        raise QualificationError(f"Use at most {MAX_GROUPS} groups.")
    by_name = {f["name"]: f for f in fields}
    clean: List[List[Dict[str, Any]]] = []
    for group in rules:
        if not isinstance(group, list) or not group:
            continue
        if len(group) > MAX_CONDITIONS:
            raise QualificationError(f"Use at most {MAX_CONDITIONS} conditions in a group.")
        out = []
        for cond in group:
            if not isinstance(cond, dict):
                raise QualificationError("Each condition needs a detail and a check.")
            field = by_name.get(cond.get("field"))
            if not field:
                raise QualificationError(f"'{cond.get('field')}' isn't a detail this AI employee collects.")
            op = cond.get("op")
            if op not in OPS[field["data_type"]]:
                raise QualificationError(f"That check doesn't apply to '{field['label']}'.")
            item: Dict[str, Any] = {"field": field["name"], "op": op}
            if op in ("in",):
                values = [str(v).strip() for v in (cond.get("value") or []) if str(v).strip()]
                if not values:
                    raise QualificationError(f"Give at least one value for '{field['label']}'.")
                item["value"] = values[:20]
            elif op == "contains":
                value = str(cond.get("value") or "").strip()
                if not value:
                    raise QualificationError(f"Give the text to look for in '{field['label']}'.")
                item["value"] = value[:100]
            elif op in ("gte", "lte", "eq"):
                try:
                    item["value"] = float(cond.get("value"))
                except (TypeError, ValueError):
                    raise QualificationError(f"Give a number for '{field['label']}'.")
            out.append(item)
        clean.append(out)
    return clean


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _check(cond: Dict[str, Any], details: Dict[str, Any]) -> Optional[bool]:
    """True / False, or None when the detail wasn't collected."""
    value = details.get(cond["field"])
    op = cond["op"]
    if op == "is_set":
        return value not in (None, "")
    if value in (None, "") or (cond["field"] == INTEREST_FIELD and value == "unclear"):
        return None
    if op == "is_true":
        return value is True
    if op == "is_false":
        return value is False
    if op in ("gte", "lte", "eq"):
        number = _number(value)
        if number is None:
            return None
        target = float(cond["value"])
        return number >= target if op == "gte" else number <= target if op == "lte" else number == target
    text = str(value).strip().lower()
    if op == "in":
        return text in {str(v).strip().lower() for v in cond.get("value") or []}
    if op == "contains":
        return str(cond.get("value") or "").strip().lower() in text
    return None


def describe(cond: Dict[str, Any], details: Optional[Dict[str, Any]] = None) -> str:
    """'demo class booked', 'target exam is NEET or JEE', 'student class at least 11'."""
    name, op = _label(cond["field"]), cond["op"]
    if cond["field"] == INTEREST_FIELD:
        shown = (details or {}).get(INTEREST_FIELD)
        if shown:
            return INTEREST_LABELS.get(shown, shown)
        return " or ".join(INTEREST_LABELS.get(v, v) for v in cond.get("value") or [])
    if op == "is_true":
        return name
    if op == "is_false":
        return f"not {name}"
    if op == "is_set":
        return f"{name} given"
    if op == "in":
        shown = (details or {}).get(cond["field"])
        return f"{name}: {shown}" if shown not in (None, "") else f"{name} is {' or '.join(cond.get('value') or [])}"
    if op == "contains":
        return f"{name} mentions {cond.get('value')}"
    value = cond.get("value")
    value = int(value) if isinstance(value, float) and value.is_integer() else value
    return f"{name} {'at least' if op == 'gte' else 'at most' if op == 'lte' else 'is'} {value}"


def evaluate_rules(rules: List[List[Dict[str, Any]]], details: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """(status, reason): qualified if any group fully holds; unknown if one still could; else not qualified."""
    if not rules:
        return UNKNOWN, None
    undecided = False
    for group in rules:
        results = [_check(c, details) for c in group]
        if all(r is True for r in results):
            reason = "; ".join(describe(c, details) for c in group)
            return QUALIFIED, reason[:1].upper() + reason[1:]
        if not any(r is False for r in results):
            undecided = True
    if undecided:
        return UNKNOWN, None
    return NOT_QUALIFIED, "Didn't meet your qualification rules"


# ---------------------------------------------------------------- deciding


def get_setup(db: Session, agent_id: Optional[str]) -> Optional[LeadQualificationSetup]:
    if not agent_id:
        return None
    return db.query(LeadQualificationSetup).filter(LeadQualificationSetup.agent_id == agent_id).first()


def ai_criteria(db: Session, agent_id: Optional[str]) -> Optional[str]:
    setup = get_setup(db, agent_id)
    return (setup.ai_criteria or "").strip() or None if setup else None


def qualify(setup: Optional[LeadQualificationSetup], outputs: Dict[str, Any], interest: Optional[str],
            ai: Optional[Dict[str, Any]] = None, summary: Optional[str] = None) -> Dict[str, Any]:
    """The call's qualification, from the client's rules, then their AI test, then the caller's interest."""
    if interest == "do_not_call":
        return {"status": NOT_QUALIFIED, "reason": "Asked not to be called again", "source": INTEREST_FIELD}
    details = {**(outputs or {}), INTEREST_FIELD: interest}
    rules = list(setup.rules or []) if setup else []
    if rules:
        status, reason = evaluate_rules(rules, details)
        if status != UNKNOWN:
            return {"status": status, "reason": reason, "source": "rules"}
    if setup and (setup.ai_criteria or "").strip():
        if ai and ai.get("status") in STATUSES:
            return {"status": ai["status"], "reason": ai.get("reason") or None, "source": "ai"}
        return {"status": UNKNOWN, "reason": "Not enough on the call to tell", "source": "ai"}
    if rules:
        return {"status": UNKNOWN, "reason": "A detail your rules need wasn't collected", "source": "rules"}
    if interest in HOT_INTERESTS:
        return {"status": QUALIFIED, "reason": summary or INTEREST_LABELS[interest], "source": INTEREST_FIELD}
    if interest in ("not_interested",):
        return {"status": NOT_QUALIFIED, "reason": INTEREST_LABELS[interest], "source": INTEREST_FIELD}
    return {"status": UNKNOWN, "reason": None, "source": INTEREST_FIELD}


def is_qualified(metadata: Optional[Dict[str, Any]]) -> bool:
    """For calls (and campaign results) analysed before qualification existed, interest decides."""
    metadata = metadata or {}
    qualification = metadata.get("qualification")
    if isinstance(qualification, dict) and qualification.get("status"):
        return qualification["status"] == QUALIFIED
    return metadata.get("interest") in HOT_INTERESTS


def record_on_lead(db: Session, call: Call, qualification: Dict[str, Any]) -> None:
    """Marks the call's lead QUALIFIED / UNQUALIFIED, unless the agent or the client already set a status."""
    status = {QUALIFIED: "QUALIFIED", NOT_QUALIFIED: "UNQUALIFIED"}.get(qualification.get("status"))
    if not status:
        return
    from app.services.whatsapp_followups import _lead_for, lead_phone
    phone = lead_phone(call)
    lead = _lead_for(db, call, phone) if phone else None
    if lead and (lead.lead_qualification_status or "PENDING") == "PENDING":
        lead.lead_qualification_status = status
        db.commit()


# ---------------------------------------------------------------- client settings


def own_agent(db: Session, client_id: str, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent or agent.client_id != client_id:
        raise QualificationError("AI employee not found.", 404)
    return agent


def setup_out(db: Session, agent: Agent) -> Dict[str, Any]:
    setup = get_setup(db, agent.id)
    fields = fields_for_agent(db, agent.id)
    return {
        "agent_id": agent.id, "agent_name": agent.name, "fields": fields,
        "ops": {k: list(v) for k, v in OPS.items()},
        "interest_values": [{"value": k, "label": v} for k, v in INTEREST_LABELS.items() if k != "unclear"],
        "configured": setup is not None,
        "rules": list(setup.rules or []) if setup else [],
        "ai_criteria": setup.ai_criteria if setup else None,
        "suggested_rules": suggested_rules(fields),
        "updated_at": setup.updated_at if setup else None,
    }


def save_setup(db: Session, client_id: str, agent_id: str, rules: Any, criteria: Optional[str],
               user_id: Optional[str] = None) -> LeadQualificationSetup:
    own_agent(db, client_id, agent_id)
    clean = validate_rules(rules, fields_for_agent(db, agent_id))
    criteria = (criteria or "").strip() or None
    if criteria and len(criteria) > MAX_CRITERIA_CHARS:
        raise QualificationError(f"Keep the description under {MAX_CRITERIA_CHARS} characters.")
    setup = get_setup(db, agent_id)
    if setup is None:
        setup = LeadQualificationSetup(client_id=client_id, agent_id=agent_id)
        db.add(setup)
    setup.rules, setup.ai_criteria, setup.updated_by = clean, criteria, user_id
    flag_modified(setup, "rules")
    db.commit()
    return setup


def reevaluate(db: Session, client_id: str, agent_id: str, days: int = REEVALUATE_DAYS,
               now: Optional[datetime] = None) -> int:
    """
    Applies the current rules to the agent's recent calls from what was already collected (no new AI runs:
    a call without a stored AI verdict for a newly written test stays unknown). Returns how many changed.
    """
    from app.models.campaign import CampaignRecipient
    own_agent(db, client_id, agent_id)
    setup = get_setup(db, agent_id)
    since = (now or datetime.now(timezone.utc).replace(tzinfo=None)) - timedelta(days=days)
    calls = db.query(Call).filter(Call.agent_id == agent_id, Call.client_id == client_id,
                                  Call.created_at >= since).all()
    changed = 0
    for call in calls:
        metadata = dict(call.metadata_ or {})
        if metadata.get("outputs_status") != "done":
            continue
        previous = metadata.get("qualification") or {}
        updated = qualify(setup, metadata.get("outputs") or {}, metadata.get("interest"),
                          ai=metadata.get("ai_qualification"), summary=metadata.get("summary"))
        if (updated["status"], updated["reason"]) == (previous.get("status"), previous.get("reason")):
            continue
        metadata["qualification"] = updated
        call.metadata_ = metadata
        flag_modified(call, "metadata_")
        recipient_id = metadata.get("recipient_id")
        recipient = db.get(CampaignRecipient, recipient_id) if recipient_id else None
        if recipient and recipient.last_call_id == call.id:
            recipient.result = {**(recipient.result or {}), "qualification": updated}
            flag_modified(recipient, "result")
        changed += 1
    db.commit()
    return changed
