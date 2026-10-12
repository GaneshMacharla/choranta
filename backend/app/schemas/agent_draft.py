from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from app.schemas.agent_spec import AgentConfigurationData


class AgentDraftRequest(BaseModel):
    client_id: str
    name: str = Field(..., min_length=2, max_length=255)
    role: str = Field(..., min_length=2, max_length=255)
    call_direction: Literal["inbound", "outbound", "both"] = "inbound"
    primary_language: str = "en"
    supported_languages: List[str] = Field(default_factory=list)
    description: str = Field(..., min_length=10, max_length=4000, description="What the employee should do, in plain words")
    business_notes: str = Field(default="", max_length=4000, description="Hours, location, offers, policies")


class AgentDraftResponse(BaseModel):
    configuration: AgentConfigurationData
    draft_source: Literal["ai", "fallback"]
    message: Optional[str] = None
