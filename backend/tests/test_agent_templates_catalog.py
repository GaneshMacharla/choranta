from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.knowledge_source import KnowledgeSource
from app.models.tool import Tool
from app.schemas.agent_spec import AgentConfigurationData
from app.services.agent_templates import get_all_agent_templates

BUSINESS_TYPES = {"CLINIC", "HOSPITAL", "SALON", "REAL_ESTATE", "HOTEL", "RESTAURANT", "CORPORATE", "OTHER"}


def test_every_business_type_has_a_template():
    covered = {bt for t in get_all_agent_templates(include_hidden=True) for bt in t.get("business_types", [])}
    assert BUSINESS_TYPES <= covered


def test_templates_are_valid_and_reference_real_tools(db: Session):
    tool_ids = {t.id for t in db.query(Tool).all()}
    knowledge_ids = {k.id for k in db.query(KnowledgeSource).all()}
    ids = set()
    for tpl in get_all_agent_templates(include_hidden=True):
        assert tpl["id"] not in ids
        ids.add(tpl["id"])
        assert tpl.get("call_direction") in ("inbound", "outbound", "both")
        config = AgentConfigurationData(**tpl["default_config"])
        assert set(config.tools) <= tool_ids, (tpl["id"], set(config.tools) - tool_ids)
        assert set(config.knowledge_sources) <= knowledge_ids, (tpl["id"], set(config.knowledge_sources) - knowledge_ids)


def test_templates_api_lists_only_the_gallery(client: TestClient, auth_headers: dict):
    """Only reviewed templates are offered; hidden ones still load by id for agents built from them."""
    templates = client.get("/api/catalogs/agent-templates", headers=auth_headers).json()
    assert [t["id"] for t in templates] == ["course_batch_announcement", "real_estate_site_visit_caller"]
    clinic = client.get("/api/catalogs/agent-templates/clinic_receptionist", headers=auth_headers).json()
    assert clinic["business_types"] == ["CLINIC"] and clinic["call_direction"] == "inbound"


def test_templates_api_returns_complete_configs(client: TestClient, auth_headers: dict):
    """The wizard uses default_config directly, so every section (e.g. call limits) must be present."""
    for tpl in client.get("/api/catalogs/agent-templates", headers=auth_headers).json():
        limits = tpl["default_config"]["conversation"]["limits"]
        assert "max_call_duration_s" in limits and limits["end_call_phrases"] is not None, tpl["id"]
