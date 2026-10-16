import uuid
import pytest
from app.db.session import SessionLocal
from app.models.client import Client
from app.models.agent import Agent
from app.models.lead import Lead
from app.models.property import Property
from app.schemas.agent import AgentCreate
from app.services.agent_service import AgentService
from app.services.agent_templates import REAL_ESTATE_LEAD_QUALIFICATION_TEMPLATE
from app.services.agent_configuration_service import AgentConfigurationService
from app.services.agent_version_service import AgentVersionService
from app.runtime.tools.mock import (
    MockGetLeadDetailsTool,
    MockSearchPropertiesTool,
    MockCheckSiteVisitSlotsTool,
    MockUpdateLeadRecordTool,
)
from app.services.agent_spec_builder import AgentSpecBuilder
from app.runtime.context import RuntimeContext


@pytest.mark.asyncio
async def test_real_estate_template_creation_and_e2e_flow():
    db = SessionLocal()
    try:
        # 1. Create a client business
        client_id = f"client_re_{uuid.uuid4().hex[:8]}"
        client = Client(
            id=client_id,
            name="Apex Realty Bangalore",
            business_type="Real Estate",
            timezone="Asia/Kolkata",
            status="ACTIVE",
        )
        db.add(client)
        db.commit()
        db.refresh(client)

        # 2. Create agent from template
        agent_in = AgentCreate(
            client_id=client.id,
            name="Real Estate Lead Qualification Assistant",
            role="Lead Qualification Specialist",
            description="Autonomous property qualification assistant",
            template_id="real_estate_lead_qualification",
        )
        agent_service = AgentService(db)
        agent = agent_service.create_agent(agent_in)
        assert agent is not None
        assert agent.name == "Real Estate Lead Qualification Assistant"
        assert agent.role == "Lead Qualification Specialist"

        # 3. Verify draft configuration populated from template
        config_service = AgentConfigurationService(db)
        config_res = config_service.get_configuration(agent.id)
        config = config_res.configuration.model_dump()

        # Identity
        assert config["identity"]["name"] == "Real Estate Lead Qualification Assistant"
        assert config["identity"]["organization"] == "Apex Realty Bangalore"
        assert "real estate" in config["identity"]["persona"].lower()

        # Greeting & Placeholders
        assert "{{user_name}}" not in config["conversation"]["greeting"]
        assert "{{company_name}}" in config["conversation"]["greeting"]

        # Voice & Languages
        assert config["languages"]["primary"] == "en-IN"
        assert "hi" in config["languages"]["supported"]
        assert "te" in config["languages"]["supported"]
        assert config["voice"]["voice_id"] == "4459a9a5-69d6-4680-b970-e13dc51845b6" and config["voice"]["provider"] == "cartesia"  # Siya
        assert config["providers"]["stt"] == config["providers"]["llm"] == "sarvam"
        assert config["providers"]["tts"] == "cartesia"

        # Variables: 2 inputs, 3 outputs (minimal)
        input_vars = config["variables"]["inputs"]
        output_vars = config["variables"]["outputs"]
        assert len(input_vars) == 2
        assert len(output_vars) == 3
        input_names = [v["name"] for v in input_vars]
        assert "user_name" in input_names
        assert "company_name" in input_names

        output_names = [v["name"] for v in output_vars]
        assert "buyer_budget" in output_names
        assert "buyer_location" in output_names
        assert "lead_qualification_status" in output_names

        # Tools attached: 2 minimal tools
        assert "search_properties" in config["tools"]
        assert "update_lead_record" in config["tools"]

        agent_db = db.query(Agent).filter(Agent.id == agent.id).first()
        spec = AgentSpecBuilder.build_from_draft(
            agent=agent_db,
            client=client,
            draft=config_res.configuration,
            attached_knowledge_ids=config_res.configuration.knowledge_sources,
            attached_tool_ids=config_res.configuration.tools,
            attached_integration_ids=config_res.configuration.integrations,
        )

        # 4. Test Runtime Greeting Dynamic Resolution
        # Case A: Caller name present
        ctx_with_caller = RuntimeContext(
            session_id="sess_test_1",
            client_id=client.id,
            agent_id=agent.id,
            agent_version_id="ver_draft",
            agent_spec=spec,
            metadata={"user_name": "Rahul Sharma", "company_name": "Apex Realty"},
        )
        resolved_a = ctx_with_caller.resolved_greeting
        assert "Rahul Sharma" not in resolved_a  # callers are not addressed by name
        assert "Apex Realty" in resolved_a
        assert "{{" not in resolved_a and "}}" not in resolved_a

        # Case B: Caller name missing from source (automatic mock fallback)
        ctx_without_caller = RuntimeContext(
            session_id="sess_test_2",
            client_id=client.id,
            agent_id=agent.id,
            agent_version_id="ver_draft",
            agent_spec=spec,
            metadata={"company_name": "Apex Realty"},
        )
        resolved_b = ctx_without_caller.resolved_greeting
        assert "Rahul Sharma" not in resolved_b
        assert "Apex Realty" in resolved_b
        assert "{{" not in resolved_b and "}}" not in resolved_b

        # 5. Test Mock Execution of Core Real Estate Tools
        # Seed test lead & property if not already in DB
        lead = db.query(Lead).filter(Lead.id == "lead_re_101").first()
        if not lead:
            lead = Lead(
                id="lead_re_101",
                client_id=client.id,
                name="Rahul Sharma",
                phone="+919876543210",
                email="rahul.sharma@example.com",
                property_viewed="Prestige Highline Residences",
                enquiry_location="Whitefield",
                enquiry_budget="₹90 Lakhs - ₹1.1 Cr",
                enquiry_bhk="3 BHK",
            )
            db.add(lead)
            db.commit()

        prop = db.query(Property).filter(Property.id == "prop_re_001").first()
        if not prop:
            prop = Property(
                id="prop_re_001",
                client_id=client.id,
                project_name="Prestige Highline Residences",
                location="Whitefield",
                price=9500000,
                price_display="₹95 Lakhs",
                bhk=3,
                property_type="Apartment",
                status="AVAILABLE",
                amenities=["Clubhouse", "Gym", "Swimming Pool"],
            )
            db.add(prop)
            db.commit()

        # Tool: get_lead_details
        get_lead_tool = MockGetLeadDetailsTool()
        lead_result = get_lead_tool.execute({
            "lead_id": "lead_re_101",
        })
        assert lead_result["found"] is True
        assert lead_result["name"] == "Rahul Sharma"

        # Tool: search_properties
        search_tool = MockSearchPropertiesTool()
        props_result = search_tool.execute({
            "location": "Whitefield",
            "bhk": "3 BHK",
        })
        assert props_result["count"] > 0
        assert any("Prestige Highline" in p["project_name"] for p in props_result["properties"])

        # Tool: check_site_visit_slots
        slots_tool = MockCheckSiteVisitSlotsTool()
        slots_result = slots_tool.execute({
            "property_id": "prop_re_001",
            "preferred_date": "Saturday",
        })
        assert len(slots_result["available_slots"]) > 0

        # Tool: update_lead_record
        update_tool = MockUpdateLeadRecordTool()
        update_result = update_tool.execute({
            "lead_id": "lead_re_101",
            "lead_qualification_status": "QUALIFIED",
            "buyer_budget": "1.1 Cr",
            "buyer_location": "Whitefield",
            "buyer_bhk": "3 BHK",
            "next_action": "SITE_VISIT_SCHEDULED",
            "call_disposition": "COMPLETED",
        })
        assert update_result["success"] is True

        # 6. Test Commit Version (Draft -> Immutable Version Snapshot)
        version_service = AgentVersionService(db)
        new_version = version_service.create_version(agent.id)
        assert new_version.version_number == 1
        assert new_version.configuration_json["identity"]["name"] == "Real Estate Lead Qualification Assistant"

        # Verify template original was NOT mutated
        assert REAL_ESTATE_LEAD_QUALIFICATION_TEMPLATE["name"] == "Real Estate Lead Qualification"
    finally:
        db.close()
