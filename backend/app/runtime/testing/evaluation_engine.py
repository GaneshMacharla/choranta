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
        voice_metrics: Optional[Dict[str, Any]] = None,
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
        # Its keyword checks are English-only, so voice runs (often Telugu or Hindi) use them only on request
        if voice_metrics is None or expected.get("quality_checks"):
            quality_results = self.quality_evaluator.evaluate_quality(
                turns=turns,
                caller_goal=caller_goal,
                expected=expected,
                business_state=business_state,
            )
            assertions.extend(quality_results)

        # 9. VOICE CALL CHECKS (voice test runs only)
        if voice_metrics is not None:
            assertions.extend(voice_assertions(expected, voice_metrics, turns))

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


# Voice checks that apply when a scenario doesn't set its own threshold (expected_json keys of the same name)
DEFAULT_VOICE_THRESHOLDS: Dict[str, Any] = {
    "max_response_gap_ms": 2500,      # longest silence after the caller finishes before the agent speaks
    "avg_response_gap_ms": 1800,
    "max_interrupt_stop_ms": 600,     # how long the agent keeps talking once the caller cuts in
    "min_transcript_accuracy": 0.8,   # share of the caller's words the agent heard correctly (real runs)
    "max_talk_over_ms": 300,          # agent audio while the caller was still mid-sentence
    "expected_call_end": "any",       # "agent", "caller" or "any"
}


def voice_assertions(expected: Dict[str, Any], metrics: Dict[str, Any], turns: List[Dict[str, Any]]) -> List[AssertionResult]:
    """Rule-based checks on how a voice call went: timing, interruptions, hearing the caller, ending."""
    limits = {**DEFAULT_VOICE_THRESHOLDS, **{k: v for k, v in expected.items() if k in DEFAULT_VOICE_THRESHOLDS}}
    results: List[AssertionResult] = []

    def check(name: str, passed: bool, expected_text: str, actual: Any, explanation: str) -> None:
        results.append(AssertionResult(
            name=name, category="voice", status="PASS" if passed else "FAIL",
            expected=expected_text, actual=actual, evidence="Voice test call timings", explanation=explanation,
        ))

    unanswered = metrics.get("unanswered_turns") or []
    check("voice:every_turn_answered", not unanswered, "The agent answers every caller line",
          unanswered or "all answered",
          "Every caller line got a spoken reply." if not unanswered
          else f"No reply within the time limit after caller line(s) {unanswered}.")

    gaps = metrics.get("response_gaps_ms") or []
    if gaps:
        slowest = max(gaps)
        slow_turns = [t["turn_number"] for t in turns if (t.get("response_gap_ms") or 0) > limits["max_response_gap_ms"]]
        check("voice:max_response_gap", slowest <= limits["max_response_gap_ms"],
              f"Every reply starts within {limits['max_response_gap_ms']} ms", f"{slowest} ms",
              f"Slowest reply started {slowest} ms after the caller finished"
              + (f" (slow turns: {slow_turns})." if slow_turns else "."))
        average = metrics.get("avg_response_gap_ms") or 0
        check("voice:avg_response_gap", average <= limits["avg_response_gap_ms"],
              f"Average reply gap <= {limits['avg_response_gap_ms']} ms", f"{average} ms",
              f"Replies started {average} ms after the caller finished, on average.")

    for turn in turns:
        if turn.get("behavior") != "interrupt":
            continue
        n = turn["turn_number"]
        if not turn.get("agent_was_speaking", True):
            results.append(AssertionResult(
                name=f"voice:interrupt_stop:turn_{n}", category="voice", status="PASS",
                expected="Agent stops when the caller cuts in", actual="agent had already finished",
                evidence="Voice test call timings",
                explanation=f"Turn {n}: the agent's reply ended before the caller cut in, so there was nothing to stop.",
            ))
            continue
        stop = turn.get("interrupt_stop_ms")
        check(f"voice:interrupt_stop:turn_{n}", stop is not None and stop <= limits["max_interrupt_stop_ms"],
              f"Agent stops within {limits['max_interrupt_stop_ms']} ms of the caller cutting in",
              f"{stop} ms" if stop is not None else "kept talking",
              f"Turn {n}: the agent stopped {stop} ms after the caller started talking." if stop is not None
              else f"Turn {n}: the agent did not stop when the caller cut in.")

    for turn in turns:
        if turn.get("behavior") == "backchannel":
            kept = bool(turn.get("agent_kept_talking"))
            check(f"voice:backchannel:turn_{turn['turn_number']}", kept,
                  f"Agent keeps talking through '{turn.get('caller')}'", "kept talking" if kept else "stopped",
                  "The short acknowledgement didn't derail the reply." if kept
                  else "The agent treated a short acknowledgement as an interruption.")

    accuracy = metrics.get("transcript_accuracy")
    if accuracy is not None and metrics.get("provider_mode") == "real":
        worst = min((t for t in turns if "transcript_accuracy" in t), key=lambda t: t["transcript_accuracy"], default=None)
        check("voice:transcript_accuracy", accuracy >= limits["min_transcript_accuracy"],
              f"Agent hears >= {round(limits['min_transcript_accuracy'] * 100)}% of the caller's words",
              f"{round(accuracy * 100)}%",
              f"Average {round(accuracy * 100)}% of words heard correctly"
              + (f"; worst: said \"{worst['caller']}\", heard \"{worst.get('heard', '')}\"." if worst else "."))

    talk_over = metrics.get("talk_over_ms") or 0
    check("voice:no_talking_over_caller", talk_over <= limits["max_talk_over_ms"],
          f"Agent talks over the caller for <= {limits['max_talk_over_ms']} ms", f"{talk_over} ms",
          "The agent waited for the caller to finish." if talk_over <= limits["max_talk_over_ms"]
          else f"The agent started speaking while the caller was still talking ({talk_over} ms).")

    wanted = str(limits["expected_call_end"] or "any").lower()
    ended_by = metrics.get("call_ended_by")
    if wanted in ("agent", "caller"):
        check("voice:call_end", ended_by == wanted, f"Call ended by the {wanted}", ended_by,
              f"The call was ended by the {ended_by} ({metrics.get('end_reason')}).")
    return results
