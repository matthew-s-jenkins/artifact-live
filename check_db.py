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
cursor.execute("SHOW COLUMNS FROM products")
columns = cursor.fetchall()

print("\n=== PRODUCTS TABLE COLUMNS ===")
for col in columns:
    print(f"  {col[0]}")

if any('business_id' in str(col) for col in columns):
    print("\n✅ business_id column EXISTS")
else:
    print("\n❌ business_id column MISSING")
    print("\nAdding business_id column...")
    cursor.execute("ALTER TABLE products ADD COLUMN business_id INT DEFAULT NULL AFTER user_id")
    conn.commit()
    print("✅ business_id column added!")

cursor.close()
conn.close()
