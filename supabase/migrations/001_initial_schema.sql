-- ========================================================
-- Choranta Internal Operating System — Phase 1 Schema
-- Target Database: Supabase PostgreSQL
-- ========================================================

-- Custom enum types for PostgreSQL
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('ADMIN', 'OPERATOR');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'client_business_type') THEN
        CREATE TYPE client_business_type AS ENUM (
            'CLINIC', 'HOSPITAL', 'SALON', 'REAL_ESTATE', 
            'HOTEL', 'RESTAURANT', 'CORPORATE', 'OTHER'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'client_status') THEN
        CREATE TYPE client_status AS ENUM ('ACTIVE', 'INACTIVE');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agent_status') THEN
        CREATE TYPE agent_status AS ENUM (
            'DRAFT', 'TESTING', 'READY', 'DEPLOYED', 'PAUSED', 'ARCHIVED'
        );
    END IF;
END$$;

-- 1. USERS (Internal Operators and Administrators)
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255),
    role VARCHAR(32) NOT NULL DEFAULT 'OPERATOR',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

-- 2. CLIENTS (Enterprise accounts)
CREATE TABLE IF NOT EXISTS clients (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    business_type VARCHAR(64) NOT NULL,
    description TEXT,
    contact_name VARCHAR(255),
    contact_email VARCHAR(255),
    contact_phone VARCHAR(64),
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status);
CREATE INDEX IF NOT EXISTS idx_clients_business_type ON clients(business_type);

-- 3. AGENTS (AI Voice Employees)
CREATE TABLE IF NOT EXISTS agents (
    id VARCHAR(64) PRIMARY KEY, -- Prefix format: agt_xxxxxxxx
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_client_id ON agents(client_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

-- 4. AGENT VERSIONS (Immutable Configuration Snapshots)
CREATE TABLE IF NOT EXISTS agent_versions (
    id VARCHAR(64) PRIMARY KEY, -- Prefix format: agtv_xxxxxxxx
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    configuration_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT uq_agent_version_number UNIQUE(agent_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_agent_versions_agent_id ON agent_versions(agent_id);

-- Enforce strict immutability on agent_versions at the database level
CREATE OR REPLACE FUNCTION prevent_agent_version_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'agent_versions table is strictly append-only. Existing versions cannot be updated or mutated.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_agent_version_update ON agent_versions;
CREATE TRIGGER trg_prevent_agent_version_update
BEFORE UPDATE ON agent_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_agent_version_update();

-- Enable Row Level Security (RLS) on all tables for Supabase PostgreSQL
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_versions ENABLE ROW LEVEL SECURITY;

-- Allow internal service role / backend access
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_users') THEN
        CREATE POLICY service_role_all_users ON users FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_clients') THEN
        CREATE POLICY service_role_all_clients ON clients FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_agents') THEN
        CREATE POLICY service_role_all_agents ON agents FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_versions') THEN
        CREATE POLICY service_role_all_versions ON agent_versions FOR ALL USING (true);
    END IF;
END$$;
