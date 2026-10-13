"""Each AI employee has its own knowledge (notes / FAQ) that it reads on every conversation."""
from fastapi.testclient import TestClient

from app.runtime.providers.base import LLMResult
from app.runtime.providers.mock.llm import MockLLMProvider
from test_runtime_foundation import helper_create_client_and_agent, helper_create_published_version


def test_agent_knowledge_tab_reaches_the_conversation(client: TestClient, auth_headers: dict, monkeypatch):
    seen = []
    monkeypatch.setattr(MockLLMProvider, "generate", lambda self, system_instruction, messages, available_tools=None, **kw:
                        seen.append(system_instruction) or LLMResult(text="We open at 10am.", usage={"input_tokens": 1, "output_tokens": 1}))
    _, agent_id = helper_create_client_and_agent(client, auth_headers, "knowledge_tab")

    created = client.post(f"/api/agents/{agent_id}/knowledge", headers=auth_headers, json={
        "name": "Clinic timings", "type": "FAQ", "content": "Q: When do you open?\nA: 10am to 8pm, closed Sundays.",
    })
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["owner_agent_id"] == agent_id and entry["content"].startswith("Q: When")
    assert entry["id"] in [k["id"] for k in client.get(f"/api/agents/{agent_id}/knowledge", headers=auth_headers).json()]
    # Private to this AI employee: not in the shared library
    assert entry["id"] not in [k["id"] for k in client.get("/api/knowledge", headers=auth_headers).json()]

    edited = client.put(f"/api/agents/{agent_id}/knowledge/{entry['id']}", headers=auth_headers, json={
        "name": "Clinic timings", "type": "FAQ", "content": "Q: When do you open?\nA: 9am to 9pm every day.",
    }).json()
    assert "9am to 9pm" in edited["content"]

    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post("/api/runtime/sessions", headers=auth_headers,
                             json={"agent_id": agent_id, "agent_version_id": version_id}).json()["id"]
    client.post(f"/api/runtime/sessions/{session_id}/simulate_turn", headers=auth_headers, json={"input_text": "When do you open?"})
    assert seen and "Business knowledge" in seen[-1] and "9am to 9pm every day" in seen[-1]

    # Removing it from the tab deletes it
    client.delete(f"/api/agents/{agent_id}/knowledge/{entry['id']}", headers=auth_headers)
    assert entry["id"] not in [k["id"] for k in client.get(f"/api/agents/{agent_id}/knowledge", headers=auth_headers).json()]
    assert client.put(f"/api/agents/{agent_id}/knowledge/{entry['id']}", headers=auth_headers,
                      json={"name": "x", "type": "NOTES", "content": "y"}).status_code == 404
