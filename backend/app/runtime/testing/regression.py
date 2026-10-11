from typing import Any, Dict, List
from app.models.test_scenario import TestRun


def compare_test_runs(baseline: TestRun, comparison: TestRun) -> Dict[str, Any]:
    """
    Performs deterministic regression analysis between two completed test runs.
    Detects newly passing/failing assertions, tool behavior drift, and latency changes.
    """
    baseline_summary = baseline.summary_json or {}
    comparison_summary = comparison.summary_json or {}

    b_assertions = {item["name"]: item for item in baseline_summary.get("assertions", [])}
    c_assertions = {item["name"]: item for item in comparison_summary.get("assertions", [])}

    all_names = sorted(set(b_assertions.keys()) | set(c_assertions.keys()))

    newly_passing: List[Dict[str, Any]] = []
    newly_failing: List[Dict[str, Any]] = []
    unchanged_passing: List[str] = []
    unchanged_failing: List[str] = []
    status_changes: List[Dict[str, Any]] = []

    for name in all_names:
        b_status = b_assertions.get(name, {}).get("status", "NOT_EVALUATED")
        c_status = c_assertions.get(name, {}).get("status", "NOT_EVALUATED")

        if b_status != c_status:
            status_changes.append({
                "name": name,
                "before": b_status,
                "after": c_status,
                "expected": c_assertions.get(name, {}).get("expected"),
                "actual": c_assertions.get(name, {}).get("actual"),
                "explanation": c_assertions.get(name, {}).get("explanation", ""),
            })

            if b_status in ("FAIL", "ERROR") and c_status == "PASS":
                newly_passing.append({"name": name, "before": b_status, "after": c_status})
            elif b_status == "PASS" and c_status in ("FAIL", "ERROR"):
                newly_failing.append({"name": name, "before": b_status, "after": c_status})
        else:
            if b_status == "PASS":
                unchanged_passing.append(name)
            elif b_status in ("FAIL", "ERROR"):
                unchanged_failing.append(name)

    # Tool execution diff
    b_tools = [
        tc.get("tool_name")
        for turn in baseline_summary.get("turns", [])
        for tc in turn.get("tool_calls", [])
    ]
    c_tools = [
        tc.get("tool_name")
        for turn in comparison_summary.get("turns", [])
        for tc in turn.get("tool_calls", [])
    ]

    # Latency metric delta
    b_duration = baseline.duration_ms or 0
    c_duration = comparison.duration_ms or 0
    delta_ms = c_duration - b_duration
    delta_pct = round((delta_ms / max(b_duration, 1)) * 100, 1)

    # Overall regression verdict
    if len(newly_failing) > 0:
        verdict = "REGRESSED"
    elif len(newly_passing) > 0:
        verdict = "IMPROVED"
    else:
        verdict = "UNCHANGED"

    # Compatibility check notes
    compatibility_notes = []
    if baseline.provider_mode != comparison.provider_mode:
        compatibility_notes.append(
            f"Different provider modes: baseline was '{baseline.provider_mode}', comparison was '{comparison.provider_mode}'."
        )
    if baseline.scenario_version != comparison.scenario_version:
        compatibility_notes.append(
            f"Scenario version modified: baseline v{baseline.scenario_version} vs comparison v{comparison.scenario_version}."
        )

    return {
        "scenario_id": baseline.scenario_id,
        "baseline_run_id": baseline.id,
        "comparison_run_id": comparison.id,
        "verdict": verdict,
        "newly_passing": newly_passing,
        "newly_failing": newly_failing,
        "unchanged_passing_count": len(unchanged_passing),
        "unchanged_failing_count": len(unchanged_failing),
        "status_changes": status_changes,
        "tool_execution": {
            "baseline_tools": b_tools,
            "comparison_tools": c_tools,
            "tools_added": [t for t in c_tools if t not in b_tools],
            "tools_removed": [t for t in b_tools if t not in c_tools],
        },
        "latency": {
            "baseline_ms": b_duration,
            "comparison_ms": c_duration,
            "delta_ms": delta_ms,
            "delta_percentage": delta_pct,
        },
        "compatibility_notes": compatibility_notes,
    }
