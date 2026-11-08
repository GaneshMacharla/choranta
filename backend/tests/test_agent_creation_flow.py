"""The agent creation flow from the wizard to live calls: knowledge, status, restore, requests, direction, numbers."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.agent_request import AgentRequest
from app.models.call import Call
from app.models.notification import ClientNotification
from app.models.phone_number import PhoneNumber
from app.runtime.knowledge import _sources
from app.schemas.agent_spec import CanonicalAgentSpec
from app.services import agent_requests, knowledge_store as store
from app.services import campaigns as campaign_service
from app.services.agent_templates import get_agent_template_by_id, get_all_agent_templates
from app.services.outbound_calls import OutboundCallError, place_outbound_call
from test_phase3c_telephony import telephony_setup  # noqa: F401
from test_portal import portal  # noqa: F401

_clients = iter(range(1, 1000))


def _client(http: TestClient, headers: dict) -> dict:
    body = {"name": f"Flow Client {next(_clients)}", "business_type": "CLINIC"}
    created = http.post("/api/clients", headers=headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _agent(http: TestClient, headers: dict, client_id: str, name: str = "Priya") -> str:
    """An agent with a complete draft, as the wizard leaves it."""
    template = get_all_agent_templates()[0]
    created = http.post("/api/agents", headers=headers, json={
        "client_id": client_id, "name": name, "role": template["role"], "description": template["description"],
    })
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    saved = http.put(f"/api/agents/{agent_id}/configuration", headers=headers, json=template["default_config"])
    assert saved.status_code == 200, saved.text
    return agent_id


def _config(http: TestClient, headers: dict, agent_id: str) -> dict:
    return http.get(f"/api/agents/{agent_id}/configuration", headers=headers).json()["configuration"]


def _publish(http: TestClient, headers: dict, agent_id: str) -> dict:
    published = http.post(f"/api/agents/{agent_id}/versions", headers=headers)
    assert published.status_code == 201, published.text
    return published.json()


def _go_live(http: TestClient, headers: dict, agent_id: str) -> None:
    for status in ("TESTING", "READY", "DEPLOYED"):
        assert http.patch(f"/api/agents/{agent_id}", headers=headers, json={"status": status}).status_code == 200


# ---------------------------------------------------------------- uploaded documents


def test_uploaded_document_doesnt_stop_an_agent_being_created(client: TestClient, auth_headers: dict):
    owner = _client(client, auth_headers)
    document = store.upload_documents(owner["id"], [("brochure.pdf", "application/pdf", b"%PDF-1.4")], store._actor("CLIENT", "c"))[0]
    note = store.create_note(owner["id"], "NOTES", "Fees", "Fees are 500", [], store._actor("CLIENT", "c"))
    agent_id = _agent(client, auth_headers, owner["id"])

    config = _config(client, auth_headers, agent_id)
    config["knowledge_sources"] = [document.id, note.id]
    saved = client.put(f"/api/agents/{agent_id}/configuration", headers=auth_headers, json=config)

    assert saved.status_code == 200, saved.text
    assert saved.json()["configuration"]["knowledge_sources"] == [note.id]
    assert _config(client, auth_headers, agent_id)["knowledge_sources"] == [note.id]


# ---------------------------------------------------------------- only live agents take real calls


@pytest.fixture
def status_enforced(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_STATUS_ENFORCED", True)


def _ring(http: TestClient, number: PhoneNumber, sid: str):
    return http.get("/api/telephony/vobiz/answer", params={"CallFrom": "+15558889999", "CallTo": number.phone_number, "CallSid": sid})


@pytest.mark.parametrize("status", ["DRAFT", "TESTING", "READY", "PAUSED", "ARCHIVED"])
def test_inbound_call_refused_unless_agent_is_live(client: TestClient, telephony_setup, db: Session, status_enforced, status):
    telephony_setup["agent"].status = status
    db.commit()
    sid = f"CA_NOT_LIVE_{status}"
    response = _ring(client, telephony_setup["phone_number"], sid)
    assert response.status_code == 200
    assert response.json()["url"] == "" and "temporarily unavailable" in response.json()["error"]
    assert db.query(Call).filter(Call.provider_call_id == sid).first() is None


def test_inbound_call_answered_when_agent_is_live(client: TestClient, telephony_setup, db: Session, status_enforced):
    telephony_setup["agent"].status = "DEPLOYED"
    db.commit()
    response = _ring(client, telephony_setup["phone_number"], "CA_LIVE")
    assert "ws/telephony/vobiz/media" in response.json()["url"]


def test_outbound_call_refused_unless_agent_is_live_but_test_calls_work(db: Session, telephony_setup, status_enforced):
    telephony_setup["agent"].status = "PAUSED"
    db.commit()
    number = telephony_setup["phone_number"]
    with pytest.raises(OutboundCallError) as refused:
        place_outbound_call(db, destination_number="+919876500001", phone_number_id=number.id)
    assert refused.value.code == "NOT_READY"
    test_call = place_outbound_call(db, destination_number="+919876500002", phone_number_id=number.id, is_test=True)
    assert test_call.id


def test_pausing_stops_outbound_at_once_despite_cached_readiness(db: Session, telephony_setup, status_enforced):
    telephony_setup["agent"].status = "DEPLOYED"
    db.commit()
    number = telephony_setup["phone_number"]
    assert place_outbound_call(db, destination_number="+919876500003", phone_number_id=number.id).id
    telephony_setup["agent"].status = "PAUSED"
    db.commit()
    with pytest.raises(OutboundCallError):
        place_outbound_call(db, destination_number="+919876500004", phone_number_id=number.id)


def test_campaign_launch_refused_unless_agent_is_live(db: Session, telephony_setup, status_enforced, monkeypatch):
    telephony_setup["agent"].status = "READY"
    db.commit()
    monkeypatch.setattr(campaign_service, "validate_config", lambda *_: None)
    campaign = SimpleNamespace(status="DRAFT", purpose="SERVICE", kind="TRIGGER", agent_id=telephony_setup["agent"].id, id="c1")
    with pytest.raises(campaign_service.CampaignError, match="isn't live"):
        campaign_service.launch(db, campaign, None, True)


def test_number_readiness_reports_agent_not_live(client: TestClient, auth_headers: dict, telephony_setup, status_enforced):
    report = client.get(f"/api/telephony/numbers/{telephony_setup['phone_number'].id}/readiness", headers=auth_headers).json()
    assert report["ready"] is False and any("isn't live" in e for e in report["errors"])


def test_setting_off_lets_any_status_take_calls(client: TestClient, telephony_setup, db: Session):
    telephony_setup["agent"].status = "DRAFT"
    db.commit()
    assert "url" in _ring(client, telephony_setup["phone_number"], "CA_FLAG_OFF").json()


# ---------------------------------------------------------------- restoring a version


def test_restore_keeps_variables(client: TestClient, auth_headers: dict):
    agent_id = _agent(client, auth_headers, _client(client, auth_headers)["id"])
    before = _config(client, auth_headers, agent_id)["variables"]
    assert before["inputs"] and before["outputs"]
    version = _publish(client, auth_headers, agent_id)

    assert client.post(f"/api/agents/{agent_id}/versions/{version['id']}/restore", headers=auth_headers).status_code == 200

    assert _config(client, auth_headers, agent_id)["variables"] == before
    assert _publish(client, auth_headers, agent_id)["configuration_json"]["variables"] == before


def test_restore_takes_off_knowledge_added_since(client: TestClient, auth_headers: dict):
    owner = _client(client, auth_headers)
    agent_id = _agent(client, auth_headers, owner["id"])
    version = _publish(client, auth_headers, agent_id)
    later = store.create_note(owner["id"], "NOTES", "Later", "Added after v1", [agent_id], store._actor("CLIENT", "c"))
    assert later.id in _config(client, auth_headers, agent_id)["knowledge_sources"]

    client.post(f"/api/agents/{agent_id}/versions/{version['id']}/restore", headers=auth_headers)

    assert later.id not in _config(client, auth_headers, agent_id)["knowledge_sources"]


# ---------------------------------------------------------------- the client hears "ready" when it's live


def _open_request(db: Session, client_id: str) -> AgentRequest:
    request = AgentRequest(client_id=client_id, name="Priya", company_name="Co", business_type="CLINIC",
                           status="IN_PROGRESS", details=json.dumps({"tasks": [], "languages": ["en-IN"]}))
    db.add(request)
    db.commit()
    return request


def _ready_notices(db: Session, client_id: str) -> int:
    return db.query(ClientNotification).filter(ClientNotification.client_id == client_id, ClientNotification.kind == "EMPLOYEE_READY").count()


def test_client_told_ready_only_when_agent_goes_live(client: TestClient, auth_headers: dict, db: Session, status_enforced):
    owner = _client(client, auth_headers)
    request = _open_request(db, owner["id"])
    agent_id = _agent(client, auth_headers, owner["id"])

    linked = client.post(f"/api/agent-requests/{request.id}/link", headers=auth_headers, json={"agent_id": agent_id}).json()
    assert linked["status"] == "IN_PROGRESS" and linked["agent_id"] == agent_id
    _publish(client, auth_headers, agent_id)
    assert _ready_notices(db, owner["id"]) == 0

    _go_live(client, auth_headers, agent_id)

    assert client.get(f"/api/agent-requests/{request.id}", headers=auth_headers).json()["status"] == "COMPLETED"
    assert _ready_notices(db, owner["id"]) == 1


def test_going_live_again_doesnt_repeat_the_notice(client: TestClient, auth_headers: dict, db: Session):
    owner = _client(client, auth_headers)
    request = _open_request(db, owner["id"])
    agent_id = _agent(client, auth_headers, owner["id"])
    client.post(f"/api/agent-requests/{request.id}/link", headers=auth_headers, json={"agent_id": agent_id})
    _publish(client, auth_headers, agent_id)
    _go_live(client, auth_headers, agent_id)
    for status in ("PAUSED", "DEPLOYED"):
        client.patch(f"/api/agents/{agent_id}", headers=auth_headers, json={"status": status})
    assert _ready_notices(db, owner["id"]) == 1


def test_request_cant_be_completed_before_publish_or_live(client: TestClient, auth_headers: dict, db: Session, status_enforced):
    owner = _client(client, auth_headers)
    request = _open_request(db, owner["id"])
    agent_id = _agent(client, auth_headers, owner["id"])
    body = {"agent_id": agent_id}

    unpublished = client.post(f"/api/agent-requests/{request.id}/complete", headers=auth_headers, json=body)
    assert unpublished.status_code == 422 and "no published version" in unpublished.json()["error"]
    _publish(client, auth_headers, agent_id)
    not_live = client.post(f"/api/agent-requests/{request.id}/complete", headers=auth_headers, json=body)
    assert not_live.status_code == 422 and "isn't live" in not_live.json()["error"]
    assert _ready_notices(db, owner["id"]) == 0


def test_link_needs_the_clients_own_agent_and_an_open_request(client: TestClient, auth_headers: dict, db: Session):
    owner, other = _client(client, auth_headers), _client(client, auth_headers)
    request = _open_request(db, owner["id"])
    foreign = _agent(client, auth_headers, other["id"])
    assert client.post(f"/api/agent-requests/{request.id}/link", headers=auth_headers, json={"agent_id": foreign}).status_code == 422
    request.status = "REJECTED"
    db.commit()
    with pytest.raises(ValidationException):
        agent_requests.link_request(db, request, _agent(client, auth_headers, owner["id"]), "admin")


def test_operator_cant_link(client: TestClient, auth_headers: dict, operator_headers: dict, db: Session):
    owner = _client(client, auth_headers)
    request = _open_request(db, owner["id"])
    agent_id = _agent(client, auth_headers, owner["id"])
    assert client.post(f"/api/agent-requests/{request.id}/link", headers=operator_headers, json={"agent_id": agent_id}).status_code == 403


# ---------------------------------------------------------------- another client's knowledge


@pytest.fixture
def two_clients(client: TestClient, auth_headers: dict):
    mine, theirs = _client(client, auth_headers), _client(client, auth_headers)
    secret = store.create_note(theirs["id"], "NOTES", "Their prices", "Private price list", [], store._actor("CLIENT", "b"))
    return SimpleNamespace(mine=mine, theirs=theirs, secret=secret, agent_id=_agent(client, auth_headers, mine["id"]))


def test_saving_another_clients_knowledge_is_refused(client: TestClient, auth_headers: dict, two_clients):
    config = _config(client, auth_headers, two_clients.agent_id)
    config["knowledge_sources"] = [two_clients.secret.id]
    refused = client.put(f"/api/agents/{two_clients.agent_id}/configuration", headers=auth_headers, json=config)
    assert refused.status_code == 422
    assert two_clients.secret.id not in _config(client, auth_headers, two_clients.agent_id)["knowledge_sources"]


def test_repository_wont_attach_another_clients_knowledge(db: Session, two_clients):
    from app.repositories.knowledge_repository import KnowledgeRepository
    assert KnowledgeRepository(db).attach_to_agent(two_clients.agent_id, two_clients.secret.id) is False
    assert store.entries_for_agent(two_clients.agent_id) == []


def test_another_clients_private_agent_notes_are_refused(client: TestClient, auth_headers: dict, two_clients):
    other_agent = _agent(client, auth_headers, two_clients.theirs["id"])
    note = client.post(f"/api/agents/{other_agent}/knowledge", headers=auth_headers,
                       json={"name": "Private", "type": "NOTES", "content": "Only for that agent"}).json()
    config = _config(client, auth_headers, two_clients.agent_id)
    config["knowledge_sources"] = [note["id"]]
    assert client.put(f"/api/agents/{two_clients.agent_id}/configuration", headers=auth_headers, json=config).status_code == 422


def test_published_version_naming_another_clients_knowledge_cant_read_it(client: TestClient, auth_headers: dict, db: Session, two_clients):
    """A version published before the rule existed, and a link made then."""
    spec = _publish(client, auth_headers, two_clients.agent_id)["configuration_json"]
    spec["knowledge"]["sources"] = [two_clients.secret.id]
    store.attach(two_clients.agent_id, two_clients.secret.id)
    readable = _sources(db, two_clients.agent_id, CanonicalAgentSpec.model_validate(spec))
    assert two_clients.secret.id not in [source.id for source in readable]


def test_publish_refuses_a_draft_naming_another_clients_knowledge(client: TestClient, auth_headers: dict, db: Session, two_clients):
    """A draft saved before the rule existed."""
    from app.models.agent_configuration import AgentConfiguration
    record = db.query(AgentConfiguration).filter(AgentConfiguration.agent_id == two_clients.agent_id).first()
    record.configuration_data = {**record.configuration_data, "knowledge_sources": [two_clients.secret.id]}
    db.commit()
    refused = client.post(f"/api/agents/{two_clients.agent_id}/versions", headers=auth_headers)
    assert refused.status_code == 422 and "another client" in refused.json()["error"]


# ---------------------------------------------------------------- call direction


@pytest.mark.parametrize("template", get_all_agent_templates(include_hidden=True), ids=lambda t: t["id"])
def test_templates_carry_their_direction_into_the_config(template):
    assert template["default_config"]["business_context"]["call_direction"] == template["call_direction"]


def test_direction_survives_save_and_publish(client: TestClient, auth_headers: dict):
    agent_id = _agent(client, auth_headers, _client(client, auth_headers)["id"])
    config = _config(client, auth_headers, agent_id)
    config["business_context"]["call_direction"] = "both"
    client.put(f"/api/agents/{agent_id}/configuration", headers=auth_headers, json=config)
    assert _publish(client, auth_headers, agent_id)["configuration_json"]["business_context"]["call_direction"] == "both"


def test_outbound_template_loads_by_id_as_outbound():
    assert get_agent_template_by_id("real_estate_site_visit_caller")["default_config"]["business_context"]["call_direction"] == "outbound"


# ---------------------------------------------------------------- phone numbers and versions


@pytest.fixture
def number_on_v1(client: TestClient, auth_headers: dict, db: Session):
    owner = _client(client, auth_headers)
    agent_id = _agent(client, auth_headers, owner["id"])
    v1 = _publish(client, auth_headers, agent_id)
    number = PhoneNumber(id=f"phn_{agent_id[-8:]}", client_id=owner["id"], provider="vobiz", phone_number=f"+9180{int(agent_id[-6:], 16):08d}",
                         status="ACTIVE", agent_id=agent_id, agent_version_id=v1["id"])
    db.add(number)
    db.commit()
    return SimpleNamespace(agent_id=agent_id, v1=v1, number=number)


def test_publish_alone_leaves_numbers_where_they_are_and_reports_them(client: TestClient, auth_headers: dict, number_on_v1):
    _publish(client, auth_headers, number_on_v1.agent_id)
    listed = client.get(f"/api/agents/{number_on_v1.agent_id}/numbers", headers=auth_headers).json()
    assert [(n["id"], n["version_number"]) for n in listed] == [(number_on_v1.number.id, 1)]


def test_admin_moves_numbers_to_a_new_version(client: TestClient, auth_headers: dict, db: Session, number_on_v1):
    v2 = _publish(client, auth_headers, number_on_v1.agent_id)
    moved = client.post(f"/api/agents/{number_on_v1.agent_id}/numbers/move", headers=auth_headers, json={"version_id": v2["id"]})
    assert moved.status_code == 200, moved.text
    assert [n["version_number"] for n in moved.json()] == [2]
    db.refresh(number_on_v1.number)
    assert number_on_v1.number.agent_version_id == v2["id"]


def test_operator_cant_move_numbers(client: TestClient, operator_headers: dict, number_on_v1):
    url = f"/api/agents/{number_on_v1.agent_id}/numbers/move"
    assert client.post(url, headers=operator_headers, json={"version_id": number_on_v1.v1["id"]}).status_code == 403


def test_numbers_cant_move_to_another_agents_version(client: TestClient, auth_headers: dict, number_on_v1):
    other = _agent(client, auth_headers, _client(client, auth_headers)["id"])
    foreign = _publish(client, auth_headers, other)
    url = f"/api/agents/{number_on_v1.agent_id}/numbers/move"
    assert client.post(url, headers=auth_headers, json={"version_id": foreign["id"]}).status_code == 404


def test_portal_marks_only_live_agents_as_connectable(client: TestClient, portal, telephony_setup, db: Session, status_enforced):
    telephony_setup["agent"].status = "READY"
    db.commit()
    assert client.get("/api/portal/agents", headers=portal["headers"]).json()[0]["live"] is False
    telephony_setup["agent"].status = "DEPLOYED"
    db.commit()
    assert client.get("/api/portal/agents", headers=portal["headers"]).json()[0]["live"] is True
