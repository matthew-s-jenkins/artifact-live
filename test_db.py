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

cursor = conn.cursor(dictionary=True)

print("\n=== ALL PRODUCTS ===")
cursor.execute("SELECT * FROM products")
products = cursor.fetchall()
for p in products:
    print(f"  {p['product_id']}: {p['name']} (SKU: {p['sku']})")

print("\n=== ALL INVENTORY LAYERS ===")
cursor.execute("""
    SELECT il.*, p.name
    FROM inventory_layers il
    JOIN products p ON il.product_id = p.product_id
""")
layers = cursor.fetchall()
for l in layers:
    print(f"  Layer {l['layer_id']}: {l['name']} - Qty: {l['quantity_remaining']}, Cost: ${l['unit_cost']}")

cursor.close()
conn.close()
