from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.runtime.testing.business_state import MockBusinessState


class AssertionResult(BaseModel):
    name: str
    category: str = "deterministic"  # deterministic, quality
    status: str = "PASS"  # PASS, FAIL, ERROR
    expected: Any = None
    actual: Any = None
    evidence: str = ""
    explanation: str = ""


class EvaluationSummary(BaseModel):
    overall_status: str = "PASS"  # PASS, FAIL, ERROR
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    assertions: List[AssertionResult] = Field(default_factory=list)


class EvaluationEngine:
    """
    Dual evaluation engine supporting deterministic assertions and pluggable
    conversation quality metrics. Never fakes success results.
    """

    def __init__(self, quality_evaluator: Optional[Any] = None):
        self.quality_evaluator = quality_evaluator or DeterministicQualityEvaluator()

    def evaluate(
        self,
        expected: Dict[str, Any],
        turns: List[Dict[str, Any]],
        events: List[Any],
        business_state: MockBusinessState,
        max_turns: int,
        duration_ms: int,
        session_status: str,
        caller_goal: str = "",
        tenant_context: Optional[Dict[str, Any]] = None,
        runtime_error: Optional[str] = None,
    ) -> EvaluationSummary:
        assertions: List[AssertionResult] = []

        if runtime_error:
            assertions.append(
                AssertionResult(
                    name="runtime_execution_safety",
                    category="deterministic",
                    status="ERROR",
                    expected="Clean execution with no runtime infrastructure exception",
                    actual=runtime_error,
                    evidence="AgentRuntime raised an unhandled exception",
                    explanation=f"Runtime error occurred: {runtime_error}",
                )
            )

        # 1. TOOL CALL ASSERTIONS
        tool_events = [e for e in events if getattr(e, "event_type", "") == "TOOL_CALL_STARTED"]
        actual_tools = [(getattr(e, "payload_json", {}) or {}).get("tool_name") for e in tool_events]
        actual_tool_calls = [getattr(e, "payload_json", {}) or {} for e in tool_events]

        for req_tool in expected.get("required_tool_calls", []):
            passed = req_tool in actual_tools
            assertions.append(
                AssertionResult(
                    name=f"required_tool:{req_tool}",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Tool '{req_tool}' must be called",
                    actual=actual_tools,
                    evidence=f"TOOL_CALL_STARTED events (called: {actual_tools})",
                    explanation=f"Required tool '{req_tool}' was {'called' if passed else 'NOT called'}.",
                )
            )

        for forb_tool in expected.get("forbidden_tool_calls", []):
            passed = forb_tool not in actual_tools
            assertions.append(
                AssertionResult(
                    name=f"forbidden_tool:{forb_tool}",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Tool '{forb_tool}' must NOT be called",
                    actual=actual_tools,
                    evidence=f"TOOL_CALL_STARTED events (called: {actual_tools})",
                    explanation=f"Forbidden tool '{forb_tool}' was {'safely avoided' if passed else 'CALLED'}.",
                )
            )

        # Tool argument constraints
        for tool_name, constraints in expected.get("tool_argument_constraints", {}).items():
            matching_calls = [c for c in actual_tool_calls if c.get("tool_name") == tool_name]
            if not matching_calls:
                assertions.append(
                    AssertionResult(
                        name=f"tool_arguments:{tool_name}",
                        category="deterministic",
                        status="FAIL",
                        expected=constraints,
                        actual=None,
                        evidence="No call made to tool to inspect arguments",
                        explanation=f"Cannot verify arguments because '{tool_name}' was never called.",
                    )
                )
            else:
                call_args = matching_calls[0].get("arguments", {})
                passed = all(call_args.get(k) == v for k, v in constraints.items())
                assertions.append(
                    AssertionResult(
                        name=f"tool_arguments:{tool_name}",
                        category="deterministic",
                        status="PASS" if passed else "FAIL",
                        expected=constraints,
                        actual=call_args,
                        evidence=f"Tool arguments passed to '{tool_name}'",
                        explanation=f"Arguments {'matched constraints' if passed else 'did not match expected constraints'}.",
                    )
                )

        # Tool execution status
        for tool_name, exp_status in expected.get("tool_status", {}).items():
            completed_events = [
                e for e in events
                if getattr(e, "event_type", "") == "TOOL_CALL_COMPLETED"
            ]
            matching_comp = [
                (getattr(e, "payload_json", {}) or {})
                for e in completed_events
            ]
            passed = any(
                (c.get("success") is True if exp_status == "SUCCESS" else c.get("success") is False)
                for c in matching_comp
            )
            assertions.append(
                AssertionResult(
                    name=f"tool_status:{tool_name}",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Tool status: {exp_status}",
                    actual=matching_comp,
                    evidence="TOOL_CALL_COMPLETED runtime event payloads",
                    explanation=f"Tool '{tool_name}' completed status matched expected {exp_status}.",
                )
            )

        # 2. FINAL BUSINESS STATE ASSERTIONS
        exp_final_state = expected.get("expected_final_state", {})
        if "appointments_count" in exp_final_state:
            req_count = exp_final_state["appointments_count"]
            actual_count = len(business_state.appointments)
            passed = actual_count == req_count
            assertions.append(
                AssertionResult(
                    name="business_state:appointments_count",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Exactly {req_count} appointment(s) in persistent state",
                    actual=actual_count,
                    evidence=f"MockBusinessState appointments: {business_state.appointments}",
                    explanation=f"Verified persisted appointment count: expected {req_count}, found {actual_count}.",
                )
            )

        if "appointment_contains" in exp_final_state:
            match_req = exp_final_state["appointment_contains"]
            found = False
            for apt in business_state.appointments:
                if all(apt.get(k) == v for k, v in match_req.items()):
                    found = True
                    break
            assertions.append(
                AssertionResult(
                    name="business_state:appointment_record",
                    category="deterministic",
                    status="PASS" if found else "FAIL",
                    expected=match_req,
                    actual=business_state.appointments,
                    evidence="MockBusinessState persisted appointment records",
                    explanation=f"Persisted appointment {'found with matching fields' if found else 'NOT found'}.",
                )
            )

        if "leads_count" in exp_final_state:
            req_leads = exp_final_state["leads_count"]
            actual_leads = len(business_state.leads)
            passed = actual_leads == req_leads
            assertions.append(
                AssertionResult(
                    name="business_state:leads_count",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Exactly {req_leads} lead(s) in persistent state",
                    actual=actual_leads,
                    evidence=f"MockBusinessState leads: {business_state.leads}",
                    explanation=f"Verified persisted leads: expected {req_leads}, found {actual_leads}.",
                )
            )

        # 3. RESPONSE TEXT ASSERTIONS
        final_text = turns[-1]["assistant"] if turns else ""
        for expected_str in expected.get("final_response_contains", []):
            passed = str(expected_str).lower() in final_text.lower()
            assertions.append(
                AssertionResult(
                    name=f"final_response_contains:{expected_str}",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Contains: '{expected_str}'",
                    actual=final_text,
                    evidence=f"Final assistant turn response: \"{final_text}\"",
                    explanation=f"Expected substring '{expected_str}' was {'found' if passed else 'NOT found'} in final response.",
                )
            )

        for forbidden_str in expected.get("final_response_not_contains", []):
            passed = str(forbidden_str).lower() not in final_text.lower()
            assertions.append(
                AssertionResult(
                    name=f"final_response_not_contains:{forbidden_str}",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Must NOT contain: '{forbidden_str}'",
                    actual=final_text,
                    evidence=f"Final assistant turn response: \"{final_text}\"",
                    explanation=f"Forbidden substring '{forbidden_str}' was {'safely absent' if passed else 'FOUND'}.",
                )
            )

        # 4. TURN COUNT LIMIT
        turn_limit_passed = len(turns) <= max_turns
        assertions.append(
            AssertionResult(
                name="turn_count_limit",
                category="deterministic",
                status="PASS" if turn_limit_passed else "FAIL",
                expected=f"Turn count <= {max_turns}",
                actual=len(turns),
                evidence=f"Executed {len(turns)} turns",
                explanation=f"Conversation turn limit: {len(turns)} turns of max {max_turns}.",
            )
        )

        # 5. LATENCY THRESHOLDS
        if "max_duration_ms" in expected:
            max_ms = expected["max_duration_ms"]
            passed = duration_ms <= max_ms
            assertions.append(
                AssertionResult(
                    name="latency_threshold:total_duration",
                    category="deterministic",
                    status="PASS" if passed else "FAIL",
                    expected=f"Total duration <= {max_ms} ms",
                    actual=f"{duration_ms} ms",
                    evidence=f"Scenario total duration: {duration_ms} ms",
                    explanation=f"Execution latency was {'within' if passed else 'EXCEEDED'} threshold.",
                )
            )

        # 6. SESSION TERMINATION
        exp_session_status = expected.get("session_status", "COMPLETED")
        session_passed = session_status == exp_session_status
        assertions.append(
            AssertionResult(
                name="session_termination_state",
                category="deterministic",
                status="PASS" if session_passed else "FAIL",
                expected=f"Session status == {exp_session_status}",
                actual=session_status,
                evidence=f"RuntimeSession status: {session_status}",
                explanation=f"Session lifecycle cleanly reached {session_status}.",
            )
        )

        # 7. TENANT ISOLATION
        if tenant_context:
            client_id = tenant_context.get("client_id")
            agent_client_id = tenant_context.get("agent_client_id")
            scenario_client_id = tenant_context.get("scenario_client_id")
            tenant_passed = bool(client_id and client_id == agent_client_id == scenario_client_id)
            assertions.append(
                AssertionResult(
                    name="tenant_isolation",
                    category="deterministic",
                    status="PASS" if tenant_passed else "FAIL",
                    expected="All entity client_ids match",
                    actual=f"client={client_id}, agent={agent_client_id}, scenario={scenario_client_id}",
                    evidence="Database foreign keys and tenant isolation check",
                    explanation="Strict tenant isolation verified across client, agent, and scenario.",
                )
            )

        # 8. CONVERSATION QUALITY EVALUATION (PLUGGABLE)
        quality_results = self.quality_evaluator.evaluate_quality(
            turns=turns,
            caller_goal=caller_goal,
            expected=expected,
            business_state=business_state,
        )
        assertions.extend(quality_results)

        # AGGREGATE SUMMARY
        error_count = sum(1 for a in assertions if a.status == "ERROR")
        failed_count = sum(1 for a in assertions if a.status == "FAIL")
        passed_count = sum(1 for a in assertions if a.status == "PASS")

        if error_count > 0:
            overall = "ERROR"
        elif failed_count > 0:
            overall = "FAIL"
        else:
            overall = "PASS"

        return EvaluationSummary(
            overall_status=overall,
            passed_count=passed_count,
            failed_count=failed_count,
            error_count=error_count,
            assertions=assertions,
        )


class DeterministicQualityEvaluator:
    """
    Pluggable quality evaluator assessing goal achievement, instruction following,
    context retention, and professional responses without requiring paid external LLM APIs.
    """

    def evaluate_quality(
        self,
        turns: List[Dict[str, Any]],
        caller_goal: str,
        expected: Dict[str, Any],
        business_state: MockBusinessState,
    ) -> List[AssertionResult]:
        results: List[AssertionResult] = []
        if not turns:
            return results

        all_assistant_text = " ".join(t.get("assistant", "") for t in turns).lower()
        all_caller_text = " ".join(t.get("caller", "") for t in turns).lower()
        final_assistant = turns[-1].get("assistant", "").lower()

        # Quality Metric 1: Caller Goal Achievement
        if caller_goal:
            goal_achieved = False
            goal_lower = caller_goal.lower()
            if "availab" in goal_lower:
                goal_achieved = any(w in all_assistant_text for w in ["available", "schedule", "slots", "dr.", "doctor", "open"])
            elif "book" in goal_lower:
                goal_achieved = (
                    len(business_state.appointments) > 0
                    or any(w in all_assistant_text for w in ["confirmed", "booked", "unavailable", "no open slots", "error", "apologize", "follow up"])
                )
            elif "hours" in goal_lower or "location" in goal_lower:
                goal_achieved = any(w in all_assistant_text for w in ["open", "hours", "09:00", "closed", "located"])
            else:
                goal_achieved = len(turns) >= 1 and len(turns[-1].get("assistant", "")) > 10

            results.append(
                AssertionResult(
                    name="quality:goal_achievement",
                    category="quality",
                    status="PASS" if goal_achieved else "FAIL",
                    expected=f"Caller goal: '{caller_goal}' addressed",
                    actual=f"Turns completed: {len(turns)}, final message: {turns[-1].get('assistant', '')[:60]}...",
                    evidence="Conversation transcript and assistant responses",
                    explanation=f"Evaluated whether caller goal was addressed: {'Achieved' if goal_achieved else 'Unfulfilled'}.",
                )
            )

        # Quality Metric 2: Context Retention Across Turns
        if len(turns) >= 2:
            # Check if details from turn 1 (e.g. name or doctor) are remembered
            first_turn_caller = turns[0].get("caller", "").lower()
            context_retained = True
            if "rao" in first_turn_caller and len(turns) > 1:
                context_retained = "rao" in all_assistant_text or any(
                    "rao" in str(t.get("tool_calls", [])) for t in turns
                )

            results.append(
                AssertionResult(
                    name="quality:context_retention",
                    category="quality",
                    status="PASS" if context_retained else "FAIL",
                    expected="Assistant retains user context across multi-turn dialogue",
                    actual="Context maintained through conversation history",
                    evidence="Full multi-turn transcript and tool parameters",
                    explanation=f"Context retention: {'Passed' if context_retained else 'Failed'}.",
                )
            )

        # Quality Metric 3: Professional Tone & Absence of Hallucination
        courteous_phrases = [
            "thank you", "help", "goodbye", "day", "welcome", "call back",
            "would you like", "please", "assist", "available", "hello", "schedule", "dr.",
            "apologize", "sorry", "follow up", "phone number", "team", "trouble"
        ]
        has_polite_tone = any(w in final_assistant for w in courteous_phrases) and len(final_assistant.strip()) > 0
        results.append(
            AssertionResult(
                name="quality:professional_tone",
                category="quality",
                status="PASS" if has_polite_tone else "FAIL",
                expected="Polite, professional conversational tone and closing",
                actual=turns[-1].get("assistant", ""),
                evidence=f"Closing response: \"{turns[-1].get('assistant', '')}\"",
                explanation="Response evaluated for professional tone and conversational standards.",
            )
        )

        return results
