"""The AI employee stays on the business's topic and hangs up (end_call) on unrelated talk, on every channel."""
from fastapi.testclient import TestClient

from app.runtime import call_rules
from app.runtime.providers.base import LLMResult, ToolCallRequest
from app.runtime.providers.mock.llm import MockLLMProvider
from test_runtime_foundation import _read_sse, helper_create_client_and_agent, helper_create_published_version


class _Spec:
    class business_context:  # noqa: N801
        business_name = "Smile Dental Care"
    class identity:  # noqa: N801
        organization = "Ignored Org"
    class conversation:  # noqa: N801
        farewell = "Thanks for calling Smile Dental Care!"


def test_rules_name_the_business_and_end_call():
    text = call_rules.rules_text(_Spec)
    assert "Only talk about Smile Dental Care" in text and "end_call" in text
    assert call_rules.goodbye_text(_Spec, None) == "Thanks for calling Smile Dental Care!"
    assert call_rules.goodbye_text(_Spec, " Bye! ") == "Bye!"
    assert [t["name"] for t in call_rules.with_end_call([{"name": "book_appointment"}])] == ["book_appointment", "end_call"]
    assert len(call_rules.with_end_call([call_rules.END_CALL_TOOL])) == 1


def test_off_topic_message_ends_the_chat(client: TestClient, auth_headers: dict, monkeypatch):
    seen = {}

    def fake_generate(self, system_instruction, messages, available_tools=None, **kwargs):
        seen["system"] = system_instruction
        seen["tools"] = [t.get("name") for t in (available_tools or [])]
        last = messages[-1]["content"] if messages else ""
        if "cricket" in str(last).lower():
            return LLMResult(text="Sorry, I can only help with clinic enquiries. Goodbye!",
                             tool_calls=[ToolCallRequest(id="c1", tool_name="end_call", arguments={"reason": "off_topic"})],
                             finish_reason="tool_calls", usage={"input_tokens": 10, "output_tokens": 5})
        return LLMResult(text="Happy to help with your appointment.", usage={"input_tokens": 10, "output_tokens": 5})

    monkeypatch.setattr(MockLLMProvider, "generate", fake_generate)
    _, agent_id = helper_create_client_and_agent(client, auth_headers, "off_topic_hangup")
    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post("/api/runtime/sessions", headers=auth_headers,
                             json={"agent_id": agent_id, "agent_version_id": version_id}).json()["id"]

    on_topic = _read_sse(client.post(f"/api/runtime/sessions/{session_id}/stream_turn", headers=auth_headers,
                                     json={"input_text": "Can I book a cleaning tomorrow?"}))[-1]
    assert on_topic["type"] == "done" and on_topic["call_ended"] is False
    assert call_rules.RULES_MARKER in seen["system"] and "end_call" in seen["tools"]

    off_topic = _read_sse(client.post(f"/api/runtime/sessions/{session_id}/stream_turn", headers=auth_headers,
                                      json={"input_text": "Who won the cricket match yesterday?"}))[-1]
    assert off_topic["call_ended"] is True
    assert off_topic["assistant_response"].endswith("Goodbye!")
    assert off_topic["tool_calls_executed"] == 0  # end_call isn't run as a business tool

    # The session is over: no more turns
    assert client.get(f"/api/runtime/sessions/{session_id}", headers=auth_headers).json()["status"] != "ACTIVE"
    again = client.post(f"/api/runtime/sessions/{session_id}/stream_turn", headers=auth_headers, json={"input_text": "hello?"})
    assert again.status_code >= 400


def test_simulated_turn_reports_hang_up(client: TestClient, auth_headers: dict, monkeypatch):
    monkeypatch.setattr(MockLLMProvider, "generate", lambda self, system_instruction, messages, available_tools=None, **kw: LLMResult(
        text="", tool_calls=[ToolCallRequest(id="c1", tool_name="end_call", arguments={})], finish_reason="tool_calls"))
    _, agent_id = helper_create_client_and_agent(client, auth_headers, "sim_hangup")
    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post("/api/runtime/sessions", headers=auth_headers,
                             json={"agent_id": agent_id, "agent_version_id": version_id}).json()["id"]
    result = client.post(f"/api/runtime/sessions/{session_id}/simulate_turn", headers=auth_headers,
                         json={"input_text": "tell me a joke"}).json()
    assert result["call_ended"] is True and result["assistant_response"]  # falls back to the farewell / default goodbye
    assert client.get(f"/api/runtime/sessions/{session_id}", headers=auth_headers).json()["status"] != "ACTIVE"
