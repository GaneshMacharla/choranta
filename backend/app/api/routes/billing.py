from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_operator
from app.core.security import generate_unique_id
from app.models.billing import ClientBillingProfile, ClientUser, Invoice, WalletTransaction
from app.models.client import Client
from app.models.user import User
from app.services import billing, subscriptions
from app.services.invoice_pdf import render_invoice_pdf

router = APIRouter(tags=["Billing"])


class BillingProfileRequest(BaseModel):
    legal_name: str = Field(..., min_length=1, max_length=255)
    gstin: Optional[str] = Field(None, max_length=15)
    address: Optional[str] = None
    state_code: Optional[str] = Field(None, pattern=r"^\d{2}$", description="2-digit GST state code")
    billing_email: Optional[EmailStr] = None


class PaymentRequest(BaseModel):
    amount_received_inr: float = Field(..., gt=0, description="Total received from the client, GST included")
    reference: Optional[str] = Field(None, max_length=255, description="UTR / UPI reference")


class AdjustmentRequest(BaseModel):
    amount_inr: float = Field(..., description="Positive to credit, negative to debit")
    note: str = Field(..., min_length=1)


class WalletSettingsRequest(BaseModel):
    low_balance_threshold_inr: float = Field(..., ge=0)


class ClientLoginRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None


def _client_or_404(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found.")
    return client


def transaction_out(t: WalletTransaction) -> Dict[str, Any]:
    return {
        "id": t.id,
        "type": t.type,
        "amount_inr": t.amount_inr,
        "balance_after_inr": t.balance_after_inr,
        "call_id": t.call_id,
        "invoice_id": t.invoice_id,
        "reference": t.reference,
        "note": t.note,
        "created_at": t.created_at,
    }


def invoice_out(i: Invoice) -> Dict[str, Any]:
    return {
        "id": i.id,
        "number": i.number,
        "issue_date": i.issue_date,
        "taxable_inr": i.taxable_inr,
        "cgst_inr": i.cgst_inr,
        "sgst_inr": i.sgst_inr,
        "igst_inr": i.igst_inr,
        "total_inr": i.total_inr,
        "payment_reference": i.payment_reference,
        "description": i.description or "Prepaid usage credit",
    }


def wallet_out(db: Session, client_id: str, limit: int = 100) -> Dict[str, Any]:
    wallet = billing.get_wallet(db, client_id)
    db.commit()
    txns = (
        db.query(WalletTransaction).filter(WalletTransaction.client_id == client_id)
        .order_by(WalletTransaction.created_at.desc()).limit(limit).all()
    )
    allowed, reason, _ = billing.check_call_allowed(db, client_id)
    out = {
        "client_id": client_id,
        "balance_inr": wallet.balance_inr,
        "low_balance_threshold_inr": wallet.low_balance_threshold_inr,
        "low_balance": wallet.balance_inr <= wallet.low_balance_threshold_inr,
        "calls_blocked": not allowed,
        "calls_blocked_reason": reason,
        "subscription": subscriptions.subscription_out(db, client_id),
        "transactions": [transaction_out(t) for t in txns],
    }
    db.commit()  # persist a subscription status change worked out on read
    return out


def invoice_pdf_response(invoice: Invoice) -> Response:
    filename = invoice.number.replace("/", "-") + ".pdf"
    return Response(
        content=render_invoice_pdf(invoice),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------- billing profile

@router.get("/clients/{client_id}/billing-profile")
def get_billing_profile(client_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_operator)):
    client = _client_or_404(db, client_id)
    profile = db.get(ClientBillingProfile, client_id)
    if not profile:
        return {"legal_name": client.name, "gstin": None, "address": None, "state_code": None, "billing_email": client.contact_email}
    return {"legal_name": profile.legal_name, "gstin": profile.gstin, "address": profile.address,
            "state_code": profile.state_code, "billing_email": profile.billing_email}


@router.put("/clients/{client_id}/billing-profile")
def put_billing_profile(client_id: str, req: BillingProfileRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    profile = db.get(ClientBillingProfile, client_id) or ClientBillingProfile(client_id=client_id)
    profile.legal_name = req.legal_name.strip()
    profile.gstin = (req.gstin or "").strip().upper() or None
    profile.address = (req.address or "").strip() or None
    profile.state_code = req.state_code
    profile.billing_email = req.billing_email
    db.add(profile)
    db.commit()
    return get_billing_profile(client_id, db, current_user)


# ---------------------------------------------------------------- wallet

@router.get("/clients/{client_id}/wallet")
def get_client_wallet(client_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_operator)):
    _client_or_404(db, client_id)
    return wallet_out(db, client_id)


@router.put("/clients/{client_id}/wallet")
def update_wallet_settings(client_id: str, req: WalletSettingsRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    wallet = billing.get_wallet(db, client_id)
    wallet.low_balance_threshold_inr = req.low_balance_threshold_inr
    db.commit()
    return wallet_out(db, client_id)


@router.post("/clients/{client_id}/wallet/payments/preview")
def preview_payment(client_id: str, req: PaymentRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """GST split for an amount, without recording anything."""
    _client_or_404(db, client_id)
    profile = db.get(ClientBillingProfile, client_id)
    return billing.gst_split(req.amount_received_inr, profile.state_code if profile else None)


@router.post("/clients/{client_id}/wallet/payments", status_code=status.HTTP_201_CREATED)
def record_payment(client_id: str, req: PaymentRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    return billing.record_payment(db, client_id, req.amount_received_inr, req.reference, current_user.id)


@router.post("/clients/{client_id}/wallet/adjustments")
def adjust_wallet(client_id: str, req: AdjustmentRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    billing.adjust_wallet(db, client_id, req.amount_inr, req.note, current_user.id)
    return wallet_out(db, client_id)


# ---------------------------------------------------------------- invoices

@router.get("/clients/{client_id}/invoices")
def list_invoices(client_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_operator)) -> List[Dict[str, Any]]:
    _client_or_404(db, client_id)
    invoices = db.query(Invoice).filter(Invoice.client_id == client_id).order_by(Invoice.created_at.desc()).all()
    return [invoice_out(i) for i in invoices]


@router.get("/invoices/{invoice_id}/pdf")
def get_invoice_pdf(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_operator)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice_pdf_response(invoice)


# ---------------------------------------------------------------- client logins

@router.get("/clients/{client_id}/users")
def list_client_users(client_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    rows = (
        db.query(User).join(ClientUser, ClientUser.user_id == User.id)
        .filter(ClientUser.client_id == client_id).order_by(User.email).all()
    )
    return [{"id": u.id, "email": u.email, "name": u.name, "status": u.status} for u in rows]


@router.post("/clients/{client_id}/users", status_code=status.HTTP_201_CREATED)
def invite_client_user(client_id: str, req: ClientLoginRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Invites a client login; the person signs in with the Google account for this email."""
    client = _client_or_404(db, client_id)
    email = str(req.email).lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if user and user.role != "CLIENT":
        raise HTTPException(status_code=409, detail="That email belongs to an internal Choranta user.")
    if user:
        link = db.get(ClientUser, user.id)
        if link and link.client_id != client_id:
            raise HTTPException(status_code=409, detail="That email already has access to another client.")
        user.status = "ACTIVE"
        if not link:
            db.add(ClientUser(user_id=user.id, client_id=client_id))
    else:
        user = User(id=generate_unique_id("usr", 12), email=email, name=(req.name or email.split("@")[0]).strip(),
                    hashed_password=None, role="CLIENT", status="ACTIVE")
        db.add(user)
        db.flush()
        db.add(ClientUser(user_id=user.id, client_id=client_id))
    db.commit()
    return {"id": user.id, "email": user.email, "name": user.name, "status": user.status, "client_name": client.name}


@router.delete("/clients/{client_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_client_user(client_id: str, user_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    link = db.get(ClientUser, user_id)
    if not link or link.client_id != client_id:
        raise HTTPException(status_code=404, detail="Client login not found.")
    user = db.get(User, user_id)
    if user:
        user.status = "INACTIVE"  # keeps history; the person can no longer sign in
    db.delete(link)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
