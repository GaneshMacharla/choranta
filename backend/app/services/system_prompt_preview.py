"""
The exact system prompt an AI employee's LLM receives, built from its draft the same way a live call builds it
(spec builder, runtime context, knowledge and today's date), so admins can read what the model is told.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models.agent import Agent
from app.models.client import Client
from app.runtime import call_rules
from app.runtime.context import RuntimeContext
from app.runtime.knowledge import apply_knowledge
from app.runtime.tools.catalog import describe_tools
from app.schemas.agent_spec import AgentConfigurationData
from app.services.agent_spec_builder import AgentSpecBuilder


def build_system_prompt(db: Session, agent_id: str, configuration: Optional[AgentConfigurationData] = None,
                        outbound: bool = False) -> Dict[str, Any]:
    """The prompt for the first reply of a call. `configuration` previews unsaved edits; otherwise the saved draft."""
    from app.services.agent_configuration_service import AgentConfigurationService
    from app.services.call_scripts import with_standard_script

    agent = db.get(Agent, agent_id)
    if not agent:
        raise NotFoundException("Agent", agent_id)
    client = db.get(Client, agent.client_id)
    draft = configuration or AgentConfigurationService(db).get_configuration(agent_id).configuration
    draft = with_standard_script(db, draft)
    spec = AgentSpecBuilder.build_from_draft(
        agent=agent, client=client, draft=draft,
        attached_knowledge_ids=list(draft.knowledge_sources or []),
        attached_tool_ids=list(draft.tools or []),
        attached_integration_ids=list(draft.integrations or []),
    )
    metadata = {"origin": "telephony_outbound" if outbound else "telephony_inbound"}
    if client:
        metadata["company_name"] = client.name
    context = RuntimeContext(session_id="preview", agent_id=agent.id, client_id=agent.client_id,
                             agent_version_id="draft", agent_spec=spec, metadata=metadata)
    apply_knowledge(db, context)
    tools = call_rules.with_end_call(describe_tools(db, context.active_tools))
    return {
        "system_prompt": context.instruction_for_turn(),
        "fixed_instructions": context.conversation.system_instruction,
        "call_details": getattr(context, "call_details", ""),
        "greeting": context.resolved_greeting,
        "tools": [{"name": t.get("name") or t.get("id"), "description": t.get("description") or ""} for t in tools],
    }
