def test_create_and_get_agent(client, auth_headers):
    # 1. Create client first
    cli_res = client.post(
        "/api/clients",
        json={"name": "Metropolitan Realty Group", "business_type": "REAL_ESTATE"},
        headers=auth_headers
    )
    client_id = cli_res.json()["id"]

    # 2. Create agent
    agent_payload = {
        "client_id": client_id,
        "name": "Leasing Inquiries Agent",
        "role": "AI Property Manager",
        "description": "Answers buyer calls, qualifies budgets, and schedules on-site showings."
    }
    create_res = client.post("/api/agents", json=agent_payload, headers=auth_headers)
    assert create_res.status_code == 201, create_res.text
    agent = create_res.json()
    assert agent["id"].startswith("agt_")
    assert agent["status"] == "DRAFT"
    assert agent["client_id"] == client_id
    assert agent["client_name"] == "Metropolitan Realty Group"

    # 3. Get agent by id
    agent_id = agent["id"]
    get_res = client.get(f"/api/agents/{agent_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == agent_id

    # 4. Agent versions endpoint
    versions_res = client.get(f"/api/agents/{agent_id}/versions", headers=auth_headers)
    assert versions_res.status_code == 200
    assert isinstance(versions_res.json(), list)


def test_create_agent_invalid_client(client, auth_headers):
    agent_payload = {
        "client_id": "cli_nonexistent999",
        "name": "Front Desk Agent",
        "role": "Receptionist"
    }
    res = client.post("/api/agents", json=agent_payload, headers=auth_headers)
    assert res.status_code == 404


def test_update_agent_status(client, auth_headers):
    cli_res = client.post(
        "/api/clients",
        json={"name": "Serenity Med Spa", "business_type": "CLINIC"},
        headers=auth_headers
    )
    client_id = cli_res.json()["id"]

    agent_res = client.post(
        "/api/agents",
        json={"client_id": client_id, "name": "Appointment Booker", "role": "Scheduler"},
        headers=auth_headers
    )
    agent_id = agent_res.json()["id"]

    # Valid lifecycle transition: DRAFT -> TESTING -> READY
    patch1 = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "TESTING"},
        headers=auth_headers
    )
    assert patch1.status_code == 200
    assert patch1.json()["status"] == "TESTING"

    patch2 = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "READY"},
        headers=auth_headers
    )
    assert patch2.status_code == 200
    assert patch2.json()["status"] == "READY"
