import { request } from './api';

export interface TestScenario {
  id: string;
  client_id: string;
  agent_id: string;
  agent_version_id: string;
  name: string;
  description: string;
  caller_goal: string;
  turns: string[];
  initial_mock_state?: Record<string, any>;
  expected: Record<string, any>;
  evaluation_config?: Record<string, any>;
  provider_config: Record<string, any>;
  max_turns: number;
  timeout_seconds: number;
  version_number: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ScenarioTemplate {
  template_id: string;
  name: string;
  description: string;
  caller_goal: string;
  turns: string[];
  initial_mock_state: Record<string, any>;
  provider_config: Record<string, any>;
  expected: Record<string, any>;
  max_turns: number;
  category?: string;
}

export interface AssertionResult {
  name: string;
  status: 'PASS' | 'FAIL' | 'ERROR';
  expected: any;
  actual: any;
  evidence: string;
}

export interface TestTurnSummary {
  turn_index?: number;
  caller: string;
  assistant: string;
  tool_calls: number;
  latency_ms?: { stt?: number; llm?: number; tts?: number; total?: number };
}

export interface TestRun {
  id: string;
  scenario_id: string;
  client_id?: string;
  agent_id?: string;
  agent_version_id?: string;
  status: 'RUNNING' | 'PASS' | 'FAIL' | 'ERROR';
  provider_mode: string;
  scenario_version: number;
  runtime_session_id?: string | null;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number | null;
  turn_count: number;
  summary: {
    assertions?: AssertionResult[];
    turns?: TestTurnSummary[];
    error?: string | null;
  };
  final_state?: Record<string, any>;
  metrics?: {
    latencies?: {
      stt_avg_ms?: number;
      llm_avg_ms?: number;
      tts_avg_ms?: number;
      turn_avg_ms?: number;
    };
    quality?: {
      goal_completion_score?: number;
      tone_consistency?: string;
      hallucination_detected?: boolean;
      interruption_handling?: string;
      explanation?: string;
    };
  };
  usage: Record<string, any>;
}

export interface RegressionComparison {
  status: 'REGRESSION' | 'IMPROVEMENT' | 'UNCHANGED';
  baseline_run_id: string;
  comparison_run_id: string;
  baseline_status: string;
  comparison_status: string;
  assertions: {
    total_baseline: number;
    total_comparison: number;
    newly_passing: string[];
    newly_failing: string[];
    common_passing: string[];
    common_failing: string[];
  };
  tools: {
    baseline_tool_calls: number;
    comparison_tool_calls: number;
    difference: number;
  };
  duration: {
    baseline_ms: number;
    comparison_ms: number;
    delta_ms: number;
  };
  metrics_comparison: {
    llm_latency_delta_ms: number;
    stt_latency_delta_ms: number;
    tts_latency_delta_ms: number;
  };
  summary: string;
}

export interface TestMetricsSummary {
  total_scenarios?: number;
  total_runs: number;
  pass_count?: number;
  fail_count?: number;
  error_count?: number;
  pass_rate_percent?: number;
  pass_rate_percentage?: number;
  status_counts?: {
    PASS?: number;
    FAIL?: number;
    ERROR?: number;
    RUNNING?: number;
  };
  avg_duration_ms?: number;
  avg_turns?: number;
  avg_latencies?: {
    stt_ms?: number;
    llm_ms?: number;
    tts_ms?: number;
  };
}

export const testScenariosService = {
  list: (agentId?: string) =>
    request<TestScenario[]>(`/test-scenarios${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`),
  create: (payload: Partial<TestScenario>) =>
    request<TestScenario>('/test-scenarios', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id: string, payload: Partial<TestScenario>) =>
    request<TestScenario>(`/test-scenarios/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  delete: (id: string) =>
    request<void>(`/test-scenarios/${id}`, { method: 'DELETE' }),
  duplicate: (id: string) =>
    request<TestScenario>(`/test-scenarios/${id}/duplicate`, { method: 'POST' }),
  listTemplates: () =>
    request<ScenarioTemplate[]>('/test-scenarios/templates'),
  instantiateTemplate: (payload: { template_id: string; agent_id: string; agent_version_id?: string; name?: string }) =>
    request<TestScenario>('/test-scenarios/templates/instantiate', { method: 'POST', body: JSON.stringify(payload) }),
  run: (scenarioId: string, payload?: { mock_providers?: Record<string, any>; initial_state?: Record<string, any> }) =>
    request<TestRun>(`/test-scenarios/${scenarioId}/runs`, {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
    }),
  listRuns: (scenarioId: string) =>
    request<TestRun[]>(`/test-scenarios/${scenarioId}/runs`),
  compareRuns: (baselineRunId: string, comparisonRunId: string) =>
    request<RegressionComparison>(`/test-scenarios/runs/${comparisonRunId}/compare/${baselineRunId}`),
  getMetricsSummary: (agentId?: string) =>
    request<TestMetricsSummary>(`/test-scenarios/metrics/summary${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`),
};
