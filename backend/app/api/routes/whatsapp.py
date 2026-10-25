"""WhatsApp follow-ups: Meta's webhook, and the client portal's connection and message settings."""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user
from app.core.config import settings
from app.models.agent import Agent
from app.models.call import Call
from app.services import whatsapp, whatsapp_followups

logger = logging.getLogger("choranta.api.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])
portal_router = APIRouter(prefix="/portal/whatsapp", tags=["Client Portal"])


def webhook_url() -> str:
    base = (settings.TELEPHONY_BASE_URL or "").rstrip("/") or "https://<your-choranta-domain>"
    return f"{base}{settings.API_V1_PREFIX}/whatsapp/webhook"


# ---------------------------------------------------------------- Meta's webhook


@router.get("/webhook")
def verify_webhook(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                   challenge: str = Query("", alias="hub.challenge")):
    """Meta's one-time check when the callback URL is saved in the app's webhook settings."""
    if mode == "subscribe" and settings.WHATSAPP_VERIFY_TOKEN and token == settings.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed.")


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")
    signature = request.headers.get("X-Hub-Signature-256")
    messaging = whatsapp.provider()
    if not any(messaging.verify_signature(raw, signature, secret) for secret in whatsapp.webhook_secrets(db, payload)):
        logger.warning("Rejected a WhatsApp webhook with a missing or wrong signature")
        raise HTTPException(status_code=403, detail="Invalid signature.")
    whatsapp_followups.handle_webhook(db, payload)
    return {"ok": True}


# ---------------------------------------------------------------- portal


class AccountIn(BaseModel):
    waba_id: str = Field(..., max_length=64)
    phone_number_id: str = Field(..., max_length=64)
    access_token: str = Field(..., max_length=1024)
    app_secret: Optional[str] = Field(None, max_length=256)


class FollowupIn(BaseModel):
    enabled: bool = True
    message: str = Field(..., max_length=2000)
    language: str = "en"
    send_when: List[str] = Field(default_factory=lambda: ["qualified"])
    button_text: Optional[str] = Field(None, max_length=60)
    button_url: Optional[str] = Field(None, max_length=2000)


def _raise(exc: whatsapp.WhatsAppError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _overview(db: Session, client_id: str):
    agents = db.query(Agent).filter(Agent.client_id == client_id).order_by(Agent.name).all()
    return {
        "account": whatsapp.account_out(whatsapp.get_account(db, client_id)),
        "webhook_url": webhook_url(),
        "verify_token": settings.WHATSAPP_VERIFY_TOKEN or "",
        "followups": [whatsapp.followup_out(db, a, whatsapp.get_followup(db, client_id, a.id)) for a in agents],
    }


@portal_router.get("")
def overview(account=Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    return _overview(db, client_id)


@portal_router.put("/account")
def connect(body: AccountIn, account=Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    try:
        whatsapp.connect_account(db, client_id, body.waba_id, body.phone_number_id, body.access_token, body.app_secret)
    except whatsapp.WhatsAppError as exc:
        _raise(exc)
    return _overview(db, client_id)


@portal_router.delete("/account")
def disconnect(account=Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    whatsapp.disconnect_account(db, client_id)
    return _overview(db, client_id)


@portal_router.put("/followups/{agent_id}")
def save_followup(agent_id: str, body: FollowupIn, account=Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    try:
        followup = whatsapp.save_followup(
            db, client_id, agent_id, enabled=body.enabled, message=body.message, send_when=body.send_when,
            language=body.language, button_text=body.button_text, button_url=body.button_url,
        )
    except whatsapp.WhatsAppError as exc:
        _raise(exc)
    return whatsapp.followup_out(db, db.get(Agent, agent_id), followup)


@portal_router.get("/calls")
def call_summaries(ids: str = Query("", max_length=4000), account=Depends(require_client_user),
                   db: Session = Depends(get_db)):
    """For lists: each call's follow-up status and reply count, keyed by call id."""
    _, client_id = account
    call_ids = [i for i in ids.split(",") if i][:200]
    return whatsapp_followups.threads_for_calls(db, client_id, call_ids)


@portal_router.get("/calls/{call_id}")
def call_thread(call_id: str, account=Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    call = db.get(Call, call_id)
    if not call or call.client_id != client_id:
        raise HTTPException(status_code=404, detail="Call not found.")
    return whatsapp_followups.thread_for_call(db, client_id, call_id)
