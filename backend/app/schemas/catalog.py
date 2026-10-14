from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class KnowledgeSourceResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    description: Optional[str] = None
    content: Optional[str] = None
    owner_agent_id: Optional[str] = None
    client_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def map_orm_metadata(cls, data: Any) -> Any:
        if hasattr(data, "meta"):
            return {
                "id": data.id,
                "name": data.name,
                "type": data.type,
                "status": data.status,
                "description": data.description,
                "content": getattr(data, "content", None),
                "owner_agent_id": getattr(data, "owner_agent_id", None),
                "client_id": getattr(data, "client_id", None),
                "metadata": data.meta if data.meta is not None else {},
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data


class ToolResponse(BaseModel):
    id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    executor_type: str
    timeout: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IntegrationResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: str
    provider: str
    connection_status: str
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def map_orm_metadata(cls, data: Any) -> Any:
        if hasattr(data, "meta"):
            return {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "category": data.category,
                "provider": data.provider,
                "connection_status": data.connection_status,
                "metadata": data.meta if data.meta is not None else {},
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data


class AttachedItemIds(BaseModel):
    ids: List[str]


class VoiceResponse(BaseModel):
    id: str
    name: str
    gender: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None
    tagline: Optional[str] = None
    country: Optional[str] = None
    preview_url: Optional[str] = None
    is_default: bool = False
    provider: str = "cartesia"

    model_config = ConfigDict(from_attributes=True)

