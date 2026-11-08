from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.core.exceptions import NotFoundException, ValidationException
from app.core.security import generate_unique_id
from app.models.agent_version import AgentVersion
from app.models.phone_number import PhoneNumber
from app.repositories.agent_repository import AgentRepository
from app.repositories.agent_version_repository import AgentVersionRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.agent_configuration_repository import AgentConfigurationRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.tool_repository import ToolRepository
from app.repositories.integration_repository import IntegrationRepository
from app.schemas.agent_spec import (
    AgentVersionResponse,
    VersionComparisonResponse,
    FieldDiff,
    AgentConfigurationData,
)
from app.services.agent_spec_builder import AgentSpecBuilder
from app.services.agent_spec_validator import AgentSpecValidator


class AgentVersionService:
    def __init__(self, db: Session):
        self.db = db
        self.agent_repo = AgentRepository(db)
        self.client_repo = ClientRepository(db)
        self.version_repo = AgentVersionRepository(db)
        self.config_repo = AgentConfigurationRepository(db)
        self.knowledge_repo = KnowledgeRepository(db)
        self.tool_repo = ToolRepository(db)
        self.integration_repo = IntegrationRepository(db)

    def list_versions(self, agent_id: str) -> List[AgentVersionResponse]:
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

    def get_version(self, agent_id: str, version_id: str) -> AgentVersionResponse:
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        version = self.version_repo.get_by_id(version_id)
        if not version or version.agent_id != agent_id:
            raise NotFoundException("AgentVersion", version_id)

        return AgentVersionResponse(
            id=version.id,
            agent_id=version.agent_id,
            version_number=version.version_number,
            configuration_json=version.configuration_json,
            status=version.status,
            created_at=version.created_at,
            created_by=version.created_by
        )

    def create_version(self, agent_id: str, creator_id: Optional[str] = None) -> AgentVersionResponse:
        """
        Freezes the current draft configuration into an immutable version snapshot.
        Validates completeness before creating the version.
        """
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        client = self.client_repo.get_by_id(agent.client_id)
        if not client:
            raise NotFoundException("Client", agent.client_id)

        config_record = self.config_repo.get_by_agent_id(agent_id)
        if not config_record:
            from app.services.agent_configuration_service import AgentConfigurationService
            AgentConfigurationService(self.db).get_configuration(agent_id)
            config_record = self.config_repo.get_by_agent_id(agent_id)

        from app.services.call_scripts import with_standard_script
        draft_data = with_standard_script(self.db, AgentConfigurationData.model_validate(config_record.configuration_data))
        attached_knw = [k.id for k in self.knowledge_repo.get_for_agent(agent_id)]
        attached_tools = [t.id for t in self.tool_repo.get_for_agent(agent_id)]
        attached_ints = [i.id for i in self.integration_repo.get_for_agent(agent_id)]

        canonical_spec = AgentSpecBuilder.build_from_draft(
            agent=agent,
            client=client,
            draft=draft_data,
            attached_knowledge_ids=attached_knw,
            attached_tool_ids=attached_tools,
            attached_integration_ids=attached_ints
        )

        # Validate spec
        val_result = AgentSpecValidator.validate(canonical_spec, self.db)
        if not val_result.valid:
            error_msgs = "; ".join([f"{e.field}: {e.message}" for e in val_result.errors])
            raise ValidationException(f"Configuration validation failed: {error_msgs}", details=val_result.model_dump())

        next_version_num = self.version_repo.get_latest_version_number(agent_id) + 1

        version_record = AgentVersion(
            id=generate_unique_id("agtv", 12),
            agent_id=agent_id,
            version_number=next_version_num,
            configuration_json=canonical_spec.model_dump(),
            status="PUBLISHED",
            created_by=creator_id
        )
        saved = self.version_repo.create(version_record)

        return AgentVersionResponse(
            id=saved.id,
            agent_id=saved.agent_id,
            version_number=saved.version_number,
            configuration_json=saved.configuration_json,
            status=saved.status,
            created_at=saved.created_at,
            created_by=saved.created_by
        )

    def restore_version_to_draft(self, agent_id: str, version_id: str) -> Dict[str, Any]:
        """
        Rollback mechanism: Restores an old version's specification into the agent's current draft.
        Never mutates the old version.
        """
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        old_version = self.version_repo.get_by_id(version_id)
        if not old_version or old_version.agent_id != agent_id:
            raise NotFoundException("AgentVersion", version_id)

        spec_data = old_version.configuration_json
        if not isinstance(spec_data, dict) or "identity" not in spec_data:
            raise ValidationException(f"Version {old_version.version_number} is in an old format and can't be restored.")
        # Convert canonical spec back into draft configuration structure
        draft_dict = {
            "identity": spec_data.get("identity", {}),
            "business_context": spec_data.get("business_context", {}),
            "instructions": spec_data.get("instructions", {}),
            "conversation": spec_data.get("conversation", {}),
            "languages": spec_data.get("languages", {}),
            "knowledge_sources": spec_data.get("knowledge", {}).get("sources", []),
            "tools": spec_data.get("tools", {}).get("enabled", []),
            "integrations": spec_data.get("integrations", {}).get("enabled", []),
            "variables": spec_data.get("variables", {}),
            "voice": spec_data.get("voice", {}),
            "providers": spec_data.get("providers", {})
        }

        # Saved like any draft edit, so knowledge and integrations added since this version come off again.
        # Knowledge this agent can no longer use is left out rather than blocking the restore.
        from app.services.agent_configuration_service import AgentConfigurationService
        config_service = AgentConfigurationService(self.db)
        draft = AgentConfigurationData.model_validate(draft_dict)
        usable, _ = config_service.usable_knowledge(agent, draft.knowledge_sources)
        config_service.update_configuration(agent_id, draft.model_copy(update={"knowledge_sources": usable}))

        return {
            "agent_id": agent_id,
            "restored_from_version": old_version.version_number,
            "message": f"Successfully loaded version {old_version.version_number} into current editable draft."
        }

    def list_numbers(self, agent_id: str) -> List[Dict[str, Any]]:
        """The phone numbers answered by this AI employee, each with the version it runs."""
        if not self.agent_repo.get_by_id(agent_id):
            raise NotFoundException("Agent", agent_id)
        numbers = self.db.query(PhoneNumber).filter(PhoneNumber.agent_id == agent_id).order_by(PhoneNumber.phone_number).all()
        version_numbers = {v.id: v.version_number for v in self.version_repo.list_by_agent(agent_id)}
        return [
            {
                "id": n.id,
                "phone_number": n.phone_number,
                "status": n.status,
                "agent_version_id": n.agent_version_id,
                "version_number": version_numbers.get(n.agent_version_id),
            }
            for n in numbers
        ]

    def move_numbers(self, agent_id: str, version_id: str) -> List[Dict[str, Any]]:
        """Puts all of this AI employee's phone numbers on one published version. Returns the numbers."""
        version = self.version_repo.get_by_id(version_id)
        if not version or version.agent_id != agent_id or version.status != "PUBLISHED":
            raise NotFoundException("AgentVersion", version_id)
        self.db.query(PhoneNumber).filter(PhoneNumber.agent_id == agent_id).update(
            {"agent_version_id": version.id}, synchronize_session="fetch"
        )
        self.db.commit()
        return self.list_numbers(agent_id)

    def compare_versions(self, agent_id: str, base_vnum: int, comp_vnum: int) -> VersionComparisonResponse:
        """Computes clean, human-readable differences between two versions."""
        agent = self.agent_repo.get_by_id(agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        v_base = None
        v_comp = None
        for v in self.version_repo.list_by_agent(agent_id):
            if v.version_number == base_vnum:
                v_base = v
            elif v.version_number == comp_vnum:
                v_comp = v

        if not v_base:
            raise NotFoundException("AgentVersion", f"Version {base_vnum}")
        if not v_comp:
            raise NotFoundException("AgentVersion", f"Version {comp_vnum}")

        s1 = v_base.configuration_json
        s2 = v_comp.configuration_json

        changes: List[FieldDiff] = []

        # Compare key sections
        # 1. Primary Goal
        g1 = s1.get("instructions", {}).get("primary_goal")
        g2 = s2.get("instructions", {}).get("primary_goal")
        if g1 != g2:
            changes.append(FieldDiff(field="Instructions > Primary Goal", old_value=g1, new_value=g2))

        # 2. Responsibilities
        r1 = s1.get("instructions", {}).get("responsibilities", [])
        r2 = s2.get("instructions", {}).get("responsibilities", [])
        if r1 != r2:
            changes.append(FieldDiff(field="Instructions > Responsibilities", old_value=r1, new_value=r2))

        # 3. Rules
        rules1 = s1.get("instructions", {}).get("rules", [])
        rules2 = s2.get("instructions", {}).get("rules", [])
        if rules1 != rules2:
            changes.append(FieldDiff(field="Instructions > Rules", old_value=rules1, new_value=rules2))

        # 4. Tone & Verbosity
        t1 = s1.get("conversation", {}).get("tone")
        t2 = s2.get("conversation", {}).get("tone")
        if t1 != t2:
            changes.append(FieldDiff(field="Conversation > Tone", old_value=t1, new_value=t2))

        # 5. Greeting
        gr1 = s1.get("conversation", {}).get("greeting")
        gr2 = s2.get("conversation", {}).get("greeting")
        if gr1 != gr2:
            changes.append(FieldDiff(field="Conversation > Greeting", old_value=gr1, new_value=gr2))

        # 6. Tools
        t_list1 = s1.get("tools", {}).get("enabled", [])
        t_list2 = s2.get("tools", {}).get("enabled", [])
        if t_list1 != t_list2:
            changes.append(FieldDiff(field="Tools > Enabled Tools", old_value=t_list1, new_value=t_list2))

        # 7. Knowledge
        k_list1 = s1.get("knowledge", {}).get("sources", [])
        k_list2 = s2.get("knowledge", {}).get("sources", [])
        if k_list1 != k_list2:
            changes.append(FieldDiff(field="Knowledge > Sources", old_value=k_list1, new_value=k_list2))

        # 8. Voice
        v_speed1 = s1.get("voice", {}).get("speed")
        v_speed2 = s2.get("voice", {}).get("speed")
        if v_speed1 != v_speed2:
            changes.append(FieldDiff(field="Voice > Speed", old_value=v_speed1, new_value=v_speed2))

        summary = f"{len(changes)} differences detected between v{base_vnum} and v{comp_vnum}."
        if len(changes) == 0:
            summary = f"No configuration differences detected between v{base_vnum} and v{comp_vnum}."

        return VersionComparisonResponse(
            base_version_number=base_vnum,
            compare_version_number=comp_vnum,
            changes=changes,
            summary=summary
        )
