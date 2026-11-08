from typing import List, Tuple
from sqlalchemy.orm import Session
from app.core.exceptions import NotFoundException, ValidationException
from app.models.agent import Agent
from app.models.client import Client
from app.repositories.agent_repository import AgentRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.agent_configuration_repository import AgentConfigurationRepository
from app.repositories.knowledge_repository import KnowledgeRepository, belongs_to_agent
from app.repositories.tool_repository import ToolRepository
from app.repositories.integration_repository import IntegrationRepository
from app.schemas.agent_spec import (
    AgentConfigurationData,
    AgentConfigurationResponse,
    ValidationResult,
)
from app.services.agent_spec_builder import AgentSpecBuilder
from app.services.agent_spec_validator import AgentSpecValidator
from app.services.knowledge_store import DOCUMENT


class AgentConfigurationService:
    def __init__(self, db: Session):
        self.db = db
        self.agent_repo = AgentRepository(db)
        self.client_repo = ClientRepository(db)
        self.config_repo = AgentConfigurationRepository(db)
        self.knowledge_repo = KnowledgeRepository(db)
        self.tool_repo = ToolRepository(db)
        self.integration_repo = IntegrationRepository(db)

    def get_configuration(self, agent_id: str) -> AgentConfigurationResponse:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        client = self.client_repo.get_by_id(agent.client_id)
        if not client:
            raise NotFoundException("Client", agent.client_id)

        config_record = self.config_repo.get_by_agent_id(agent_id)
        if not config_record:
            # Initialize baseline draft configuration
            default_config = self._build_baseline_draft(agent, client)
            config_record = self.config_repo.save_or_update(agent_id, default_config.model_dump())

        # Ensure attached items are synchronized into the response
        attached_knw = [k.id for k in self.knowledge_repo.get_for_agent(agent_id)]
        attached_tools = [t.id for t in self.tool_repo.get_for_agent(agent_id)]
        attached_ints = [i.id for i in self.integration_repo.get_for_agent(agent_id)]

        cfg_dict = config_record.configuration_data.copy()
        # Merge attached sources
        cfg_dict["knowledge_sources"], _ = self.usable_knowledge(
            agent, sorted(list(set(cfg_dict.get("knowledge_sources", []) + attached_knw)))
        )
        cfg_dict["tools"] = sorted(list(set(cfg_dict.get("tools", []) + attached_tools)))
        cfg_dict["integrations"] = sorted(list(set(cfg_dict.get("integrations", []) + attached_ints)))

        return AgentConfigurationResponse(
            agent_id=agent_id,
            configuration=AgentConfigurationData.model_validate(cfg_dict),
            updated_at=config_record.updated_at.isoformat()
        )

    def update_configuration(self, agent_id: str, data: AgentConfigurationData) -> AgentConfigurationResponse:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        usable, foreign = self.usable_knowledge(agent, data.knowledge_sources)
        if foreign:
            raise ValidationException(f"This AI employee can't use knowledge from another client ({', '.join(foreign)}).")
        data = data.model_copy(update={"knowledge_sources": usable})

        config_record = self.config_repo.save_or_update(agent_id, data.model_dump())

        # Sync attached junctions
        current_knw = set(k.id for k in self.knowledge_repo.get_for_agent(agent_id))
        target_knw = set(data.knowledge_sources)
        for kid in target_knw - current_knw:
            self.knowledge_repo.attach_to_agent(agent_id, kid)
        for kid in current_knw - target_knw:
            self.knowledge_repo.detach_from_agent(agent_id, kid)

        current_tools = set(t.id for t in self.tool_repo.get_for_agent(agent_id))
        target_tools = set(data.tools)
        for tid in target_tools - current_tools:
            self.tool_repo.attach_to_agent(agent_id, tid)
        for tid in current_tools - target_tools:
            self.tool_repo.detach_from_agent(agent_id, tid)

        current_ints = set(i.id for i in self.integration_repo.get_for_agent(agent_id))
        target_ints = set(data.integrations)
        for iid in target_ints - current_ints:
            self.integration_repo.attach_to_agent(agent_id, iid)
        for iid in current_ints - target_ints:
            self.integration_repo.detach_from_agent(agent_id, iid)

        return AgentConfigurationResponse(
            agent_id=agent_id,
            configuration=data,
            updated_at=config_record.updated_at.isoformat()
        )

    def usable_knowledge(self, agent: Agent, knowledge_ids: List[str]) -> Tuple[List[str], List[str]]:
        """
        Splits knowledge ids into (what this agent can use, what belongs to someone else). Uploaded documents are
        for the team to read, so they're left out of both. Unknown ids stay in the first list; publishing reports them.
        """
        usable, foreign = [], []
        for knowledge_id in knowledge_ids:
            source = self.knowledge_repo.get_by_id(knowledge_id)
            if source is not None and not belongs_to_agent(source, agent):
                foreign.append(knowledge_id)
            elif getattr(source, "type", None) != DOCUMENT:
                usable.append(knowledge_id)
        return usable, foreign

    def validate_configuration(self, agent_id: str) -> ValidationResult:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        client = self.client_repo.get_by_id(agent.client_id)
        if not client:
            raise NotFoundException("Client", agent.client_id)

        resp = self.get_configuration(agent_id)
        attached_knw = [k.id for k in self.knowledge_repo.get_for_agent(agent_id)]
        attached_tools = [t.id for t in self.tool_repo.get_for_agent(agent_id)]
        attached_ints = [i.id for i in self.integration_repo.get_for_agent(agent_id)]

        from app.services.call_scripts import with_standard_script
        spec = AgentSpecBuilder.build_from_draft(
            agent=agent,
            client=client,
            draft=with_standard_script(self.db, resp.configuration),
            attached_knowledge_ids=attached_knw,
            attached_tool_ids=attached_tools,
            attached_integration_ids=attached_ints
        )

        return AgentSpecValidator.validate(spec, self.db)

    def _build_baseline_draft(self, agent: Agent, client: Client) -> AgentConfigurationData:
        """Create structured default draft baseline for an agent."""
        return AgentConfigurationData(
            identity={
                "name": agent.name.split()[0] if agent.name else "Assistant",
                "organization": client.name,
                "persona": "professional, attentive, and helpful"
            },
            business_context={
                "business_name": client.name,
                "business_type": client.business_type,
                "business_hours": {
                    "timezone": client.timezone,
                    "monday_friday": "09:00 - 18:00"
                },
                "location": f"{client.timezone} region",
                "contact_information": {
                    "name": client.contact_name,
                    "email": client.contact_email,
                    "phone": client.contact_phone
                }
            },
            instructions={
                "primary_goal": f"Represent {client.name} and handle client inquiries and scheduling requests professionally.",
                "responsibilities": [
                    f"Answer incoming inquiries for {client.name}",
                    "Collect caller information and qualify requests",
                    "Schedule appointments and answer general FAQs",
                    "Escalate complex or urgent issues to human supervisors"
                ],
                "rules": [
                    "Speak clearly and concisely",
                    "Confirm caller details before proceeding",
                    "Do not hallucinate or guess unavailable appointments"
                ],
                "restrictions": [
                    "Do not provide confidential or unauthorized advice"
                ],
                "escalation_rules": [
                    "Transfer urgent emergency callers immediately",
                    "Escalate unresolved customer complaints"
                ]
            },
            conversation={
                "tone": "professional",
                "verbosity": "concise",
                "greeting": f"Thank you for calling {client.name}. How may I help you today?",
                "farewell": f"Thank you for contacting {client.name}. Have a wonderful day.",
                "interruption_behavior": "pause_and_listen"
            },
            languages={
                "primary": "en",
                "supported": ["en"]
            },
            knowledge_sources=[],
            tools=[],
            integrations=[],
            voice={
                "provider": "sarvam",
                "voice_id": "ishita",
                "language": "en",
                "speed": 1.0
            },
            providers={
                "stt": "sarvam",
                "llm": "sarvam",
                "tts": "sarvam",
                "telephony": None
            }
        )
