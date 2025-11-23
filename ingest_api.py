"""
Artifact Live - Fast Ingestion API
Handles rapid inventory digitization with proper capital contribution accounting
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv
from datetime import date
import uuid

load_dotenv()

ingest_bp = Blueprint('ingest', __name__)

# Database connection helper
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_or_create_system_accounts(cursor, user_id):
    """Get or create the system accounts needed for capital contributions"""
    accounts = {}

    # Check if Inventory Asset account exists
    cursor.execute("""
        SELECT account_id FROM accounts
        WHERE user_id = %s AND subtype = 'INVENTORY' AND account_type = 'ASSET'
        LIMIT 1
    """, (user_id,))
    result = cursor.fetchone()

    if result:
        accounts['inventory'] = result['account_id']
    else:
        # Create Inventory Asset account
        cursor.execute("""
            INSERT INTO accounts (user_id, account_name, account_type, subtype, is_system)
            VALUES (%s, 'Inventory Asset', 'ASSET', 'INVENTORY', TRUE)
        """, (user_id,))
        accounts['inventory'] = cursor.lastrowid

    # Check if Owner's Equity account exists
    cursor.execute("""
        SELECT account_id FROM accounts
        WHERE user_id = %s AND subtype = 'OWNER_CAPITAL' AND account_type = 'EQUITY'
        LIMIT 1
    """, (user_id,))
    result = cursor.fetchone()

    if result:
        accounts['equity'] = result['account_id']
    else:
        # Create Owner's Equity account
        cursor.execute("""
            INSERT INTO accounts (user_id, account_name, account_type, subtype, is_system)
            VALUES (%s, 'Owner Capital', 'EQUITY', 'OWNER_CAPITAL', TRUE)
        """, (user_id,))
        accounts['equity'] = cursor.lastrowid

    return accounts

def create_ledger_entry(cursor, user_id, account_id, transaction_uuid,
                       transaction_date, description, debit, credit,
                       reference_type, reference_id):
    """Create a single ledger entry"""
    cursor.execute("""
        INSERT INTO ledger (
            user_id, account_id, transaction_uuid, transaction_date,
            description, debit, credit, reference_type, reference_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_id, account_id, transaction_uuid, transaction_date,
          description, debit, credit, reference_type, reference_id))

def get_or_create_product(cursor, user_id, business_id, item_name, category, sku=None):
    """Get existing product or create new one"""

    # Generate SKU if not provided
    if not sku:
        # Simple SKU generation: CATEGORY-PREFIX + counter
        category_prefix = {
            'Switch': 'SW',
            'PCB': 'PCB',
            'Case': 'CASE',
            'Keycaps': 'CAPS',
            'Microcontroller': 'MCU',
            'Wire': 'WIRE',
            'Other': 'MISC'
        }.get(category, 'ITEM')

        # Get next number for this prefix
        cursor.execute("""
            SELECT COUNT(*) FROM products
            WHERE user_id = %s AND sku LIKE %s
        """, (user_id, f"{category_prefix}-%"))
        result = cursor.fetchone()
        count = result['COUNT(*)'] if result else 0
        sku = f"{category_prefix}-{count + 1:04d}"

    # Check if product exists by name (case-insensitive)
    cursor.execute("""
        SELECT product_id, sku FROM products
        WHERE user_id = %s AND LOWER(name) = LOWER(%s) AND is_deleted = FALSE
        LIMIT 1
    """, (user_id, item_name))
    result = cursor.fetchone()

    if result:
        return {'product_id': result['product_id'], 'sku': result['sku'], 'created': False}

    # Product doesn't exist - create it
    cursor.execute("""
        INSERT INTO products (
            user_id, business_id, sku, name, category, unit_of_measure, is_active
        ) VALUES (%s, %s, %s, %s, %s, 'EA', TRUE)
    """, (user_id, business_id, sku, item_name, category))

    product_id = cursor.lastrowid
    return {'product_id': product_id, 'sku': sku, 'created': True}

# ============================================================================
# API ENDPOINTS
# ============================================================================

@ingest_bp.route('/api/ingest/search_products', methods=['GET'])
@login_required
def search_products():
    """Typeahead search for existing products"""
    user_id = current_user.id
    query = request.args.get('q', '').strip()
    business_id = request.args.get('business_id')

    if len(query) < 2:
        return jsonify([])

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Search by name or SKU
        cursor.execute("""
            SELECT product_id, sku, name, category
            FROM products
            WHERE user_id = %s
                AND (business_id = %s OR business_id IS NULL)
                AND is_deleted = FALSE
                AND (LOWER(name) LIKE LOWER(%s) OR LOWER(sku) LIKE LOWER(%s))
            ORDER BY name
            LIMIT 10
        """, (user_id, business_id, f"%{query}%", f"%{query}%"))

        results = cursor.fetchall()
        cursor.close()
        conn.close()

        return jsonify(results)

    except Error as e:
        return jsonify({'error': str(e)}), 500

@ingest_bp.route('/api/ingest/add_item', methods=['POST'])
@login_required
def add_item():
    """
    Add item to inventory via capital contribution
    Creates product if needed, adds inventory layer, posts to ledger
    """
    user_id = current_user.id
    data = request.json

    # Validate required fields
    required = ['item_name', 'category', 'quantity', 'unit_cost']
    if not all(field in data for field in required):
        return jsonify({'error': 'Missing required fields'}), 400

    item_name = data['item_name'].strip()
    category = data['category']
    quantity = float(data['quantity'])
    unit_cost = float(data['unit_cost'])
    business_id = data.get('business_id')
    location_id = data.get('location_id')  # NEW: location support
    session_source = data.get('session_source', 'Manual Entry')
    notes = data.get('notes', '')

    if quantity <= 0 or unit_cost < 0:
        return jsonify({'error': 'Invalid quantity or cost'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get or create system accounts
        accounts = get_or_create_system_accounts(cursor, user_id)

        # Get or create product
        product = get_or_create_product(cursor, user_id, business_id, item_name, category)
        product_id = product['product_id']
        sku = product['sku']

        # Add to inventory_layers
        today = date.today()
        total_value = quantity * unit_cost

        cursor.execute("""
            INSERT INTO inventory_layers (
                user_id, product_id, location_id, session_source,
                quantity_remaining, unit_cost, received_date,
                reference_type, reference_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, product_id, location_id, session_source,
              quantity, unit_cost, today, 'CAPITAL_CONTRIBUTION', None))

        layer_id = cursor.lastrowid

        # Create ledger entries (double-entry accounting)
        transaction_uuid = str(uuid.uuid4())
        description = f"Capital Contribution: {item_name} ({session_source})"

        # DEBIT: Inventory Asset (increase asset)
        create_ledger_entry(
            cursor, user_id, accounts['inventory'], transaction_uuid,
            today, description, total_value, 0.00,
            'CAPITAL_CONTRIBUTION', layer_id
        )

        # CREDIT: Owner's Equity (increase equity)
        create_ledger_entry(
            cursor, user_id, accounts['equity'], transaction_uuid,
            today, description, 0.00, total_value,
            'CAPITAL_CONTRIBUTION', layer_id
        )

        conn.commit()

        response = {
            'success': True,
            'product_id': product_id,
            'sku': sku,
            'layer_id': layer_id,
            'item_name': item_name,
            'category': category,
            'quantity': quantity,
            'unit_cost': unit_cost,
            'total_value': total_value,
            'product_created': product['created'],
            'transaction_uuid': transaction_uuid
        }

        cursor.close()
        conn.close()

        return jsonify(response), 201

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500

@ingest_bp.route('/api/ingest/session_summary', methods=['GET'])
@login_required
def session_summary():
    """Get summary of items added in current session (by location_id or session_source)"""
    try:
        user_id = current_user.id
    except Exception as e:
        return jsonify({'error': f'Auth error: {str(e)}'}), 500

    location_id = request.args.get('location_id', type=int)
    session_source = request.args.get('session_source')

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get all items from this location or session
        if location_id:
            cursor.execute("""
                SELECT
                    il.layer_id,
                    il.product_id,
                    p.sku,
                    p.name,
                    p.category,
                    il.quantity_remaining,
                    il.unit_cost,
                    (il.quantity_remaining * il.unit_cost) as total_value,
                    il.received_date,
                    il.created_at
                FROM inventory_layers il
                JOIN products p ON il.product_id = p.product_id
                WHERE il.user_id = %s
                    AND il.location_id = %s
                    AND il.reference_type = 'CAPITAL_CONTRIBUTION'
                ORDER BY il.created_at DESC
            """, (user_id, location_id))
        else:
            cursor.execute("""
                SELECT
                    il.layer_id,
                    il.product_id,
                    p.sku,
                    p.name,
                    p.category,
                    il.quantity_remaining,
                    il.unit_cost,
                    (il.quantity_remaining * il.unit_cost) as total_value,
                    il.received_date,
                    il.created_at
                FROM inventory_layers il
                JOIN products p ON il.product_id = p.product_id
                WHERE il.user_id = %s
                    AND il.reference_type = 'CAPITAL_CONTRIBUTION'
                ORDER BY il.created_at DESC
            """, (user_id,))

        items = cursor.fetchall()

        # Calculate totals
        total_items = len(items)
        total_quantity = sum(item['quantity_remaining'] for item in items)
        total_value = sum(item['total_value'] for item in items)

        cursor.close()
        conn.close()

        return jsonify({
            'session_source': session_source,
            'items': items,
            'totals': {
                'item_count': total_items,
                'total_quantity': float(total_quantity),
                'total_value': float(total_value)
            }
        })

    except Error as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

@ingest_bp.route('/api/ingest/delete_item', methods=['DELETE'])
@login_required
def delete_item():
    """Delete an item from the current session (undo)"""
    user_id = current_user.id
    layer_id = request.args.get('layer_id', type=int)

    if not layer_id:
        return jsonify({'error': 'Missing layer_id'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verify ownership and get layer info
        cursor.execute("""
            SELECT quantity_remaining, unit_cost
            FROM inventory_layers
            WHERE layer_id = %s AND user_id = %s
        """, (layer_id, user_id))

        layer = cursor.fetchone()
        if not layer:
            return jsonify({'error': 'Layer not found'}), 404

        # Delete ledger entries for this layer
        cursor.execute("""
            DELETE FROM ledger
            WHERE user_id = %s
                AND reference_type = 'CAPITAL_CONTRIBUTION'
                AND reference_id = %s
        """, (user_id, layer_id))

        # Delete inventory layer
        cursor.execute("""
            DELETE FROM inventory_layers
            WHERE layer_id = %s AND user_id = %s
        """, (layer_id, user_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'layer_id': layer_id})

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
