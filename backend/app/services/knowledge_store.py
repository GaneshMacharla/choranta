"""
Each client's knowledge base, stored in MongoDB (app/db/mongo.py).

Clients fill it in the portal, Choranta's team on the client's page; both go through here:
- Business details: the fields every business of its type should give (address, owner, hours...), one sheet per
  client. A field can be typed in, or marked as covered by an uploaded document. Empty ones are the gaps.
- Documents: any file, any number, kept as uploaded. They're for Choranta's team to read while building the
  client's AI employees, never read by an AI employee itself: the team writes what an employee needs to know into
  its own knowledge (Build tab).
- Notes and FAQs typed in directly.

AI employees read the notes and details ticked for them (agent_ids), the same way SQL knowledge sources are attached.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.core.security import generate_unique_id
from app.db import mongo

MAX_CONTENT_CHARS = 20000
MAX_FILES_PER_UPLOAD = 20
NOTE_TYPES = ("NOTES", "FAQ")
DOCUMENT = "DOCUMENT"
DETAILS = "DETAILS"


class KnowledgeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ------------------------------------------------------------------
# Required business details, per business type
# ------------------------------------------------------------------

def _f(key: str, label: str, hint: str, required: bool = True) -> Dict[str, Any]:
    return {"key": key, "label": label, "hint": hint, "required": required}


COMMON_FIELDS = [
    _f("business_name", "Business name", "As callers know it, e.g. Smile Dental Care"),
    _f("owner", "Owner / contact person", "Name and role, e.g. Dr. Ravi Kumar (founder)"),
    _f("phone", "Contact phone number", "The number callers can be given"),
    _f("address", "Full address & landmark", "Street, area, city, PIN and a nearby landmark"),
    _f("hours", "Working days & hours", "e.g. Mon-Sat 10am-8pm, closed Sundays"),
    _f("services", "Services / products & prices", "What you offer and what it costs"),
    _f("policies", "Payment, cancellation & refund policy", "Payment modes, refunds, cancellations", required=False),
    _f("website", "Website / social links", "So callers can look you up", required=False),
]

INDUSTRY_FIELDS: Dict[str, List[Dict[str, Any]]] = {
    "CLINIC": [
        _f("doctors", "Doctors, specialities & timings", "Who sees patients and when"),
        _f("consultation_fee", "Consultation fees", "First visit and follow-up"),
        _f("appointments", "How appointments are booked", "Walk-in, call, online; how far ahead"),
    ],
    "HOSPITAL": [
        _f("departments", "Departments & specialists", "Which departments and who heads them"),
        _f("emergency", "Emergency & ambulance contact", "24x7 number and what counts as an emergency"),
        _f("insurance", "Insurance & cashless", "Insurers and TPAs accepted", required=False),
    ],
    "SALON": [
        _f("staff", "Stylists / staff", "Who works there and their speciality", required=False),
        _f("booking", "Booking & walk-ins", "Appointment rules, walk-ins, late arrivals"),
        _f("packages", "Packages & memberships", "Bridal, monthly, combo offers", required=False),
    ],
    "REAL_ESTATE": [
        _f("projects", "Projects & locations", "Each project and where it is"),
        _f("configurations", "Configurations & price ranges", "e.g. 2 BHK 1,150 sq ft from Rs 85 lakh"),
        _f("site_visits", "Site visits", "Timings and how to book one"),
        _f("approvals", "Approvals & loan tie-ups", "RERA number, banks", required=False),
    ],
    "HOTEL": [
        _f("rooms", "Room types & rates", "Each room type and its tariff"),
        _f("check_in", "Check-in & check-out times", "Including early check-in rules"),
        _f("amenities", "Amenities", "Pool, parking, restaurant, Wi-Fi", required=False),
        _f("cancellation", "Booking & cancellation policy", "Advance, refunds"),
    ],
    "RESTAURANT": [
        _f("menu", "Menu highlights & price range", "Popular dishes, veg/non-veg, cost for two"),
        _f("reservations", "Table booking", "How to reserve, large groups"),
        _f("delivery", "Delivery & takeaway", "Areas, apps, minimum order", required=False),
    ],
    "CORPORATE": [
        _f("teams", "Who handles which enquiry", "Sales, support, billing contacts"),
    ],
    "COACHING": [
        _f("courses", "Courses, fees & duration", "Also kept on the Courses page"),
        _f("batches", "Batch timings & start dates", "Also kept on the Courses page"),
        _f("demo", "Demo class", "Whether there is one and how to book it", required=False),
    ],
}


def required_fields(business_type: Optional[str]) -> List[Dict[str, Any]]:
    """The details sheet for a business type: common fields first, then the industry's own."""
    return COMMON_FIELDS[:6] + INDUSTRY_FIELDS.get((business_type or "").upper(), []) + COMMON_FIELDS[6:]


# ------------------------------------------------------------------
# Entries
# ------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    # MongoDB returns naive UTC datetimes
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class StoredKnowledge:
    """A knowledge entry shaped like the SQL KnowledgeSource, so callers and responses treat both alike."""
    id: str
    name: str
    type: str
    client_id: str
    content: str = ""
    agent_ids: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    status: str = "READY"
    description: Optional[str] = None
    owner_agent_id: Optional[str] = None

    @classmethod
    def from_doc(cls, doc: Dict[str, Any]) -> "StoredKnowledge":
        meta = {k: doc[k] for k in ("file", "text_status", "fields", "added_by") if doc.get(k) is not None}
        if doc.get("file"):
            meta["file_name"] = doc["file"].get("name")
        return cls(id=doc["_id"], name=doc.get("title", ""), type=doc.get("type", "NOTES"), client_id=doc["client_id"],
                   content=doc.get("content") or "", agent_ids=list(doc.get("agent_ids") or []), meta=meta,
                   created_at=_aware(doc.get("created_at")), updated_at=_aware(doc.get("updated_at")))


def _entries():
    return mongo.database()[mongo.ENTRIES]


def _files():
    return mongo.database()[mongo.FILES]


def _actor(role: str, name: str) -> Dict[str, str]:
    return {"role": role, "name": name}


def has_documents(client_id: str) -> bool:
    """Whether the client has uploaded at least one file."""
    return _entries().count_documents({"client_id": client_id, "type": DOCUMENT}, limit=1) > 0


def list_entries(client_id: str) -> List[StoredKnowledge]:
    return [StoredKnowledge.from_doc(d) for d in _entries().find({"client_id": client_id}).sort("created_at", 1)]


def get_entry(entry_id: str) -> Optional[StoredKnowledge]:
    if not mongo.configured() or not entry_id:
        return None
    doc = _entries().find_one({"_id": entry_id})
    return StoredKnowledge.from_doc(doc) if doc else None


def own_entry(client_id: str, entry_id: str) -> StoredKnowledge:
    entry = get_entry(entry_id)
    if not entry or entry.client_id != client_id:
        raise KnowledgeError("Knowledge entry not found for this client.", 404)
    return entry


def existing_ids(ids: Iterable[str]) -> set:
    ids = [i for i in ids if i]
    if not ids or not mongo.configured():
        return set()
    return {d["_id"] for d in _entries().find({"_id": {"$in": ids}}, {"_id": 1})}


def entries_by_ids(ids: Iterable[str]) -> List[StoredKnowledge]:
    ids = [i for i in ids if i]
    if not ids or not mongo.configured():
        return []
    return [StoredKnowledge.from_doc(d) for d in
            _entries().find({"_id": {"$in": ids}, "type": {"$ne": DOCUMENT}}).sort("created_at", 1)]


def entries_for_agent(agent_id: str) -> List[StoredKnowledge]:
    if not agent_id or not mongo.configured():
        return []
    # Documents are for the team only: one ticked before that rule is still never given to an AI employee
    return [StoredKnowledge.from_doc(d) for d in
            _entries().find({"agent_ids": agent_id, "type": {"$ne": DOCUMENT}}).sort("created_at", 1)]


def attach(agent_id: str, entry_id: str) -> None:
    _entries().update_one({"_id": entry_id}, {"$addToSet": {"agent_ids": agent_id}})


def detach(agent_id: str, entry_id: str) -> None:
    _entries().update_one({"_id": entry_id}, {"$pull": {"agent_ids": agent_id}})


def forget_agent(agent_id: str) -> None:
    """A deleted AI employee is taken off every entry it used."""
    if mongo.configured():
        _entries().update_many({"agent_ids": agent_id}, {"$pull": {"agent_ids": agent_id}})


def _insert(client_id: str, type_: str, title: str, content: str, agent_ids: List[str], added_by: Dict[str, str],
            **extra: Any) -> StoredKnowledge:
    now = _now()
    doc = {"_id": generate_unique_id("knw", 12), "client_id": client_id, "type": type_, "title": title[:255],
           "content": content, "agent_ids": agent_ids, "added_by": added_by, "created_at": now, "updated_at": now, **extra}
    _entries().insert_one(doc)
    return StoredKnowledge.from_doc(doc)


def create_note(client_id: str, type_: str, title: str, content: str, agent_ids: List[str],
                added_by: Dict[str, str]) -> StoredKnowledge:
    if type_ not in NOTE_TYPES:
        raise KnowledgeError("Choose Notes or FAQ.")
    return _insert(client_id, type_, title.strip(), content.strip()[:MAX_CONTENT_CHARS], agent_ids, added_by)


def update_entry(client_id: str, entry_id: str, title: str, content: str, type_: Optional[str] = None) -> StoredKnowledge:
    """Notes and FAQs change title, text and type; a document's title and its read text can be corrected."""
    entry = own_entry(client_id, entry_id)
    if entry.type == DETAILS:
        raise KnowledgeError("Business details are edited field by field.")
    changes: Dict[str, Any] = {"title": title.strip()[:255], "content": content.strip()[:MAX_CONTENT_CHARS], "updated_at": _now()}
    if entry.type in NOTE_TYPES and type_ in NOTE_TYPES:
        changes["type"] = type_
    _entries().update_one({"_id": entry_id}, {"$set": changes})
    return own_entry(client_id, entry_id)


def delete_entry(client_id: str, entry_id: str) -> None:
    """Deletes the entry and its stored file; AI employees using it simply stop seeing it."""
    own_entry(client_id, entry_id)
    _files().delete_many({"entry_id": entry_id})
    _entries().delete_one({"_id": entry_id})


# ------------------------------------------------------------------
# Documents
# ------------------------------------------------------------------

def _used_bytes(client_id: str) -> int:
    return sum(d.get("size_bytes", 0) for d in _files().find({"client_id": client_id}, {"size_bytes": 1}))


def upload_documents(client_id: str, files: List[Tuple[str, str, bytes]], added_by: Dict[str, str]) -> List[StoredKnowledge]:
    """Stores each (filename, mime type, bytes) as a document entry plus its original file. Nothing is read from it."""
    if not files:
        raise KnowledgeError("Choose at least one file.")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise KnowledgeError(f"Upload up to {MAX_FILES_PER_UPLOAD} files at a time.")
    limit = settings.KNOWLEDGE_MAX_FILE_MB * 1024 * 1024
    for name, _, data in files:
        if not data:
            raise KnowledgeError(f"{name} is empty.", 422)
        if len(data) > limit:
            raise KnowledgeError(f"{name} is over {settings.KNOWLEDGE_MAX_FILE_MB} MB.", 413)
    quota = settings.KNOWLEDGE_CLIENT_QUOTA_MB * 1024 * 1024
    if _used_bytes(client_id) + sum(len(d) for _, _, d in files) > quota:
        raise KnowledgeError(f"This would go over the {settings.KNOWLEDGE_CLIENT_QUOTA_MB} MB of document storage. "
                             "Delete documents you no longer need first.", 413)

    stored = []
    for name, mime, data in files:
        name = (name or "Document").replace("\\", "/").split("/")[-1][:255] or "Document"
        file_id = generate_unique_id("kfl", 12)
        entry_id = generate_unique_id("knw", 12)
        _files().insert_one({"_id": file_id, "entry_id": entry_id, "client_id": client_id, "data": data,
                             "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "created_at": _now()})
        now = _now()
        doc = {"_id": entry_id, "client_id": client_id, "type": DOCUMENT, "title": name, "content": "",
               "agent_ids": [], "added_by": added_by,
               "file": {"id": file_id, "name": name, "mime_type": mime or "application/octet-stream", "size_bytes": len(data)},
               "created_at": now, "updated_at": now}
        try:
            _entries().insert_one(doc)
        except Exception:
            _files().delete_one({"_id": file_id})
            raise
        stored.append(StoredKnowledge.from_doc(doc))
    return stored


def download(client_id: str, entry_id: str) -> Tuple[str, str, bytes]:
    """(file name, mime type, bytes) of a document's original file."""
    entry = own_entry(client_id, entry_id)
    info = entry.meta.get("file")
    blob = _files().find_one({"_id": info["id"]}) if info else None
    if not blob:
        raise KnowledgeError("This entry has no stored file.", 404)
    return info["name"], info.get("mime_type") or "application/octet-stream", bytes(blob["data"])


# ------------------------------------------------------------------
# Business details and gaps
# ------------------------------------------------------------------

def _details_doc(client_id: str) -> Optional[Dict[str, Any]]:
    return _entries().find_one({"client_id": client_id, "type": DETAILS})


def _details_text(fields: List[Dict[str, Any]], values: Dict[str, Dict[str, Any]]) -> str:
    return "\n".join(f"{f['label']}: {values[f['key']]['value']}" for f in fields
                     if (values.get(f["key"]) or {}).get("value"))


def save_details(client_id: str, business_type: Optional[str], values: Dict[str, Dict[str, Any]], agent_ids: List[str],
                 added_by: Dict[str, str]) -> StoredKnowledge:
    """Saves the details sheet ({key: {value, in_documents}}); unknown keys are dropped."""
    fields = required_fields(business_type)
    clean = {}
    for f in fields:
        given = values.get(f["key"]) or {}
        value = str(given.get("value") or "").strip()[:2000]
        clean[f["key"]] = {"value": value, "in_documents": bool(given.get("in_documents")) and not value}
    content = _details_text(fields, clean)
    existing = _details_doc(client_id)
    if existing:
        _entries().update_one({"_id": existing["_id"]}, {"$set": {"fields": clean, "content": content, "updated_at": _now()}})
        return StoredKnowledge.from_doc(_entries().find_one({"_id": existing["_id"]}))
    return _insert(client_id, DETAILS, "Business details", content, agent_ids, added_by, fields=clean)


def overview(client_id: str, business_type: Optional[str]) -> Dict[str, Any]:
    """Everything a knowledge page shows: the details sheet with its gaps, the entries, and storage used."""
    fields = required_fields(business_type)
    details = _details_doc(client_id)
    values = (details or {}).get("fields") or {}
    sheet, gaps = [], []
    for f in fields:
        v = values.get(f["key"]) or {}
        state = "FILLED" if v.get("value") else ("IN_DOCUMENTS" if v.get("in_documents") else "MISSING")
        sheet.append({**f, "value": v.get("value", ""), "in_documents": bool(v.get("in_documents")), "state": state})
        if state == "MISSING" and f["required"]:
            gaps.append(f["label"])
    entries = [e for e in list_entries(client_id) if e.type != DETAILS]
    return {
        "fields": sheet,
        "gaps": gaps,
        "details_id": details["_id"] if details else None,
        "entries": entries,
        "storage": {"used_bytes": _used_bytes(client_id), "quota_bytes": settings.KNOWLEDGE_CLIENT_QUOTA_MB * 1024 * 1024,
                    "max_file_bytes": settings.KNOWLEDGE_MAX_FILE_MB * 1024 * 1024},
    }


# ------------------------------------------------------------------
# Moving older SQL knowledge in
# ------------------------------------------------------------------

def migrate_sql_client_knowledge(db: Any) -> int:
    """
    Client knowledge written before MongoDB moves here once, keeping its id (so AI employees' settings and
    published versions still point at it) and the AI employees it was ticked for. Library and per-agent
    entries stay in SQL.
    """
    from app.models.knowledge_source import KnowledgeSource, agent_knowledge_sources
    rows = (db.query(KnowledgeSource)
            .filter(KnowledgeSource.client_id.isnot(None), KnowledgeSource.owner_agent_id.is_(None)).all())
    moved = 0
    for row in rows:
        if not _entries().find_one({"_id": row.id}):
            agents = [r.agent_id for r in db.query(agent_knowledge_sources.c.agent_id)
                      .filter(agent_knowledge_sources.c.knowledge_source_id == row.id).all()]
            meta = row.meta or {}
            doc = {"_id": row.id, "client_id": row.client_id, "type": row.type if row.type in NOTE_TYPES else DOCUMENT,
                   "title": row.name, "content": row.content or "", "agent_ids": agents,
                   "added_by": _actor("TEAM", "Choranta"), "created_at": row.created_at, "updated_at": row.updated_at}
            if doc["type"] == DOCUMENT:
                # The original file was never kept, only its text
                doc["text_status"] = "TRUNCATED" if meta.get("truncated") else "READ"
                if meta.get("file_name"):
                    doc["title"] = row.name or meta["file_name"]
            _entries().insert_one(doc)
        db.delete(row)
        moved += 1
    if moved:
        db.commit()
    return moved
