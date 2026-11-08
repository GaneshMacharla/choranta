"""
Client notifications: short, plain-language messages under the bell in the client portal.

notify() only adds the row; the caller's transaction commits it together with the change it describes.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.notification import ClientNotification

MAX_LISTED = 30


def notify(db: Session, client_id: Optional[str], kind: str, title: str, body: Optional[str] = None,
           link: Optional[str] = None, level: str = "info") -> Optional[ClientNotification]:
    if not client_id:
        return None
    note = ClientNotification(client_id=client_id, kind=kind, title=title, body=body, link=link, level=level)
    db.add(note)
    return note


def has_ai_employee(db: Session, client_id: str) -> bool:
    """Whether the client already has an AI employee, or has asked for one."""
    from app.models.agent import Agent
    from app.models.agent_request import AgentRequest
    if db.query(Agent.id).filter(Agent.client_id == client_id).first():
        return True
    return db.query(AgentRequest.id).filter(
        AgentRequest.client_id == client_id, AgentRequest.status.in_(("PENDING", "IN_PROGRESS", "CLIENT_TRIAL", "COMPLETED"))
    ).first() is not None


def _out(n: ClientNotification) -> Dict[str, Any]:
    return {"id": n.id, "kind": n.kind, "level": n.level, "title": n.title, "body": n.body, "link": n.link,
            "read": n.read_at is not None, "created_at": n.created_at}


def list_for_client(db: Session, client_id: str) -> Dict[str, Any]:
    rows = (db.query(ClientNotification).filter(ClientNotification.client_id == client_id)
            .order_by(ClientNotification.created_at.desc()).limit(MAX_LISTED).all())
    unread = db.query(func.count(ClientNotification.id)).filter(
        ClientNotification.client_id == client_id, ClientNotification.read_at.is_(None)
    ).scalar() or 0
    return {"unread": unread, "items": [_out(n) for n in rows]}


def mark_read(db: Session, client_id: str, notification_id: Optional[str] = None) -> None:
    """Marks one notification read, or all of the client's when no id is given."""
    query = db.query(ClientNotification).filter(ClientNotification.client_id == client_id,
                                                ClientNotification.read_at.is_(None))
    if notification_id:
        query = query.filter(ClientNotification.id == notification_id)
    now = datetime.now(timezone.utc)
    for n in query.all():
        n.read_at = now
    db.commit()


def credits_text(amount: float) -> str:
    return f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"
