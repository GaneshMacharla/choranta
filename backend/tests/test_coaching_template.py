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
        assert config["knowledge_sources"] == []
        assert config["tools"] == []  # every tool is switched off for now (SWITCHED_OFF_TOOLS)

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
        assert "NEET 2027" in ctx.instruction_for_turn()  # per-call details are sent after the fixed instructions
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
        prompt = unknown.instruction_for_turn()
        assert "JEE Main" not in prompt and "Priya Reddy" not in prompt and "Rahul Sharma" not in prompt
        assert "course_enquired: (not known" in prompt


def test_batch_announcement_template_is_valid():
    from app.schemas.agent_spec import AgentConfigurationData
    tpl = get_agent_template_by_id("course_batch_announcement")
    assert tpl is not None and tpl["call_direction"] == "outbound"
    config = tpl["default_config"]
    # No course is baked in: the course, batch and demo come from the campaign
    assert "Snowflake" not in str([config["instructions"], config["conversation"], tpl["description"]])
    assert "{{course_name}}" in config["conversation"]["greeting"]
    campaign_inputs = {v["name"]: v["required"] for v in config["variables"]["inputs"] if v["source"] == "Campaign details"}
    assert campaign_inputs == {"course_name": True, "batch_start_date": True, "batch_timings": True, "demo_class": True,
                               "batch_mode": False, "course_duration": False, "course_fees": False, "course_highlights": False}
    assert "book_appointment" not in config["tools"]  # the demo is a fixed group session, not a booked slot
    assert tpl["preview"]["enabled_tools"] == config["tools"]
    AgentConfigurationData(**config)


def test_batch_announcement_greeting_and_prompt_use_campaign_details(db):
    client = Client(id=f"client_batch_{uuid.uuid4().hex[:8]}", name="Naresh IT", business_type="Education",
                    timezone="Asia/Kolkata", status="ACTIVE")
    db.add(client)
    db.commit()
    agent = AgentService(db).create_agent(AgentCreate(
        client_id=client.id, name="Batch Caller", role="Batch Enrolment Caller",
        description="Announces new batches", template_id="course_batch_announcement",
    ))
    config_res = AgentConfigurationService(db).get_configuration(agent.id)
    spec = AgentSpecBuilder.build_from_draft(
        agent=db.query(Agent).filter(Agent.id == agent.id).first(), client=client, draft=config_res.configuration,
        attached_knowledge_ids=config_res.configuration.knowledge_sources,
        attached_tool_ids=config_res.configuration.tools,
        attached_integration_ids=config_res.configuration.integrations,
    )
    assert not AgentSpecValidator.validate(spec, db).errors

    # What the campaign wizard collected arrives as call variables
    metadata = {"company_name": client.name, "origin": "telephony_outbound", "course_name": "Snowflake and DBT",
                "batch_start_date": "Monday, 19 October", "demo_class": "Saturday, 25 October at 11 am"}
    ctx = RuntimeContext(session_id="sess_batch", client_id=client.id, agent_id=agent.id,
                         agent_version_id="ver_draft", agent_spec=spec, metadata=metadata)
    # Says who is calling (the AI employee, from the business), then why, then asks if it's a good time
    assert ctx.resolved_greeting == ("Hi, this is Batch Caller from Naresh IT. I'm calling about our new Snowflake and DBT "
                                     "batch starting Monday, 19 October. Is this a good time to talk?")
    assert "sample_campaign_values" not in ctx.metadata  # a real call never gets made-up details

    # A Test Lab call has no campaign: it uses each detail's example instead of announcing "a new batch"
    test_call = RuntimeContext(session_id="sess_test", client_id=client.id, agent_id=agent.id, agent_version_id="ver_draft",
                               agent_spec=spec, metadata={"company_name": client.name, "is_test": True})
    assert "Snowflake and DBT batch starting Monday, 19 October" in test_call.resolved_greeting
    assert {"course_name", "batch_start_date", "demo_class"} <= set(test_call.metadata["sample_campaign_values"])
    prompt = ctx.instruction_for_turn()
    assert "demo_class: 'Saturday, 25 October at 11 am' (known" in prompt
    assert "batch_timings: (not known" in prompt


def test_system_prompt_endpoint_shows_what_the_llm_receives(client, auth_headers, db):
    owner = Client(id=f"client_sp_{uuid.uuid4().hex[:8]}", name="Naresh IT", business_type="Education",
                   timezone="Asia/Kolkata", status="ACTIVE")
    db.add(owner)
    db.commit()
    agent = AgentService(db).create_agent(AgentCreate(
        client_id=owner.id, name="Batch Caller", role="Batch Enrolment Caller",
        description="Announces new batches", template_id="course_batch_announcement",
    ))
    res = client.post(f"/api/agents/{agent.id}/system-prompt", json={"outbound": True}, headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["system_prompt"].startswith(body["fixed_instructions"])
    assert "Naresh IT" in body["system_prompt"] and "Call Flow" in body["system_prompt"]
    assert "2. Good time?" in body["system_prompt"]  # outbound call flow
    assert {t["name"] for t in body["tools"]} == {"end_call"}  # every other tool is switched off for now

    # Unsaved edits are previewed without saving them
    config = AgentConfigurationService(db).get_configuration(agent.id).configuration.model_dump(mode="json")
    config["instructions"]["primary_goal"] = "Sell the weekend Azure batch."
    edited = client.post(f"/api/agents/{agent.id}/system-prompt", json={"configuration": config}, headers=auth_headers).json()
    assert "Sell the weekend Azure batch." in edited["system_prompt"]
