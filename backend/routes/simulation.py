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
    get_db_connection,
    _row_to_dict,
    PRESETS,
)

simulation_bp = Blueprint('simulation', __name__)


# =============================================================================
# Development lifecycle
# =============================================================================

@simulation_bp.route('/api/sim/developments', methods=['POST'])
@login_required
def create_development_route():
    """
    Create a new development from a preset.

    Body: { name, preset?, num_houses?, acreage?, land_cost?, budget?, start_date? }
    preset: 'mvp' (default) or 'full_scale'
    """
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    preset = data.get('preset', 'mvp')
    if preset not in PRESETS:
        return jsonify({'error': f"Unknown preset '{preset}'. Valid: {', '.join(PRESETS.keys())}"}), 400

    try:
        result = create_development(
            user_id=int(current_user.id),
            name=data['name'],
            preset=preset,
            num_houses=data.get('num_houses'),
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


@simulation_bp.route('/api/sim/presets', methods=['GET'])
@login_required
def list_presets_route():
    """List available presets with summary info."""
    summaries = {}
    for name, cfg in PRESETS.items():
        total_lots = sum(lc['count'] for lc in cfg['lot_configs'])
        summaries[name] = {
            'crew_types': len(cfg['crew_types']),
            'crews': len(cfg['crews']),
            'lot_configs': [
                {'type': lc['type']['name'], 'count': lc['count'],
                 'phases': len(lc['phases'])}
                for lc in cfg['lot_configs']
            ],
            'total_lots': total_lots,
            'has_materials': len(cfg.get('materials', [])) > 0,
        }
    return jsonify(summaries)


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


# =============================================================================
# Materials & PO views
# =============================================================================

@simulation_bp.route('/api/sim/developments/<int:dev_id>/materials', methods=['GET'])
@login_required
def get_materials_route(dev_id):
    """Get inventory levels, PO summary, and material costs."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Inventory levels
        cursor.execute("""
            SELECT m.material_id, m.name, m.unit, m.unit_cost,
                   m.lead_time_days, m.vendor_name,
                   inv.quantity_on_hand, inv.quantity_on_order
            FROM sim_materials m
            JOIN sim_inventory inv ON m.material_id = inv.material_id
            WHERE m.development_id = ?
            ORDER BY m.name
        """, (dev_id,))
        inventory = [_row_to_dict(r) for r in cursor.fetchall()]

        # PO summary
        cursor.execute("""
            SELECT status, COUNT(*) as count, COALESCE(SUM(total_cost), 0) as total
            FROM sim_purchase_orders WHERE development_id = ?
            GROUP BY status
        """, (dev_id,))
        po_summary = {r['status']: {'count': r['count'], 'total': r['total']}
                      for r in cursor.fetchall()}

        return jsonify({'inventory': inventory, 'po_summary': po_summary})
    finally:
        conn.close()


@simulation_bp.route('/api/sim/developments/<int:dev_id>/purchase-orders', methods=['GET'])
@login_required
def get_purchase_orders_route(dev_id):
    """Get all POs with line items."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        status_filter = request.args.get('status')

        query = """
            SELECT po.* FROM sim_purchase_orders po
            WHERE po.development_id = ?
        """
        params = [dev_id]
        if status_filter:
            query += " AND po.status = ?"
            params.append(status_filter)
        query += " ORDER BY po.order_day DESC"

        cursor.execute(query, params)
        pos = []
        for po_row in cursor.fetchall():
            po = _row_to_dict(po_row)
            cursor.execute("""
                SELECT pl.*, m.name as material_name, m.unit
                FROM sim_po_lines pl
                JOIN sim_materials m ON pl.material_id = m.material_id
                WHERE pl.po_id = ?
            """, (po['po_id'],))
            po['lines'] = [_row_to_dict(r) for r in cursor.fetchall()]
            pos.append(po)

        return jsonify({'purchase_orders': pos, 'count': len(pos)})
    finally:
        conn.close()


@simulation_bp.route('/api/sim/developments/<int:dev_id>/crews', methods=['GET'])
@login_required
def list_crews_route(dev_id):
    """List all crews with utilization stats."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT current_day FROM sim_developments WHERE development_id = ?
        """, (dev_id,))
        dev = cursor.fetchone()
        current_day = dev['current_day'] if dev else 0

        cursor.execute("""
            SELECT c.crew_id, c.name, ct.name as crew_type, ct.hourly_rate,
                   COUNT(DISTINCT dl.sim_day) as days_worked,
                   COALESCE(SUM(dl.hours_worked), 0) as total_hours,
                   COALESCE(SUM(dl.labor_cost), 0) as total_cost
            FROM sim_crews c
            JOIN sim_crew_types ct ON c.crew_type_id = ct.crew_type_id
            LEFT JOIN sim_daily_log dl ON c.crew_id = dl.crew_id
            WHERE c.development_id = ?
            GROUP BY c.crew_id
            ORDER BY ct.name, c.name
        """, (dev_id,))
        crews = []
        for r in cursor.fetchall():
            crew = _row_to_dict(r)
            crew['utilization_pct'] = round(
                crew['days_worked'] / current_day * 100, 1
            ) if current_day > 0 else 0
            crews.append(crew)

        return jsonify({'crews': crews})
    finally:
        conn.close()


# =============================================================================
# Crew detail view
# =============================================================================

@simulation_bp.route('/api/sim/developments/<int:dev_id>/crews/<int:crew_id>', methods=['GET'])
@login_required
def get_crew_detail_route(dev_id, crew_id):
    """Get crew detail: current assignment, weekly hours, upcoming work."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Crew info
        cursor.execute("""
            SELECT c.*, ct.name as crew_type, ct.hourly_rate
            FROM sim_crews c
            JOIN sim_crew_types ct ON c.crew_type_id = ct.crew_type_id
            WHERE c.crew_id = ? AND c.development_id = ?
        """, (crew_id, dev_id))
        crew = cursor.fetchone()
        if not crew:
            return jsonify({'error': 'Crew not found'}), 404
        crew = _row_to_dict(crew)

        # Current assignment
        cursor.execute("""
            SELECT lp.*, l.label as lot_label
            FROM sim_lot_phases lp
            JOIN sim_lots l ON lp.lot_id = l.lot_id
            WHERE lp.assigned_crew_id = ? AND lp.status = 'in_progress'
        """, (crew_id,))
        assignment = cursor.fetchone()
        crew['current_assignment'] = _row_to_dict(assignment) if assignment else None

        # Get current day
        cursor.execute("""
            SELECT current_day FROM sim_developments WHERE development_id = ?
        """, (dev_id,))
        dev = cursor.fetchone()
        current_day = dev['current_day'] if dev else 0

        # Hours this week (last 5 work days)
        week_start = max(1, current_day - 4)
        cursor.execute("""
            SELECT COALESCE(SUM(dl.hours_worked), 0) as week_hours,
                   COALESCE(SUM(dl.labor_cost), 0) as week_cost,
                   COUNT(*) as days_worked
            FROM sim_daily_log dl
            WHERE dl.crew_id = ? AND dl.development_id = ?
            AND dl.sim_day >= ? AND dl.sim_day <= ?
        """, (crew_id, dev_id, week_start, current_day))
        week = _row_to_dict(cursor.fetchone())
        crew['week_hours'] = week['week_hours']
        crew['week_cost'] = week['week_cost']
        crew['week_days_worked'] = week['days_worked']

        # Total hours
        cursor.execute("""
            SELECT COALESCE(SUM(hours_worked), 0) as total_hours,
                   COALESCE(SUM(labor_cost), 0) as total_cost,
                   COUNT(DISTINCT sim_day) as days_worked
            FROM sim_daily_log
            WHERE crew_id = ? AND development_id = ?
        """, (crew_id, dev_id))
        totals = _row_to_dict(cursor.fetchone())
        crew['total_hours'] = totals['total_hours']
        crew['total_cost'] = totals['total_cost']
        crew['total_days_worked'] = totals['days_worked']
        crew['utilization_pct'] = round(
            totals['days_worked'] / current_day * 100, 1
        ) if current_day > 0 else 0

        # Upcoming work queue (ready phases for this crew type)
        cursor.execute("""
            SELECT lp.lot_phase_id, lp.phase_name, lp.hours_needed,
                   lp.hours_completed, l.label as lot_label, l.lot_number
            FROM sim_lot_phases lp
            JOIN sim_lots l ON lp.lot_id = l.lot_id
            WHERE l.development_id = ?
            AND lp.crew_type_id = ?
            AND lp.status IN ('ready', 'in_progress')
            AND lp.hours_completed < lp.hours_needed
            ORDER BY l.lot_number, lp.phase_number
            LIMIT 20
        """, (dev_id, crew['crew_type_id']))
        crew['work_queue'] = [_row_to_dict(r) for r in cursor.fetchall()]

        # Materials needed for current assignment
        if crew['current_assignment']:
            cursor.execute("""
                SELECT m.name, m.unit, pm.quantity,
                       COALESCE(inv.quantity_on_hand, 0) as on_hand
                FROM sim_phase_materials pm
                JOIN sim_materials m ON pm.material_id = m.material_id
                LEFT JOIN sim_inventory inv
                    ON m.material_id = inv.material_id
                    AND inv.development_id = ?
                WHERE pm.template_id = ?
            """, (dev_id, crew['current_assignment']['template_id']))
            crew['materials_needed'] = [_row_to_dict(r) for r in cursor.fetchall()]
        else:
            crew['materials_needed'] = []

        return jsonify(crew)
    finally:
        conn.close()


# =============================================================================
# Owner KPIs
# =============================================================================

@simulation_bp.route('/api/sim/developments/<int:dev_id>/kpis', methods=['GET'])
@login_required
def get_kpis_route(dev_id):
    """Owner dashboard KPIs: % complete, cost/unit, burn rate, projections."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Development info
        cursor.execute("""
            SELECT * FROM sim_developments
            WHERE development_id = ? AND user_id = ?
        """, (dev_id, int(current_user.id)))
        dev = cursor.fetchone()
        if not dev:
            return jsonify({'error': 'Development not found'}), 404
        dev = _row_to_dict(dev)

        # Lot counts
        cursor.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                   COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress
            FROM sim_lots WHERE development_id = ?
        """, (dev_id,))
        lots = _row_to_dict(cursor.fetchone())

        # Phase progress
        cursor.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN lp.status = 'completed' THEN 1 END) as completed,
                   COALESCE(SUM(lp.hours_completed), 0) as hours_done,
                   COALESCE(SUM(lp.hours_needed), 0) as hours_total
            FROM sim_lot_phases lp
            JOIN sim_lots l ON lp.lot_id = l.lot_id
            WHERE l.development_id = ?
        """, (dev_id,))
        phases = _row_to_dict(cursor.fetchone())

        pct_complete = round(
            phases['hours_done'] / phases['hours_total'] * 100, 1
        ) if phases['hours_total'] > 0 else 0

        # Total spend (labor + materials)
        cursor.execute("""
            SELECT COALESCE(SUM(labor_cost), 0) as total_labor
            FROM sim_daily_log WHERE development_id = ?
        """, (dev_id,))
        labor_total = cursor.fetchone()['total_labor']

        cursor.execute("""
            SELECT COALESCE(SUM(total_cost), 0) as total_materials
            FROM sim_purchase_orders
            WHERE development_id = ? AND status IN ('delivered', 'paid')
        """, (dev_id,))
        materials_total = cursor.fetchone()['total_materials']

        total_spend = labor_total + materials_total
        cost_per_unit = round(
            total_spend / lots['completed'], 2
        ) if lots['completed'] > 0 else 0

        # Burn rate (last 7 days)
        burn_start = max(1, dev['current_day'] - 6)
        cursor.execute("""
            SELECT COALESCE(SUM(labor_cost), 0) as recent_labor
            FROM sim_daily_log
            WHERE development_id = ? AND sim_day >= ?
        """, (dev_id, burn_start))
        recent_labor = cursor.fetchone()['recent_labor']
        days_in_window = min(7, dev['current_day'])
        daily_burn = round(recent_labor / days_in_window, 2) if days_in_window > 0 else 0

        # Projected completion
        if pct_complete > 0 and dev['current_day'] > 0:
            estimated_total_days = round(dev['current_day'] / (pct_complete / 100))
            days_remaining = estimated_total_days - dev['current_day']
        else:
            estimated_total_days = 0
            days_remaining = 0

        # Budget remaining
        budget_remaining = dev['budget'] - total_spend if dev['budget'] > 0 else 0
        budget_pct = round(
            total_spend / dev['budget'] * 100, 1
        ) if dev['budget'] > 0 else 0

        return jsonify({
            'development': {
                'name': dev['name'],
                'current_day': dev['current_day'],
                'status': dev['status'],
                'budget': dev['budget'],
            },
            'completion': {
                'pct_complete': pct_complete,
                'lots_completed': lots['completed'],
                'lots_total': lots['total'],
                'lots_in_progress': lots['in_progress'],
                'phases_completed': phases['completed'],
                'phases_total': phases['total'],
                'hours_done': phases['hours_done'],
                'hours_total': phases['hours_total'],
            },
            'financials': {
                'total_spend': round(total_spend, 2),
                'labor_cost': round(labor_total, 2),
                'materials_cost': round(materials_total, 2),
                'cost_per_unit': cost_per_unit,
                'budget_remaining': round(budget_remaining, 2),
                'budget_pct_used': budget_pct,
            },
            'velocity': {
                'daily_burn_rate': daily_burn,
                'estimated_total_days': estimated_total_days,
                'days_remaining': days_remaining,
            },
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
