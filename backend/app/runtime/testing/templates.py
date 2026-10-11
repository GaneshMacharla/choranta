from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ScenarioTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    caller_goal: str
    turns: List[str]
    initial_mock_state: Dict[str, Any] = Field(default_factory=dict)
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    expected: Dict[str, Any] = Field(default_factory=dict)
    max_turns: int = 10
    timeout_seconds: int = 120


REUSABLE_SCENARIO_TEMPLATES: List[ScenarioTemplate] = [
    # 1. Successful customer inquiry
    ScenarioTemplate(
        template_id="tpl_01_customer_inquiry",
        name="1. Successful Customer Inquiry",
        description="Caller inquires about business hours and services. Agent answers politely without unnecessary tool calls.",
        caller_goal="Inquire about clinic opening hours and address",
        turns=[
            "Hello, could you tell me your operating hours and where you are located?",
            "That's all the information I needed, thank you. Goodbye!",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={},
        expected={
            "forbidden_tool_calls": ["book_appointment"],
            "final_response_contains": ["Goodbye"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # 2. Appointment booking
    ScenarioTemplate(
        template_id="tpl_02_appointment_booking",
        name="2. Appointment Booking",
        description="Patient checks availability and confirms booking. Tool executes and appointment is persisted in mock state.",
        caller_goal="Book an appointment with Dr. Rao for Alice Smith on 2026-10-10",
        turns=[
            "Hello, I would like to check appointment availability with Dr. Rao on 2026-10-10.",
            "Yes please, go ahead and book that slot for Alice Smith.",
            "Thank you so much! Goodbye.",
        ],
        initial_mock_state={
            "doctor_schedules": {
                "Dr. Rao": ["2026-10-10 09:00 AM", "2026-10-10 10:00 AM", "2026-10-10 02:30 PM"]
            },
            "appointments": [],
        },
        provider_config={},
        expected={
            "required_tool_calls": ["check_availability", "book_appointment"],
            "tool_status": {"book_appointment": "SUCCESS"},
            "expected_final_state": {
                "appointments_count": 1,
                "appointment_contains": {"customer_name": "Alice Smith", "doctor": "Dr. Rao"},
            },
            "final_response_contains": ["Goodbye"],
        },
        max_turns=6,
    ),

    # 3. Unavailable appointment slot
    ScenarioTemplate(
        template_id="tpl_03_unavailable_slot",
        name="3. Unavailable Appointment Slot",
        description="Patient requests an appointment with a doctor who has no open slots. Tool returns empty slots and agent handles gracefully without booking.",
        caller_goal="Attempt to book an appointment with Dr. Smith who has zero slots",
        turns=[
            "I want to book an appointment with Dr. Smith on 2026-10-10.",
            "I see, thank you for checking. Goodbye.",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Smith": []},
            "appointments": [],
        },
        provider_config={},
        expected={
            "required_tool_calls": ["check_availability"],
            "forbidden_tool_calls": ["book_appointment"],
            "expected_final_state": {"appointments_count": 0},
            "final_response_contains": ["Goodbye"],
        },
        max_turns=5,
    ),

    # 4. Tool execution failure
    ScenarioTemplate(
        template_id="tpl_04_tool_failure",
        name="4. Tool Execution Failure",
        description="Underlying business tool simulates an error. Agent cleanly discloses failure to caller without crashing.",
        caller_goal="Book an appointment when booking system encounters an error",
        turns=[
            "I want to book an appointment with Dr. Rao on 2026-10-10.",
            "Yes, please book it.",
            "Alright, I understand. Goodbye.",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
            "configured_failures": {"book_appointment": "Database connection refused"},
        },
        provider_config={},
        expected={
            "required_tool_calls": ["book_appointment"],
            "tool_status": {"book_appointment": "FAILED"},
            "expected_final_state": {"appointments_count": 0},
            "final_response_contains": ["Goodbye"],
        },
        max_turns=6,
    ),

    # 5. Caller interruption
    ScenarioTemplate(
        template_id="tpl_05_caller_interruption",
        name="5. Caller Interruption",
        description="Simulates caller interrupting the assistant mid-stream. Verifies barge-in handling and conversation continuity.",
        caller_goal="Interrupt assistant speech and redirect to a specific doctor",
        turns=[
            "I want to check availability...",
            "[interruption] Actually wait, I specifically need Dr. Rao on 2026-10-10.",
            "Yes, please confirm. Thank you, goodbye!",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={},
        expected={
            "required_tool_calls": ["check_availability"],
            "final_response_contains": ["Goodbye"],
        },
        max_turns=6,
    ),

    # 6. Ambiguous customer request
    ScenarioTemplate(
        template_id="tpl_06_ambiguous_request",
        name="6. Ambiguous Customer Request",
        description="Caller says 'I need to see someone'. Agent asks clarifying questions before calling tools.",
        caller_goal="Ask a vague question and provide details only when prompted",
        turns=[
            "I need to see someone.",
            "I want to see Dr. Rao on 2026-10-10.",
            "Thank you for the help. Goodbye!",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={},
        expected={
            "required_tool_calls": ["check_availability"],
            "final_response_contains": ["Goodbye"],
        },
        max_turns=6,
    ),

    # 7. Agent recovery after provider timeout
    ScenarioTemplate(
        template_id="tpl_07_provider_timeout_recovery",
        name="7. Agent Recovery After Provider Timeout",
        description="Simulates a transient provider timeout on LLM request followed by successful retry and completion.",
        caller_goal="Book appointment through transient provider instability",
        turns=[
            "Hello, I need an appointment with Dr. Rao.",
            "Thank you, goodbye!",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={
            "llm": {"retry_failures": 1},  # Fails 1st call, succeeds on retry
        },
        expected={
            "required_tool_calls": ["check_availability"],
            "final_response_contains": ["Goodbye"],
        },
        max_turns=5,
    ),

    # 8. Incorrect or unsupported customer request
    ScenarioTemplate(
        template_id="tpl_08_unsupported_request",
        name="8. Incorrect or Unsupported Customer Request",
        description="Caller asks for pizza delivery. Agent politely stays within healthcare scope and declines unsupported action.",
        caller_goal="Ask the clinic agent to order a pizza",
        turns=[
            "[unexpected] Can I order a large pepperoni pizza from you?",
            "Oh I see, this is a clinic. Thank you anyway, goodbye!",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={},
        expected={
            "forbidden_tool_calls": ["book_appointment", "create_lead"],
            "final_response_contains": ["Goodbye"],
        },
        max_turns=5,
    ),

    # 9. Multi-turn context retention
    ScenarioTemplate(
        template_id="tpl_09_context_retention",
        name="9. Multi-Turn Context Retention",
        description="Caller mentions patient name in turn 1 and requests appointment in turn 2. Verifies patient name is retained when booking.",
        caller_goal="State name in first turn and verify name retention in final booking",
        turns=[
            "Hello, my name is Alice Smith.",
            "I would like to check availability with Dr. Rao on 2026-10-10.",
            "Yes please, go ahead and book that.",
            "Thank you! Goodbye.",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={},
        expected={
            "required_tool_calls": ["check_availability", "book_appointment"],
            "expected_final_state": {
                "appointments_count": 1,
                "appointment_contains": {"customer_name": "Alice Smith"},
            },
            "final_response_contains": ["Goodbye"],
        },
        max_turns=8,
    ),

    # 10. Conversation termination
    ScenarioTemplate(
        template_id="tpl_10_conversation_termination",
        name="10. Conversation Termination",
        description="Caller politely ends conversation with farewell. Verifies clean session termination and COMPLETED lifecycle status.",
        caller_goal="Conclude conversation cleanly and verify session state is COMPLETED",
        turns=[
            "Hello, just checking if you are open today.",
            "That is all I needed. Thank you so much, goodbye!",
        ],
        initial_mock_state={
            "doctor_schedules": {"Dr. Rao": ["2026-10-10 10:00 AM"]},
            "appointments": [],
        },
        provider_config={},
        expected={
            "forbidden_tool_calls": ["book_appointment"],
            "final_response_contains": ["Goodbye"],
            "session_status": "COMPLETED",
        },
        max_turns=5,
    ),

    # =========================================================================
    # REAL ESTATE LEAD QUALIFICATION TEST SCENARIOS (12 SCENARIOS)
    # =========================================================================

    # RE 1. Existing lead with complete information
    ScenarioTemplate(
        template_id="tpl_re_01_existing_lead_complete",
        name="RE 1. Existing Lead with Complete Information",
        description="Rahul Sharma with 3 BHK enquiry in Whitefield. Agent greets, verifies enquiry, confirms budget (₹95 Lakhs), recommends Prestige Highline, and schedules site visit.",
        caller_goal="Confirm enquiry details and schedule a site visit for Prestige Highline",
        turns=[
            "Yes, this is Rahul. I was checking the Prestige Highline project in Whitefield.",
            "Yes, my budget is around ₹95 Lakhs and looking for a 3 BHK.",
            "Tomorrow around 10:30 AM would be great for a site visit.",
            "Thank you, see you tomorrow. Goodbye!",
        ],
        initial_mock_state={
            "lead_id": "lead_re_101",
            "caller_name": "Rahul Sharma",
            "enquiry_bhk": "3 BHK",
            "enquiry_location": "Whitefield",
        },
        provider_config={},
        expected={
            "required_tool_calls": ["search_properties"],
            "final_response_contains": ["Goodbye", "visit", "Thank"],
            "max_turns": 6,
        },
        max_turns=6,
    ),

    # RE 2. Missing caller name
    ScenarioTemplate(
        template_id="tpl_re_02_missing_caller_name",
        name="RE 2. Missing Caller Name",
        description="Caller name is not provided in metadata. Agent uses neutral greeting without speaking unresolved placeholder and politely discovers name.",
        caller_goal="Inquire about 2 BHK apartments in Panathur and provide name when asked",
        turns=[
            "Hi, I saw an ad for 2 BHK flats in Panathur. What are the options?",
            "My name is Priya Patel. Budget is around ₹75 Lakhs.",
            "Thank you, please send the brochure on WhatsApp. Goodbye!",
        ],
        initial_mock_state={
            "caller_name": "",
            "user_name": "",
        },
        provider_config={},
        expected={
            "forbidden_response_contains": ["{{user_name}}", "{{name}}", "None"],
            "required_tool_calls": ["search_properties"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 3. Caller asks for a 3 BHK within budget
    ScenarioTemplate(
        template_id="tpl_re_03_caller_asks_3bhk_within_budget",
        name="RE 3. Caller Asks for a 3 BHK within Budget",
        description="Caller specifically inquires for a 3 BHK under ₹1 Cr. Agent searches inventory and recommends Prestige Highline Residences (₹95 Lakhs).",
        caller_goal="Find a 3 BHK in Whitefield within ₹1 Cr budget limit",
        turns=[
            "Hello, I am looking for a 3 BHK in Whitefield, but my strict budget limit is 1 Crore. Do you have anything available?",
            "That sounds like a good fit. What amenities are included?",
            "Great, please have someone share the floor plan. Thanks!",
        ],
        initial_mock_state={
            "enquiry_bhk": "3 BHK",
            "enquiry_budget": "1 Crore",
        },
        provider_config={},
        expected={
            "required_tool_calls": ["search_properties"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 4. No matching property
    ScenarioTemplate(
        template_id="tpl_re_04_no_matching_property",
        name="RE 4. No Matching Property",
        description="Caller requests an unrealistic combination (e.g. 4 BHK villa for ₹40 Lakhs). Search returns no inventory; agent honestly discloses lack of matches without inventing prices.",
        caller_goal="Ask for a 4 BHK luxury villa in Whitefield for 40 Lakhs",
        turns=[
            "Do you have any 4 BHK luxury villas in Whitefield for around 40 Lakhs?",
            "Alright, I understand that is below current market rates. Keep me posted if anything comes up. Goodbye.",
        ],
        initial_mock_state={},
        provider_config={},
        expected={
            "required_tool_calls": ["search_properties"],
            "forbidden_tool_calls": ["book_site_visit"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 5. Caller changes location or budget
    ScenarioTemplate(
        template_id="tpl_re_05_caller_changes_location_or_budget",
        name="RE 5. Caller Changes Location or Budget",
        description="Caller initially asked about Whitefield but changes preference to Panathur with budget ₹75 Lakhs. Agent updates search and presents Sobha Dream Acres.",
        caller_goal="Pivot preference from Whitefield to Panathur for a ₹75 Lakhs budget",
        turns=[
            "Hi, I was looking at Whitefield earlier, but actually I want to look near Panathur for under 80 Lakhs.",
            "Yes, 2 BHK in Panathur works best for me.",
            "Sobha Dream Acres sounds good. Please schedule a callback for tomorrow.",
        ],
        initial_mock_state={
            "enquiry_location": "Whitefield",
        },
        provider_config={},
        expected={
            "required_tool_calls": ["search_properties"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 6. Caller speaks Telugu or switches language
    ScenarioTemplate(
        template_id="tpl_re_06_caller_speaks_telugu",
        name="RE 6. Caller Speaks Telugu or Switches Language",
        description="Caller switches to Telugu code-switching. Agent acknowledges language preference and continues conversation gracefully.",
        caller_goal="Inquire about property in Telugu code-switching",
        turns=[
            "Namaste, Whitefield lo unna 3 BHK flats gurinchi details cheppandi please.",
            "Avunu, na budget 1 crore lopala undi.",
            "Chala dhanyavaadalu, details message pettandi. Goodbye!",
        ],
        initial_mock_state={},
        provider_config={},
        expected={
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 7. Caller repeats information
    ScenarioTemplate(
        template_id="tpl_re_07_caller_repeats_information",
        name="RE 7. Caller Repeats Information",
        description="Caller repeats their budget and location. Agent acknowledges politely without re-asking questions already answered.",
        caller_goal="State budget firmly and verify agent avoids redundant interrogation",
        turns=[
            "Hello, I already mentioned my budget is ₹95 Lakhs for Whitefield.",
            "Yes, 3 BHK only. Please don't ask me my budget again.",
            "Okay, please send me the brochure. Bye.",
        ],
        initial_mock_state={
            "enquiry_location": "Whitefield",
            "enquiry_budget": "₹95 Lakhs",
        },
        provider_config={},
        expected={
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 8. Caller requests a site visit
    ScenarioTemplate(
        template_id="tpl_re_08_caller_requests_site_visit",
        name="RE 8. Caller Requests a Site Visit",
        description="Caller is interested and wants to book an in-person site visit. Agent invokes check_site_visit_slots and confirms slot.",
        caller_goal="Schedule a site visit for Saturday morning at Prestige Highline",
        turns=[
            "I like the Prestige Highline project. Can I visit the site this Saturday morning?",
            "Yes, 11:00 AM on Saturday works perfectly for my family.",
            "Thank you for confirming, looking forward to it. Bye!",
        ],
        initial_mock_state={
            "property_viewed": "Prestige Highline",
        },
        provider_config={},
        expected={
            "required_tool_calls": ["check_site_visit_slots"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 9. Calendar tool returns no availability
    ScenarioTemplate(
        template_id="tpl_re_09_calendar_no_availability",
        name="RE 9. Calendar Tool Returns No Availability",
        description="Preferred late date/time has no open slots. Agent discloses availability constraint honestly and offers next available alternative.",
        caller_goal="Request visit for late evening and accept next morning alternative",
        turns=[
            "I want to visit tonight at 9:00 PM.",
            "Okay, if tonight is not available, can we do tomorrow morning at 10:30 AM?",
            "Sounds good, thank you for checking!",
        ],
        initial_mock_state={},
        provider_config={},
        expected={
            "required_tool_calls": ["check_site_visit_slots"],
            "max_turns": 5,
        },
        max_turns=5,
    ),

    # RE 10. CRM update fails
    ScenarioTemplate(
        template_id="tpl_re_10_crm_update_fails",
        name="RE 10. CRM Update Fails",
        description="CRM service simulates an error. Agent cleanly communicates that details were noted and will be saved manually without crashing.",
        caller_goal="Confirm qualification details when CRM write encounters error",
        turns=[
            "Please update my new contact number as +919876500000 and budget 1.2 Crore.",
            "Alright, please make sure the sales team gets it. Thanks!",
        ],
        initial_mock_state={
            "lead_id": "lead_err_999",
        },
        provider_config={},
        expected={
            "max_turns": 4,
        },
        max_turns=4,
    ),

    # RE 11. Caller declines further contact
    ScenarioTemplate(
        template_id="tpl_re_11_caller_declines_contact",
        name="RE 11. Caller Declines Further Contact",
        description="Caller states they bought elsewhere and asks not to be called again. Agent politely apologizes, respects preference, marks DO_NOT_CALL.",
        caller_goal="Opt out of communications and request removal from contact list",
        turns=[
            "I am not interested anymore. I already bought an apartment and please don't call this number again.",
            "Thank you for understanding. Goodbye.",
        ],
        initial_mock_state={
            "lead_id": "lead_re_101",
        },
        provider_config={},
        expected={
            "forbidden_tool_calls": ["book_site_visit"],
            "final_response_contains": ["Goodbye", "apologize", "understand", "not call"],
            "max_turns": 4,
        },
        max_turns=4,
    ),

    # RE 12. Session reconnects during a conversation
    ScenarioTemplate(
        template_id="tpl_re_12_session_reconnects",
        name="RE 12. Session Reconnects During a Conversation",
        description="Network reconnects mid-call. Session rehydrates state from conversation history and continues seamlessly without restarting greeting.",
        caller_goal="Continue conversation after simulated network interruption",
        turns=[
            "Hello, my call got disconnected. We were discussing Prestige Highline 3 BHK.",
            "Yes, you were checking if covered car parking is included.",
            "That is great. Thanks for the quick update!",
        ],
        initial_mock_state={
            "property_viewed": "Prestige Highline",
        },
        provider_config={},
        expected={
            "forbidden_response_contains": ["Hello, am I speaking with"],
            "max_turns": 5,
        },
        max_turns=5,
    ),
]


def get_all_templates() -> List[Dict[str, Any]]:
    return [t.model_dump() for t in REUSABLE_SCENARIO_TEMPLATES]


def get_template_by_id(template_id: str) -> Optional[ScenarioTemplate]:
    for t in REUSABLE_SCENARIO_TEMPLATES:
        if t.template_id == template_id:
            return t
    return None
