-- Where each client maintains its property inventory (Google Sheet / API), synced into properties
CREATE TABLE IF NOT EXISTS inventory_sources (
    id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(32) NOT NULL,
    config JSON NOT NULL DEFAULT '{}',
    field_mapping JSON NOT NULL DEFAULT '{}',
    sync_interval_minutes INTEGER NOT NULL DEFAULT 15,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMP,
    last_status VARCHAR(16),
    last_error TEXT,
    last_result JSON NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_inventory_sources_client_id ON inventory_sources (client_id);
