-- ========================================================
-- Choranta Internal Operating System — Phase 3A Schema
-- Voice Runtime Foundation: Sessions, Events, and Usage
-- Target Database: Supabase PostgreSQL
-- ========================================================

-- 1. RUNTIME SESSIONS
CREATE TABLE IF NOT EXISTS runtime_sessions (
    id VARCHAR(64) PRIMARY KEY, -- ses_xxxxxxxx
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    agent_version_id VARCHAR(64) NOT NULL REFERENCES agent_versions(id) ON DELETE RESTRICT,
    status VARCHAR(32) NOT NULL DEFAULT 'CREATED', -- CREATED, INITIALIZING, ACTIVE, ENDING, COMPLETED, FAILED
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    usage_json JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast session queries
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_agent_id ON runtime_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_client_id ON runtime_sessions(client_id);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_agent_version_id ON runtime_sessions(agent_version_id);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_status ON runtime_sessions(status);
CREATE INDEX IF NOT EXISTS idx_runtime_sessions_started_at ON runtime_sessions(started_at);

-- 2. RUNTIME EVENTS (Immutable session timeline events)
CREATE TABLE IF NOT EXISTS runtime_events (
    id VARCHAR(64) PRIMARY KEY, -- evt_xxxxxxxx
    session_id VARCHAR(64) NOT NULL REFERENCES runtime_sessions(id) ON DELETE CASCADE,
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    agent_version_id VARCHAR(64) NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    payload_json JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for timeline retrieval
CREATE INDEX IF NOT EXISTS idx_runtime_events_session_id ON runtime_events(session_id);
CREATE INDEX IF NOT EXISTS idx_runtime_events_event_type ON runtime_events(event_type);
CREATE INDEX IF NOT EXISTS idx_runtime_events_timestamp ON runtime_events(timestamp);























































































































