import json

import httpx

from app.core.config import settings
from app.runtime.providers.base import LLMResult
from app.runtime.providers.sarvam.llm import SarvamLLMProvider


def _sse(*chunks) -> bytes:
    lines = [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]
    return ("\n\n".join(lines) + "\n\n").encode()


def _provider(handler) -> SarvamLLMProvider:
    provider = SarvamLLMProvider(api_key="sk_test")
    provider._client = httpx.Client(base_url="https://api.sarvam.ai/v1", transport=httpx.MockTransport(handler))
    return provider


def test_streams_text_and_sends_voice_friendly_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "Namaste "}}]},
            {"choices": [{"delta": {"content": "Rahul!"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 120, "completion_tokens": 6}},
        ))

    items = list(_provider(handler).generate_stream(
        "You are helpful.",
        [{"role": "system", "content": "ignored"}, {"role": "user", "content": "Hi"}],
        available_tools=[{"name": "search_properties", "description": "Find flats",
                          "input_schema": {"type": "object", "properties": {"location": {"type": "string"}}}}],
    ))
    assert items[:2] == ["Namaste ", "Rahul!"]
    final = items[-1]
    assert isinstance(final, LLMResult) and final.text == "Namaste Rahul!"
    assert final.usage == {"input_tokens": 120, "output_tokens": 6}

    body = seen["body"]
    assert body["model"] == settings.SARVAM_LLM_MODEL
    assert body["stream"] is True
    assert body["reasoning_effort"] is None  # thinking off for low latency
    assert body["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["tools"][0]["function"]["parameters"]["properties"]["location"]["type"] == "string"


def test_streamed_tool_call_is_assembled():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {
                "name": "search_properties", "arguments": "{\"loca"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
                "arguments": "tion\": \"Whitefield\"}"}}]}, "finish_reason": "tool_calls"}]},
        ))

    final = list(_provider(handler).generate_stream("sys", [{"role": "user", "content": "flats?"}]))[-1]
    assert final.finish_reason == "tool_calls"
    assert final.tool_calls[0].tool_name == "search_properties"
    assert final.tool_calls[0].arguments == {"location": "Whitefield"}
    assert final.usage["input_tokens"] > 0  # estimated when the stream has no usage block


def test_tool_history_is_sent_in_openai_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "Done."}}]}))

    list(_provider(handler).generate_stream("sys", [
        {"role": "user", "content": "flats?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "tool_name": "search_properties", "arguments": {"location": "Whitefield"}}]},
        {"role": "tool", "tool_call_id": "call_1", "name": "search_properties", "content": "{\"count\": 2}"},
    ]))
    msgs = seen["body"]["messages"]
    assert msgs[2]["tool_calls"][0]["function"] == {
        "name": "search_properties", "arguments": "{\"location\": \"Whitefield\"}"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": "{\"count\": 2}"}


def test_falls_back_to_gemini_when_sarvam_fails(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_FALLBACK_TO_GEMINI", True, raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g_test", raising=False)
    from app.runtime.providers.gemini import llm as gemini_llm

    def fake_stream(self, **kwargs):
        yield "from gemini"
        yield LLMResult(text="from gemini", usage={"input_tokens": 1, "output_tokens": 1})

    monkeypatch.setattr(gemini_llm.GeminiLLMProvider, "generate_stream", fake_stream)
    provider = _provider(lambda request: httpx.Response(503, content=b"overloaded"))
    items = list(provider.generate_stream("sys", [{"role": "user", "content": "hi"}]))
    assert items[0] == "from gemini"


def test_sarvam_call_cost_uses_inr_rates(monkeypatch):
    from app.services.call_costing import estimate_call_cost
    monkeypatch.setattr(settings, "SARVAM_INPUT_INR_PER_MILLION_TOKENS", 30.0, raising=False)
    monkeypatch.setattr(settings, "SARVAM_OUTPUT_INR_PER_MILLION_TOKENS", 70.0, raising=False)
    cost = estimate_call_cost(60, {"llm_provider": "sarvam", "llm_input_tokens": 1_000_000, "llm_output_tokens": 1_000_000})
    assert cost["breakdown"]["llm"] == 100.0
    assert cost["llm_provider"] == "sarvam"
