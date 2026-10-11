def test_create_and_get_client(client, auth_headers):
    # 1. Create client
    payload = {
        "name": "St. Jude Memorial Hospital",
        "business_type": "HOSPITAL",
        "description": "Multi-specialty hospital with cardiology and trauma center",
        "contact_name": "Dr. Sarah Jenkins",
        "contact_email": "sarah.jenkins@stjude.example.com",
        "contact_phone": "+1-555-019-2834",
        "timezone": "America/New_York"
    }
    create_res = client.post("/api/clients", json=payload, headers=auth_headers)
    assert create_res.status_code == 201, create_res.text
    created = create_res.json()
    assert created["id"].startswith("cli_")
    assert created["name"] == payload["name"]
    assert created["business_type"] == "HOSPITAL"
    assert created["status"] == "ACTIVE"
    assert created["agent_count"] == 0

    # 2. Get client by id
    client_id = created["id"]
    get_res = client.get(f"/api/clients/{client_id}", headers=auth_headers)
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["id"] == client_id
    assert retrieved["contact_name"] == "Dr. Sarah Jenkins"


def test_client_validation_errors(client, auth_headers):
    # Missing required name
    bad_res1 = client.post(
        "/api/clients",
        json={"name": "", "business_type": "CLINIC"},
        headers=auth_headers
    )
    assert bad_res1.status_code == 422

    # Invalid email format
    bad_res2 = client.post(
        "/api/clients",
        json={
            "name": "Apex Dental",
            "business_type": "CLINIC",
            "contact_email": "not-an-email"
        },
        headers=auth_headers
    )
    assert bad_res2.status_code == 422


def test_duplicate_client_name_rejected(client, auth_headers):
    payload = {
        "name": "Lumiere Salon & Spa",
        "business_type": "SALON"
    }
    res1 = client.post("/api/clients", json=payload, headers=auth_headers)
    assert res1.status_code == 201

    # Second attempt with same name
    res2 = client.post("/api/clients", json=payload, headers=auth_headers)
    assert res2.status_code == 409


def test_update_client(client, auth_headers):
    create_res = client.post(
        "/api/clients",
        json={"name": "Grand Hotel Horizon", "business_type": "HOTEL"},
        headers=auth_headers
    )
    client_id = create_res.json()["id"]

    patch_res = client.post = client.patch(
        f"/api/clients/{client_id}",
        json={"status": "INACTIVE", "description": "Closed for seasonal renovation"},
        headers=auth_headers
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["status"] == "INACTIVE"
    assert updated["description"] == "Closed for seasonal renovation"
