"""
AI employee requests: once a client has paid (an active plan or any paid invoice), they give their company
name, type of business, the languages their customers speak and a name for the AI employee in the portal. A Choranta admin sets up everything else
in the agent wizard and links the agent, which completes the request. The company name and business type
also update the client's profile.

Names are unique per client (across their agents and open requests). Different clients may use the same
name; admins tell them apart by the client code shown alongside (e.g. "Priya · CL-10002").
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import ChorantaException, ConflictException, NotFoundException, ValidationException
from app.models.agent import Agent
from app.models.agent_request import AgentRequest
from app.models.billing import Invoice
from app.models.client import Client
from app.services import notifications, sarvam_voices, subscriptions

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
    "HOTEL": "Hotel",
    "RESTAURANT": "Restaurant",
    "CORPORATE": "Company / Office",
    "OTHER": "Other",
}
COMPANY_MIN, COMPANY_MAX = 2, 100
OPEN_STATUSES = ("PENDING", "IN_PROGRESS")
STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETED", "REJECTED", "CANCELLED")
NAME_MIN, NAME_MAX = 2, 40


def has_paid(db: Session, client_id: str) -> bool:
    """A client may request AI employees once they have an active plan or have paid anything."""
    sub = subscriptions.get_subscription(db, client_id)
    if subscriptions.is_usable(sub):
        return True
    return db.query(Invoice.id).filter(Invoice.client_id == client_id).first() is not None


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


def complete_request(db: Session, request: AgentRequest, agent_id: str, admin_id: str) -> AgentRequest:
    if request.status not in OPEN_STATUSES:
        raise ValidationException(f"This request is {request.status.lower()}.")
    agent = db.get(Agent, agent_id)
    if not agent or agent.client_id != request.client_id:
        raise ValidationException("Link an AI employee that belongs to this client.")
    request.status = "COMPLETED"
    request.agent_id = agent.id
    request.handled_by = admin_id
    request.completed_at = datetime.now(timezone.utc)
    notifications.notify(db, request.client_id, "EMPLOYEE_READY", f"{request.name} is ready!",
                         "Connect it to a phone number to start taking calls.", link="/portal/numbers", level="success")
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
