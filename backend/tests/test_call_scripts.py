"""Standard call scripts: shared per template, edited by admins, taken by linked employees on publish."""
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.agent_configuration import AgentConfiguration
from app.models.call_script import StandardCallScript
from app.models.client import Client
from app.schemas.agent import AgentCreate
from app.services import call_scripts
from app.services.agent_configuration_service import AgentConfigurationService
from app.services.agent_service import AgentService
from app.services.agent_templates import get_agent_template_by_id
from app.services.agent_templates_business import CALL_SCRIPTS
from app.services.agent_version_service import AgentVersionService

RE_KEY = "real_estate_lead_qualification"


def _real_estate_agent(db: Session):
    client = Client(id=f"cli_{uuid.uuid4().hex[:8]}", name="Apex Realty", business_type="REAL_ESTATE",
                    timezone="Asia/Kolkata", status="ACTIVE")
    db.add(client)
    db.commit()
    return AgentService(db).create_agent(AgentCreate(
        client_id=client.id, name="Ananya", role="Lead Qualification Specialist",
        description="Qualifies property leads", template_id=RE_KEY,
    ))


def _draft(db: Session, agent_id: str) -> AgentConfiguration:
    return db.query(AgentConfiguration).filter_by(agent_id=agent_id).first()


def _set_instructions(db: Session, agent_id: str, **fields):
    record = _draft(db, agent_id)
    data = dict(record.configuration_data)
    data["instructions"] = {**data["instructions"], **fields}
    record.configuration_data = data
    flag_modified(record, "configuration_data")
    db.commit()


def _published_script(db: Session, agent_id: str):
    version = AgentVersionService(db).create_version(agent_id)
    ins = version.configuration_json["instructions"]
    return ins["discovery_questions"], ins["next_step"], ins["script_source"]


def test_every_template_script_is_seeded_and_templates_link_to_it(db: Session):
    standard = db.get(StandardCallScript, RE_KEY)
    assert standard.discovery_questions == CALL_SCRIPTS[RE_KEY]["discovery_questions"]
    assert {s.key for s in call_scripts.list_scripts(db)} == set(CALL_SCRIPTS)
    assert get_agent_template_by_id(RE_KEY)["default_config"]["instructions"]["script_source"] == RE_KEY


def test_linked_employee_takes_the_standard_script_on_its_next_publish(db: Session):
    agent = _real_estate_agent(db)
    assert AgentConfigurationService(db).get_configuration(agent.id).configuration.instructions.script_source == RE_KEY
    questions, _, source = _published_script(db, agent.id)
    assert questions == CALL_SCRIPTS[RE_KEY]["discovery_questions"] and source == RE_KEY

    original = db.get(StandardCallScript, RE_KEY)
    saved = (list(original.discovery_questions), list(original.offer_points), original.next_step)
    try:
        call_scripts.update_script(db, RE_KEY, ["Ready to move or under construction?"], [], "Book a site visit", None)
        # The published version is untouched until the next publish
        first = AgentVersionService(db).list_versions(agent.id)[-1]
        assert first.configuration_json["instructions"]["discovery_questions"] == CALL_SCRIPTS[RE_KEY]["discovery_questions"]
        questions, next_step, _ = _published_script(db, agent.id)
        assert questions == ["Ready to move or under construction?"] and next_step == "Book a site visit"
    finally:
        call_scripts.update_script(db, RE_KEY, *saved, None)


def test_customised_employee_keeps_its_own_script(db: Session):
    agent = _real_estate_agent(db)
    _set_instructions(db, agent.id, script_source="", discovery_questions=["Plots or apartments?"], next_step="Send the brochure")
    questions, next_step, source = _published_script(db, agent.id)
    assert questions == ["Plots or apartments?"] and next_step == "Send the brochure" and source == ""


def test_only_admins_edit_standard_scripts(client, auth_headers, operator_headers):
    op_headers = operator_headers
    body = {"discovery_questions": ["Which area?"], "offer_points": [], "next_step": "Book a site visit"}

    assert client.get(f"/api/call-scripts/{RE_KEY}", headers=op_headers).status_code == 200
    assert client.put(f"/api/call-scripts/{RE_KEY}", json=body, headers=op_headers).status_code == 403
    empty = {**body, "discovery_questions": []}
    assert client.put(f"/api/call-scripts/{RE_KEY}", json=empty, headers=auth_headers).status_code == 422


def test_existing_unchanged_template_copies_are_linked_once(db: Session):
    linked, edited, unlinked = (_real_estate_agent(db) for _ in range(3))
    for agent in (linked, edited, unlinked):
        record = _draft(db, agent.id)
        data = dict(record.configuration_data)
        data["instructions"] = {k: v for k, v in data["instructions"].items() if k != "script_source"}
        record.configuration_data = data
        flag_modified(record, "configuration_data")
    db.commit()
    _set_instructions(db, edited.id, discovery_questions=["Which city?"])
    _set_instructions(db, unlinked.id, script_source="")  # an admin chose this employee's own script

    call_scripts.seed_standard_scripts(db)
    source = lambda a: _draft(db, a.id).configuration_data["instructions"]["script_source"]
    assert source(linked) == RE_KEY
    assert source(edited) == ""
    assert source(unlinked) == ""
