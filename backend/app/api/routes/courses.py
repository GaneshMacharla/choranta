"""
Course catalogue for coaching centres: the centre adds courses and batches in the client portal, Choranta's team
manages the same catalogue on the client's page. Both write through app/services/courses.py, which records history.
"""
from datetime import date
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user, require_operator
from app.models.client import Client
from app.models.user import User
from app.services import courses as svc

portal_router = APIRouter(prefix="/portal/courses", tags=["Client Portal"])
admin_router = APIRouter(prefix="/clients/{client_id}/courses", tags=["Course Catalogue"])

COACHING = "COACHING"
Mode = Literal["ONLINE", "CLASSROOM", "BOTH"]


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    aliases: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=64)
    audience: Optional[str] = Field(None, max_length=1000)
    eligibility: Optional[str] = Field(None, max_length=1000)
    duration: str = Field(..., min_length=1, max_length=64)
    mode: Mode
    medium: Optional[str] = Field(None, max_length=128)
    fee: str = Field(..., min_length=1, max_length=64)
    instalments: Optional[str] = Field(None, max_length=500)
    highlights: Optional[str] = Field(None, max_length=2000)
    certificate: Optional[bool] = None
    extra_details: Optional[str] = Field(None, max_length=2000)
    sort_order: Optional[int] = None


class CourseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    aliases: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=64)
    audience: Optional[str] = Field(None, max_length=1000)
    eligibility: Optional[str] = Field(None, max_length=1000)
    duration: Optional[str] = Field(None, max_length=64)
    mode: Optional[Mode] = None
    medium: Optional[str] = Field(None, max_length=128)
    fee: Optional[str] = Field(None, max_length=64)
    instalments: Optional[str] = Field(None, max_length=500)
    highlights: Optional[str] = Field(None, max_length=2000)
    certificate: Optional[bool] = None
    extra_details: Optional[str] = Field(None, max_length=2000)
    sort_order: Optional[int] = None
    status: Optional[Literal["ACTIVE", "HIDDEN"]] = None


class BatchCreate(BaseModel):
    start_date: date
    timings: str = Field(..., min_length=1, max_length=255)
    mode: Optional[Mode] = None
    medium: Optional[str] = Field(None, max_length=128)
    seats: Literal["OPEN", "FULL"] = "OPEN"


class BatchUpdate(BaseModel):
    start_date: Optional[date] = None
    timings: Optional[str] = Field(None, max_length=255)
    mode: Optional[Mode] = None
    medium: Optional[str] = Field(None, max_length=128)
    seats: Optional[Literal["OPEN", "FULL"]] = None


class Scope(NamedTuple):
    client_id: str
    actor: svc.Actor


def portal_scope(account: Tuple[User, str] = Depends(require_client_user), db: Session = Depends(get_db)) -> Scope:
    user, client_id = account
    client = db.get(Client, client_id)
    if not client or client.business_type != COACHING:
        raise HTTPException(status_code=403, detail="Courses are available for coaching and training centres.")
    return Scope(client_id, ("CLIENT", user.name or user.email))


def admin_scope(client_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> Scope:
    if not db.get(Client, client_id):
        raise HTTPException(status_code=404, detail="Client not found.")
    return Scope(client_id, ("TEAM", user.name or user.email))


def _register(router: APIRouter, scope_dep) -> None:
    """The same catalogue endpoints for the portal and the admin client page; only who may call them differs."""

    @router.get("")
    def list_courses(scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)) -> Dict[str, Any]:
        return svc.catalogue(db, scope.client_id)

    @router.get("/changes")
    def list_changes(limit: int = Query(50, ge=1, le=200), scope: Scope = Depends(scope_dep),
                     db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
        return svc.recent_changes(db, scope.client_id, limit)

    @router.post("", status_code=201)
    def create_course(req: CourseCreate, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)) -> Dict[str, Any]:
        return svc.create_course(db, scope.client_id, req.model_dump(exclude_unset=True), scope.actor)

    @router.patch("/{course_id}")
    def update_course(course_id: str, req: CourseUpdate, scope: Scope = Depends(scope_dep),
                      db: Session = Depends(get_db)) -> Dict[str, Any]:
        return svc.update_course(db, scope.client_id, course_id, req.model_dump(exclude_unset=True), scope.actor)

    @router.post("/{course_id}/batches", status_code=201)
    def add_batch(course_id: str, req: BatchCreate, scope: Scope = Depends(scope_dep),
                  db: Session = Depends(get_db)) -> Dict[str, Any]:
        return svc.add_batch(db, scope.client_id, course_id, req.model_dump(), scope.actor)

    @router.patch("/{course_id}/batches/{batch_id}")
    def update_batch(course_id: str, batch_id: str, req: BatchUpdate, scope: Scope = Depends(scope_dep),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
        return svc.update_batch(db, scope.client_id, course_id, batch_id, req.model_dump(exclude_unset=True), scope.actor)

    @router.delete("/{course_id}/batches/{batch_id}")
    def delete_batch(course_id: str, batch_id: str, scope: Scope = Depends(scope_dep),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
        return svc.delete_batch(db, scope.client_id, course_id, batch_id, scope.actor)


_register(portal_router, portal_scope)
_register(admin_router, admin_scope)
