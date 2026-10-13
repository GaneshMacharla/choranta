from datetime import datetime, timezone
import logging
from time import perf_counter
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException, ValidationException
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.test_scenario import TestRun, TestRunEvent, TestScenario
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.runtime.providers.registry import ProviderRegistry
from app.runtime.runtime import AgentRuntime
from app.runtime.testing.business_state import MockBusinessState
from app.runtime.testing.caller_simulator import SimulatedCaller
from app.runtime.testing.evaluation_engine import EvaluationEngine
from app.runtime.testing.mock_providers import (
    TestingLLMAdapter,
    TestingSTTAdapter,
    TestingTTSAdapter,
    create_testing_tool_executor,
)

logger = logging.getLogger("choranta.testing.runner")


class TestScenarioRunner:
    """
    Executes a TestScenario against the actual Choranta runtime orchestration path.
    Enforces thread/run isolation, captures stage latencies, evaluates assertions,
    and persists immutable run results and traces.
    """

    def __init__(self, db: Session):
        self.db = db

    def run(
        self,
        scenario: TestScenario,
        provider_mode: str = "mock",
        run_id: Optional[str] = None,
    ) -> TestRun:
        # 1. Resolve and validate agent & version
        agent = self.db.query(Agent).filter(Agent.id == scenario.agent_id).first()
        version = self.db.query(AgentVersion).filter(AgentVersion.id == scenario.agent_version_id).first()
        if not agent:
            raise NotFoundException("Agent", scenario.agent_id)
        if not version:
            raise NotFoundException("AgentVersion", scenario.agent_version_id)
        if version.status != "PUBLISHED":
            raise ValidationException("Test scenario requires a published immutable agent version.")

        # 2. Create persistent TestRun record
        actual_run_id = run_id or generate_unique_id("run_")
        run = TestRun(
            id=actual_run_id,
            scenario_id=scenario.id,
            client_id=agent.client_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            status="RUNNING",
            provider_mode=provider_mode,
            scenario_version=scenario.version_number,
            started_at=datetime.now(timezone.utc),
            turn_count=0,
            summary_json={},
            usage_json={},
            final_state_json={},
            metrics_json={},
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        started_perf = perf_counter()
        turns: List[Dict[str, Any]] = []
        runtime_session = None
        business_state = MockBusinessState.from_dict(scenario.initial_mock_state_json or {})
        runtime_error: Optional[str] = None

        # Stage durations tracking
        stt_durations: List[float] = []
        llm_durations: List[float] = []
        tts_durations: List[float] = []

        try:
            # 3. Setup isolated test providers & registry
            test_registry = ProviderRegistry("mock")
            stt_adapter = TestingSTTAdapter("test_stt")
            llm_adapter = TestingLLMAdapter("test_llm")
            tts_adapter = TestingTTSAdapter("test_tts")

            p_config = scenario.provider_config_json or {}
            if "stt" in p_config:
                stt_adapter.configure(p_config["stt"])
            if "llm" in p_config:
                llm_adapter.configure(p_config["llm"])
            if "tts" in p_config:
                tts_adapter.configure(p_config["tts"])

            # Map to canonical names used by spec (cartesia, gemini, etc.)
            test_registry.register_stt("cartesia", stt_adapter)
            test_registry.register_stt("mock_stt", stt_adapter)
            test_registry.register_llm("gemini", llm_adapter)
            test_registry.register_llm("mock_llm", llm_adapter)
            test_registry.register_tts("cartesia", tts_adapter)
            test_registry.register_tts("mock_tts", tts_adapter)

            # 4. Create state-aware ToolExecutor and AgentRuntime
            tool_executor = create_testing_tool_executor(business_state)
            runtime = AgentRuntime(self.db, registry=test_registry, tool_executor=tool_executor)

            # 5. Start real runtime session
            runtime_session = runtime.start_session(
                agent_id=agent.id,
                agent_version_id=version.id,
                metadata={
                    "test_run_id": run.id,
                    "scenario_id": scenario.id,
                    "provider_mode": provider_mode,
                    "is_test": True,
                },
            )
            run.runtime_session_id = runtime_session.id
            self.db.commit()

            # 6. Initialize SimulatedCaller
            simulated_caller = SimulatedCaller(
                scripted_turns=scenario.turns_json or [],
                caller_goal=scenario.caller_goal or "",
                max_turns=scenario.max_turns or 10,
            )

            last_assistant_response: Optional[str] = None

            # 7. Multi-turn conversation execution loop
            for turn_idx in range(scenario.max_turns or 10):
                caller_turn = simulated_caller.next_turn(last_assistant_response)

                # Process turn through actual runtime
                turn_start = perf_counter()
                stt_start = perf_counter()
                # Run turn through runtime.process_turn
                turn_result = runtime.process_turn(runtime_session.id, caller_turn.text)
                turn_duration = (perf_counter() - turn_start) * 1000

                # Approximation of stage latencies for deterministic mock mode
                stt_ms = round(stt_adapter.simulated_latency_seconds * 1000 or 15)
                llm_ms = round(llm_adapter.simulated_latency_seconds * 1000 or 45)
                tts_ms = round(tts_adapter.simulated_latency_seconds * 1000 or 25)

                stt_durations.append(stt_ms)
                llm_durations.append(llm_ms)
                tts_durations.append(tts_ms)

                last_assistant_response = turn_result["assistant_response"]

                turns.append({
                    "turn_number": turn_idx + 1,
                    "caller": caller_turn.text,
                    "assistant": last_assistant_response,
                    "behavior": caller_turn.behavior,
                    "tool_calls_executed": turn_result["tool_calls_executed"],
                    "turn_duration_ms": round(turn_duration),
                    "stage_latencies": {
                        "stt_ms": stt_ms,
                        "llm_ms": llm_ms,
                        "tts_ms": tts_ms,
                    },
                    "usage": turn_result["usage"],
                    "call_ended": bool(turn_result.get("call_ended")),
                })

                if turn_result.get("call_ended"):
                    logger.info(f"AI employee hung up at turn {turn_idx + 1}.")
                    break

                if caller_turn.is_terminal:
                    logger.info(f"SimulatedCaller completed conversation naturally at turn {turn_idx + 1}.")
                    break

            # 8. Cleanly end session
            completed_session = runtime.end_session(runtime_session.id)
            session_status = completed_session.status
            run.usage_json = completed_session.usage_json or {}

        except Exception as exc:
            logger.error(f"Error during scenario execution: {exc}", exc_info=True)
            runtime_error = f"{type(exc).__name__}: {str(exc)}"
            session_status = "ERROR"
            if runtime_session and runtime_session.status == "ACTIVE":
                try:
                    AgentRuntime(self.db, registry=test_registry).end_session(runtime_session.id)
                except Exception:
                    pass

        finally:
            ended_perf = perf_counter()
            duration_ms = round((ended_perf - started_perf) * 1000)
            run.ended_at = datetime.now(timezone.utc)
            run.duration_ms = duration_ms
            run.turn_count = len(turns)

            # 9. Gather runtime events
            runtime_events = []
            if runtime_session:
                runtime_events = RuntimeEventRepository(self.db).list_by_session(runtime_session.id)

            # 10. Run Evaluation Engine
            evaluator = EvaluationEngine()
            summary = evaluator.evaluate(
                expected=scenario.expected_json or {},
                turns=turns,
                events=runtime_events,
                business_state=business_state,
                max_turns=scenario.max_turns or 10,
                duration_ms=duration_ms,
                session_status=session_status,
                caller_goal=scenario.caller_goal or "",
                tenant_context={
                    "client_id": scenario.client_id,
                    "agent_client_id": agent.client_id,
                    "scenario_client_id": scenario.client_id,
                },
                runtime_error=runtime_error,
            )

            run.status = summary.overall_status
            run.final_state_json = business_state.to_dict()

            # 11. Calculate stage metrics
            metrics = {
                "total_duration_ms": duration_ms,
                "turn_count": len(turns),
                "stt_ms_total": sum(stt_durations),
                "llm_ms_total": sum(llm_durations),
                "tts_ms_total": sum(tts_durations),
                "stt_p50_ms": sorted(stt_durations)[len(stt_durations) // 2] if stt_durations else 0,
                "llm_p50_ms": sorted(llm_durations)[len(llm_durations) // 2] if llm_durations else 0,
                "tts_p50_ms": sorted(tts_durations)[len(tts_durations) // 2] if tts_durations else 0,
                "tool_calls_total": sum(t.get("tool_calls_executed", 0) for t in turns),
                "is_simulated_latency": True,
            }
            run.metrics_json = metrics

            run.summary_json = {
                "assertions": [a.model_dump() for a in summary.assertions],
                "passed_count": summary.passed_count,
                "failed_count": summary.failed_count,
                "error_count": summary.error_count,
                "turns": turns,
                "error": runtime_error,
            }

            # 12. Persist TestRunEvents
            for event in runtime_events:
                self.db.add(
                    TestRunEvent(
                        id=generate_unique_id("runevt_"),
                        run_id=run.id,
                        session_id=runtime_session.id if runtime_session else None,
                        event_type=event.event_type,
                        timestamp=event.timestamp,
                        metadata_json=event.payload_json or {},
                    )
                )

            # Add evaluation assertion event
            self.db.add(
                TestRunEvent(
                    id=generate_unique_id("runevt_"),
                    run_id=run.id,
                    session_id=runtime_session.id if runtime_session else None,
                    event_type="ASSERTIONS_EVALUATED",
                    timestamp=datetime.now(timezone.utc),
                    metadata_json={
                        "overall_status": summary.overall_status,
                        "passed_count": summary.passed_count,
                        "failed_count": summary.failed_count,
                    },
                )
            )

            self.db.commit()
            self.db.refresh(run)

        return run
