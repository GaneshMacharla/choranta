from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user, get_current_user_from_header_or_query
from app.models.user import User
from app.models.agent import Agent
from app.schemas.catalog import (
    KnowledgeSourceResponse,
    ToolResponse,
    IntegrationResponse,
    AttachedItemIds,
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
    """List available reference knowledge sources."""
    repo = KnowledgeRepository(db)
    return repo.list_all()


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


@router.post("/agents/{agent_id}/knowledge/{knowledge_id}")
def attach_knowledge_to_agent(
    agent_id: str,
    knowledge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Attach a knowledge source to an AI Employee."""
    repo = KnowledgeRepository(db)
    if not repo.get_by_id(knowledge_id):
        raise HTTPException(status_code=404, detail=f"Knowledge source '{knowledge_id}' not found.")
    if not AgentRepository(db).get_by_id(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    repo.attach_to_agent(agent_id, knowledge_id)
    return {"message": "Knowledge source attached successfully."}


@router.delete("/agents/{agent_id}/knowledge/{knowledge_id}")
def detach_knowledge_from_agent(
    agent_id: str,
    knowledge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Detach a knowledge source from an AI Employee."""
    repo = KnowledgeRepository(db)
    repo.detach_from_agent(agent_id, knowledge_id)
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
    token: Optional[str] = Query(None, description="JWT token for direct media playback"),
    current_user: User = Depends(get_current_user_from_header_or_query)
):
    """
    Synthesize and stream a short preview WAV sample for the specified Cartesia voice.
    """
    try:
        wav_bytes = VoiceService.get_voice_preview_wav(voice_id=voice_id, sample_text=text)
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'inline; filename="preview_{voice_id}.wav"',
                "Cache-Control": "public, max-age=86400"
            }
        )
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

