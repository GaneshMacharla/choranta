from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.agent_version import AgentVersionResponse, AgentVersionListResponse


class AgentMetaSpec(BaseModel):
    id: str
    name: str
    role: str
    description: Optional[str] = None


class IdentitySpec(BaseModel):
    name: str = Field(default="", description="Name used by the AI voice persona (e.g. Anu)")
    organization: str = Field(default="", description="Organization the AI employee represents")
    persona: str = Field(default="professional and friendly", description="Personality description")


class BusinessContextSpec(BaseModel):
    business_name: str = ""
    business_type: str = ""
    business_hours: Dict[str, Any] = Field(default_factory=dict)
    location: str = ""
    contact_information: Dict[str, Any] = Field(default_factory=dict)


class InstructionsSpec(BaseModel):
    primary_goal: str = Field(default="", description="Core goal of the agent")
    responsibilities: List[str] = Field(default_factory=list, description="Key duties and functions")
    rules: List[str] = Field(default_factory=list, description="Behavioral rules to strictly follow")
    restrictions: List[str] = Field(default_factory=list, description="Explicit boundaries and prohibitions")
    escalation_rules: List[str] = Field(default_factory=list, description="Conditions for escalating to human")


class ConversationSpec(BaseModel):
    tone: str = Field(default="professional", description="Tone (e.g. professional, friendly, warm, casual)")
    verbosity: str = Field(default="concise", description="Verbosity (concise, balanced, detailed)")
    greeting: str = Field(default="", description="Opening phrase spoken when answering")
    farewell: str = Field(default="", description="Closing phrase when concluding session")
    interruption_behavior: str = Field(default="pause_and_listen", description="How to handle caller interruption")
    fallback_response: Optional[str] = Field(default="I understand. How else may I assist you?", description="Fallback response")


class LanguagesSpec(BaseModel):
    primary: str = Field(default="en", description="Primary spoken language code")
    supported: List[str] = Field(default_factory=lambda: ["en"], description="List of supported language codes")


class KnowledgeSpec(BaseModel):
    sources: List[str] = Field(default_factory=list, description="List of attached knowledge source IDs")


class ToolsSpec(BaseModel):
    enabled: List[str] = Field(default_factory=list, description="List of enabled tool IDs")


class IntegrationsSpec(BaseModel):
    enabled: List[str] = Field(default_factory=list, description="List of enabled integration IDs")


class VariableSpec(BaseModel):
    name: str
    description: str = ""
    data_type: str = "string"
    default_value: Optional[Any] = None
    required: bool = False
    source: Optional[str] = None
    extraction_instructions: str = ""

    model_config = ConfigDict(extra="ignore")


class VariablesSpec(BaseModel):
    inputs: List[VariableSpec] = Field(default_factory=list)
    outputs: List[VariableSpec] = Field(default_factory=list)


class VoiceSpec(BaseModel):
    provider: str = Field(default="cartesia", description="Voice synthesis provider")
    voice_id: Optional[str] = Field(default=None, description="Provider voice identifier")
    language: str = Field(default="en", description="Voice model language code")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Playback speech rate multiplier")


class ProvidersSpec(BaseModel):
    stt: str = Field(default="cartesia", description="Speech-to-text provider")
    llm: str = Field(default="gemini", description="Large language model provider")
    tts: str = Field(default="cartesia", description="Text-to-speech provider")
    telephony: Optional[str] = Field(default=None, description="Telephony carrier or null")


class CanonicalAgentSpec(BaseModel):
    """
    Canonical Agent Specification — The central contract between
    Choranta Agent Studio and the future Choranta Voice Runtime.
    """
    schema_version: str = "1.0"
    agent: AgentMetaSpec
    identity: IdentitySpec
    business_context: BusinessContextSpec
    instructions: InstructionsSpec
    conversation: ConversationSpec
    languages: LanguagesSpec
    knowledge: KnowledgeSpec
    tools: ToolsSpec
    integrations: IntegrationsSpec
    variables: VariablesSpec = Field(default_factory=VariablesSpec)
    voice: VoiceSpec
    providers: ProvidersSpec

    model_config = ConfigDict(extra="ignore")


class ValidationErrorItem(BaseModel):
    field: str
    message: str
    severity: str = "error"  # error, warning


class ValidationResult(BaseModel):
    valid: bool
    errors: List[ValidationErrorItem] = Field(default_factory=list)
    warnings: List[ValidationErrorItem] = Field(default_factory=list)


class AgentConfigurationData(BaseModel):
    """Mutable draft configuration data model."""
    identity: IdentitySpec = Field(default_factory=IdentitySpec)
    business_context: BusinessContextSpec = Field(default_factory=BusinessContextSpec)
    instructions: InstructionsSpec = Field(default_factory=InstructionsSpec)
    conversation: ConversationSpec = Field(default_factory=ConversationSpec)
    languages: LanguagesSpec = Field(default_factory=LanguagesSpec)
    knowledge_sources: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    integrations: List[str] = Field(default_factory=list)
    variables: VariablesSpec = Field(default_factory=VariablesSpec)
    voice: VoiceSpec = Field(default_factory=VoiceSpec)
    providers: ProvidersSpec = Field(default_factory=ProvidersSpec)


class AgentConfigurationResponse(BaseModel):
    agent_id: str
    configuration: AgentConfigurationData
    updated_at: str


class FieldDiff(BaseModel):
    field: str
    old_value: Any
    new_value: Any


class VersionComparisonResponse(BaseModel):
    base_version_number: int
    compare_version_number: int
    changes: List[FieldDiff] = Field(default_factory=list)
    summary: str
