-- Artifact Live v2 - Database Schema
-- Built from Digital Harvest v5 foundation, stripped of game mechanics
-- Author: Matthew Jenkins
-- Date: 2026-01-19

-- Enable foreign key constraints (CRITICAL for data integrity)
PRAGMA foreign_keys = ON;

-- =================================================================
-- TABLE 1: users - User authentication
-- =================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- TABLE 2: businesses - Multi-business support
-- =================================================================
CREATE TABLE IF NOT EXISTS businesses (
    business_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,                          -- 'Computer Chop Shop', 'Family Electric', etc.
    business_type TEXT,                          -- 'reseller', 'service', 'inventory_only'
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_businesses_user_id ON businesses(user_id);

-- =================================================================
-- TABLE 3: subsections - Subsections within a business
-- =================================================================
CREATE TABLE IF NOT EXISTS subsections (
    subsection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER,                         -- NULL for personal inventory (keyboards, electronics)
    name TEXT NOT NULL,                          -- 'Computer Chop Shop', 'Keyboards', 'Electronics'
    description TEXT,
    is_business INTEGER DEFAULT 0,               -- 1 = real business operations, 0 = inventory tracking only
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(business_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_subsections_business_id ON subsections(business_id);

-- =================================================================
-- TABLE 4: projects - Systems/Builds/Acquisitions (flips)
-- =================================================================
CREATE TABLE IF NOT EXISTS projects (
    project_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subsection_id INTEGER NOT NULL,
    name TEXT NOT NULL,                          -- 'Dell OptiPlex 7050', 'Keychron Q1 Build', etc.
    description TEXT,
    acquisition_cost REAL,                       -- What you paid for the whole thing
    acquisition_date TEXT,
    acquisition_source TEXT,                     -- 'eBay', 'Facebook Marketplace', 'Estate Sale', etc.
    status TEXT CHECK(status IN ('ACQUIRED', 'PARTING', 'LISTED', 'SOLD', 'COMPLETE')) DEFAULT 'ACQUIRED',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (subsection_id) REFERENCES subsections(subsection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_subsection_id ON projects(subsection_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- =================================================================
-- TABLE 5: parts_catalog - Generic Parts Library
-- =================================================================
CREATE TABLE IF NOT EXISTS parts_catalog (
    catalog_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subsection_id INTEGER NOT NULL,
    category TEXT NOT NULL,                      -- 'GPU', 'CPU', 'RAM', 'Switch', 'Keycap', 'Resistor'
    name TEXT NOT NULL,                          -- 'NVIDIA GTX 1080', 'Cherry MX Red', '10k Ohm Resistor'
    sku TEXT,                                    -- Optional internal SKU
    default_price REAL,                          -- Optional reference price
    weight_class TEXT CHECK(weight_class IN ('light', 'medium', 'heavy')),
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subsection_id) REFERENCES subsections(subsection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_parts_catalog_subsection_id ON parts_catalog(subsection_id);
CREATE INDEX IF NOT EXISTS idx_parts_catalog_category ON parts_catalog(category);

-- =================================================================
-- TABLE 6: project_parts - Individual Parts Within Projects
-- IMPORTANT: Each physical part gets its own row
-- set_id groups parts sold together (e.g., RAM kit sold as pair)
-- =================================================================
CREATE TABLE IF NOT EXISTS project_parts (
    part_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    catalog_id INTEGER,                          -- NULL if ad-hoc part not in catalog
    set_id TEXT,                                 -- UUID to group parts sold together
    custom_name TEXT,                            -- Used when catalog_id is NULL
    serial_number TEXT,                          -- Optional for valuable parts
    condition TEXT,                              -- 'New', 'Used-Like New', 'Used-Good', 'For Parts'
    weight_class TEXT CHECK(weight_class IN ('light', 'medium', 'heavy')) DEFAULT 'medium',
    estimated_value REAL,                        -- Manual price estimate
    actual_sale_price REAL,                      -- What it actually sold for
    shipping_paid REAL,                          -- Actual shipping cost when sold
    fees_paid REAL,                              -- Actual fees when sold
    status TEXT CHECK(status IN ('IN_SYSTEM', 'LISTED', 'SOLD', 'KEPT', 'TRASHED', 'IN_PROJECT')) DEFAULT 'IN_SYSTEM',
    listing_url TEXT,                            -- eBay/marketplace link
    sold_date TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (catalog_id) REFERENCES parts_catalog(catalog_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_project_parts_project_id ON project_parts(project_id);
CREATE INDEX IF NOT EXISTS idx_project_parts_catalog_id ON project_parts(catalog_id);
CREATE INDEX IF NOT EXISTS idx_project_parts_set_id ON project_parts(set_id);
CREATE INDEX IF NOT EXISTS idx_project_parts_status ON project_parts(status);

-- =================================================================
-- TABLE 7: shipping_supplies - Track boxes, tape, bubble wrap, etc.
-- =================================================================
CREATE TABLE IF NOT EXISTS shipping_supplies (
    supply_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,                          -- '12x12x8 Box', 'Bubble Wrap Roll', '2" Packing Tape'
    category TEXT,                               -- 'box', 'padding', 'tape', 'label'
    quantity INTEGER DEFAULT 0,
    unit_cost REAL,                              -- Cost per unit
    reorder_point INTEGER,                       -- Alert when below this
    notes TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shipping_supplies_user_id ON shipping_supplies(user_id);

-- =================================================================
-- TABLE 8: pricing_config - User's fee rates and shipping estimates
-- =================================================================
CREATE TABLE IF NOT EXISTS pricing_config (
    config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    config_key TEXT NOT NULL,                    -- 'ebay_final_value_fee', 'ebay_payment_processing', etc.
    config_value REAL NOT NULL,                  -- The rate/value
    description TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, config_key)
);
CREATE INDEX IF NOT EXISTS idx_pricing_config_user_id ON pricing_config(user_id);

-- =================================================================
-- TABLE 9: accounts - Chart of accounts for double-entry ledger
-- (From Digital Harvest/Perfect Books foundation)
-- =================================================================
CREATE TABLE IF NOT EXISTS accounts (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT CHECK(account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')) NOT NULL,
    subtype TEXT,                                -- 'INVENTORY', 'CASH', 'COGS', 'SALES', etc.
    is_system INTEGER DEFAULT 0,                 -- System-generated accounts
    is_active INTEGER DEFAULT 1,
    is_deleted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, account_name)
);
CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(account_type);

-- =================================================================
-- TABLE 10: financial_ledger - Double-entry accounting ledger (immutable)
-- (From Digital Harvest/Perfect Books foundation)
-- =================================================================
CREATE TABLE IF NOT EXISTS financial_ledger (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    transaction_uuid TEXT NOT NULL,              -- Groups related entries
    transaction_date TEXT NOT NULL,
    description TEXT,
    debit REAL DEFAULT 0.00,
    credit REAL DEFAULT 0.00,
    reference_type TEXT,                         -- 'PURCHASE', 'SALE', 'ADJUSTMENT', 'REVERSAL', 'PROJECT'
    reference_id INTEGER,                        -- Link to source record (project_id, part_id, etc.)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);
CREATE INDEX IF NOT EXISTS idx_ledger_user_date ON financial_ledger(user_id, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_transaction_uuid ON financial_ledger(transaction_uuid);
CREATE INDEX IF NOT EXISTS idx_ledger_account_id ON financial_ledger(account_id);
CREATE INDEX IF NOT EXISTS idx_ledger_reference ON financial_ledger(reference_type, reference_id);

-- =================================================================
-- TABLE 11: inventory_layers - FIFO cost tracking
-- (From Digital Harvest foundation)
-- =================================================================
CREATE TABLE IF NOT EXISTS inventory_layers (
    layer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    part_id INTEGER NOT NULL,                    -- References project_parts
    quantity_received REAL NOT NULL,
    quantity_remaining REAL NOT NULL,
    unit_cost REAL NOT NULL,
    received_date TEXT NOT NULL,
    reference_type TEXT,                         -- 'PROJECT_PART', 'PURCHASE_ORDER', 'ADJUSTMENT'
    reference_id INTEGER,                        -- Link to source record
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (part_id) REFERENCES project_parts(part_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory_layers(user_id);
CREATE INDEX IF NOT EXISTS idx_inventory_part ON inventory_layers(part_id);
CREATE INDEX IF NOT EXISTS idx_inventory_received ON inventory_layers(received_date);

-- =================================================================
-- TABLE 12: expense_categories - User-defined expense categorization
-- (From Perfect Books foundation)
-- =================================================================
CREATE TABLE IF NOT EXISTS expense_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#6366f1',
    is_default INTEGER DEFAULT 0,
    is_monthly INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_expense_categories_user_id ON expense_categories(user_id);

-- =================================================================
-- TABLE 13: schema_version - Migration tracking
-- =================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- VIEWS
-- =================================================================

-- View: Account Balances
CREATE VIEW IF NOT EXISTS v_account_balances AS
SELECT
    a.account_id,
    a.user_id,
    a.account_name,
    a.account_type,
    a.subtype,
    COALESCE(SUM(l.debit), 0) - COALESCE(SUM(l.credit), 0) AS balance
FROM accounts a
LEFT JOIN financial_ledger l ON a.account_id = l.account_id
WHERE a.is_deleted = 0 AND a.is_active = 1
GROUP BY a.account_id, a.user_id, a.account_name, a.account_type, a.subtype;

-- View: Project Summary
CREATE VIEW IF NOT EXISTS v_project_summary AS
SELECT
    p.project_id,
    p.user_id,
    p.name,
    p.acquisition_cost,
    p.status,
    COUNT(pp.part_id) AS total_parts,
    COUNT(CASE WHEN pp.status IN ('IN_SYSTEM', 'LISTED') THEN 1 END) AS parts_for_sale,
    COUNT(CASE WHEN pp.status = 'SOLD' THEN 1 END) AS parts_sold,
    COALESCE(SUM(pp.estimated_value), 0) AS total_estimated_value,
    COALESCE(SUM(pp.actual_sale_price), 0) AS total_actual_revenue,
    COALESCE(SUM(pp.fees_paid), 0) AS total_fees_paid,
    COALESCE(SUM(pp.shipping_paid), 0) AS total_shipping_paid
FROM projects p
LEFT JOIN project_parts pp ON p.project_id = pp.project_id
GROUP BY p.project_id, p.user_id, p.name, p.acquisition_cost, p.status;

-- =================================================================
-- SEED DATA - Initial schema version
-- =================================================================
INSERT OR IGNORE INTO schema_version (version, description) VALUES (1, 'Initial Artifact Live v2 schema');
