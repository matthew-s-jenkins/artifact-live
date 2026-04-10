-- Migration 007: Construction Development Simulator
-- Adds all tables needed for the land development simulation.
-- Phase 1 MVP: 10 houses, 3 crew types, 5 phases, FIFO scheduling.
-- Tables designed for full scale (96 houses + 4 condo buildings, 9 crew types, 8 phases).
--
-- Author: Matthew Jenkins
-- Date: 2026-04-10

PRAGMA foreign_keys = ON;

-- =================================================================
-- TABLE: sim_developments — Top-level development project
-- One row per simulation run. Owns all lots, crews, and daily state.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_developments (
    development_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    business_id     INTEGER,                        -- FK to businesses (sim creates its own)
    name            TEXT NOT NULL,                   -- 'Oakwood Estates'
    acreage         REAL,
    land_cost       REAL DEFAULT 0,                  -- Purchase price of land
    budget          REAL DEFAULT 0,                  -- Total development budget
    start_date      TEXT NOT NULL,                   -- Sim calendar start (YYYY-MM-DD)
    current_day     INTEGER NOT NULL DEFAULT 0,      -- Days elapsed since start
    status          TEXT NOT NULL DEFAULT 'setup'
                    CHECK(status IN ('setup','running','paused','completed')),
    strategy        TEXT NOT NULL DEFAULT 'fifo'
                    CHECK(strategy IN ('fifo','batch','rolling')),
    config          TEXT,                            -- JSON for sim settings (weather, etc.)
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (business_id) REFERENCES businesses(business_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_dev_user ON sim_developments(user_id);

-- =================================================================
-- TABLE: sim_crew_types — Types of crews (General Labor, Concrete, etc.)
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_crew_types (
    crew_type_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id  INTEGER NOT NULL,
    name            TEXT NOT NULL,                   -- 'General Labor', 'Concrete', 'Framing'
    hourly_rate     REAL NOT NULL,                   -- Cost per labor-hour
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_crew_types_dev ON sim_crew_types(development_id);

-- =================================================================
-- TABLE: sim_crews — Individual crew instances
-- Multiple crews of the same type can exist (e.g., 2 framing crews).
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_crews (
    crew_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id  INTEGER NOT NULL,
    crew_type_id    INTEGER NOT NULL,
    name            TEXT NOT NULL,                   -- 'Framing Crew Alpha'
    hours_per_day   REAL NOT NULL DEFAULT 8,         -- Work capacity per sim day
    is_active       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE,
    FOREIGN KEY (crew_type_id) REFERENCES sim_crew_types(crew_type_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_crews_dev ON sim_crews(development_id);
CREATE INDEX IF NOT EXISTS idx_sim_crews_type ON sim_crews(crew_type_id);

-- =================================================================
-- TABLE: sim_lot_types — Templates for house/condo types
-- Defines the blueprint: what phases, how many labor hours, etc.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_lot_types (
    lot_type_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id  INTEGER NOT NULL,
    name            TEXT NOT NULL,                   -- 'Small House', 'Large House', 'Condo Building A'
    category        TEXT NOT NULL DEFAULT 'house'
                    CHECK(category IN ('house','condo_building')),
    unit_count      INTEGER NOT NULL DEFAULT 1,      -- 1 for houses, N for condo buildings
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_lot_types_dev ON sim_lot_types(development_id);

-- =================================================================
-- TABLE: sim_phase_templates — Phase definitions per lot type
-- Defines what each lot type needs built, in what order, by whom.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_phase_templates (
    template_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_type_id     INTEGER NOT NULL,
    phase_number    INTEGER NOT NULL,                -- Execution order (1, 2, 3...)
    phase_name      TEXT NOT NULL,                   -- 'Site Prep', 'Foundation', 'Framing'
    crew_type_id    INTEGER NOT NULL,                -- Which crew type does this work
    base_hours      REAL NOT NULL,                   -- Labor hours for this phase
    depends_on_phase INTEGER,                        -- Phase number that must complete first (NULL = no dependency)
    cure_days       INTEGER DEFAULT 0,               -- Wait days after completion before next can start (e.g., concrete curing)
    FOREIGN KEY (lot_type_id) REFERENCES sim_lot_types(lot_type_id) ON DELETE CASCADE,
    FOREIGN KEY (crew_type_id) REFERENCES sim_crew_types(crew_type_id),
    UNIQUE(lot_type_id, phase_number)
);

CREATE INDEX IF NOT EXISTS idx_sim_phase_tmpl_lot_type ON sim_phase_templates(lot_type_id);

-- =================================================================
-- TABLE: sim_lots — Individual lots (houses or condo buildings)
-- One row per physical structure being built.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_lots (
    lot_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id  INTEGER NOT NULL,
    lot_type_id     INTEGER NOT NULL,
    lot_number      INTEGER NOT NULL,                -- Sequential: House #001, #002...
    label           TEXT,                            -- Optional friendly name
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','in_progress','completed')),
    started_day     INTEGER,                         -- Sim day construction began
    completed_day   INTEGER,                         -- Sim day all phases done
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE,
    FOREIGN KEY (lot_type_id) REFERENCES sim_lot_types(lot_type_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_lots_dev ON sim_lots(development_id);
CREATE INDEX IF NOT EXISTS idx_sim_lots_status ON sim_lots(status);

-- =================================================================
-- TABLE: sim_lot_phases — Phase instances per lot (tracks actual progress)
-- Created when a lot is initialized. Updated as crews work.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_lot_phases (
    lot_phase_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id          INTEGER NOT NULL,
    template_id     INTEGER NOT NULL,                -- Which phase template this instantiates
    phase_number    INTEGER NOT NULL,
    phase_name      TEXT NOT NULL,
    crew_type_id    INTEGER NOT NULL,
    hours_needed    REAL NOT NULL,                   -- From template (may vary per lot in future)
    hours_completed REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','blocked','ready','in_progress','curing','completed')),
    ready_day       INTEGER,                         -- Sim day this phase became workable
    started_day     INTEGER,                         -- Sim day first crew-hour logged
    completed_day   INTEGER,
    cure_until_day  INTEGER,                         -- If curing, day it becomes unblocked
    assigned_crew_id INTEGER,                        -- Currently assigned crew (NULL if unassigned)
    FOREIGN KEY (lot_id) REFERENCES sim_lots(lot_id) ON DELETE CASCADE,
    FOREIGN KEY (template_id) REFERENCES sim_phase_templates(template_id),
    FOREIGN KEY (crew_type_id) REFERENCES sim_crew_types(crew_type_id),
    FOREIGN KEY (assigned_crew_id) REFERENCES sim_crews(crew_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_lot_phases_lot ON sim_lot_phases(lot_id);
CREATE INDEX IF NOT EXISTS idx_sim_lot_phases_status ON sim_lot_phases(status);
CREATE INDEX IF NOT EXISTS idx_sim_lot_phases_crew_type ON sim_lot_phases(crew_type_id);
CREATE INDEX IF NOT EXISTS idx_sim_lot_phases_assigned ON sim_lot_phases(assigned_crew_id);

-- =================================================================
-- TABLE: sim_daily_log — Record of what happened each sim day
-- One row per crew per day. The granular activity log.
-- =================================================================
CREATE TABLE IF NOT EXISTS sim_daily_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id  INTEGER NOT NULL,
    sim_day         INTEGER NOT NULL,
    crew_id         INTEGER NOT NULL,
    lot_phase_id    INTEGER NOT NULL,
    hours_worked    REAL NOT NULL,
    labor_cost      REAL NOT NULL,                   -- hours_worked * hourly_rate
    event_id        TEXT,                            -- FK to business_events (the accounting entry)
    notes           TEXT,
    FOREIGN KEY (development_id) REFERENCES sim_developments(development_id) ON DELETE CASCADE,
    FOREIGN KEY (crew_id) REFERENCES sim_crews(crew_id),
    FOREIGN KEY (lot_phase_id) REFERENCES sim_lot_phases(lot_phase_id),
    FOREIGN KEY (event_id) REFERENCES business_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_daily_log_dev_day ON sim_daily_log(development_id, sim_day);
CREATE INDEX IF NOT EXISTS idx_sim_daily_log_crew ON sim_daily_log(crew_id);
CREATE INDEX IF NOT EXISTS idx_sim_daily_log_phase ON sim_daily_log(lot_phase_id);

-- =================================================================
-- FUTURE TABLES (Phase 3 — placeholders, not created yet):
--   sim_materials        — Material types and unit costs
--   sim_phase_materials  — Materials consumed per phase template
--   sim_purchase_orders  — POs with delivery dates
--   sim_po_lines         — Line items on POs
--   sim_inventory        — Material stock levels
-- =================================================================

-- =================================================================
-- Schema version
-- =================================================================
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (7, 'Construction development simulator tables');
