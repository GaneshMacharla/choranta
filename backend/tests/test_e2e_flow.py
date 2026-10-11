import pytest
from app.core.config import settings


def test_complete_phase1_flow(client):
    # 1. Unauthenticated request to protected endpoint should be rejected
    unauth_res = client.get("/api/dashboard/summary")
    assert unauth_res.status_code == 401

    # 2. Login as internal operator/admin
    login_res = client.post(
        "/api/auth/login",
        json={
            "email": settings.INITIAL_ADMIN_EMAIL,
            "password": settings.INITIAL_ADMIN_PASSWORD
        }
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Verify user profile
    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == settings.INITIAL_ADMIN_EMAIL
    assert me_res.json()["role"] == "ADMIN"

    # 4. Initial dashboard summary check
    dash1_res = client.get("/api/dashboard/summary", headers=headers)
    assert dash1_res.status_code == 200
    initial_summary = dash1_res.json()

    # 5. Create a new client
    client_payload = {
        "name": "Elysium Wellness Retreat",
        "business_type": "HOTEL",
        "description": "Luxury wellness and recovery resort",
        "contact_name": "Elena Rostova",
        "contact_email": "elena@elysium.example.com",
        "contact_phone": "+1-800-555-0199",
        "timezone": "America/Los_Angeles"
    }
    create_client_res = client.post("/api/clients", json=client_payload, headers=headers)
    assert create_client_res.status_code == 201
    created_client = create_client_res.json()
    client_id = created_client["id"]
    assert client_id.startswith("cli_")
    assert created_client["name"] == "Elysium Wellness Retreat"
    assert created_client["status"] == "ACTIVE"

    # 6. Verify duplicate client rejection
    dup_res = client.post("/api/clients", json=client_payload, headers=headers)
    assert dup_res.status_code == 409

    # 7. Edit client details
    patch_client_res = client.patch(
        f"/api/clients/{client_id}",
        json={"description": "Updated wellness resort description", "contact_phone": "+1-800-555-0200"},
        headers=headers
    )
    assert patch_client_res.status_code == 200
    assert patch_client_res.json()["description"] == "Updated wellness resort description"
    assert patch_client_res.json()["contact_phone"] == "+1-800-555-0200"

    # 8. Create AI Employee for this client
    agent_payload = {
        "client_id": client_id,
        "name": "Concierge Booking Assistant",
        "role": "AI Guest Concierge",
        "description": "Assists high-profile guests with suite reservations and spa scheduling."
    }
    create_agent_res = client.post("/api/agents", json=agent_payload, headers=headers)
    assert create_agent_res.status_code == 201
    created_agent = create_agent_res.json()
    agent_id = created_agent["id"]
    assert agent_id.startswith("agt_")
    assert created_agent["status"] == "DRAFT"
    assert created_agent["client_id"] == client_id
    assert created_agent["client_name"] == "Elysium Wellness Retreat"

    # 9. Retrieve AI Employee details
    get_agent_res = client.get(f"/api/agents/{agent_id}", headers=headers)
    assert get_agent_res.status_code == 200
    assert get_agent_res.json()["id"] == agent_id

    # 10. Update AI Employee status: DRAFT -> TESTING -> READY
    client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "TESTING"},
        headers=headers
    )
    patch_agent_res = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "READY"},
        headers=headers
    )
    assert patch_agent_res.status_code == 200
    assert patch_agent_res.json()["status"] == "READY"

    # 11. Check Agent versions endpoint
    versions_res = client.get(f"/api/agents/{agent_id}/versions", headers=headers)
    assert versions_res.status_code == 200
    assert isinstance(versions_res.json(), list)

    # 12. Check client agent count updated
    get_client_res = client.get(f"/api/clients/{client_id}", headers=headers)
    assert get_client_res.status_code == 200
    assert get_client_res.json()["agent_count"] == 1

    # 13. Check dashboard metrics reflect newly created records
    dash2_res = client.get("/api/dashboard/summary", headers=headers)
    assert dash2_res.status_code == 200
    updated_summary = dash2_res.json()
    assert updated_summary["total_clients"] == initial_summary["total_clients"] + 1
    assert updated_summary["active_clients"] == initial_summary["active_clients"] + 1
    assert updated_summary["total_agents"] == initial_summary["total_agents"] + 1
    assert updated_summary["active_agents"] == initial_summary["active_agents"] + 1
