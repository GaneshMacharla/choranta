def test_dashboard_summary_metrics(client, auth_headers):
    # Fetch initial dashboard summary
    res = client.get("/api/dashboard/summary", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_clients" in data
    assert "active_clients" in data
    assert "total_agents" in data
    assert "active_agents" in data
    assert "recent_clients" in data
    assert "recent_agents" in data
    assert isinstance(data["recent_clients"], list)
    assert isinstance(data["recent_agents"], list)

    initial_clients = data["total_clients"]
    initial_agents = data["total_agents"]

    # Create a client
    c_res = client.post(
        "/api/clients",
        json={"name": "Bistro Gourmet", "business_type": "RESTAURANT"},
        headers=auth_headers
    )
    client_id = c_res.json()["id"]

    # Create an agent
    a_res = client.post(
        "/api/agents",
        json={"client_id": client_id, "name": "Table Reservation Bot", "role": "Hostess"},
        headers=auth_headers
    )

    # Recheck dashboard metrics
    res2 = client.get("/api/dashboard/summary", headers=auth_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["total_clients"] == initial_clients + 1
    assert data2["total_agents"] == initial_agents + 1
    # Verify recent clients includes our new client
    client_names = [c["name"] for c in data2["recent_clients"]]
    assert "Bistro Gourmet" in client_names
