from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.client import Client


def test_mock_environment_status_is_server_selected(client, operator_headers):
    response = client.get("/api/mock/environment", headers=operator_headers)

    assert response.status_code == 200
    assert response.json() == {
        "mode": "mock",
        "mock": True,
        "external_calls_allowed": False,
        "label": "MOCK ENVIRONMENT - NO EXTERNAL PROVIDER CALLS",
    }


def test_seed_creates_repeatable_isolated_mock_dataset(client, operator_headers, db):
    response = client.post("/api/mock/seed", headers=operator_headers)

    assert response.status_code == 200
    assert response.json()["clients"] == 3
    assert db.query(Client).filter(Client.id.like("mock_%")).count() == 3
    assert db.query(Agent).filter(Agent.id.like("mock_%")).count() == 3
    assert db.query(Call).filter(Call.id.like("mock_%")).count() == 3

    second = client.post("/api/mock/seed", headers=operator_headers)
    assert second.status_code == 200
    assert db.query(Client).filter(Client.id.like("mock_%")).count() == 3
    assert db.query(Call).filter(Call.id.like("mock_%")).count() == 3


def test_mock_reset_is_admin_only_and_removes_only_mock_records(client, operator_headers, auth_headers, db):
    client.post("/api/mock/seed", headers=operator_headers)

    forbidden = client.post("/api/mock/reset", headers=operator_headers)
    assert forbidden.status_code == 403

    reset = client.post("/api/mock/reset", headers=auth_headers)
    assert reset.status_code == 200
    assert reset.json()["reset"] is True
    assert db.query(Client).filter(Client.id.like("mock_%")).count() == 0
    assert db.query(Call).filter(Call.id.like("mock_%")).count() == 0


def test_mock_analytics_are_labeled_and_excluded_from_billing(client, operator_headers):
    client.post("/api/mock/seed", headers=operator_headers)

    response = client.get("/api/mock/analytics", headers=operator_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mock"] is True
    assert data["billing_excluded"] is True
    assert data["calls"]["total"] == 3
    assert data["usage"]["llm_input_tokens"] > 0
    assert data["cost"]["total_usd"] >= 0


def test_simulated_call_uses_runtime_and_persists_call(client, operator_headers, db):
    client.post("/api/mock/seed", headers=operator_headers)
    agent = db.query(Agent).filter(Agent.id == "mock_agt_acme_health").one()
    version = db.query(AgentVersion).filter(AgentVersion.id == "mock_agtv_1").one()

    response = client.post(
        "/api/mock/calls/simulate",
        headers=operator_headers,
        json={
            "agent_id": agent.id,
            "agent_version_id": version.id,
            "utterances": ["I want to check appointment availability", "Thank you"],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["label"] == "SIMULATED CALL"
    assert data["status"] == "COMPLETED"
    assert len(data["turns"]) == 2
    assert data["event_count"] > 0
    assert data["billing_excluded"] is True
    assert db.query(Call).filter(Call.id == data["call_id"]).one().provider == "mock_telephony"


def test_complete_pending_ends_only_mock_outbound_calls(client, operator_headers, db):
    client.post("/api/mock/seed", headers=operator_headers)
    agent = db.query(Agent).filter(Agent.id == "mock_agt_acme_health").one()

    def outbound(call_id, provider_call_id):
        return Call(
            id=call_id, client_id=agent.client_id, agent_id=agent.id, agent_version_id="mock_agtv_1",
            provider="exotel", provider_call_id=provider_call_id, direction="OUTBOUND",
            caller_number="+910000000000", destination_number="+919876543210", status="INITIATED",
        )

    db.add_all([
        outbound("call_sim_a", "mock_call_aaaaaaaaaaaa"),
        outbound("call_sim_b", "mock_call_bbbbbbbbbbbb"),
        outbound("call_real_c", "exotel_real_sid"),
    ])
    db.commit()

    only_b = client.post(
        "/api/mock/calls/complete-pending", headers=operator_headers,
        json={"status": "no-answer", "call_ids": ["call_sim_b"]},
    )
    assert only_b.status_code == 200, only_b.text
    assert only_b.json()["call_ids"] == ["call_sim_b"]

    rest = client.post("/api/mock/calls/complete-pending", headers=operator_headers, json={"duration_seconds": 45})
    assert rest.json()["call_ids"] == ["call_sim_a"]

    db.expire_all()
    a, b, c = (db.get(Call, i) for i in ("call_sim_a", "call_sim_b", "call_real_c"))
    assert (a.status, a.duration_seconds) == ("COMPLETED", 45.0)
    assert (b.status, b.termination_reason) == ("FAILED", "no-answer")
    assert c.status == "INITIATED"
