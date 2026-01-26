-- Migration 005: Add STAGED status for Plan Mode (Phase 1.3)
-- Adds STAGED status to project_parts for "plan a build" functionality
--
-- Changes:
-- 1. project_parts: Add STAGED to status CHECK constraint

PRAGMA foreign_keys = OFF;

-- =================================================================
-- STEP 1: Recreate project_parts with updated status CHECK
-- =================================================================

CREATE TABLE project_parts_new (
    part_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    subsection_id INTEGER,
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
    -- Added STAGED for plan/stage mode
    status TEXT CHECK(status IN ('IN_SYSTEM', 'LISTED', 'SOLD', 'KEPT', 'TRASHED', 'IN_PROJECT', 'ALLOCATED', 'STAGED')) DEFAULT 'IN_SYSTEM',
    listing_url TEXT,
    sold_date TEXT,
    for_sale INTEGER DEFAULT 0,
    quantity INTEGER DEFAULT 1,
    is_mystery INTEGER DEFAULT 0,
    metadata TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
    FOREIGN KEY (subsection_id) REFERENCES subsections(subsection_id) ON DELETE CASCADE,
    FOREIGN KEY (catalog_id) REFERENCES parts_catalog(catalog_id) ON DELETE SET NULL
);

-- Copy data from old table
INSERT INTO project_parts_new SELECT * FROM project_parts;

-- Drop old table and rename
DROP TABLE project_parts;
ALTER TABLE project_parts_new RENAME TO project_parts;

-- Recreate indexes
CREATE INDEX idx_project_parts_project_id ON project_parts(project_id);
CREATE INDEX idx_project_parts_subsection_id ON project_parts(subsection_id);
CREATE INDEX idx_project_parts_catalog_id ON project_parts(catalog_id);
CREATE INDEX idx_project_parts_set_id ON project_parts(set_id);
CREATE INDEX idx_project_parts_status ON project_parts(status);
CREATE INDEX idx_project_parts_for_sale ON project_parts(for_sale);
CREATE INDEX idx_project_parts_is_mystery ON project_parts(is_mystery);

PRAGMA foreign_keys = ON;

-- Record migration
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (5, 'Add STAGED status for plan/stage mode');
