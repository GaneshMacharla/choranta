from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_operator
from app.models.user import User
from app.services import call_scripts

router = APIRouter(prefix="/call-scripts", tags=["Standard Call Scripts"])


class UpdateCallScriptRequest(BaseModel):
    discovery_questions: List[str] = Field(..., description="Questions to ask, in order")
    offer_points: List[str] = Field(default_factory=list, description="Points to mention when they fit")
    next_step: str = Field(..., description="The next step to agree")


@router.get("")
def list_call_scripts(db: Session = Depends(get_db), _: User = Depends(require_operator)) -> List[Dict[str, Any]]:
    """Standard call scripts (one per template), shared by the AI employees linked to them."""
    return [call_scripts.script_out(s) for s in call_scripts.list_scripts(db)]


@router.get("/{key}")
def get_call_script(key: str, db: Session = Depends(get_db), _: User = Depends(require_operator)) -> Dict[str, Any]:
    return call_scripts.script_out(call_scripts.get_script(db, key))


@router.put("/{key}")
def update_call_script(key: str, req: UpdateCallScriptRequest, db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Edits a standard call script (admins only). Linked AI employees use it from their next publish."""
    script = call_scripts.update_script(db, key, req.discovery_questions, req.offer_points, req.next_step, admin.id)
    return call_scripts.script_out(script)
