"""
Preconfigured Agent Templates Registry.
Contains production-grade blueprints such as the Sarvam-inspired Real Estate Lead Qualification Agent.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.schemas.agent_spec import AgentConfigurationData


class TemplatePreview(BaseModel):
    persona: str
    sample_greeting: str
    key_capabilities: List[str]
    input_variables: List[str]
    output_variables: List[str]
    enabled_tools: List[str]


class AgentTemplate(BaseModel):
    id: str
    name: str
    role: str
    description: str
    category: str
    capabilities: List[str]
    preview: TemplatePreview
    default_config: Dict[str, Any]


REAL_ESTATE_LEAD_QUALIFICATION_TEMPLATE: Dict[str, Any] = {
    "id": "real_estate_lead_qualification",
    "name": "Real Estate Lead Qualification",
    "role": "Lead Qualification Specialist",
    "description": "An AI voice sales assistant that contacts property leads, understands their requirements, qualifies potential buyers, recommends matching properties, and arranges the next step with the sales team.",
    "category": "Real Estate & Property Sales",
    "capabilities": [
        "Natural caller greeting & identity confirmation",
        "Structured property inventory search (Location, Price, BHK)",
        "Qualification outcome write-back (Budget, Location, Status)"
    ],
    "preview": {
        "persona": "Friendly, professional real estate sales assistant speaking natural conversational tone with concise phrasing suitable for phone conversations.",
        "sample_greeting": "Hello, am I speaking with {{user_name}}? I'm calling from {{company_name}} regarding your property enquiry.",
        "key_capabilities": [
            "Verify caller identity and greet warmly",
            "Understand preferred budget and desired location",
            "Search and recommend approved matching properties",
            "Record qualified lead details and disposition"
        ],
        "input_variables": [
            "user_name", "company_name"
        ],
        "output_variables": [
            "buyer_budget", "buyer_location", "lead_qualification_status"
        ],
        "enabled_tools": [
            "search_properties", "update_lead_record"
        ]
    },
    "default_config": {
        "identity": {
            "name": "Real Estate Lead Qualification Assistant",
            "organization": "Choranta Realty Partners",
            "persona": "friendly, professional real estate sales assistant speaking natural conversational tone with concise responses suitable for telephone conversations"
        },
        "business_context": {
            "business_name": "Choranta Realty Partners",
            "business_type": "Real Estate Advisory & Property Development",
            "business_hours": {
                "timezone": "Asia/Kolkata",
                "monday_sunday": "09:30 - 19:30"
            },
            "location": "Bengaluru & Mumbai Metropolitan Region, India",
            "contact_information": {
                "email": "sales@chorantarealty.com",
                "phone": "+918041234567"
            }
        },
        "instructions": {
            "primary_goal": "Qualify property enquiries, understand buyer preferences, search suitable properties, and record the lead qualification outcome.",
            "responsibilities": [
                "Verify the caller and greet them warmly.",
                "Understand the caller's budget range and preferred location.",
                "Search property inventory records using search_properties when the caller requests recommendations.",
                "Present matching properties with clear prices and locations.",
                "Save confirmed buyer preferences and qualification status using update_lead_record."
            ],
            "rules": [
                "Never invent prices, inventory, availability, or project details.",
                "Ask one focused question at a time to maintain natural conversation pacing.",
                "Handle interruptions and unclear answers gracefully.",
                "Follow the caller's language preference when supported (e.g., English, Hindi, Telugu).",
                "Respect requests not to be contacted again immediately and mark DO_NOT_CALL."
            ],
            "restrictions": [
                "Do not quote unauthorized discounts or unverified possession schedules.",
                "Do not make legally binding contractual statements on call."
            ],
            "escalation_rules": [
                "If caller requests commercial discount negotiation or custom legal terms, route to Senior Property Advisor."
            ]
        },
        "conversation": {
            "tone": "friendly and professional",
            "verbosity": "concise",
            "greeting": "Hello, am I speaking with {{user_name}}? I'm calling from {{company_name}} regarding your property enquiry.",
            "farewell": "Thank you for your time, {{user_name}}. Our property consultant will assist you further. Have a wonderful day!",
            "interruption_behavior": "pause_and_listen"
        },
        "languages": {
            "primary": "en-IN",
            "supported": ["en-IN", "hi", "te"]
        },
        "knowledge_sources": ["knw_property_catalog"],
        "tools": [
            "search_properties",
            "update_lead_record"
        ],
        "integrations": [],
        "variables": {
            "inputs": [
                {
                    "name": "user_name",
                    "description": "Name of the prospect/caller",
                    "data_type": "string",
                    "default_value": "Rahul Sharma",
                    "required": False,
                    "source": "Caller or CRM",
                    "extraction_instructions": "Extracted from caller greeting or metadata"
                },
                {
                    "name": "company_name",
                    "description": "Real estate business brand name",
                    "data_type": "string",
                    "default_value": "Apex Realty Bangalore",
                    "required": True,
                    "source": "Campaign/contact data",
                    "extraction_instructions": "Workspace/client company name"
                }
            ],
            "outputs": [
                {
                    "name": "buyer_budget",
                    "description": "Confirmed budget range confirmed by caller",
                    "data_type": "string",
                    "default_value": None,
                    "required": False,
                    "source": "Caller-provided information",
                    "extraction_instructions": "Extract budget stated by caller during conversation"
                },
                {
                    "name": "buyer_location",
                    "description": "Confirmed preferred locality in city",
                    "data_type": "string",
                    "default_value": None,
                    "required": False,
                    "source": "Caller-provided information",
                    "extraction_instructions": "Extract locality confirmed by caller"
                },
                {
                    "name": "lead_qualification_status",
                    "description": "Qualification outcome (QUALIFIED, UNQUALIFIED, NURTURING)",
                    "data_type": "string",
                    "default_value": "PENDING",
                    "required": True,
                    "source": "Call metadata",
                    "extraction_instructions": "Determine qualification based on budget fit and interest"
                }
            ]
        },
        "voice": {
            "provider": "cartesia",
            "voice_id": "4459a9a5-69d6-4680-b970-e13dc51845b6",
            "language": "en",
            "speed": 1.0
        },
        "providers": {
            "stt": "cartesia",
            "llm": "gemini",
            "tts": "cartesia",
            "telephony": None
        }
    }
}

AVAILABLE_AGENT_TEMPLATES = [
    REAL_ESTATE_LEAD_QUALIFICATION_TEMPLATE
]


def get_all_agent_templates() -> List[Dict[str, Any]]:
    """Return all available preconfigured agent templates."""
    return AVAILABLE_AGENT_TEMPLATES


def get_agent_template_by_id(template_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single agent template by identifier."""
    for tpl in AVAILABLE_AGENT_TEMPLATES:
        if tpl["id"] == template_id:
            return tpl
    return None


def create_configuration_from_template(
    template_id: str,
    client_name: str,
    agent_name: Optional[str] = None
) -> AgentConfigurationData:
    """
    Constructs an independent mutable AgentConfigurationData copy initialized with template values.
    Customizes placeholders with client information.
    """
    tpl = get_agent_template_by_id(template_id)
    if not tpl:
        raise ValueError(f"Agent template '{template_id}' not found.")

    raw_config = dict(tpl["default_config"])
    config_copy = eval(repr(raw_config))  # deep copy dictionary

    # Customize with client and agent context
    if client_name:
        config_copy["identity"]["organization"] = client_name
        config_copy["business_context"]["business_name"] = client_name
        # Update greeting placeholder default
        for v in config_copy.get("variables", {}).get("inputs", []):
            if v["name"] == "company_name":
                v["default_value"] = client_name

    if agent_name:
        config_copy["identity"]["name"] = agent_name

    return AgentConfigurationData.model_validate(config_copy)
