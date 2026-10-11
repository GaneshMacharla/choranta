from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class AgentStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    TESTING = "TESTING"
    READY = "READY"
    DEPLOYED = "DEPLOYED"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
            return cls.DRAFT
        return cls.DRAFT


class AgentBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Agent display name (e.g., Hospital Receptionist)")
    role: str = Field(..., min_length=2, max_length=255, description="Operational role (e.g., AI Receptionist)")
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Agent name cannot be blank")
        return clean

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Role cannot be blank")
        return clean


class AgentCreate(AgentBase):
    client_id: str = Field(..., description="ID of the client this agent belongs to")
    template_id: Optional[str] = Field(None, description="Optional preconfigured template ID to initialize configuration from")


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    role: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[AgentStatusEnum] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Agent name cannot be blank")
            return clean
        return None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Role cannot be blank")
            return clean
        return None


class AgentResponse(AgentBase):
    id: str
    client_id: str
    client_name: Optional[str] = None
    status: AgentStatusEnum
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentListResponse(BaseModel):
    items: List[AgentResponse]
    total: int
