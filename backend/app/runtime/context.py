from typing import Any, Dict, List, Optional
from app.schemas.agent_spec import CanonicalAgentSpec
from app.runtime.conversation import ConversationState
from app.runtime.usage.tracker import UsageTracker
from app.core.config import settings
from app.runtime.providers.overrides import apply_provider_overrides
from app.runtime.greeting_language import is_english, language_name, localize_greeting

# Tools that record who the caller is; the call's known phone number fills them in
CONTACT_TOOLS = {
    "book_appointment", "create_lead", "schedule_callback", "book_site_visit", "update_customer", "update_lead_record",
}
# Test Lab calls simulate a phone call without a real number
TEST_CALL_PHONE = "+910000000000"


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

        # The other person's number is known on a phone call (dialled, or caller ID): never ask for it
        self.contact_phone = self._contact_phone(self.metadata)

        # Resolved opening greeting with variable substitution (the system prompt tells the agent what it said)
        self.resolved_greeting = self._resolve_greeting(agent_spec, self.metadata)
        # The farewell is fixed text too: say it in the call's language, like the greeting
        self.resolved_farewell = self._resolve_farewell(agent_spec)

        # Conversation state initialized with primary system prompt derived from AgentSpec
        system_prompt = self._compile_system_prompt(agent_spec)
        self.conversation = ConversationState(system_instruction=system_prompt)
        # Per-call details (caller, today's date), sent after the fixed instructions: see instruction_for_turn
        self.call_details = self._compile_call_details(agent_spec)
        # Set by runtime.knowledge.apply_knowledge when the knowledge base is too big to give whole
        self.knowledge_index = None

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
            user_name = ""  # unknown: never guess a name
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
        # Open the call in the agent's primary language even when the greeting was written in English
        return localize_greeting(greeting, spec.languages.primary if spec.languages else "en",
                                 keep=[metadata["company_name"], metadata["user_name"]])

    def _resolve_farewell(self, spec: CanonicalAgentSpec) -> str:
        farewell = (spec.conversation.farewell or "").strip()
        if not farewell:
            return ""
        farewell = self.fill_placeholders(farewell)
        return localize_greeting(
            farewell, spec.languages.primary if spec.languages else "en",
            keep=[self.metadata.get("company_name") or "", self.metadata.get("user_name") or ""],
        )

    def instruction_for_turn(self) -> str:
        """
        The system instruction for the next reply: with a large knowledge base, plus the passages matching what
        the caller said in their last two messages (so a follow-up like "and the timings?" still finds the course).
        """
        from app.runtime.knowledge import relevant_knowledge

        # Fixed instructions first (identical on every turn and every call to this agent, so the LLM provider can
        # reuse them from cache), then this call's details, then this turn's knowledge
        base = self.conversation.system_instruction + getattr(self, "call_details", "")
        if self.knowledge_index is None:
            return base
        said = [m.content for m in self.conversation.messages
                if str(getattr(m.role, "value", m.role)).lower() == "user" and m.content][-2:]
        return base + relevant_knowledge(self.knowledge_index, " ".join(said))

    def fill_placeholders(self, text: str) -> str:
        """Fills {{variable}} placeholders from the session's variables and drops any left unresolved,
        so a raw placeholder is never spoken (e.g. a farewell written as "Thank you, {{user_name}}.")."""
        import re

        def value(match: "re.Match[str]") -> str:
            v = self.metadata.get(match.group(1).strip())
            return "" if v is None or str(v).strip().lower() in ("none", "null") else str(v).strip()

        text = re.sub(r"\{\{([^}]+)\}\}", value, text or "")
        text = re.sub(r"\s*,\s*(?=[.!?,]|$)", "", text)  # "time, ." -> "time."
        text = re.sub(r"\s+([,.!?])", r"", text)  # "Thanks , from" -> "Thanks, from"
        return re.sub(r"\s{2,}", " ", text).strip()

    def _compile_system_prompt(self, spec: CanonicalAgentSpec) -> str:
        """Assembles prompt grounding the agent from its immutable canonical spec and variables."""
        company_name = self.metadata.get("company_name") or (spec.business_context and spec.business_context.business_name) or spec.identity.organization or "Apex Realty Bangalore"
        def sentence(text: str) -> str:
            text = (text or "").strip()
            return text if not text or text[-1] in ".!?" else text + "."

        lines = [
            f"You are {spec.identity.name or spec.agent.name}, {spec.agent.role or 'an agent'} at {company_name}, "
            "speaking with a customer on the phone.",
            f"Persona: {sentence(spec.identity.persona)}",
            f"Tone: {sentence(spec.conversation.tone)}",
            f"Primary Goal: {sentence(spec.instructions.primary_goal)}",
        ]

        primary = spec.languages.primary if spec.languages else "en"
        if not is_english(primary):
            others = [language_name(code) for code in (spec.languages.supported or []) if code != primary]
            lines.append(
                f"Language: speak {language_name(primary)} by default, from your first reply onwards"
                + (f"; switch to {', '.join(dict.fromkeys(others))} only if the caller clearly speaks it" if others else "")
                + "."
            )

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

        lines.append(self._call_flow(spec))
        return "\n".join(lines)

    def _compile_call_details(self, spec: CanonicalAgentSpec) -> str:
        """
        What is specific to this call (who the caller is, what we know about them). Sent after the agent's fixed
        instructions, so every call to the same agent starts with identical text the LLM provider can cache.
        """
        company_name = self.metadata.get("company_name") or (spec.business_context and spec.business_context.business_name) or spec.identity.organization or "Apex Realty Bangalore"
        lines: List[str] = []
        # Ground Input Variables (known lead/call context)
        input_vars = getattr(spec.variables, "inputs", [])
        if input_vars:
            lines.append("\nKnown Lead Context & Input Variables:")
            for iv in input_vars:
                val = self.metadata.get(iv.name)
                if val is None or str(val).strip().lower() in ("", "none", "null", "there"):
                    # Template defaults are examples, not facts about this caller
                    val = company_name if iv.name == "company_name" else None
                val_str = f"'{val}' (known - don't ask for it again)" if val is not None else "(not known; ask the caller only if it matters)"
                desc_str = f" - {iv.description}" if iv.description else ""
                lines.append(f"- {iv.name}: {val_str}{desc_str}")
        contact = self._contact_section()
        if contact:
            lines.append(contact)
        return ("\n\nThis call:" + "\n".join(lines)) if lines else ""

    @staticmethod
    def _contact_phone(metadata: Dict[str, Any]) -> Optional[str]:
        """The caller's phone number when the call itself tells us: the number dialled on an outbound call,
        the caller ID on an inbound one, or a stand-in on Test Lab calls (which simulate a phone call)."""
        explicit = metadata.get("contact_phone") or metadata.get("phone")
        if explicit:
            return str(explicit)
        origin = str(metadata.get("origin") or "")
        if origin == "telephony_outbound":
            return metadata.get("destination") or None
        if origin == "telephony_inbound":
            return metadata.get("caller") or None
        if origin == "internal_test_lab":
            return TEST_CALL_PHONE
        return None

    def _contact_section(self) -> str:
        if not self.contact_phone:
            return ""
        lines = [
            "\nCaller Contact (known from this call):",
            f"- Phone number: {self.contact_phone}. Never ask the caller for their phone number - it is already on "
            "file. Use it for bookings, leads and callbacks. Only note a different number if the caller offers one.",
        ]
        name = str(self.metadata.get("user_name") or "").strip()
        if name:
            lines.append(f"- Name: {name}. Don't ask for their name again; use it when a tool needs it.")
        return "\n".join(lines)

    def with_contact_details(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Tool arguments with the known phone number (and name) filled in where the agent left them out."""
        if not self.contact_phone or tool_name not in CONTACT_TOOLS:
            return arguments
        filled = dict(arguments or {})
        for key in ("contact_phone", "phone"):
            if not str(filled.get(key) or "").strip():
                filled[key] = self.contact_phone
        name = str(self.metadata.get("user_name") or "").strip()
        if name:
            for key in ("customer_name", "name"):
                if not str(filled.get(key) or "").strip():
                    filled[key] = name
        return filled

    def _call_flow(self, spec: CanonicalAgentSpec) -> str:
        """
        Every agent follows the same shape: greet once, (outbound) check it's a good time, understand the caller,
        offer what fits, agree one next step, then confirm and close.
        """
        greeting = (self.resolved_greeting or "").strip()
        farewell = getattr(self, "resolved_farewell", "")
        outbound = str(self.metadata.get("origin") or "") == "telephony_outbound"
        if greeting:
            step1 = (
                f"1. Greeting - ALREADY DONE. Your opening line was: \"{greeting}\". Everything in it has been said: "
                "never greet, introduce yourself, repeat its announcement or ask its question again. Your first reply "
                "continues from the caller's answer to it."
            )
        else:
            step1 = "1. Greeting - greet the caller once, briefly, in your first reply, then move on."
        if outbound:
            step2 = (
                "2. Good time? - you called them: if your greeting didn't already ask whether this is a good time, ask "
                "once. If it isn't, offer a callback at a time that suits them and close."
            )
        else:
            step2 = "2. Reason - find out why they called, in their own words, before offering anything."

        tools = set(spec.tools.enabled or [])
        handoff = [name for tool, name in (("transfer_call", "transfer the call"), ("schedule_callback", "book a callback with the team"))
                   if tool in tools]
        human = (
            f"If the caller asks for a person, has a complaint, or needs something you can't answer from your "
            f"information, {' or '.join(handoff)} instead of guessing."
            if handoff else
            "If the caller asks for a person or needs something you can't answer from your information, say a team "
            "member will call them back, instead of guessing."
        )
        # The agent's call script (when set) makes steps 3, 4 and 6 concrete
        script = spec.instructions
        questions = [q for q in (getattr(script, "discovery_questions", None) or []) if q.strip()]
        points = [p for p in (getattr(script, "offer_points", None) or []) if p.strip()]
        agreed = (getattr(script, "next_step", "") or "").strip()
        understand = (
            "3. Understand - ask these questions, one per reply, in this order, skipping any already answered or known: "
            + " | ".join(f'"{q}"' for q in questions) + "."
            if questions else
            "3. Understand - ask the few questions your Core Responsibilities need (at most two or three, one at a time). "
            "Skip anything you already know."
        )
        offer = (
            "4. Offer - from these points, mention only the one or two that match what the caller told you: "
            + " | ".join(points) + "."
            if points else
            "4. Offer - share only the one or two points that match what the caller just told you, not everything you know."
        )
        next_step = (
            f"6. Next step - propose: {agreed}. Offer at most two choices (e.g. two time slots)."
            if agreed else
            "6. Next step - propose one concrete next step from your Primary Goal (a booking, visit, demo or callback), "
            "offering at most two choices (e.g. two time slots)."
        )
        return "\n".join([
            "\nCall Flow (follow in this order, one short step per reply; skip any step already covered and never repeat one):",
            step1,
            step2,
            understand,
            offer,
            f"5. Questions and concerns - answer briefly from your information. {human}",
            next_step,
            "7. Confirm and close - read the booked details back (day, time, what was booked) and confirm, then "
            + (f"say your farewell (\"{farewell}\") " if farewell else "say a brief goodbye ")
            + "and end the call. If the caller declines or wants to stop at any point, thank them and close without pushing.",
        ])
