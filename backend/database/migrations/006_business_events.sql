-- Migration 006: Business Events Layer
-- Adds the BusinessEvent object model, transactions table, and account enhancements.
-- This is the foundation that connects every real-world action to the double-entry ledger.
--
-- Author: Matthew Jenkins
-- Date: 2026-04-10

PRAGMA foreign_keys = ON;

-- =================================================================
-- NEW TABLE: business_events — The core event object
-- Every real-world action (purchase, sale, transfer) is a BusinessEvent.
-- =================================================================
CREATE TABLE IF NOT EXISTS business_events (
    event_id        TEXT PRIMARY KEY,                   -- UUID
    user_id         INTEGER NOT NULL,
    event_type      TEXT NOT NULL,                      -- 'inventory_purchase', 'inventory_sale', etc.
    parent_event_id TEXT,                               -- FK to self for composition (batch -> items)
    entity_type     TEXT,                               -- 'project', 'part', 'part_set'
    entity_id       INTEGER,                            -- FK to the relevant entity
    event_date      TEXT NOT NULL,                      -- Business date (YYYY-MM-DD)
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft','pending','posted','reconciled','void')),
    source          TEXT NOT NULL DEFAULT 'manual',     -- 'manual', 'auto', 'import'
    metadata        TEXT,                               -- JSON blob for type-specific data
    notes           TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    created_by      INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_event_id) REFERENCES business_events(event_id),
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_events_user_id ON business_events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON business_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_status ON business_events(status);
CREATE INDEX IF NOT EXISTS idx_events_entity ON business_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_events_parent ON business_events(parent_event_id);
CREATE INDEX IF NOT EXISTS idx_events_date ON business_events(user_id, event_date DESC);

-- =================================================================
-- NEW TABLE: transactions — Journal entry grouping
-- Links a business event to its balanced set of ledger entries.
-- =================================================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_uuid TEXT UNIQUE NOT NULL,              -- External-facing stable ID
    event_id         TEXT NOT NULL,                     -- FK to business_events
    user_id          INTEGER NOT NULL,
    transaction_date TEXT NOT NULL,
    description      TEXT,
    is_posted        INTEGER NOT NULL DEFAULT 0,        -- 0 = staging, 1 = in the books
    is_reversal      INTEGER NOT NULL DEFAULT 0,
    reversal_of      TEXT,                              -- UUID of reversed transaction
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES business_events(event_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transactions_event ON transactions(event_id);
CREATE INDEX IF NOT EXISTS idx_transactions_uuid ON transactions(transaction_uuid);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, transaction_date DESC);

-- =================================================================
-- ALTER: accounts — Add fields from platform architecture spec
-- =================================================================
ALTER TABLE accounts ADD COLUMN account_number TEXT;
ALTER TABLE accounts ADD COLUMN normal_balance TEXT CHECK(normal_balance IN ('DEBIT','CREDIT'));
ALTER TABLE accounts ADD COLUMN parent_id INTEGER REFERENCES accounts(account_id);
ALTER TABLE accounts ADD COLUMN is_contra INTEGER DEFAULT 0;

-- Backfill normal_balance from account_type (deterministic mapping)
UPDATE accounts SET normal_balance = 'DEBIT' WHERE account_type IN ('ASSET', 'EXPENSE');
UPDATE accounts SET normal_balance = 'CREDIT' WHERE account_type IN ('LIABILITY', 'EQUITY', 'REVENUE');

-- =================================================================
-- ALTER: financial_ledger — Add FK to transactions table
-- =================================================================
ALTER TABLE financial_ledger ADD COLUMN transaction_id INTEGER REFERENCES transactions(transaction_id);

CREATE INDEX IF NOT EXISTS idx_ledger_transaction_id ON financial_ledger(transaction_id);

-- =================================================================
-- REBUILD VIEW: v_account_balances — Now normal_balance-aware
-- Positive balance = amount in the account's normal direction
-- =================================================================
DROP VIEW IF EXISTS v_account_balances;
CREATE VIEW v_account_balances AS
SELECT
    a.account_id,
    a.user_id,
    a.account_name,
    a.account_number,
    a.account_type,
    a.subtype,
    a.normal_balance,
    COALESCE(SUM(l.debit), 0) AS total_debits,
    COALESCE(SUM(l.credit), 0) AS total_credits,
    CASE
        WHEN a.normal_balance = 'DEBIT'
        THEN COALESCE(SUM(l.debit), 0) - COALESCE(SUM(l.credit), 0)
        ELSE COALESCE(SUM(l.credit), 0) - COALESCE(SUM(l.debit), 0)
    END AS balance
FROM accounts a
LEFT JOIN financial_ledger l ON a.account_id = l.account_id
WHERE a.is_deleted = 0 AND a.is_active = 1
GROUP BY a.account_id, a.user_id, a.account_name, a.account_number,
         a.account_type, a.subtype, a.normal_balance;

-- =================================================================
-- Schema version
-- =================================================================
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (6, 'Business events layer, transactions table, account enhancements');
