-- Migration 002: Keyboard Support (Phase 1.0)
-- Adds support for keyboard inventory tracking with flexible attributes
--
-- Changes:
-- 1. project_parts: make project_id nullable, add subsection_id, for_sale, metadata
-- 2. projects: expand status CHECK to include keyboard lifecycle statuses

PRAGMA foreign_keys = OFF;

-- =================================================================
-- STEP 0: Drop existing views that reference tables we're modifying
-- =================================================================
DROP VIEW IF EXISTS v_project_summary;
DROP VIEW IF EXISTS v_loose_inventory;

-- =================================================================
-- STEP 1: Recreate project_parts with nullable project_id and new columns
-- =================================================================

-- Create new table with updated schema
CREATE TABLE project_parts_new (
    part_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,                          -- NOW NULLABLE for loose inventory
    subsection_id INTEGER,                       -- Required when project_id is NULL
    catalog_id INTEGER,
    set_id TEXT,
    custom_name TEXT,
    serial_number TEXT,
    condition TEXT,
    weight_class TEXT CHECK(weight_class IN ('light', 'medium', 'heavy')) DEFAULT 'medium',
    estimated_value REAL,
    actual_sale_price REAL,
    shipping_paid REAL,
    fees_paid REAL,
    status TEXT CHECK(status IN ('IN_SYSTEM', 'LISTED', 'SOLD', 'KEPT', 'TRASHED', 'IN_PROJECT', 'ALLOCATED')) DEFAULT 'IN_SYSTEM',
    listing_url TEXT,
    sold_date TEXT,
    for_sale INTEGER DEFAULT 0,                  -- NEW: Is this part available for sale?
    metadata TEXT,                               -- NEW: JSON for flexible attributes (hot_swap, lubed, etc.)
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
    FOREIGN KEY (subsection_id) REFERENCES subsections(subsection_id) ON DELETE CASCADE,
    FOREIGN KEY (catalog_id) REFERENCES parts_catalog(catalog_id) ON DELETE SET NULL
);

-- Copy data from old table, deriving subsection_id from project
INSERT INTO project_parts_new (
    part_id, project_id, subsection_id, catalog_id, set_id, custom_name,
    serial_number, condition, weight_class, estimated_value, actual_sale_price,
    shipping_paid, fees_paid, status, listing_url, sold_date, for_sale, metadata, notes, created_at
)
SELECT
    pp.part_id, pp.project_id, p.subsection_id, pp.catalog_id, pp.set_id, pp.custom_name,
    pp.serial_number, pp.condition, pp.weight_class, pp.estimated_value, pp.actual_sale_price,
    pp.shipping_paid, pp.fees_paid, pp.status, pp.listing_url, pp.sold_date, 0, NULL, pp.notes, pp.created_at
FROM project_parts pp
JOIN projects p ON pp.project_id = p.project_id;

-- Drop old table and rename new one
DROP TABLE project_parts;
ALTER TABLE project_parts_new RENAME TO project_parts;

-- Recreate indexes
CREATE INDEX idx_project_parts_project_id ON project_parts(project_id);
CREATE INDEX idx_project_parts_subsection_id ON project_parts(subsection_id);
CREATE INDEX idx_project_parts_catalog_id ON project_parts(catalog_id);
CREATE INDEX idx_project_parts_set_id ON project_parts(set_id);
CREATE INDEX idx_project_parts_status ON project_parts(status);
CREATE INDEX idx_project_parts_for_sale ON project_parts(for_sale);

-- =================================================================
-- STEP 2: Recreate projects with expanded status CHECK
-- =================================================================

-- Create new table with expanded statuses
CREATE TABLE projects_new (
    project_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subsection_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    acquisition_cost REAL,
    acquisition_date TEXT,
    acquisition_source TEXT,
    -- Expanded status: CCS workflow + Keyboard workflow
    status TEXT CHECK(status IN (
        -- CCS workflow (PC flipping)
        'ACQUIRED', 'PARTING', 'LISTED', 'SOLD', 'COMPLETE',
        -- Keyboard workflow
        'PLANNED', 'IN_PROGRESS', 'ASSEMBLED', 'DEPLOYED', 'DISASSEMBLED'
    )) DEFAULT 'ACQUIRED',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (subsection_id) REFERENCES subsections(subsection_id) ON DELETE CASCADE
);

-- Copy data from old table
INSERT INTO projects_new (
    project_id, user_id, subsection_id, name, description, acquisition_cost,
    acquisition_date, acquisition_source, status, notes, created_at
)
SELECT
    project_id, user_id, subsection_id, name, description, acquisition_cost,
    acquisition_date, acquisition_source, status, notes, created_at
FROM projects;

-- Drop old table and rename new one
DROP TABLE projects;
ALTER TABLE projects_new RENAME TO projects;

-- Recreate indexes
CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_projects_subsection_id ON projects(subsection_id);
CREATE INDEX idx_projects_status ON projects(status);

-- =================================================================
-- STEP 3: Recreate views that reference these tables
-- =================================================================

CREATE VIEW v_project_summary AS
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
-- STEP 4: Create view for loose inventory (parts without projects)
-- =================================================================

CREATE VIEW IF NOT EXISTS v_loose_inventory AS
SELECT
    pp.part_id,
    pp.subsection_id,
    s.name AS subsection_name,
    pp.catalog_id,
    pc.name AS catalog_name,
    pc.category AS catalog_category,
    pp.custom_name,
    COALESCE(pc.name, pp.custom_name) AS display_name,
    pp.condition,
    pp.weight_class,
    pp.estimated_value,
    pp.for_sale,
    pp.metadata,
    pp.status,
    pp.notes,
    pp.created_at
FROM project_parts pp
LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
WHERE pp.project_id IS NULL;

PRAGMA foreign_keys = ON;

-- Record migration
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (2, 'Keyboard support - nullable project_id, for_sale, metadata fields');
