import uuid
import json
import logging
import time
from typing import Any, Dict, Iterator, List, Optional, Union
from google import genai
from google.genai import types
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.base import LLMResult, ToolCallRequest
from app.runtime.providers.llm import LLMProvider

logger = logging.getLogger("choranta.runtime.providers.gemini.llm")

DEFAULT_GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.7-flash",
)

# Models that recently returned a rate-limit/quota/unavailable error are skipped until this
# monotonic time, so every turn doesn't pay for a failed request before falling back.
MODEL_COOLDOWN_SECONDS = 600.0
_model_cooldown_until: Dict[str, float] = {}


def _models_available(models: List[str]) -> List[str]:
    now = time.monotonic()
    available = [m for m in models if _model_cooldown_until.get(m, 0.0) <= now]
    return available or models[-1:]


class GeminiLLMProvider(LLMProvider):
    """
    Google Gemini LLM provider adapter using modern Google GenAI SDK (google-genai).
    Translates Choranta conversation history and tools into Gemini format,
    executing conversational turns and returning structured tool calls or text responses.
    """

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.default_model = default_model or getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self._client: Optional[genai.Client] = None
        self._configured = False

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def environment(self) -> str:
        return "production"

    def initialize(self, config: Dict[str, Any]) -> None:
        key = self._api_key or config.get("api_key")
        if not key:
            raise ProviderUnavailable("LLM", "Gemini: Missing GEMINI_API_KEY")
        self._api_key = key
        try:
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=30000,
                    retry_options=types.HttpRetryOptions(attempts=1)
                )
            )
            self._configured = True
        except Exception as e:
            logger.error(f"Failed to initialize Gemini Client: {type(e).__name__}")
            raise ProviderUnavailable("LLM", f"Gemini configuration failed: {str(e)}")

    def close(self) -> None:
        self._configured = False
        self._client = None

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[types.Content]:
        """Converts Choranta messages into google.genai types.Content objects."""
        contents: List[types.Content] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            if role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=str(content))]
                    )
                )
            elif role == "assistant":
                parts: List[types.Part] = []
                if content:
                    parts.append(types.Part.from_text(text=str(content)))
                for tc in tool_calls:
                    tc_name = tc.get("tool_name") or tc.get("name")
                    tc_args = tc.get("arguments") or tc.get("args") or {}
                    ts_val = tc.get("thought_signature")
                    ts_bytes = bytes.fromhex(ts_val) if isinstance(ts_val, str) else ts_val
                    if ts_bytes:
                        parts.append(types.Part(
                            function_call=types.FunctionCall(name=tc_name, args=tc_args),
                            thought_signature=ts_bytes
                        ))
                    else:
                        parts.append(types.Part.from_function_call(name=tc_name, args=tc_args))
                if not parts:
                    parts.append(types.Part.from_text(text=""))
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                tc_name = msg.get("name", "function")
                try:
                    resp_dict = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    resp_dict = {"response": str(content)}

                if not isinstance(resp_dict, dict):
                    resp_dict = {"result": resp_dict}

                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(name=tc_name, response=resp_dict)]
                    )
                )
        return contents

    def _build_tools_config(self, available_tools: Optional[List[Dict[str, Any]]]) -> Optional[List[types.Tool]]:
        """Constructs tool declarations for Gemini function calling."""
        if not available_tools:
            return None

        declarations: List[types.FunctionDeclaration] = []
        for tool in available_tools:
            tool_name = tool.get("name") or tool.get("id")
            if not tool_name:
                continue

            if tool_name == "check_availability":
                param_schema = types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "date": types.Schema(type=types.Type.STRING, description="Date in YYYY-MM-DD format"),
                        "service": types.Schema(type=types.Type.STRING, description="Name of the requested service")
                    },
                    required=["date"]
                )
            elif tool_name == "book_appointment":
                param_schema = types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "customer_name": types.Schema(type=types.Type.STRING, description="Customer full name"),
                        "date": types.Schema(type=types.Type.STRING, description="Appointment date YYYY-MM-DD"),
                        "time_slot": types.Schema(type=types.Type.STRING, description="Time slot e.g. 10:00 AM"),
                        "service": types.Schema(type=types.Type.STRING, description="Requested service")
                    },
                    required=["customer_name", "date", "time_slot"]
                )
            elif tool_name == "create_lead":
                param_schema = types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "name": types.Schema(type=types.Type.STRING, description="Lead full name"),
                        "phone": types.Schema(type=types.Type.STRING, description="Lead contact phone number"),
                        "interest": types.Schema(type=types.Type.STRING, description="Product or service interest")
                    },
                    required=["name", "phone"]
                )
            else:
                param_schema = types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(type=types.Type.STRING, description="Query or parameter for tool")
                    }
                )

            declarations.append(types.FunctionDeclaration(
                name=tool_name,
                description=tool.get("description", f"Execute action for {tool_name}"),
                parameters=param_schema
            ))

        return [types.Tool(function_declarations=declarations)] if declarations else None

    def _parse_response(self, response: Any) -> LLMResult:
        """Parses a GenerateContentResponse into Choranta LLMResult."""
        text_parts: List[str] = []
        tool_calls: List[ToolCallRequest] = []

        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        args = dict(fc.args) if hasattr(fc, "args") and fc.args else {}
                        ts = getattr(part, "thought_signature", None)
                        ts_str = ts.hex() if isinstance(ts, bytes) else (str(ts) if ts else None)
                        call_id = f"call_{uuid.uuid4().hex[:8]}"
                        tool_calls.append(ToolCallRequest(
                            id=call_id,
                            tool_name=fc.name,
                            arguments=args,
                            thought_signature=ts_str
                        ))

        combined_text = "".join(text_parts).strip() if text_parts else None
        finish_reason = "tool_calls" if tool_calls else "stop"

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        return LLMResult(
            text=combined_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens}
        )

    def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        if not self._configured or not self._client:
            self.initialize({})

        model_name = model or self.default_model
        gemini_tools = self._build_tools_config(available_tools)
        contents = self._convert_messages(messages)

        models_to_try = [model_name]
        if model_name == self.default_model:
            models_to_try.extend(GEMINI_FALLBACK_MODELS)
        models_to_try = _models_available(models_to_try)

        last_error: Optional[Exception] = None
        for candidate_model in models_to_try:
            try:
                candidate_config = types.GenerateContentConfig(
                    temperature=temperature,
                    system_instruction=system_instruction,
                    tools=gemini_tools,
                )
                if "3.8" in candidate_model:
                    candidate_config.thinking_config = types.ThinkingConfig(thinking_budget=0)

                response = self._client.models.generate_content(
                    model=candidate_model,
                    contents=contents,
                    config=candidate_config
                )
                return self._parse_response(response)
            except Exception as e:
                last_error = e
                status_code = getattr(e, "code", getattr(e, "status_code", None))
                err_text = str(e).lower()
                is_quota_or_rate_limit = (
                    status_code in (400, 403, 429, 500, 502, 503, 504)
                    or "429" in err_text
                    or "503" in err_text
                    or "504" in err_text
                    or "resource_exhausted" in err_text
                    or "quota" in err_text
                    or "deadline_exceeded" in err_text
                    or "unavailable" in err_text
                )
                if status_code in (429, 503) or "resource_exhausted" in err_text or "quota" in err_text:
                    _model_cooldown_until[candidate_model] = time.monotonic() + MODEL_COOLDOWN_SECONDS
                if candidate_model != models_to_try[-1] and (status_code in (429, 500, 502, 503, 504) or is_quota_or_rate_limit):
                    logger.warning(
                        f"Gemini model {candidate_model} unavailable ({status_code}); "
                        f"trying fallback model."
                    )
                    continue
                if settings.GEMINI_FALLBACK_TO_MOCK:
                    logger.warning(f"Gemini error ({type(e).__name__}: {str(e)}); using deterministic mock LLM fallback.")
                    from app.runtime.providers.mock.llm import MockLLMProvider
                    return MockLLMProvider("gemini_quota_fallback").generate(
                        system_instruction=system_instruction,
                        messages=messages,
                        available_tools=available_tools,
                        temperature=temperature,
                        model=model
                    )
                logger.error(f"Gemini LLM generation error: {type(e).__name__}: {str(e)}")
                raise

        raise last_error or RuntimeError("Gemini generation failed without an exception.")

    def generate_stream(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> Iterator[Union[str, LLMResult]]:
        """
        Streams Gemini output: yields text deltas as they arrive, then the aggregated LLMResult.
        Falls back to the next model only if a model fails before producing any output.
        """
        if not self._configured or not self._client:
            self.initialize({})

        model_name = model or self.default_model
        gemini_tools = self._build_tools_config(available_tools)
        contents = self._convert_messages(messages)

        models_to_try = [model_name]
        if model_name == self.default_model:
            models_to_try.extend(GEMINI_FALLBACK_MODELS)
        models_to_try = _models_available(models_to_try)

        last_error: Optional[Exception] = None
        for candidate_model in models_to_try:
            text_parts: List[str] = []
            tool_calls: List[ToolCallRequest] = []
            usage = {"input_tokens": 0, "output_tokens": 0}
            emitted = False
            try:
                candidate_config = types.GenerateContentConfig(
                    temperature=temperature,
                    system_instruction=system_instruction,
                    tools=gemini_tools,
                )
                if "3.8" in candidate_model:
                    candidate_config.thinking_config = types.ThinkingConfig(thinking_budget=0)

                for chunk in self._client.models.generate_content_stream(
                    model=candidate_model,
                    contents=contents,
                    config=candidate_config
                ):
                    parsed = self._parse_response(chunk)
                    # Raw chunk text: _parse_response strips whitespace, which would glue words across chunks
                    delta = "".join(
                        part.text
                        for cand in (getattr(chunk, "candidates", None) or [])[:1]
                        if cand.content and cand.content.parts
                        for part in cand.content.parts
                        if getattr(part, "text", None) and not getattr(part, "thought", False)
                    )
                    if delta:
                        emitted = True
                        text_parts.append(delta)
                        yield delta
                    if parsed.tool_calls:
                        emitted = True
                        tool_calls.extend(parsed.tool_calls)
                    if parsed.usage.get("input_tokens") or parsed.usage.get("output_tokens"):
                        usage = parsed.usage

                yield LLMResult(
                    text="".join(text_parts).strip() or None,
                    tool_calls=tool_calls,
                    finish_reason="tool_calls" if tool_calls else "stop",
                    usage=usage
                )
                return
            except Exception as e:
                last_error = e
                if emitted:
                    logger.error(f"Gemini stream interrupted mid-response: {type(e).__name__}: {str(e)}")
                    raise
                status_code = getattr(e, "code", getattr(e, "status_code", None))
                err_text = str(e).lower()
                if status_code in (429, 503) or "resource_exhausted" in err_text or "quota" in err_text:
                    _model_cooldown_until[candidate_model] = time.monotonic() + MODEL_COOLDOWN_SECONDS
                retryable = (
                    status_code in (429, 500, 502, 503, 504)
                    or any(k in err_text for k in ("429", "503", "504", "resource_exhausted", "quota", "deadline_exceeded", "unavailable"))
                )
                if candidate_model != models_to_try[-1] and retryable:
                    logger.warning(f"Gemini model {candidate_model} unavailable ({status_code}); trying fallback model.")
                    continue
                if settings.GEMINI_FALLBACK_TO_MOCK:
                    logger.warning(f"Gemini stream error ({type(e).__name__}: {str(e)}); using deterministic mock LLM fallback.")
                    from app.runtime.providers.mock.llm import MockLLMProvider
                    yield from MockLLMProvider("gemini_quota_fallback").generate_stream(
                        system_instruction=system_instruction,
                        messages=messages,
                        available_tools=available_tools,
                        temperature=temperature,
                        model=model
                    )
                    return
                logger.error(f"Gemini stream generation error: {type(e).__name__}: {str(e)}")
                raise

        raise last_error or RuntimeError("Gemini stream generation failed without an exception.")

    async def generate_async(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        if not self._configured or not self._client:
            self.initialize({})

        model_name = model or self.default_model
        gemini_tools = self._build_tools_config(available_tools)
        contents = self._convert_messages(messages)

        models_to_try = [model_name]
        if model_name == self.default_model:
            models_to_try.extend(GEMINI_FALLBACK_MODELS)
        models_to_try = _models_available(models_to_try)

        last_error: Optional[Exception] = None
        for candidate_model in models_to_try:
            try:
                candidate_config = types.GenerateContentConfig(
                    temperature=temperature,
                    system_instruction=system_instruction,
                    tools=gemini_tools
                )
                if "3.8" in candidate_model:
                    candidate_config.thinking_config = types.ThinkingConfig(thinking_budget=0)

                response = await self._client.aio.models.generate_content(
                    model=candidate_model,
                    contents=contents,
                    config=candidate_config
                )
                return self._parse_response(response)
            except Exception as e:
                last_error = e
                status_code = getattr(e, "code", getattr(e, "status_code", None))
                err_text = str(e).lower()
                is_quota_or_rate_limit = (
                    status_code in (400, 403, 429, 500, 502, 503, 504)
                    or "429" in err_text
                    or "503" in err_text
                    or "504" in err_text
                    or "resource_exhausted" in err_text
                    or "quota" in err_text
                    or "deadline_exceeded" in err_text
                    or "unavailable" in err_text
                )
                if status_code in (429, 503) or "resource_exhausted" in err_text or "quota" in err_text:
                    _model_cooldown_until[candidate_model] = time.monotonic() + MODEL_COOLDOWN_SECONDS
                if candidate_model != models_to_try[-1] and (status_code in (429, 500, 502, 503, 504) or is_quota_or_rate_limit):
                    logger.warning(
                        f"Gemini model {candidate_model} unavailable ({status_code}); "
                        f"trying fallback model."
                    )
                    continue
                if settings.GEMINI_FALLBACK_TO_MOCK:
                    logger.warning(f"Gemini async error ({type(e).__name__}: {str(e)}); using deterministic mock LLM fallback.")
                    from app.runtime.providers.mock.llm import MockLLMProvider
                    return MockLLMProvider("gemini_quota_fallback").generate(
                        system_instruction=system_instruction,
                        messages=messages,
                        available_tools=available_tools,
                        temperature=temperature,
                        model=model
                    )
                logger.error(f"Gemini async generation error: {type(e).__name__}: {str(e)}")
                raise

        raise last_error or RuntimeError("Gemini async generation failed without an exception.")
