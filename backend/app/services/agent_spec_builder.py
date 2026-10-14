from typing import Any, Dict, List
from app.models.agent import Agent
from app.models.client import Client
from app.schemas.agent_spec import (
    CanonicalAgentSpec,
    AgentMetaSpec,
    IdentitySpec,
    BusinessContextSpec,
    InstructionsSpec,
    ConversationSpec,
    LanguagesSpec,
    KnowledgeSpec,
    ToolsSpec,
    IntegrationsSpec,
    VoiceSpec,
    ProvidersSpec,
    AgentConfigurationData
)


class AgentSpecBuilder:
    """
    Authoritative backend builder for generating the Canonical AgentSpec.
    Combines agent metadata, client business context, and draft configuration.
    """

    @staticmethod
    def build_from_draft(
        agent: Agent,
        client: Client,
        draft: AgentConfigurationData,
        attached_knowledge_ids: List[str],
        attached_tool_ids: List[str],
        attached_integration_ids: List[str]
    ) -> CanonicalAgentSpec:
        # 1. Agent Metadata
        agent_meta = AgentMetaSpec(
            id=agent.id,
            name=agent.name,
            role=agent.role,
            description=agent.description
        )

        # 2. Identity (fallback to agent defaults if empty)
        identity = IdentitySpec(
            name=draft.identity.name.strip() if draft.identity.name else agent.name.split()[0],
            organization=draft.identity.organization.strip() if draft.identity.organization else client.name,
            persona=draft.identity.persona.strip() if draft.identity.persona else "professional and friendly"
        )

        # 3. Resolved Business Context
        business_context = BusinessContextSpec(
            business_name=draft.business_context.business_name.strip() or client.name,
            business_type=draft.business_context.business_type.strip() or client.business_type,
            business_hours=draft.business_context.business_hours or {
                "timezone": client.timezone,
                "monday_friday": "09:00 - 18:00",
                "saturday": "09:00 - 14:00",
                "sunday": "closed"
            },
            location=draft.business_context.location.strip() or f"{client.timezone} region",
            contact_information=draft.business_context.contact_information or {
                "name": client.contact_name,
                "email": client.contact_email,
                "phone": client.contact_phone
            },
            call_direction=draft.business_context.call_direction or "inbound"
        )

        # 4. Instructions
        instructions = InstructionsSpec(
            primary_goal=draft.instructions.primary_goal.strip(),
            responsibilities=[r.strip() for r in draft.instructions.responsibilities if r.strip()],
            rules=[r.strip() for r in draft.instructions.rules if r.strip()],
            restrictions=[r.strip() for r in draft.instructions.restrictions if r.strip()],
            escalation_rules=[r.strip() for r in draft.instructions.escalation_rules if r.strip()],
            discovery_questions=[q.strip() for q in draft.instructions.discovery_questions if q.strip()],
            offer_points=[p.strip() for p in draft.instructions.offer_points if p.strip()],
            next_step=draft.instructions.next_step.strip(),
        )

        # 5. Conversation
        conversation = ConversationSpec(
            tone=draft.conversation.tone or "professional",
            verbosity=draft.conversation.verbosity or "concise",
            greeting=draft.conversation.greeting.strip() or f"Hello, thank you for calling {client.name}. How can I assist you today?",
            farewell=draft.conversation.farewell.strip() or f"Thank you for contacting {client.name}. Have a great day.",
            interruption_behavior=draft.conversation.interruption_behavior or "pause_and_listen",
            limits=draft.conversation.limits.model_copy(update={
                "end_call_phrases": [p.strip() for p in draft.conversation.limits.end_call_phrases if p.strip()]
            })
        )

        # 6. Languages
        primary_lang = draft.languages.primary or "en"
        supported_langs = list(set([primary_lang] + (draft.languages.supported or ["en"])))
        languages = LanguagesSpec(
            primary=primary_lang,
            supported=supported_langs
        )

        # 7. Knowledge References (combine draft references and attached records)
        combined_knowledge = sorted(list(set(draft.knowledge_sources + attached_knowledge_ids)))
        knowledge = KnowledgeSpec(sources=combined_knowledge)

        # 8. Tools References (combine draft and attached records)
        combined_tools = sorted(list(set(draft.tools + attached_tool_ids)))
        tools = ToolsSpec(enabled=combined_tools)

        # 9. Integrations References
        combined_integrations = sorted(list(set(draft.integrations + attached_integration_ids)))
        integrations = IntegrationsSpec(enabled=combined_integrations)

        # 10. Voice
        voice = VoiceSpec(
            provider=draft.voice.provider or "cartesia",
            voice_id=draft.voice.voice_id,
            language=draft.voice.language or primary_lang,
            speed=draft.voice.speed if 0.5 <= draft.voice.speed <= 2.0 else 1.0
        )

        # 11. Providers
        providers = ProvidersSpec(
            stt=draft.providers.stt or "cartesia",
            llm=draft.providers.llm or "gemini",
            tts=draft.providers.tts or "cartesia",
            telephony=draft.providers.telephony
        )

        return CanonicalAgentSpec(
            schema_version="1.0",
            agent=agent_meta,
            identity=identity,
            business_context=business_context,
            instructions=instructions,
            conversation=conversation,
            languages=languages,
            knowledge=knowledge,
            tools=tools,
            integrations=integrations,
            variables=draft.variables,
            voice=voice,
            providers=providers
        )
