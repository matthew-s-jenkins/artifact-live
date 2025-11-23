"""
Artifact Live - Locations API
Manage physical/logical locations for inventory storage
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

load_dotenv()

locations_bp = Blueprint('locations', __name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

@locations_bp.route('/api/locations', methods=['GET'])
@login_required
def get_locations():
    """Get all locations for the current user"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if business_id:
            cursor.execute("""
                SELECT * FROM locations
                WHERE user_id = %s AND business_id = %s AND is_active = TRUE
                ORDER BY name
            """, (user_id, business_id))
        else:
            cursor.execute("""
                SELECT * FROM locations
                WHERE user_id = %s AND is_active = TRUE
                ORDER BY name
            """, (user_id,))

        locations = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(locations)

    except Error as e:
        return jsonify({'error': str(e)}), 500

@locations_bp.route('/api/locations', methods=['POST'])
@login_required
def create_location():
    """Create a new location"""
    user_id = current_user.id
    data = request.json

    # Validate required fields
    if not data.get('name'):
        return jsonify({'error': 'Location name is required'}), 400

    name = data['name'].strip()
    description = data.get('description', '').strip()
    location_type = data.get('location_type', 'Storage')
    business_id = data.get('business_id')

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if location with same name already exists
        cursor.execute("""
            SELECT location_id FROM locations
            WHERE user_id = %s AND name = %s
        """, (user_id, name))

        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Location with this name already exists'}), 400

        # Create location
        cursor.execute("""
            INSERT INTO locations (user_id, business_id, name, description, location_type)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, business_id, name, description, location_type))

        location_id = cursor.lastrowid
        conn.commit()

        # Fetch the created location
        cursor.execute("SELECT * FROM locations WHERE location_id = %s", (location_id,))
        location = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify(location), 201

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500

@locations_bp.route('/api/locations/<int:location_id>', methods=['PUT'])
@login_required
def update_location(location_id):
    """Update a location"""
    user_id = current_user.id
    data = request.json

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verify ownership
        cursor.execute("""
            SELECT location_id FROM locations
            WHERE location_id = %s AND user_id = %s
        """, (location_id, user_id))

        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Location not found'}), 404

        # Update location
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        location_type = data.get('location_type', 'Storage')
        is_active = data.get('is_active', True)

        cursor.execute("""
            UPDATE locations
            SET name = %s, description = %s, location_type = %s, is_active = %s
            WHERE location_id = %s
        """, (name, description, location_type, is_active, location_id))

        conn.commit()

        # Fetch updated location
        cursor.execute("SELECT * FROM locations WHERE location_id = %s", (location_id,))
        location = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify(location)

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500

@locations_bp.route('/api/locations/<int:location_id>', methods=['DELETE'])
@login_required
def delete_location(location_id):
    """Soft delete a location (set is_active = FALSE)"""
    user_id = current_user.id

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verify ownership
        cursor.execute("""
            SELECT location_id FROM locations
            WHERE location_id = %s AND user_id = %s
        """, (location_id, user_id))

        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Location not found'}), 404

        # Soft delete
        cursor.execute("""
            UPDATE locations
            SET is_active = FALSE
            WHERE location_id = %s
        """, (location_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'location_id': location_id})

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
