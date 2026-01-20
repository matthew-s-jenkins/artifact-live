"""
Artifact Live v2 - Projects API

CRUD operations for projects (systems/acquisitions/flips).
Each project represents a single acquisition that will be parted out and sold.

Endpoints:
    POST   /api/projects          - Create new project
    GET    /api/projects          - List all projects (with filters)
    GET    /api/projects/<id>     - Get single project with nested parts
    PUT    /api/projects/<id>     - Update project
    DELETE /api/projects/<id>     - Delete project (cascades to parts)

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
                status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACQUIRED', ?)
        """, (
            current_user.id,
            subsection_id,
            name,
            data.get('description'),
            data.get('acquisition_cost'),
            data.get('acquisition_date'),
            data.get('acquisition_source'),
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
        status: string (optional) - Filter by status (ACQUIRED, PARTING, LISTED, SOLD, COMPLETE)

    Returns:
        success: bool
        projects: array of project objects with basic info
    """
    subsection_id = request.args.get('subsection_id', type=int)
    status = request.args.get('status')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Build query with optional filters
        query = """
            SELECT
                p.*,
                s.name as subsection_name,
                COUNT(pp.part_id) as part_count,
                COALESCE(SUM(pp.estimated_value), 0) as total_estimated_value
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

        # Calculate summary stats
        project['summary'] = {
            'total_parts': len(parts),
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
        status: string (ACQUIRED, PARTING, LISTED, SOLD, COMPLETE)
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

        if not updates:
            conn.close()
            return jsonify(success=False, message="No fields to update."), 400

        # Validate status if provided
        if 'status' in data:
            valid_statuses = ('ACQUIRED', 'PARTING', 'LISTED', 'SOLD', 'COMPLETE')
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
