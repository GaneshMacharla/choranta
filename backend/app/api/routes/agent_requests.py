"""
AI employee requests: clients name a new AI employee and pick a Sarvam voice in the portal; Choranta
admins build it from the "Employee requests" queue. Also serves the Sarvam voice list and previews.
"""
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_client_user, require_operator
from app.models.client import Client
from app.models.user import User
from app.services import agent_requests as svc
from app.services import sarvam_voices

portal_router = APIRouter(prefix="/portal", tags=["Client Portal"])
admin_router = APIRouter(prefix="/agent-requests", tags=["AI Employee Requests"])

ClientAccount = Tuple[User, str]


class CreateAgentRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    business_type: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=100)  # the AI employee's name
    languages: List[str] = Field(default_factory=list, max_length=12)  # first = main language
    voice_id: Optional[str] = Field(None, max_length=64)  # optional for now: admins pick the voice when building


class CompleteRequest(BaseModel):
    agent_id: str


class RejectRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)


def _preview_response(voice_id: str) -> Response:
    try:
        audio = sarvam_voices.preview_wav(voice_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except sarvam_voices.VoicePreviewUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})


# ---------------------------------------------------------------- client portal

@portal_router.get("/voices")
def portal_voices(account: ClientAccount = Depends(require_client_user)):
    return sarvam_voices.list_voices()


@portal_router.get("/voices/{voice_id}/preview")
def portal_voice_preview(voice_id: str, account: ClientAccount = Depends(require_client_user)):
    return _preview_response(voice_id)


@portal_router.get("/agent-requests/options")
def portal_request_options(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    """Choices for the "Create an AI employee" form, and the client's current details to pre-fill it."""
    _, client_id = account
    client = db.get(Client, client_id)
    return {
        "business_types": [{"id": k, "label": v} for k, v in svc.BUSINESS_TYPES.items()],
        "languages": [{"id": k, "label": v} for k, v in svc.LANGUAGES.items()],
        "company_name": client.name if client else "",
        "business_type": client.business_type if client else "OTHER",
    }


@portal_router.get("/agent-requests")
def portal_list_requests(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    return {"can_request": svc.has_paid(db, client_id), "requests": svc.list_requests(db, client_id=client_id)}


@portal_router.post("/agent-requests", status_code=201)
def portal_create_request(req: CreateAgentRequest, account: ClientAccount = Depends(require_client_user),
                          db: Session = Depends(get_db)):
    user, client_id = account
    request = svc.create_request(db, client_id, req.name, req.company_name, req.business_type, user.id,
                                 voice_id=req.voice_id, languages=req.languages)
    return svc.request_out(db, request)


@portal_router.delete("/agent-requests/{request_id}")
def portal_cancel_request(request_id: str, account: ClientAccount = Depends(require_client_user),
                          db: Session = Depends(get_db)):
    _, client_id = account
    return svc.request_out(db, svc.cancel_request(db, svc.get_request(db, request_id, client_id)))


# ---------------------------------------------------------------- Choranta admins

@admin_router.get("")
def admin_list_requests(status: Optional[str] = Query(None, description="OPEN, PENDING, IN_PROGRESS, COMPLETED, ..."),
                        client_id: Optional[str] = None, db: Session = Depends(get_db),
                        user: User = Depends(require_operator)):
    return svc.list_requests(db, client_id=client_id, status=status)


@admin_router.get("/count")
def admin_pending_count(db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return {"pending": svc.open_count(db)}


@admin_router.get("/voices/{voice_id}/preview")
def admin_voice_preview(voice_id: str, user: User = Depends(require_operator)):
    return _preview_response(voice_id)


@admin_router.get("/{request_id}")
def admin_get_request(request_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return svc.request_out(db, svc.get_request(db, request_id))


@admin_router.post("/{request_id}/start")
def admin_start_request(request_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return svc.request_out(db, svc.start_request(db, svc.get_request(db, request_id), user.id))


@admin_router.post("/{request_id}/complete")
def admin_complete_request(request_id: str, req: CompleteRequest, db: Session = Depends(get_db),
                           user: User = Depends(require_admin)):
    return svc.request_out(db, svc.complete_request(db, svc.get_request(db, request_id), req.agent_id, user.id))


@admin_router.post("/{request_id}/reject")
def admin_reject_request(request_id: str, req: RejectRequest, db: Session = Depends(get_db),
                         user: User = Depends(require_admin)):
    return svc.request_out(db, svc.reject_request(db, svc.get_request(db, request_id), req.note, user.id))
