import asyncio
from typing import Any, Dict, List, Optional
from app.runtime.providers.llm import LLMProvider
from app.runtime.providers.base import LLMResult, ToolCallRequest


class MockLLMProvider(LLMProvider):
    """
    Deterministic Mock LLM provider for testing runtime orchestration and tool calling loops.
    ENVIRONMENT: development/test
    """

    def __init__(self, name: str = "mock_llm"):
        self._name = name
        self._initialized = False
        self._scripted_responses: List[LLMResult] = []
        self._delay_seconds = 0.0
        self._error_message: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def environment(self) -> str:
        return "development/test"

    def initialize(self, config: Dict[str, Any]) -> None:
        self._initialized = True
        self.configure(config)

    def configure(self, config: Dict[str, Any]) -> None:
        self._delay_seconds = max(0.0, float(config.get("delay_seconds", self._delay_seconds)))
        self._error_message = config.get("error_message")
        scripted = config.get("scripted_responses")
        if scripted is not None:
            self._scripted_responses = [LLMResult.model_validate(item) for item in scripted]

    def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        if self._error_message:
            raise RuntimeError(self._error_message)
        if self._scripted_responses:
            return self._scripted_responses.pop(0)
        # Check last message
        last_message = messages[-1] if messages else {"role": "user", "content": ""}
        last_role = last_message.get("role", "")
        last_content = str(last_message.get("content", "")).lower()

        # Identify domain: Real Estate vs Clinic
        sys_lower = system_instruction.lower()
        tool_names = [t.get("name") or t.get("id") for t in (available_tools or []) if isinstance(t, dict)]
        is_real_estate = (
            any(t in ("search_properties", "update_lead_record", "get_lead_details", "check_site_visit_slots") for t in tool_names)
            or any(kw in sys_lower for kw in ("real estate", "property", "bhk", "realty", "lead qualification", "buyer"))
            or any(kw in last_content for kw in ("property", "bhk", "apartment", "flat", "villa", "budget", "whitefield", "site visit", "real estate"))
        )

        # Extract lead name and company name from system instruction if grounded
        import re
        lead_name = "Rahul Sharma"
        name_match = re.search(r"user_name:\s*'([^']+)'", system_instruction)
        if name_match and name_match.group(1).lower() not in ("none", "null", "(not provided yet)", "there"):
            lead_name = name_match.group(1)

        company_name = "Apex Realty Bangalore"
        comp_match = re.search(r"company_name:\s*'([^']+)'", system_instruction) or re.search(r"representing\s+([^,\.]+)", system_instruction)
        if comp_match and comp_match.group(1).strip().lower() not in ("none", "null", "default client"):
            company_name = comp_match.group(1).strip()

        # 1. Check if we just received a tool result
        if last_role == "tool":
            if is_real_estate:
                if "properties" in last_content or "search_properties" in last_content or "prestige" in last_content or "whitefield" in last_content:
                    return LLMResult(
                        text=f"We have found great matching properties for you, such as Prestige Highline in Whitefield (3 BHK for ₹95 Lakhs) and Brigade Cornerstone Utopia in Varthur (3 BHK for ₹1.15 Cr). Would you like to schedule an in-person site visit or have our property consultant follow up?",
                        tool_calls=[],
                        finish_reason="stop",
                        usage={"input_tokens": 190, "output_tokens": 58}
                    )
                if "record_updated" in last_content or "update_lead_record" in last_content:
                    return LLMResult(
                        text=f"Thank you, {lead_name}! I have recorded your preferences and marked your enquiry as qualified. Our senior property advisor from {company_name} will contact you shortly to coordinate next steps. Have a wonderful day!",
                        tool_calls=[],
                        finish_reason="stop",
                        usage={"input_tokens": 180, "output_tokens": 50}
                    )
                if "slots" in last_content or "site_visit" in last_content:
                    return LLMResult(
                        text=f"We have site visit slots available tomorrow at 10:30 AM and Saturday at 11:00 AM. Which of those works better for you, {lead_name}?",
                        tool_calls=[],
                        finish_reason="stop",
                        usage={"input_tokens": 170, "output_tokens": 42}
                    )
                return LLMResult(
                    text=f"I have retrieved your property details, {lead_name}. How else can I assist with your home search today?",
                    tool_calls=[],
                    finish_reason="stop",
                    usage={"input_tokens": 160, "output_tokens": 40}
                )

            return LLMResult(
                text="I have verified the schedule. Dr. Rao is available on 2026-10-10 at 10:00 AM. Would you like me to book that for you?",
                tool_calls=[],
                finish_reason="stop",
                usage={"input_tokens": 180, "output_tokens": 52}
            )

        # 2. Real Estate autonomous tool invocation
        if is_real_estate:
            has_search_tool = "search_properties" in tool_names
            has_update_tool = "update_lead_record" in tool_names

            # Caller asks to search or mentions property preferences
            if has_search_tool and any(kw in last_content for kw in ("search", "property", "properties", "bhk", "budget", "location", "recommend", "show me", "flat", "apartment", "whitefield", "options")):
                return LLMResult(
                    text=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_mock_prop_1",
                            tool_name="search_properties",
                            arguments={"location": "Whitefield", "bhk": 3, "budget_max": 12000000}
                        )
                    ],
                    finish_reason="tool_calls",
                    usage={"input_tokens": 150, "output_tokens": 35}
                )

            # Caller confirms interest, site visit, or gives qualification details
            if has_update_tool and any(kw in last_content for kw in ("yes", "book", "schedule", "site visit", "interested", "proceed", "visit", "confirm", "qualif")):
                return LLMResult(
                    text=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_mock_upd_1",
                            tool_name="update_lead_record",
                            arguments={
                                "lead_id": "lead_re_101",
                                "buyer_budget": "₹1.1 Cr",
                                "buyer_location": "Whitefield",
                                "buyer_bhk": "3 BHK",
                                "lead_qualification_status": "QUALIFIED",
                                "call_disposition": "INTERESTED",
                                "next_action": "site_visit"
                            }
                        )
                    ],
                    finish_reason="tool_calls",
                    usage={"input_tokens": 160, "output_tokens": 45}
                )

            # Conversational greetings or questions
            if any(kw in last_content for kw in ("hello", "hi", "who is this", "calling", "speak", "hey")):
                return LLMResult(
                    text=f"Hello, am I speaking with {lead_name}? I'm calling from {company_name} regarding your property enquiry.",
                    tool_calls=[],
                    finish_reason="stop",
                    usage={"input_tokens": 120, "output_tokens": 35}
                )

            if any(kw in last_content for kw in ("bye", "thank you", "thanks", "done", "no", "that's all")):
                return LLMResult(
                    text=f"Thank you for your time, {lead_name}. Have a wonderful day!",
                    tool_calls=[],
                    finish_reason="stop",
                    usage={"input_tokens": 100, "output_tokens": 20}
                )

            return LLMResult(
                text=f"Understood, {lead_name}! Could you share your preferred location, budget range, and whether you are looking for a 2 BHK or 3 BHK?",
                tool_calls=[],
                finish_reason="stop",
                usage={"input_tokens": 130, "output_tokens": 38}
            )

        # 3. Medical Clinic / Appointment Booking Fallback
        has_availability_tool = any(
            (t.get("name") == "check_availability" or t.get("id") == "check_availability")
            for t in (available_tools or [])
        )

        if ("appointment" in last_content or "available" in last_content or "book" in last_content) and has_availability_tool:
            return LLMResult(
                text=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_mock_chk_1",
                        tool_name="check_availability",
                        arguments={"doctor": "Dr. Rao", "date": "2026-10-10"}
                    )
                ],
                finish_reason="tool_calls",
                usage={"input_tokens": 140, "output_tokens": 30}
            )

        # Standard conversational response
        return LLMResult(
            text="Sure. What date and service would you prefer?",
            tool_calls=[],
            finish_reason="stop",
            usage={"input_tokens": 110, "output_tokens": 35}
        )

    async def generate_async(self, *args: Any, **kwargs: Any) -> LLMResult:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return self.generate(*args, **kwargs)

    def close(self) -> None:
        self._initialized = False
