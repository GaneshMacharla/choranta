"""Admin review of clients' business verification (KYC) for buying phone numbers."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_operator
from app.core.exceptions import NotFoundException
from app.models.user import User
from app.services import verifications as svc

router = APIRouter(prefix="/verifications", tags=["Business Verification"])


class RejectRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)


@router.get("")
def list_verifications(status: Optional[str] = Query(None, description="PENDING, APPROVED or REJECTED"),
                       db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return svc.list_all(db, status)


@router.get("/count")
def pending_count(db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return {"pending": len(svc.list_all(db, "PENDING"))}


@router.get("/{client_id}")
def get_verification(client_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    v = svc.get(db, client_id)
    if not v:
        raise NotFoundException("Business verification", client_id)
    return svc.out(db, v)


@router.get("/{client_id}/documents/{index}")
def download_document(client_id: str, index: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    v = svc.get(db, client_id)
    if not v:
        raise NotFoundException("Business verification", client_id)
    path, doc = svc.document_path(v, index)
    return FileResponse(path, media_type=doc["content_type"], filename=doc["filename"])


@router.post("/{client_id}/approve")
def approve(client_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return svc.out(db, svc.review(db, client_id, True, user.id))


@router.post("/{client_id}/reject")
def reject(client_id: str, req: RejectRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return svc.out(db, svc.review(db, client_id, False, user.id, req.note))
