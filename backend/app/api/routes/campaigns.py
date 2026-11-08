"""
Outbound calling campaigns. The same endpoints are mounted twice: /campaigns for internal users
(any client) and /portal/campaigns for client portal users (their own client only).
"""
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_client_user, require_operator
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.campaign import Campaign, CampaignRecipient, DoNotCallEntry
from app.models.client import Client
from app.models.lead import Lead
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.schemas.campaign import (
    CampaignResponse,
    CampaignStats,
    CreateCampaignRequest,
    CsvPreviewResponse,
    CsvRecipientsRequest,
    DoNotCallRequest,
    DoNotCallResponse,
    LaunchCampaignRequest,
    LeadRecipientsRequest,
    RecipientImportResult,
    RecipientPage,
    RecipientResponse,
    UpdateCampaignRequest,
)
from app.services import campaigns as svc
from app.services import recipient_files
from app.services import phone_numbers


@dataclass
class Scope:
    user_id: str
    client_id: Optional[str]  # None = internal user, may act for any client


def internal_scope(user: User = Depends(require_operator)) -> Scope:
    return Scope(user_id=user.id, client_id=None)


def portal_scope(account=Depends(require_client_user)) -> Scope:
    user, client_id = account
    return Scope(user_id=user.id, client_id=client_id)


def _error(e: svc.CampaignError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.message)


def _client_for(scope: Scope, requested: Optional[str]) -> str:
    client_id = scope.client_id or requested
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required.")
    return client_id


def _get_campaign(db: Session, scope: Scope, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign or (scope.client_id and campaign.client_id != scope.client_id):
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


def _settings_data(payload: Any) -> Dict[str, Any]:
    data = payload.model_dump(exclude_unset=isinstance(payload, UpdateCampaignRequest))
    data.pop("client_id", None)
    if data.get("kind") == "TRIGGER" and "retry_intervals_min" not in payload.model_fields_set:
        # Instant leads are retried sooner than bulk lists
        data["retry_intervals_min"] = list(svc.TRIGGER_RETRY_INTERVALS)
    if data.get("windows") is not None:
        data["windows"] = [dict(w) for w in data["windows"]]
    if data.get("start_at") is not None and data["start_at"].tzinfo is not None:
        data["start_at"] = data["start_at"].astimezone(timezone.utc).replace(tzinfo=None)
    return data


def _campaign_out(db: Session, campaign: Campaign) -> CampaignResponse:
    client = db.get(Client, campaign.client_id)
    agent = db.get(Agent, campaign.agent_id)
    version = db.get(AgentVersion, campaign.agent_version_id)
    numbers = [db.get(PhoneNumber, n) for n in campaign.caller_number_ids or []]
    out = CampaignResponse.model_validate(campaign)
    out.client_name = client.name if client else None
    out.agent_name = agent.name if agent else None
    out.agent_version_number = version.version_number if version else None
    out.caller_numbers = [n.phone_number for n in numbers if n]
    out.stats = CampaignStats(**svc.stats(db, campaign))
    return out


class SheetLinkRequest(BaseModel):
    url: str = Field(..., max_length=2000)


def _register(router: APIRouter, scope_dep: Callable[..., Scope]) -> None:

    @router.get("", response_model=List[CampaignResponse])
    def list_campaigns(
        client_id: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        kind: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=200),
        scope: Scope = Depends(scope_dep),
        db: Session = Depends(get_db),
    ):
        q = db.query(Campaign)
        if scope.client_id or client_id:
            q = q.filter(Campaign.client_id == (scope.client_id or client_id))
        if status:
            q = q.filter(Campaign.status == status)
        if kind:
            q = q.filter(Campaign.kind == kind)
        return [_campaign_out(db, c) for c in q.order_by(Campaign.created_at.desc()).limit(limit).all()]

    @router.post("", response_model=CampaignResponse, status_code=201)
    def create_campaign(payload: CreateCampaignRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        client_id = _client_for(scope, payload.client_id)
        try:
            campaign = svc.create_campaign(db, client_id, _settings_data(payload), scope.user_id)
        except svc.CampaignError as e:
            raise _error(e)
        return _campaign_out(db, campaign)

    @router.get("/options")
    def campaign_options(client_id: Optional[str] = Query(None), scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)) -> Dict[str, Any]:
        """Everything the "Schedule campaign" wizard needs for one client: agents, versions, numbers, limits."""
        client_id = _client_for(scope, client_id)
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found.")
        agents = []
        for agent in db.query(Agent).filter(Agent.client_id == client_id).order_by(Agent.name).all():
            versions = (
                db.query(AgentVersion)
                .filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "PUBLISHED")
                .order_by(AgentVersion.version_number.desc()).all()
            )
            if versions:
                agents.append({
                    "id": agent.id,
                    "name": agent.name,
                    "versions": [{"id": v.id, "version_number": v.version_number, "created_at": v.created_at,
                                  "campaign_inputs": svc.version_campaign_inputs(v)} for v in versions],
                })
        numbers = []
        for number in db.query(PhoneNumber).filter(PhoneNumber.client_id == client_id).order_by(PhoneNumber.created_at).all():
            blocked = phone_numbers.blocked_reason(db, number)
            numbers.append({
                "id": number.id,
                "phone_number": number.phone_number,
                "provider": number.provider,
                "usable": number.status == "ACTIVE" and not blocked,
                "reason": blocked or (None if number.status == "ACTIVE" else f"Number is {number.status.lower()}"),
            })
        timezone_name = client.timezone if client.timezone and client.timezone != "UTC" else "Asia/Kolkata"
        return {
            "client_id": client_id,
            "timezone": timezone_name,
            "agents": agents,
            "numbers": numbers,
            "connections": [{"id": "vobiz", "name": "Vobiz"}],
            "concurrency_cap": svc.concurrency_cap(db, client_id),
            "max_recipients": svc.MAX_RECIPIENTS,
        }

    @router.get("/options/leads")
    def campaign_lead_options(
        client_id: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        scope: Scope = Depends(scope_dep),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        client_id = _client_for(scope, client_id)
        q = db.query(Lead).filter(Lead.client_id == client_id)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(or_(Lead.name.ilike(like), Lead.phone.ilike(like), Lead.lead_source.ilike(like)))
        total = q.count()
        leads = q.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
        return {
            "total": total,
            "items": [{
                "id": l.id, "name": l.name, "phone": l.phone, "lead_source": l.lead_source,
                "status": l.lead_qualification_status, "call_disposition": l.call_disposition,
                "created_at": l.created_at,
            } for l in leads],
        }

    @router.post("/recipient-file")
    async def convert_recipient_file(file: UploadFile = File(...), scope: Scope = Depends(scope_dep)):
        """Turns an Excel or text file into the CSV text preview-csv and import take."""
        data = await file.read(recipient_files.MAX_FILE_BYTES + 1)
        try:
            return recipient_files.file_to_csv(file.filename or "", data)
        except svc.CampaignError as e:
            raise _error(e)

    @router.post("/recipient-sheet")
    def convert_recipient_sheet(payload: SheetLinkRequest, scope: Scope = Depends(scope_dep)):
        """Reads a Google Sheet shared as 'Anyone with the link can view'."""
        try:
            return recipient_files.google_sheet_to_csv(payload.url)
        except svc.CampaignError as e:
            raise _error(e)

    @router.post("/preview-csv", response_model=CsvPreviewResponse)
    def preview_csv(payload: CsvRecipientsRequest, scope: Scope = Depends(scope_dep)):
        try:
            parsed = svc.parse_recipients_csv(payload.csv_text)
        except svc.CampaignError as e:
            raise _error(e)
        return CsvPreviewResponse(
            valid=len(parsed.rows),
            invalid=parsed.invalid[:50],
            invalid_count=len(parsed.invalid),
            duplicates=parsed.duplicates,
            phone_column=parsed.phone_column,
            variable_names=parsed.variable_names,
            sample=[{"phone": r["phone"], "name": r["name"], "variables": r["variables"]} for r in parsed.rows[:5]],
        )

    @router.get("/dnc", response_model=List[DoNotCallResponse])
    def list_do_not_call(client_id: Optional[str] = Query(None), scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        client_id = _client_for(scope, client_id)
        return db.query(DoNotCallEntry).filter(DoNotCallEntry.client_id == client_id).order_by(DoNotCallEntry.created_at.desc()).all()

    @router.post("/dnc", response_model=DoNotCallResponse, status_code=201)
    def add_do_not_call(payload: DoNotCallRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        client_id = _client_for(scope, payload.client_id)
        try:
            return svc.add_do_not_call(db, client_id, payload.phone, source="manual", note=payload.note)
        except svc.CampaignError as e:
            raise _error(e)

    @router.delete("/dnc/{entry_id}", status_code=204)
    def delete_do_not_call(entry_id: str, client_id: Optional[str] = Query(None), scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        entry = db.get(DoNotCallEntry, entry_id)
        if not entry or (scope.client_id and entry.client_id != scope.client_id):
            raise HTTPException(status_code=404, detail="Entry not found.")
        try:
            svc.remove_do_not_call(db, entry.client_id, entry_id)
        except svc.CampaignError as e:
            raise _error(e)
        return Response(status_code=204)

    @router.get("/{campaign_id}", response_model=CampaignResponse)
    def get_campaign(campaign_id: str, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        return _campaign_out(db, _get_campaign(db, scope, campaign_id))

    @router.patch("/{campaign_id}", response_model=CampaignResponse)
    def update_campaign(campaign_id: str, payload: UpdateCampaignRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, scope, campaign_id)
        try:
            campaign = svc.update_campaign(db, campaign, _settings_data(payload))
        except svc.CampaignError as e:
            raise _error(e)
        return _campaign_out(db, campaign)

    @router.delete("/{campaign_id}", status_code=204)
    def delete_campaign(campaign_id: str, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        try:
            svc.delete_campaign(db, _get_campaign(db, scope, campaign_id))
        except svc.CampaignError as e:
            raise _error(e)
        return Response(status_code=204)

    @router.post("/{campaign_id}/recipients/csv", response_model=RecipientImportResult)
    def import_csv(campaign_id: str, payload: CsvRecipientsRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        try:
            return svc.add_recipients_from_csv(db, _get_campaign(db, scope, campaign_id), payload.csv_text)
        except svc.CampaignError as e:
            raise _error(e)

    @router.post("/{campaign_id}/recipients/leads", response_model=RecipientImportResult)
    def import_leads(campaign_id: str, payload: LeadRecipientsRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        try:
            return svc.add_recipients_from_leads(db, _get_campaign(db, scope, campaign_id), payload.lead_ids)
        except svc.CampaignError as e:
            raise _error(e)

    @router.delete("/{campaign_id}/recipients/{recipient_id}", status_code=204)
    def delete_recipient(campaign_id: str, recipient_id: str, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        try:
            svc.remove_recipient(db, _get_campaign(db, scope, campaign_id), recipient_id)
        except svc.CampaignError as e:
            raise _error(e)
        return Response(status_code=204)

    @router.get("/{campaign_id}/recipients", response_model=RecipientPage)
    def list_recipients(
        campaign_id: str,
        status: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        scope: Scope = Depends(scope_dep),
        db: Session = Depends(get_db),
    ):
        campaign = _get_campaign(db, scope, campaign_id)
        q = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id)
        if status:
            q = q.filter(CampaignRecipient.status == status)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(or_(CampaignRecipient.phone.ilike(like), CampaignRecipient.name.ilike(like)))
        total = q.count()
        items = q.order_by(CampaignRecipient.position).offset(skip).limit(limit).all()
        return RecipientPage(items=[RecipientResponse.model_validate(r) for r in items], total=total)

    @router.post("/{campaign_id}/launch", response_model=CampaignResponse)
    def launch_campaign(campaign_id: str, payload: LaunchCampaignRequest, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        try:
            campaign = svc.launch(db, _get_campaign(db, scope, campaign_id), scope.user_id, payload.consent)
        except svc.CampaignError as e:
            raise _error(e)
        return _campaign_out(db, campaign)

    def _action(name: str, fn: Callable[[Session, Campaign], Campaign]) -> None:
        @router.post(f"/{{campaign_id}}/{name}", response_model=CampaignResponse, name=f"{name}_campaign")
        def action(campaign_id: str, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
            try:
                campaign = fn(db, _get_campaign(db, scope, campaign_id))
            except svc.CampaignError as e:
                raise _error(e)
            return _campaign_out(db, campaign)

    _action("webhook-secret", svc.rotate_webhook_secret)
    _action("pause", svc.pause)
    _action("resume", svc.resume)
    _action("stop", svc.stop)
    _action("cancel", svc.cancel)

    @router.get("/{campaign_id}/export.csv")
    def export_campaign(campaign_id: str, scope: Scope = Depends(scope_dep), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, scope, campaign_id)
        filename = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in campaign.name)[:60] or campaign.id
        return Response(
            content=svc.export_results_csv(db, campaign),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}-results.csv"'},
        )


router = APIRouter(prefix="/campaigns", tags=["Campaigns"])
portal_router = APIRouter(prefix="/portal/campaigns", tags=["Client Portal"])
_register(router, internal_scope)
_register(portal_router, portal_scope)
