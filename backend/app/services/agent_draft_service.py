import json
import logging
import re
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.exceptions import NotFoundException
from app.models.client import Client
from app.repositories.client_repository import ClientRepository
from app.runtime.providers.registry import default_registry
from app.runtime.providers.sarvam.limits import background_llm
from app.schemas.agent_draft import AgentDraftRequest, AgentDraftResponse
from app.schemas.agent_spec import AgentConfigurationData

logger = logging.getLogger("choranta.agent_draft")

DRAFT_SYSTEM_PROMPT = """You design AI voice agents that talk to people on live phone calls in India.
Given a business and a plain-language description, write the agent's configuration.

Cover these six parts:
1. Persona: who the agent is and how it sounds.
2. Environment: a phone call; the caller cannot see anything, so keep everything spoken.
3. Tone: one of professional, friendly, warm, casual.
4. Goal: the single outcome the call should achieve.
5. Guardrails: rules to follow, things never to do or say, and when to hand over to a human.
6. Variables: details to collect from the caller (outputs) and details known before the call (inputs).

Keep it phone-friendly and cost-conscious:
- Short replies and one question at a time.
- Collect only what the goal needs.
- End the call politely once the goal is met or the caller declines.

Return ONLY a JSON object, with no markdown, in exactly this shape:
{
  "identity": {"name": "<first name for the voice persona>", "persona": "<one sentence>"},
  "instructions": {
    "primary_goal": "<one or two sentences>",
    "responsibilities": ["<3-6 items>"],
    "rules": ["<3-6 items>"],
    "restrictions": ["<2-5 items>"],
    "escalation_rules": ["<1-3 items>"]
  },
  "conversation": {
    "tone": "professional|friendly|warm|casual",
    "greeting": "<first sentence spoken, under 30 words>",
    "farewell": "<closing sentence, under 20 words>",
    "end_call_phrases": ["<2-4 short caller phrases that mean they want to stop, e.g. not interested>"]
  },
  "variables": {
    "inputs": [{"name": "snake_case", "description": "...", "data_type": "string|number|boolean", "required": false}],
    "outputs": [{"name": "snake_case", "description": "...", "data_type": "string|number|boolean", "required": true, "extraction_instructions": "..."}]
  }
}

Greeting and farewell may use {{company_name}}. Do not address the caller by name or use {{user_name}}."""

_DIRECTION_TEXT = {
    "inbound": "Inbound: customers call the business.",
    "outbound": "Outbound: the agent calls leads or customers.",
    "both": "Both inbound and outbound calls.",
}


class AgentDraftService:
    """Drafts an AI Employee's configuration from a plain-language description."""

    def __init__(self, db: Session):
        self.client_repo = ClientRepository(db)

    def draft(self, req: AgentDraftRequest) -> AgentDraftResponse:
        client = self.client_repo.get_by_id(req.client_id)
        if not client:
            raise NotFoundException("Client", req.client_id)

        base = self._base_configuration(req, client)
        raw = self._ask_llm(req, client)
        if raw is None:
            return AgentDraftResponse(
                configuration=base, draft_source="fallback",
                message="AI drafting is unavailable right now; a starter draft was created from your description.",
            )
        try:
            return AgentDraftResponse(configuration=self._merge(base, raw), draft_source="ai")
        except Exception as e:
            logger.warning(f"AI draft did not match the configuration shape: {e}")
            return AgentDraftResponse(
                configuration=base, draft_source="fallback",
                message="The AI draft could not be used; a starter draft was created from your description.",
            )

    def _base_configuration(self, req: AgentDraftRequest, client: Client) -> AgentConfigurationData:
        supported = list(dict.fromkeys([req.primary_language] + req.supported_languages))
        is_outbound = req.call_direction == "outbound"
        greeting = (
            f"Hello, this is {req.name.split()[0]} calling from {client.name}. Is this a good time to talk?"
            if is_outbound
            else f"Hello, thank you for calling {client.name}. How can I assist you today?"
        )
        return AgentConfigurationData.model_validate({
            "identity": {"name": req.name.split()[0], "organization": client.name, "persona": "professional and friendly"},
            "business_context": {
                "business_name": client.name,
                "business_type": client.business_type or "",
                "call_direction": req.call_direction,
            },
            "instructions": {
                "primary_goal": req.description.strip(),
                "responsibilities": [req.role.strip()],
                "rules": [
                    "Keep replies short and ask one question at a time.",
                    "Confirm important details back to the caller before saving them.",
                ],
                "restrictions": ["Never make promises about prices, discounts or availability you have not been given."],
                "escalation_rules": ["If the caller asks for a human or is upset, offer a callback from the team."],
            },
            "conversation": {
                "tone": "professional",
                "greeting": greeting,
                "farewell": "Thank you for your time. Have a great day!",
            },
            "languages": {"primary": req.primary_language, "supported": supported},
            "voice": {"language": req.primary_language},
        })

    def _ask_llm(self, req: AgentDraftRequest, client: Client) -> Optional[Dict[str, Any]]:
        # Gemini has no output cap here; Sarvam's SARVAM_MAX_TOKENS would cut the JSON short
        provider_name = "gemini" if settings.GEMINI_API_KEY else (settings.LLM_PROVIDER_OVERRIDE or "gemini")
        user_prompt = "\n".join([
            f"Business: {client.name} ({client.business_type})",
            f"Client description: {client.description or '-'}",
            f"Employee name: {req.name}",
            f"Role: {req.role}",
            f"Calls: {_DIRECTION_TEXT[req.call_direction]}",
            f"Primary language: {req.primary_language}; also speaks: {', '.join(req.supported_languages) or '-'}",
            f"What the employee should do: {req.description.strip()}",
            f"Business notes: {req.business_notes.strip() or '-'}",
        ])
        try:
            llm = default_registry.get_llm(provider_name)
            with background_llm():  # nobody is on the phone: live callers go first
                result = llm.generate(
                    system_instruction=DRAFT_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                    temperature=0.4,
                )
        except Exception as e:
            logger.warning(f"AI draft request failed ({provider_name}): {e}")
            return None
        return _parse_json(result.text or "")

    @staticmethod
    def _merge(base: AgentConfigurationData, raw: Dict[str, Any]) -> AgentConfigurationData:
        data = base.model_dump()
        identity = raw.get("identity") or {}
        for key in ("name", "persona"):
            if isinstance(identity.get(key), str) and identity[key].strip():
                data["identity"][key] = identity[key].strip()

        instructions = raw.get("instructions") or {}
        if isinstance(instructions.get("primary_goal"), str) and instructions["primary_goal"].strip():
            data["instructions"]["primary_goal"] = instructions["primary_goal"].strip()
        for key in ("responsibilities", "rules", "restrictions", "escalation_rules"):
            items = [str(x).strip() for x in instructions.get(key) or [] if str(x).strip()]
            if items:
                data["instructions"][key] = items

        conversation = raw.get("conversation") or {}
        if conversation.get("tone") in ("professional", "friendly", "warm", "casual"):
            data["conversation"]["tone"] = conversation["tone"]
        for key in ("greeting", "farewell"):
            if isinstance(conversation.get(key), str) and conversation[key].strip():
                data["conversation"][key] = conversation[key].strip()
        phrases = [str(x).strip() for x in conversation.get("end_call_phrases") or [] if len(str(x).strip()) >= 3]
        data["conversation"]["limits"]["end_call_phrases"] = phrases[:6]

        variables = raw.get("variables") or {}
        for key in ("inputs", "outputs"):
            items = [v for v in variables.get(key) or [] if isinstance(v, dict) and v.get("name")]
            if items:
                data["variables"][key] = items

        return AgentConfigurationData.model_validate(data)


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Pulls the first JSON object out of a model reply, tolerating code fences and stray prose."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
