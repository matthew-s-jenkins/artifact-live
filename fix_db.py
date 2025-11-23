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

try:
    cursor.execute("ALTER TABLE products ADD COLUMN business_id INT DEFAULT NULL AFTER user_id")
    conn.commit()
    print("SUCCESS: business_id column added")
except Exception as e:
    if "Duplicate column" in str(e):
        print("Column already exists")
    else:
        print(f"Error: {e}")

cursor.close()
conn.close()
