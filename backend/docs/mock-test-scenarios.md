# Mock Voice-Agent Test Scenarios

Choranta test scenarios run only when the server is configured with `RUNTIME_MODE=mock`.
They execute the existing `AgentRuntime` and persist the resulting runtime session, events,
assertions, usage, and status. They never call Cartesia, Gemini, Exotel, or external tools.

## Workflow

1. Seed deterministic local fixtures with `POST /api/mock/seed`.
2. Create a scenario with `POST /api/test-scenarios`.
3. Run it with `POST /api/test-scenarios/{scenario_id}/runs`.
4. Inspect the run and trace with `GET /api/test-scenarios/runs/{run_id}`.
5. Compare completed runs with `GET /api/test-scenarios/runs/{run_id}/compare/{other_run_id}`.

Example scenario payload:

```json
{
  "agent_id": "mock_agt_acme_health",
  "agent_version_id": "mock_agtv_1",
  "name": "Appointment availability",
  "caller_goal": "Find an appointment slot",
  "turns": ["I want to check appointment availability"],
  "expected": {
    "required_tool_calls": ["check_availability"],
    "final_response_contains": ["Dr. Rao"]
  },
  "max_turns": 5,
  "timeout_seconds": 60
}
```

Runs return `PASS`, `FAIL`, or `ERROR`. A failed deterministic assertion is `FAIL`;
provider/runtime/persistence failures are `ERROR`. Mock usage is labelled simulated and is
excluded from production billing.

The current runner supports scripted text turns, required/forbidden tool assertions,
final-response substring assertions, maximum turn limits, runtime event traces, and run
comparison. LLM-judge evaluation, cancellation, initial mock business-state snapshots, and
full scenario fixture isolation remain future extensions.
