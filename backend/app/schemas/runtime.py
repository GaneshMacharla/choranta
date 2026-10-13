from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ReadinessCheckRequest(BaseModel):
    agent_id: str
    agent_version_id: str


class ReadinessCheckResponse(BaseModel):
    ready: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    agent_id: str
    version_id: str
    version_number: Optional[int] = None


class CreateRuntimeSessionRequest(BaseModel):
    agent_id: str
    agent_version_id: str
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class RuntimeSessionResponse(BaseModel):
    id: str
    client_id: str
    agent_id: str
    agent_version_id: str
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    usage: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SimulateTurnRequest(BaseModel):
    input_text: Optional[str] = Field(
        default="Hello, I want to book an appointment.",
        description="Simulated user speech or audio transcript."
    )
    synthesize_audio: bool = Field(
        default=True,
        description="Run TTS for the reply. Text chat turns set this to false to skip audio synthesis."
    )


class SimulateTurnResponse(BaseModel):
    session_id: str
    transcript: str
    assistant_response: str
    audio_duration_seconds: float
    tool_calls_executed: int
    call_ended: bool = False  # the AI employee hung up; the session is ended after this turn
    usage: Dict[str, Any] = Field(default_factory=dict)
    events: List["RuntimeEventResponse"] = Field(default_factory=list)


class RuntimeEventResponse(BaseModel):
    id: str
    session_id: str
    client_id: str
    agent_id: str
    agent_version_id: str
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


SimulateTurnResponse.model_rebuild()
