from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user, get_current_user_from_header_or_query
from app.models.user import User
from app.schemas.catalog import (
    KnowledgeSourceResponse,
    ToolResponse,
    IntegrationResponse,
    VoiceResponse
)

from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.tool_repository import ToolRepository
from app.repositories.integration_repository import IntegrationRepository
from app.repositories.agent_repository import AgentRepository
from app.services.voice_service import VoiceService

router = APIRouter(tags=["Catalogs & Attachments"])


# ==========================================
# KNOWLEDGE SOURCES
# ==========================================

@router.get("/knowledge", response_model=List[KnowledgeSourceResponse])
def list_knowledge_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """The shared knowledge library (entries written inside one AI employee aren't listed here)."""
    repo = KnowledgeRepository(db)
    return [k for k in repo.list_all() if not getattr(k, "owner_agent_id", None)]


@router.get("/agents/{agent_id}/knowledge", response_model=List[KnowledgeSourceResponse])
def get_agent_knowledge(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List knowledge sources attached to an AI Employee."""
    agent = AgentRepository(db).get_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return KnowledgeRepository(db).get_for_agent(agent_id)


class AgentKnowledgeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field("NOTES", pattern="^(NOTES|FAQ)$")
    content: str = Field(..., min_length=1, max_length=20000)


def _own_entry(db: Session, agent_id: str, knowledge_id: str):
    from app.models.knowledge_source import KnowledgeSource
    entry = db.get(KnowledgeSource, knowledge_id)
    if not entry or entry.owner_agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Knowledge entry not found for this AI Employee.")
    return entry


@router.post("/agents/{agent_id}/knowledge", response_model=KnowledgeSourceResponse, status_code=201)
def create_agent_knowledge(agent_id: str, req: AgentKnowledgeRequest, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """Writes knowledge for one AI Employee (notes or FAQ) and attaches it. Used on its next conversation."""
    from app.core.security import generate_unique_id
    from app.models.knowledge_source import KnowledgeSource
    if not AgentRepository(db).get_by_id(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    entry = KnowledgeSource(id=generate_unique_id("knw", 12), name=req.name.strip(), type=req.type, status="READY",
                            content=req.content.strip(), owner_agent_id=agent_id, meta={})
    db.add(entry)
    db.commit()
    KnowledgeRepository(db).attach_to_agent(agent_id, entry.id)
    db.refresh(entry)
    return entry


@router.put("/agents/{agent_id}/knowledge/{knowledge_id}", response_model=KnowledgeSourceResponse)
def update_agent_knowledge(agent_id: str, knowledge_id: str, req: AgentKnowledgeRequest, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    entry = _own_entry(db, agent_id, knowledge_id)
    entry.name, entry.type, entry.content = req.name.strip(), req.type, req.content.strip()
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/agents/{agent_id}/knowledge/{knowledge_id}")
def attach_knowledge_to_agent(
    agent_id: str,
    knowledge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Attach a knowledge source to an AI Employee."""
    repo = KnowledgeRepository(db)
    source = repo.get_by_id(knowledge_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{knowledge_id}' not found.")
    agent = AgentRepository(db).get_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    # An AI employee only uses its own client's knowledge
    if getattr(source, "client_id", None) and source.client_id != agent.client_id:
        raise HTTPException(status_code=400, detail="That knowledge belongs to another client.")
    repo.attach_to_agent(agent_id, knowledge_id)
    return {"message": "Knowledge source attached successfully."}


@router.delete("/agents/{agent_id}/knowledge/{knowledge_id}")
def detach_knowledge_from_agent(
    agent_id: str,
    knowledge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Detach a library entry from an AI Employee; an entry written inside it is deleted."""
    from app.models.knowledge_source import KnowledgeSource
    repo = KnowledgeRepository(db)
    repo.detach_from_agent(agent_id, knowledge_id)
    entry = db.get(KnowledgeSource, knowledge_id)
    if entry and entry.owner_agent_id == agent_id:
        db.delete(entry)
        db.commit()
    return {"message": "Knowledge source detached successfully."}


# ==========================================
# TOOLS
# ==========================================

@router.get("/tools", response_model=List[ToolResponse])
def list_tools_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List system available tools and action capabilities."""
    repo = ToolRepository(db)
    return repo.list_all()


@router.get("/agents/{agent_id}/tools", response_model=List[ToolResponse])
def get_agent_tools(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List tools enabled for an AI Employee."""
    agent = AgentRepository(db).get_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return ToolRepository(db).get_for_agent(agent_id)


@router.post("/agents/{agent_id}/tools/{tool_id}")
def enable_tool_for_agent(
    agent_id: str,
    tool_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enable a tool for an AI Employee."""
    repo = ToolRepository(db)
    if not repo.get_by_id(tool_id):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found.")
    if not AgentRepository(db).get_by_id(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    repo.attach_to_agent(agent_id, tool_id)
    return {"message": "Tool enabled successfully."}


@router.delete("/agents/{agent_id}/tools/{tool_id}")
def disable_tool_for_agent(
    agent_id: str,
    tool_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Disable a tool for an AI Employee."""
    repo = ToolRepository(db)
    repo.detach_from_agent(agent_id, tool_id)
    return {"message": "Tool disabled successfully."}


# ==========================================
# INTEGRATIONS
# ==========================================

@router.get("/integrations", response_model=List[IntegrationResponse])
def list_integrations_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List external integration capabilities."""
    repo = IntegrationRepository(db)
    return repo.list_all()


@router.get("/agents/{agent_id}/integrations", response_model=List[IntegrationResponse])
def get_agent_integrations(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List integrations configured for an AI Employee."""
    agent = AgentRepository(db).get_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return IntegrationRepository(db).get_for_agent(agent_id)


@router.post("/agents/{agent_id}/integrations/{integration_id}")
def attach_integration_to_agent(
    agent_id: str,
    integration_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Attach an integration reference to an AI Employee."""
    repo = IntegrationRepository(db)
    if not repo.get_by_id(integration_id):
        raise HTTPException(status_code=404, detail=f"Integration '{integration_id}' not found.")
    if not AgentRepository(db).get_by_id(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    repo.attach_to_agent(agent_id, integration_id)
    return {"message": "Integration attached successfully."}


@router.delete("/agents/{agent_id}/integrations/{integration_id}")
def detach_integration_from_agent(
    agent_id: str,
    integration_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Detach an integration reference from an AI Employee."""
    repo = IntegrationRepository(db)
    repo.detach_from_agent(agent_id, integration_id)
    return {"message": "Integration detached successfully."}


# ==========================================
# SARVAM VOICES CATALOG (voices in use; Cartesia below is kept but not shown in the Studio)
# ==========================================

@router.get("/catalogs/sarvam-voices")
def list_sarvam_voices(language: Optional[str] = Query(None, description="Put voices recommended for this language first"),
                       current_user: User = Depends(get_current_user)):
    """Sarvam Bulbul voices for the Studio voice picker, best first."""
    from app.services import sarvam_voices
    return sarvam_voices.list_voices(language)


@router.get("/catalogs/sarvam-voices/{voice_id}/preview")
def preview_sarvam_voice(voice_id: str, language: Optional[str] = Query(None, description="Agent language, e.g. 'te'"),
                         current_user: User = Depends(get_current_user)):
    """Short WAV sample of a Sarvam voice in the agent's language (generated once, then cached)."""
    from app.services import sarvam_voices
    try:
        audio = sarvam_voices.preview_wav(voice_id, language)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except sarvam_voices.VoicePreviewUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})


# ==========================================
# CARTESIA VOICES CATALOG
# ==========================================

@router.get("/voices", response_model=List[VoiceResponse])
@router.get("/catalogs/voices", response_model=List[VoiceResponse])
def list_voices_catalog(
    query: Optional[str] = Query(None, description="Search voice by name or description"),
    gender: Optional[str] = Query(None, description="Filter by gender ('feminine' or 'masculine')"),
    language: Optional[str] = Query(None, description="Filter by language code (e.g. 'en')"),
    current_user: User = Depends(get_current_user)
):
    """
    List voices available in Cartesia workspace.
    Supports filtering by search query, gender, and language.
    """
    return VoiceService.list_cartesia_voices(
        query=query,
        gender=gender,
        language=language
    )


@router.get("/voices/{voice_id}/preview")
@router.get("/catalogs/voices/{voice_id}/preview")
def preview_voice_audio(
    voice_id: str,
    text: Optional[str] = Query(None, description="Custom preview text"),
    language: Optional[str] = Query(None, description="Agent language, e.g. 'te': the preview is spoken in it"),
    token: Optional[str] = Query(None, description="JWT token for direct media playback"),
    current_user: User = Depends(get_current_user_from_header_or_query)
):
    """
    Synthesize and stream a short preview WAV sample for the specified Cartesia voice.
    """
    from app.services.voice_service import CartesiaPreviewUnavailable
    try:
        wav_bytes = VoiceService.get_voice_preview_wav(voice_id=voice_id, sample_text=text, language=language)
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'inline; filename="preview_{voice_id}.wav"',
                "Cache-Control": "public, max-age=86400"
            }
        )
    except CartesiaPreviewUnavailable as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate voice preview: {str(e)}"
        )


# ==========================================
# AGENT TEMPLATES CATALOG
# ==========================================

@router.get("/agent-templates")
@router.get("/catalogs/agent-templates")
def list_agent_templates(
    current_user: User = Depends(get_current_user)
):
    """List preconfigured production-ready voice agent templates."""
    from app.services.agent_templates import get_all_agent_templates
    return get_all_agent_templates()


@router.get("/agent-templates/{template_id}")
@router.get("/catalogs/agent-templates/{template_id}")
def get_agent_template(
    template_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get single preconfigured voice agent template with preview metadata."""
    from app.services.agent_templates import get_agent_template_by_id
    tpl = get_agent_template_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Agent template '{template_id}' not found.")
    return tpl

