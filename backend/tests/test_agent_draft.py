"""AI-drafted agent configuration for the admin 'create from scratch' wizard."""
from types import SimpleNamespace

from app.runtime.providers.base import LLMResult
from app.runtime.providers.registry import default_registry
from app.schemas.agent_spec import AgentConfigurationData, CallLimitsSpec
from app.services.agent_spec_builder import AgentSpecBuilder

DRAFT_JSON = """```json
{
  "identity": {"name": "Priya", "persona": "A warm clinic receptionist."},
  "instructions": {
    "primary_goal": "Book dental appointments for callers.",
    "responsibilities": ["Find a convenient slot", "Collect the patient's name"],
    "rules": ["Ask one question at a time"],
    "restrictions": ["Never give medical advice"],
    "escalation_rules": ["Offer a callback for emergencies"]
  },
  "conversation": {"tone": "warm", "greeting": "Hello, Smile Dental, Priya speaking.", "farewell": "Take care!",
                   "end_call_phrases": ["not interested", "no", "wrong number"]},
  "variables": {"inputs": [], "outputs": [{"name": "patient_name", "description": "Patient's name", "data_type": "string", "required": true}]}
}
```"""


class _StaticLLM:
    def __init__(self, text: str):
        self.text = text

    def generate(self, system_instruction, messages, available_tools=None, temperature=0.7, model=None):
        return LLMResult(text=self.text)


def _make_client(client, auth_headers) -> str:
    res = client.post("/api/clients", json={"name": "Smile Dental", "business_type": "HEALTHCARE"}, headers=auth_headers)
    return res.json()["id"]


def _payload(client_id: str, **overrides):
    body = {
        "client_id": client_id,
        "name": "Priya Receptionist",
        "role": "Front Desk",
        "call_direction": "inbound",
        "primary_language": "en",
        "supported_languages": ["hi"],
        "description": "Answer calls for a dental clinic and book appointments.",
    }
    body.update(overrides)
    return body


def test_admin_gets_ai_draft(client, auth_headers, monkeypatch):
    monkeypatch.setattr(default_registry, "get_llm", lambda name: _StaticLLM(DRAFT_JSON))
    res = client.post("/api/agents/draft-configuration", json=_payload(_make_client(client, auth_headers)), headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["draft_source"] == "ai"
    cfg = body["configuration"]
    assert cfg["identity"]["name"] == "Priya"
    assert cfg["identity"]["organization"] == "Smile Dental"
    assert cfg["conversation"]["tone"] == "warm"
    assert cfg["conversation"]["limits"]["end_call_phrases"] == ["not interested", "wrong number"]  # "no" is too short
    assert cfg["business_context"]["call_direction"] == "inbound"
    assert cfg["languages"] == {"primary": "en", "supported": ["en", "hi"]}
    assert cfg["variables"]["outputs"][0]["name"] == "patient_name"


def test_malformed_llm_reply_returns_fallback(client, auth_headers, monkeypatch):
    monkeypatch.setattr(default_registry, "get_llm", lambda name: _StaticLLM("Sorry, I can't help with that."))
    res = client.post(
        "/api/agents/draft-configuration",
        json=_payload(_make_client(client, auth_headers), call_direction="outbound"),
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["draft_source"] == "fallback"
    cfg = body["configuration"]
    assert cfg["instructions"]["primary_goal"].startswith("Answer calls for a dental clinic")
    assert "{{user_name}}" not in cfg["conversation"]["greeting"]  # callers are not addressed by name


def test_operator_cannot_draft(client, auth_headers, operator_headers):
    res = client.post("/api/agents/draft-configuration", json=_payload(_make_client(client, auth_headers)), headers=operator_headers)
    assert res.status_code == 403


def test_builder_keeps_limits_and_direction():
    draft = AgentConfigurationData.model_validate({
        "business_context": {"call_direction": "outbound"},
        "instructions": {"primary_goal": "Qualify leads", "responsibilities": ["Ask budget"]},
        "conversation": {"limits": {"max_call_duration_s": 300, "end_call_phrases": [" not interested ", " "]}},
    })
    agent = SimpleNamespace(id="agt_1", name="Asha Caller", role="Sales", description="Calls leads")
    client = SimpleNamespace(name="Acme Homes", business_type="REAL_ESTATE", timezone="Asia/Kolkata",
                             contact_name=None, contact_email=None, contact_phone=None)
    spec = AgentSpecBuilder.build_from_draft(agent, client, draft, [], [], [])
    assert spec.business_context.call_direction == "outbound"
    assert spec.conversation.limits == CallLimitsSpec(max_call_duration_s=300, end_call_phrases=["not interested"])
