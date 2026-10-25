"""
API keys for the public leads API: managed by client portal users for their own client, and by
internal users for any client.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user, require_operator
from app.core.config import settings
from app.models.api_key import ApiKey
from app.models.campaign import Campaign
from app.models.client import Client
from app.models.user import User
from app.services import instant_leads


class CreateApiKeyRequest(BaseModel):
    name: str = Field("Website", min_length=1, max_length=255)


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    is_default: Optional[bool] = None


class CreatedApiKeyResponse(ApiKeyResponse):
    key: str  # shown once


def _list(db: Session, client_id: str) -> List[ApiKey]:
    return db.query(ApiKey).filter(ApiKey.client_id == client_id).order_by(ApiKey.created_at.desc()).all()


def _create(db: Session, client_id: str, payload: CreateApiKeyRequest, user_id: str) -> CreatedApiKeyResponse:
    if not db.get(Client, client_id):
        raise HTTPException(status_code=404, detail="Client not found.")
    key, raw = instant_leads.create_api_key(db, client_id, payload.name, user_id)
    return CreatedApiKeyResponse(**ApiKeyResponse.model_validate(key).model_dump(), key=raw)


def _revoke(db: Session, client_id: str, key_id: str) -> ApiKey:
    key = db.get(ApiKey, key_id)
    if not key or key.client_id != client_id:
        raise HTTPException(status_code=404, detail="API key not found.")
    return instant_leads.revoke_api_key(db, key)


def public_leads_url() -> str:
    base = (settings.TELEPHONY_BASE_URL or "").rstrip("/") or "https://<your-choranta-domain>"
    return f"{base}/api/public/leads"


# ---------------------------------------------------------------- client portal

portal_router = APIRouter(prefix="/portal", tags=["Client Portal"])


@portal_router.get("/api-keys", response_model=List[ApiKeyResponse])
def portal_list_keys(account=Depends(require_client_user), db: Session = Depends(get_db)):
    return _list(db, account[1])


@portal_router.post("/api-keys", response_model=CreatedApiKeyResponse, status_code=201)
def portal_create_key(payload: CreateApiKeyRequest, account=Depends(require_client_user), db: Session = Depends(get_db)):
    user, client_id = account
    return _create(db, client_id, payload, user.id)


@portal_router.delete("/api-keys/{key_id}", response_model=ApiKeyResponse)
def portal_revoke_key(key_id: str, account=Depends(require_client_user), db: Session = Depends(get_db)):
    return _revoke(db, account[1], key_id)


@portal_router.get("/integrations")
def portal_integrations(account=Depends(require_client_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """What the "How to connect your website" panel needs."""
    client_id = account[1]
    campaigns = (
        db.query(Campaign)
        .filter(Campaign.client_id == client_id, Campaign.kind == "TRIGGER")
        .order_by(Campaign.created_at.desc()).all()
    )
    return {
        "leads_url": public_leads_url(),
        "rate_limit_per_minute": instant_leads.RATE_LIMIT_PER_MIN,
        "trigger_campaigns": [{"id": c.id, "name": c.name, "status": c.status} for c in campaigns],
        "active_keys": sum(1 for k in _list(db, client_id) if not k.revoked_at),
    }


def instant_setup(db: Session, client_id: str) -> Dict[str, Any]:
    """The dashboard's "call website enquiries instantly" card: what is set up, and the address and key to use."""
    from app.models.agent import Agent
    from app.models.agent_version import AgentVersion
    campaigns = (db.query(Campaign).filter(Campaign.client_id == client_id, Campaign.kind == "TRIGGER")
                 .order_by(Campaign.created_at.desc()).all())
    has_agent = db.query(AgentVersion.id).join(Agent, Agent.id == AgentVersion.agent_id).filter(
        Agent.client_id == client_id, AgentVersion.status == "PUBLISHED").first() is not None
    key = instant_leads.ensure_default_key(db, client_id)
    return {
        "leads_url": public_leads_url(),
        "has_agent": has_agent,
        "campaigns": [{"id": c.id, "name": c.name, "status": c.status} for c in campaigns],
        "running": any(c.status == "RUNNING" for c in campaigns),
        "key": {"id": key.id, "prefix": key.prefix, "created_at": key.created_at,
                "last_used_at": key.last_used_at} if key else None,
    }


@portal_router.get("/instant-setup")
def portal_instant_setup(account=Depends(require_client_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return instant_setup(db, account[1])


@portal_router.post("/instant-setup/key")
def portal_reveal_key(account=Depends(require_client_user), db: Session = Depends(get_db)) -> Dict[str, str]:
    """The full default key (a POST, so it isn't cached or kept in browser history)."""
    key = instant_leads.ensure_default_key(db, account[1])
    if not key:
        raise HTTPException(status_code=503, detail="Your key can't be shown right now. Please contact Choranta support.")
    try:
        return {"key": instant_leads.reveal_key(key)}
    except instant_leads.LeadError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@portal_router.post("/instant-setup/key/regenerate")
def portal_regenerate_key(account=Depends(require_client_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Makes a new default key; the old one stops working straight away."""
    user, client_id = account
    if not instant_leads.regenerate_default_key(db, client_id, user.id):
        raise HTTPException(status_code=503, detail="A new key can't be made right now. Please contact Choranta support.")
    return instant_setup(db, client_id)


# ---------------------------------------------------------------- internal users

admin_router = APIRouter(prefix="/clients/{client_id}/api-keys", tags=["Clients"])


@admin_router.get("", response_model=List[ApiKeyResponse])
def admin_list_keys(client_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    return _list(db, client_id)


@admin_router.post("", response_model=CreatedApiKeyResponse, status_code=201)
def admin_create_key(client_id: str, payload: CreateApiKeyRequest, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    return _create(db, client_id, payload, user.id)


@admin_router.delete("/{key_id}", response_model=ApiKeyResponse)
def admin_revoke_key(client_id: str, key_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)):
    return _revoke(db, client_id, key_id)
