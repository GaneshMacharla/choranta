def test_login_success(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "admin@choranta.internal",
            "password": "chorantaAdmin2026!"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "admin@choranta.internal"
    assert data["user"]["role"] == "ADMIN"


def test_login_invalid_password(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "admin@choranta.internal",
            "password": "wrongPassword"
        }
    )
    assert response.status_code == 401


def test_login_nonexistent_user(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "ghost@choranta.internal",
            "password": "chorantaAdmin2026!"
        }
    )
    assert response.status_code == 401


def test_get_current_user_profile(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    user = response.json()
    assert user["email"] == "admin@choranta.internal"
    assert user["role"] == "ADMIN"


def test_unauthenticated_request_rejected(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
