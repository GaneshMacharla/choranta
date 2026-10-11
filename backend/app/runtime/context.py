from typing import Any, Dict, List, Optional
from app.schemas.agent_spec import CanonicalAgentSpec
from app.runtime.conversation import ConversationState
from app.runtime.usage.tracker import UsageTracker
from app.core.config import settings
from app.runtime.providers.overrides import apply_provider_overrides


class RuntimeContext:
    """
    Domain-level execution context for an active voice runtime interaction.
    Pure domain state — contains no database connections or HTTP request references.
    """

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        client_id: str,
        agent_version_id: str,
        agent_spec: CanonicalAgentSpec,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.session_id = session_id
        self.agent_id = agent_id
        self.client_id = client_id
        self.agent_version_id = agent_version_id
        agent_spec = apply_provider_overrides(agent_spec)
        self.agent_spec = agent_spec
        self.metadata = metadata or {}

        # Conversation state initialized with primary system prompt derived from AgentSpec
        system_prompt = self._compile_system_prompt(agent_spec)
        self.conversation = ConversationState(system_instruction=system_prompt)

        # Active tools enabled for this session
        self.active_tools: List[str] = list(agent_spec.tools.enabled)

        # Provider configurations
        self.provider_references: Dict[str, Any] = {
            "stt": agent_spec.providers.stt,
            "llm": agent_spec.providers.llm,
            "tts": agent_spec.providers.tts,
            "telephony": agent_spec.providers.telephony,
        }

        # Operational metrics tracking
        self.usage_tracker = UsageTracker(
            settings.RUNTIME_MODE,
            llm_provider=agent_spec.providers.llm,
            stt_provider=agent_spec.providers.stt,
            tts_provider=agent_spec.providers.tts,
        )

        # Resolved opening greeting with variable substitution
        self.resolved_greeting = self._resolve_greeting(agent_spec, self.metadata)

    def _resolve_greeting(self, spec: CanonicalAgentSpec, metadata: Dict[str, Any]) -> str:
        """
        Substitutes {{variable}} placeholders in the greeting using session metadata or defaults.
        Safely provides realistic mock lead/company defaults if not provided by a source.
        """
        greeting = spec.conversation.greeting.strip()
        if not greeting:
            return ""

        # Retrieve user/lead name from metadata or mock default
        user_name = metadata.get("user_name") or metadata.get("caller_name") or metadata.get("name")
        if not user_name or str(user_name).strip().lower() in ("", "none", "null", "there"):
            user_name = "Rahul Sharma"  # Default realistic mock lead name when no source is connected
        metadata["user_name"] = str(user_name).strip()

        # Retrieve company name from metadata, business context, identity, or mock default
        company_name = (
            metadata.get("company_name")
            or (spec.business_context and spec.business_context.business_name)
            or (spec.identity and spec.identity.organization)
        )
        if not company_name or str(company_name).strip().lower() in ("", "none", "null", "our office", "default client"):
            company_name = "Apex Realty Bangalore"  # Default realistic mock company
        metadata["company_name"] = str(company_name).strip()

        if "{{user_name}}" in greeting:
            greeting = greeting.replace("{{user_name}}", metadata["user_name"])

        if "{{company_name}}" in greeting:
            greeting = greeting.replace("{{company_name}}", metadata["company_name"])

        # Clean any remaining unresolved double curly bracket placeholders
        import re
        greeting = re.sub(r"\{\{[^}]+\}\}", "", greeting).strip()
        return greeting

    def _compile_system_prompt(self, spec: CanonicalAgentSpec) -> str:
        """Assembles prompt grounding the agent from its immutable canonical spec and variables."""
        company_name = self.metadata.get("company_name") or (spec.business_context and spec.business_context.business_name) or spec.identity.organization or "Apex Realty Bangalore"
        lines = [
            f"You are {spec.identity.name or spec.agent.name}, an AI voice employee representing {company_name}.",
            f"Role: {spec.agent.role}.",
            f"Persona: {spec.identity.persona}.",
            f"Tone: {spec.conversation.tone}.",
            f"Primary Goal: {spec.instructions.primary_goal}.",
        ]

        # Ground Input Variables (known lead/call context)
        input_vars = getattr(spec.variables, "inputs", [])
        if input_vars:
            lines.append("\nKnown Lead Context & Input Variables:")
            for iv in input_vars:
                val = self.metadata.get(iv.name)
                if val is None or str(val).strip().lower() in ("", "none", "null", "there"):
                    if iv.name == "user_name":
                        val = "Rahul Sharma"
                    elif iv.name == "company_name":
                        val = company_name
                    elif iv.name == "lead_id":
                        val = "lead_re_101"
                    else:
                        val = iv.default_value
                val_str = f"'{val}'" if val is not None else "(Not provided yet)"
                desc_str = f" - {iv.description}" if iv.description else ""
                lines.append(f"- {iv.name}: {val_str}{desc_str}")

        # Ground Output Variables (targets to discover and qualify)
        output_vars = getattr(spec.variables, "outputs", [])
        if output_vars:
            lines.append("\nLead Qualification Targets (Confirm and qualify during conversation):")
            for ov in output_vars:
                desc_str = f": {ov.description}" if ov.description else ""
                lines.append(f"- {ov.name}{desc_str}")

        if spec.instructions.responsibilities:
            lines.append("\nCore Responsibilities:")
            for r in spec.instructions.responsibilities:
                lines.append(f"- {r}")

        if spec.instructions.rules:
            lines.append("\nBehavioral Rules:")
            for rule in spec.instructions.rules:
                lines.append(f"- {rule}")

        if spec.instructions.restrictions:
            lines.append("\nStrict Restrictions:")
            for rest in spec.instructions.restrictions:
                lines.append(f"- {rest}")

        if spec.instructions.escalation_rules:
            lines.append("\nEscalation Criteria:")
            for esc in spec.instructions.escalation_rules:
                lines.append(f"- {esc}")

        return "\n".join(lines)
