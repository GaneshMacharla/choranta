"""Staff view of clients' business verification (KYC). Vobiz does the verifying; staff can only see and re-check."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_operator
from app.core.exceptions import NotFoundException
from app.models.user import User
from app.services import verifications as svc

router = APIRouter(prefix="/verifications", tags=["Business Verification"])


@router.get("")
def list_verifications(status: Optional[str] = Query(None, description="IN_PROGRESS or VERIFIED"),
                       db: Session = Depends(get_db), user: User = Depends(require_operator)):
    return svc.list_all(db, status)


@router.get("/{client_id}")
def get_verification(client_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    v = svc.get(db, client_id)
    if not v:
        raise NotFoundException("Business verification", client_id)
    return svc.out(db, v)


@router.post("/{client_id}/refresh")
def refresh_verification(client_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    """Re-reads the client's KYC from Vobiz."""
    return svc.out(db, svc.refresh(db, client_id))
