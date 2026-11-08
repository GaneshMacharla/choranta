from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_operator
from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_configuration import AgentConfiguration
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.campaign import CampaignRecipient
from app.models.client import Client
from app.models.phone_number import PhoneNumber
from app.models.runtime_event import RuntimeEvent
from app.models.runtime_session import RuntimeSession
from app.services.agent_spec_builder import AgentSpecBuilder
from app.schemas.agent_spec import AgentConfigurationData
from app.runtime.runtime import AgentRuntime
from app.runtime.providers.registry import default_registry
from app.services.call_status import apply_call_status

router = APIRouter(prefix="/mock", tags=["Mock Environment"])


class MockCallRequest(BaseModel):
    agent_id: str
    agent_version_id: str
    utterances: List[str] = Field(min_length=1, max_length=20)
    caller_number: str = "+15550209999"


class CompletePendingCallsRequest(BaseModel):
    status: Literal["completed", "no-answer", "busy", "failed"] = "completed"
    duration_seconds: float = Field(30.0, ge=0, le=3600)
    campaign_id: Optional[str] = None
    call_ids: Optional[List[str]] = None
    # What post-call extraction would have found (answered calls only); fills the client's insights
    interest: Optional[Literal["interested", "callback", "not_interested", "do_not_call", "unclear"]] = None
    summary: Optional[str] = Field(None, max_length=300)
    callback_time: Optional[str] = Field(None, max_length=120)
    outputs: Optional[Dict[str, Any]] = None

MOCK_CLIENTS = (
    {
        "id": "mock_cli_acme_health",
        "name": "Acme Health Clinic",
        "business_type": "CLINIC",
        "description": "Deterministic clinic fixture for mock voice-agent testing.",
        "contact_name": "Dr. Maya Rao",
        "contact_email": "mock@acme-health.test",
        "contact_phone": "+15550001001",
        "timezone": "America/New_York",
    },
    {
        "id": "mock_cli_ora_salon",
        "name": "Ora Salon",
        "business_type": "SALON",
        "description": "Deterministic salon fixture for mock scheduling flows.",
        "contact_name": "Nisha Kapoor",
        "contact_email": "mock@ora-salon.test",
        "contact_phone": "+15550001002",
        "timezone": "Asia/Kolkata",
    },
    {
        "id": "mock_cli_horizon_realty",
        "name": "Horizon Realty",
        "business_type": "REAL_ESTATE",
        "description": "Deterministic real-estate fixture for mock lead capture.",
        "contact_name": "Alex Morgan",
        "contact_email": "mock@horizon-realty.test",
        "contact_phone": "+15550001003",
        "timezone": "America/Los_Angeles",
    },
)


def _require_mock_mode() -> None:
    if settings.RUNTIME_MODE != "mock":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mock environment operations require server RUNTIME_MODE=mock.",
        )


def _configuration(client: Client, name: str, role: str) -> AgentConfigurationData:
    return AgentConfigurationData.model_validate(
        {
            "identity": {
                "name": name,
                "organization": client.name,
                "persona": "warm, concise, and reliable",
            },
            "business_context": {
                "business_name": client.name,
                "business_type": client.business_type,
                "location": client.timezone,
                "business_hours": {"monday_friday": "09:00 - 18:00", "sunday": "closed"},
                "contact_information": {"name": client.contact_name, "email": client.contact_email},
            },
            "instructions": {
                "primary_goal": f"Help callers of {client.name} with common {role.lower()} requests.",
                "responsibilities": ["Greet the caller", "Answer common questions", "Escalate when the request is outside scope"],
                "rules": ["Be concise", "Confirm important details before taking action"],
                "restrictions": ["Do not claim a real booking or external action was completed"],
                "escalation_rules": ["Offer a human handoff for unknown or urgent requests"],
            },
            "conversation": {
                "tone": "professional and friendly",
                "verbosity": "concise",
                "greeting": f"Thank you for calling {client.name}. How may I help you today?",
                "farewell": "Thank you. Have a great day.",
                "interruption_behavior": "pause_and_listen",
            },
            "languages": {"primary": "en", "supported": ["en"]},
            "knowledge_sources": [],
            "tools": ["check_availability", "book_appointment", "cancel_appointment", "create_lead"],
            "integrations": [],
            "voice": {"provider": "cartesia", "voice_id": None, "language": "en", "speed": 1.0},
            "providers": {"stt": "cartesia", "llm": "gemini", "tts": "cartesia", "telephony": "mock_telephony"},
        }
    )


def seed_mock_environment(db: Session) -> Dict[str, Any]:
    _require_mock_mode()
    clients: List[Client] = []
    for data in MOCK_CLIENTS:
        client = db.query(Client).filter(Client.id == data["id"]).first()
        if not client:
            client = Client(**data)
            db.add(client)
            db.flush()
        clients.append(client)

    agents: List[Agent] = []
    now = datetime.now(timezone.utc)
    for index, client in enumerate(clients):
        agent_id = f"mock_agt_{client.id.removeprefix('mock_cli_')}"
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            agent = Agent(
                id=agent_id,
                client_id=client.id,
                name=f"{client.name} Receptionist",
                role="Mock Voice Receptionist",
                description="Simulated agent. No external provider or business action is used.",
                status="READY",
            )
            db.add(agent)
            db.flush()
        agents.append(agent)

        draft = _configuration(client, agent.name, "receptionist")
        config = db.query(AgentConfiguration).filter(AgentConfiguration.agent_id == agent.id).first()
        if not config:
            config = AgentConfiguration(
                id=f"mock_cfg_{index + 1}",
                agent_id=agent.id,
                configuration_data=draft.model_dump(),
            )
            db.add(config)
        else:
            config.configuration_data = draft.model_dump()

        version_id = f"mock_agtv_{index + 1}"
        version = db.query(AgentVersion).filter(AgentVersion.id == version_id).first()
        if not version:
            spec = AgentSpecBuilder.build_from_draft(agent, client, draft, [], draft.tools, [])
            version = AgentVersion(
                id=version_id,
                agent_id=agent.id,
                version_number=1,
                configuration_json=spec.model_dump(),
                status="PUBLISHED",
                created_at=now,
            )
            db.add(version)
            db.flush()

        phone_id = f"mock_phn_{index + 1}"
        phone = db.query(PhoneNumber).filter(PhoneNumber.id == phone_id).first()
        if not phone:
            phone = PhoneNumber(
                id=phone_id,
                client_id=client.id,
                agent_id=agent.id,
                agent_version_id=version.id,
                provider="mock_telephony",
                provider_number_id=f"mock-number-{index + 1}",
                phone_number=f"+15550100{index + 1:02d}",
                country_code="US",
                status="ACTIVE",
                metadata_={"mock": True, "label": "SIMULATED NUMBER"},
            )
            db.add(phone)
            db.flush()

        call_id = f"mock_call_{index + 1}"
        if not db.query(Call).filter(Call.id == call_id).first():
            started = now - timedelta(minutes=index + 4)
            db.add(Call(
                id=call_id,
                client_id=client.id,
                agent_id=agent.id,
                agent_version_id=version.id,
                phone_number_id=phone.id,
                provider="mock_telephony",
                provider_call_id=f"mock-provider-call-{index + 1}",
                direction="INBOUND",
                caller_number=f"+15550200{index + 1:02d}",
                destination_number=phone.phone_number,
                status="COMPLETED",
                started_at=started,
                answered_at=started,
                ended_at=started + timedelta(seconds=42 + index * 11),
                duration_seconds=42 + index * 11,
                termination_reason="mock_completed",
                transcript_summary="SIMULATED: Caller asked about availability and received a deterministic response.",
                metadata_={"mock": True, "usage": {"stt_seconds": 4.2, "tts_seconds": 6.8, "llm_input_tokens": 120, "llm_output_tokens": 38}, "simulated_cost_usd": 0.0},
            ))

    db.commit()
    return {"mode": "mock", "clients": len(clients), "agents": len(agents), "label": "MOCK DATA / NO EXTERNAL CALLS"}


@router.get("/environment")
def mock_environment_status(current_user=Depends(require_operator)) -> Dict[str, Any]:
    return {
        "mode": settings.RUNTIME_MODE,
        "mock": settings.RUNTIME_MODE == "mock",
        "external_calls_allowed": settings.RUNTIME_MODE == "real",
        "label": "MOCK ENVIRONMENT - NO EXTERNAL PROVIDER CALLS" if settings.RUNTIME_MODE == "mock" else "REAL PROVIDER ENVIRONMENT",
    }


@router.post("/seed")
def seed_environment(db: Session = Depends(get_db), current_user=Depends(require_operator)) -> Dict[str, Any]:
    return seed_mock_environment(db)


@router.post("/reset")
def reset_environment(db: Session = Depends(get_db), current_user=Depends(require_admin)) -> Dict[str, Any]:
    _require_mock_mode()
    for model in (Call, RuntimeEvent, RuntimeSession, PhoneNumber, AgentVersion, AgentConfiguration, Agent, Client):
        db.query(model).filter(model.id.like("mock_%")).delete(synchronize_session=False)
    db.commit()
    return {"mode": "mock", "reset": True, "label": "MOCK DATA RESET"}


@router.get("/analytics")
def mock_analytics(db: Session = Depends(get_db), current_user=Depends(require_operator)) -> Dict[str, Any]:
    """Return simulated usage and cost estimates without touching production billing."""
    _require_mock_mode()
    calls = db.query(Call).filter(Call.id.like("mock_%")).all()
    completed = [call for call in calls if call.status == "COMPLETED"]
    usage = {"stt_seconds": 0.0, "tts_seconds": 0.0, "llm_input_tokens": 0, "llm_output_tokens": 0}
    for call in calls:
        values = (call.metadata_ or {}).get("usage", {}) if isinstance(call.metadata_, dict) else {}
        for key in usage:
            usage[key] += values.get(key, 0) or 0

    stt_minutes = usage["stt_seconds"] / 60
    tts_minutes = usage["tts_seconds"] / 60
    cost = {
        "stt_usd": round(stt_minutes * settings.MOCK_STT_PRICE_PER_MINUTE, 6),
        "tts_usd": round(tts_minutes * settings.MOCK_TTS_PRICE_PER_MINUTE, 6),
        "llm_usd": round(
            (usage["llm_input_tokens"] / 1_000_000) * settings.MOCK_LLM_INPUT_PRICE_PER_MILLION_TOKENS
            + (usage["llm_output_tokens"] / 1_000_000) * settings.MOCK_LLM_OUTPUT_PRICE_PER_MILLION_TOKENS,
            6,
        ),
    }
    cost["total_usd"] = round(sum(cost.values()), 6)
    return {
        "label": "SIMULATED USAGE / ESTIMATED COST",
        "mock": True,
        "calls": {"total": len(calls), "completed": len(completed), "failed": len(calls) - len(completed)},
        "duration_seconds": round(sum(call.duration_seconds or 0 for call in calls), 2),
        "usage": usage,
        "cost": cost,
        "pricing": {
            "stt_per_minute": settings.MOCK_STT_PRICE_PER_MINUTE,
            "tts_per_minute": settings.MOCK_TTS_PRICE_PER_MINUTE,
            "llm_input_per_million_tokens": settings.MOCK_LLM_INPUT_PRICE_PER_MILLION_TOKENS,
            "llm_output_per_million_tokens": settings.MOCK_LLM_OUTPUT_PRICE_PER_MILLION_TOKENS,
        },
        "billing_excluded": True,
    }


@router.post("/calls/simulate")
def simulate_mock_call(
    payload: MockCallRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    """Run a multi-turn simulated call through the actual runtime orchestration."""
    _require_mock_mode()
    agent = db.query(Agent).filter(Agent.id == payload.agent_id).first()
    version = db.query(AgentVersion).filter(AgentVersion.id == payload.agent_version_id).first()
    if not agent or not version or version.agent_id != agent.id or version.status != "PUBLISHED":
        raise HTTPException(status_code=404, detail="A published mock agent version is required.")

    runtime = AgentRuntime(db, registry=default_registry)
    session = runtime.start_session(agent.id, version.id, {"mock": True, "origin": "mock_call_simulator"})
    turns: List[Dict[str, Any]] = []
    try:
        for utterance in payload.utterances:
            result = runtime.process_turn(session.id, utterance)
            turns.append({
                "transcript": result["transcript"],
                "assistant_response": result["assistant_response"],
                "tool_calls_executed": result["tool_calls_executed"],
                "usage": result["usage"],
            })
        completed = runtime.end_session(session.id)
        now = datetime.now(timezone.utc)
        call = Call(
            id=generate_unique_id("mock_call_"),
            client_id=agent.client_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            provider="mock_telephony",
            provider_call_id=generate_unique_id("mock_provider_"),
            direction="INBOUND",
            caller_number=payload.caller_number,
            destination_number="+15550100000",
            status="COMPLETED",
            started_at=completed.started_at or now,
            answered_at=completed.started_at or now,
            ended_at=completed.ended_at or now,
            duration_seconds=(completed.usage_json or {}).get("session_duration_seconds", 0.0),
            termination_reason="mock_completed",
            transcript_summary="SIMULATED: " + " | ".join(turn["transcript"] for turn in turns),
            metadata_={"mock": True, "simulated_cost_usd": 0.0, "turns": turns},
        )
        db.add(call)
        db.commit()
        events = db.query(RuntimeEvent).filter(RuntimeEvent.session_id == session.id).order_by(RuntimeEvent.timestamp.asc()).all()
        return {
            "label": "SIMULATED CALL",
            "call_id": call.id,
            "session_id": session.id,
            "status": completed.status,
            "turns": turns,
            "event_count": len(events),
            "usage": completed.usage_json or {},
            "billing_excluded": True,
        }
    except Exception:
        if session.status == "ACTIVE":
            try:
                runtime.end_session(session.id)
            except Exception:
                pass
        raise


@router.post("/calls/complete-pending")
def complete_pending_mock_calls(
    payload: CompletePendingCallsRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    """
    Ends outbound calls placed through the mock carrier, as the carrier's hangup callback would.
    The mock carrier never reports back, so without this campaign recipients stay DIALING.
    Narrow it with campaign_id or call_ids; the dialer picks up the outcomes on its next tick.
    """
    _require_mock_mode()
    query = db.query(Call).filter(
        Call.direction == "OUTBOUND",
        Call.status == "INITIATED",
        Call.provider_call_id.like(r"mock\_call\_%", escape="\\"),
    )
    if payload.call_ids:
        query = query.filter(Call.id.in_(payload.call_ids))
    if payload.campaign_id:
        recipient_calls = db.query(CampaignRecipient.last_call_id).filter(
            CampaignRecipient.campaign_id == payload.campaign_id
        )
        query = query.filter(Call.id.in_(recipient_calls))

    calls = query.all()
    duration = payload.duration_seconds if payload.status == "completed" else 0.0
    extracted = {
        k: v for k, v in (("interest", payload.interest), ("summary", payload.summary),
                          ("callback_time", payload.callback_time), ("outputs", payload.outputs)) if v is not None
    }
    for call in calls:
        if extracted and payload.status == "completed":
            call.metadata_ = {**(call.metadata_ or {}), **extracted, "outputs_status": "done"}
        apply_call_status(db, call, payload.status, duration)
    return {
        "label": "SIMULATED CALL STATUS",
        "status": payload.status,
        "updated": len(calls),
        "call_ids": [call.id for call in calls],
    }
