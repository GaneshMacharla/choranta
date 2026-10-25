from typing import List
from sqlalchemy.orm import Session
from app.schemas.agent_spec import CanonicalAgentSpec, ValidationResult, ValidationErrorItem
from app.models.knowledge_source import KnowledgeSource
from app.models.tool import Tool
from app.models.integration import Integration


class AgentSpecValidator:
    """
    Validates canonical AgentSpec completeness, business rules, and reference validity.
    Returns structured field-level errors and warnings.
    """

    @staticmethod
    def validate(spec: CanonicalAgentSpec, db: Session) -> ValidationResult:
        errors: List[ValidationErrorItem] = []
        warnings: List[ValidationErrorItem] = []

        # 1. Agent Metadata
        if not spec.agent.name or len(spec.agent.name.strip()) < 2:
            errors.append(ValidationErrorItem(field="agent.name", message="Agent name is required and must be at least 2 characters."))
        if not spec.agent.role or len(spec.agent.role.strip()) < 2:
            errors.append(ValidationErrorItem(field="agent.role", message="Agent role is required and must be at least 2 characters."))
        if not spec.agent.description or len(spec.agent.description.strip()) < 5:
            warnings.append(ValidationErrorItem(field="agent.description", message="Agent description is recommended to be detailed.", severity="warning"))

        # 2. Identity
        if not spec.identity.name or len(spec.identity.name.strip()) < 1:
            warnings.append(ValidationErrorItem(field="identity.name", message="Voice persona name is recommended.", severity="warning"))

        # 3. Instructions
        if not spec.instructions.primary_goal or len(spec.instructions.primary_goal.strip()) < 5:
            errors.append(ValidationErrorItem(field="instructions.primary_goal", message="Primary goal is required to define agent objectives."))

        if not spec.instructions.responsibilities or len(spec.instructions.responsibilities) == 0:
            errors.append(ValidationErrorItem(field="instructions.responsibilities", message="At least one responsibility must be defined."))

        if not spec.instructions.rules:
            warnings.append(ValidationErrorItem(field="instructions.rules", message="Defining behavioral rules is strongly recommended for call safety.", severity="warning"))

        if not spec.instructions.escalation_rules:
            warnings.append(ValidationErrorItem(field="instructions.escalation_rules", message="Escalation rules recommended for unhandled inquiries.", severity="warning"))

        # 4. Conversation
        if not spec.conversation.greeting or len(spec.conversation.greeting.strip()) < 5:
            warnings.append(ValidationErrorItem(field="conversation.greeting", message="A distinct greeting message is recommended.", severity="warning"))

        if spec.business_context.call_direction not in ("inbound", "outbound", "both"):
            errors.append(ValidationErrorItem(field="business_context.call_direction", message="Call direction must be inbound, outbound or both."))

        limits = spec.conversation.limits
        if limits.max_call_duration_s and limits.max_call_duration_s > 1800:
            warnings.append(ValidationErrorItem(field="conversation.limits.max_call_duration_s", message="Calls longer than 30 minutes are costly; consider a lower maximum.", severity="warning"))
        if len(limits.end_call_phrases) > 10:
            warnings.append(ValidationErrorItem(field="conversation.limits.end_call_phrases", message="More than 10 end-call phrases raises the risk of hanging up on real callers.", severity="warning"))
        short_phrases = [p for p in limits.end_call_phrases if len(p.strip()) < 3]
        if short_phrases:
            warnings.append(ValidationErrorItem(field="conversation.limits.end_call_phrases", message=f"Very short end-call phrases may hang up by mistake: {', '.join(short_phrases)}", severity="warning"))

        # 5. Languages
        if not spec.languages.primary:
            errors.append(ValidationErrorItem(field="languages.primary", message="Primary spoken language is required."))
        elif spec.languages.primary not in spec.languages.supported:
            errors.append(ValidationErrorItem(field="languages.supported", message="Primary language must be included in supported languages."))

        # 6. Providers
        if not spec.providers.stt:
            errors.append(ValidationErrorItem(field="providers.stt", message="STT provider selection is required."))
        if not spec.providers.llm:
            errors.append(ValidationErrorItem(field="providers.llm", message="LLM provider selection is required."))
        if not spec.providers.tts:
            errors.append(ValidationErrorItem(field="providers.tts", message="TTS provider selection is required."))

        # 7. Voice
        if spec.voice.speed < 0.5 or spec.voice.speed > 2.0:
            errors.append(ValidationErrorItem(field="voice.speed", message="Speech rate multiplier must be between 0.5 and 2.0."))

        # 8. Check Knowledge Source References
        if spec.knowledge.sources:
            existing_knw_ids = set(
                row[0] for row in db.query(KnowledgeSource.id).filter(KnowledgeSource.id.in_(spec.knowledge.sources)).all()
            )
            # Clients' knowledge bases live in MongoDB
            from app.services.knowledge_store import existing_ids
            existing_knw_ids |= existing_ids(set(spec.knowledge.sources) - existing_knw_ids)
            for knw_id in spec.knowledge.sources:
                if knw_id not in existing_knw_ids:
                    errors.append(ValidationErrorItem(
                        field="knowledge.sources",
                        message=f"Referenced knowledge source ID '{knw_id}' does not exist in catalog."
                    ))

        # 9. Check Tool References
        if spec.tools.enabled:
            existing_tool_ids = set(
                row[0] for row in db.query(Tool.id).filter(Tool.id.in_(spec.tools.enabled)).all()
            )
            for tool_id in spec.tools.enabled:
                if tool_id not in existing_tool_ids:
                    errors.append(ValidationErrorItem(
                        field="tools.enabled",
                        message=f"Referenced tool ID '{tool_id}' does not exist in catalog."
                    ))

        # 10. Check Integration References
        if spec.integrations.enabled:
            existing_int_ids = set(
                row[0] for row in db.query(Integration.id).filter(Integration.id.in_(spec.integrations.enabled)).all()
            )
            for int_id in spec.integrations.enabled:
                if int_id not in existing_int_ids:
                    errors.append(ValidationErrorItem(
                        field="integrations.enabled",
                        message=f"Referenced integration ID '{int_id}' does not exist in catalog."
                    ))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
