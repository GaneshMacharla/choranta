import pytest
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.test_scenario import (
    TestRun as DbTestRun,
    TestRunEvent as DbTestRunEvent,
    TestScenario as DbTestScenario,
)
from app.runtime.testing.templates import get_all_templates


def _setup_agent(client, operator_headers, db):
    client.post("/api/mock/seed", headers=operator_headers)
    agent = db.query(Agent).filter(Agent.id == "mock_agt_acme_health").one()
    version = db.query(AgentVersion).filter(AgentVersion.id == "mock_agtv_1").one()
    return agent, version


# 1. SCENARIO VALIDATION & CRUD
def test_01_scenario_validation_and_crud(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    # Valid scenario creation
    res = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Validation Test Scenario",
            "caller_goal": "Goal description",
            "turns": ["Turn 1", "Turn 2"],
            "max_turns": 8,
            "timeout_seconds": 120,
        },
    )
    assert res.status_code == 201
    scenario_id = res.json()["id"]

    # Validation: empty turns rejection
    bad_res = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Empty Turns",
            "turns": [],
        },
    )
    assert bad_res.status_code == 422

    # Duplicate scenario
    dup_res = client.post(f"/api/test-scenarios/{scenario_id}/duplicate", headers=operator_headers)
    assert dup_res.status_code == 201
    assert dup_res.json()["name"].endswith("Copy")

    # Update scenario
    update_res = client.patch(
        f"/api/test-scenarios/{scenario_id}",
        headers=operator_headers,
        json={"name": "Updated Scenario Name", "max_turns": 12},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Scenario Name"
    assert update_res.json()["max_turns"] == 12

    # Delete scenario (soft delete)
    del_res = client.delete(f"/api/test-scenarios/{scenario_id}", headers=operator_headers)
    assert del_res.status_code == 204
    assert db.query(DbTestScenario).filter(DbTestScenario.id == scenario_id).one().status == "ARCHIVED"


# 2. SUCCESSFUL MULTI-TURN CONVERSATIONS
def test_02_successful_multiturn_conversation(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Multi-turn inquiry flow",
            "caller_goal": "Check availability and book slot",
            "turns": [
                "Hello, I would like to check availability with Dr. Rao.",
                "Yes please, go ahead and book that for Alice Smith.",
                "Thank you so much! Goodbye.",
            ],
            "initial_mock_state": {
                "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            },
            "expected": {
                "required_tool_calls": ["check_availability", "book_appointment"],
                "final_response_contains": ["Goodbye"],
            },
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "PASS", run
    assert run["turn_count"] >= 2
    assert len(run["summary"]["turns"]) >= 2


# 3. CORRECT TOOL EXECUTION & PERSISTED STATE
def test_03_correct_tool_execution_and_persisted_state(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "State mutation flow",
            "caller_goal": "Book Dr. Rao and verify persisted state",
            "turns": [
                "I want to book an appointment with Dr. Rao on 2026-10-10.",
                "Yes, book it please.",
            ],
            "initial_mock_state": {
                "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
                "appointments": [],
            },
            "expected": {
                "required_tool_calls": ["book_appointment"],
                "expected_final_state": {
                    "appointments_count": 1,
                    "appointment_contains": {"doctor": "Dr. Rao"},
                },
            },
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "PASS", run
    assert len(run["final_state"]["appointments"]) == 1
    assert run["final_state"]["appointments"][0]["doctor"] == "Dr. Rao"


# 4. INCORRECT TOOL ARGUMENTS ASSERTION
def test_04_incorrect_tool_arguments_assertion(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Wrong arguments expectation",
            "caller_goal": "Inquire Dr. Rao",
            "turns": ["I want an appointment with Dr. Rao on 2026-10-10."],
            "expected": {
                "required_tool_calls": ["check_availability"],
                "tool_argument_constraints": {
                    "check_availability": {"doctor": "Dr. NonExistentDoctor"}
                },
            },
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "FAIL", run
    failed = [a for a in run["summary"]["assertions"] if a["status"] == "FAIL"]
    assert any("tool_arguments" in f["name"] for f in failed)


# 5. TOOL EXECUTION FAILURE
def test_05_tool_execution_failure(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Tool failure scenario",
            "caller_goal": "Handle booking failure gracefully",
            "turns": [
                "I want to book an appointment with Dr. Rao.",
                "Yes, book it please.",
            ],
            "initial_mock_state": {
                "configured_failures": {"book_appointment": "Database connection timeout"}
            },
            "expected": {
                "required_tool_calls": ["book_appointment"],
                "tool_status": {"book_appointment": "FAILED"},
            },
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "PASS", run


# 6. PROVIDER TIMEOUT AND RECOVERY
def test_06_provider_timeout_and_recovery(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Transient timeout recovery",
            "caller_goal": "Check availability through transient provider retry",
            "turns": ["I want to check availability."],
            "provider_config": {
                "llm": {"retry_failures": 1}
            },
            "expected": {
                "required_tool_calls": ["check_availability"]
            },
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "PASS", run


# 7. MALFORMED PROVIDER RESPONSES
def test_07_malformed_provider_responses(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Malformed STT payload",
            "caller_goal": "Test malformed payload safety",
            "turns": ["Hello"],
            "provider_config": {
                "stt": {"malformed_response": True}
            },
            "expected": {},
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] in ("PASS", "FAIL")  # Safely handled without server 500


# 8. MAXIMUM TURN ENFORCEMENT
def test_08_maximum_turn_enforcement(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Max turn guard",
            "caller_goal": "Loop turns",
            "turns": ["Turn 1", "Turn 2", "Turn 3", "Turn 4", "Turn 5"],
            "max_turns": 2,
            "expected": {"max_turns": 2},
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["turn_count"] <= 2


# 9. SESSION TERMINATION
def test_09_session_termination(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Clean session termination",
            "caller_goal": "Farewell termination",
            "turns": ["Goodbye, thank you!"],
            "expected": {
                "session_status": "COMPLETED",
                "final_response_contains": ["Goodbye"],
            },
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "PASS", run


# 10. PERSISTENCE OF RESULTS AND TRACES
def test_10_persistence_of_results_and_traces(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Trace persistence flow",
            "turns": ["I need appointment availability."],
            "expected": {"required_tool_calls": ["check_availability"]},
        },
    ).json()

    run = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    run_id = run["id"]

    db_run = db.query(DbTestRun).filter(DbTestRun.id == run_id).one()
    assert db_run.runtime_session_id is not None
    assert db_run.duration_ms is not None
    assert db_run.turn_count >= 1
    assert db_run.summary_json is not None
    assert db_run.metrics_json is not None

    events_count = db.query(DbTestRunEvent).filter(DbTestRunEvent.run_id == run_id).count()
    assert events_count > 0

    detail = client.get(f"/api/test-scenarios/runs/{run_id}", headers=operator_headers).json()
    assert len(detail["events"]) == events_count


# 11. CONCURRENT TEST ISOLATION
def test_11_concurrent_test_isolation(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    # Scenario A with Dr. Rao
    scn_a = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Scenario A",
            "turns": ["I want Dr. Rao on 2026-10-10."],
            "initial_mock_state": {"doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]}},
            "expected": {"required_tool_calls": ["check_availability"]},
        },
    ).json()

    # Scenario B with Dr. Smith (zero slots)
    scn_b = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Scenario B",
            "turns": ["I want Dr. Smith on 2026-10-10."],
            "initial_mock_state": {"doctor_schedules": {"Dr. Smith": []}},
            "expected": {"forbidden_tool_calls": ["book_appointment"]},
        },
    ).json()

    run_a = client.post(f"/api/test-scenarios/{scn_a['id']}/runs", headers=operator_headers).json()
    run_b = client.post(f"/api/test-scenarios/{scn_b['id']}/runs", headers=operator_headers).json()

    assert run_a["status"] == "PASS"
    assert run_b["status"] == "PASS"
    assert run_a["id"] != run_b["id"]


# 12. TENANT ACCESS CONTROL
def test_12_tenant_access_control(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    # Attempt to forge mismatched client_id
    bad_res = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "client_id": "cli_unauthorized_other_tenant",
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Cross tenant injection",
            "turns": ["Hello"],
        },
    )
    assert bad_res.status_code == 403


# 13. TEMPLATES API & METRICS SUMMARY
def test_13_templates_api_and_metrics_summary(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    # Get templates
    tpl_res = client.get("/api/test-scenarios/templates", headers=operator_headers)
    assert tpl_res.status_code == 200
    templates = tpl_res.json()
    assert len(templates) == 10

    # Instantiate template 2 (Appointment Booking)
    inst_res = client.post(
        "/api/test-scenarios/templates/instantiate",
        headers=operator_headers,
        json={
            "template_id": "tpl_02_appointment_booking",
            "agent_id": agent.id,
            "agent_version_id": version.id,
        },
    )
    assert inst_res.status_code == 201
    instantiated_scenario = inst_res.json()
    assert "Appointment Booking" in instantiated_scenario["name"]

    # Run instantiated scenario
    run = client.post(f"/api/test-scenarios/{instantiated_scenario['id']}/runs", headers=operator_headers).json()
    assert run["status"] == "PASS"

    # Get metrics summary
    metrics_res = client.get("/api/test-scenarios/metrics/summary", headers=operator_headers)
    assert metrics_res.status_code == 200
    metrics = metrics_res.json()
    assert metrics["total_runs"] >= 1
    assert "latencies" in metrics


# 14. REGRESSION COMPARISON
def test_14_regression_comparison(client, operator_headers, db):
    agent, version = _setup_agent(client, operator_headers, db)

    scenario = client.post(
        "/api/test-scenarios",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "name": "Regression baseline scenario",
            "turns": ["I want appointment availability."],
            "expected": {"required_tool_calls": ["check_availability"]},
        },
    ).json()

    run1 = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()
    run2 = client.post(f"/api/test-scenarios/{scenario['id']}/runs", headers=operator_headers).json()

    comp_res = client.get(
        f"/api/test-scenarios/runs/{run1['id']}/compare/{run2['id']}",
        headers=operator_headers,
    )
    assert comp_res.status_code == 200
    comp = comp_res.json()
    assert comp["baseline_run_id"] == run1["id"]
    assert comp["comparison_run_id"] == run2["id"]
    assert "verdict" in comp
    assert "tool_execution" in comp
    assert "latency" in comp
