-- ========================================================
-- Choranta Internal Operating System — Phase 2 Schema
-- Agent Configuration Engine, Knowledge, Tools & Integrations
-- Target Database: Supabase PostgreSQL
-- ========================================================

-- 1. AGENT CONFIGURATIONS (Draft / In-Progress Configuration)
CREATE TABLE IF NOT EXISTS agent_configurations (
    id VARCHAR(64) PRIMARY KEY, -- cfg_xxxxxxxx
    agent_id VARCHAR(64) NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    configuration_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_configurations_agent_id ON agent_configurations(agent_id);

-- 2. KNOWLEDGE SOURCES (Reference catalog)
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id VARCHAR(64) PRIMARY KEY, -- knw_xxxxxxxx
    name VARCHAR(255) NOT NULL,
    type VARCHAR(32) NOT NULL, -- PDF, TEXT, WEBSITE, FAQ
    status VARCHAR(32) NOT NULL DEFAULT 'READY', -- READY, PROCESSING, ARCHIVED
    description TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_sources_type ON knowledge_sources(type);

-- Agent to Knowledge Sources junction
CREATE TABLE IF NOT EXISTS agent_knowledge_sources (
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    knowledge_source_id VARCHAR(64) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, knowledge_source_id)
);

-- 3. TOOLS (Tool capability catalog)
CREATE TABLE IF NOT EXISTS tools (
    id VARCHAR(64) PRIMARY KEY, -- check_availability, book_appointment, etc.
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    executor_type VARCHAR(64) NOT NULL DEFAULT 'SYSTEM', -- SYSTEM, WEBHOOK, CALENDAR
    timeout INTEGER NOT NULL DEFAULT 30,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent to Tools junction
CREATE TABLE IF NOT EXISTS agent_tools (
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    tool_id VARCHAR(64) NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, tool_id)
);

-- 4. INTEGRATIONS (Integration capability catalog)
CREATE TABLE IF NOT EXISTS integrations (
    id VARCHAR(64) PRIMARY KEY, -- int_xxxxxxxx or slug
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(64) NOT NULL, -- CALENDAR, CRM, WEBHOOK, MESSAGING, EMAIL
    provider VARCHAR(64) NOT NULL, -- GOOGLE, HUBSPOT, SALESFORCE, CUSTOM, TWILIO, SENDGRID
    connection_status VARCHAR(32) NOT NULL DEFAULT 'CONFIGURED', -- CONFIGURED, DISCONNECTED
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent to Integrations junction
CREATE TABLE IF NOT EXISTS agent_integrations (
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    integration_id VARCHAR(64) NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, integration_id)
);

-- Enable RLS for all new tables
ALTER TABLE agent_configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_knowledge_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE tools ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tools ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_integrations ENABLE ROW LEVEL SECURITY;

-- Allow internal service role / backend access
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_agent_configurations') THEN
        CREATE POLICY service_role_all_agent_configurations ON agent_configurations FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_knowledge_sources') THEN
        CREATE POLICY service_role_all_knowledge_sources ON knowledge_sources FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_agent_knowledge_sources') THEN
        CREATE POLICY service_role_all_agent_knowledge_sources ON agent_knowledge_sources FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_tools') THEN
        CREATE POLICY service_role_all_tools ON tools FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_agent_tools') THEN
        CREATE POLICY service_role_all_agent_tools ON agent_tools FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_integrations') THEN
        CREATE POLICY service_role_all_integrations ON integrations FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'service_role_all_agent_integrations') THEN
        CREATE POLICY service_role_all_agent_integrations ON agent_integrations FOR ALL USING (true);
    END IF;
END$$;




