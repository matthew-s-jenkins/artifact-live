"""
Artifact Live v2 - Construction Simulation Routes

REST API for the construction development simulator.
Exposes the simulation engine as a set of HTTP endpoints.

Author: Matthew Jenkins
Date: 2026-04-10
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from services.construction_sim import (
    create_development,
    start_development,
    advance_day,
    advance_days,
    get_development_status,
    get_lot_detail,
    get_financial_summary,
)

simulation_bp = Blueprint('simulation', __name__)


# =============================================================================
# Development lifecycle
# =============================================================================

@simulation_bp.route('/api/sim/developments', methods=['POST'])
@login_required
def create_development_route():
    """
    Create a new development with all defaults (MVP preset).

    Body: { name, num_houses?, acreage?, land_cost?, budget?, start_date? }
    """
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    try:
        result = create_development(
            user_id=int(current_user.id),
            name=data['name'],
            num_houses=data.get('num_houses', 10),
            acreage=data.get('acreage'),
            land_cost=data.get('land_cost', 0),
            budget=data.get('budget', 0),
            start_date=data.get('start_date', '2026-01-01'),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to create development: {str(e)}'}), 500


@simulation_bp.route('/api/sim/developments/<int:dev_id>/start', methods=['POST'])
@login_required
def start_development_route(dev_id):
    """Start a development (setup → running)."""
    try:
        start_development(int(current_user.id), dev_id)
        return jsonify({'status': 'running', 'development_id': dev_id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@simulation_bp.route('/api/sim/developments/<int:dev_id>', methods=['GET'])
@login_required
def get_development_route(dev_id):
    """Get full development status."""
    result = get_development_status(int(current_user.id), dev_id)
    if not result:
        return jsonify({'error': 'Development not found'}), 404
    return jsonify(result)


# =============================================================================
# Simulation control
# =============================================================================

@simulation_bp.route('/api/sim/developments/<int:dev_id>/advance', methods=['POST'])
@login_required
def advance_route(dev_id):
    """
    Advance the simulation by N days (default 1).

    Body: { days?: int }
    """
    data = request.get_json() or {}
    num_days = data.get('days', 1)

    if num_days < 1:
        return jsonify({'error': 'days must be >= 1'}), 400
    if num_days > 365:
        return jsonify({'error': 'Maximum 365 days per request'}), 400

    try:
        if num_days == 1:
            result = advance_day(int(current_user.id), dev_id)
        else:
            result = advance_days(int(current_user.id), dev_id, num_days)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Simulation error: {str(e)}'}), 500


# =============================================================================
# Detail views
# =============================================================================

@simulation_bp.route('/api/sim/developments/<int:dev_id>/lots', methods=['GET'])
@login_required
def list_lots_route(dev_id):
    """List all lots with summary status."""
    status = get_development_status(int(current_user.id), dev_id)
    if not status:
        return jsonify({'error': 'Development not found'}), 404

    from services.construction_sim import get_db_connection, _row_to_dict
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.*,
                   COUNT(lp.lot_phase_id) as total_phases,
                   COUNT(CASE WHEN lp.status = 'completed' THEN 1 END) as completed_phases,
                   COALESCE(SUM(lp.hours_completed), 0) as hours_done,
                   COALESCE(SUM(lp.hours_needed), 0) as hours_total
            FROM sim_lots l
            LEFT JOIN sim_lot_phases lp ON l.lot_id = lp.lot_id
            WHERE l.development_id = ?
            GROUP BY l.lot_id
            ORDER BY l.lot_number
        """, (dev_id,))
        lots = []
        for row in cursor.fetchall():
            lot = _row_to_dict(row)
            lot['progress_pct'] = round(
                lot['hours_done'] / lot['hours_total'] * 100, 1
            ) if lot['hours_total'] > 0 else 0
            lots.append(lot)
        return jsonify({'lots': lots})
    finally:
        conn.close()


@simulation_bp.route('/api/sim/developments/<int:dev_id>/lots/<int:lot_id>', methods=['GET'])
@login_required
def get_lot_route(dev_id, lot_id):
    """Get detailed lot status with all phases and labor log."""
    result = get_lot_detail(int(current_user.id), dev_id, lot_id)
    if not result:
        return jsonify({'error': 'Lot not found'}), 404
    return jsonify(result)


@simulation_bp.route('/api/sim/developments/<int:dev_id>/financials', methods=['GET'])
@login_required
def get_financials_route(dev_id):
    """Get financial summary: budget vs actual, cost by phase, account balances."""
    result = get_financial_summary(int(current_user.id), dev_id)
    if not result:
        return jsonify({'error': 'Development not found'}), 404
    return jsonify(result)


@simulation_bp.route('/api/sim/developments/<int:dev_id>/daily-log', methods=['GET'])
@login_required
def get_daily_log_route(dev_id):
    """
    Get the daily activity log. Optional ?day=N to filter to a specific day.
    """
    from services.construction_sim import get_db_connection, _row_to_dict
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        day_filter = request.args.get('day', type=int)

        if day_filter is not None:
            cursor.execute("""
                SELECT dl.*, c.name as crew_name, lp.phase_name,
                       l.label as lot_label
                FROM sim_daily_log dl
                JOIN sim_crews c ON dl.crew_id = c.crew_id
                JOIN sim_lot_phases lp ON dl.lot_phase_id = lp.lot_phase_id
                JOIN sim_lots l ON lp.lot_id = l.lot_id
                WHERE dl.development_id = ? AND dl.sim_day = ?
                ORDER BY dl.log_id
            """, (dev_id, day_filter))
        else:
            cursor.execute("""
                SELECT dl.*, c.name as crew_name, lp.phase_name,
                       l.label as lot_label
                FROM sim_daily_log dl
                JOIN sim_crews c ON dl.crew_id = c.crew_id
                JOIN sim_lot_phases lp ON dl.lot_phase_id = lp.lot_phase_id
                JOIN sim_lots l ON lp.lot_id = l.lot_id
                WHERE dl.development_id = ?
                ORDER BY dl.sim_day, dl.log_id
            """, (dev_id,))

        logs = [_row_to_dict(r) for r in cursor.fetchall()]
        return jsonify({'logs': logs, 'count': len(logs)})
    finally:
        conn.close()
