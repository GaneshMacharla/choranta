-- Admin-editable pricing: profit margin and infrastructure overhead used to price calls
CREATE TABLE IF NOT EXISTS pricing_settings (
    id VARCHAR(32) PRIMARY KEY DEFAULT 'default',
    profit_percent DOUBLE PRECISION NOT NULL,
    infra_cost_per_minute_inr DOUBLE PRECISION NOT NULL,
    updated_by VARCHAR(64),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
