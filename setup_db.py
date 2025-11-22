import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

# Read the SQL file
with open('init_db.sql', 'r') as f:
    sql_script = f.read()

# Split into individual statements
statements = [s.strip() for s in sql_script.split(';') if s.strip()]

# Connect to MySQL (without specifying database first)
conn = mysql.connector.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD', '')
)

cursor = conn.cursor()

try:
    # Execute each statement
    for statement in statements:
        if statement:
            print(f"Executing: {statement[:50]}...")
            cursor.execute(statement)
            conn.commit()

    print("✅ Database setup complete!")

    # Verify tables were created
    cursor.execute("USE artifact_live")
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    print(f"\n📊 Created {len(tables)} tables:")
    for table in tables:
        print(f"  - {table[0]}")

except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    cursor.close()
    conn.close()
