from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class CanonicalAgentSpec(BaseModel):
    """Canonical Agent Specification reserved for Phase 2 orchestration."""
    agent_id: str
    client_id: str
    name: str
    role: str
    description: Optional[str] = None
    prompt: str = ""
    knowledge_sources: List[Dict[str, Any]] = Field(default_factory=list)
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    integrations: List[Dict[str, Any]] = Field(default_factory=list)
    stt_provider: str = "cartesia"
    llm_provider: str = "gemini"
    tts_provider: str = "cartesia"
    telephony_provider: Optional[str] = None
    status: str = "draft"


class AgentVersionResponse(BaseModel):
    id: str
    agent_id: str
    version_number: int
    configuration_json: Dict[str, Any]
    status: str
    created_at: datetime
    created_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AgentVersionListResponse(BaseModel):
    items: List[AgentVersionResponse]
    total: int
