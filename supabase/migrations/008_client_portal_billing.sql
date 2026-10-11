-- Client portal logins, prepaid wallets, ledger, billing profiles and GST invoices
CREATE TABLE IF NOT EXISTS client_users (
    user_id VARCHAR(64) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_client_users_client_id ON client_users (client_id);

CREATE TABLE IF NOT EXISTS client_wallets (
    client_id VARCHAR(64) PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
    balance_inr DOUBLE PRECISION NOT NULL DEFAULT 0,
    low_balance_threshold_inr DOUBLE PRECISION NOT NULL DEFAULT 500,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    type VARCHAR(16) NOT NULL,
    amount_inr DOUBLE PRECISION NOT NULL,
    balance_after_inr DOUBLE PRECISION NOT NULL,
    call_id VARCHAR(64) UNIQUE,
    invoice_id VARCHAR(64),
    reference VARCHAR(255),
    note TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_wallet_transactions_client_id ON wallet_transactions (client_id);

CREATE TABLE IF NOT EXISTS client_billing_profiles (
    client_id VARCHAR(64) PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
    legal_name VARCHAR(255) NOT NULL,
    gstin VARCHAR(15),
    address TEXT,
    state_code VARCHAR(2),
    billing_email VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoices (
    id VARCHAR(64) PRIMARY KEY,
    number VARCHAR(32) NOT NULL UNIQUE,
    client_id VARCHAR(64) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    issue_date DATE NOT NULL,
    financial_year VARCHAR(7) NOT NULL,
    sequence DOUBLE PRECISION NOT NULL,
    taxable_inr DOUBLE PRECISION NOT NULL,
    cgst_inr DOUBLE PRECISION NOT NULL DEFAULT 0,
    sgst_inr DOUBLE PRECISION NOT NULL DEFAULT 0,
    igst_inr DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_inr DOUBLE PRECISION NOT NULL,
    place_of_supply VARCHAR(2),
    payment_reference VARCHAR(255),
    transaction_id VARCHAR(64),
    bill_to TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_invoices_client_id ON invoices (client_id);
