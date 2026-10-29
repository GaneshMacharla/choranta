import pytest

from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.test_scenario import TestRun as DbTestRun, TestRunEvent as DbTestRunEvent, TestScenario as DbTestScenario


def _seed_and_ids(client, operator_headers, db):
    assert client.post("/api/mock/seed", headers=operator_headers).status_code == 200
    agent = db.query(Agent).filter(Agent.id == "mock_agt_acme_health").one()
    version = db.query(AgentVersion).filter(AgentVersion.id == "mock_agtv_1").one()
    return agent, version


def test_scenario_crud_duplicate_and_archival(client, operator_headers, db):
    agent, version = _seed_and_ids(client, operator_headers, db)
    response = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Availability inquiry",
            "caller_goal": "Find an appointment slot",
            "turns": ["I need an appointment"],
            "expected": {"required_tool_calls": ["check_availability"]},
        },
    )
    assert response.status_code == 201, response.text
    scenario_id = response.json()["id"]

    duplicate = client.post(f"/api/test-scenarios/{scenario_id}/duplicate", headers=operator_headers)
    assert duplicate.status_code == 201
    assert duplicate.json()["name"].endswith("Copy")

    archived = client.delete(f"/api/test-scenarios/{scenario_id}", headers=operator_headers)
    assert archived.status_code == 204
    assert db.query(DbTestScenario).filter(DbTestScenario.id == scenario_id).one().status == "ARCHIVED"


@pytest.mark.skip(reason="Tools are switched off for now (SWITCHED_OFF_TOOLS); re-enable with them")
def test_scenario_run_uses_runtime_tools_and_persists_trace(client, operator_headers, db):
    agent, version = _seed_and_ids(client, operator_headers, db)
    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Successful availability flow",
            "caller_goal": "Check appointment availability",
            "turns": ["I want to check appointment availability"],
            "expected": {"required_tool_calls": ["check_availability"], "final_response_contains": ["Dr. Rao"]},
        },
    ).json()

    run_response = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers)
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()
    assert run["status"] == "PASS", run
    assert run["provider_mode"] == "mock"
    assert run["turn_count"] == 1
    assert run["summary"]["assertions"]
    assert db.query(DbTestRun).filter(DbTestRun.id == run["id"]).one().runtime_session_id
    assert db.query(DbTestRunEvent).filter(DbTestRunEvent.run_id == run["id"]).count() > 0

    detail = client.get(f"/api/test-scenarios/runs/{run['id']}", headers=operator_headers)
    assert detail.status_code == 200
    assert len(detail.json()["events"]) > 0


@pytest.mark.skip(reason="Tools are switched off for now (SWITCHED_OFF_TOOLS); re-enable with them")
def test_scenario_failed_assertion_is_not_reported_as_pass(client, operator_headers, db):
    agent, version = _seed_and_ids(client, operator_headers, db)
    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Forbidden tool guard",
            "turns": ["I want to check appointment availability"],
            "expected": {"forbidden_tool_calls": ["check_availability"]},
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "FAIL", run
    assert any(item["status"] == "FAIL" for item in run["summary"]["assertions"])


def test_scenario_requires_mock_mode_and_published_version(client, operator_headers, db):
    agent, version = _seed_and_ids(client, operator_headers, db)
    version.status = "DRAFT"
    db.commit()
    response = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={"agent_id": agent.id, "agent_version_id": version.id, "name": "Invalid", "turns": ["Hello"]},
    )
    assert response.status_code == 409
