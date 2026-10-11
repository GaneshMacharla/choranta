-- Persistent deterministic voice-agent test scenarios and run traces.
-- These records are test artifacts and must not be included in production billing.

create table if not exists test_scenarios (
    id text primary key,
    client_id text not null references clients(id) on delete cascade,
    agent_id text not null references agents(id) on delete cascade,
    agent_version_id text not null references agent_versions(id) on delete restrict,
    name text not null,
    description text,
    caller_goal text not null default '',
    turns_json jsonb not null default '[]'::jsonb,
    expected_json jsonb not null default '{}'::jsonb,
    provider_config_json jsonb not null default '{}'::jsonb,
    max_turns integer not null default 10,
    timeout_seconds integer not null default 120,
    version_number integer not null default 1,
    status text not null default 'ACTIVE',
    created_by text references users(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_test_scenarios_client on test_scenarios(client_id);
create index if not exists idx_test_scenarios_agent on test_scenarios(agent_id);

create table if not exists test_runs (
    id text primary key,
    scenario_id text not null references test_scenarios(id) on delete cascade,
    client_id text not null references clients(id) on delete cascade,
    agent_id text not null references agents(id) on delete cascade,
    agent_version_id text not null references agent_versions(id) on delete restrict,
    runtime_session_id text references runtime_sessions(id) on delete set null,
    status text not null default 'RUNNING',
    provider_mode text not null default 'mock',
    scenario_version integer not null default 1,
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    duration_ms integer,
    turn_count integer not null default 0,
    summary_json jsonb not null default '{}'::jsonb,
    usage_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_test_runs_scenario on test_runs(scenario_id);
create index if not exists idx_test_runs_client on test_runs(client_id);
create index if not exists idx_test_runs_status on test_runs(status);

create table if not exists test_run_events (
    id text primary key,
    run_id text not null references test_runs(id) on delete cascade,
    session_id text,
    event_type text not null,
    timestamp timestamptz not null default now(),
    duration_ms integer,
    metadata_json jsonb not null default '{}'::jsonb
);

create index if not exists idx_test_run_events_run on test_run_events(run_id, timestamp);
create index if not exists idx_test_run_events_type on test_run_events(event_type);
