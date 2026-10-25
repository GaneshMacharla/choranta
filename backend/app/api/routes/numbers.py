"""
Number management for Choranta staff: search the carrier's inventory, buy, assign to clients, sync and release.
Buying, releasing and syncing are admin-only and rate limited; operators can browse, assign and unassign.
Clients never reach these routes (they buy through /portal/numbers, scoped to their own account).
Errors come back as {detail, code, operation?}; the operation is the audit record of what was attempted.
"""
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_operator
from app.core import rate_limit
from app.core.config import settings
from app.models.numbers import NumberOperation
from app.models.user import User
from app.services import number_assignments, number_reconciliation
from app.services import number_service as svc

router = APIRouter(prefix="/numbers", tags=["Number Management"])

InternalStatus = Literal["AVAILABLE", "ASSIGNED", "RELEASING", "RELEASED", "NEEDS_RECONCILIATION"]


class PurchaseRequest(BaseModel):
    e164: str = Field(..., min_length=8, max_length=20)
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    confirm: bool = Field(..., description="Must be true: buying debits Choranta's Vobiz balance")
    expected_monthly_cost: Optional[float] = Field(None, ge=0)
    expected_setup_cost: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)


class AssignRequest(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=64)
    agent_id: Optional[str] = Field(None, max_length=64)
    trunk_id: Optional[str] = Field(None, max_length=128)


class ReleaseRequest(BaseModel):
    confirm_e164: str = Field(..., min_length=8, max_length=20)
    idempotency_key: str = Field(..., min_length=8, max_length=128)


def _error(exc: svc.NumberServiceError) -> JSONResponse:
    body: Dict[str, Any] = {"detail": exc.message, "code": exc.code}
    if exc.operation is not None:
        body["operation"] = svc.operation_out(exc.operation)
    if exc.details:
        body["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=_jsonable(body))


def _jsonable(value: Any) -> Any:
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(value)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.NumberServiceError as exc:
        return _error(exc)


def _with_number(db: Session, op: NumberOperation) -> Dict[str, Any]:
    pn = db.get(svc.ProviderNumber, op.provider_number_id) if op.provider_number_id else None
    return {"operation": svc.operation_out(op), "number": svc.number_out(db, pn) if pn else None}


@router.get("/provider-status")
def provider_status(db: Session = Depends(get_db), _: User = Depends(require_operator)):
    """Mock or real carrier, whether it's configured, and Choranta's balance there."""
    return svc.provider_status(db)


@router.get("/inventory")
def inventory(country: Optional[str] = Query("IN", min_length=2, max_length=2), search: Optional[str] = Query(None, max_length=20),
              number_type: Optional[Literal["Landline", "Mobile", "TollFree"]] = None,
              region: Optional[str] = Query(None, max_length=64),
              page: int = Query(1, ge=1, le=1000), per_page: int = Query(25, ge=1, le=100),
              db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return _run(svc.search_inventory, db, country=country, search=search, number_type=number_type, region=region,
                page=page, per_page=per_page)


@router.get("")
def list_numbers(status: Optional[InternalStatus] = None, client_id: Optional[str] = Query(None, max_length=64),
                 search: Optional[str] = Query(None, max_length=20),
                 capability: Optional[Literal["voice", "sms", "mms", "fax"]] = None,
                 page: int = Query(1, ge=1, le=1000), per_page: int = Query(25, ge=1, le=100),
                 db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return svc.list_numbers(db, status=status, client_id=client_id, search=search, capability=capability,
                            page=page, per_page=per_page)


@router.get("/operations")
def list_operations(status: Optional[str] = Query(None, max_length=32), operation_type: Optional[str] = Query(None, max_length=32),
                    e164: Optional[str] = Query(None, max_length=20),
                    page: int = Query(1, ge=1, le=1000), per_page: int = Query(50, ge=1, le=100),
                    db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return svc.list_operations(db, status=status, operation_type=operation_type, e164=e164, page=page, per_page=per_page)


@router.get("/trunks")
def list_trunks(db: Session = Depends(get_db), _: User = Depends(require_operator)):
    """SIP trunks on Choranta's carrier account (optional when assigning a number)."""
    try:
        with svc.carrier(db) as provider:
            return [{"id": t.id, "name": t.name} for t in provider.list_trunks()]
    except svc.NumberProviderError as exc:
        return _error(svc._fail(exc))


@router.post("/purchase")
def purchase(req: PurchaseRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Buys a number into Choranta's pool. The operation's status says whether it's bought, uncertain or failed."""
    if not req.confirm:
        return _error(svc.NumberServiceError(400, "confirmation_required", "Confirm the purchase: it debits Choranta's Vobiz balance."))
    rate_limit.check(user.id, "purchase", settings.NUMBER_PURCHASES_PER_HOUR)
    result = _run(svc.purchase, db, req.e164, idempotency_key=req.idempotency_key, actor=svc.Actor.of(user),
                  currency=req.currency, expected_monthly_cost=req.expected_monthly_cost,
                  expected_setup_cost=req.expected_setup_cost)
    return result if isinstance(result, JSONResponse) else _with_number(db, result)


@router.post("/sync")
def sync(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Reads every number Choranta owns at the carrier and lines up the records here."""
    rate_limit.check(user.id, "sync", settings.NUMBER_SYNCS_PER_HOUR)
    return _run(number_reconciliation.sync, db, svc.Actor.of(user))


@router.post("/operations/{operation_id}/reconcile")
def reconcile(operation_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Settles an uncertain purchase or release by checking the carrier (never repeats it)."""
    op = db.get(NumberOperation, operation_id)
    if not op:
        return _error(svc.NumberServiceError(404, "not_found", "Operation not found."))
    result = _run(number_reconciliation.reconcile_operation, db, op, None, svc.Actor.of(user))
    return result if isinstance(result, JSONResponse) else _with_number(db, result)


@router.get("/{number_id}")
def get_number(number_id: str, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    result = _run(svc.get_number, db, number_id)
    return result if isinstance(result, JSONResponse) else svc.number_out(db, result, detail=True)


@router.post("/{number_id}/assign")
def assign(number_id: str, req: AssignRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    result = _run(number_assignments.assign, db, number_id, client_id=req.client_id, agent_id=req.agent_id or None,
                  trunk_id=req.trunk_id or None, actor=svc.Actor.of(user))
    return result if isinstance(result, JSONResponse) else svc.number_out(db, svc.get_number(db, number_id), detail=True)


@router.post("/{number_id}/unassign")
def unassign(number_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    result = _run(number_assignments.unassign, db, number_id, actor=svc.Actor.of(user))
    return result if isinstance(result, JSONResponse) else svc.number_out(db, result, detail=True)


@router.post("/{number_id}/release")
def release(number_id: str, req: ReleaseRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Gives the number back to the carrier (a release fee may apply). It must be unassigned first."""
    rate_limit.check(user.id, "release", settings.NUMBER_RELEASES_PER_HOUR)
    result = _run(svc.release, db, number_id, confirm_e164=req.confirm_e164, idempotency_key=req.idempotency_key,
                  actor=svc.Actor.of(user))
    return result if isinstance(result, JSONResponse) else _with_number(db, result)
