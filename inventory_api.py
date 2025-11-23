"""
Artifact Live - Inventory API
View and manage current inventory across all locations
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

load_dotenv()

inventory_bp = Blueprint('inventory', __name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

@inventory_bp.route('/api/inventory/summary', methods=['GET'])
@login_required
def get_inventory_summary():
    """Get inventory summary aggregated by product"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get aggregated inventory by product
        cursor.execute("""
            SELECT
                p.product_id,
                p.sku,
                p.name,
                p.category,
                SUM(il.quantity_remaining) as total_quantity,
                AVG(il.unit_cost) as avg_cost,
                SUM(il.quantity_remaining * il.unit_cost) as total_value
            FROM products p
            INNER JOIN inventory_layers il ON p.product_id = il.product_id
            WHERE p.user_id = %s
                AND p.is_deleted = FALSE
                AND il.quantity_remaining > 0
                AND (p.business_id = %s OR %s IS NULL)
            GROUP BY p.product_id, p.sku, p.name, p.category
            ORDER BY p.name
        """, (user_id, business_id, business_id))

        products = cursor.fetchall()

        # Get location breakdown for each product (summed per location)
        for product in products:
            cursor.execute("""
                SELECT
                    l.name as location_name,
                    SUM(il.quantity_remaining) as quantity
                FROM inventory_layers il
                LEFT JOIN locations l ON il.location_id = l.location_id
                WHERE il.product_id = %s
                    AND il.quantity_remaining > 0
                GROUP BY il.location_id, l.name
                ORDER BY l.name
            """, (product['product_id'],))

            locations = cursor.fetchall()
            product['locations'] = [
                {'name': loc['location_name'] or 'No Location', 'quantity': float(loc['quantity'])}
                for loc in locations
            ]

        # Calculate overall totals
        total_products = len(products)
        total_quantity = sum(p['total_quantity'] for p in products)
        total_value = sum(p['total_value'] for p in products)

        cursor.close()
        conn.close()

        return jsonify({
            'products': products,
            'totals': {
                'total_products': total_products,
                'total_quantity': float(total_quantity) if total_quantity else 0,
                'total_value': float(total_value) if total_value else 0
            }
        })

    except Error as e:
        return jsonify({'error': str(e)}), 500

@inventory_bp.route('/api/inventory/by-location', methods=['GET'])
@login_required
def get_inventory_by_location():
    """Get inventory grouped by location"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                l.location_id,
                l.name as location_name,
                l.location_type,
                COUNT(DISTINCT p.product_id) as product_count,
                SUM(il.quantity_remaining) as total_quantity,
                SUM(il.quantity_remaining * il.unit_cost) as total_value
            FROM locations l
            LEFT JOIN inventory_layers il ON l.location_id = il.location_id AND il.quantity_remaining > 0
            LEFT JOIN products p ON il.product_id = p.product_id AND p.is_deleted = FALSE
            WHERE l.user_id = %s
                AND l.is_active = TRUE
                AND (l.business_id = %s OR %s IS NULL)
            GROUP BY l.location_id, l.name, l.location_type
            ORDER BY l.name
        """, (user_id, business_id, business_id))

        locations = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify({'locations': locations})

    except Error as e:
        return jsonify({'error': str(e)}), 500

@inventory_bp.route('/api/inventory/by-category', methods=['GET'])
@login_required
def get_inventory_by_category():
    """Get inventory grouped by category"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.category,
                COUNT(DISTINCT p.product_id) as product_count,
                SUM(il.quantity_remaining) as total_quantity,
                SUM(il.quantity_remaining * il.unit_cost) as total_value
            FROM products p
            INNER JOIN inventory_layers il ON p.product_id = il.product_id
            WHERE p.user_id = %s
                AND p.is_deleted = FALSE
                AND il.quantity_remaining > 0
                AND (p.business_id = %s OR %s IS NULL)
            GROUP BY p.category
            ORDER BY p.category
        """, (user_id, business_id, business_id))

        categories = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify({'categories': categories})

    except Error as e:
        return jsonify({'error': str(e)}), 500
