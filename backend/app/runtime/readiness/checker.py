from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.client import Client
from app.schemas.agent_spec import CanonicalAgentSpec
from app.runtime.providers.registry import ProviderRegistry, default_registry


def live_block_reason(agent: Optional[Agent]) -> Optional[str]:
    """Why this AI employee can't take real calls, or None if it can. Test calls don't go through this."""
    if not settings.AGENT_STATUS_ENFORCED or agent is None or agent.status == "DEPLOYED":
        return None
    return f"{agent.name} isn't live (its status is {agent.status}). Press Go live on its Test tab to take real calls."


class RuntimeReadinessChecker:
    """
    Validates that an agent version satisfies all prerequisites to execute in the voice runtime.
    """

    def __init__(self, db: Session, registry: ProviderRegistry = default_registry):
        self.db = db
        self.registry = registry

    def check(self, agent_id: str, version_id: str) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Fetch Agent
        agent = self.db.get(Agent, agent_id)
        if not agent:
            errors.append(f"Agent '{agent_id}' does not exist.")
            return {
                "ready": False,
                "errors": errors,
                "warnings": warnings,
                "agent_id": agent_id,
                "version_id": version_id,
                "version_number": None
            }

        # 2. Check Client status
        client = self.db.get(Client, agent.client_id)
        if not client:
            errors.append(f"Client '{agent.client_id}' does not exist.")
        elif client.status != "ACTIVE":
            errors.append(f"Client '{client.name}' is INACTIVE. Calls cannot be serviced.")

        # 3. Check Agent status
        if agent.status in ("ARCHIVED", "PAUSED"):
            warnings.append(f"Agent status is '{agent.status}'.")

        # 4. Fetch AgentVersion
        version = self.db.get(AgentVersion, version_id)
        if version is not None and version.agent_id != agent_id:
            version = None

        if not version:
            errors.append(f"AgentVersion '{version_id}' does not exist for agent '{agent_id}'.")
            return {
                "ready": False,
                "errors": errors,
                "warnings": warnings,
                "agent_id": agent_id,
                "version_id": version_id,
                "version_number": None
            }

        # 5. Check version status (MUST be PUBLISHED, never DRAFT)
        if version.status != "PUBLISHED":
            errors.append(
                f"AgentVersion '{version_id}' has status '{version.status}'. Only PUBLISHED versions can run."
            )

        # 6. Parse and validate CanonicalAgentSpec
        try:
            spec = CanonicalAgentSpec.model_validate(version.configuration_json)
        except Exception as e:
            errors.append(f"AgentVersion configuration does not conform to CanonicalAgentSpec: {str(e)}")
            return {
                "ready": False,
                "errors": errors,
                "warnings": warnings,
                "agent_id": agent_id,
                "version_id": version_id,
                "version_number": version.version_number
            }

        if spec.schema_version != "1.0":
            errors.append(f"Unsupported schema version '{spec.schema_version}'. Expected '1.0'.")

        # 7. Check Provider readiness (after any *_PROVIDER_OVERRIDE settings)
        from app.runtime.providers.overrides import apply_provider_overrides
        spec = apply_provider_overrides(spec)
        if not spec.providers.stt or not self.registry.has_stt(spec.providers.stt):
            errors.append(f"Configured STT provider '{spec.providers.stt}' is not registered.")

        if not spec.providers.llm or not self.registry.has_llm(spec.providers.llm):
            errors.append(f"Configured LLM provider '{spec.providers.llm}' is not registered.")

        if not spec.providers.tts or not self.registry.has_tts(spec.providers.tts):
            errors.append(f"Configured TTS provider '{spec.providers.tts}' is not registered.")

        # In provider mode, verify required credentials
        if self.registry.mode in ("provider", "real"):
            if (spec.providers.stt == "cartesia" or spec.providers.tts == "cartesia") and not settings.CARTESIA_API_KEY:
                errors.append("Cartesia API key (CARTESIA_API_KEY) is not configured in server environment.")
            if spec.providers.llm == "gemini" and not settings.GEMINI_API_KEY:
                errors.append("Gemini API key (GEMINI_API_KEY) is not configured in server environment.")
            if "sarvam" in (spec.providers.stt, spec.providers.tts, spec.providers.llm) and not settings.SARVAM_API_KEY:
                errors.append("Sarvam API key (SARVAM_API_KEY) is not configured in server environment.")

        # 8. Check Tools
        if not spec.tools.enabled:
            warnings.append("No tools are enabled for this agent specification.")

        # 9. Check Instructions completeness
        if not spec.instructions.primary_goal:
            warnings.append("Primary goal is empty in agent specification.")

        return {
            "ready": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "agent_id": agent_id,
            "version_id": version_id,
            "version_number": version.version_number
        }
