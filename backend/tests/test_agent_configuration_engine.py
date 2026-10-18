import pytest
from app.schemas.agent_spec import CanonicalAgentSpec


def test_get_and_update_agent_configuration(client, auth_headers):
    # 1. Onboard client and agent
    cli = client.post("/api/clients", json={"name": "Premier Cardiology", "business_type": "CLINIC"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "Cardiology Receptionist", "role": "Receptionist"}, headers=auth_headers).json()
    agent_id = agent["id"]

    # 2. Get configuration (should return structured baseline draft)
    get_res = client.get(f"/api/agents/{agent_id}/configuration", headers=auth_headers)
    assert get_res.status_code == 200
    config_data = get_res.json()["configuration"]
    assert config_data["identity"]["organization"] == "Premier Cardiology"
    assert config_data["instructions"]["primary_goal"] != ""
    assert len(config_data["instructions"]["responsibilities"]) > 0

    # 3. Update configuration draft
    updated_instructions = config_data["instructions"]
    updated_instructions["primary_goal"] = "Assist cardiac patients with appointments and clinic inquiries."
    updated_instructions["responsibilities"].append("Triage chest pain callers to immediate emergency queue")
    config_data["instructions"] = updated_instructions
    config_data["conversation"]["tone"] = "empathetic"

    put_res = client.put(f"/api/agents/{agent_id}/configuration", json=config_data, headers=auth_headers)
    assert put_res.status_code == 200
    saved_cfg = put_res.json()["configuration"]
    assert saved_cfg["instructions"]["primary_goal"] == "Assist cardiac patients with appointments and clinic inquiries."
    assert saved_cfg["conversation"]["tone"] == "empathetic"


def test_agent_configuration_validation(client, auth_headers):
    cli = client.post("/api/clients", json={"name": "Validation Dental", "business_type": "CLINIC"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "Dental Assistant", "role": "Dental AI"}, headers=auth_headers).json()
    agent_id = agent["id"]

    # 1. Fetch current draft
    cfg = client.get(f"/api/agents/{agent_id}/configuration", headers=auth_headers).json()["configuration"]

    # 2. Break validation: empty primary goal and clear responsibilities
    cfg["instructions"]["primary_goal"] = ""
    cfg["instructions"]["responsibilities"] = []
    client.put(f"/api/agents/{agent_id}/configuration", json=cfg, headers=auth_headers)

    val_res = client.post(f"/api/agents/{agent_id}/configuration/validate", headers=auth_headers)
    assert val_res.status_code == 200
    res_data = val_res.json()
    assert res_data["valid"] is False
    assert any("primary_goal" in e["field"] for e in res_data["errors"])
    assert any("responsibilities" in e["field"] for e in res_data["errors"])

    # 3. Fix validation
    cfg["instructions"]["primary_goal"] = "Book dental cleanings and triage toothache emergencies."
    cfg["instructions"]["responsibilities"] = ["Schedule cleanings", "Confirm dental appointments"]
    client.put(f"/api/agents/{agent_id}/configuration", json=cfg, headers=auth_headers)

    val_res2 = client.post(f"/api/agents/{agent_id}/configuration/validate", headers=auth_headers)
    assert val_res2.status_code == 200
    assert val_res2.json()["valid"] is True


def test_only_admin_can_publish_version(client, auth_headers, operator_headers):
    cli = client.post("/api/clients", json={"name": "Lotus Hotel", "business_type": "HOTEL"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "Front Desk", "role": "Receptionist"}, headers=auth_headers).json()

    res = client.post(f"/api/agents/{agent['id']}/versions", headers=operator_headers)
    assert res.status_code == 403
    assert client.get(f"/api/agents/{agent['id']}/versions", headers=auth_headers).json() == []


def test_create_immutable_version_and_numbering(client, auth_headers):
    cli = client.post("/api/clients", json={"name": "Horizon Luxury Hotel", "business_type": "HOTEL"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "Concierge AI", "role": "Hotel Concierge"}, headers=auth_headers).json()
    agent_id = agent["id"]

    # 1. Create first version snapshot (v1)
    v1_res = client.post(f"/api/agents/{agent_id}/versions", headers=auth_headers)
    assert v1_res.status_code == 201
    v1_data = v1_res.json()
    assert v1_data["version_number"] == 1
    assert v1_data["status"] == "PUBLISHED"
    spec1 = v1_data["configuration_json"]
    assert spec1["schema_version"] == "1.0"
    assert spec1["agent"]["id"] == agent_id
    assert spec1["identity"]["organization"] == "Horizon Luxury Hotel"

    # 2. Modify draft configuration for v2
    cfg = client.get(f"/api/agents/{agent_id}/configuration", headers=auth_headers).json()["configuration"]
    cfg["conversation"]["greeting"] = "Welcome to Horizon Luxury Hotel. May I coordinate your stay?"
    cfg["conversation"]["tone"] = "luxurious"
    client.put(f"/api/agents/{agent_id}/configuration", json=cfg, headers=auth_headers)

    # 3. Create second version snapshot (v2)
    v2_res = client.post(f"/api/agents/{agent_id}/versions", headers=auth_headers)
    assert v2_res.status_code == 201
    v2_data = v2_res.json()
    assert v2_data["version_number"] == 2
    spec2 = v2_data["configuration_json"]
    assert spec2["conversation"]["tone"] == "luxurious"

    # 4. Verify v1 was NOT modified by draft changes (Immutability check!)
    v1_check = client.get(f"/api/agents/{agent_id}/versions/{v1_data['id']}", headers=auth_headers)
    assert v1_check.status_code == 200
    assert v1_check.json()["configuration_json"]["conversation"]["tone"] != "luxurious"

    # 5. List versions
    list_res = client.get(f"/api/agents/{agent_id}/versions", headers=auth_headers)
    assert list_res.status_code == 200
    versions = list_res.json()
    assert len(versions) == 2
    assert versions[0]["version_number"] == 2
    assert versions[1]["version_number"] == 1


def test_version_comparison_and_rollback(client, auth_headers):
    cli = client.post("/api/clients", json={"name": "Aura Med Spa", "business_type": "CLINIC"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "Aura Booking Specialist", "role": "Booking Agent"}, headers=auth_headers).json()
    agent_id = agent["id"]

    # 1. Create baseline v1
    v1 = client.post(f"/api/agents/{agent_id}/versions", headers=auth_headers).json()

    # 2. Modify draft and create v2
    cfg = client.get(f"/api/agents/{agent_id}/configuration", headers=auth_headers).json()["configuration"]
    cfg["instructions"]["primary_goal"] = "Coordinate botox and facial appointments exclusively."
    cfg["conversation"]["tone"] = "soothing"
    client.put(f"/api/agents/{agent_id}/configuration", json=cfg, headers=auth_headers)
    v2 = client.post(f"/api/agents/{agent_id}/versions", headers=auth_headers).json()

    # 3. Compare v1 and v2
    comp_res = client.get(f"/api/agents/{agent_id}/versions/compare?base_version=1&compare_version=2", headers=auth_headers)
    assert comp_res.status_code == 200
    diff_data = comp_res.json()
    assert diff_data["base_version_number"] == 1
    assert diff_data["compare_version_number"] == 2
    diff_fields = [c["field"] for c in diff_data["changes"]]
    assert any("Primary Goal" in f for f in diff_fields)
    assert any("Tone" in f for f in diff_fields)

    # 4. Rollback to v1: restore v1 into new draft
    restore_res = client.post(f"/api/agents/{agent_id}/versions/{v1['id']}/restore", headers=auth_headers)
    assert restore_res.status_code == 200
    assert restore_res.json()["restored_from_version"] == 1

    # 5. Verify current draft has restored v1 properties
    restored_cfg = client.get(f"/api/agents/{agent_id}/configuration", headers=auth_headers).json()["configuration"]
    assert restored_cfg["conversation"]["tone"] != "soothing"

    # 6. Create v3 from this restored draft
    v3 = client.post(f"/api/agents/{agent_id}/versions", headers=auth_headers).json()
    assert v3["version_number"] == 3
    assert v3["configuration_json"]["conversation"]["tone"] != "soothing"


def test_knowledge_tools_and_integrations_attachment(client, auth_headers):
    cli = client.post("/api/clients", json={"name": "Multi-Tool Medical", "business_type": "HOSPITAL"}, headers=auth_headers).json()
    agent = client.post("/api/agents", json={"client_id": cli["id"], "name": "General Triage", "role": "Triage AI"}, headers=auth_headers).json()
    agent_id = agent["id"]

    # 1. Knowledge catalog
    knw_list = client.get("/api/knowledge", headers=auth_headers).json()
    assert len(knw_list) > 0
    test_knw_id = knw_list[0]["id"]

    # Attach knowledge to agent
    att_knw = client.post(f"/api/agents/{agent_id}/knowledge/{test_knw_id}", headers=auth_headers)
    assert att_knw.status_code == 200

    agent_knw = client.get(f"/api/agents/{agent_id}/knowledge", headers=auth_headers).json()
    assert any(k["id"] == test_knw_id for k in agent_knw)

    # Detach knowledge
    det_knw = client.delete(f"/api/agents/{agent_id}/knowledge/{test_knw_id}", headers=auth_headers)
    assert det_knw.status_code == 200
    agent_knw_after = client.get(f"/api/agents/{agent_id}/knowledge", headers=auth_headers).json()
    assert not any(k["id"] == test_knw_id for k in agent_knw_after)

    # 2. Tools catalog
    tools_list = client.get("/api/tools", headers=auth_headers).json()
    assert len(tools_list) > 0
    test_tool_id = "check_availability"

    # Enable tool
    att_tool = client.post(f"/api/agents/{agent_id}/tools/{test_tool_id}", headers=auth_headers)
    assert att_tool.status_code == 200

    agent_tools = client.get(f"/api/agents/{agent_id}/tools", headers=auth_headers).json()
    assert any(t["id"] == test_tool_id for t in agent_tools)

    # Disable tool
    det_tool = client.delete(f"/api/agents/{agent_id}/tools/{test_tool_id}", headers=auth_headers)
    assert det_tool.status_code == 200
    agent_tools_after = client.get(f"/api/agents/{agent_id}/tools", headers=auth_headers).json()
    assert not any(t["id"] == test_tool_id for t in agent_tools_after)

    # 3. Integrations catalog
    int_list = client.get("/api/integrations", headers=auth_headers).json()
    assert len(int_list) > 0
    test_int_id = int_list[0]["id"]

    # Attach integration
    att_int = client.post(f"/api/agents/{agent_id}/integrations/{test_int_id}", headers=auth_headers)
    assert att_int.status_code == 200

    agent_ints = client.get(f"/api/agents/{agent_id}/integrations", headers=auth_headers).json()
    assert any(i["id"] == test_int_id for i in agent_ints)

    # Detach integration
    det_int = client.delete(f"/api/agents/{agent_id}/integrations/{test_int_id}", headers=auth_headers)
    assert det_int.status_code == 200
