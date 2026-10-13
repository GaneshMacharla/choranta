"""
Public API used by clients' websites (server side), authenticated with an X-API-Key header.
"""
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_db
from app.db.session import SessionLocal
from app.services import instant_leads
from app.services.outbound_calls import place_outbound_call

router = APIRouter(prefix="/public", tags=["Public API"])

# Overridable in tests: where the post-response work gets its session, and how it dials
SESSION_FACTORY = SessionLocal
DIAL = place_outbound_call


async def _payload(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            data = await request.json()
        else:
            data = dict(await request.form())
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Send the lead as JSON or form fields.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Send the lead as a JSON object.")
    return data


@router.post("/leads", status_code=202)
async def submit_lead(
    request: Request,
    background: BackgroundTasks,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """
    Accepts a website form submission and calls the person within seconds (inside the campaign's
    calling hours; later submissions are called when the window opens).
    Body: phone (required), consent=true (required), name, source, campaign_id, and any other
    fields, which are passed to the AI agent as variables.
    """
    payload = await _payload(request)

    def accept():
        ctx = instant_leads.authenticate(db, x_api_key)
        return ctx, instant_leads.accept_lead(db, ctx, payload)

    try:
        ctx, accepted = await run_in_threadpool(accept)
    except instant_leads.LeadError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})

    if accepted["status"] == "accepted":
        background.add_task(instant_leads.process_lead_job, SESSION_FACTORY, ctx, accepted, DIAL)
    return {
        "status": accepted["status"],
        "lead_id": accepted["recipient_id"],
        "campaign_id": accepted["campaign_id"],
        "calling": "now" if accepted.get("dial_now") else "queued" if accepted["status"] == "accepted" else "already_received",
    }
