from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import numpy as np

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_operator
from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.test_scenario import TestRun, TestRunEvent, TestScenario
from app.runtime.testing.regression import compare_test_runs
from app.runtime.testing.scenario_runner import TestScenarioRunner
from app.runtime.testing.templates import get_all_templates, get_template_by_id

router = APIRouter(prefix="/test-scenarios", tags=["Voice Agent Test Scenarios"])


class ScenarioPayload(BaseModel):
    client_id: Optional[str] = None
    agent_id: str
    agent_version_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    caller_goal: str = ""
    turns: List[str] = Field(min_length=1, max_length=50)
    initial_mock_state: Dict[str, Any] = Field(default_factory=dict)
    expected: Dict[str, Any] = Field(default_factory=dict)
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    evaluation_config: Dict[str, Any] = Field(default_factory=dict)
    max_turns: int = Field(default=10, ge=1, le=50)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class ScenarioUpdatePayload(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    caller_goal: Optional[str] = None
    turns: Optional[List[str]] = Field(default=None, min_length=1, max_length=50)
    initial_mock_state: Optional[Dict[str, Any]] = None
    expected: Optional[Dict[str, Any]] = None
    provider_config: Optional[Dict[str, Any]] = None
    evaluation_config: Optional[Dict[str, Any]] = None
    max_turns: Optional[int] = Field(default=None, ge=1, le=50)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    agent_version_id: Optional[str] = None


class TemplateInstantiatePayload(BaseModel):
    template_id: str
    agent_id: str
    agent_version_id: str
    name_override: Optional[str] = None


def _require_mock_mode() -> None:
    if settings.RUNTIME_MODE != "mock":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scenario execution requires server RUNTIME_MODE=mock.",
        )


def _resolve_agent(db: Session, agent_id: str, version_id: str) -> tuple[Agent, AgentVersion]:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    version = db.query(AgentVersion).filter(AgentVersion.id == version_id).first()
    if not agent or not version or version.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Agent or agent version not found.")
    if version.status != "PUBLISHED":
        raise HTTPException(status_code=409, detail="Test scenarios require a published immutable agent version.")
    return agent, version


def _scenario_response(scenario: TestScenario) -> Dict[str, Any]:
    return {
        "id": scenario.id,
        "client_id": scenario.client_id,
        "agent_id": scenario.agent_id,
        "agent_version_id": scenario.agent_version_id,
        "name": scenario.name,
        "description": scenario.description or "",
        "caller_goal": scenario.caller_goal or "",
        "turns": scenario.turns_json or [],
        "initial_mock_state": scenario.initial_mock_state_json or {},
        "expected": scenario.expected_json or {},
        "provider_config": scenario.provider_config_json or {},
        "evaluation_config": scenario.evaluation_config_json or {},
        "max_turns": scenario.max_turns,
        "timeout_seconds": scenario.timeout_seconds,
        "version_number": scenario.version_number,
        "status": scenario.status,
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
    }


def _run_response(run: TestRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "client_id": run.client_id,
        "agent_id": run.agent_id,
        "agent_version_id": run.agent_version_id,
        "runtime_session_id": run.runtime_session_id,
        "status": run.status,
        "provider_mode": run.provider_mode,
        "scenario_version": run.scenario_version,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "duration_ms": run.duration_ms,
        "turn_count": run.turn_count,
        "summary": run.summary_json or {},
        "usage": run.usage_json or {},
        "final_state": run.final_state_json or {},
        "metrics": run.metrics_json or {},
        "created_at": run.created_at,
    }


# ---------------------------------------------------------------------------
# SCENARIO TEMPLATES ENDPOINTS
# ---------------------------------------------------------------------------

@router.get("/templates")
def list_scenario_templates(current_user=Depends(require_operator)) -> List[Dict[str, Any]]:
    """Returns the 10 pre-configured enterprise Voice Agent Testing templates."""
    return get_all_templates()


@router.post("/templates/instantiate", status_code=status.HTTP_201_CREATED)
def instantiate_template(
    payload: TemplateInstantiatePayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    """Creates a persistent TestScenario instance from a chosen template for an agent."""
    tpl = get_template_by_id(payload.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Template '{payload.template_id}' not found.")

    agent, version = _resolve_agent(db, payload.agent_id, payload.agent_version_id)

    scenario = TestScenario(
        id=generate_unique_id("scn_"),
        client_id=agent.client_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        name=payload.name_override or tpl.name,
        description=tpl.description,
        caller_goal=tpl.caller_goal,
        turns_json=tpl.turns,
        initial_mock_state_json=tpl.initial_mock_state,
        expected_json=tpl.expected,
        provider_config_json=tpl.provider_config,
        evaluation_config_json={},
        max_turns=tpl.max_turns,
        timeout_seconds=tpl.timeout_seconds,
        created_by=current_user.id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return _scenario_response(scenario)


# ---------------------------------------------------------------------------
# SCENARIO CRUD ENDPOINTS
# ---------------------------------------------------------------------------

@router.get("")
def list_scenarios(
    agent_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> List[Dict[str, Any]]:
    query = db.query(TestScenario).filter(TestScenario.status == "ACTIVE")
    if agent_id:
        query = query.filter(TestScenario.agent_id == agent_id)
    scenarios = query.order_by(TestScenario.updated_at.desc()).all()
    
    # Enrich with latest run status if available
    result = []
    for scn in scenarios:
        data = _scenario_response(scn)
        latest_run = (
            db.query(TestRun)
            .filter(TestRun.scenario_id == scn.id)
            .order_by(TestRun.created_at.desc())
            .first()
        )
        if latest_run:
            data["latest_run"] = {
                "id": latest_run.id,
                "status": latest_run.status,
                "duration_ms": latest_run.duration_ms,
                "created_at": latest_run.created_at,
            }
        else:
            data["latest_run"] = None
        result.append(data)
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_scenario(
    payload: ScenarioPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    agent, version = _resolve_agent(db, payload.agent_id, payload.agent_version_id)
    if payload.client_id and payload.client_id != agent.client_id:
        raise HTTPException(status_code=403, detail="Scenario client does not match the agent tenant.")

    scenario = TestScenario(
        id=generate_unique_id("scn_"),
        client_id=agent.client_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        name=payload.name,
        description=payload.description,
        caller_goal=payload.caller_goal,
        turns_json=payload.turns,
        initial_mock_state_json=payload.initial_mock_state,
        expected_json=payload.expected,
        provider_config_json=payload.provider_config,
        evaluation_config_json=payload.evaluation_config,
        max_turns=payload.max_turns,
        timeout_seconds=payload.timeout_seconds,
        created_by=current_user.id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return _scenario_response(scenario)


@router.get("/{scenario_id}")
def get_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    scenario = db.query(TestScenario).filter(TestScenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Test scenario not found.")
    return _scenario_response(scenario)


@router.patch("/{scenario_id}")
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdatePayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    scenario = db.query(TestScenario).filter(TestScenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Test scenario not found.")

    changes = payload.model_dump(exclude_unset=True)
    if "agent_version_id" in changes:
        _, version = _resolve_agent(db, scenario.agent_id, changes["agent_version_id"])
        scenario.agent_version_id = version.id
        scenario.version_number += 1

    for key in (
        "name", "description", "caller_goal", "turns", "initial_mock_state",
        "expected", "provider_config", "evaluation_config", "max_turns", "timeout_seconds"
    ):
        if key in changes:
            target_attr = f"{key}_json" if key in ("turns", "initial_mock_state", "expected", "provider_config", "evaluation_config") else key
            setattr(scenario, target_attr, changes[key])

    scenario.version_number += 1
    scenario.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(scenario)
    return _scenario_response(scenario)


@router.post("/{scenario_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    source = db.query(TestScenario).filter(TestScenario.id == scenario_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Test scenario not found.")

    duplicate = TestScenario(
        id=generate_unique_id("scn_"),
        client_id=source.client_id,
        agent_id=source.agent_id,
        agent_version_id=source.agent_version_id,
        name=f"{source.name} Copy",
        description=source.description,
        caller_goal=source.caller_goal,
        turns_json=source.turns_json,
        initial_mock_state_json=source.initial_mock_state_json,
        expected_json=source.expected_json,
        provider_config_json=source.provider_config_json,
        evaluation_config_json=source.evaluation_config_json,
        max_turns=source.max_turns,
        timeout_seconds=source.timeout_seconds,
        created_by=current_user.id,
    )
    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)
    return _scenario_response(duplicate)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> None:
    scenario = db.query(TestScenario).filter(TestScenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Test scenario not found.")
    scenario.status = "ARCHIVED"
    db.commit()


# ---------------------------------------------------------------------------
# SCENARIO EXECUTION & RUNS
# ---------------------------------------------------------------------------

@router.post("/{scenario_id}/runs")
def run_scenario(
    scenario_id: str,
    provider_mode: str = Query(default="mock", pattern="^(mock|real|hybrid)$"),
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    _require_mock_mode()
    scenario = db.query(TestScenario).filter(TestScenario.id == scenario_id, TestScenario.status == "ACTIVE").first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Active test scenario not found.")

    runner = TestScenarioRunner(db)
    run = runner.run(scenario=scenario, provider_mode=provider_mode)
    return _run_response(run)


@router.get("/{scenario_id}/runs")
def list_runs(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> List[Dict[str, Any]]:
    runs = db.query(TestRun).filter(TestRun.scenario_id == scenario_id).order_by(TestRun.created_at.desc()).all()
    return [_run_response(run) for run in runs]


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    events_data = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "timestamp": e.timestamp,
            "duration_ms": e.duration_ms,
            "metadata": e.metadata_json,
        }
        for e in run.events
    ]
    return {**_run_response(run), "events": events_data}


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")
    if run.status == "RUNNING":
        run.status = "CANCELLED"
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
    return _run_response(run)


@router.get("/runs/{run_id}/compare/{other_run_id}")
def compare_runs_endpoint(
    run_id: str,
    other_run_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    first = db.query(TestRun).filter(TestRun.id == run_id).first()
    second = db.query(TestRun).filter(TestRun.id == other_run_id).first()
    if not first or not second or first.scenario_id != second.scenario_id:
        raise HTTPException(status_code=404, detail="Comparable runs for the same scenario were not found.")

    return compare_test_runs(baseline=first, comparison=second)


# ---------------------------------------------------------------------------
# AGGREGATE TESTING METRICS
# ---------------------------------------------------------------------------

@router.get("/metrics/summary")
def get_testing_metrics_summary(
    agent_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_operator),
) -> Dict[str, Any]:
    """Returns aggregated latency metrics (median, p95), pass rates, and failure categories."""
    scn_query = db.query(TestScenario).filter(TestScenario.status == "ACTIVE")
    if agent_id:
        scn_query = scn_query.filter(TestScenario.agent_id == agent_id)
    total_scenarios = scn_query.count()

    query = db.query(TestRun)
    if agent_id:
        query = query.filter(TestRun.agent_id == agent_id)

    runs = query.all()
    total_runs = len(runs)
    if total_runs == 0:
        return {
            "total_scenarios": total_scenarios,
            "total_runs": 0,
            "pass_count": 0,
            "fail_count": 0,
            "error_count": 0,
            "running_count": 0,
            "pass_rate_percentage": 0.0,
            "pass_rate_percent": 100.0,
            "status_counts": {"PASS": 0, "FAIL": 0, "ERROR": 0, "RUNNING": 0},
            "avg_duration_ms": 0,
            "avg_turns": 0,
            "latencies": {"p50_duration_ms": 0, "p95_duration_ms": 0},
            "stage_latencies": {"stt_p50_ms": 0, "llm_p50_ms": 0, "tts_p50_ms": 0},
            "avg_latencies": {"stt_ms": 0, "llm_ms": 0, "tts_ms": 0},
            "error_categories": {},
        }

    pass_count = sum(1 for r in runs if r.status == "PASS")
    fail_count = sum(1 for r in runs if r.status == "FAIL")
    error_count = sum(1 for r in runs if r.status in ("ERROR", "CANCELLED"))
    running_count = sum(1 for r in runs if r.status == "RUNNING")
    pass_pct = round((pass_count / total_runs) * 100, 1)

    durations = [r.duration_ms for r in runs if r.duration_ms is not None]
    durations_sorted = sorted(durations) if durations else [0]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0
    p50_ms = int(np.percentile(durations_sorted, 50)) if durations else 0
    p95_ms = int(np.percentile(durations_sorted, 95)) if durations else 0

    turns = [r.turn_count for r in runs if r.turn_count is not None]
    avg_turns = round(sum(turns) / len(turns), 1) if turns else 0

    stt_vals = [
        (r.metrics_json or {}).get("stt_p50_ms", 0)
        for r in runs
        if (r.metrics_json or {}).get("stt_p50_ms") is not None
    ]
    llm_vals = [
        (r.metrics_json or {}).get("llm_p50_ms", 0)
        for r in runs
        if (r.metrics_json or {}).get("llm_p50_ms") is not None
    ]
    tts_vals = [
        (r.metrics_json or {}).get("tts_p50_ms", 0)
        for r in runs
        if (r.metrics_json or {}).get("tts_p50_ms") is not None
    ]

    stt_p50 = int(np.percentile(stt_vals, 50)) if stt_vals else 0
    llm_p50 = int(np.percentile(llm_vals, 50)) if llm_vals else 0
    tts_p50 = int(np.percentile(tts_vals, 50)) if tts_vals else 0

    error_categories: Dict[str, int] = {}
    for r in runs:
        if r.status in ("FAIL", "ERROR"):
            err_msg = (r.summary_json or {}).get("error") or "AssertionFailure"
            key = err_msg.split(":")[0] if ":" in err_msg else err_msg[:30]
            error_categories[key] = error_categories.get(key, 0) + 1

    return {
        "total_scenarios": total_scenarios,
        "total_runs": total_runs,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "running_count": running_count,
        "pass_rate_percentage": pass_pct,
        "pass_rate_percent": pass_pct,
        "status_counts": {
            "PASS": pass_count,
            "FAIL": fail_count,
            "ERROR": error_count,
            "RUNNING": running_count,
        },
        "avg_duration_ms": avg_duration,
        "avg_turns": avg_turns,
        "latencies": {
            "p50_duration_ms": p50_ms,
            "p95_duration_ms": p95_ms,
        },
        "stage_latencies": {
            "stt_p50_ms": stt_p50,
            "llm_p50_ms": llm_p50,
            "tts_p50_ms": tts_p50,
        },
        "avg_latencies": {
            "stt_ms": stt_p50,
            "llm_ms": llm_p50,
            "tts_ms": tts_p50,
        },
        "error_categories": error_categories,
    }
