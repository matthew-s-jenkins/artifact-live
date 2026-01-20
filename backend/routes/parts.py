"""
Artifact Live v2 - Parts API

CRUD operations for parts within projects and the parts catalog.

Endpoints:
    POST   /api/projects/<id>/parts  - Add part to project
    GET    /api/projects/<id>/parts  - List parts in project (grouped by set_id)
    PUT    /api/parts/<id>           - Update part details
    DELETE /api/parts/<id>           - Remove part from project
    POST   /api/parts/bulk           - Add multiple parts at once

Catalog:
    POST   /api/catalog              - Add to parts catalog
    GET    /api/catalog              - List catalog entries
    GET    /api/catalog/categories   - List unique categories

Author: Matthew Jenkins
Date: 2026-01-19
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import sqlite3
import uuid
from pathlib import Path


parts_bp = Blueprint('parts', __name__)


def get_db_connection():
    """Get a database connection with row factory."""
    db_path = Path(__file__).parent.parent / "database" / "artifactlive.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row):
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


# =============================================================================
# PARTS ENDPOINTS
# =============================================================================

@parts_bp.route('/projects/<int:project_id>/parts', methods=['POST'])
@login_required
def add_part_to_project(project_id):
    """
    Add a part to a project.

    Request JSON:
        catalog_id: int (optional) - Reference to catalog entry
        custom_name: string (required if no catalog_id) - Ad-hoc part name
        set_id: string (optional) - UUID to group parts sold together
        serial_number: string (optional)
        condition: string (optional) - 'New', 'Used-Like New', 'Used-Good', 'For Parts'
        weight_class: string (optional) - 'light', 'medium', 'heavy'
        estimated_value: float (optional)
        notes: string (optional)

    Returns:
        success: bool
        part: created part object
    """
    data = request.get_json()

    catalog_id = data.get('catalog_id')
    custom_name = data.get('custom_name', '').strip() if data.get('custom_name') else None

    # Must have either catalog_id or custom_name
    if not catalog_id and not custom_name:
        return jsonify(success=False, message="Either catalog_id or custom_name is required."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        if not cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        # If catalog_id provided, verify it exists
        if catalog_id:
            cursor.execute(
                "SELECT catalog_id, name FROM parts_catalog WHERE catalog_id = ?",
                (catalog_id,)
            )
            catalog_entry = cursor.fetchone()
            if not catalog_entry:
                conn.close()
                return jsonify(success=False, message="Catalog entry not found."), 400

        # Validate weight_class if provided
        weight_class = data.get('weight_class', 'medium')
        if weight_class not in ('light', 'medium', 'heavy'):
            weight_class = 'medium'

        # Insert part
        cursor.execute("""
            INSERT INTO project_parts (
                project_id, catalog_id, set_id, custom_name,
                serial_number, condition, weight_class,
                estimated_value, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'IN_SYSTEM', ?)
        """, (
            project_id,
            catalog_id,
            data.get('set_id'),
            custom_name,
            data.get('serial_number'),
            data.get('condition'),
            weight_class,
            data.get('estimated_value'),
            data.get('notes')
        ))

        part_id = cursor.lastrowid
        conn.commit()

        # Fetch created part with catalog info
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.part_id = ?
        """, (part_id,))
        part = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(success=True, part=part), 201

    except Exception as e:
        print(f"[PARTS] Add error: {e}")
        return jsonify(success=False, message="Failed to add part."), 500


@parts_bp.route('/projects/<int:project_id>/parts', methods=['GET'])
@login_required
def list_project_parts(project_id):
    """
    List all parts in a project.

    Query params:
        group_by_set: bool (optional) - Group parts by set_id

    Returns:
        success: bool
        parts: array of part objects
        status_counts: object with counts by status
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        if not cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        # Get parts
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.project_id = ?
            ORDER BY pp.set_id NULLS LAST, pp.created_at DESC
        """, (project_id,))

        parts = [row_to_dict(row) for row in cursor.fetchall()]

        # Calculate status counts
        status_counts = {}
        for part in parts:
            status = part['status']
            status_counts[status] = status_counts.get(status, 0) + 1

        conn.close()

        return jsonify(success=True, parts=parts, status_counts=status_counts)

    except Exception as e:
        print(f"[PARTS] List error: {e}")
        return jsonify(success=False, message="Failed to retrieve parts."), 500


@parts_bp.route('/parts/<int:part_id>', methods=['PUT'])
@login_required
def update_part(part_id):
    """
    Update a part's details.

    Request JSON (all fields optional):
        custom_name: string
        serial_number: string
        condition: string
        weight_class: string
        estimated_value: float
        actual_sale_price: float
        shipping_paid: float
        fees_paid: float
        status: string (IN_SYSTEM, LISTED, SOLD, KEPT, TRASHED, IN_PROJECT)
        listing_url: string
        sold_date: string (YYYY-MM-DD)
        notes: string
        set_id: string

    Returns:
        success: bool
        part: updated part object
    """
    data = request.get_json()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify part exists and belongs to user's project
        cursor.execute("""
            SELECT pp.part_id, p.user_id
            FROM project_parts pp
            JOIN projects p ON pp.project_id = p.project_id
            WHERE pp.part_id = ? AND p.user_id = ?
        """, (part_id, current_user.id))

        if not cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Part not found."), 404

        # Build update query
        updatable_fields = [
            'custom_name', 'serial_number', 'condition', 'weight_class',
            'estimated_value', 'actual_sale_price', 'shipping_paid', 'fees_paid',
            'status', 'listing_url', 'sold_date', 'notes', 'set_id'
        ]

        updates = []
        params = []

        for field in updatable_fields:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field])

        if not updates:
            conn.close()
            return jsonify(success=False, message="No fields to update."), 400

        # Validate status if provided
        if 'status' in data:
            valid_statuses = ('IN_SYSTEM', 'LISTED', 'SOLD', 'KEPT', 'TRASHED', 'IN_PROJECT')
            if data['status'] not in valid_statuses:
                conn.close()
                return jsonify(success=False, message=f"Invalid status. Must be one of: {valid_statuses}"), 400

        # Validate weight_class if provided
        if 'weight_class' in data:
            if data['weight_class'] not in ('light', 'medium', 'heavy'):
                conn.close()
                return jsonify(success=False, message="Invalid weight_class. Must be: light, medium, heavy"), 400

        params.append(part_id)

        cursor.execute(f"""
            UPDATE project_parts SET {', '.join(updates)} WHERE part_id = ?
        """, params)

        conn.commit()

        # Fetch updated part
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.part_id = ?
        """, (part_id,))
        part = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(success=True, part=part)

    except Exception as e:
        print(f"[PARTS] Update error: {e}")
        return jsonify(success=False, message="Failed to update part."), 500


@parts_bp.route('/parts/<int:part_id>', methods=['DELETE'])
@login_required
def delete_part(part_id):
    """
    Delete a part from a project.

    Returns:
        success: bool
        message: string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify part exists and belongs to user's project
        cursor.execute("""
            SELECT pp.part_id, pp.custom_name, pc.name as catalog_name
            FROM project_parts pp
            JOIN projects p ON pp.project_id = p.project_id
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.part_id = ? AND p.user_id = ?
        """, (part_id, current_user.id))

        part = cursor.fetchone()
        if not part:
            conn.close()
            return jsonify(success=False, message="Part not found."), 404

        part_name = part['custom_name'] or part['catalog_name'] or f"Part #{part_id}"

        cursor.execute("DELETE FROM project_parts WHERE part_id = ?", (part_id,))
        conn.commit()
        conn.close()

        return jsonify(success=True, message=f"Part '{part_name}' deleted.")

    except Exception as e:
        print(f"[PARTS] Delete error: {e}")
        return jsonify(success=False, message="Failed to delete part."), 500


@parts_bp.route('/parts/bulk', methods=['POST'])
@login_required
def bulk_add_parts():
    """
    Add multiple parts to a project at once.

    Request JSON:
        project_id: int (required)
        parts: array of part objects (same fields as single add)
        set_id: string (optional) - Apply same set_id to all parts

    Returns:
        success: bool
        parts: array of created part objects
        count: number of parts created
    """
    data = request.get_json()

    project_id = data.get('project_id')
    parts_data = data.get('parts', [])
    shared_set_id = data.get('set_id')

    if not project_id:
        return jsonify(success=False, message="project_id is required."), 400
    if not parts_data or not isinstance(parts_data, list):
        return jsonify(success=False, message="parts array is required."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        if not cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        created_parts = []

        for part_data in parts_data:
            catalog_id = part_data.get('catalog_id')
            custom_name = part_data.get('custom_name', '').strip() if part_data.get('custom_name') else None

            if not catalog_id and not custom_name:
                continue  # Skip invalid entries

            weight_class = part_data.get('weight_class', 'medium')
            if weight_class not in ('light', 'medium', 'heavy'):
                weight_class = 'medium'

            # Use shared set_id if provided, otherwise use individual
            set_id = shared_set_id or part_data.get('set_id')

            cursor.execute("""
                INSERT INTO project_parts (
                    project_id, catalog_id, set_id, custom_name,
                    serial_number, condition, weight_class,
                    estimated_value, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'IN_SYSTEM', ?)
            """, (
                project_id,
                catalog_id,
                set_id,
                custom_name,
                part_data.get('serial_number'),
                part_data.get('condition'),
                weight_class,
                part_data.get('estimated_value'),
                part_data.get('notes')
            ))

            part_id = cursor.lastrowid

            # Fetch created part
            cursor.execute("""
                SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category
                FROM project_parts pp
                LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
                WHERE pp.part_id = ?
            """, (part_id,))
            created_parts.append(row_to_dict(cursor.fetchone()))

        conn.commit()
        conn.close()

        return jsonify(
            success=True,
            parts=created_parts,
            count=len(created_parts)
        ), 201

    except Exception as e:
        print(f"[PARTS] Bulk add error: {e}")
        return jsonify(success=False, message="Failed to add parts."), 500


# =============================================================================
# CATALOG ENDPOINTS
# =============================================================================

@parts_bp.route('/catalog', methods=['POST'])
@login_required
def add_catalog_entry():
    """
    Add an entry to the parts catalog.

    Request JSON:
        subsection_id: int (required)
        category: string (required) - e.g., 'GPU', 'CPU', 'RAM'
        name: string (required) - e.g., 'NVIDIA GTX 1080'
        sku: string (optional)
        default_price: float (optional)
        weight_class: string (optional) - 'light', 'medium', 'heavy'
        notes: string (optional)

    Returns:
        success: bool
        catalog_entry: created entry
    """
    data = request.get_json()

    subsection_id = data.get('subsection_id')
    category = data.get('category', '').strip()
    name = data.get('name', '').strip()

    if not subsection_id:
        return jsonify(success=False, message="subsection_id is required."), 400
    if not category:
        return jsonify(success=False, message="category is required."), 400
    if not name:
        return jsonify(success=False, message="name is required."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify subsection exists and belongs to user
        cursor.execute(
            "SELECT subsection_id FROM subsections WHERE subsection_id = ? AND user_id = ?",
            (subsection_id, current_user.id)
        )
        if not cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Invalid subsection."), 400

        weight_class = data.get('weight_class')
        if weight_class and weight_class not in ('light', 'medium', 'heavy'):
            weight_class = None

        cursor.execute("""
            INSERT INTO parts_catalog (
                subsection_id, category, name, sku,
                default_price, weight_class, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            subsection_id,
            category,
            name,
            data.get('sku'),
            data.get('default_price'),
            weight_class,
            data.get('notes')
        ))

        catalog_id = cursor.lastrowid
        conn.commit()

        cursor.execute("SELECT * FROM parts_catalog WHERE catalog_id = ?", (catalog_id,))
        entry = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(success=True, catalog_entry=entry), 201

    except Exception as e:
        print(f"[CATALOG] Add error: {e}")
        return jsonify(success=False, message="Failed to add catalog entry."), 500


@parts_bp.route('/catalog', methods=['GET'])
@login_required
def list_catalog():
    """
    List catalog entries.

    Query params:
        subsection_id: int (optional) - Filter by subsection
        category: string (optional) - Filter by category

    Returns:
        success: bool
        catalog: array of catalog entries
    """
    subsection_id = request.args.get('subsection_id', type=int)
    category = request.args.get('category')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get user's subsection IDs
        cursor.execute(
            "SELECT subsection_id FROM subsections WHERE user_id = ?",
            (current_user.id,)
        )
        user_subsections = [row['subsection_id'] for row in cursor.fetchall()]

        if not user_subsections:
            conn.close()
            return jsonify(success=True, catalog=[])

        # Build query
        placeholders = ','.join('?' * len(user_subsections))
        query = f"""
            SELECT pc.*, s.name as subsection_name
            FROM parts_catalog pc
            JOIN subsections s ON pc.subsection_id = s.subsection_id
            WHERE pc.subsection_id IN ({placeholders})
        """
        params = list(user_subsections)

        if subsection_id:
            query += " AND pc.subsection_id = ?"
            params.append(subsection_id)

        if category:
            query += " AND pc.category = ?"
            params.append(category)

        query += " ORDER BY pc.category, pc.name"

        cursor.execute(query, params)
        catalog = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify(success=True, catalog=catalog)

    except Exception as e:
        print(f"[CATALOG] List error: {e}")
        return jsonify(success=False, message="Failed to retrieve catalog."), 500


@parts_bp.route('/catalog/categories', methods=['GET'])
@login_required
def list_catalog_categories():
    """
    List unique categories in the catalog.

    Query params:
        subsection_id: int (optional) - Filter by subsection

    Returns:
        success: bool
        categories: array of category strings
    """
    subsection_id = request.args.get('subsection_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get user's subsection IDs
        cursor.execute(
            "SELECT subsection_id FROM subsections WHERE user_id = ?",
            (current_user.id,)
        )
        user_subsections = [row['subsection_id'] for row in cursor.fetchall()]

        if not user_subsections:
            conn.close()
            return jsonify(success=True, categories=[])

        placeholders = ','.join('?' * len(user_subsections))
        query = f"""
            SELECT DISTINCT category FROM parts_catalog
            WHERE subsection_id IN ({placeholders})
        """
        params = list(user_subsections)

        if subsection_id:
            query += " AND subsection_id = ?"
            params.append(subsection_id)

        query += " ORDER BY category"

        cursor.execute(query, params)
        categories = [row['category'] for row in cursor.fetchall()]

        conn.close()

        return jsonify(success=True, categories=categories)

    except Exception as e:
        print(f"[CATALOG] Categories error: {e}")
        return jsonify(success=False, message="Failed to retrieve categories."), 500
