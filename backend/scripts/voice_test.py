"""
Voice test calls from the command line: a scripted caller talks to an AI Employee through the real call
engine, and each turn's timing is reported. No phone needed.

  cd backend
  python -m scripts.voice_test --agent <agent_id>                     all of the agent's test scenarios (mock)
  python -m scripts.voice_test --agent <agent_id> --real              ...with the real speech and AI providers
  python -m scripts.voice_test --scenario <scenario_id> --real        one scenario
  python -m scripts.voice_test --agent <agent_id> --real --say "Hello?" --say "I want a 2BHK in Kondapur"
                                                                      quick check with your own caller lines
  python -m scripts.voice_test --list                                 agents with a published version

Mock runs are free (synthetic voices, scripted replies) and check the conversation flow. Real runs use the
agent's own providers and cost about as much as a short call; they are never billed to the client.
"""
import argparse
import asyncio
import logging
import os
import sys
from typing import List, Optional

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.test_scenario import TestRun, TestScenario
from app.runtime.testing.voice_runner import VoiceScenarioRunner

QUICK_SCENARIO_NAME = "Quick voice check (CLI)"


def _published_version(db, agent_id: str) -> Optional[AgentVersion]:
    return (db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent_id, AgentVersion.status == "PUBLISHED")
            .order_by(AgentVersion.created_at.desc()).first())


def _quick_scenario(db, agent: Agent, lines: List[str]) -> TestScenario:
    version = _published_version(db, agent.id)
    if not version:
        sys.exit(f"Agent {agent.id} has no published version to test.")
    scenario = (db.query(TestScenario)
                .filter(TestScenario.agent_id == agent.id, TestScenario.name == QUICK_SCENARIO_NAME).first())
    if scenario is None:
        scenario = TestScenario(client_id=agent.client_id, agent_id=agent.id, name=QUICK_SCENARIO_NAME,
                                description="Caller lines given on the command line.")
        db.add(scenario)
    scenario.agent_version_id = version.id
    scenario.turns_json = lines
    scenario.max_turns = max(len(lines), 1)
    scenario.expected_json = scenario.expected_json or {}
    scenario.provider_config_json = scenario.provider_config_json or {}
    scenario.status = "ACTIVE"
    db.commit()
    db.refresh(scenario)
    return scenario


def _ms(value) -> str:
    if value is None:
        return "-"
    return f"{value / 1000:.2f} s" if value >= 1000 else f"{value} ms"


def _cut(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def print_report(run: TestRun, scenario: TestScenario) -> None:
    summary = run.summary_json or {}
    metrics = run.metrics_json or {}
    print()
    print(f"=== {scenario.name}  [{run.provider_mode}]  ->  {run.status}")
    if summary.get("error"):
        print(f"    ERROR: {summary['error']}")
    if summary.get("greeting"):
        print(f"    Agent greeting: \"{_cut(summary['greeting'], 100)}\"")
    print()
    print(f"    {'#':<3}{'Caller said':<34}{'Agent heard':<30}{'Gap':>9}{'STT':>9}{'LLM 1st':>9}  Agent replied")
    for t in summary.get("turns", []):
        caller = t.get("caller") or f"({t.get('behavior')})"
        if t.get("behavior") not in ("normal", None):
            caller = f"[{t['behavior']}] {caller}"
        stages = t.get("stage_latencies") or {}
        note = ""
        if t.get("behavior") == "interrupt":
            note = f"  (stopped in {_ms(t.get('interrupt_stop_ms'))})" if t.get("interrupt_stop_ms") is not None else "  (did NOT stop)"
        if t.get("behavior") == "backchannel":
            note = "  (kept talking)" if t.get("agent_kept_talking") else "  (STOPPED)"
        if t.get("behavior") == "silence":
            after = t.get("agent_spoke_during_silence_after_ms")
            note = f"  (agent checked in after {_ms(after)})" if after else "  (agent stayed quiet)"
        if (t.get("engine_stall_ms") or 0) >= 200:
            note += f"  (engine froze for {_ms(t['engine_stall_ms'])})"
        if t.get("talk_over_ms"):
            note += f"  (agent talked over the caller for {_ms(t['talk_over_ms'])})"
        print(f"    {t['turn_number']:<3}{_cut(caller, 33):<34}{_cut(t.get('heard', ''), 29):<30}"
              f"{_ms(t.get('response_gap_ms')):>9}{_ms(stages.get('stt_ms')):>9}{_ms(stages.get('llm_first_token_ms')):>9}"
              f"  {_cut(t.get('assistant', ''), 60)}{note}")
    print()
    print(f"    Reply gap: avg {_ms(metrics.get('avg_response_gap_ms'))}, median {_ms(metrics.get('p50_response_gap_ms'))}, "
          f"worst {_ms(metrics.get('max_response_gap_ms'))}   |   talk-over {_ms(metrics.get('talk_over_ms'))}"
          f"   |   heard correctly {round((metrics.get('transcript_accuracy') or 0) * 100)}%"
          f"   |   ended by {metrics.get('call_ended_by')}"
          f"   |   engine stall {_ms(metrics.get('max_engine_stall_ms'))}")
    print("    (Gap = caller's last word to the agent's first sound, including the silence the engine waits"
          " to be sure the caller finished.)")
    failed = [a for a in summary.get("assertions", []) if a.get("status") != "PASS"]
    print(f"    Checks: {summary.get('passed_count', 0)} passed, {summary.get('failed_count', 0)} failed, "
          f"{summary.get('error_count', 0)} errors")
    for a in failed:
        print(f"      x {a['name']}: {a.get('explanation')}")
    if metrics.get("recording_file"):
        print(f"    Recording: {os.path.join(settings.RECORDINGS_DIR, metrics['recording_file'])}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Voice test calls against an AI Employee (no phone needed).")
    parser.add_argument("--agent", help="agent id: run all of its active test scenarios")
    parser.add_argument("--scenario", help="run one test scenario")
    parser.add_argument("--real", action="store_true", help="use the real speech and AI providers (costs credits)")
    parser.add_argument("--say", action="append", help="a caller line for a quick check (repeat for more lines)")
    parser.add_argument("--list", action="store_true", help="list agents that have a published version")
    parser.add_argument("--verbose", action="store_true", help="show the call engine's log")
    args = parser.parse_args()
    # Agents speak Telugu, Hindi and more; Windows consoles default to a code page that can't print them
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    mode = "real" if args.real else "mock"
    db = SessionLocal()
    try:
        if args.list:
            for agent in db.query(Agent).order_by(Agent.name).all():
                version = _published_version(db, agent.id)
                if version:
                    count = db.query(TestScenario).filter(TestScenario.agent_id == agent.id,
                                                          TestScenario.status == "ACTIVE").count()
                    print(f"{agent.id}  {agent.name}  ({count} scenarios)")
            return 0

        if args.scenario:
            scenarios = db.query(TestScenario).filter(TestScenario.id == args.scenario).all()
        elif args.agent:
            agent = db.get(Agent, args.agent)
            if not agent:
                sys.exit(f"No agent '{args.agent}'.")
            if args.say:
                scenarios = [_quick_scenario(db, agent, args.say)]
            else:
                scenarios = (db.query(TestScenario)
                             .filter(TestScenario.agent_id == agent.id, TestScenario.status == "ACTIVE",
                                     TestScenario.name != QUICK_SCENARIO_NAME)
                             .order_by(TestScenario.created_at).all())
        else:
            parser.print_help()
            return 2
        if not scenarios:
            sys.exit("No test scenarios found. Add some in the studio, or pass caller lines with --say.")

        runner = VoiceScenarioRunner(db)
        failures = 0
        for scenario in scenarios:
            print(f"Calling: {scenario.name} ({mode}) ...", flush=True)
            run = await runner.run(scenario, provider_mode=mode)
            print_report(run, scenario)
            failures += run.status != "PASS"
        print()
        print(f"{len(scenarios) - failures}/{len(scenarios)} scenarios passed.")
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
