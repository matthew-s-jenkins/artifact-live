"""
Artifact Live v2 - Projects API

CRUD operations for projects (systems/acquisitions/flips).
Each project represents a single acquisition that will be parted out and sold.

Endpoints:
    POST   /api/projects                    - Create new project
    GET    /api/projects                    - List all projects (with filters)
    GET    /api/projects/<id>               - Get single project with nested parts
    PUT    /api/projects/<id>               - Update project
    DELETE /api/projects/<id>               - Delete project (cascades to parts)
    POST   /api/projects/<id>/disassemble   - Disassemble project (return parts to inventory)
    POST   /api/projects/<id>/plan-build    - Plan a build (analyze part availability)
    POST   /api/projects/<id>/confirm-staged - Confirm staged parts (STAGED -> ALLOCATED)
    POST   /api/projects/<id>/cancel-staged  - Cancel staged parts (return to inventory)

Author: Matthew Jenkins
Date: 2026-01-19
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import sqlite3
from pathlib import Path


projects_bp = Blueprint('projects', __name__)


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


@projects_bp.route('/projects', methods=['POST'])
@login_required
def create_project():
    """
    Create a new project.

    Request JSON:
        name: string (required) - Project name, e.g., 'Dell OptiPlex 7050'
        subsection_id: int (required) - Which subsection this belongs to
        description: string (optional)
        acquisition_cost: float (optional) - What you paid
        acquisition_date: string (optional) - Date acquired (YYYY-MM-DD)
        acquisition_source: string (optional) - Where acquired
        status: string (optional) - Initial status (defaults to ACQUIRED)
               CCS: ACQUIRED, PARTING, LISTED, SOLD, COMPLETE
               Keyboard: PLANNED, IN_PROGRESS, ASSEMBLED, DEPLOYED, DISASSEMBLED
        for_sale: bool (optional) - Is this project/build available for sale?
        notes: string (optional)

    Returns:
        success: bool
        project: object with project_id and all fields
    """
    data = request.get_json()

    # Validate required fields
    name = data.get('name', '').strip()
    subsection_id = data.get('subsection_id')

    if not name:
        return jsonify(success=False, message="Project name is required."), 400
    if not subsection_id:
        return jsonify(success=False, message="Subsection ID is required."), 400

    # Validate status if provided
    status = data.get('status', 'ACQUIRED')
    valid_statuses = (
        'ACQUIRED', 'PARTING', 'LISTED', 'SOLD', 'COMPLETE',
        'PLANNED', 'IN_PROGRESS', 'ASSEMBLED', 'DEPLOYED', 'DISASSEMBLED'
    )
    if status not in valid_statuses:
        return jsonify(success=False, message=f"Invalid status. Must be one of: {valid_statuses}"), 400

    # Handle for_sale flag
    for_sale = 1 if data.get('for_sale') else 0

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

        # Insert project
        cursor.execute("""
            INSERT INTO projects (
                user_id, subsection_id, name, description,
                acquisition_cost, acquisition_date, acquisition_source,
                status, for_sale, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            current_user.id,
            subsection_id,
            name,
            data.get('description'),
            data.get('acquisition_cost'),
            data.get('acquisition_date'),
            data.get('acquisition_source'),
            status,
            for_sale,
            data.get('notes')
        ))

        project_id = cursor.lastrowid
        conn.commit()

        # Fetch the created project
        cursor.execute("""
            SELECT p.*, s.name as subsection_name
            FROM projects p
            JOIN subsections s ON p.subsection_id = s.subsection_id
            WHERE p.project_id = ?
        """, (project_id,))
        project = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(success=True, project=project), 201

    except Exception as e:
        print(f"[PROJECTS] Create error: {e}")
        return jsonify(success=False, message="Failed to create project."), 500


@projects_bp.route('/projects', methods=['GET'])
@login_required
def list_projects():
    """
    List all projects for the current user.

    Query params:
        subsection_id: int (optional) - Filter by subsection
        status: string (optional) - Filter by status
               CCS: ACQUIRED, PARTING, LISTED, SOLD, COMPLETE
               Keyboard: PLANNED, IN_PROGRESS, ASSEMBLED, DEPLOYED, DISASSEMBLED
        for_sale: bool (optional) - Filter by for_sale status

    Returns:
        success: bool
        projects: array of project objects with basic info
    """
    subsection_id = request.args.get('subsection_id', type=int)
    status = request.args.get('status')
    for_sale = request.args.get('for_sale')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Build query with optional filters
        query = """
            SELECT
                p.*,
                s.name as subsection_name,
                COUNT(pp.part_id) as part_count,
                COALESCE(SUM(pp.quantity), 0) as total_quantity,
                COALESCE(SUM(pp.estimated_value), 0) as total_estimated_value,
                SUM(CASE WHEN pp.status = 'ALLOCATED' THEN 1 ELSE 0 END) as allocated_parts
            FROM projects p
            JOIN subsections s ON p.subsection_id = s.subsection_id
            LEFT JOIN project_parts pp ON p.project_id = pp.project_id
            WHERE p.user_id = ?
        """
        params = [current_user.id]

        if subsection_id:
            query += " AND p.subsection_id = ?"
            params.append(subsection_id)

        if status:
            query += " AND p.status = ?"
            params.append(status)

        if for_sale is not None:
            query += " AND p.for_sale = ?"
            params.append(1 if for_sale in ('true', '1', 'True') else 0)

        query += " GROUP BY p.project_id ORDER BY p.created_at DESC"

        cursor.execute(query, params)
        projects = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify(success=True, projects=projects)

    except Exception as e:
        print(f"[PROJECTS] List error: {e}")
        return jsonify(success=False, message="Failed to retrieve projects."), 500


@projects_bp.route('/projects/<int:project_id>', methods=['GET'])
@login_required
def get_project(project_id):
    """
    Get a single project with all details and nested parts.

    Returns:
        success: bool
        project: object with all fields + parts array
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get project
        cursor.execute("""
            SELECT p.*, s.name as subsection_name
            FROM projects p
            JOIN subsections s ON p.subsection_id = s.subsection_id
            WHERE p.project_id = ? AND p.user_id = ?
        """, (project_id, current_user.id))

        project_row = cursor.fetchone()
        if not project_row:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        project = row_to_dict(project_row)

        # Get parts for this project
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.project_id = ?
            ORDER BY pp.created_at DESC
        """, (project_id,))

        parts = [row_to_dict(row) for row in cursor.fetchall()]
        project['parts'] = parts

        # Calculate summary stats (keyboard-aware)
        allocated_parts = [p for p in parts if p['status'] == 'ALLOCATED']
        direct_parts = [p for p in parts if p['status'] != 'ALLOCATED']
        total_quantity = sum(p.get('quantity', 1) or 1 for p in parts)

        project['summary'] = {
            'total_parts': len(parts),
            'total_quantity': total_quantity,
            'allocated_parts': len(allocated_parts),
            'direct_parts': len(direct_parts),
            'parts_for_sale': sum(1 for p in parts if p['status'] in ('IN_SYSTEM', 'LISTED')),
            'parts_sold': sum(1 for p in parts if p['status'] == 'SOLD'),
            'total_estimated_value': sum(p['estimated_value'] or 0 for p in parts),
            'total_actual_revenue': sum(p['actual_sale_price'] or 0 for p in parts if p['status'] == 'SOLD'),
            'total_fees_paid': sum(p['fees_paid'] or 0 for p in parts if p['status'] == 'SOLD'),
            'total_shipping_paid': sum(p['shipping_paid'] or 0 for p in parts if p['status'] == 'SOLD'),
        }

        conn.close()

        return jsonify(success=True, project=project)

    except Exception as e:
        print(f"[PROJECTS] Get error: {e}")
        return jsonify(success=False, message="Failed to retrieve project."), 500


@projects_bp.route('/projects/<int:project_id>', methods=['PUT'])
@login_required
def update_project(project_id):
    """
    Update a project.

    Request JSON (all fields optional):
        name: string
        description: string
        acquisition_cost: float
        acquisition_date: string
        acquisition_source: string
        status: string (CCS: ACQUIRED, PARTING, LISTED, SOLD, COMPLETE)
                       (Keyboard: PLANNED, IN_PROGRESS, ASSEMBLED, DEPLOYED, DISASSEMBLED)
        for_sale: bool
        notes: string

    Returns:
        success: bool
        project: updated project object
    """
    data = request.get_json()

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

        # Build update query dynamically based on provided fields
        updatable_fields = [
            'name', 'description', 'acquisition_cost', 'acquisition_date',
            'acquisition_source', 'status', 'notes'
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

        if not updates:
            conn.close()
            return jsonify(success=False, message="No fields to update."), 400

        # Validate status if provided (includes both CCS and Keyboard workflows)
        if 'status' in data:
            valid_statuses = (
                # CCS workflow (PC flipping)
                'ACQUIRED', 'PARTING', 'LISTED', 'SOLD', 'COMPLETE',
                # Keyboard workflow
                'PLANNED', 'IN_PROGRESS', 'ASSEMBLED', 'DEPLOYED', 'DISASSEMBLED'
            )
            if data['status'] not in valid_statuses:
                conn.close()
                return jsonify(success=False, message=f"Invalid status. Must be one of: {valid_statuses}"), 400

        params.append(project_id)

        cursor.execute(f"""
            UPDATE projects SET {', '.join(updates)} WHERE project_id = ?
        """, params)

        conn.commit()

        # Fetch updated project
        cursor.execute("""
            SELECT p.*, s.name as subsection_name
            FROM projects p
            JOIN subsections s ON p.subsection_id = s.subsection_id
            WHERE p.project_id = ?
        """, (project_id,))
        project = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(success=True, project=project)

    except Exception as e:
        print(f"[PROJECTS] Update error: {e}")
        return jsonify(success=False, message="Failed to update project."), 500


@projects_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@login_required
def delete_project(project_id):
    """
    Delete a project and all associated parts (cascade).

    Returns:
        success: bool
        message: string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id, name FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project = cursor.fetchone()
        if not project:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        project_name = project['name']

        # Get part count for confirmation message
        cursor.execute(
            "SELECT COUNT(*) as count FROM project_parts WHERE project_id = ?",
            (project_id,)
        )
        part_count = cursor.fetchone()['count']

        # Delete project (parts will cascade delete due to FK constraint)
        cursor.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        conn.commit()
        conn.close()

        message = f"Project '{project_name}' deleted"
        if part_count > 0:
            message += f" along with {part_count} part(s)"

        return jsonify(success=True, message=message)

    except Exception as e:
        print(f"[PROJECTS] Delete error: {e}")
        return jsonify(success=False, message="Failed to delete project."), 500


@projects_bp.route('/projects/<int:project_id>/disassemble', methods=['POST'])
@login_required
def disassemble_project(project_id):
    """
    Disassemble a project - return parts to inventory, destroy consumables.

    This endpoint:
    - Returns non-consumable parts to loose inventory (status = IN_SYSTEM)
    - Marks consumable parts as TRASHED (destroyed during disassembly)
    - Sets project status to DISASSEMBLED
    - Optionally identifies mystery parts during disassembly

    Request JSON (optional):
        identify_parts: array of objects [{part_id: int, catalog_id: int, custom_name: string}]
            - Identify mystery parts during disassembly

    Returns:
        success: bool
        project: updated project object
        parts_returned: int - Count of parts returned to inventory
        consumables_destroyed: int - Count of consumable parts trashed
        parts_identified: int - Count of mystery parts identified
    """
    data = request.get_json() or {}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id, name, status FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project_row = cursor.fetchone()
        if not project_row:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        project_name = project_row['name']
        current_status = project_row['status']

        # Warn if already disassembled (but allow re-running)
        if current_status == 'DISASSEMBLED':
            conn.close()
            return jsonify(
                success=False,
                message=f"Project '{project_name}' is already disassembled."
            ), 400

        # Get all parts in the project with their catalog categories
        cursor.execute("""
            SELECT pp.part_id, pp.catalog_id, pp.custom_name, pp.quantity, pp.is_mystery,
                   pc.category as catalog_category, pc.name as catalog_name
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.project_id = ?
        """, (project_id,))

        parts = cursor.fetchall()

        # Process identify_parts if provided (for mystery parts)
        identify_parts = data.get('identify_parts', [])
        identify_map = {item['part_id']: item for item in identify_parts if 'part_id' in item}

        parts_returned = 0
        consumables_destroyed = 0
        parts_identified = 0

        for part in parts:
            part_id = part['part_id']
            category = part['catalog_category']
            is_mystery = part['is_mystery']

            # Check if this mystery part should be identified
            if is_mystery and part_id in identify_map:
                identify_info = identify_map[part_id]
                update_fields = ["is_mystery = 0"]
                update_params = []

                if 'catalog_id' in identify_info:
                    update_fields.append("catalog_id = ?")
                    update_params.append(identify_info['catalog_id'])
                if 'custom_name' in identify_info:
                    update_fields.append("custom_name = ?")
                    update_params.append(identify_info['custom_name'])

                update_params.append(part_id)
                cursor.execute(f"""
                    UPDATE project_parts SET {', '.join(update_fields)} WHERE part_id = ?
                """, update_params)
                parts_identified += 1

                # Re-fetch category if catalog_id was updated
                if 'catalog_id' in identify_info:
                    cursor.execute(
                        "SELECT category FROM parts_catalog WHERE catalog_id = ?",
                        (identify_info['catalog_id'],)
                    )
                    cat_row = cursor.fetchone()
                    if cat_row:
                        category = cat_row['category']

            # Determine if consumable (destroyed during disassembly)
            is_consumable = category == 'Consumable' if category else False

            if is_consumable:
                # Mark consumables as TRASHED (destroyed)
                cursor.execute("""
                    UPDATE project_parts
                    SET status = 'TRASHED', project_id = NULL
                    WHERE part_id = ?
                """, (part_id,))
                consumables_destroyed += 1
            else:
                # Return to loose inventory
                cursor.execute("""
                    UPDATE project_parts
                    SET status = 'IN_SYSTEM', project_id = NULL
                    WHERE part_id = ?
                """, (part_id,))
                parts_returned += 1

        # Update project status to DISASSEMBLED
        cursor.execute("""
            UPDATE projects SET status = 'DISASSEMBLED' WHERE project_id = ?
        """, (project_id,))

        conn.commit()

        # Fetch updated project
        cursor.execute("""
            SELECT p.*, s.name as subsection_name
            FROM projects p
            JOIN subsections s ON p.subsection_id = s.subsection_id
            WHERE p.project_id = ?
        """, (project_id,))
        project = row_to_dict(cursor.fetchone())

        conn.close()

        return jsonify(
            success=True,
            project=project,
            parts_returned=parts_returned,
            consumables_destroyed=consumables_destroyed,
            parts_identified=parts_identified,
            message=f"Project '{project_name}' disassembled. {parts_returned} parts returned, {consumables_destroyed} consumables destroyed."
        )

    except Exception as e:
        print(f"[PROJECTS] Disassemble error: {e}")
        return jsonify(success=False, message="Failed to disassemble project."), 500


@projects_bp.route('/projects/<int:project_id>/plan-build', methods=['POST'])
@login_required
def plan_build(project_id):
    """
    Plan a build - analyze part availability without committing allocation.

    This endpoint analyzes which parts are available for a theoretical build:
    - Available in loose inventory (ready to allocate)
    - Available in for-sale projects (can disassemble to free up)
    - Available in personal projects (would need disassembly)
    - Not available (need to source/purchase)

    Request JSON:
        parts: array of objects [
            {catalog_id: int, quantity: int} or
            {custom_name: string, quantity: int}
        ]
        stage: bool (optional) - If true, stage available parts (don't commit)

    Returns:
        success: bool
        plan: {
            project_id: int,
            project_name: string,
            parts: [
                {
                    catalog_id: int,
                    catalog_name: string,
                    requested: int,
                    available: {
                        loose_inventory: [{part_id, quantity, subsection_name}],
                        for_sale_projects: [{project_id, project_name, part_id, quantity}],
                        personal_projects: [{project_id, project_name, part_id, quantity}]
                    },
                    total_available: int,
                    shortage: int,
                    status: 'available' | 'partial' | 'needs_disassembly' | 'unavailable'
                }
            ],
            summary: {
                fully_available: int,
                partial: int,
                needs_disassembly: int,
                unavailable: int
            }
        }
        staged_parts: array (only if stage=true)
    """
    data = request.get_json() or {}
    parts_requested = data.get('parts', [])
    should_stage = data.get('stage', False)

    if not parts_requested:
        return jsonify(success=False, message="parts array is required."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id, name, subsection_id FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project_row = cursor.fetchone()
        if not project_row:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        project_name = project_row['name']
        project_subsection = project_row['subsection_id']

        # Get user's subsections for inventory queries
        cursor.execute(
            "SELECT subsection_id FROM subsections WHERE user_id = ?",
            (current_user.id,)
        )
        user_subsections = [row['subsection_id'] for row in cursor.fetchall()]
        subsection_placeholders = ','.join('?' * len(user_subsections))

        plan_parts = []
        staged_parts = []
        summary = {'fully_available': 0, 'partial': 0, 'needs_disassembly': 0, 'unavailable': 0}

        for req in parts_requested:
            catalog_id = req.get('catalog_id')
            custom_name = req.get('custom_name')
            requested_qty = req.get('quantity', 1)

            if not catalog_id and not custom_name:
                continue

            # Get catalog info if catalog_id provided
            catalog_name = None
            catalog_category = None
            if catalog_id:
                cursor.execute(
                    "SELECT name, category FROM parts_catalog WHERE catalog_id = ?",
                    (catalog_id,)
                )
                cat_row = cursor.fetchone()
                if cat_row:
                    catalog_name = cat_row['name']
                    catalog_category = cat_row['category']

            part_plan = {
                'catalog_id': catalog_id,
                'catalog_name': catalog_name or custom_name,
                'catalog_category': catalog_category,
                'requested': requested_qty,
                'available': {
                    'loose_inventory': [],
                    'for_sale_projects': [],
                    'personal_projects': []
                },
                'total_available': 0,
                'shortage': 0,
                'status': 'unavailable'
            }

            # 1. Check loose inventory (available immediately)
            if catalog_id:
                cursor.execute(f"""
                    SELECT pp.part_id, pp.quantity, pp.custom_name, s.name as subsection_name
                    FROM project_parts pp
                    JOIN subsections s ON pp.subsection_id = s.subsection_id
                    WHERE pp.catalog_id = ?
                      AND pp.project_id IS NULL
                      AND pp.status = 'IN_SYSTEM'
                      AND pp.subsection_id IN ({subsection_placeholders})
                """, [catalog_id] + user_subsections)
            else:
                cursor.execute(f"""
                    SELECT pp.part_id, pp.quantity, pp.custom_name, s.name as subsection_name
                    FROM project_parts pp
                    JOIN subsections s ON pp.subsection_id = s.subsection_id
                    WHERE pp.custom_name LIKE ?
                      AND pp.project_id IS NULL
                      AND pp.status = 'IN_SYSTEM'
                      AND pp.subsection_id IN ({subsection_placeholders})
                """, [f'%{custom_name}%'] + user_subsections)

            for row in cursor.fetchall():
                part_plan['available']['loose_inventory'].append({
                    'part_id': row['part_id'],
                    'quantity': row['quantity'] or 1,
                    'custom_name': row['custom_name'],
                    'subsection_name': row['subsection_name']
                })

            # 2. Check for-sale projects (can disassemble without personal impact)
            if catalog_id:
                cursor.execute(f"""
                    SELECT pp.part_id, pp.quantity, pp.custom_name,
                           p.project_id, p.name as project_name
                    FROM project_parts pp
                    JOIN projects p ON pp.project_id = p.project_id
                    WHERE pp.catalog_id = ?
                      AND p.user_id = ?
                      AND p.for_sale = 1
                      AND p.status != 'DISASSEMBLED'
                      AND pp.status NOT IN ('SOLD', 'TRASHED')
                """, (catalog_id, current_user.id))
            else:
                cursor.execute(f"""
                    SELECT pp.part_id, pp.quantity, pp.custom_name,
                           p.project_id, p.name as project_name
                    FROM project_parts pp
                    JOIN projects p ON pp.project_id = p.project_id
                    WHERE pp.custom_name LIKE ?
                      AND p.user_id = ?
                      AND p.for_sale = 1
                      AND p.status != 'DISASSEMBLED'
                      AND pp.status NOT IN ('SOLD', 'TRASHED')
                """, (f'%{custom_name}%', current_user.id))

            for row in cursor.fetchall():
                part_plan['available']['for_sale_projects'].append({
                    'part_id': row['part_id'],
                    'quantity': row['quantity'] or 1,
                    'custom_name': row['custom_name'],
                    'project_id': row['project_id'],
                    'project_name': row['project_name']
                })

            # 3. Check personal projects (would need disassembly)
            if catalog_id:
                cursor.execute(f"""
                    SELECT pp.part_id, pp.quantity, pp.custom_name,
                           p.project_id, p.name as project_name
                    FROM project_parts pp
                    JOIN projects p ON pp.project_id = p.project_id
                    WHERE pp.catalog_id = ?
                      AND p.user_id = ?
                      AND p.for_sale = 0
                      AND p.status != 'DISASSEMBLED'
                      AND pp.status NOT IN ('SOLD', 'TRASHED', 'STAGED')
                """, (catalog_id, current_user.id))
            else:
                cursor.execute(f"""
                    SELECT pp.part_id, pp.quantity, pp.custom_name,
                           p.project_id, p.name as project_name
                    FROM project_parts pp
                    JOIN projects p ON pp.project_id = p.project_id
                    WHERE pp.custom_name LIKE ?
                      AND p.user_id = ?
                      AND p.for_sale = 0
                      AND p.status != 'DISASSEMBLED'
                      AND pp.status NOT IN ('SOLD', 'TRASHED', 'STAGED')
                """, (f'%{custom_name}%', current_user.id))

            for row in cursor.fetchall():
                part_plan['available']['personal_projects'].append({
                    'part_id': row['part_id'],
                    'quantity': row['quantity'] or 1,
                    'custom_name': row['custom_name'],
                    'project_id': row['project_id'],
                    'project_name': row['project_name']
                })

            # Calculate totals and status
            loose_qty = sum(p['quantity'] for p in part_plan['available']['loose_inventory'])
            for_sale_qty = sum(p['quantity'] for p in part_plan['available']['for_sale_projects'])
            personal_qty = sum(p['quantity'] for p in part_plan['available']['personal_projects'])

            part_plan['total_available'] = loose_qty + for_sale_qty + personal_qty
            part_plan['shortage'] = max(0, requested_qty - part_plan['total_available'])

            # Determine status
            if loose_qty >= requested_qty:
                part_plan['status'] = 'available'
                summary['fully_available'] += 1
            elif loose_qty + for_sale_qty >= requested_qty:
                part_plan['status'] = 'needs_disassembly'
                summary['needs_disassembly'] += 1
            elif part_plan['total_available'] >= requested_qty:
                part_plan['status'] = 'needs_disassembly'
                summary['needs_disassembly'] += 1
            elif part_plan['total_available'] > 0:
                part_plan['status'] = 'partial'
                summary['partial'] += 1
            else:
                part_plan['status'] = 'unavailable'
                summary['unavailable'] += 1

            plan_parts.append(part_plan)

            # Stage parts from loose inventory if requested
            if should_stage and loose_qty > 0:
                remaining_to_stage = min(requested_qty, loose_qty)
                for inv_part in part_plan['available']['loose_inventory']:
                    if remaining_to_stage <= 0:
                        break

                    part_id = inv_part['part_id']
                    available = inv_part['quantity']
                    stage_qty = min(remaining_to_stage, available)

                    if stage_qty == available:
                        # Stage entire part
                        cursor.execute("""
                            UPDATE project_parts
                            SET project_id = ?, status = 'STAGED'
                            WHERE part_id = ?
                        """, (project_id, part_id))
                        staged_parts.append({
                            'part_id': part_id,
                            'quantity': stage_qty,
                            'catalog_name': catalog_name or custom_name
                        })
                    else:
                        # Partial stage - split the row
                        remaining_qty = available - stage_qty
                        cursor.execute("""
                            UPDATE project_parts SET quantity = ? WHERE part_id = ?
                        """, (remaining_qty, part_id))

                        # Create new row for staged portion
                        cursor.execute("""
                            SELECT * FROM project_parts WHERE part_id = ?
                        """, (part_id,))
                        orig = row_to_dict(cursor.fetchone())

                        cursor.execute("""
                            INSERT INTO project_parts (
                                project_id, subsection_id, catalog_id, set_id, custom_name,
                                serial_number, condition, weight_class, estimated_value,
                                for_sale, quantity, is_mystery, metadata, status, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STAGED', ?)
                        """, (
                            project_id, orig['subsection_id'], orig['catalog_id'],
                            orig['set_id'], orig['custom_name'], orig['serial_number'],
                            orig['condition'], orig['weight_class'], orig['estimated_value'],
                            orig['for_sale'], stage_qty, orig['is_mystery'],
                            orig['metadata'], orig['notes']
                        ))
                        staged_parts.append({
                            'part_id': cursor.lastrowid,
                            'quantity': stage_qty,
                            'catalog_name': catalog_name or custom_name
                        })

                    remaining_to_stage -= stage_qty

        if should_stage:
            conn.commit()

        conn.close()

        # Build disassembly suggestions
        disassembly_needed = []
        for part in plan_parts:
            if part['status'] == 'needs_disassembly':
                for proj in part['available']['for_sale_projects']:
                    if proj not in disassembly_needed:
                        disassembly_needed.append({
                            'project_id': proj['project_id'],
                            'project_name': proj['project_name'],
                            'reason': f"to free up {part['catalog_name']}"
                        })

        response = {
            'success': True,
            'plan': {
                'project_id': project_id,
                'project_name': project_name,
                'parts': plan_parts,
                'summary': summary,
                'disassembly_suggestions': disassembly_needed
            }
        }

        if should_stage:
            response['staged_parts'] = staged_parts
            response['message'] = f"{len(staged_parts)} part(s) staged for build"

        return jsonify(**response)

    except Exception as e:
        print(f"[PROJECTS] Plan build error: {e}")
        return jsonify(success=False, message="Failed to plan build."), 500


@projects_bp.route('/projects/<int:project_id>/confirm-staged', methods=['POST'])
@login_required
def confirm_staged_parts(project_id):
    """
    Confirm staged parts - convert STAGED status to ALLOCATED.

    Returns:
        success: bool
        confirmed_count: int
        message: string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id, name FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project_row = cursor.fetchone()
        if not project_row:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        # Convert STAGED to ALLOCATED
        cursor.execute("""
            UPDATE project_parts
            SET status = 'ALLOCATED'
            WHERE project_id = ? AND status = 'STAGED'
        """, (project_id,))

        confirmed_count = cursor.rowcount
        conn.commit()
        conn.close()

        return jsonify(
            success=True,
            confirmed_count=confirmed_count,
            message=f"{confirmed_count} part(s) confirmed and allocated to project."
        )

    except Exception as e:
        print(f"[PROJECTS] Confirm staged error: {e}")
        return jsonify(success=False, message="Failed to confirm staged parts."), 500


@projects_bp.route('/projects/<int:project_id>/cancel-staged', methods=['POST'])
@login_required
def cancel_staged_parts(project_id):
    """
    Cancel staged parts - return STAGED parts to loose inventory.

    Returns:
        success: bool
        cancelled_count: int
        message: string
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute(
            "SELECT project_id, name FROM projects WHERE project_id = ? AND user_id = ?",
            (project_id, current_user.id)
        )
        project_row = cursor.fetchone()
        if not project_row:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        # Return STAGED parts to inventory
        cursor.execute("""
            UPDATE project_parts
            SET status = 'IN_SYSTEM', project_id = NULL
            WHERE project_id = ? AND status = 'STAGED'
        """, (project_id,))

        cancelled_count = cursor.rowcount
        conn.commit()
        conn.close()

        return jsonify(
            success=True,
            cancelled_count=cancelled_count,
            message=f"{cancelled_count} staged part(s) returned to inventory."
        )

    except Exception as e:
        print(f"[PROJECTS] Cancel staged error: {e}")
        return jsonify(success=False, message="Failed to cancel staged parts."), 500


@projects_bp.route('/subsections', methods=['GET'])
@login_required
def list_subsections():
    """
    List all subsections for the current user.
    Useful for populating dropdown when creating a project.

    Returns:
        success: bool
        subsections: array of subsection objects
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM subsections
            WHERE user_id = ?
            ORDER BY is_business DESC, name ASC
        """, (current_user.id,))

        subsections = [row_to_dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(success=True, subsections=subsections)

    except Exception as e:
        print(f"[PROJECTS] List subsections error: {e}")
        return jsonify(success=False, message="Failed to retrieve subsections."), 500
