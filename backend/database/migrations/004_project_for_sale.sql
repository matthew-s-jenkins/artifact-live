-- Migration 004: Project For Sale Flag (Phase 1.2)
-- Adds for_sale flag to projects table for keyboard builds that can be sold whole
--
-- Changes:
-- 1. projects: add for_sale flag (default 0)

-- Add for_sale column to projects
ALTER TABLE projects ADD COLUMN for_sale INTEGER DEFAULT 0;

-- Create index for quick filtering of projects for sale
CREATE INDEX IF NOT EXISTS idx_projects_for_sale ON projects(for_sale);

-- Record migration
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (4, 'Project for_sale flag for keyboard builds');
