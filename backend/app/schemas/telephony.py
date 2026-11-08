from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# -------------------------------------------------------------
# Phone Number Schemas
# -------------------------------------------------------------

class PhoneNumberBase(BaseModel):
    phone_number: str = Field(..., description="E.164 formatted number, e.g. +14155552671")
    client_id: str
    agent_id: Optional[str] = None
    agent_version_id: Optional[str] = None
    provider: str = "vobiz"
    provider_number_id: Optional[str] = None
    country_code: str = "US"
    status: str = "ACTIVE"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreatePhoneNumberRequest(PhoneNumberBase):
    pass


class UpdatePhoneNumberRequest(BaseModel):
    agent_id: Optional[str] = None
    agent_version_id: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PhoneNumberResponse(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_version_id: Optional[str] = None
    agent_version_number: Optional[int] = None
    provider: str
    provider_number_id: Optional[str] = None
    phone_number: str
    country_code: str
    status: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    # Set for numbers bought from Choranta (rented monthly from the wallet); None for free numbers
    monthly_rent_inr: Optional[float] = None
    rental_status: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    grace_ends_at: Optional[datetime] = None


class PhoneNumberReadinessResponse(BaseModel):
    phone_number_id: str
    phone_number: str
    ready: bool
    errors: List[str]
    warnings: List[str]
    agent_id: Optional[str] = None
    agent_version_id: Optional[str] = None


# -------------------------------------------------------------
# Call Schemas
# -------------------------------------------------------------

class CallResponse(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    agent_id: str
    agent_name: Optional[str] = None
    agent_version_id: str
    agent_version_number: Optional[int] = None
    phone_number_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    provider: str
    provider_call_id: str
    direction: str
    caller_number: str
    destination_number: str
    status: str
    started_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: float
    termination_reason: Optional[str] = None
    recording_url: Optional[str] = None
    has_recording: bool = False
    cost: Optional[Dict[str, Any]] = None  # estimated INR cost: total, per_minute, breakdown, rates
    transcript_summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CallDetailResponse(CallResponse):
    events: List[Dict[str, Any]] = Field(default_factory=list)
    usage: Dict[str, Any] = Field(default_factory=dict)
    conversation: List[Dict[str, Any]] = Field(default_factory=list)


class InitiateOutboundCallRequest(BaseModel):
    """
    Call from a provisioned number (phone_number_id; uses its assigned agent) or directly as an
    agent (agent_id + agent_version_id; caller ID is the client's own active number, or VOBIZ_CALLER_ID for test calls).
    """
    phone_number_id: Optional[str] = Field(None, description="ID of the provisioned PhoneNumber in Choranta Studio")
    agent_id: Optional[str] = Field(None, description="Agent to place the call as (when not using phone_number_id)")
    agent_version_id: Optional[str] = Field(None, description="Published AgentVersion to run (with agent_id)")
    caller_id: Optional[str] = Field(None, description="Which of the client's numbers to call from (test calls: defaults to VOBIZ_CALLER_ID)")
    destination_number: str = Field(..., description="The customer phone number to call (e.g. 09876543210 or +919876543210)")
    custom_field: Optional[str] = Field(None, description="Optional tracking metadata string")
    is_test: bool = Field(False, description="Test call from the AI Employee's Tests step: never billed or blocked by the wallet")
    variables: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom lead/campaign variables (e.g. user_name, property_viewed, enquiry_budget) to ground the agent")



# -------------------------------------------------------------
# Overview / Diagnostics Schemas
# -------------------------------------------------------------

class TelephonyOverviewResponse(BaseModel):
    provider: str
    provider_status: str  # CONFIGURED, UNCONFIGURED, ERROR
    total_phone_numbers: int
    active_phone_numbers: int
    assigned_phone_numbers: int
    total_calls_today: int
    completed_calls_today: int
    active_calls_now: int
