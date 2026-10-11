from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.client import BusinessTypeEnum, ClientStatusEnum
from app.schemas.agent import AgentStatusEnum


class RecentClientItem(BaseModel):
    id: str
    name: str
    business_type: BusinessTypeEnum
    status: ClientStatusEnum
    agent_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecentAgentItem(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    name: str
    role: str
    status: AgentStatusEnum
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardSummaryResponse(BaseModel):
    total_clients: int
    active_clients: int
    total_agents: int
    active_agents: int
    recent_clients: List[RecentClientItem]
    recent_agents: List[RecentAgentItem]
