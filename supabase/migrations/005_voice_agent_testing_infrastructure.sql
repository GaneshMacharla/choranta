-- Migration 005: Voice Agent Testing Infrastructure
-- Adds initial_mock_state_json, evaluation_config_json to test_scenarios
-- Adds final_state_json, metrics_json to test_runs

alter table if exists test_scenarios
    add column if not exists initial_mock_state_json jsonb not null default '{}'::jsonb,
    add column if not exists evaluation_config_json jsonb not null default '{}'::jsonb;

alter table if exists test_runs
    add column if not exists final_state_json jsonb not null default '{}'::jsonb,
    add column if not exists metrics_json jsonb not null default '{}'::jsonb;

create index if not exists idx_test_runs_agent on test_runs(agent_id);
create index if not exists idx_test_runs_started_at on test_runs(started_at);
