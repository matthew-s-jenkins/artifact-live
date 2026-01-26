-- Migration 003: Quantity and Mystery Part Support (Phase 1.1)
-- Adds quantity tracking for bulk items and mystery part identification
--
-- Changes:
-- 1. project_parts: add quantity field (default 1)
-- 2. project_parts: add is_mystery flag for unidentified parts

-- Add quantity column (default 1 for existing single-item rows)
ALTER TABLE project_parts ADD COLUMN quantity INTEGER DEFAULT 1;

-- Add is_mystery flag for unidentified parts
ALTER TABLE project_parts ADD COLUMN is_mystery INTEGER DEFAULT 0;

-- Create index for mystery parts lookup
CREATE INDEX IF NOT EXISTS idx_project_parts_is_mystery ON project_parts(is_mystery);

-- Record migration
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (3, 'Quantity and mystery part support');
