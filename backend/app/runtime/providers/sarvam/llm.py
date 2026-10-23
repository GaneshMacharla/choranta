import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx

from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import LLMResult, ToolCallRequest
from app.runtime.providers.llm import LLMProvider
from app.runtime.providers.sarvam.common import CONNECT_RETRIES, CONNECT_TIMEOUT_S, KEEPALIVE_S

logger = logging.getLogger("choranta.runtime.providers.sarvam.llm")

# Sarvam answers 429 over the plan's requests/min and 503 when briefly overloaded; a caller is waiting,
# so wait at most this long before retrying (Retry-After, else a short backoff)
RATE_LIMIT_STATUSES = (429, 503)
MAX_RETRY_WAIT_S = 2.0


def _retry_wait(response: httpx.Response, attempt: int) -> float:
    try:
        wait = float(response.headers.get("retry-after") or 0)
    except ValueError:
        wait = 0.0
    return min(MAX_RETRY_WAIT_S, wait or 0.5 * (2 ** attempt))


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


class SarvamLLMProvider(LLMProvider):
    """
    Sarvam chat completions (OpenAI-compatible) — sarvam-105b-conversations by default, the model
    Sarvam recommends for real-time voice agents. Reasoning ("thinking") is off by default for
    low latency. If Sarvam fails before producing output, the request falls back to Gemini.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.SARVAM_API_KEY
        self.default_model = model or settings.SARVAM_LLM_MODEL
        self._client: Optional[httpx.Client] = None

    @property
    def provider_name(self) -> str:
        return "sarvam"

    @property
    def environment(self) -> str:
        return "production"

    def initialize(self, config: Dict[str, Any]) -> None:
        key = self._api_key or config.get("api_key")
        if not key:
            raise ProviderUnavailable("LLM", "Sarvam: Missing SARVAM_API_KEY")
        self._api_key = key
        if self._client is None:
            self._client = httpx.Client(
                base_url=settings.SARVAM_BASE_URL.rstrip("/"),
                headers={"Authorization": f"Bearer {key}"},
                timeout=httpx.Timeout(settings.SARVAM_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
                transport=httpx.HTTPTransport(retries=CONNECT_RETRIES),  # retries failed connects only
            )

    def warm(self) -> None:
        """Opens the connection ahead of the first reply (any response will do)."""
        try:
            if self._client is None:
                self.initialize({})
            self._client.head("/")
        except Exception as e:
            logger.debug(f"Sarvam LLM warm-up failed: {type(e).__name__}: {e}")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _convert_messages(self, system_instruction: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
        if system_instruction:
            converted.append({"role": "system", "content": system_instruction})
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "system":
                continue  # already sent as system_instruction
            if role == "user":
                converted.append({"role": "user", "content": str(content)})
            elif role == "assistant":
                item: Dict[str, Any] = {"role": "assistant", "content": str(content) if content else None}
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                            "type": "function",
                            "function": {
                                "name": tc.get("tool_name") or tc.get("name"),
                                "arguments": json.dumps(tc.get("arguments") or tc.get("args") or {}),
                            },
                        }
                        for tc in tool_calls
                    ]
                elif item["content"] is None:
                    item["content"] = ""
                converted.append(item)
            elif role == "tool":
                converted.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id") or "",
                    "content": str(content),
                })
        return converted

    def _tools(self, available_tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not available_tools:
            return None
        tools = []
        for tool in available_tools:
            name = tool.get("name") or tool.get("id")
            if not name:
                continue
            schema = tool.get("input_schema") or {}
            if not isinstance(schema, dict) or schema.get("type") != "object":
                schema = {"type": "object", "properties": {}}
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description") or f"Execute action for {name}",
                    "parameters": schema,
                },
            })
        return tools or None

    def _payload(self, system_instruction, messages, available_tools, temperature, model, stream) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._convert_messages(system_instruction, messages),
            "temperature": temperature,
            "max_tokens": settings.SARVAM_MAX_TOKENS,
            "stream": stream,
        }
        effort = (settings.SARVAM_REASONING_EFFORT or "").strip().lower()
        # Sarvam disables reasoning when reasoning_effort is explicitly null
        payload["reasoning_effort"] = None if effort in ("", "none", "off") else effort
        tools = self._tools(available_tools)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except (TypeError, ValueError):
            return {"raw": raw}

    @staticmethod
    def _usage(usage: Optional[Dict[str, Any]], prompt_chars: int, output_text: str) -> Dict[str, int]:
        if usage:
            return {
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
            }
        # Streamed responses may omit usage; estimate so call costs aren't zero
        return {"input_tokens": prompt_chars // 4, "output_tokens": _estimate_tokens(output_text)}

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        result = None
        for item in self.generate_stream(system_instruction, messages, available_tools, temperature, model):
            if isinstance(item, LLMResult):
                result = item
        return result or LLMResult(text=None, tool_calls=[], finish_reason="stop", usage={"input_tokens": 0, "output_tokens": 0})

    async def generate_async(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        return await asyncio.to_thread(self.generate, system_instruction, messages, available_tools, temperature, model)

    def _open_stream(self, payload: Dict[str, Any]) -> httpx.Response:
        """Starts a streamed completion, retrying when Sarvam is rate-limited or briefly overloaded."""
        attempt = 0
        while True:
            response = self._client.send(self._client.build_request("POST", "/chat/completions", json=payload), stream=True)
            if response.status_code < 400:
                return response
            body = response.read().decode("utf-8", "replace")[:500]
            response.close()
            if response.status_code in RATE_LIMIT_STATUSES and attempt < settings.SARVAM_RATE_LIMIT_RETRIES:
                wait = _retry_wait(response, attempt)
                logger.warning(f"Sarvam LLM returned {response.status_code}; retrying in {wait:.1f}s")
                time.sleep(wait)
                attempt += 1
                continue
            raise RuntimeError(f"Sarvam API error {response.status_code}: {body}")

    def generate_stream(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> Iterator[Union[str, LLMResult]]:
        if self._client is None:
            self.initialize({})

        payload = self._payload(system_instruction, messages, available_tools, temperature, model, stream=True)
        prompt_chars = sum(len(str(m.get("content") or "")) for m in payload["messages"])
        text_parts: List[str] = []
        tool_parts: Dict[int, Dict[str, Any]] = {}
        usage: Optional[Dict[str, Any]] = None
        finish_reason = "stop"
        emitted = False

        try:
            with contextlib.closing(self._open_stream(payload)) as response:
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            emitted = True
                            text_parts.append(content)
                            yield content
                        for tc in delta.get("tool_calls") or []:
                            emitted = True
                            slot = tool_parts.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except Exception as e:
            if emitted:
                logger.error(f"Sarvam stream interrupted mid-response: {type(e).__name__}: {e}")
                raise
            if settings.SARVAM_FALLBACK_TO_GEMINI and settings.GEMINI_API_KEY:
                logger.warning(f"Sarvam LLM failed ({type(e).__name__}: {e}); falling back to Gemini for this turn.")
                from app.runtime.providers.gemini.llm import GeminiLLMProvider
                yield from GeminiLLMProvider().generate_stream(
                    system_instruction=system_instruction,
                    messages=messages,
                    available_tools=available_tools,
                    temperature=temperature,
                )
                return
            raise

        tool_calls = [
            ToolCallRequest(
                id=slot["id"] or f"call_{uuid.uuid4().hex[:8]}",
                tool_name=slot["name"],
                arguments=self._parse_arguments(slot["arguments"]),
            )
            for _, slot in sorted(tool_parts.items())
            if slot["name"]
        ]
        text = "".join(text_parts).strip() or None
        yield LLMResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else ("stop" if finish_reason != "length" else "length"),
            usage=self._usage(usage, prompt_chars, text or ""),
        )
