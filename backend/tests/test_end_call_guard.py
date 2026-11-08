"""
A silent hang-up mid-conversation is refused once, so the AI employee says what happens next (Sarvam once hung up on
a caller right after "online, weekends are better", losing the demo booking). Goodbyes with words, callers who are
wrapping up, and a second attempt always go through.
"""
from fastapi.testclient import TestClient

from app.runtime import call_rules
from app.runtime.conversation import ConversationState
from app.runtime.providers.base import LLMResult, ToolCallRequest
from app.runtime.providers.mock.llm import MockLLMProvider
from test_runtime_foundation import _read_sse, helper_create_client_and_agent, helper_create_published_version


def _said(text: str) -> ConversationState:
    conversation = ConversationState(system_instruction="You are Ananya.")
    conversation.add_user_message(text)
    return conversation


def test_silent_hang_up_mid_conversation_is_refused_once():
    mid = _said("Online, and weekends are better for me.")
    assert call_rules.refuse_early_end(mid, already_refused=False, said="") is True
    assert call_rules.refuse_early_end(mid, already_refused=True, said="") is False


def test_goodbyes_and_wrapping_up_callers_are_left_alone():
    assert call_rules.refuse_early_end(_said("Online, weekends."), False, said="Our team will call you. Bye!") is False
    for closing in ("I'm not interested, bye.", "Thank you, that's all.", "వద్దు అండి", "धन्यवाद", "nahi chahiye"):
        assert call_rules.refuse_early_end(_said(closing), False, said="") is False, closing


def test_refused_hang_up_is_recorded_for_the_next_reply():
    conversation = _said("Online, weekends are better.")
    call_rules.refuse_end_call(conversation, None, [ToolCallRequest(id="e1", tool_name="end_call", arguments={})])
    tool_result = conversation.messages[-1]
    assert "Not ended" in tool_result.content and "what happens next" in tool_result.content


def test_chat_continues_after_a_silent_hang_up_attempt(client: TestClient, auth_headers: dict, monkeypatch):
    calls = []

    def fake_generate(self, system_instruction, messages, available_tools=None, **kwargs):
        calls.append(messages[-1])
        if messages[-1].get("role") == "tool":  # told the hang-up was refused
            return LLMResult(text="Our team will call you to confirm the demo. Anything else?",
                             usage={"input_tokens": 10, "output_tokens": 5})
        return LLMResult(text="", tool_calls=[ToolCallRequest(id="e1", tool_name="end_call", arguments={})],
                         finish_reason="tool_calls", usage={"input_tokens": 10, "output_tokens": 5})

    monkeypatch.setattr(MockLLMProvider, "generate", fake_generate)
    _, agent_id = helper_create_client_and_agent(client, auth_headers, "silent_hangup")
    version_id = helper_create_published_version(client, auth_headers, agent_id)["id"]
    session_id = client.post("/api/runtime/sessions", headers=auth_headers,
                             json={"agent_id": agent_id, "agent_version_id": version_id}).json()["id"]
    done = _read_sse(client.post(f"/api/runtime/sessions/{session_id}/stream_turn", headers=auth_headers,
                                 json={"input_text": "Online, and weekends are better for me."}))[-1]
    assert done["call_ended"] is False
    assert done["assistant_response"] == "Our team will call you to confirm the demo. Anything else?"


def test_caller_recap_is_sent_with_each_reply():
    from app.runtime.context import RuntimeContext
    from test_phase3c_telephony import _build_test_agent_spec

    ctx = RuntimeContext("s", "a", "c", "v", _build_test_agent_spec(), {})
    assert "What the caller has told you so far" not in ctx.instruction_for_turn()
    ctx.conversation.add_user_message("I'm a fresher and I want the data analytics demo.")
    turn = ctx.instruction_for_turn()
    assert turn.rstrip().endswith("- I'm a fresher and I want the data analytics demo.")
    assert "never ask for any of this again" in turn
