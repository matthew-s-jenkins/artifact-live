-- ============================================================================
-- ARTIFACT LIVE DATABASE SCHEMA
-- Inventory Management System with Double-Entry Accounting
-- Based on Perfect Books architecture with inventory/supply chain extensions
-- ============================================================================

CREATE DATABASE IF NOT EXISTS artifact_live;
USE artifact_live;

-- ============================================================================
-- USER MANAGEMENT
-- ============================================================================

CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_google_id (google_id)
) ENGINE=InnoDB;

-- ============================================================================
-- BUSINESSES / WORKSPACES
-- Support for multiple businesses per user
-- ============================================================================

CREATE TABLE businesses (
    business_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    business_name VARCHAR(255) NOT NULL,
    business_type VARCHAR(50),  -- 'KEYBOARD_SHOP', 'ELECTRONICS', 'GENERAL', etc.
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_businesses (user_id, is_active)
) ENGINE=InnoDB;

-- ============================================================================
-- PRODUCT CATALOG
-- ============================================================================

CREATE TABLE products (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    business_id INT DEFAULT NULL,  -- Optional: Link product to specific business
    sku VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    unit_of_measure VARCHAR(20) DEFAULT 'EA',  -- EA, LB, KG, etc.
    reorder_point INT DEFAULT 0,
    reorder_quantity INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE,  -- Soft delete flag
    deleted_at TIMESTAMP NULL,  -- When was it deleted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (business_id) REFERENCES businesses(business_id) ON DELETE SET NULL,
    UNIQUE KEY unique_user_sku (user_id, sku),
    INDEX idx_user_products (user_id, is_active),
    INDEX idx_business_products (business_id, is_active),
    INDEX idx_deleted (is_deleted),
    INDEX idx_category (category)
) ENGINE=InnoDB;

-- ============================================================================
-- INVENTORY TRACKING (FIFO Cost Layers)
-- ============================================================================

CREATE TABLE inventory_layers (
    layer_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity_remaining DECIMAL(12,4) NOT NULL,
    unit_cost DECIMAL(12,4) NOT NULL,
    received_date DATE NOT NULL,
    reference_type VARCHAR(20),  -- 'PURCHASE_ORDER', 'ADJUSTMENT', etc.
    reference_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE,
    INDEX idx_product_fifo (product_id, received_date),
    INDEX idx_user_inventory (user_id)
) ENGINE=InnoDB;

-- ============================================================================
-- EXPENSE CATEGORIES (from Perfect Books)
-- ============================================================================

CREATE TABLE expense_categories (
    category_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#6366f1',
    is_default BOOLEAN DEFAULT FALSE,
    is_monthly BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_category (user_id, name),
    INDEX idx_user_categories (user_id)
) ENGINE=InnoDB;

-- ============================================================================
-- VENDORS
-- ============================================================================

CREATE TABLE vendors (
    vendor_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    vendor_name VARCHAR(255) NOT NULL,
    contact_person VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address TEXT,
    payment_terms VARCHAR(50),  -- 'NET30', 'NET60', 'COD', etc.
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE,  -- Soft delete flag
    deleted_at TIMESTAMP NULL,  -- When was it deleted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_vendors (user_id, is_active),
    INDEX idx_deleted (is_deleted)
) ENGINE=InnoDB;

-- ============================================================================
-- VENDOR PRICING (from Digital Harvest)
-- Volume-based pricing tiers for vendor products
-- ============================================================================

CREATE TABLE volume_discounts (
    discount_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    vendor_id INT NOT NULL,
    product_id INT NOT NULL,
    min_quantity INT NOT NULL,
    max_quantity INT,  -- NULL means unlimited
    unit_cost DECIMAL(12,4) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE,
    INDEX idx_vendor_product (vendor_id, product_id),
    INDEX idx_user_pricing (user_id)
) ENGINE=InnoDB;

-- ============================================================================
-- PURCHASE ORDERS
-- ============================================================================

CREATE TABLE purchase_orders (
    po_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    vendor_id INT NOT NULL,
    po_number VARCHAR(50) NOT NULL,
    order_date DATE NOT NULL,
    expected_delivery_date DATE,
    status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, RECEIVED, PARTIAL, CANCELLED
    total_amount DECIMAL(12,2) DEFAULT 0.00,
    notes TEXT,
    is_deleted BOOLEAN DEFAULT FALSE,  -- Soft delete flag
    deleted_at TIMESTAMP NULL,  -- When was it deleted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    UNIQUE KEY unique_user_po (user_id, po_number),
    INDEX idx_user_po (user_id, order_date),
    INDEX idx_status (status),
    INDEX idx_deleted (is_deleted)
) ENGINE=InnoDB;

CREATE TABLE purchase_order_items (
    po_item_id INT AUTO_INCREMENT PRIMARY KEY,
    po_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity_ordered DECIMAL(12,4) NOT NULL,
    quantity_received DECIMAL(12,4) DEFAULT 0,
    unit_cost DECIMAL(12,4) NOT NULL,
    line_total DECIMAL(12,2) GENERATED ALWAYS AS (quantity_ordered * unit_cost) STORED,
    FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    INDEX idx_po_items (po_id)
) ENGINE=InnoDB;

-- ============================================================================
-- ACCOUNTS PAYABLE (from Digital Harvest)
-- Track vendor invoices and payment obligations
-- ============================================================================

CREATE TABLE accounts_payable (
    payable_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    po_id INT NOT NULL,
    vendor_id INT NOT NULL,
    amount_due DECIMAL(12,2) NOT NULL,
    creation_date DATE NOT NULL,
    due_date DATE,
    paid_date DATE,
    status VARCHAR(20) DEFAULT 'UNPAID',  -- UNPAID, PAID, OVERDUE
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id),
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    INDEX idx_user_payables (user_id, status),
    INDEX idx_vendor_payables (vendor_id, status),
    INDEX idx_due_date (due_date)
) ENGINE=InnoDB;

-- ============================================================================
-- SALES ORDERS
-- ============================================================================

CREATE TABLE sales_orders (
    so_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    order_number VARCHAR(50) NOT NULL,
    order_date DATE NOT NULL,
    customer_name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, FULFILLED, PARTIAL, CANCELLED
    total_amount DECIMAL(12,2) DEFAULT 0.00,
    notes TEXT,
    is_deleted BOOLEAN DEFAULT FALSE,  -- Soft delete flag
    deleted_at TIMESTAMP NULL,  -- When was it deleted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_so (user_id, order_number),
    INDEX idx_user_so (user_id, order_date),
    INDEX idx_status (status),
    INDEX idx_deleted (is_deleted)
) ENGINE=InnoDB;

CREATE TABLE sales_order_items (
    so_item_id INT AUTO_INCREMENT PRIMARY KEY,
    so_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity_ordered DECIMAL(12,4) NOT NULL,
    quantity_fulfilled DECIMAL(12,4) DEFAULT 0,
    unit_price DECIMAL(12,4) NOT NULL,
    line_total DECIMAL(12,2) GENERATED ALWAYS AS (quantity_ordered * unit_price) STORED,
    cogs DECIMAL(12,2) DEFAULT 0.00,  -- Cost of Goods Sold (calculated on fulfillment)
    FOREIGN KEY (so_id) REFERENCES sales_orders(so_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    INDEX idx_so_items (so_id)
) ENGINE=InnoDB;

-- ============================================================================
-- KITTING / ASSEMBLY (Bill of Materials)
-- For keyboard builds and other assembled products
-- ============================================================================

CREATE TABLE bom_templates (
    bom_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    parent_product_id INT NOT NULL,  -- The assembled product (e.g., "Complete Keyboard")
    bom_name VARCHAR(255) NOT NULL,
    labor_cost DECIMAL(12,2) DEFAULT 0.00,  -- Cost to assemble
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_product_id) REFERENCES products(product_id),
    INDEX idx_user_bom (user_id, is_active),
    INDEX idx_parent_product (parent_product_id),
    INDEX idx_deleted (is_deleted)
) ENGINE=InnoDB;

CREATE TABLE bom_components (
    component_id INT AUTO_INCREMENT PRIMARY KEY,
    bom_id INT NOT NULL,
    child_product_id INT NOT NULL,  -- Component product (e.g., "Gateron Yellow Switch")
    quantity_required DECIMAL(12,4) NOT NULL,  -- How many of this component needed
    is_optional BOOLEAN DEFAULT FALSE,  -- For optional components
    substitution_group VARCHAR(50),  -- Allow alternative components (e.g., "switches", "caps")
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bom_id) REFERENCES bom_templates(bom_id) ON DELETE CASCADE,
    FOREIGN KEY (child_product_id) REFERENCES products(product_id),
    INDEX idx_bom (bom_id),
    INDEX idx_substitution (substitution_group)
) ENGINE=InnoDB;

-- Keyboard-specific: Define which keys are in a keycap set
CREATE TABLE keycap_sets (
    keycap_set_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,  -- Links to products table
    set_name VARCHAR(255) NOT NULL,
    -- Key counts by size/type
    key_1u INT DEFAULT 0,
    key_1_25u INT DEFAULT 0,
    key_1_5u INT DEFAULT 0,
    key_1_75u INT DEFAULT 0,
    key_2u INT DEFAULT 0,
    key_2_25u INT DEFAULT 0,
    key_2_75u INT DEFAULT 0,
    key_6_25u INT DEFAULT 0,  -- Spacebar
    key_7u INT DEFAULT 0,  -- Alternate spacebar
    -- ISO-specific keys
    iso_enter INT DEFAULT 0,
    iso_shift INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    UNIQUE KEY unique_product_keycap_set (product_id),
    INDEX idx_user_sets (user_id)
) ENGINE=InnoDB;

-- Keyboard-specific: Define which keys a keyboard layout requires
CREATE TABLE keyboard_layouts (
    layout_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,  -- The keyboard product
    layout_name VARCHAR(100) NOT NULL,  -- "60%", "65%", "TKL", "Full", "ISO-UK", etc.
    -- Key requirements by size/type
    key_1u_required INT DEFAULT 0,
    key_1_25u_required INT DEFAULT 0,
    key_1_5u_required INT DEFAULT 0,
    key_1_75u_required INT DEFAULT 0,
    key_2u_required INT DEFAULT 0,
    key_2_25u_required INT DEFAULT 0,
    key_2_75u_required INT DEFAULT 0,
    key_6_25u_required INT DEFAULT 0,
    key_7u_required INT DEFAULT 0,
    iso_enter_required INT DEFAULT 0,
    iso_shift_required INT DEFAULT 0,
    total_switches_required INT DEFAULT 0,  -- Total switch count
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    UNIQUE KEY unique_product_layout (product_id),
    INDEX idx_user_layouts (user_id)
) ENGINE=InnoDB;

-- Assembly transactions: When you build/kit an assembled product
CREATE TABLE assembly_transactions (
    assembly_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    bom_id INT NOT NULL,
    quantity_assembled DECIMAL(12,4) NOT NULL,
    assembly_date DATE NOT NULL,
    total_cost DECIMAL(12,2) DEFAULT 0.00,  -- Materials + Labor
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (bom_id) REFERENCES bom_templates(bom_id),
    INDEX idx_user_assemblies (user_id, assembly_date),
    INDEX idx_bom (bom_id)
) ENGINE=InnoDB;

-- ============================================================================
-- DOUBLE-ENTRY ACCOUNTING LEDGER
-- Based on Perfect Books architecture
-- ============================================================================

CREATE TABLE accounts (
    account_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(20) NOT NULL,  -- ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
    subtype VARCHAR(50),  -- CASH, INVENTORY, COGS, SALES, etc.
    is_system BOOLEAN DEFAULT FALSE,  -- System accounts created automatically
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE,  -- Soft delete flag
    deleted_at TIMESTAMP NULL,  -- When was it deleted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_accounts (user_id, account_type),
    INDEX idx_deleted (is_deleted)
) ENGINE=InnoDB;

CREATE TABLE ledger (
    entry_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    account_id INT NOT NULL,
    transaction_uuid CHAR(36) NOT NULL,  -- Groups DR/CR entries together
    transaction_date DATE NOT NULL,
    description VARCHAR(500),
    debit DECIMAL(12,2) DEFAULT 0.00,
    credit DECIMAL(12,2) DEFAULT 0.00,
    category_id INT DEFAULT NULL,  -- Link to expense_categories (from Perfect Books)
    reference_type VARCHAR(30),  -- PURCHASE, SALE, ADJUSTMENT, etc.
    reference_id INT,  -- ID of the related record (PO, SO, etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id),
    FOREIGN KEY (category_id) REFERENCES expense_categories(category_id) ON DELETE SET NULL,
    INDEX idx_user_ledger (user_id, transaction_date),
    INDEX idx_transaction (transaction_uuid),
    INDEX idx_account_date (account_id, transaction_date),
    INDEX idx_category (category_id)
) ENGINE=InnoDB;

-- ============================================================================
-- RECURRING EXPENSES (from Perfect Books)
-- Automated monthly bill payments and recurring costs
-- ============================================================================

CREATE TABLE recurring_expenses (
    expense_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    description VARCHAR(255) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    frequency VARCHAR(20) NOT NULL,  -- DAILY, WEEKLY, MONTHLY
    due_day_of_month INT NOT NULL DEFAULT 1,
    last_processed_date DATE DEFAULT NULL,
    payment_account_id INT DEFAULT NULL,  -- Which account to pay from
    category_id INT DEFAULT NULL,  -- Link to expense_categories
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (payment_account_id) REFERENCES accounts(account_id) ON DELETE SET NULL,
    FOREIGN KEY (category_id) REFERENCES expense_categories(category_id) ON DELETE SET NULL,
    INDEX idx_user_expenses (user_id, is_active),
    INDEX idx_category (category_id)
) ENGINE=InnoDB;

-- ============================================================================
-- VIEWS FOR REPORTING
-- ============================================================================

-- Current Inventory Value by Product
CREATE VIEW v_inventory_value AS
SELECT
    il.user_id,
    il.product_id,
    p.sku,
    p.name,
    SUM(il.quantity_remaining) AS total_quantity,
    ROUND(SUM(il.quantity_remaining * il.unit_cost), 2) AS total_value,
    ROUND(SUM(il.quantity_remaining * il.unit_cost) / NULLIF(SUM(il.quantity_remaining), 0), 4) AS avg_unit_cost
FROM inventory_layers il
JOIN products p ON il.product_id = p.product_id
WHERE il.quantity_remaining > 0
GROUP BY il.user_id, il.product_id, p.sku, p.name;

-- Account Balances
CREATE VIEW v_account_balances AS
SELECT
    l.user_id,
    l.account_id,
    a.account_name,
    a.account_type,
    a.subtype,
    SUM(l.debit - l.credit) AS balance
FROM ledger l
JOIN accounts a ON l.account_id = a.account_id
GROUP BY l.user_id, l.account_id, a.account_name, a.account_type, a.subtype;

-- ============================================================================
-- SYSTEM INITIALIZATION
-- After user registration, create default accounts
-- This will be handled by the application
-- ============================================================================
