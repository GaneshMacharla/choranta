import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Response, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, require_admin, require_operator
from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.user import User
from app.models.client import Client
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.phone_number import PhoneNumber
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.repositories.phone_number_repository import PhoneNumberRepository
from app.repositories.call_repository import CallRepository
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.runtime.runtime import AgentRuntime
from app.runtime.readiness.checker import RuntimeReadinessChecker
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony import TelephonyProvider
from app.runtime.telephony.session import TelephonyMediaSession, active_telephony_calls
from app.schemas.telephony import (
    CreatePhoneNumberRequest,
    UpdatePhoneNumberRequest,
    PhoneNumberResponse,
    PhoneNumberReadinessResponse,
    CallResponse,
    CallDetailResponse,
    TelephonyOverviewResponse,
    InitiateOutboundCallRequest,
)


logger = logging.getLogger("choranta.api.telephony")

router = APIRouter(prefix="/telephony", tags=["Telephony & Inbound Calling"])
ws_router = APIRouter(tags=["Telephony WebSocket Transport"])


def _format_phone_number_response(pn: PhoneNumber, db: Session) -> PhoneNumberResponse:
    client = db.query(Client).filter(Client.id == pn.client_id).first() if pn.client_id else None
    agent = db.query(Agent).filter(Agent.id == pn.agent_id).first() if pn.agent_id else None
    version = db.query(AgentVersion).filter(AgentVersion.id == pn.agent_version_id).first() if pn.agent_version_id else None

    return PhoneNumberResponse(
        id=pn.id,
        client_id=pn.client_id,
        client_name=client.name if client else None,
        agent_id=pn.agent_id,
        agent_name=agent.name if agent else None,
        agent_version_id=pn.agent_version_id,
        agent_version_number=version.version_number if version else None,
        provider=pn.provider,
        provider_number_id=pn.provider_number_id,
        phone_number=pn.phone_number,
        country_code=pn.country_code,
        status=pn.status,
        metadata=pn.metadata_ if isinstance(pn.metadata_, dict) else {},
        created_at=pn.created_at,
        updated_at=pn.updated_at
    )


def _format_call_response(c: Call, db: Session) -> CallResponse:
    client = db.query(Client).filter(Client.id == c.client_id).first() if c.client_id else None
    agent = db.query(Agent).filter(Agent.id == c.agent_id).first() if c.agent_id else None
    version = db.query(AgentVersion).filter(AgentVersion.id == c.agent_version_id).first() if c.agent_version_id else None

    return CallResponse(
        id=c.id,
        client_id=c.client_id,
        client_name=client.name if client else None,
        agent_id=c.agent_id,
        agent_name=agent.name if agent else None,
        agent_version_id=c.agent_version_id,
        agent_version_number=version.version_number if version else None,
        phone_number_id=c.phone_number_id,
        runtime_session_id=c.runtime_session_id,
        provider=c.provider,
        provider_call_id=c.provider_call_id,
        direction=c.direction,
        caller_number=c.caller_number,
        destination_number=c.destination_number,
        status=c.status,
        started_at=c.started_at,
        answered_at=c.answered_at,
        ended_at=c.ended_at,
        duration_seconds=c.duration_seconds,
        termination_reason=c.termination_reason,
        recording_url=c.recording_url,
        transcript_summary=c.transcript_summary,
        metadata=c.metadata_ if isinstance(c.metadata_, dict) else {},
        created_at=c.created_at,
        updated_at=c.updated_at
    )


# -------------------------------------------------------------
# 1. INBOUND CALL WEBHOOKS (EXOTEL)
# -------------------------------------------------------------

async def _collect_webhook_params(request: Request) -> Dict[str, Any]:
    """Merges query-string and form parameters (Exotel applets may use GET or POST)."""
    params: Dict[str, Any] = dict(request.query_params)
    if request.method == "POST":
        try:
            form_data = await request.form()
            params.update(dict(form_data))
        except Exception:
            pass
    params.pop("token", None)
    return params


def _with_token(url: str) -> str:
    secret = getattr(settings, "EXOTEL_WEBHOOK_SECRET", None)
    return f"{url}?{urlencode({'token': secret})}" if secret else url


@router.api_route("/exotel/inbound", methods=["GET", "POST"], response_class=Response)
async def exotel_inbound_call_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Dynamic URL endpoint for Exotel's Voicebot applet.
    Authenticates the shared-secret token, resolves PhoneNumber to pinned AgentVersion,
    verifies runtime readiness, initiates Call and RuntimeSession, and returns the media WebSocket URL.
    """
    telephony_provider = default_registry.get_telephony("exotel")
    media_type = telephony_provider.response_media_type

    # 1. Parse webhook parameters
    token = request.query_params.get("token", "")
    params = await _collect_webhook_params(request)
    request_url = str(request.url.remove_query_params("token"))

    # 2. Shared-secret validation
    if not telephony_provider.validate_webhook(request_url, params, token):
        logger.warning(f"Rejecting Exotel webhook: invalid token for url '{request_url}'")
        return Response(status_code=status.HTTP_403_FORBIDDEN, content="Invalid Exotel webhook token")

    payload = telephony_provider.parse_inbound_call_webhook(params)
    logger.info(f"Inbound call received: {payload.caller_number} -> {payload.destination_number} (CallSid={payload.provider_call_id})")

    # 3. Resolve which agent handles the call.
    # A call we placed ourselves (outbound) already has a Call record keyed by Exotel's CallSid
    # that pins the agent version; anything else is routed by the dialled phone number.
    call_repo = CallRepository(db)
    existing_call = call_repo.get_by_provider_call_id(payload.provider_call_id)

    if existing_call:
        route = SimpleNamespace(
            id=existing_call.phone_number_id,
            agent_id=existing_call.agent_id,
            agent_version_id=existing_call.agent_version_id,
            client_id=existing_call.client_id,
        )
    else:
        phone_repo = PhoneNumberRepository(db)
        phone_record = phone_repo.get_by_e164(payload.destination_number)

        if not phone_record:
            logger.warning(f"Unconfigured phone number called: {payload.destination_number}")
            rejection = telephony_provider.generate_reject_response(
                "Thank you for calling. This phone number is not currently configured for an AI employee."
            )
            return Response(content=rejection, media_type=media_type)

        if phone_record.status != "ACTIVE":
            logger.warning(f"Inactive phone number called: {phone_record.phone_number} (status={phone_record.status})")
            rejection = telephony_provider.generate_reject_response(
                "This service is temporarily inactive. Please contact support."
            )
            return Response(content=rejection, media_type=media_type)

        if not phone_record.agent_id or not phone_record.agent_version_id:
            logger.warning(f"Phone number {phone_record.phone_number} has no assigned AgentVersion.")
            rejection = telephony_provider.generate_reject_response(
                "No AI employee is currently assigned to this phone number."
            )
            return Response(content=rejection, media_type=media_type)
        route = phone_record

    # 4. Verify deployment readiness
    checker = RuntimeReadinessChecker(db, default_registry)
    readiness = checker.check(route.agent_id, route.agent_version_id)
    if not readiness["ready"]:
        error_reasons = "; ".join(readiness["errors"])
        logger.error(f"Readiness check failed for call on agent {route.agent_id}: {error_reasons}")
        rejection = telephony_provider.generate_reject_response(
            "The requested AI assistant is currently undergoing maintenance. Please call back shortly."
        )
        return Response(content=rejection, media_type=media_type)

    # 5. Idempotency: webhook retries reuse the existing Call / Session
    runtime = AgentRuntime(db, registry=default_registry)
    emitter = EventEmitter(db)

    if existing_call and existing_call.runtime_session_id:
        call_record = existing_call
        session_id = existing_call.runtime_session_id
    elif existing_call:
        # Outbound call answered by the customer: start its runtime session now
        call_record = existing_call
        custom_vars = dict((call_record.metadata_ or {}).get("variables") or {})

        # If variables missing, look up lead by destination phone number
        from app.models.lead import Lead
        lead = db.query(Lead).filter(Lead.phone == call_record.destination_number).first()
        if not lead and len(call_record.destination_number) >= 10:
            lead = db.query(Lead).filter(Lead.phone.endswith(call_record.destination_number[-10:])).first()
        if lead:
            custom_vars.setdefault("user_name", lead.name)
            custom_vars.setdefault("lead_id", lead.id)
            if lead.property_viewed:
                custom_vars.setdefault("property_viewed", lead.property_viewed)
            if lead.enquiry_location:
                custom_vars.setdefault("enquiry_location", lead.enquiry_location)
            if lead.enquiry_budget:
                custom_vars.setdefault("enquiry_budget", lead.enquiry_budget)
            if lead.enquiry_bhk:
                custom_vars.setdefault("enquiry_bhk", lead.enquiry_bhk)

        session_obj = runtime.start_session(
            agent_id=call_record.agent_id,
            agent_version_id=call_record.agent_version_id,
            metadata={
                "origin": "telephony_outbound",
                "call_id": call_record.id,
                "provider": call_record.provider or "exotel",
                "caller": call_record.caller_number,
                "destination": call_record.destination_number,
                "phone_number_id": call_record.phone_number_id,
                **custom_vars
            }
        )
        call_record.runtime_session_id = session_obj.id
        call_record.status = "ANSWERED"
        call_record.answered_at = datetime.now(timezone.utc)
        call_repo.update(call_record)
        session_id = session_obj.id
    else:
        # Create Call Record in RINGING state
        call_id = generate_unique_id("call", 12)
        call_record = Call(
            id=call_id,
            client_id=route.client_id,
            agent_id=route.agent_id,
            agent_version_id=route.agent_version_id,
            phone_number_id=route.id,
            provider="exotel",
            provider_call_id=payload.provider_call_id,
            direction="INBOUND",
            caller_number=payload.caller_number,
            destination_number=payload.destination_number,
            status="RINGING",
            started_at=datetime.now(timezone.utc),
            metadata_=payload.raw_params
        )
        call_repo.create(call_record)

        # 6. Create RuntimeSession with pinned immutable version
        session_obj = runtime.start_session(
            agent_id=route.agent_id,
            agent_version_id=route.agent_version_id,
            metadata={
                "origin": "telephony_inbound",
                "call_id": call_id,
                "provider": "exotel",
                "caller": payload.caller_number,
                "destination": payload.destination_number,
                "phone_number_id": route.id
            }
        )
        call_record.runtime_session_id = session_obj.id
        call_record.status = "ANSWERED"
        call_repo.update(call_record)
        session_id = session_obj.id

    # Emit telephony routing events
    emitter.emit(
        RuntimeEventType.CALL_RECEIVED,
        session_id=session_id or "",
        agent_id=route.agent_id,
        agent_version_id=route.agent_version_id,
        client_id=route.client_id,
        payload={"call_id": call_record.id, "caller": payload.caller_number, "destination": payload.destination_number}
    )

    emitter.emit(
        RuntimeEventType.CALL_ROUTING_STARTED,
        session_id=session_id or "",
        agent_id=route.agent_id,
        agent_version_id=route.agent_version_id,
        client_id=route.client_id,
        payload={"phone_number_id": route.id}
    )

    emitter.emit(
        RuntimeEventType.CALL_ROUTED,
        session_id=session_id or "",
        agent_id=route.agent_id,
        agent_version_id=route.agent_version_id,
        client_id=route.client_id,
        payload={"agent_id": route.agent_id, "agent_version_id": route.agent_version_id}
    )

    emitter.emit(
        RuntimeEventType.CALL_ANSWERED,
        session_id=session_id or "",
        agent_id=route.agent_id,
        agent_version_id=route.agent_version_id,
        client_id=route.client_id,
        payload={"call_id": call_record.id, "provider_call_id": payload.provider_call_id}
    )

    # 7. Return the bidirectional media stream URL
    base_url = settings.TELEPHONY_BASE_URL or str(request.base_url).rstrip("/")
    ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = _with_token(f"{ws_base}/ws/telephony/exotel/media")
    status_callback_url = _with_token(f"{base_url}/api/telephony/exotel/status")

    connect_response = telephony_provider.generate_connect_response(
        stream_url=stream_url,
        call_sid=payload.provider_call_id,
        status_callback_url=status_callback_url
    )
    return Response(content=connect_response, media_type=media_type)


@router.api_route("/exotel/status", methods=["GET", "POST"])
async def exotel_call_status_callback(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Exotel call status callback (Passthru applet or Calls API StatusCallback):
    call completed, busy, no-answer, duration, recording.
    """
    telephony_provider = default_registry.get_telephony("exotel")
    token = request.query_params.get("token", "")
    params = await _collect_webhook_params(request)
    if not telephony_provider.validate_webhook(str(request.url.remove_query_params("token")), params, token):
        return Response(status_code=status.HTTP_403_FORBIDDEN, content="Invalid Exotel webhook token")

    call_sid = params.get("CallSid") or params.get("call_sid")
    if not call_sid:
        return {"status": "ignored"}

    call_repo = CallRepository(db)
    call_record = call_repo.get_by_provider_call_id(call_sid)
    if not call_record:
        return {"status": "not_found"}

    call_status = (params.get("Status") or params.get("CallStatus") or params.get("DialCallStatus") or "").lower()
    try:
        call_duration = float(
            params.get("ConversationDuration") or params.get("DialCallDuration") or params.get("Duration") or 0.0
        )
    except (TypeError, ValueError):
        call_duration = 0.0
    recording_url = params.get("RecordingUrl")

    if call_duration > 0:
        call_record.duration_seconds = call_duration

    if recording_url:
        call_record.recording_url = recording_url

    now = datetime.now(timezone.utc)
    emitter = EventEmitter(db)

    if call_status in ("completed", "answered"):
        call_record.status = "COMPLETED"
        call_record.ended_at = now
        call_repo.update(call_record)
        emitter.emit(
            RuntimeEventType.CALL_COMPLETED,
            session_id=call_record.runtime_session_id or "",
            agent_id=call_record.agent_id,
            agent_version_id=call_record.agent_version_id,
            client_id=call_record.client_id,
            payload={"call_id": call_record.id, "duration": call_duration}
        )
    elif call_status in ("busy", "failed", "no-answer", "canceled", "cancelled"):
        call_record.status = "FAILED"
        call_record.ended_at = now
        call_record.termination_reason = call_status
        call_repo.update(call_record)
        emitter.emit(
            RuntimeEventType.CALL_FAILED,
            session_id=call_record.runtime_session_id or "",
            agent_id=call_record.agent_id,
            agent_version_id=call_record.agent_version_id,
            client_id=call_record.client_id,
            payload={"call_id": call_record.id, "reason": call_status}
        )
    else:
        call_repo.update(call_record)

    return {"status": "processed", "call_id": call_record.id}


# -------------------------------------------------------------
# 2. BIDIRECTIONAL TELEPHONY WEBSOCKET AUDIO TRANSPORT
# -------------------------------------------------------------

@ws_router.websocket("/ws/telephony/exotel/media")
@ws_router.websocket("/api/telephony/exotel/media")
@router.websocket("/exotel/media")
async def exotel_telephony_media_websocket(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    Exotel Voicebot (AgentStream) WebSocket endpoint.
    Transcodes full-duplex 8kHz PCM16 audio to 16kHz PCM16, bridging Exotel with AgentRuntime.
    """
    await websocket.accept()
    telephony_provider = default_registry.get_telephony("exotel")
    # Exotel may drop query parameters from the stream URL, so a missing token isn't fatal here:
    # the stream must then belong to a call already routed through the token-checked Voicebot
    # webhook (an unguessable CallSid with a live runtime session), which is enforced on "start".
    token = websocket.query_params.get("token", "")
    token_valid = bool(token) and telephony_provider.validate_webhook(str(websocket.url), {}, token)
    if token and not token_valid:
        logger.warning("Rejecting Exotel media stream: invalid token.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    media_session: Optional[TelephonyMediaSession] = None
    call_record: Optional[Call] = None

    try:
        while True:
            message_text = await websocket.receive_text()
            data = json.loads(message_text)
            event_type = data.get("event")

            if event_type == "connected":
                logger.info("Exotel media stream connected.")

            elif event_type == "start":
                stream_sid, call_sid = telephony_provider.parse_stream_start(data)
                start_info = data.get("start") or {}
                logger.info(
                    f"Exotel media stream starting: stream_sid={stream_sid}, call_sid={call_sid}, "
                    f"media_format={start_info.get('media_format')}, start_keys={sorted(start_info.keys())}"
                )

                call_repo = CallRepository(db)
                call_record = call_repo.get_by_provider_call_id(call_sid)
                if not call_record:
                    logger.error(f"Cannot find active Call record for Exotel CallSid '{call_sid}'")
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break

                if not token_valid:
                    custom_token = (start_info.get("custom_parameters") or {}).get("token", "")
                    routed = bool(call_record.runtime_session_id) and call_record.status in ("ANSWERED", "RINGING")
                    if not (custom_token and telephony_provider.validate_webhook(str(websocket.url), {}, custom_token)) and not routed:
                        logger.warning(f"Rejecting Exotel media stream for call '{call_sid}': not routed via the Voicebot webhook.")
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        break

                media_session = TelephonyMediaSession(
                    websocket=websocket,
                    call_record=call_record,
                    stream_sid=stream_sid,
                    db=db,
                    telephony_provider=telephony_provider
                )
                await media_session.initialize()

            elif event_type == "media":
                if media_session:
                    media_payload = data.get("media", {}).get("payload", "")
                    if media_payload:
                        await media_session.handle_media_payload(media_payload)

            elif event_type == "stop":
                logger.info("Exotel media stream received stop event (caller hangup).")
                if media_session:
                    await media_session.close(reason="caller_hangup")
                break

    except WebSocketDisconnect:
        logger.info("Exotel media stream disconnected.")
    except Exception as e:
        logger.error(f"Error in Exotel media websocket loop: {e}")
    finally:
        if media_session:
            await media_session.close(reason="disconnect")


# -------------------------------------------------------------
# 3. INTERNAL PHONE NUMBER MANAGEMENT REST ENDPOINTS
# -------------------------------------------------------------

@router.get("/numbers", response_model=List[PhoneNumberResponse])
def list_phone_numbers(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Lists phone numbers with optional client filtering and tenancy isolation."""
    repo = PhoneNumberRepository(db)
    if current_user.role != "ADMIN" and client_id:
        numbers = repo.list_by_client(client_id, limit=limit)
    elif client_id:
        numbers = repo.list_by_client(client_id, limit=limit)
    else:
        numbers = repo.list_all(skip=skip, limit=limit, status=status)
    return [_format_phone_number_response(pn, db) for pn in numbers]


@router.post("/numbers", response_model=PhoneNumberResponse, status_code=status.HTTP_201_CREATED)
def create_phone_number(
    req: CreatePhoneNumberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Registers a phone number in Choranta and optionally assigns an agent deployment."""
    repo = PhoneNumberRepository(db)
    normalized = req.phone_number.strip().replace(" ", "").replace("-", "")

    existing = repo.get_by_e164(normalized)
    if existing:
        raise HTTPException(status_code=400, detail=f"Phone number '{normalized}' already registered.")

    client = db.query(Client).filter(Client.id == req.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{req.client_id}' not found.")

    if req.agent_id:
        agent = db.query(Agent).filter(Agent.id == req.agent_id, Agent.client_id == req.client_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' does not belong to client.")

    if req.agent_version_id:
        version = db.query(AgentVersion).filter(AgentVersion.id == req.agent_version_id, AgentVersion.agent_id == req.agent_id).first()
        if not version or version.status != "PUBLISHED":
            raise HTTPException(status_code=400, detail="Pinned AgentVersion must exist and have status PUBLISHED.")

    pn_id = generate_unique_id("phn", 10)
    record = PhoneNumber(
        id=pn_id,
        client_id=req.client_id,
        agent_id=req.agent_id,
        agent_version_id=req.agent_version_id,
        provider=req.provider,
        provider_number_id=req.provider_number_id,
        phone_number=normalized,
        country_code=req.country_code,
        status=req.status,
        metadata_=req.metadata
    )
    saved = repo.create(record)
    return _format_phone_number_response(saved, db)


@router.get("/numbers/{phone_number_id}", response_model=PhoneNumberResponse)
def get_phone_number_details(
    phone_number_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    repo = PhoneNumberRepository(db)
    record = repo.get_by_id(phone_number_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Phone number '{phone_number_id}' not found.")
    return _format_phone_number_response(record, db)


@router.get("/numbers/{phone_number_id}/readiness", response_model=PhoneNumberReadinessResponse)
def check_phone_number_readiness(
    phone_number_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Verifies that an assigned phone number satisfies all prerequisites to accept inbound phone calls."""
    repo = PhoneNumberRepository(db)
    record = repo.get_by_id(phone_number_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Phone number '{phone_number_id}' not found.")

    errors = []
    warnings = []

    if record.status != "ACTIVE":
        errors.append(f"Phone number status is '{record.status}'. Must be 'ACTIVE'.")

    if not record.agent_id or not record.agent_version_id:
        errors.append("No AI employee or pinned published version is assigned to this phone number.")
        return PhoneNumberReadinessResponse(
            phone_number_id=record.id,
            phone_number=record.phone_number,
            ready=False,
            errors=errors,
            warnings=warnings,
            agent_id=record.agent_id,
            agent_version_id=record.agent_version_id
        )

    checker = RuntimeReadinessChecker(db, default_registry)
    res = checker.check(record.agent_id, record.agent_version_id)
    errors.extend(res.get("errors", []))
    warnings.extend(res.get("warnings", []))

    return PhoneNumberReadinessResponse(
        phone_number_id=record.id,
        phone_number=record.phone_number,
        ready=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        agent_id=record.agent_id,
        agent_version_id=record.agent_version_id
    )


@router.patch("/numbers/{phone_number_id}", response_model=PhoneNumberResponse)
def update_phone_number(
    phone_number_id: str,
    req: UpdatePhoneNumberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Assigns or modifies the AI employee and pinned version handling inbound calls on this number."""
    repo = PhoneNumberRepository(db)
    record = repo.get_by_id(phone_number_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Phone number '{phone_number_id}' not found.")

    if req.agent_id is not None:
        if req.agent_id:
            agent = db.query(Agent).filter(Agent.id == req.agent_id, Agent.client_id == record.client_id).first()
            if not agent:
                raise HTTPException(status_code=400, detail="Agent does not belong to client.")
            record.agent_id = req.agent_id
        else:
            record.agent_id = None
            record.agent_version_id = None

    if req.agent_version_id is not None:
        if req.agent_version_id:
            version = db.query(AgentVersion).filter(AgentVersion.id == req.agent_version_id, AgentVersion.agent_id == record.agent_id).first()
            if not version or version.status != "PUBLISHED":
                raise HTTPException(status_code=400, detail="Assigned version must exist and have status PUBLISHED.")
            record.agent_version_id = req.agent_version_id
        else:
            record.agent_version_id = None

    if req.status is not None:
        record.status = req.status
    if req.metadata is not None:
        record.metadata_ = req.metadata

    updated = repo.update(record)
    return _format_phone_number_response(updated, db)


@router.delete("/numbers/{phone_number_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phone_number(
    phone_number_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    repo = PhoneNumberRepository(db)
    record = repo.get_by_id(phone_number_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Phone number '{phone_number_id}' not found.")
    repo.delete(record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------
# 4. CALL MONITORING & DETAIL REST ENDPOINTS
# -------------------------------------------------------------

@router.get("/calls", response_model=List[CallResponse])
def list_calls(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Lists call history with client isolation and filtering."""
    repo = CallRepository(db)
    calls = repo.list_all(
        skip=skip,
        limit=limit,
        status=status,
        direction=direction,
        client_id=client_id
    )
    return [_format_call_response(c, db) for c in calls]


@router.post("/calls/outbound", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
def initiate_outbound_call_endpoint(
    req: InitiateOutboundCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """
    Triggers an outbound call to a customer via the configured telephony carrier (Exotel).
    Once the customer answers, Exotel connects the call to the AI Employee.
    """
    phone_record: Optional[PhoneNumber] = None
    if req.phone_number_id:
        phone_repo = PhoneNumberRepository(db)
        phone_record = phone_repo.get_by_id(req.phone_number_id) or phone_repo.get_by_e164(req.phone_number_id)
        if not phone_record:
            raise HTTPException(status_code=404, detail=f"Phone number '{req.phone_number_id}' not found.")
        if not phone_record.agent_id or not phone_record.agent_version_id:
            raise HTTPException(
                status_code=400,
                detail=f"Phone number '{phone_record.phone_number}' is not assigned to an AI Employee."
            )
        agent_id, agent_version_id = phone_record.agent_id, phone_record.agent_version_id
        caller_id = phone_record.phone_number
        provider_name = phone_record.provider or "exotel"
    elif req.agent_id and req.agent_version_id:
        agent_id, agent_version_id = req.agent_id, req.agent_version_id
        caller_id = req.caller_id or getattr(settings, "EXOTEL_CALLER_ID", None)
        if not caller_id:
            raise HTTPException(
                status_code=400,
                detail="No caller ID: set EXOTEL_CALLER_ID in backend/.env to your ExoPhone, or pass caller_id."
            )
        provider_name = "exotel"
    else:
        raise HTTPException(status_code=400, detail="Provide phone_number_id, or agent_id and agent_version_id.")

    readiness = RuntimeReadinessChecker(db, default_registry).check(agent_id, agent_version_id)
    if not readiness["ready"]:
        raise HTTPException(status_code=400, detail="Agent is not ready for calls: " + "; ".join(readiness["errors"]))
    agent = db.get(Agent, agent_id)

    # Exotel must reach this server when the customer answers; fail fast instead of placing a dead call
    base_url = (settings.TELEPHONY_BASE_URL or "").rstrip("/")
    if not base_url.startswith("https://") or any(h in base_url for h in ("localhost", "127.0.0.1")):
        raise HTTPException(
            status_code=400,
            detail="TELEPHONY_BASE_URL must be a public https:// address Exotel can reach (e.g. your ngrok URL)."
        )

    flow_id = req.flow_id or getattr(settings, "EXOTEL_FLOW_ID", None)
    account_sid = getattr(settings, "EXOTEL_ACCOUNT_SID", None)
    if not flow_id or not account_sid:
        raise HTTPException(status_code=400, detail="EXOTEL_FLOW_ID and EXOTEL_ACCOUNT_SID must be configured.")
    flow_url = f"http://my.exotel.com/{account_sid}/exoml/start_voice/{flow_id}"
    status_callback_url = _with_token(f"{base_url}/api/telephony/exotel/status")

    telephony_provider = default_registry.get_telephony(provider_name)

    # Initiate carrier call
    try:
        call_result = telephony_provider.initiate_outbound_call(
            customer_number=req.destination_number,
            caller_id=caller_id,
            flow_url=flow_url,
            status_callback_url=status_callback_url,
            custom_field=req.custom_field or f"agent:{agent_id}"
        )
    except Exception as exc:
        logger.error(f"Failed to initiate outbound call: {exc}")
        raise HTTPException(status_code=502, detail=f"Carrier error: {str(exc)}")

    # Extract Call SID from provider response
    exotel_call_obj = call_result.get("Call") or {}
    provider_call_id = exotel_call_obj.get("Sid") or generate_unique_id("call", 12)

    # Persist the Call record
    call_repo = CallRepository(db)
    now = datetime.now(timezone.utc)
    call_id = generate_unique_id("call", 10)
    call_record = Call(
        id=call_id,
        client_id=agent.client_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        phone_number_id=phone_record.id if phone_record else None,
        provider=provider_name,
        provider_call_id=provider_call_id,
        direction="OUTBOUND",
        caller_number=caller_id,
        destination_number=req.destination_number,
        status="INITIATED",
        started_at=now,
        duration_seconds=0.0,
        metadata_={"exotel_response": call_result, "custom_field": req.custom_field, "variables": req.variables or {}}
    )
    saved_call = call_repo.create(call_record)

    emitter = EventEmitter(db)
    emitter.emit(
        RuntimeEventType.CALL_INITIATED,
        session_id="",
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        client_id=agent.client_id,
        payload={"call_id": saved_call.id, "direction": "OUTBOUND", "provider_call_id": provider_call_id}
    )

    return _format_call_response(saved_call, db)


@router.get("/calls/{call_id}", response_model=CallDetailResponse)

def get_call_detail(
    call_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Retrieves full call details including lifecycle timeline events, transcript, and usage."""
    repo = CallRepository(db)
    call_obj = repo.get_by_id(call_id)
    if not call_obj:
        raise HTTPException(status_code=404, detail=f"Call '{call_id}' not found.")

    formatted_base = _format_call_response(call_obj, db)

    events_list = []
    usage_dict = {}
    conversation_list = []

    if call_obj.runtime_session_id:
        event_repo = RuntimeEventRepository(db)
        db_events = event_repo.list_by_session(call_obj.runtime_session_id)
        events_list = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "payload": e.payload_json
            }
            for e in db_events
        ]

        sess_repo = RuntimeSessionRepository(db)
        sess = sess_repo.get_by_id(call_obj.runtime_session_id)
        if sess and isinstance(sess.usage_json, dict):
            usage_dict = sess.usage_json

        # Parse conversation turns from events
        for e in db_events:
            if e.event_type == RuntimeEventType.USER_TRANSCRIPT_FINAL.value:
                txt = e.payload_json.get("text", "")
                conversation_list.append({
                    "role": "caller",
                    "content": txt,
                    "text": txt,
                    "timestamp": e.timestamp.isoformat()
                })
            elif e.event_type == RuntimeEventType.ASSISTANT_RESPONSE.value:
                txt = e.payload_json.get("text", "")
                conversation_list.append({
                    "role": "assistant",
                    "content": txt,
                    "text": txt,
                    "timestamp": e.timestamp.isoformat()
                })

        if not conversation_list and call_obj.metadata_ and isinstance(call_obj.metadata_, dict):
            cached_trans = call_obj.metadata_.get("transcript") or []
            for item in cached_trans:
                r = "assistant" if item.get("role") in ("assistant", "model") else "caller"
                c = item.get("content") or item.get("text") or ""
                conversation_list.append({
                    "role": r,
                    "content": c,
                    "text": c,
                    "timestamp": item.get("timestamp") or call_obj.created_at.isoformat()
                })

    return CallDetailResponse(
        **formatted_base.model_dump(),
        events=events_list,
        usage=usage_dict,
        conversation=conversation_list
    )


# -------------------------------------------------------------
# 5. OVERVIEW / DIAGNOSTICS
# -------------------------------------------------------------

@router.get("/overview", response_model=TelephonyOverviewResponse)
def get_telephony_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    """Returns overview statistics of telephony providers, active numbers, and call volume."""
    phone_repo = PhoneNumberRepository(db)
    call_repo = CallRepository(db)

    all_numbers = phone_repo.list_all(limit=1000)
    total_numbers = len(all_numbers)
    active_numbers = sum(1 for n in all_numbers if n.status == "ACTIVE")
    assigned_numbers = sum(1 for n in all_numbers if n.agent_id and n.agent_version_id)

    recent_calls = call_repo.list_all(limit=500)
    total_calls = len(recent_calls)
    completed_calls = sum(1 for c in recent_calls if c.status == "COMPLETED")
    active_calls_count = len(active_telephony_calls)

    has_exotel_credentials = all(
        getattr(settings, key, None)
        for key in ("EXOTEL_ACCOUNT_SID", "EXOTEL_API_KEY", "EXOTEL_API_TOKEN", "EXOTEL_WEBHOOK_SECRET")
    )
    provider_status = "CONFIGURED" if has_exotel_credentials or settings.RUNTIME_MODE == "mock" else "UNCONFIGURED"

    return TelephonyOverviewResponse(
        provider="exotel",
        provider_status=provider_status,
        total_phone_numbers=total_numbers,
        active_phone_numbers=active_numbers,
        assigned_phone_numbers=assigned_numbers,
        total_calls_today=total_calls,
        completed_calls_today=completed_calls,
        active_calls_now=active_calls_count
    )
