"""
Each client's knowledge base: business details, uploaded documents, notes and FAQs its AI employees answer from.
Stored in MongoDB (app/services/knowledge_store.py). Only the client adds to it, in the portal. Choranta's team
reviews it on the client's page and the AI employee's Build tab: checks the gaps, downloads documents and deletes
what's wrong.
An AI employee can only use its own client's knowledge.
"""
from typing import Any, Dict, List, NamedTuple, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user, require_operator
from app.core.config import settings
from app.db import mongo
from app.models.agent import Agent
from app.models.client import Client
from app.models.user import User
from app.schemas.catalog import KnowledgeSourceResponse
from app.services import knowledge_store as store

router = APIRouter(prefix="/clients/{client_id}/knowledge", tags=["Client Knowledge Base"])
portal_router = APIRouter(prefix="/portal/knowledge", tags=["Client Portal"])


class ClientKnowledgeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field("NOTES", pattern="^(NOTES|FAQ)$")
    content: str = Field(..., min_length=1, max_length=store.MAX_CONTENT_CHARS)


class DetailValue(BaseModel):
    value: str = Field("", max_length=2000)
    in_documents: bool = False


class DetailsRequest(BaseModel):
    fields: Dict[str, DetailValue]


class Scope(NamedTuple):
    client: Client
    actor: Dict[str, str]


def _require_store() -> None:
    try:
        mongo.database()
    except mongo.KnowledgeStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def admin_scope(client_id: str, user: User = Depends(require_operator), db: Session = Depends(get_db)) -> Scope:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    _require_store()
    return Scope(client, store._actor("TEAM", user.name or user.email))


def portal_scope(account: Tuple[User, str] = Depends(require_client_user), db: Session = Depends(get_db)) -> Scope:
    user, client_id = account
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    _require_store()
    return Scope(client, store._actor("CLIENT", user.name or user.email))


def _agent_ids(db: Session, client_id: str) -> List[str]:
    """New knowledge is ticked for all the client's AI employees; the team can untick it per employee."""
    return [row.id for row in db.query(Agent.id).filter(Agent.client_id == client_id).all()]


def _out(entry: Any) -> Dict[str, Any]:
    return KnowledgeSourceResponse.model_validate(entry).model_dump(mode="json")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except store.KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _register_review(r: APIRouter, scope_dep) -> None:
    """Reading and deleting: the portal and the admin client page alike."""

    @r.get("", response_model=List[KnowledgeSourceResponse])
    def list_knowledge(scope: Scope = Depends(scope_dep)):
        return store.list_entries(scope.client.id)

    @r.get("/overview")
    def knowledge_overview(scope: Scope = Depends(scope_dep)) -> Dict[str, Any]:
        """The details sheet with its gaps, every entry, and document storage used."""
        data = store.overview(scope.client.id, scope.client.business_type)
        return {**data, "business_type": scope.client.business_type, "entries": [_out(e) for e in data["entries"]]}

    @r.get("/{knowledge_id}/download")
    def download_knowledge(knowledge_id: str, scope: Scope = Depends(scope_dep)):
        name, mime, data = _call(store.download, scope.client.id, knowledge_id)
        disposition = f"attachment; filename*=UTF-8''{quote(name)}"
        return Response(content=data, media_type=mime, headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store"})

    @r.delete("/{knowledge_id}", status_code=204)
    def delete_knowledge(knowledge_id: str, scope: Scope = Depends(scope_dep)):
        """Deletes the entry and its stored file from the database."""
        _call(store.delete_entry, scope.client.id, knowledge_id)


def _register_additions(r: APIRouter, scope_dep) -> None:
    """Adding and editing knowledge: the client, in the portal."""

    @r.put("/details", response_model=KnowledgeSourceResponse)
    def save_details(req: DetailsRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        values = {k: v.model_dump() for k, v in req.fields.items()}
        return store.save_details(scope.client.id, scope.client.business_type, values,
                                  _agent_ids(db, scope.client.id), scope.actor)

    @r.post("", response_model=KnowledgeSourceResponse, status_code=201)
    def create_knowledge(req: ClientKnowledgeRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        return _call(store.create_note, scope.client.id, req.type, req.name, req.content,
                     _agent_ids(db, scope.client.id), scope.actor)

    @r.post("/upload", response_model=List[KnowledgeSourceResponse], status_code=201)
    async def upload_knowledge(files: List[UploadFile] = File(...), scope: Scope = Depends(scope_dep),
                               db: Session = Depends(get_db)):
        """Any number of documents of any type. Text is read from PDF, Word, Excel and text files."""
        limit = 1024 * 1024 * settings.KNOWLEDGE_MAX_FILE_MB
        read = []
        for f in files:
            data = await f.read(limit + 1)  # one byte over the limit is enough to refuse it
            read.append((f.filename or "Document", f.content_type or "", data))
        return _call(store.upload_documents, scope.client.id, read, _agent_ids(db, scope.client.id), scope.actor)

    @r.put("/{knowledge_id}", response_model=KnowledgeSourceResponse)
    def update_knowledge(knowledge_id: str, req: ClientKnowledgeRequest, scope: Scope = Depends(scope_dep)):
        return _call(store.update_entry, scope.client.id, knowledge_id, req.name, req.content, req.type)


_register_review(router, admin_scope)
_register_review(portal_router, portal_scope)
_register_additions(portal_router, portal_scope)
