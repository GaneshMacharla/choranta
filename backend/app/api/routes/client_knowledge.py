"""
Each client's knowledge base: notes, FAQs and uploaded documents its AI employees answer from on calls.
Admins manage it on the client's page; an AI employee can only use its own client's knowledge.
"""
import io
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_operator
from app.core.security import generate_unique_id
from app.models.client import Client
from app.models.knowledge_source import KnowledgeSource
from app.models.user import User
from app.schemas.catalog import KnowledgeSourceResponse

router = APIRouter(prefix="/clients/{client_id}/knowledge", tags=["Client Knowledge Base"])

MAX_CONTENT_CHARS = 20000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TEXT_EXTENSIONS = (".txt", ".md", ".csv")


class ClientKnowledgeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field("NOTES", pattern="^(NOTES|FAQ)$")
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_CHARS)


def _client(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    return client


def _entry(db: Session, client_id: str, knowledge_id: str) -> KnowledgeSource:
    entry = db.get(KnowledgeSource, knowledge_id)
    if not entry or entry.client_id != client_id:
        raise HTTPException(status_code=404, detail="Knowledge entry not found for this client.")
    return entry


def _extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            raise HTTPException(status_code=422, detail="Couldn't read that PDF. Try another file or paste the text.")
    if name.endswith(TEXT_EXTENSIONS):
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
    raise HTTPException(status_code=422, detail="Upload a PDF, TXT, MD or CSV file.")


@router.get("", response_model=List[KnowledgeSourceResponse])
def list_client_knowledge(client_id: str, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    _client(db, client_id)
    return (db.query(KnowledgeSource).filter(KnowledgeSource.client_id == client_id)
            .order_by(KnowledgeSource.created_at).all())


@router.post("", response_model=KnowledgeSourceResponse, status_code=201)
def create_client_knowledge(client_id: str, req: ClientKnowledgeRequest, db: Session = Depends(get_db),
                            _: User = Depends(require_operator)):
    _client(db, client_id)
    entry = KnowledgeSource(id=generate_unique_id("knw", 12), name=req.name.strip(), type=req.type, status="READY",
                            content=req.content.strip(), client_id=client_id, meta={})
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/upload", response_model=KnowledgeSourceResponse, status_code=201)
async def upload_client_knowledge(client_id: str, file: UploadFile = File(...), name: Optional[str] = Form(None),
                                  db: Session = Depends(get_db), _: User = Depends(require_operator)):
    """A document (PDF, TXT, MD, CSV) whose text becomes a knowledge entry."""
    _client(db, client_id)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="That file is over 10 MB.")
    # Tidy extracted text: PDFs often pad with spaces and leave runs of blank lines
    text = re.sub(r"[ \t]+", " ", _extract_text(file.filename or "", data))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text.strip():
        raise HTTPException(status_code=422, detail="No text found in that file (scanned PDFs need their text pasted in).")
    truncated = len(text) > MAX_CONTENT_CHARS
    entry = KnowledgeSource(
        id=generate_unique_id("knw", 12), name=(name or file.filename or "Document").strip()[:255],
        type="PDF" if (file.filename or "").lower().endswith(".pdf") else "TEXT", status="READY",
        content=text[:MAX_CONTENT_CHARS], client_id=client_id,
        meta={"file_name": file.filename, "file_size_kb": round(len(data) / 1024), "truncated": truncated},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/{knowledge_id}", response_model=KnowledgeSourceResponse)
def update_client_knowledge(client_id: str, knowledge_id: str, req: ClientKnowledgeRequest,
                            db: Session = Depends(get_db), _: User = Depends(require_operator)):
    entry = _entry(db, client_id, knowledge_id)
    entry.name, entry.content = req.name.strip(), req.content.strip()
    if entry.type in ("NOTES", "FAQ"):
        entry.type = req.type
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{knowledge_id}", status_code=204)
def delete_client_knowledge(client_id: str, knowledge_id: str, db: Session = Depends(get_db),
                            _: User = Depends(require_operator)):
    """Deletes the entry; AI employees using it simply stop seeing it."""
    db.delete(_entry(db, client_id, knowledge_id))
    db.commit()
