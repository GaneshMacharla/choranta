import asyncio
import logging
from typing import Any, Dict, List, Optional
from app.runtime.providers.base import AudioResult, LLMResult, ToolCallRequest, TranscriptResult
from app.runtime.providers.llm import LLMProvider
from app.runtime.providers.stt import STTProvider
from app.runtime.providers.tts import TTSProvider
from app.runtime.tools.executor import ToolExecutor
from app.runtime.tools.mock import BaseToolHandler
from app.runtime.testing.business_state import MockBusinessState

logger = logging.getLogger("choranta.testing.providers")


# ---------------------------------------------------------------------------
# 1. STATE-AWARE TESTING TOOL HANDLERS
# ---------------------------------------------------------------------------

class StateAwareCheckAvailabilityTool(BaseToolHandler):
    def __init__(self, state: MockBusinessState):
        self.state = state

    @property
    def tool_id(self) -> str:
        return "check_availability"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        doctor = arguments.get("doctor", "Dr. Rao")
        date_str = arguments.get("date", "2026-10-10")
        return self.state.check_availability(doctor=doctor, date_str=date_str)


class StateAwareBookAppointmentTool(BaseToolHandler):
    def __init__(self, state: MockBusinessState):
        self.state = state

    @property
    def tool_id(self) -> str:
        return "book_appointment"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        customer = arguments.get("customer_name", "Alice Smith")
        slot = arguments.get("slot", "2026-10-10 10:00 AM")
        phone = arguments.get("contact_phone", "+15550209999")
        doctor = arguments.get("doctor", "Dr. Rao")
        return self.state.book_appointment(customer_name=customer, slot=slot, contact_phone=phone, doctor=doctor)


class StateAwareCancelAppointmentTool(BaseToolHandler):
    def __init__(self, state: MockBusinessState):
        self.state = state

    @property
    def tool_id(self) -> str:
        return "cancel_appointment"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        conf_id = arguments.get("confirmation_id", "")
        reason = arguments.get("reason", "")
        return self.state.cancel_appointment(confirmation_id=conf_id, reason=reason)


class StateAwareCreateLeadTool(BaseToolHandler):
    def __init__(self, state: MockBusinessState):
        self.state = state

    @property
    def tool_id(self) -> str:
        return "create_lead"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        name = arguments.get("name", "Caller")
        phone = arguments.get("phone", "+15550209999")
        email = arguments.get("email", "")
        notes = arguments.get("notes", "")
        return self.state.create_lead(name=name, phone=phone, email=email, notes=notes)


def create_testing_tool_executor(state: MockBusinessState) -> ToolExecutor:
    """Creates a ToolExecutor bound to an isolated MockBusinessState instance."""
    executor = ToolExecutor()
    executor.register_handler(StateAwareCheckAvailabilityTool(state))
    executor.register_handler(StateAwareBookAppointmentTool(state))
    executor.register_handler(StateAwareCancelAppointmentTool(state))
    executor.register_handler(StateAwareCreateLeadTool(state))
    return executor


# ---------------------------------------------------------------------------
# 2. CONFIGURABLE TESTING STT ADAPTER
# ---------------------------------------------------------------------------

class TestingSTTAdapter(STTProvider):
    def __init__(self, name: str = "mock_stt"):
        self._name = name
        self.simulated_latency_seconds = 0.0
        self.simulate_timeout = False
        self.error_message: Optional[str] = None
        self.malformed_response = False
        self.rate_limited = False
        self.request_logs: List[Dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def environment(self) -> str:
        return "development/test"

    def initialize(self, config: Dict[str, Any]) -> None:
        self.configure(config)

    def configure(self, config: Dict[str, Any]) -> None:
        self.simulated_latency_seconds = float(config.get("latency_seconds", config.get("delay_seconds", 0.0)))
        self.simulate_timeout = bool(config.get("simulate_timeout", False))
        self.error_message = config.get("error_message")
        self.malformed_response = bool(config.get("malformed_response", False))
        self.rate_limited = bool(config.get("rate_limited", False))

    def process_audio(self, audio_data: Any) -> TranscriptResult:
        self.request_logs.append({"type": "stt_request", "audio_data": str(audio_data)[:100]})
        if self.simulate_timeout:
            raise TimeoutError("STT provider timeout simulated after 30.0s")
        if self.rate_limited:
            raise RuntimeError("STT provider HTTP 429 Too Many Requests (Rate limit exceeded)")
        if self.error_message:
            raise RuntimeError(f"STT provider failure: {self.error_message}")
        if self.malformed_response:
            # Malformed missing transcript or corrupt payload
            return TranscriptResult(text="", is_final=False, confidence=-1.0)

        if isinstance(audio_data, str):
            text = audio_data.strip()
        else:
            text = "I would like to check appointment availability."

        res = TranscriptResult(text=text, is_final=True, confidence=0.98)
        self.request_logs.append({"type": "stt_response", "transcript": text})
        return res

    def start_stream(self) -> None:
        pass

    def end_stream(self) -> TranscriptResult:
        return TranscriptResult(text="I would like to check appointment availability.", is_final=True, confidence=0.98)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 3. CONFIGURABLE TESTING LLM ADAPTER
# ---------------------------------------------------------------------------

class TestingLLMAdapter(LLMProvider):
    def __init__(self, name: str = "mock_llm"):
        self._name = name
        self.simulated_latency_seconds = 0.0
        self.simulate_timeout = False
        self.error_message: Optional[str] = None
        self.malformed_response = False
        self.rate_limited = False
        self.retry_failures_remaining = 0
        self.scripted_responses: List[LLMResult] = []
        self.request_logs: List[Dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def environment(self) -> str:
        return "development/test"

    def initialize(self, config: Dict[str, Any]) -> None:
        self.configure(config)

    def configure(self, config: Dict[str, Any]) -> None:
        self.simulated_latency_seconds = float(config.get("latency_seconds", config.get("delay_seconds", 0.0)))
        self.simulate_timeout = bool(config.get("simulate_timeout", False))
        self.error_message = config.get("error_message")
        self.malformed_response = bool(config.get("malformed_response", False))
        self.rate_limited = bool(config.get("rate_limited", False))
        self.retry_failures_remaining = int(config.get("retry_failures", 0))
        if "scripted_responses" in config and config["scripted_responses"]:
            self.scripted_responses = [
                LLMResult.model_validate(item) if isinstance(item, dict) else item
                for item in config["scripted_responses"]
            ]

    def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> LLMResult:
        self.request_logs.append({"type": "llm_request", "message_count": len(messages)})

        # Simulated transient error with retry recovery
        if self.retry_failures_remaining > 0:
            self.retry_failures_remaining -= 1
            self.request_logs.append({
                "type": "transient_provider_retry",
                "status": "recovered",
                "remaining": self.retry_failures_remaining,
            })
            # Transient error is recovered internally by provider client adapter retry

        if self.simulate_timeout:
            raise TimeoutError("LLM provider timeout simulated after 60.0s")
        if self.rate_limited:
            raise RuntimeError("LLM provider HTTP 429: Resource has been exhausted (quota limit)")
        if self.error_message:
            raise RuntimeError(f"LLM provider error: {self.error_message}")
        if self.malformed_response:
            return LLMResult(text=None, tool_calls=[], finish_reason="malformed", usage={})

        if self.scripted_responses:
            res = self.scripted_responses.pop(0)
            self.request_logs.append({"type": "llm_response_scripted", "text": res.text, "tools": len(res.tool_calls)})
            return res

        # Contextual logic based on conversation state
        last_msg = messages[-1] if messages else {"role": "user", "content": ""}
        role = last_msg.get("role", "")
        content = str(last_msg.get("content", "")).lower()

        # 1. Tool result returned
        if role == "tool":
            import json
            tool_content = last_msg.get("content", "{}")
            try:
                data = json.loads(tool_content)
            except Exception:
                data = {}

            if "error" in data:
                return LLMResult(
                    text="I apologize, but our appointment system encountered an error. May I take your phone number so our team can follow up?",
                    tool_calls=[],
                    finish_reason="stop",
                    usage={"input_tokens": 160, "output_tokens": 30},
                )

            if "available" in data:
                if data["available"]:
                    slots = data.get("slots", [])
                    slot_str = slots[0] if slots else "tomorrow at 10:00 AM"
                    doctor = data.get("doctor", "Dr. Rao")
                    return LLMResult(
                        text=f"I checked the schedule. {doctor} is available for an appointment on {slot_str}. Would you like me to book that for you?",
                        tool_calls=[],
                        finish_reason="stop",
                        usage={"input_tokens": 190, "output_tokens": 40},
                    )
                else:
                    doctor = data.get("doctor", "Dr. Smith")
                    return LLMResult(
                        text=f"I checked the schedule for {doctor}, but unfortunately there are no open slots available for that date. Would you like to check another day?",
                        tool_calls=[],
                        finish_reason="stop",
                        usage={"input_tokens": 170, "output_tokens": 35},
                    )

            if "confirmation_id" in data:
                conf = data["confirmation_id"]
                slot = data.get("slot", "")
                return LLMResult(
                    text=f"Your appointment has been confirmed for {slot}! Your confirmation number is {conf}. Is there anything else I can assist you with today?",
                    tool_calls=[],
                    finish_reason="stop",
                    usage={"input_tokens": 180, "output_tokens": 35},
                )

            if "lead_id" in data:
                return LLMResult(
                    text="Thank you. I have recorded your contact details and our team will get in touch with you shortly.",
                    tool_calls=[],
                    finish_reason="stop",
                    usage={"input_tokens": 150, "output_tokens": 25},
                )

        # 2. Available tools inspection
        tool_names = [t.get("name") or t.get("id") for t in (available_tools or [])]

        # Check if availability has already been checked in this session history
        has_checked_availability = any(
            m.get("tool_name") == "check_availability" or "is available" in str(m.get("content", "")).lower()
            for m in messages
        )

        # Check if booking was already confirmed in this session
        is_already_booked = any(
            "confirmation number" in str(m.get("content", "")).lower() or "confirmed for" in str(m.get("content", "")).lower()
            for m in messages
        )

        # 3. Caller asks to confirm / book
        # If availability was checked or caller explicitly says yes/book it, execute book_appointment
        wants_book = any(k in content for k in ["yes please", "go ahead", "book that", "book it", "confirm"]) or (
            has_checked_availability and not is_already_booked and ("yes" in content or "book" in content)
        )
        if wants_book and "book_appointment" in tool_names and not is_already_booked:
            # Extract customer name from history if mentioned
            customer_name = "Alice Smith"
            for m in messages:
                m_txt = str(m.get("content", ""))
                if "for alice" in m_txt.lower():
                    customer_name = "Alice Smith"
                elif "my name is" in m_txt.lower():
                    parts = m_txt.lower().split("my name is")
                    if len(parts) > 1:
                        customer_name = parts[1].split()[0].capitalize()

            return LLMResult(
                text=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_mock_bk_1",
                        tool_name="book_appointment",
                        arguments={"customer_name": customer_name, "slot": "2026-10-10 10:00 AM", "doctor": "Dr. Rao"},
                    )
                ],
                finish_reason="tool_calls",
                usage={"input_tokens": 160, "output_tokens": 35},
            )

        # 4. Caller asks about availability / appointment
        if ("availab" in content or "appointment" in content or "schedule" in content or "dr." in content or "book" in content) and "check_availability" in tool_names and not has_checked_availability:
            doctor = "Dr. Smith" if "dr. smith" in content or "smith" in content else "Dr. Rao"
            date_str = "2026-10-10"
            return LLMResult(
                text=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_mock_chk_1",
                        tool_name="check_availability",
                        arguments={"doctor": doctor, "date": date_str},
                    )
                ],
                finish_reason="tool_calls",
                usage={"input_tokens": 150, "output_tokens": 30},
            )

        # Direct book if check_availability is not available
        if ("book" in content or "appointment" in content) and "book_appointment" in tool_names and not is_already_booked:
            return LLMResult(
                text=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_mock_bk_1",
                        tool_name="book_appointment",
                        arguments={"customer_name": "Alice Smith", "slot": "2026-10-10 10:00 AM", "doctor": "Dr. Rao"},
                    )
                ],
                finish_reason="tool_calls",
                usage={"input_tokens": 160, "output_tokens": 35},
            )

        # 5. Caller asks out of domain / unsupported request
        if any(unsupported in content for unsupported in ["pizza", "crypto", "flight", "lottery"]):
            return LLMResult(
                text="I apologize, but as an assistant for this clinic, I can only assist with healthcare services and appointment scheduling. Would you like to check doctor availability?",
                tool_calls=[],
                finish_reason="stop",
                usage={"input_tokens": 130, "output_tokens": 32},
            )

        # 6. Ambiguous request
        if content in ["i need to see someone", "i want an appointment", "help me"]:
            return LLMResult(
                text="I would be happy to help you. Which doctor or department would you like to see, and on what date?",
                tool_calls=[],
                finish_reason="stop",
                usage={"input_tokens": 120, "output_tokens": 28},
            )

        # 7. Farewell / termination
        if any(w in content for w in ["goodbye", "bye", "that's all", "thank you bye"]):
            return LLMResult(
                text="Thank you for calling Acme Health Clinic. Have a wonderful day! Goodbye.",
                tool_calls=[],
                finish_reason="stop",
                usage={"input_tokens": 100, "output_tokens": 20},
            )

        # Default conversational prompt
        return LLMResult(
            text="Thank you for contacting us. How may I assist you with your appointment today?",
            tool_calls=[],
            finish_reason="stop",
            usage={"input_tokens": 110, "output_tokens": 25},
        )

    async def generate_async(self, *args: Any, **kwargs: Any) -> LLMResult:
        if self.simulated_latency_seconds:
            await asyncio.sleep(self.simulated_latency_seconds)
        return self.generate(*args, **kwargs)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 4. CONFIGURABLE TESTING TTS ADAPTER
# ---------------------------------------------------------------------------

class TestingTTSAdapter(TTSProvider):
    def __init__(self, name: str = "mock_tts"):
        self._name = name
        self.simulated_latency_seconds = 0.0
        self.simulate_timeout = False
        self.error_message: Optional[str] = None
        self.empty_audio = False
        self.request_logs: List[Dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def environment(self) -> str:
        return "development/test"

    def initialize(self, config: Dict[str, Any]) -> None:
        self.configure(config)

    def configure(self, config: Dict[str, Any]) -> None:
        self.simulated_latency_seconds = float(config.get("latency_seconds", config.get("chunk_delay_seconds", 0.0)))
        self.simulate_timeout = bool(config.get("simulate_timeout", False))
        self.error_message = config.get("error_message")
        self.empty_audio = bool(config.get("empty_audio", False))

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 0.0,
        emotion: Optional[str] = None,
        language: Optional[str] = None,
    ) -> AudioResult:
        self.request_logs.append({"type": "tts_request", "text_length": len(text)})
        if self.simulate_timeout:
            raise TimeoutError("TTS provider timeout simulated")
        if self.error_message:
            raise RuntimeError(f"TTS provider failure: {self.error_message}")
        if self.empty_audio:
            return AudioResult(audio_bytes=b"", format="pcm_s16le", duration_seconds=0.0)

        word_count = len(text.split()) if text else 1
        duration = max(0.5, round((word_count / 2.5) / max(speed, 0.5), 2))
        return AudioResult(audio_bytes=b"\x00\x02" * 320, format="pcm_s16le", duration_seconds=duration)

    def close(self) -> None:
        pass
