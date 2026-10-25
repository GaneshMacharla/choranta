from datetime import timedelta
import pytest
import jwt
from app.core.config import Settings, settings
from app.core.security import create_access_token


def test_unauthorized_api_access(client):
    """Endpoints must reject requests missing Authorization headers."""
    assert client.get("/api/dashboard/summary").status_code == 401
    assert client.get("/api/clients").status_code == 401
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/clients", json={"name": "Test", "business_type": "CLINIC"}).status_code == 401


def test_invalid_jwt_format_and_signature(client):
    """Malformed tokens and forged signatures must be rejected with 401."""
    # 1. Malformed token
    res1 = client.get("/api/dashboard/summary", headers={"Authorization": "Bearer not-a-valid-token"})
    assert res1.status_code == 401
    assert "Invalid" in res1.json()["detail"] or "expired" in res1.json()["detail"]

    # 2. Forged token signed with incorrect secret
    forged_token = jwt.encode(
        {"sub": "usr_fake", "exp": 9999999999},
        "wrong-secret-key-that-does-not-match-at-all",
        algorithm="HS256"
    )
    res2 = client.get("/api/dashboard/summary", headers={"Authorization": f"Bearer {forged_token}"})
    assert res2.status_code == 401


def test_expired_jwt(client):
    """Expired tokens must be rejected with 401 and explicit expiration detail."""
    expired_token = create_access_token(
        subject="usr_admin",
        expires_delta=timedelta(seconds=-60)  # Expired 1 minute ago
    )
    res = client.get("/api/dashboard/summary", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_role_enforcement(client, auth_headers, operator_headers):
    """
    Test RBAC authorization boundaries:
    - Operator cannot deactivate a client (status change requires ADMIN).
    - Operator cannot transition an agent to DEPLOYED or ARCHIVED (requires ADMIN).
    - Admin can perform both.
    """
    # 1. Create a client using operator (operators can onboard clients)
    create_res = client.post(
        "/api/clients",
        json={"name": "Sovereign Health Institute", "business_type": "HOSPITAL"},
        headers=operator_headers
    )
    assert create_res.status_code == 201
    client_id = create_res.json()["id"]

    # 2. Operator attempts to deactivate client -> 403 Forbidden
    deactivate_attempt = client.patch(
        f"/api/clients/{client_id}",
        json={"status": "INACTIVE"},
        headers=operator_headers
    )
    assert deactivate_attempt.status_code == 403
    assert "administrator privileges" in deactivate_attempt.json()["detail"].lower()

    # 3. Admin deactivates client -> 200 OK
    admin_deactivate = client.patch(
        f"/api/clients/{client_id}",
        json={"status": "INACTIVE"},
        headers=auth_headers
    )
    assert admin_deactivate.status_code == 200
    assert admin_deactivate.json()["status"] == "INACTIVE"

    # Reactivate client for next tests
    client.patch(f"/api/clients/{client_id}", json={"status": "ACTIVE"}, headers=auth_headers)

    # 4. Create an agent using operator
    agent_res = client.post(
        "/api/agents",
        json={"client_id": client_id, "name": "Nurse Assistant", "role": "Triage AI"},
        headers=operator_headers
    )
    assert agent_res.status_code == 201
    agent_id = agent_res.json()["id"]

    # 5. Operator moves agent from DRAFT to TESTING -> Allowed
    test_move = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "TESTING"},
        headers=operator_headers
    )
    assert test_move.status_code == 200

    # 6. Operator moves agent from TESTING to READY -> Allowed
    ready_move = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "READY"},
        headers=operator_headers
    )
    assert ready_move.status_code == 200

    # 7. Operator attempts to deploy agent to DEPLOYED -> 403 Forbidden (requires ADMIN)
    deploy_attempt = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "DEPLOYED"},
        headers=operator_headers
    )
    assert deploy_attempt.status_code == 403
    assert "administrator" in deploy_attempt.json()["detail"].lower()

    # 8. Admin deploys agent -> 200 OK
    admin_deploy = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "DEPLOYED"},
        headers=auth_headers
    )
    assert admin_deploy.status_code == 200
    assert admin_deploy.json()["status"] == "DEPLOYED"


def test_client_scoped_agents_and_ownership(client, auth_headers):
    """Test client-scoped agent queries and IDOR prevention."""
    c1 = client.post("/api/clients", json={"name": "Client Alpha Clinic", "business_type": "CLINIC"}, headers=auth_headers).json()
    c2 = client.post("/api/clients", json={"name": "Client Beta Hotel", "business_type": "HOTEL"}, headers=auth_headers).json()

    # Create agent under Client Alpha
    a1 = client.post("/api/agents", json={"client_id": c1["id"], "name": "Alpha Agent", "role": "Bot"}, headers=auth_headers).json()

    # Scoped query for Client Alpha should return 1 agent
    res1 = client.get(f"/api/clients/{c1['id']}/agents", headers=auth_headers)
    assert res1.status_code == 200
    assert len(res1.json()["items"]) == 1
    assert res1.json()["items"][0]["id"] == a1["id"]

    # Scoped query for Client Beta should return 0 agents
    res2 = client.get(f"/api/clients/{c2['id']}/agents", headers=auth_headers)
    assert res2.status_code == 200
    assert len(res2.json()["items"]) == 0

    # Scoped query for non-existent client returns 404
    res3 = client.get("/api/clients/cli_nonexistent999/agents", headers=auth_headers)
    assert res3.status_code == 404


def test_agent_belonging_to_client_and_inactive_client_guard(client, auth_headers):
    """Cannot create an agent under an INACTIVE client."""
    # 1. Create client and deactivate it
    cli = client.post("/api/clients", json={"name": "Inactive Client Group", "business_type": "CORPORATE"}, headers=auth_headers).json()
    client.patch(f"/api/clients/{cli['id']}", json={"status": "INACTIVE"}, headers=auth_headers)

    # 2. Attempt to create agent under inactive client -> 422 Validation Error
    res = client.post(
        "/api/agents",
        json={"client_id": cli["id"], "name": "Agent Under Inactive", "role": "Bot"},
        headers=auth_headers
    )
    assert res.status_code == 422
    assert "inactive" in res.json()["error"].lower() or "client status is inactive" in res.json()["error"].lower()


def test_invalid_agent_status_transitions(client, auth_headers):
    """
    Test strict lifecycle transition rules:
    - DRAFT cannot jump directly to DEPLOYED (must go through TESTING / READY).
    - ARCHIVED cannot jump directly to DEPLOYED.
    """
    cli = client.post("/api/clients", json={"name": "Transition Test Spa", "business_type": "SALON"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "Booking Bot", "role": "Scheduler"}, headers=auth_headers).json()
    agent_id = agent["id"]
    assert agent["status"] == "DRAFT"

    # 1. Attempt invalid transition: DRAFT -> DEPLOYED
    invalid_jump = client.patch(
        f"/api/agents/{agent_id}",
        json={"status": "DEPLOYED"},
        headers=auth_headers
    )
    assert invalid_jump.status_code == 422
    assert "invalid status transition" in invalid_jump.json()["error"].lower()

    # 2. Archive agent: DRAFT -> ARCHIVED is valid
    archive_res = client.patch(f"/api/agents/{agent_id}", json={"status": "ARCHIVED"}, headers=auth_headers)
    assert archive_res.status_code == 200
    assert archive_res.json()["status"] == "ARCHIVED"

    # 3. Attempt invalid transition: ARCHIVED -> DEPLOYED
    invalid_unarchive = client.patch(f"/api/agents/{agent_id}", json={"status": "DEPLOYED"}, headers=auth_headers)
    assert invalid_unarchive.status_code == 422
    assert "invalid status transition" in invalid_unarchive.json()["error"].lower()


def test_configuration_and_secret_validation():
    """Verify that production mode fails fast if required secrets or database are invalid."""
    # 1. Production mode with SQLite should fail
    with pytest.raises(ValueError, match="CRITICAL: Production DATABASE_URL must be a PostgreSQL"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="sqlite:///./fake.db",
            JWT_SECRET_KEY="a" * 32
        )

    # 2. Production mode with weak/missing JWT secret should fail
    with pytest.raises(ValueError, match="CRITICAL: Production requires either SUPABASE_JWT_SECRET or JWT_SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:pass@localhost:5432/db",
            JWT_SECRET_KEY="short-secret"
        )

    # 3. Production mode with wildcard CORS origin should fail
    with pytest.raises(ValueError, match="CRITICAL: Production CORS_ORIGINS cannot contain wildcard"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:pass@localhost:5432/db",
            JWT_SECRET_KEY="a" * 32,
            CORS_ORIGINS=["*"]
        )

    # 4. Valid production settings succeed
    valid_prod = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:pass@db.project.supabase.co:5432/postgres",
        JWT_SECRET_KEY="super-secure-production-jwt-secret-min-32-chars-long",
        CORS_ORIGINS=["https://choranta.internal"],
        PHONE_NUMBER_MOCK_MODE=False,  # the test run itself uses mock numbers
    )
    assert valid_prod.ENVIRONMENT == "production"
