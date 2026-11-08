from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class CallingWindow(BaseModel):
    start_min: int = Field(..., ge=0, le=1440, description="Minutes after local midnight, e.g. 600 = 10:00")
    end_min: int = Field(..., ge=0, le=1440)


class CampaignSettings(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    purpose: Literal["SERVICE", "PROMOTIONAL"] = "SERVICE"
    kind: Literal["BULK", "TRIGGER"] = "BULK"  # TRIGGER = always-on website leads
    agent_id: str
    agent_version_id: str
    provider: str = "vobiz"
    caller_number_ids: List[str] = Field(default_factory=list)
    timezone: Optional[str] = None  # defaults to the client's timezone
    windows: List[CallingWindow] = Field(default_factory=lambda: [CallingWindow(start_min=600, end_min=1140)])
    days: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    start_at: Optional[datetime] = None  # UTC; None = start on launch
    max_concurrent: int = Field(1, ge=1, le=100)
    retry_max: int = Field(2, ge=0, le=3)
    retry_intervals_min: List[int] = Field(default_factory=lambda: [30, 60])
    retry_on: List[str] = Field(default_factory=lambda: ["no-answer", "busy", "failed"])
    webhook_url: Optional[str] = Field(None, max_length=2000)
    # Campaign details every call receives, keyed by the agent's input variable names (e.g. course_name)
    variables: Dict[str, str] = Field(default_factory=dict)


class CreateCampaignRequest(CampaignSettings):
    client_id: Optional[str] = None  # required for internal users; portal users use their own client


class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    purpose: Optional[Literal["SERVICE", "PROMOTIONAL"]] = None
    agent_id: Optional[str] = None
    agent_version_id: Optional[str] = None
    caller_number_ids: Optional[List[str]] = None
    timezone: Optional[str] = None
    windows: Optional[List[CallingWindow]] = None
    days: Optional[List[int]] = None
    start_at: Optional[datetime] = None
    max_concurrent: Optional[int] = Field(None, ge=1, le=100)
    retry_max: Optional[int] = Field(None, ge=0, le=3)
    retry_intervals_min: Optional[List[int]] = None
    retry_on: Optional[List[str]] = None
    webhook_url: Optional[str] = Field(None, max_length=2000)  # "" removes the webhook
    variables: Optional[Dict[str, str]] = None


class CsvRecipientsRequest(BaseModel):
    csv_text: str = Field(..., max_length=5_000_000)


class LeadRecipientsRequest(BaseModel):
    lead_ids: List[str] = Field(..., min_length=1, max_length=10_000)


class LaunchCampaignRequest(BaseModel):
    consent: bool = False


class DoNotCallRequest(BaseModel):
    phone: str
    note: Optional[str] = None
    client_id: Optional[str] = None


class CampaignStats(BaseModel):
    total: int = 0
    pending: int = 0
    dialing: int = 0
    retry_wait: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    answered: int = 0
    done: int = 0
    outcomes: Dict[str, int] = Field(default_factory=dict)
    answer_rate: Optional[float] = None
    attempts: int = 0
    minutes: float = 0.0
    collected: Dict[str, Dict[str, int]] = Field(default_factory=dict)


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    client_name: Optional[str] = None
    name: str
    purpose: str
    kind: str = "BULK"
    agent_id: str
    agent_name: Optional[str] = None
    agent_version_id: str
    agent_version_number: Optional[int] = None
    provider: str
    caller_number_ids: List[str]
    caller_numbers: List[str] = Field(default_factory=list)
    status: str
    pause_reason: Optional[str] = None
    timezone: str
    windows: List[CallingWindow]
    days: List[int]
    start_at: Optional[datetime] = None
    max_concurrent: int
    retry_max: int
    retry_intervals_min: List[int]
    retry_on: List[str]
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    launched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    stats: CampaignStats = Field(default_factory=CampaignStats)


class RecipientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phone: str
    name: Optional[str] = None
    variables: Dict[str, Any] = Field(default_factory=dict)
    lead_id: Optional[str] = None
    source: Optional[str] = None
    status: str
    attempts: int
    next_attempt_at: Optional[datetime] = None
    last_call_id: Optional[str] = None
    last_dialed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    updated_at: datetime


class RecipientPage(BaseModel):
    items: List[RecipientResponse]
    total: int


class RecipientImportResult(BaseModel):
    added: int
    already_present: int
    invalid: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_count: int = 0
    duplicates: int = 0


class CsvPreviewResponse(BaseModel):
    valid: int
    invalid: List[Dict[str, Any]]
    invalid_count: int
    duplicates: int
    phone_column: Optional[str] = None
    variable_names: List[str]
    sample: List[Dict[str, Any]]


class DoNotCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    phone: str
    source: str
    note: Optional[str] = None
    created_at: datetime
