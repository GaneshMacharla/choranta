"""
AI employee requests: once a client has paid (an active plan or any payment), they give their company
name, type of business, the languages their customers speak and a name for the AI employee in the portal. A Choranta admin sets up everything else
in the agent wizard and links the agent, which completes the request. The company name and business type
also update the client's profile.

Names are unique per client (across their agents and open requests). Different clients may use the same
name; admins tell them apart by the client code shown alongside (e.g. "Priya · CL-10002").
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ChorantaException, ConflictException, NotFoundException, ValidationException
from app.models.agent import Agent
from app.models.agent_request import AgentRequest
from app.models.agent_version import AgentVersion
from app.models.billing import Invoice, WalletTransaction
from app.models.client import Client
from app.db import mongo
from app.services import knowledge_store, notifications, sarvam_voices, subscriptions

# Jobs a client can tick in plain words; the admin wizard maps them to a role and call direction
TASKS: Dict[str, str] = {
    "answer_calls": "Answer calls from customers",
    "answer_questions": "Answer questions about my products or services",
    "book_appointments": "Book appointments or visits",
    "call_leads": "Call new enquiries and leads",
    "send_reminders": "Remind customers (payments, appointments)",
    "collect_feedback": "Ask customers for feedback",
}
LANGUAGES: Dict[str, str] = {
    "en-IN": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam",
    "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "or": "Odia", "ur": "Urdu",
}
# Business types (BusinessTypeEnum values) in plain words for the portal form
BUSINESS_TYPES: Dict[str, str] = {
    "CLINIC": "Clinic",
    "HOSPITAL": "Hospital",
    "SALON": "Salon / Spa",
    "REAL_ESTATE": "Real estate",
    "COACHING": "Coaching centre",
    "HOTEL": "Hotel",
    "RESTAURANT": "Restaurant",
    "CORPORATE": "Company / Office",
    "OTHER": "Other",
}
COMPANY_MIN, COMPANY_MAX = 2, 100
# CLIENT_TRIAL: the team sent it to the client to try; the team still decides when it goes live
OPEN_STATUSES = ("PENDING", "IN_PROGRESS", "CLIENT_TRIAL")
STATUSES = ("PENDING", "IN_PROGRESS", "CLIENT_TRIAL", "COMPLETED", "REJECTED", "CANCELLED")
# A trial call that ends this soon after connecting because the connection dropped is given back
TRIAL_DROPPED_GRACE_S = 30
NAME_MIN, NAME_MAX = 2, 40


def has_paid(db: Session, client_id: str) -> bool:
    """A client may request AI employees once they have an active plan or have paid anything."""
    sub = subscriptions.get_subscription(db, client_id)
    if subscriptions.is_usable(sub):
        return True
    if db.query(Invoice.id).filter(Invoice.client_id == client_id).first() is not None:
        return True
    return db.query(WalletTransaction.id).filter(
        WalletTransaction.client_id == client_id, WalletTransaction.type == "CREDIT").first() is not None


def needs_documents(db: Session, client_id: str) -> bool:
    """
    Before their first AI employee, a client uploads files about their business (brochure, price list, FAQ...):
    Choranta's team builds the employee from them. Not checked when switched off or the knowledge store isn't set up.
    """
    if not settings.AGENT_REQUEST_REQUIRES_DOCUMENTS:
        return False
    if db.query(Agent.id).filter(Agent.client_id == client_id).first():
        return False
    return mongo.configured() and not knowledge_store.has_documents(client_id)


def _name_taken(db: Session, client_id: str, name: str, exclude_request: Optional[str] = None) -> bool:
    key = name.strip().lower()
    if db.query(Agent.id).filter(Agent.client_id == client_id, func.lower(Agent.name) == key).first():
        return True
    query = db.query(AgentRequest.id).filter(
        AgentRequest.client_id == client_id, func.lower(AgentRequest.name) == key, AgentRequest.status.in_(OPEN_STATUSES)
    )
    if exclude_request:
        query = query.filter(AgentRequest.id != exclude_request)
    return query.first() is not None


def _update_profile(db: Session, client: Client, company_name: str, business_type: str) -> None:
    """Saves the company name and type on the client's profile; the name only if no other client uses it."""
    client.business_type = business_type
    if company_name.lower() == (client.name or "").strip().lower():
        return
    taken = db.query(Client.id).filter(func.lower(Client.name) == company_name.lower(), Client.id != client.id).first()
    if not taken:
        client.name = company_name


def create_request(db: Session, client_id: str, name: str, company_name: str, business_type: str,
                   user_id: Optional[str], voice_id: Optional[str] = None,
                   languages: Optional[List[str]] = None) -> AgentRequest:
    if not has_paid(db, client_id):
        raise ChorantaException("Complete a payment (choose a plan or buy credits) before creating an AI employee.", status_code=402)
    if needs_documents(db, client_id):
        raise ValidationException("Upload at least one file about your business (brochure, price list, FAQ...) "
                                  "so our team can set up your AI employee.")
    name = " ".join((name or "").split())
    company_name = " ".join((company_name or "").split())
    business_type = (business_type or "").strip().upper()
    if not COMPANY_MIN <= len(company_name) <= COMPANY_MAX:
        raise ValidationException(f"Enter your company name ({COMPANY_MIN}–{COMPANY_MAX} characters).")
    if business_type not in BUSINESS_TYPES:
        raise ValidationException("Choose the type of business from the list.")
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise ValidationException(f"The AI employee's name must be {NAME_MIN}–{NAME_MAX} characters.")
    languages = [lang for lang in dict.fromkeys(languages or []) if lang]
    if not languages:
        raise ValidationException("Choose at least one language your customers speak.")
    if any(lang not in LANGUAGES for lang in languages):
        raise ValidationException("Choose languages from the list.")
    voice_id = (voice_id or "").strip()
    if voice_id and not sarvam_voices.is_voice(voice_id):
        raise ValidationException("Choose one of the listed voices.")
    if _name_taken(db, client_id, name):
        raise ConflictException(f"You already have an AI employee named '{name}'. Choose a different name.")
    client = db.get(Client, client_id)
    if client:
        _update_profile(db, client, company_name, business_type)
    request = AgentRequest(client_id=client_id, name=name, company_name=company_name, business_type=business_type,
                           voice_id=voice_id, details=json.dumps({"tasks": [], "languages": languages}),
                           requested_by=user_id)
    db.add(request)
    db.commit()
    return request


def get_request(db: Session, request_id: str, client_id: Optional[str] = None) -> AgentRequest:
    request = db.get(AgentRequest, request_id)
    if not request or (client_id and request.client_id != client_id):
        raise NotFoundException("AI employee request", request_id)
    return request


def cancel_request(db: Session, request: AgentRequest) -> AgentRequest:
    if request.status != "PENDING":
        raise ValidationException("Only requests that haven't been started can be cancelled.")
    request.status = "CANCELLED"
    db.commit()
    return request


def start_request(db: Session, request: AgentRequest, admin_id: str) -> AgentRequest:
    if request.status not in OPEN_STATUSES:
        raise ValidationException(f"This request is {request.status.lower()}.")
    if request.status == "PENDING":
        notifications.notify(db, request.client_id, "EMPLOYEE_SETUP", f"We're setting up {request.name}",
                             "Our team has started on your AI employee. We'll let you know when it's ready.",
                             link="/portal/employees")
    request.status = "IN_PROGRESS"
    request.handled_by = admin_id
    db.commit()
    return request


def link_request(db: Session, request: AgentRequest, agent_id: str, admin_id: str) -> AgentRequest:
    """Records the AI employee being built for this request. The client hears nothing until it goes live."""
    if request.status not in OPEN_STATUSES:
        raise ValidationException(f"This request is {request.status.lower()}.")
    agent = db.get(Agent, agent_id)
    if not agent or agent.client_id != request.client_id:
        raise ValidationException("Link an AI employee that belongs to this client.")
    if request.status == "PENDING":
        start_request(db, request, admin_id)
    request.agent_id = agent.id
    request.handled_by = admin_id
    db.commit()
    return request


def latest_published_version(db: Session, agent_id: str) -> Optional[AgentVersion]:
    return (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent_id, AgentVersion.status == "PUBLISHED")
        .order_by(AgentVersion.version_number.desc())
        .first()
    )


def send_for_trial(db: Session, request: AgentRequest, admin_id: str) -> AgentRequest:
    """Lets the client try the AI employee once from the portal. Sending again gives them a fresh trial call."""
    if request.status not in ("IN_PROGRESS", "CLIENT_TRIAL"):
        raise ValidationException(f"This request is {request.status.lower().replace('_', ' ')}.")
    agent = db.get(Agent, request.agent_id) if request.agent_id else None
    if not agent or agent.client_id != request.client_id:
        raise ValidationException("Build the AI employee for this request before sending it to the client.")
    version = latest_published_version(db, agent.id)
    if not version:
        raise ValidationException(f"Publish a version of {agent.name} before sending it to the client.")
    from app.runtime.readiness.checker import RuntimeReadinessChecker
    readiness = RuntimeReadinessChecker(db).check(agent.id, version.id)
    if not readiness["ready"]:
        raise ValidationException(f"{agent.name} isn't ready for calls yet: " + "; ".join(readiness["errors"]))
    request.status = "CLIENT_TRIAL"
    request.trial_calls_used = 0
    request.handled_by = admin_id
    notifications.notify(db, request.client_id, "EMPLOYEE_TRIAL", f"{request.name} is ready for you to try",
                         "Talk to it from your browser. Our team will contact you soon.", link="/portal/employees")
    db.commit()
    return request


def reserve_trial_call(db: Session, request_id: str, client_id: str) -> Tuple[AgentRequest, Agent, AgentVersion]:
    """
    Takes one of the client's trial calls, under a row lock so two tabs can't both take the last one.
    A refusal raises; the request's session then ends and releases the lock.
    """
    request = db.query(AgentRequest).filter(AgentRequest.id == request_id).with_for_update().first()
    if not request or request.client_id != client_id:
        raise NotFoundException("AI employee request", request_id)
    if request.status != "CLIENT_TRIAL":
        raise ValidationException(f"{request.name} isn't ready for you to try yet.")
    if (request.trial_calls_used or 0) >= settings.CLIENT_TRIAL_CALLS:
        raise ConflictException(f"You've already tried {request.name}. Our team will contact you soon.")
    agent = db.get(Agent, request.agent_id) if request.agent_id else None
    version = latest_published_version(db, agent.id) if agent else None
    if not agent or not version:
        raise ValidationException(f"{request.name} isn't ready for you to try yet.")
    request.trial_calls_used = (request.trial_calls_used or 0) + 1
    db.commit()
    return request, agent, version


def release_trial_call(db: Session, request_id: str) -> None:
    """Gives a trial call back (it never connected, or dropped straight away)."""
    request = db.query(AgentRequest).filter(AgentRequest.id == request_id).with_for_update().first()
    if request and (request.trial_calls_used or 0) > 0:
        request.trial_calls_used -= 1
    db.commit()


def trial_call_counts(reason: str, connected_seconds: Optional[float]) -> bool:
    """Whether an ended trial call used up the trial."""
    if connected_seconds is None:
        return False  # never connected
    return not (reason == "connection_failed" and connected_seconds < TRIAL_DROPPED_GRACE_S)


def _finish(db: Session, request: AgentRequest, agent: Agent) -> None:
    request.status = "COMPLETED"
    request.agent_id = agent.id
    request.completed_at = datetime.now(timezone.utc)
    notifications.notify(db, request.client_id, "EMPLOYEE_READY", f"{request.name} is ready!",
                         "Connect it to a phone number to start taking calls.", link="/portal/numbers", level="success")


def complete_for_agent(db: Session, agent: Agent) -> None:
    """The AI employee went live: tells the client, and closes the request it was built for."""
    requests = db.query(AgentRequest).filter(AgentRequest.agent_id == agent.id, AgentRequest.status.in_(OPEN_STATUSES)).all()
    for request in requests:
        _finish(db, request, agent)
    if requests:
        db.commit()


def complete_request(db: Session, request: AgentRequest, agent_id: str, admin_id: str) -> AgentRequest:
    if request.status not in OPEN_STATUSES:
        raise ValidationException(f"This request is {request.status.lower()}.")
    agent = db.get(Agent, agent_id)
    if not agent or agent.client_id != request.client_id:
        raise ValidationException("Link an AI employee that belongs to this client.")
    # The client is told it can take calls, so it must be able to
    from app.runtime.readiness.checker import live_block_reason
    if not db.query(AgentVersion.id).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "PUBLISHED").first():
        raise ValidationException(f"{agent.name} has no published version yet.")
    not_live = live_block_reason(agent)
    if not_live:
        raise ValidationException(not_live)
    request.handled_by = admin_id
    _finish(db, request, agent)
    db.commit()
    return request


def reject_request(db: Session, request: AgentRequest, note: str, admin_id: str) -> AgentRequest:
    if request.status not in OPEN_STATUSES:
        raise ValidationException(f"This request is {request.status.lower()}.")
    if not (note or "").strip():
        raise ValidationException("Tell the client why the request was declined.")
    request.status = "REJECTED"
    request.admin_note = note.strip()
    request.handled_by = admin_id
    notifications.notify(db, request.client_id, "EMPLOYEE_DECLINED", f"We couldn't set up {request.name}",
                         request.admin_note, link="/portal/employees", level="warning")
    db.commit()
    return request


def _details(request: AgentRequest) -> Dict[str, List[str]]:
    try:
        data = json.loads(request.details) if request.details else {}
    except ValueError:
        data = {}
    return {"tasks": list(data.get("tasks") or []), "languages": list(data.get("languages") or [])}


def request_out(db: Session, request: AgentRequest, client: Optional[Client] = None) -> Dict[str, Any]:
    client = client or db.get(Client, request.client_id)
    agent = db.get(Agent, request.agent_id) if request.agent_id else None
    details = _details(request)
    return {
        "id": request.id,
        "client_id": request.client_id,
        "client_name": client.name if client else None,
        "client_code": client.client_code if client else None,
        "name": request.name,
        "voice_id": request.voice_id or None,
        "voice_name": request.voice_id.capitalize() if request.voice_id else None,
        "company_name": request.company_name or (client.name if client else None),
        "business_type": request.business_type,
        "business_type_label": BUSINESS_TYPES.get(request.business_type or "", None),
        "notes": request.notes,
        "tasks": details["tasks"],
        "task_labels": [TASKS.get(t, t) for t in details["tasks"]],
        "languages": details["languages"],
        "language_labels": [LANGUAGES.get(lang, lang) for lang in details["languages"]],
        "status": request.status,
        "agent_id": request.agent_id,
        "agent_name": agent.name if agent else None,
        "admin_note": request.admin_note,
        "trial_calls_used": request.trial_calls_used or 0,
        "trial_calls_allowed": settings.CLIENT_TRIAL_CALLS,
        "trial_max_minutes": max(1, round(settings.CLIENT_TRIAL_MAX_DURATION_S / 60)),
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "completed_at": request.completed_at,
    }


def list_requests(db: Session, client_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    query = db.query(AgentRequest)
    if client_id:
        query = query.filter(AgentRequest.client_id == client_id)
    if status == "OPEN":
        query = query.filter(AgentRequest.status.in_(OPEN_STATUSES))
    elif status:
        query = query.filter(AgentRequest.status == status)
    rows = query.order_by(AgentRequest.created_at.desc()).limit(500).all()
    clients = {c.id: c for c in db.query(Client).filter(Client.id.in_({r.client_id for r in rows})).all()} if rows else {}
    return [request_out(db, r, clients.get(r.client_id)) for r in rows]


def open_count(db: Session) -> int:
    return db.query(func.count(AgentRequest.id)).filter(AgentRequest.status == "PENDING").scalar() or 0
