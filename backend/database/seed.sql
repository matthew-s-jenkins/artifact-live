-- Artifact Live v2 - Seed Data
-- Default subsections, pricing config, and test user
-- Date: 2026-01-19

-- Note: This file is run AFTER schema.sql
-- Foreign key constraints must be enabled

PRAGMA foreign_keys = ON;

-- =================================================================
-- Default Subsections (no business_id = personal inventory tracking)
-- =================================================================

-- These subsections are created for the first user during registration
-- but we define templates here for reference

-- Computer Chop Shop - the active business
-- INSERT INTO subsections (business_id, name, description, is_business) VALUES
--     (1, 'Computer Chop Shop', 'PC parting and flipping business', 1);

-- Keyboards - inventory tracking only
-- INSERT INTO subsections (business_id, name, description, is_business) VALUES
--     (NULL, 'Keyboards', 'Mechanical keyboard parts inventory', 0);

-- Electronics/Microcontrollers - inventory tracking only
-- INSERT INTO subsections (business_id, name, description, is_business) VALUES
--     (NULL, 'Electronics', 'Electronics and microcontroller parts inventory', 0);

-- =================================================================
-- Default Pricing Config Values (per user - inserted at registration)
-- =================================================================

-- These are template values used when creating a new user:
-- config_key                  | config_value | description
-- ebay_final_value_fee        | 0.1315       | eBay Final Value Fee (13.15%)
-- ebay_payment_processing     | 0.029        | Payment processing fee (2.9%)
-- ebay_payment_fixed          | 0.30         | Fixed payment processing fee ($0.30 per transaction)
-- ebay_promoted_listing       | 0.0          | Promoted listing fee (0% default, user can set)
-- shipping_estimate_light     | 8.00         | Shipping estimate for items under 1lb
-- shipping_estimate_medium    | 15.00        | Shipping estimate for items 1-5lb
-- shipping_estimate_heavy     | 25.00        | Shipping estimate for items 5lb+

-- =================================================================
-- Default Account Types (Chart of Accounts - inserted at registration)
-- =================================================================

-- These are template accounts created for each new user:
-- account_name         | account_type | subtype
-- Inventory Asset      | ASSET        | INVENTORY
-- Cash                 | ASSET        | CASH
-- Owner Capital        | EQUITY       | OWNER_CAPITAL
-- Sales Revenue        | REVENUE      | SALES
-- Cost of Goods Sold   | EXPENSE      | COGS
-- eBay Fees            | EXPENSE      | FEES
-- Shipping Expense     | EXPENSE      | SHIPPING

-- =================================================================
-- Default Parts Catalog Categories (Computer Chop Shop)
-- =================================================================

-- These category names are used as reference for the parts catalog:
-- CPU, GPU, RAM, Motherboard, Storage, Power Supply, Case, Cooling,
-- Cable, Peripheral, Networking, Other

-- =================================================================
-- Test User (Development Only)
-- Password: 'testpassword' hashed with bcrypt
-- =================================================================

-- DEVELOPMENT ONLY - Remove for production
-- INSERT INTO users (email, password_hash) VALUES
--     ('test@artifactlive.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.lLw9stML0J5O1G');

-- Note: The actual test user creation should be done through the API
-- or init_db.py script which properly hashes passwords
