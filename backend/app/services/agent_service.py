from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.core.exceptions import NotFoundException, ValidationException, ConflictException
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.repositories.agent_repository import AgentRepository
from app.repositories.agent_version_repository import AgentVersionRepository
from app.repositories.client_repository import ClientRepository
from app.schemas.agent import AgentCreate, AgentUpdate, AgentResponse, AgentListResponse
from app.schemas.agent_version import AgentVersionResponse, CanonicalAgentSpec

# Strict lifecycle state transition rules
VALID_AGENT_STATUS_TRANSITIONS: Dict[str, set] = {
    "DRAFT": {"TESTING", "ARCHIVED"},
    "TESTING": {"DRAFT", "READY", "ARCHIVED"},
    "READY": {"TESTING", "DEPLOYED", "PAUSED", "ARCHIVED"},
    "DEPLOYED": {"PAUSED", "ARCHIVED", "TESTING"},
    "PAUSED": {"READY", "DEPLOYED", "ARCHIVED"},
    "ARCHIVED": {"DRAFT"},
}


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self.agent_repo = AgentRepository(db)
        self.version_repo = AgentVersionRepository(db)
        self.client_repo = ClientRepository(db)

    def create_agent(self, data: AgentCreate, creator_id: Optional[str] = None) -> AgentResponse:
        client = self.client_repo.get_by_id(data.client_id)
        if not client:
            raise NotFoundException("Client", data.client_id)

        # Access control: Cannot create agents under inactive/decommissioned clients
        if client.status != "ACTIVE":
            raise ValidationException(
                f"Cannot create an AI employee for client '{client.name}' because the client status is {client.status}."
            )

        # Unique non-sequential agent ID prefixed with agt_
        agent_id = generate_unique_id("agt", 12)

        agent = Agent(
            id=agent_id,
            client_id=data.client_id,
            name=data.name.strip(),
            role=data.role.strip(),
            description=data.description.strip() if data.description else None,
            status="DRAFT"
        )
        saved = self.agent_repo.create(agent)

        if data.template_id:
            from app.services.agent_templates import create_configuration_from_template
            from app.services.agent_configuration_service import AgentConfigurationService
            try:
                config_data = create_configuration_from_template(
                    template_id=data.template_id,
                    client_name=client.name,
                    agent_name=saved.name
                )
                config_svc = AgentConfigurationService(self.db)
                config_svc.update_configuration(saved.id, config_data)
            except Exception as e:
                # Log and fallback gracefully
                import logging
                logging.getLogger("choranta.agents").warning(f"Could not apply template '{data.template_id}': {e}")

        return self._to_response(saved, client_name=client.name)

    def get_agent(self, agent_id: str) -> AgentResponse:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)
        client = self.client_repo.get_by_id(agent.client_id)
        return self._to_response(agent, client_name=client.name if client else None)

    def update_agent(self, agent_id: str, data: AgentUpdate) -> AgentResponse:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        client = self.client_repo.get_by_id(agent.client_id)
        if not client:
            raise NotFoundException("Client", agent.client_id)

        update_dict: Dict[str, Any] = {}

        if data.name is not None:
            update_dict["name"] = data.name.strip()
        if data.role is not None:
            update_dict["role"] = data.role.strip()
        if data.description is not None:
            update_dict["description"] = data.description.strip() if data.description else None

        # Validate lifecycle status transitions
        if data.status is not None and data.status.value != agent.status:
            current_status = agent.status
            target_status = data.status.value

            allowed_targets = VALID_AGENT_STATUS_TRANSITIONS.get(current_status, set())
            if target_status not in allowed_targets:
                raise ValidationException(
                    f"Invalid status transition: Cannot transition AI employee from '{current_status}' to '{target_status}'. "
                    f"Allowed transitions from '{current_status}' are: {sorted(list(allowed_targets))}."
                )

            # Extra guards for DEPLOYED status:
            if target_status == "DEPLOYED":
                # Guard 1: Client must be ACTIVE
                if client.status != "ACTIVE":
                    raise ValidationException(
                        f"Cannot deploy AI employee '{agent.name}': Associated client '{client.name}' is {client.status}."
                    )

                # Guard 2: Agent must have at least one immutable version snapshot
                existing_versions = self.version_repo.list_by_agent(agent.id)
                if not existing_versions:
                    # In Phase 1 hardening: Auto-publish an initial immutable version before deployment
                    self.publish_agent_version(agent.id, creator_id=None, notes="Initial deployment baseline")

            update_dict["status"] = target_status

        updated = self.agent_repo.update(agent, update_dict)
        return self._to_response(updated, client_name=client.name)

    def delete_agent(self, agent_id: str) -> None:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)
        self.agent_repo.delete(agent)

    def list_agents(
        self,
        skip: int = 0,
        limit: int = 100,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> AgentListResponse:
        if client_id:
            # Verify client exists if scoping by client
            client = self.client_repo.get_by_id(client_id)
            if not client:
                raise NotFoundException("Client", client_id)

        items, total = self.agent_repo.list_all(
            skip=skip,
            limit=limit,
            client_id=client_id,
            status=status,
            search=search
        )
        responses = []
        for a in items:
            c = self.client_repo.get_by_id(a.client_id)
            responses.append(self._to_response(a, client_name=c.name if c else None))
        return AgentListResponse(items=responses, total=total)

    def get_agent_versions(self, agent_id: str) -> List[AgentVersionResponse]:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)
        versions = self.version_repo.list_by_agent(agent_id)
        return [
            AgentVersionResponse(
                id=v.id,
                agent_id=v.agent_id,
                version_number=v.version_number,
                configuration_json=v.configuration_json,
                status=v.status,
                created_at=v.created_at,
                created_by=v.created_by
            )
            for v in versions
        ]

    def publish_agent_version(
        self,
        agent_id: str,
        creator_id: Optional[str] = None,
        notes: str = ""
    ) -> AgentVersionResponse:
        """
        Creates an immutable configuration snapshot for the agent.
        Guarantees that production deployments run on immutable specifications.
        """
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        next_version = self.version_repo.get_latest_version_number(agent_id) + 1
        spec = self.build_canonical_spec(agent)

        version_record = AgentVersion(
            id=generate_unique_id("agtv", 12),
            agent_id=agent_id,
            version_number=next_version,
            configuration_json=spec.model_dump(),
            status="PUBLISHED",
            created_by=creator_id
        )
        saved = self.version_repo.create(version_record)
        return AgentVersionResponse.model_validate(saved)

    def build_canonical_spec(self, agent: Agent) -> CanonicalAgentSpec:
        """Construct canonical specification model."""
        return CanonicalAgentSpec(
            agent_id=agent.id,
            client_id=agent.client_id,
            name=agent.name,
            role=agent.role,
            description=agent.description,
            prompt="",
            knowledge_sources=[],
            tools=[],
            integrations=[],
            stt_provider="sarvam",
            llm_provider="sarvam",
            tts_provider="cartesia",
            telephony_provider=None,
            status=agent.status.lower()
        )

    def _to_response(self, agent: Agent, client_name: Optional[str] = None) -> AgentResponse:
        return AgentResponse(
            id=agent.id,
            client_id=agent.client_id,
            client_name=client_name,
            name=agent.name,
            role=agent.role,
            description=agent.description,
            status=agent.status,
            created_at=agent.created_at,
            updated_at=agent.updated_at
        )
