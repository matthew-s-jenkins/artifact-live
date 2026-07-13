-- Migration 008: Phase 3 — Materials, POs, Multi-Dependency
-- Adds tables for material tracking, purchase orders, inventory,
-- and a junction table for multi-predecessor phase dependencies.
--
-- Author: Matthew Jenkins
-- Date: 2026-04-10

PRAGMA foreign_keys = ON;

-- =================================================================
-- TABLE: sim_phase_dependencies — Multi-predecessor junction table
-- Allows a phase to depend on multiple predecessors.
-- E.g., Drywall depends on Electrical + Plumbing + HVAC.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_phase_dependencies (
    dependency_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id             INTEGER NOT NULL,     -- the phase that is blocked
    depends_on_template_id  INTEGER NOT NULL,     -- the phase it waits for
    FOREIGN KEY (template_id) REFERENCES sim_phase_templates(template_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_template_id) REFERENCES sim_phase_templates(template_id) ON DELETE CASCADE,
    UNIQUE(template_id, depends_on_template_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_phase_deps_tmpl ON sim_phase_dependencies(template_id);
CREATE INDEX IF NOT EXISTS idx_sim_phase_deps_dep ON sim_phase_dependencies(depends_on_template_id);

-- =================================================================
-- TABLE: sim_materials — Material types catalog per development
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_materials (
    material_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id  INTEGER NOT NULL,
    name            TEXT NOT NULL,               -- 'Lumber', 'Concrete Mix', 'Copper Wire'
    unit            TEXT NOT NULL DEFAULT 'unit', -- 'board_ft', 'cubic_yd', 'roll', 'sheet'
    unit_cost       REAL NOT NULL,
    lead_time_days  INTEGER NOT NULL DEFAULT 2,  -- delivery delay after PO placed
    vendor_name     TEXT,
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_materials_dev ON sim_materials(development_id);

-- =================================================================
-- TABLE: sim_phase_materials — Materials required per phase template
-- Links phase templates to their material requirements.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_phase_materials (
    phase_material_id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id       INTEGER NOT NULL,
    material_id       INTEGER NOT NULL,
    quantity          REAL NOT NULL,
    FOREIGN KEY (template_id) REFERENCES sim_phase_templates(template_id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES sim_materials(material_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_phase_mat_tmpl ON sim_phase_materials(template_id);
CREATE INDEX IF NOT EXISTS idx_sim_phase_mat_mat ON sim_phase_materials(material_id);

-- =================================================================
-- TABLE: sim_purchase_orders — POs for material procurement
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_purchase_orders (
    po_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id   INTEGER NOT NULL,
    vendor_name      TEXT,
    order_day        INTEGER NOT NULL,           -- sim day PO was placed
    delivery_day     INTEGER NOT NULL,           -- sim day materials arrive
    status           TEXT NOT NULL DEFAULT 'ordered'
                     CHECK(status IN ('ordered','delivered','paid')),
    total_cost       REAL NOT NULL DEFAULT 0,
    event_id         TEXT,                       -- FK to business_events (inventory_receipt on delivery)
    payment_event_id TEXT,                       -- FK to business_events (vendor_payment)
    payment_due_day  INTEGER,                    -- sim day payment is due (delivery + net terms)
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_po_dev ON sim_purchase_orders(development_id);
CREATE INDEX IF NOT EXISTS idx_sim_po_status ON sim_purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_sim_po_delivery ON sim_purchase_orders(delivery_day);

-- =================================================================
-- TABLE: sim_po_lines — Line items on purchase orders
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_po_lines (
    po_line_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id            INTEGER NOT NULL,
    material_id      INTEGER NOT NULL,
    lot_phase_id     INTEGER,                   -- which lot-phase triggered this need
    quantity         REAL NOT NULL,
    unit_cost        REAL NOT NULL,
    line_total       REAL NOT NULL,
    FOREIGN KEY (po_id) REFERENCES sim_purchase_orders(po_id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES sim_materials(material_id),
    FOREIGN KEY (lot_phase_id) REFERENCES sim_lot_phases(lot_phase_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_po_lines_po ON sim_po_lines(po_id);
CREATE INDEX IF NOT EXISTS idx_sim_po_lines_mat ON sim_po_lines(material_id);

-- =================================================================
-- TABLE: sim_inventory — Current stock levels per material
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_inventory (
    inventory_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id   INTEGER NOT NULL,
    material_id      INTEGER NOT NULL,
    quantity_on_hand  REAL NOT NULL DEFAULT 0,
    quantity_on_order REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES sim_materials(material_id) ON DELETE CASCADE,
    UNIQUE(development_id, material_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_inventory_dev ON sim_inventory(development_id);

-- =================================================================
-- ALTER: Add materials_ready flag to sim_lot_phases
-- Gates crew dispatch — phase can't start until materials are on site.
-- Default 1 so existing MVP phases (no materials) work unchanged.
-- =================================================================
ALTER TABLE sim_lot_phases ADD COLUMN materials_ready INTEGER NOT NULL DEFAULT 1;

-- =================================================================
-- ALTER: Add scales_with_units flag to sim_phase_templates
-- When true, hours_needed = base_hours * lot_type.unit_count
-- Used for condo "Unit Finish" phase.
-- =================================================================
ALTER TABLE sim_phase_templates ADD COLUMN scales_with_units INTEGER NOT NULL DEFAULT 0;

-- =================================================================
-- Schema version
-- =================================================================
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (8, 'Phase 3: materials, POs, inventory, multi-dependency');
