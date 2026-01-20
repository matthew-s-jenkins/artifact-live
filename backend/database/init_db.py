"""
Artifact Live v2 - Database Initialization Script

This module creates and initializes the Artifact Live SQLite database.
Run this script to create a fresh database or reset an existing one.

Usage:
    python init_db.py              # Create database if not exists
    python init_db.py --reset      # Delete and recreate database
    python init_db.py --verify     # Verify schema only

Author: Matthew Jenkins
Date: 2026-01-19
"""

import sqlite3
import sys
from pathlib import Path


def get_db_path():
    """Return the path to the SQLite database file"""
    return Path(__file__).parent / "artifactlive.db"


def get_schema_path():
    """Return the path to the schema SQL file"""
    return Path(__file__).parent / "schema.sql"


def get_seed_path():
    """Return the path to the seed SQL file"""
    return Path(__file__).parent / "seed.sql"


def create_database():
    """
    Create the Artifact Live SQLite database with all tables.

    Returns True if successful, False otherwise.
    """
    db_path = get_db_path()
    schema_path = get_schema_path()

    # Check schema file exists
    if not schema_path.exists():
        print(f"[ERROR] Schema file not found: {schema_path}")
        return False

    # Create directory if needed
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Artifact Live v2 - Database Initialization")
    print("=" * 60)
    print()
    print(f"Database: {db_path}")
    print(f"Schema:   {schema_path}")
    print()

    try:
        # Connect to SQLite (creates file if doesn't exist)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON;")

        # Read and execute schema
        print("Executing schema.sql...")
        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        cursor.executescript(schema_sql)
        conn.commit()
        print("[OK] Schema applied successfully")

        # Execute seed data if exists
        seed_path = get_seed_path()
        if seed_path.exists():
            print("Executing seed.sql...")
            with open(seed_path, 'r') as f:
                seed_sql = f.read()
            cursor.executescript(seed_sql)
            conn.commit()
            print("[OK] Seed data applied successfully")

        conn.close()
        print()
        print("[OK] Database created successfully!")
        return True

    except sqlite3.Error as err:
        print(f"[ERROR] Database error: {err}")
        return False
    except Exception as err:
        print(f"[ERROR] Unexpected error: {err}")
        return False


def reset_database():
    """
    Delete the existing database and create a fresh one.
    WARNING: All data will be permanently lost!
    """
    db_path = get_db_path()

    if db_path.exists():
        print(f"[WARNING] Deleting existing database: {db_path}")
        db_path.unlink()
        print("[OK] Database deleted")

    return create_database()


def verify_schema():
    """
    Verify that all expected tables exist in the database.
    """
    db_path = get_db_path()

    if not db_path.exists():
        print("[ERROR] Database does not exist")
        return False

    expected_tables = [
        'users',
        'businesses',
        'subsections',
        'projects',
        'parts_catalog',
        'project_parts',
        'shipping_supplies',
        'pricing_config',
        'accounts',
        'financial_ledger',
        'inventory_layers',
        'expense_categories',
        'schema_version'
    ]

    expected_views = [
        'v_account_balances',
        'v_project_summary'
    ]

    print("=" * 60)
    print("Artifact Live v2 - Schema Verification")
    print("=" * 60)
    print()

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check tables
        print("Checking tables...")
        all_ok = True
        for table in expected_tables:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            if cursor.fetchone():
                print(f"  [OK] {table}")
            else:
                print(f"  [MISSING] {table}")
                all_ok = False

        print()
        print("Checking views...")
        for view in expected_views:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
                (view,)
            )
            if cursor.fetchone():
                print(f"  [OK] {view}")
            else:
                print(f"  [MISSING] {view}")
                all_ok = False

        # Check foreign keys
        print()
        cursor.execute("PRAGMA foreign_keys;")
        fk_status = cursor.fetchone()[0]
        print(f"Foreign keys: {'[OK] Enabled' if fk_status else '[WARNING] Disabled'}")

        # Check schema version
        cursor.execute("SELECT version, description FROM schema_version ORDER BY version DESC LIMIT 1")
        version_row = cursor.fetchone()
        if version_row:
            print(f"Schema version: {version_row[0]} - {version_row[1]}")

        conn.close()

        print()
        if all_ok:
            print("[OK] Schema verification complete - all tables present")
        else:
            print("[ERROR] Schema verification failed - missing tables")

        return all_ok

    except sqlite3.Error as err:
        print(f"[ERROR] Database error: {err}")
        return False


def get_table_info(table_name):
    """Display detailed schema information for a specific table."""
    db_path = get_db_path()

    if not db_path.exists():
        print("[ERROR] Database does not exist")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()

    if not columns:
        print(f"[ERROR] Table '{table_name}' not found")
        conn.close()
        return

    print(f"\nTable: {table_name}")
    print("=" * 80)
    print(f"{'Column':<25} {'Type':<15} {'NotNull':<10} {'Default':<20}")
    print("-" * 80)

    for col in columns:
        cid, name, col_type, notnull, default_val, pk = col
        pk_marker = " (PK)" if pk else ""
        print(f"{name + pk_marker:<25} {col_type:<15} {str(bool(notnull)):<10} {str(default_val):<20}")

    # Show indexes
    cursor.execute(f"PRAGMA index_list({table_name});")
    indexes = cursor.fetchall()

    if indexes:
        print()
        print("Indexes:")
        for idx in indexes:
            seq, name, unique, origin, partial = idx
            print(f"  - {name} {'(UNIQUE)' if unique else ''}")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--reset":
            confirm = input("WARNING: This will DELETE ALL DATA. Type 'DELETE' to confirm: ")
            if confirm == 'DELETE':
                reset_database()
                verify_schema()
            else:
                print("Reset cancelled.")
        elif sys.argv[1] == "--verify":
            verify_schema()
        elif sys.argv[1] == "--info":
            if len(sys.argv) > 2:
                get_table_info(sys.argv[2])
            else:
                print("Usage: python init_db.py --info <table_name>")
        else:
            print("Usage:")
            print("  python init_db.py              # Create database")
            print("  python init_db.py --reset      # Reset database (DELETES DATA)")
            print("  python init_db.py --verify     # Verify schema")
            print("  python init_db.py --info <tbl> # Show table info")
    else:
        db_path = get_db_path()
        if db_path.exists():
            print(f"Database already exists: {db_path}")
            print()
            print("Options:")
            print("  python init_db.py --verify  # Verify existing schema")
            print("  python init_db.py --reset   # Delete and recreate")
        else:
            create_database()
            verify_schema()
