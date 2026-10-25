"""Client portal: what makes a caller a qualified lead, per AI employee."""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user
from app.models.agent import Agent
from app.services import lead_qualification as svc

portal_router = APIRouter(prefix="/portal/qualification", tags=["Client Portal"])


class SetupIn(BaseModel):
    rules: List[List[Any]] = Field(default_factory=list)
    ai_criteria: Optional[str] = Field(None, max_length=2000)


def _raise(exc: svc.QualificationError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@portal_router.get("")
def list_setups(account=Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    agents = db.query(Agent).filter(Agent.client_id == client_id).order_by(Agent.name).all()
    return [svc.setup_out(db, a) for a in agents]


@portal_router.put("/{agent_id}")
def save_setup(agent_id: str, body: SetupIn, account=Depends(require_client_user), db: Session = Depends(get_db)):
    user, client_id = account
    try:
        svc.save_setup(db, client_id, agent_id, body.rules, body.ai_criteria, user_id=user.id)
    except svc.QualificationError as exc:
        _raise(exc)
    return svc.setup_out(db, db.get(Agent, agent_id))


@portal_router.post("/{agent_id}/reevaluate")
def reevaluate(agent_id: str, account=Depends(require_client_user), db: Session = Depends(get_db)):
    """Re-checks the last 30 days of this AI employee's calls against the current rules."""
    _, client_id = account
    try:
        changed = svc.reevaluate(db, client_id, agent_id)
    except svc.QualificationError as exc:
        _raise(exc)
    return {"changed": changed, "days": svc.REEVALUATE_DAYS}
