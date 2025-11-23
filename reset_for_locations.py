"""
Reset database and add locations table for proper inventory management
"""
import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv('DB_HOST'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)

cursor = conn.cursor()

print("=" * 60)
print("RESETTING DATABASE FOR LOCATION-BASED INVENTORY")
print("=" * 60)

# Clear existing test data
print("\n1. Clearing test data...")
try:
    # Check if ledger_entries table exists
    cursor.execute("SHOW TABLES LIKE 'ledger_entries'")
    if cursor.fetchone():
        cursor.execute("DELETE FROM ledger_entries WHERE reference_type = 'CAPITAL_CONTRIBUTION'")
        deleted_ledger = cursor.rowcount
        print(f"   - Deleted {deleted_ledger} ledger entries")

    cursor.execute("DELETE FROM inventory_layers WHERE reference_type = 'CAPITAL_CONTRIBUTION'")
    deleted_layers = cursor.rowcount
    print(f"   - Deleted {deleted_layers} inventory layers")

    conn.commit()
    print("   OK - Test data cleared")
except Exception as e:
    print(f"   WARNING - Error clearing data: {e}")
    conn.rollback()

# Create locations table
print("\n2. Creating locations table...")
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            location_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            business_id INT DEFAULT NULL,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            location_type ENUM('Storage', 'Workspace', 'Shipping', 'Other') DEFAULT 'Storage',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE KEY unique_location_name (user_id, name)
        )
    """)
    print("   OK - Locations table created")
    conn.commit()
except Exception as e:
    print(f"   WARNING - Table may already exist: {e}")

# Add location_id column to inventory_layers
print("\n3. Adding location_id to inventory_layers...")
try:
    cursor.execute("""
        ALTER TABLE inventory_layers
        ADD COLUMN location_id INT DEFAULT NULL AFTER product_id,
        ADD FOREIGN KEY (location_id) REFERENCES locations(location_id) ON DELETE SET NULL
    """)
    print("   OK - location_id column added to inventory_layers")
    conn.commit()
except Exception as e:
    if "Duplicate column" in str(e):
        print("   OK - location_id column already exists")
    else:
        print(f"   WARNING - Error: {e}")

# Add session_source column to inventory_layers (keep for legacy tracking)
print("\n4. Adding session_source to inventory_layers...")
try:
    cursor.execute("""
        ALTER TABLE inventory_layers
        ADD COLUMN session_source VARCHAR(100) DEFAULT NULL AFTER location_id
    """)
    print("   OK - session_source column added to inventory_layers")
    conn.commit()
except Exception as e:
    if "Duplicate column" in str(e):
        print("   OK - session_source column already exists")
    else:
        print(f"   WARNING - Error: {e}")

cursor.close()
conn.close()

print("\n" + "=" * 60)
print("DATABASE RESET COMPLETE")
print("=" * 60)
print("\nNext steps:")
print("1. Restart your Flask server")
print("2. Create locations in the Location Management tab")
print("3. Use Fast Ingestion Wizard with location dropdown")
print("=" * 60)
