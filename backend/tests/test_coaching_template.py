import uuid
from app.models.client import Client
from app.models.agent import Agent
from app.schemas.agent import AgentCreate
from app.services.agent_service import AgentService
from app.services.agent_templates import get_agent_template_by_id
from app.services.agent_configuration_service import AgentConfigurationService
from app.services.agent_spec_builder import AgentSpecBuilder
from app.services.agent_spec_validator import AgentSpecValidator
from app.runtime.context import RuntimeContext


def test_coaching_template_is_listed():
    tpl = get_agent_template_by_id("coaching_admission_counsellor")
    assert tpl is not None
    assert tpl["category"] == "Education & Coaching"
    assert tpl["preview"]["enabled_tools"] == tpl["default_config"]["tools"]


def test_coaching_template_creates_valid_agent(db):
    if True:
        client = Client(
            id=f"client_coach_{uuid.uuid4().hex[:8]}",
            name="Choranta Test Academy",
            business_type="Education",
            timezone="Asia/Kolkata",
            status="ACTIVE",
        )
        db.add(client)
        db.commit()
        db.refresh(client)

        agent = AgentService(db).create_agent(AgentCreate(
            client_id=client.id,
            name="Admission Counsellor",
            role="Admission Counsellor",
            description="Handles course enquiries and books demo classes",
            template_id="coaching_admission_counsellor",
        ))

        config_res = AgentConfigurationService(db).get_configuration(agent.id)
        config = config_res.configuration.model_dump()

        assert config["identity"]["organization"] == client.name
        assert config["business_context"]["business_name"] == client.name
        assert "counsellor" in config["identity"]["persona"].lower()
        assert config["languages"]["supported"] == ["en-IN", "hi", "te"]
        assert config["knowledge_sources"] == ["knw_coaching_course_catalog"]
        assert set(config["tools"]) == {"check_availability", "book_appointment", "create_lead", "schedule_callback"}

        company_var = next(v for v in config["variables"]["inputs"] if v["name"] == "company_name")
        assert company_var["default_value"] == client.name
        output_names = {v["name"] for v in config["variables"]["outputs"]}
        assert {"student_class", "target_exam", "preferred_batch", "demo_class_booked", "lead_qualification_status"} <= output_names

        spec = AgentSpecBuilder.build_from_draft(
            agent=db.query(Agent).filter(Agent.id == agent.id).first(),
            client=client,
            draft=config_res.configuration,
            attached_knowledge_ids=config_res.configuration.knowledge_sources,
            attached_tool_ids=config_res.configuration.tools,
            attached_integration_ids=config_res.configuration.integrations,
        )
        result = AgentSpecValidator.validate(spec, db)
        assert not result.errors, result.errors

        ctx = RuntimeContext(
            session_id="sess_coach_1",
            client_id=client.id,
            agent_id=agent.id,
            agent_version_id="ver_draft",
            agent_spec=spec,
            metadata={"user_name": "Priya", "company_name": client.name, "course_enquired": "NEET 2027"},
        )
        greeting = ctx.resolved_greeting
        assert "Priya" not in greeting and client.name in greeting
        assert "NEET 2027" in ctx.conversation.system_instruction
        assert "{{" not in greeting

        # Nothing known about the caller: the template's example values are never presented as facts
        unknown = RuntimeContext(
            session_id="sess_coach_2",
            client_id=client.id,
            agent_id=agent.id,
            agent_version_id="ver_draft",
            agent_spec=spec,
            metadata={"company_name": client.name},
        )
        prompt = unknown.conversation.system_instruction
        assert "JEE Main" not in prompt and "Priya Reddy" not in prompt and "Rahul Sharma" not in prompt
        assert "course_enquired: (not known" in prompt


def test_batch_announcement_template_is_valid():
    from app.schemas.agent_spec import AgentConfigurationData
    tpl = get_agent_template_by_id("course_batch_announcement")
    assert tpl is not None and tpl["call_direction"] == "outbound"
    assert "Snowflake" in tpl["default_config"]["conversation"]["greeting"]
    assert "19 October 2026" in tpl["default_config"]["instructions"]["primary_goal"]
    assert tpl["preview"]["enabled_tools"] == tpl["default_config"]["tools"]
    AgentConfigurationData(**tpl["default_config"])
