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
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB;

-- ============================================================================
-- PRODUCT CATALOG
-- ============================================================================

CREATE TABLE products (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    sku VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    unit_of_measure VARCHAR(20) DEFAULT 'EA',  -- EA, LB, KG, etc.
    reorder_point INT DEFAULT 0,
    reorder_quantity INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_sku (user_id, sku),
    INDEX idx_user_products (user_id, is_active),
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_vendors (user_id, is_active)
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    UNIQUE KEY unique_user_po (user_id, po_number),
    INDEX idx_user_po (user_id, order_date),
    INDEX idx_status (status)
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_so (user_id, order_number),
    INDEX idx_user_so (user_id, order_date),
    INDEX idx_status (status)
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_accounts (user_id, account_type)
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
    reference_type VARCHAR(30),  -- PURCHASE, SALE, ADJUSTMENT, etc.
    reference_id INT,  -- ID of the related record (PO, SO, etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id),
    INDEX idx_user_ledger (user_id, transaction_date),
    INDEX idx_transaction (transaction_uuid),
    INDEX idx_account_date (account_id, transaction_date)
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
