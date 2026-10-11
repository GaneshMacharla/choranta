"""Client portal: every endpoint is scoped to the signed-in client account's own client."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user
from app.api.routes.billing import invoice_out, invoice_pdf_response, wallet_out
from app.api.routes.telephony import _format_call_response, _recording_path, get_call_detail
from app.core.config import settings
from app.models.billing import Invoice, WalletTransaction
from app.models.call import Call
from app.models.client import Client
from app.models.property import Property
from app.models.user import User
from app.services.pricing import get_pricing

router = APIRouter(prefix="/portal", tags=["Client Portal"])

ClientAccount = Tuple[User, str]


def _own_call(db: Session, client_id: str, call_id: str) -> Call:
    call = db.get(Call, call_id)
    if not call or call.client_id != client_id:
        raise HTTPException(status_code=404, detail="Call not found.")
    return call


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/summary")
def summary(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    user, client_id = account
    client = db.get(Client, client_id)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)

    calls = db.query(Call).filter(Call.client_id == client_id, Call.created_at >= min(month_start, since).replace(tzinfo=None)).all()
    debits = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.client_id == client_id, WalletTransaction.type == "DEBIT",
                WalletTransaction.created_at >= min(month_start, since).replace(tzinfo=None))
        .all()
    )

    daily: Dict[str, Dict[str, float]] = defaultdict(lambda: {"calls": 0, "minutes": 0.0, "spend_inr": 0.0})
    month = {"calls": 0, "minutes": 0.0, "spend_inr": 0.0}
    for c in calls:
        created = _aware(c.created_at)
        minutes = (c.duration_seconds or 0) / 60.0
        if created >= since:
            day = daily[created.date().isoformat()]
            day["calls"] += 1
            day["minutes"] += minutes
        if created >= month_start:
            month["calls"] += 1
            month["minutes"] += minutes
    for t in debits:
        created = _aware(t.created_at)
        if created >= since:
            daily[created.date().isoformat()]["spend_inr"] += -t.amount_inr
        if created >= month_start:
            month["spend_inr"] += -t.amount_inr

    series = []
    for offset in range(30):
        day = (since + timedelta(days=offset)).date().isoformat()
        values = daily.get(day, {"calls": 0, "minutes": 0.0, "spend_inr": 0.0})
        series.append({"date": day, "calls": values["calls"], "minutes": round(values["minutes"], 1),
                       "spend_inr": round(values["spend_inr"], 2)})

    wallet = wallet_out(db, client_id, limit=0)
    return {
        "client_name": client.name if client else "",
        "user_name": user.name,
        "wallet": {k: wallet[k] for k in ("balance_inr", "low_balance_threshold_inr", "low_balance", "calls_blocked")},
        "month": {"calls": month["calls"], "minutes": round(month["minutes"], 1), "spend_inr": round(month["spend_inr"], 2)},
        "daily": series,
    }


@router.get("/calls")
def list_calls(
    limit: int = Query(50, ge=1, le=200),
    account: ClientAccount = Depends(require_client_user),
    db: Session = Depends(get_db),
):
    user, client_id = account
    calls = db.query(Call).filter(Call.client_id == client_id).order_by(Call.created_at.desc()).limit(limit).all()
    pricing = get_pricing(db)
    return [_format_call_response(c, db, user, pricing) for c in calls]


@router.get("/calls/{call_id}")
def call_detail(call_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    user, client_id = account
    _own_call(db, client_id, call_id)
    detail = get_call_detail(call_id=call_id, db=db, current_user=user)
    # Clients see the conversation and their charge, not internal runtime events or token usage
    return detail.model_copy(update={"events": [], "usage": {}})


@router.get("/calls/{call_id}/recording")
def call_recording(call_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    call = _own_call(db, client_id, call_id)
    path = _recording_path(call)
    if not path:
        raise HTTPException(status_code=404, detail="No recording is available for this call.")
    return FileResponse(path, media_type="audio/wav", filename=f"{call_id}.wav")


@router.get("/wallet")
def wallet(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    return wallet_out(db, client_id, limit=200)


@router.get("/invoices")
def invoices(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    _, client_id = account
    rows = db.query(Invoice).filter(Invoice.client_id == client_id).order_by(Invoice.created_at.desc()).all()
    return [invoice_out(i) for i in rows]


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: str, account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    invoice = db.get(Invoice, invoice_id)
    if not invoice or invoice.client_id != client_id:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice_pdf_response(invoice)


@router.get("/properties")
def properties(account: ClientAccount = Depends(require_client_user), db: Session = Depends(get_db)):
    _, client_id = account
    props = (
        db.query(Property).filter(Property.client_id == client_id, Property.status != "UNAVAILABLE")
        .order_by(Property.project_name).limit(500).all()
    )
    return {
        "count": len(props),
        "last_synced_at": max((p.last_synced_at for p in props if p.last_synced_at), default=None),
        "properties": [
            {"id": p.id, "project_name": p.project_name, "location": p.location, "bhk": p.bhk,
             "price_display": p.price_display, "property_type": p.property_type, "status": p.status}
            for p in props
        ],
    }


@router.get("/payment-instructions")
def payment_instructions(account: ClientAccount = Depends(require_client_user)):
    return {
        "upi_id": settings.PAYMENT_UPI_ID or None,
        "bank_details": settings.PAYMENT_BANK_DETAILS or None,
        "gst_rate_percent": settings.GST_RATE_PERCENT,
        "note": "After paying, share the UTR / UPI reference with your Choranta contact. Your wallet is credited "
                "with the amount excluding GST, and a GST invoice is issued.",
    }
