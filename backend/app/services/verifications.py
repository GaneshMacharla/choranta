"""
Business verification (KYC) for buying phone numbers: one time per client, reviewed by a Choranta admin.

Documents are stored privately on the server (KYC_UPLOAD_DIR/<client_id>/) and only admins can download them.
"""
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ChorantaException, NotFoundException, ValidationException
from app.models.client import Client
from app.models.verification import ClientVerification
from app.services import notifications

DOCUMENT_KINDS: Dict[str, str] = {
    "pan_card": "Business PAN card",
    "gst_certificate": "GST registration certificate",
    "address_proof": "Address proof (utility bill or bank statement, under 3 months old)",
    "signatory_id": "Authorised signatory's ID (Aadhaar, passport or driving licence)",
}
REQUIRED_KINDS = ("pan_card", "address_proof", "signatory_id")  # GST certificate only when a GSTIN is given
MAX_FILE_BYTES = 5 * 1024 * 1024
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Checked by content, not by the file name
_SIGNATURES = [(b"%PDF-", "application/pdf", ".pdf"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"), (b"\xff\xd8\xff", "image/jpeg", ".jpg")]


class VerificationRequired(ChorantaException):
    def __init__(self, status: Optional[str]):
        message = {
            None: "Verify your business before buying a number. It's a one-time step required by telecom rules.",
            "PENDING": "Your business verification is under review. You can buy numbers once it's approved.",
            "REJECTED": "Your business verification needs changes. Fix it and resubmit to buy numbers.",
        }.get(status, "Verify your business before buying a number.")
        super().__init__(message, status_code=403, details={"code": "VERIFICATION_REQUIRED", "status": status})


def get(db: Session, client_id: str) -> Optional[ClientVerification]:
    return db.get(ClientVerification, client_id)


def require_approved(db: Session, client_id: str) -> None:
    v = get(db, client_id)
    if not v or v.status != "APPROVED":
        raise VerificationRequired(v.status if v else None)


def _sniff(data: bytes) -> Optional[Tuple[str, str]]:
    for magic, content_type, ext in _SIGNATURES:
        if data.startswith(magic):
            return content_type, ext
    return None


def _store(client_id: str, kind: str, filename: str, data: bytes) -> Dict[str, Any]:
    if len(data) == 0:
        raise ValidationException(f"{DOCUMENT_KINDS[kind]}: the file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ValidationException(f"{DOCUMENT_KINDS[kind]}: files must be 5 MB or smaller.")
    sniffed = _sniff(data)
    if not sniffed:
        raise ValidationException(f"{DOCUMENT_KINDS[kind]}: upload a PDF, JPG or PNG file.")
    content_type, ext = sniffed
    folder = os.path.join(settings.KYC_UPLOAD_DIR, client_id)
    os.makedirs(folder, exist_ok=True)
    stored = f"{kind}_{secrets.token_hex(8)}{ext}"
    with open(os.path.join(folder, stored), "wb") as f:
        f.write(data)
    return {"kind": kind, "filename": os.path.basename(filename or stored)[:200], "path": stored, "size": len(data),
            "content_type": content_type, "uploaded_at": datetime.now(timezone.utc).isoformat()}


def submit(db: Session, client_id: str, details: Dict[str, Any], files: Dict[str, Tuple[str, bytes]]) -> ClientVerification:
    """Saves (or resubmits) the client's verification and puts it in the review queue."""
    current = get(db, client_id)
    if current and current.status == "APPROVED":
        raise ValidationException("Your business is already verified.")
    clean = {k: " ".join(str(details.get(k) or "").split()) for k in
             ("legal_name", "pan", "gstin", "cin", "registered_address", "signatory_name", "signatory_designation", "signatory_phone")}
    clean["pan"] = clean["pan"].upper()
    clean["gstin"] = clean["gstin"].upper()
    clean["cin"] = clean["cin"].upper()
    for field, label in (("legal_name", "Registered business name"), ("registered_address", "Registered address"),
                         ("signatory_name", "Authorised signatory's name")):
        if len(clean[field]) < 3:
            raise ValidationException(f"{label} is required.")
    if not PAN_RE.match(clean["pan"]):
        raise ValidationException("Enter a valid PAN (e.g. ABCDE1234F).")
    if clean["gstin"]:
        if not GSTIN_RE.match(clean["gstin"]):
            raise ValidationException("Enter a valid 15-character GSTIN.")
        if clean["gstin"][2:12] != clean["pan"]:
            raise ValidationException("The GSTIN doesn't match the PAN (characters 3-12 of the GSTIN are the PAN).")

    unknown = set(files) - set(DOCUMENT_KINDS)
    if unknown:
        raise ValidationException("Unknown document type.")
    kept = {d["kind"]: d for d in (current.documents if current else [])}
    for kind, (filename, data) in files.items():
        kept[kind] = _store(client_id, kind, filename, data)
    required = list(REQUIRED_KINDS) + (["gst_certificate"] if clean["gstin"] else [])
    missing = [DOCUMENT_KINDS[k] for k in required if k not in kept]
    if missing:
        raise ValidationException("Please upload: " + "; ".join(missing) + ".")

    v = current or ClientVerification(client_id=client_id)
    for key, value in clean.items():
        setattr(v, key, value or None if key in ("gstin", "cin", "signatory_designation", "signatory_phone") else value)
    v.documents = list(kept.values())
    v.status = "PENDING"
    v.admin_note = None
    v.submitted_at = datetime.now(timezone.utc)
    v.reviewed_at = v.reviewed_by = None
    if not current:
        db.add(v)
    db.commit()
    return v


def review(db: Session, client_id: str, approve: bool, admin_id: str, note: Optional[str] = None) -> ClientVerification:
    v = get(db, client_id)
    if not v:
        raise NotFoundException("Business verification", client_id)
    if v.status != "PENDING":
        raise ValidationException(f"This verification is already {v.status.lower()}.")
    if not approve and not (note or "").strip():
        raise ValidationException("Tell the client what to fix.")
    v.status = "APPROVED" if approve else "REJECTED"
    v.admin_note = None if approve else note.strip()
    v.reviewed_at = datetime.now(timezone.utc)
    v.reviewed_by = admin_id
    if approve:
        notifications.notify(db, client_id, "VERIFICATION_APPROVED", "Your business is verified",
                             "You can now buy phone numbers for your AI employees.", link="/portal/numbers", level="success")
    else:
        notifications.notify(db, client_id, "VERIFICATION_REJECTED", "Business verification needs changes",
                             v.admin_note, link="/portal/verification", level="warning")
    db.commit()
    return v


def document_path(v: ClientVerification, index: int) -> Tuple[str, Dict[str, Any]]:
    docs = v.documents or []
    if not 0 <= index < len(docs):
        raise NotFoundException("Document", str(index))
    doc = docs[index]
    path = os.path.join(settings.KYC_UPLOAD_DIR, v.client_id, os.path.basename(doc["path"]))
    if not os.path.isfile(path):
        raise NotFoundException("Document file", doc["filename"])
    return path, doc


def out(db: Session, v: Optional[ClientVerification]) -> Dict[str, Any]:
    if not v:
        return {"status": "NOT_STARTED", "document_kinds": DOCUMENT_KINDS}
    client = db.get(Client, v.client_id)
    return {
        "client_id": v.client_id,
        "client_name": client.name if client else None,
        "client_code": client.client_code if client else None,
        "status": v.status,
        "legal_name": v.legal_name, "pan": v.pan, "gstin": v.gstin, "cin": v.cin,
        "registered_address": v.registered_address, "signatory_name": v.signatory_name,
        "signatory_designation": v.signatory_designation, "signatory_phone": v.signatory_phone,
        "documents": [{"index": i, "kind": d["kind"], "label": DOCUMENT_KINDS.get(d["kind"], d["kind"]),
                       "filename": d["filename"], "size": d["size"], "content_type": d["content_type"]}
                      for i, d in enumerate(v.documents or [])],
        "admin_note": v.admin_note,
        "submitted_at": v.submitted_at,
        "reviewed_at": v.reviewed_at,
        "document_kinds": DOCUMENT_KINDS,
    }


def list_all(db: Session, status: Optional[str] = None) -> List[Dict[str, Any]]:
    query = db.query(ClientVerification)
    if status:
        query = query.filter(ClientVerification.status == status)
    return [out(db, v) for v in query.order_by(ClientVerification.submitted_at.desc()).all()]
