"""
Artifact Live v2 - Parts API

CRUD operations for parts within projects, loose inventory, and the parts catalog.

Endpoints:
    POST   /api/projects/<id>/parts  - Add part to project
    GET    /api/projects/<id>/parts  - List parts in project (grouped by set_id)
    PUT    /api/parts/<id>           - Update part details (incl. quantity, is_mystery)
    DELETE /api/parts/<id>           - Remove part
    POST   /api/parts/bulk           - Add multiple parts at once

Inventory (loose parts without project):
    POST   /api/inventory            - Create loose inventory part (with quantity, is_mystery)
    GET    /api/inventory            - List loose inventory (filter by is_mystery)
    GET    /api/inventory/summary    - Get inventory availability breakdown
    POST   /api/parts/<id>/allocate  - Allocate loose part to project (supports partial qty, staged)
    POST   /api/parts/<id>/deallocate - Return part to loose inventory

Catalog:
    POST   /api/catalog              - Add to parts catalog
    GET    /api/catalog              - List catalog entries
    GET    /api/catalog/categories   - List unique categories
    POST   /api/catalog/seed-keyboard - Seed default keyboard categories
    PUT    /api/catalog/<id>         - Update catalog entry
    DELETE /api/catalog/<id>         - Delete catalog entry

Author: Matthew Jenkins
Date: 2026-01-19
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import sqlite3
import uuid
import json
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
        for_sale: bool (optional) - Is this part available for sale?
        quantity: int (optional, default 1) - Quantity for bulk items
        is_mystery: bool (optional, default false) - Unknown/unidentified part
        metadata: object (optional) - Flexible attributes (hot_swap, lubed, etc.)
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

        # Verify project exists and belongs to user, get subsection_id
        cursor.execute(
            "SELECT project_id, subsection_id FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project = cursor.fetchone()
        if not project:
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

        # Validate quantity (default 1, minimum 1)
        quantity = data.get('quantity', 1)
        if not isinstance(quantity, int) or quantity < 1:
            quantity = 1

        # Handle is_mystery flag
        is_mystery = 1 if data.get('is_mystery') else 0

        # Handle metadata as JSON
        metadata = data.get('metadata')
        metadata_json = json.dumps(metadata) if metadata else None

        # Insert part with subsection_id derived from project
        cursor.execute("""
            INSERT INTO project_parts (
                project_id, subsection_id, catalog_id, set_id, custom_name,
                serial_number, condition, weight_class,
                estimated_value, for_sale, quantity, is_mystery,
                metadata, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_SYSTEM', ?)
        """, (
            project_id,
            project['subsection_id'],
            catalog_id,
            data.get('set_id'),
            custom_name,
            data.get('serial_number'),
            data.get('condition'),
            weight_class,
            data.get('estimated_value'),
            1 if data.get('for_sale') else 0,
            quantity,
            is_mystery,
            metadata_json,
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

        # Parse metadata back to dict
        if part and part.get('metadata'):
            part['metadata'] = json.loads(part['metadata'])

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
        status: string (IN_SYSTEM, LISTED, SOLD, KEPT, TRASHED, IN_PROJECT, ALLOCATED)
        listing_url: string
        sold_date: string (YYYY-MM-DD)
        for_sale: bool
        quantity: int (must be >= 1)
        is_mystery: bool
        metadata: object (flexible attributes)
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

        # Verify part exists and belongs to user
        # Check both project-assigned parts AND loose inventory (via subsection)
        cursor.execute("""
            SELECT pp.part_id, pp.project_id, pp.subsection_id
            FROM project_parts pp
            LEFT JOIN projects p ON pp.project_id = p.project_id
            LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
            WHERE pp.part_id = ?
              AND (p.user_id = ? OR s.user_id = ?)
        """, (part_id, current_user.id, current_user.id))

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

        # Handle for_sale specially (convert to int)
        if 'for_sale' in data:
            updates.append("for_sale = ?")
            params.append(1 if data['for_sale'] else 0)

        # Handle quantity specially (validate >= 1)
        if 'quantity' in data:
            quantity = data['quantity']
            if isinstance(quantity, int) and quantity >= 1:
                updates.append("quantity = ?")
                params.append(quantity)

        # Handle is_mystery specially (convert to int)
        if 'is_mystery' in data:
            updates.append("is_mystery = ?")
            params.append(1 if data['is_mystery'] else 0)

        # Handle metadata specially (convert to JSON)
        if 'metadata' in data:
            updates.append("metadata = ?")
            metadata_json = json.dumps(data['metadata']) if data['metadata'] else None
            params.append(metadata_json)

        if not updates:
            conn.close()
            return jsonify(success=False, message="No fields to update."), 400

        # Validate status if provided
        if 'status' in data:
            valid_statuses = ('IN_SYSTEM', 'LISTED', 'SOLD', 'KEPT', 'TRASHED', 'IN_PROJECT', 'ALLOCATED', 'STAGED')
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

        # Parse metadata back to dict
        if part and part.get('metadata'):
            part['metadata'] = json.loads(part['metadata'])

        conn.close()

        return jsonify(success=True, part=part)

    except Exception as e:
        print(f"[PARTS] Update error: {e}")
        return jsonify(success=False, message="Failed to update part."), 500


@parts_bp.route('/parts/<int:part_id>', methods=['DELETE'])
@login_required
def delete_part(part_id):
    """
    Delete a part (from project or loose inventory).

    Returns:
        success: bool
        message: string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify part exists and belongs to user (via project OR subsection)
        cursor.execute("""
            SELECT pp.part_id, pp.custom_name, pc.name as catalog_name
            FROM project_parts pp
            LEFT JOIN projects p ON pp.project_id = p.project_id
            LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.part_id = ?
              AND (p.user_id = ? OR s.user_id = ?)
        """, (part_id, current_user.id, current_user.id))

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
# LOOSE INVENTORY ENDPOINTS
# =============================================================================

@parts_bp.route('/inventory', methods=['POST'])
@login_required
def create_loose_part():
    """
    Create a loose inventory part (not assigned to any project).

    Request JSON:
        subsection_id: int (required) - Which subsection this part belongs to
        catalog_id: int (optional) - Reference to catalog entry
        custom_name: string (required if no catalog_id) - Ad-hoc part name
        serial_number: string (optional)
        condition: string (optional) - 'New', 'Used-Like New', 'Used-Good', 'For Parts'
        weight_class: string (optional) - 'light', 'medium', 'heavy'
        estimated_value: float (optional)
        for_sale: bool (optional) - Is this part available for sale?
        quantity: int (optional, default 1) - Quantity for bulk items
        is_mystery: bool (optional, default false) - Unknown/unidentified part
        metadata: object (optional) - Flexible attributes (hot_swap, lubed, etc.)
        notes: string (optional)

    Returns:
        success: bool
        part: created part object
    """
    data = request.get_json()

    subsection_id = data.get('subsection_id')
    catalog_id = data.get('catalog_id')
    custom_name = data.get('custom_name', '').strip() if data.get('custom_name') else None

    if not subsection_id:
        return jsonify(success=False, message="subsection_id is required for loose inventory."), 400

    if not catalog_id and not custom_name:
        return jsonify(success=False, message="Either catalog_id or custom_name is required."), 400

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

        # If catalog_id provided, verify it exists
        if catalog_id:
            cursor.execute(
                "SELECT catalog_id, name FROM parts_catalog WHERE catalog_id = ?",
                (catalog_id,)
            )
            if not cursor.fetchone():
                conn.close()
                return jsonify(success=False, message="Catalog entry not found."), 400

        # Validate weight_class
        weight_class = data.get('weight_class', 'medium')
        if weight_class not in ('light', 'medium', 'heavy'):
            weight_class = 'medium'

        # Validate quantity (default 1, minimum 1)
        quantity = data.get('quantity', 1)
        if not isinstance(quantity, int) or quantity < 1:
            quantity = 1

        # Handle is_mystery flag
        is_mystery = 1 if data.get('is_mystery') else 0

        # Handle metadata as JSON
        metadata = data.get('metadata')
        metadata_json = json.dumps(metadata) if metadata else None

        # Insert loose part (project_id = NULL)
        cursor.execute("""
            INSERT INTO project_parts (
                project_id, subsection_id, catalog_id, custom_name,
                serial_number, condition, weight_class,
                estimated_value, for_sale, quantity, is_mystery,
                metadata, status, notes
            ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_SYSTEM', ?)
        """, (
            subsection_id,
            catalog_id,
            custom_name,
            data.get('serial_number'),
            data.get('condition'),
            weight_class,
            data.get('estimated_value'),
            1 if data.get('for_sale') else 0,
            quantity,
            is_mystery,
            metadata_json,
            data.get('notes')
        ))

        part_id = cursor.lastrowid
        conn.commit()

        # Fetch created part
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category,
                   s.name as subsection_name
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
            WHERE pp.part_id = ?
        """, (part_id,))
        part = row_to_dict(cursor.fetchone())

        if part and part.get('metadata'):
            part['metadata'] = json.loads(part['metadata'])

        conn.close()

        return jsonify(success=True, part=part), 201

    except Exception as e:
        print(f"[INVENTORY] Create error: {e}")
        return jsonify(success=False, message="Failed to create part."), 500


@parts_bp.route('/inventory', methods=['GET'])
@login_required
def list_loose_inventory():
    """
    List all loose inventory parts (not assigned to any project).

    Query params:
        subsection_id: int (optional) - Filter by subsection
        for_sale: bool (optional) - Filter by for_sale status
        category: string (optional) - Filter by catalog category
        is_mystery: bool (optional) - Filter by mystery part status

    Returns:
        success: bool
        parts: array of part objects
        summary: object with counts (total_parts, total_quantity, mystery_count)
    """
    subsection_id = request.args.get('subsection_id', type=int)
    for_sale = request.args.get('for_sale')
    category = request.args.get('category')
    is_mystery = request.args.get('is_mystery')

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
            return jsonify(success=True, parts=[], summary={'total_parts': 0, 'total_quantity': 0, 'mystery_count': 0})

        # Build query for loose parts
        placeholders = ','.join('?' * len(user_subsections))
        query = f"""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category,
                   s.name as subsection_name
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
            WHERE pp.project_id IS NULL
              AND pp.subsection_id IN ({placeholders})
        """
        params = list(user_subsections)

        if subsection_id:
            query += " AND pp.subsection_id = ?"
            params.append(subsection_id)

        if for_sale is not None:
            query += " AND pp.for_sale = ?"
            params.append(1 if for_sale in ('true', '1', 'True') else 0)

        if category:
            query += " AND pc.category = ?"
            params.append(category)

        if is_mystery is not None:
            query += " AND pp.is_mystery = ?"
            params.append(1 if is_mystery in ('true', '1', 'True') else 0)

        query += " ORDER BY pp.created_at DESC"

        cursor.execute(query, params)
        parts = [row_to_dict(row) for row in cursor.fetchall()]

        # Parse metadata for each part and calculate summary
        total_quantity = 0
        mystery_count = 0
        for part in parts:
            if part.get('metadata'):
                part['metadata'] = json.loads(part['metadata'])
            total_quantity += part.get('quantity', 1) or 1
            if part.get('is_mystery'):
                mystery_count += 1

        conn.close()

        summary = {
            'total_parts': len(parts),
            'total_quantity': total_quantity,
            'mystery_count': mystery_count
        }

        return jsonify(success=True, parts=parts, summary=summary)

    except Exception as e:
        print(f"[INVENTORY] List error: {e}")
        return jsonify(success=False, message="Failed to retrieve inventory."), 500


@parts_bp.route('/inventory/summary', methods=['GET'])
@login_required
def get_inventory_summary():
    """
    Get comprehensive inventory summary showing availability breakdown.

    Query params:
        subsection_id: int (optional) - Filter by subsection
        category: string (optional) - Filter by catalog category

    Returns:
        success: bool
        summary: {
            total: { parts: int, quantity: int },
            available: { parts: int, quantity: int },
            in_projects: {
                total: { parts: int, quantity: int },
                for_sale: { parts: int, quantity: int },
                personal: { parts: int, quantity: int },
                staged: { parts: int, quantity: int }
            },
            mystery: { parts: int, quantity: int }
        }
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
            empty_count = {'parts': 0, 'quantity': 0}
            return jsonify(success=True, summary={
                'total': empty_count,
                'available': empty_count,
                'in_projects': {
                    'total': empty_count,
                    'for_sale': empty_count,
                    'personal': empty_count,
                    'staged': empty_count
                },
                'mystery': empty_count
            })

        # Build base query conditions
        placeholders = ','.join('?' * len(user_subsections))
        base_condition = f"pp.subsection_id IN ({placeholders})"
        params = list(user_subsections)

        if subsection_id:
            base_condition += " AND pp.subsection_id = ?"
            params.append(subsection_id)

        if category:
            base_condition += " AND pc.category = ?"
            params.append(category)

        # Query for complete breakdown
        cursor.execute(f"""
            SELECT
                -- Total
                COUNT(pp.part_id) as total_parts,
                COALESCE(SUM(pp.quantity), 0) as total_quantity,
                -- Available (loose inventory)
                SUM(CASE WHEN pp.project_id IS NULL THEN 1 ELSE 0 END) as available_parts,
                COALESCE(SUM(CASE WHEN pp.project_id IS NULL THEN pp.quantity ELSE 0 END), 0) as available_quantity,
                -- In Projects total
                SUM(CASE WHEN pp.project_id IS NOT NULL THEN 1 ELSE 0 END) as in_project_parts,
                COALESCE(SUM(CASE WHEN pp.project_id IS NOT NULL THEN pp.quantity ELSE 0 END), 0) as in_project_quantity,
                -- For Sale (project.for_sale = 1)
                SUM(CASE WHEN pp.project_id IS NOT NULL AND p.for_sale = 1 THEN 1 ELSE 0 END) as for_sale_parts,
                COALESCE(SUM(CASE WHEN pp.project_id IS NOT NULL AND p.for_sale = 1 THEN pp.quantity ELSE 0 END), 0) as for_sale_quantity,
                -- Personal (project.for_sale = 0, not staged)
                SUM(CASE WHEN pp.project_id IS NOT NULL AND p.for_sale = 0 AND pp.status != 'STAGED' THEN 1 ELSE 0 END) as personal_parts,
                COALESCE(SUM(CASE WHEN pp.project_id IS NOT NULL AND p.for_sale = 0 AND pp.status != 'STAGED' THEN pp.quantity ELSE 0 END), 0) as personal_quantity,
                -- Staged
                SUM(CASE WHEN pp.status = 'STAGED' THEN 1 ELSE 0 END) as staged_parts,
                COALESCE(SUM(CASE WHEN pp.status = 'STAGED' THEN pp.quantity ELSE 0 END), 0) as staged_quantity,
                -- Mystery
                SUM(CASE WHEN pp.is_mystery = 1 THEN 1 ELSE 0 END) as mystery_parts,
                COALESCE(SUM(CASE WHEN pp.is_mystery = 1 THEN pp.quantity ELSE 0 END), 0) as mystery_quantity
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            LEFT JOIN projects p ON pp.project_id = p.project_id
            WHERE {base_condition}
        """, params)

        row = cursor.fetchone()
        conn.close()

        summary = {
            'total': {
                'parts': row['total_parts'] or 0,
                'quantity': row['total_quantity'] or 0
            },
            'available': {
                'parts': row['available_parts'] or 0,
                'quantity': row['available_quantity'] or 0
            },
            'in_projects': {
                'total': {
                    'parts': row['in_project_parts'] or 0,
                    'quantity': row['in_project_quantity'] or 0
                },
                'for_sale': {
                    'parts': row['for_sale_parts'] or 0,
                    'quantity': row['for_sale_quantity'] or 0
                },
                'personal': {
                    'parts': row['personal_parts'] or 0,
                    'quantity': row['personal_quantity'] or 0
                },
                'staged': {
                    'parts': row['staged_parts'] or 0,
                    'quantity': row['staged_quantity'] or 0
                }
            },
            'mystery': {
                'parts': row['mystery_parts'] or 0,
                'quantity': row['mystery_quantity'] or 0
            }
        }

        return jsonify(success=True, summary=summary)

    except Exception as e:
        print(f"[INVENTORY] Summary error: {e}")
        return jsonify(success=False, message="Failed to retrieve inventory summary."), 500


@parts_bp.route('/parts/<int:part_id>/allocate', methods=['POST'])
@login_required
def allocate_part_to_project(part_id):
    """
    Allocate a loose inventory part (or portion) to a project.

    Supports partial allocation: allocate 67 of 90 switches, leaving 23 in inventory.
    When allocating less than total quantity, the row is split.

    Request JSON:
        project_id: int (required) - Project to allocate to
        quantity: int (optional) - Quantity to allocate (defaults to all)
        staged: bool (optional) - If true, mark as STAGED instead of ALLOCATED (plan mode)

    Returns:
        success: bool
        part: allocated part object
        remaining: remaining inventory part (if split occurred)
    """
    data = request.get_json()
    project_id = data.get('project_id')
    requested_qty = data.get('quantity')
    staged = data.get('staged', False)

    if not project_id:
        return jsonify(success=False, message="project_id is required."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify part exists, is loose (no project), and belongs to user
        cursor.execute("""
            SELECT pp.*, s.user_id
            FROM project_parts pp
            JOIN subsections s ON pp.subsection_id = s.subsection_id
            WHERE pp.part_id = ?
              AND pp.project_id IS NULL
              AND s.user_id = ?
        """, (part_id, current_user.id))

        part_row = cursor.fetchone()
        if not part_row:
            conn.close()
            return jsonify(success=False, message="Part not found or already allocated."), 404

        part_data = row_to_dict(part_row)
        available_qty = part_data.get('quantity', 1) or 1

        # Determine allocation quantity
        if requested_qty is None:
            allocate_qty = available_qty  # Allocate all
        else:
            allocate_qty = int(requested_qty)

        # Validate quantity
        if allocate_qty < 1:
            conn.close()
            return jsonify(success=False, message="Quantity must be at least 1."), 400

        if allocate_qty > available_qty:
            conn.close()
            return jsonify(
                success=False,
                message=f"Cannot allocate {allocate_qty}. Only {available_qty} available."
            ), 400

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id, subsection_id FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project = cursor.fetchone()
        if not project:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        # Determine status based on staged flag
        new_status = 'STAGED' if staged else 'ALLOCATED'
        remaining_part = None

        if allocate_qty == available_qty:
            # Allocate entire part (no split needed)
            cursor.execute("""
                UPDATE project_parts
                SET project_id = ?, status = ?
                WHERE part_id = ?
            """, (project_id, new_status, part_id))
            allocated_part_id = part_id
        else:
            # Partial allocation - split the row
            remaining_qty = available_qty - allocate_qty

            # Update original row to have remaining quantity
            cursor.execute("""
                UPDATE project_parts SET quantity = ? WHERE part_id = ?
            """, (remaining_qty, part_id))

            # Create new row for allocated portion
            cursor.execute("""
                INSERT INTO project_parts (
                    project_id, subsection_id, catalog_id, set_id, custom_name,
                    serial_number, condition, weight_class, estimated_value,
                    for_sale, quantity, is_mystery, metadata, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                part_data['subsection_id'],
                part_data['catalog_id'],
                part_data['set_id'],
                part_data['custom_name'],
                part_data['serial_number'],
                part_data['condition'],
                part_data['weight_class'],
                part_data['estimated_value'],
                part_data['for_sale'],
                allocate_qty,
                part_data['is_mystery'],
                part_data['metadata'],
                new_status,
                part_data['notes']
            ))
            allocated_part_id = cursor.lastrowid

            # Fetch remaining part info
            cursor.execute("""
                SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category,
                       s.name as subsection_name
                FROM project_parts pp
                LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
                LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
                WHERE pp.part_id = ?
            """, (part_id,))
            remaining_part = row_to_dict(cursor.fetchone())
            if remaining_part and remaining_part.get('metadata'):
                remaining_part['metadata'] = json.loads(remaining_part['metadata'])

        conn.commit()

        # Fetch allocated part
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category,
                   s.name as subsection_name
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
            WHERE pp.part_id = ?
        """, (allocated_part_id,))
        part = row_to_dict(cursor.fetchone())

        if part and part.get('metadata'):
            part['metadata'] = json.loads(part['metadata'])

        conn.close()

        response = {
            'success': True,
            'part': part,
            'message': f"{allocate_qty} allocated to project" + (" (staged)" if staged else "")
        }
        if remaining_part:
            response['remaining'] = remaining_part

        return jsonify(**response)

    except Exception as e:
        print(f"[PARTS] Allocate error: {e}")
        return jsonify(success=False, message="Failed to allocate part."), 500


@parts_bp.route('/parts/<int:part_id>/deallocate', methods=['POST'])
@login_required
def deallocate_part_from_project(part_id):
    """
    Remove a part from a project back to loose inventory.

    Returns:
        success: bool
        part: updated part object
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify part exists, is in a project, and belongs to user
        cursor.execute("""
            SELECT pp.part_id, pp.project_id, pp.subsection_id
            FROM project_parts pp
            JOIN projects p ON pp.project_id = p.project_id
            WHERE pp.part_id = ?
              AND pp.project_id IS NOT NULL
              AND p.user_id = ?
        """, (part_id, current_user.id))

        part_row = cursor.fetchone()
        if not part_row:
            conn.close()
            return jsonify(success=False, message="Part not found or not in a project."), 404

        # Deallocate part (set project_id to NULL)
        cursor.execute("""
            UPDATE project_parts
            SET project_id = NULL, status = 'IN_SYSTEM'
            WHERE part_id = ?
        """, (part_id,))

        conn.commit()

        # Fetch updated part
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category,
                   s.name as subsection_name
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
            WHERE pp.part_id = ?
        """, (part_id,))
        part = row_to_dict(cursor.fetchone())

        if part and part.get('metadata'):
            part['metadata'] = json.loads(part['metadata'])

        conn.close()

        return jsonify(success=True, part=part, message="Part returned to loose inventory.")

    except Exception as e:
        print(f"[PARTS] Deallocate error: {e}")
        return jsonify(success=False, message="Failed to deallocate part."), 500


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


# Default keyboard categories with sample entries
KEYBOARD_CATALOG_DEFAULTS = {
    'Switch': [
        {'name': 'Cherry MX Red', 'notes': 'Linear, 45g'},
        {'name': 'Cherry MX Blue', 'notes': 'Clicky, 50g'},
        {'name': 'Cherry MX Brown', 'notes': 'Tactile, 45g'},
        {'name': 'Gateron Yellow', 'notes': 'Linear, 50g'},
        {'name': 'Gateron Milky Yellow', 'notes': 'Linear, 50g, milky housing'},
    ],
    'Keycap': [
        {'name': 'Generic PBT Keycaps', 'notes': 'PBT material'},
        {'name': 'Generic ABS Keycaps', 'notes': 'ABS material'},
    ],
    'Case': [
        {'name': 'Generic 60% Case', 'notes': 'Plastic 60% case'},
        {'name': 'Generic 65% Case', 'notes': 'Plastic 65% case'},
        {'name': 'Generic TKL Case', 'notes': 'Plastic TKL case'},
    ],
    'PCB': [
        {'name': 'Generic 60% PCB', 'notes': 'Hot-swap 60% PCB'},
        {'name': 'Generic 65% PCB', 'notes': 'Hot-swap 65% PCB'},
    ],
    'Plate': [
        {'name': 'Aluminum Plate', 'notes': 'Aluminum mounting plate'},
        {'name': 'Brass Plate', 'notes': 'Brass mounting plate'},
        {'name': 'FR4 Plate', 'notes': 'FR4 mounting plate'},
        {'name': 'Polycarbonate Plate', 'notes': 'PC mounting plate'},
    ],
    'Stabilizer': [
        {'name': 'Cherry Clip-in Stabilizers', 'notes': 'Plate mount'},
        {'name': 'Durock V2 Stabilizers', 'notes': 'Screw-in PCB mount'},
        {'name': 'C3 Equalz Stabilizers', 'notes': 'Screw-in PCB mount'},
    ],
    'Consumable': [
        {'name': 'Krytox 205g0', 'notes': 'Switch lubricant'},
        {'name': 'Tribosys 3204', 'notes': 'Switch lubricant'},
        {'name': 'Dielectric Grease', 'notes': 'Stabilizer lubricant'},
        {'name': 'Switch Films', 'notes': 'Reduces housing wobble'},
        {'name': 'O-Rings', 'notes': 'Dampening rings'},
        {'name': 'Case Foam', 'notes': 'Sound dampening foam'},
    ],
    'Tool': [
        {'name': 'Switch Puller', 'notes': 'For hot-swap boards'},
        {'name': 'Keycap Puller', 'notes': 'Wire or plastic'},
        {'name': 'Lube Station', 'notes': 'Holds switches for lubing'},
        {'name': 'Switch Opener', 'notes': 'Opens switch housing'},
    ],
}


@parts_bp.route('/catalog/seed-keyboard', methods=['POST'])
@login_required
def seed_keyboard_catalog():
    """
    Seed default keyboard categories and sample entries for a subsection.

    Request JSON:
        subsection_id: int (required) - Subsection to seed

    Returns:
        success: bool
        message: string
        entries_created: int
    """
    data = request.get_json()
    subsection_id = data.get('subsection_id')

    if not subsection_id:
        return jsonify(success=False, message="subsection_id is required."), 400

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

        entries_created = 0

        for category, entries in KEYBOARD_CATALOG_DEFAULTS.items():
            for entry in entries:
                # Check if entry already exists (by name and category)
                cursor.execute(
                    "SELECT catalog_id FROM parts_catalog WHERE subsection_id = ? AND category = ? AND name = ?",
                    (subsection_id, category, entry['name'])
                )
                if cursor.fetchone():
                    continue  # Skip existing entries

                cursor.execute("""
                    INSERT INTO parts_catalog (subsection_id, category, name, notes)
                    VALUES (?, ?, ?, ?)
                """, (subsection_id, category, entry['name'], entry.get('notes')))
                entries_created += 1

        conn.commit()
        conn.close()

        return jsonify(
            success=True,
            message=f"Keyboard catalog seeded with {entries_created} entries.",
            entries_created=entries_created
        ), 201

    except Exception as e:
        print(f"[CATALOG] Seed keyboard error: {e}")
        return jsonify(success=False, message="Failed to seed keyboard catalog."), 500


@parts_bp.route('/catalog/<int:catalog_id>', methods=['PUT'])
@login_required
def update_catalog_entry(catalog_id):
    """
    Update a catalog entry.

    Request JSON (all fields optional):
        category: string
        name: string
        sku: string
        default_price: float
        weight_class: string
        notes: string

    Returns:
        success: bool
        catalog_entry: updated entry
    """
    data = request.get_json()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify catalog entry exists and belongs to user (via subsection)
        cursor.execute("""
            SELECT pc.catalog_id
            FROM parts_catalog pc
            JOIN subsections s ON pc.subsection_id = s.subsection_id
            WHERE pc.catalog_id = ? AND s.user_id = ?
        """, (catalog_id, current_user.id))

        if not cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Catalog entry not found."), 404

        # Build update query
        updatable_fields = ['category', 'name', 'sku', 'default_price', 'weight_class', 'notes']

        updates = []
        params = []

        for field in updatable_fields:
            if field in data:
                if field == 'weight_class' and data[field] not in ('light', 'medium', 'heavy', None):
                    continue
                updates.append(f"{field} = ?")
                params.append(data[field])

        if not updates:
            conn.close()
            return jsonify(success=False, message="No fields to update."), 400

        params.append(catalog_id)

        cursor.execute(f"""
            UPDATE parts_catalog SET {', '.join(updates)} WHERE catalog_id = ?
        """, params)

        conn.commit()

        # Fetch updated entry
        cursor.execute("""
            SELECT pc.*, s.name as subsection_name
            FROM parts_catalog pc
            JOIN subsections s ON pc.subsection_id = s.subsection_id
            WHERE pc.catalog_id = ?
        """, (catalog_id,))
        entry = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(success=True, catalog_entry=entry)

    except Exception as e:
        print(f"[CATALOG] Update error: {e}")
        return jsonify(success=False, message="Failed to update catalog entry."), 500


@parts_bp.route('/catalog/<int:catalog_id>', methods=['DELETE'])
@login_required
def delete_catalog_entry(catalog_id):
    """
    Delete a catalog entry.

    Returns:
        success: bool
        message: string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify catalog entry exists and belongs to user (via subsection)
        cursor.execute("""
            SELECT pc.catalog_id, pc.name
            FROM parts_catalog pc
            JOIN subsections s ON pc.subsection_id = s.subsection_id
            WHERE pc.catalog_id = ? AND s.user_id = ?
        """, (catalog_id, current_user.id))

        entry = cursor.fetchone()
        if not entry:
            conn.close()
            return jsonify(success=False, message="Catalog entry not found."), 404

        entry_name = entry['name']

        cursor.execute("DELETE FROM parts_catalog WHERE catalog_id = ?", (catalog_id,))
        conn.commit()
        conn.close()

        return jsonify(success=True, message=f"Catalog entry '{entry_name}' deleted.")

    except Exception as e:
        print(f"[CATALOG] Delete error: {e}")
        return jsonify(success=False, message="Failed to delete catalog entry."), 500
