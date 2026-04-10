"""
Construction Development Simulator — Engine

Simulates a land development project: scheduling crews, building houses
through sequential phases, logging labor hours, and generating real
BusinessEvents with balanced double-entry accounting.

Phase 1 MVP: 10 houses, 3 crew types, 5 phases, FIFO scheduling, labor-only costing.

Usage:
    from services.construction_sim import (
        create_development, initialize_lots, advance_day, advance_days,
        get_development_status, get_lot_detail, get_crew_status,
        get_financial_summary
    )

Author: Matthew Jenkins
Date: 2026-04-10
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from services.accounting import create_business_event, get_account_balances


# =============================================================================
# DATABASE
# =============================================================================

def get_db_connection():
    """Get a database connection with row factory."""
    db_path = Path(__file__).parent.parent / "database" / "artifactlive.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


# =============================================================================
# PRESET: Phase 1 MVP Configuration
# =============================================================================

MVP_CREW_TYPES = [
    {'name': 'General Labor', 'hourly_rate': 25.00},
    {'name': 'Concrete',      'hourly_rate': 45.00},
    {'name': 'Framing',       'hourly_rate': 40.00},
]

MVP_CREWS = [
    # (crew_type_name, crew_name, hours_per_day)
    ('General Labor', 'Site Crew Alpha',    8),
    ('General Labor', 'Site Crew Beta',     8),
    ('Concrete',      'Concrete Crew Alpha', 8),
    ('Framing',       'Framing Crew Alpha',  8),
    ('Framing',       'Framing Crew Beta',   8),
]

MVP_LOT_TYPE = {
    'name': 'Standard House',
    'category': 'house',
    'unit_count': 1,
}

# Phase definitions: (phase_number, name, crew_type_name, base_hours, depends_on, cure_days)
MVP_PHASES = [
    (1, 'Site Prep',    'General Labor', 16,  None, 0),
    (2, 'Foundation',   'Concrete',      40,  1,    3),  # 3-day cure after pour
    (3, 'Framing',      'Framing',       80,  2,    0),
    (4, 'Rough-In',     'General Labor', 60,  3,    0),
    (5, 'Finish',       'General Labor', 40,  4,    0),
]


# =============================================================================
# CHART OF ACCOUNTS for sim business
# =============================================================================

SIM_ACCOUNTS = [
    # (account_name, account_type, subtype, normal_balance)
    ('Cash',                  'ASSET',    'CASH',      'DEBIT'),
    ('Work-In-Progress',      'ASSET',    'WIP',       'DEBIT'),
    ('Inventory — Materials', 'ASSET',    'INVENTORY', 'DEBIT'),
    ('Accounts Payable',      'LIABILITY','AP',        'CREDIT'),
    ('Owner Equity',          'EQUITY',   'EQUITY',    'CREDIT'),
    ('Revenue — Home Sales',  'REVENUE',  'SALES',     'CREDIT'),
    ('COGS — Construction',   'EXPENSE',  'COGS',      'DEBIT'),
    ('Labor Expense',         'EXPENSE',  'LABOR',     'DEBIT'),
]


# =============================================================================
# PUBLIC API: Create & Initialize
# =============================================================================

def create_development(user_id, name, num_houses=10, acreage=None,
                       land_cost=0, budget=0, start_date='2026-01-01',
                       conn=None):
    """
    Create a new development with all crews, lot types, phase templates,
    lots, and lot phases. Sets up the sim business and chart of accounts.

    Returns: dict with development_id and summary counts.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # 1. Create a business for this sim
        cursor.execute("""
            INSERT INTO businesses (user_id, name, business_type, is_active)
            VALUES (?, ?, 'simulation', 1)
        """, (user_id, f"Sim: {name}"))
        business_id = cursor.lastrowid

        # 2. Create chart of accounts
        for acct_name, acct_type, subtype, normal_balance in SIM_ACCOUNTS:
            cursor.execute("""
                INSERT INTO accounts
                    (user_id, account_name, account_type, subtype,
                     normal_balance, is_system, is_active)
                VALUES (?, ?, ?, ?, ?, 1, 1)
            """, (user_id, f"{name} — {acct_name}", acct_type, subtype, normal_balance))

        # Seed cash with budget via direct ledger entries
        # (Using direct insert instead of adjustment event to ensure correct
        # sim-scoped accounts are targeted, since adjustment builder resolves
        # by subtype only and could hit non-sim accounts.)
        if budget > 0:
            import uuid as _uuid
            cash_id = _resolve_sim_account(user_id, name, 'CASH', cursor)
            equity_id = _resolve_sim_account(user_id, name, 'EQUITY', cursor)
            seed_uuid = str(_uuid.uuid4())

            # Create a business event for the initial investment
            seed_event_id = str(_uuid.uuid4())
            cursor.execute("""
                INSERT INTO business_events
                    (event_id, user_id, event_type, event_date, status, source,
                     metadata, notes, created_by)
                VALUES (?, ?, 'adjustment', ?, 'posted', 'auto', ?, ?, ?)
            """, (seed_event_id, user_id, start_date,
                  json.dumps({'reason': f'Initial development budget — {name}'}),
                  f'Budget seed for {name}', user_id))

            cursor.execute("""
                INSERT INTO transactions
                    (transaction_uuid, event_id, user_id, transaction_date,
                     description, is_posted)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (seed_uuid, seed_event_id, user_id, start_date,
                  f'Initial development budget — {name}'))
            seed_txn_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO financial_ledger
                    (user_id, account_id, transaction_uuid, transaction_id,
                     transaction_date, description, debit, credit,
                     reference_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ADJUSTMENT')
            """, (user_id, cash_id, seed_uuid, seed_txn_id, start_date,
                  f'Cash — development budget', budget, 0.0))

            cursor.execute("""
                INSERT INTO financial_ledger
                    (user_id, account_id, transaction_uuid, transaction_id,
                     transaction_date, description, debit, credit,
                     reference_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ADJUSTMENT')
            """, (user_id, equity_id, seed_uuid, seed_txn_id, start_date,
                  f'Owner equity — development investment', 0.0, budget))

        # 3. Create development record
        cursor.execute("""
            INSERT INTO sim_developments
                (user_id, business_id, name, acreage, land_cost, budget,
                 start_date, current_day, status, strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'setup', 'fifo')
        """, (user_id, business_id, name, acreage, land_cost, budget, start_date))
        development_id = cursor.lastrowid

        # 4. Create crew types
        crew_type_map = {}  # name -> crew_type_id
        for ct in MVP_CREW_TYPES:
            cursor.execute("""
                INSERT INTO sim_crew_types (development_id, name, hourly_rate)
                VALUES (?, ?, ?)
            """, (development_id, ct['name'], ct['hourly_rate']))
            crew_type_map[ct['name']] = cursor.lastrowid

        # 5. Create crew instances
        for ct_name, crew_name, hours in MVP_CREWS:
            cursor.execute("""
                INSERT INTO sim_crews (development_id, crew_type_id, name, hours_per_day)
                VALUES (?, ?, ?, ?)
            """, (development_id, crew_type_map[ct_name], crew_name, hours))

        # 6. Create lot type
        cursor.execute("""
            INSERT INTO sim_lot_types (development_id, name, category, unit_count)
            VALUES (?, ?, ?, ?)
        """, (development_id, MVP_LOT_TYPE['name'], MVP_LOT_TYPE['category'],
              MVP_LOT_TYPE['unit_count']))
        lot_type_id = cursor.lastrowid

        # 7. Create phase templates
        template_ids = {}  # phase_number -> template_id
        for phase_num, phase_name, ct_name, base_hours, depends_on, cure_days in MVP_PHASES:
            cursor.execute("""
                INSERT INTO sim_phase_templates
                    (lot_type_id, phase_number, phase_name, crew_type_id,
                     base_hours, depends_on_phase, cure_days)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (lot_type_id, phase_num, phase_name,
                  crew_type_map[ct_name], base_hours, depends_on, cure_days))
            template_ids[phase_num] = cursor.lastrowid

        # 8. Create lots and their phase instances
        for i in range(1, num_houses + 1):
            cursor.execute("""
                INSERT INTO sim_lots
                    (development_id, lot_type_id, lot_number, label, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (development_id, lot_type_id, i, f"House #{i:03d}"))
            lot_id = cursor.lastrowid

            # Create phase instances for this lot
            for phase_num, phase_name, ct_name, base_hours, depends_on, cure_days in MVP_PHASES:
                # First phase with no dependency starts as 'ready'
                status = 'ready' if depends_on is None else 'blocked'
                cursor.execute("""
                    INSERT INTO sim_lot_phases
                        (lot_id, template_id, phase_number, phase_name,
                         crew_type_id, hours_needed, hours_completed, status)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """, (lot_id, template_ids[phase_num], phase_num, phase_name,
                      crew_type_map[ct_name], base_hours, status))

        if owns_conn:
            conn.commit()

        return {
            'development_id': development_id,
            'business_id': business_id,
            'name': name,
            'num_houses': num_houses,
            'num_crews': len(MVP_CREWS),
            'num_phases_per_house': len(MVP_PHASES),
            'total_phases': num_houses * len(MVP_PHASES),
            'status': 'setup',
        }

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


# =============================================================================
# PUBLIC API: Advance Simulation
# =============================================================================

def start_development(user_id, development_id, conn=None):
    """Transition development from 'setup' to 'running'."""
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE sim_developments
            SET status = 'running'
            WHERE development_id = ? AND user_id = ? AND status = 'setup'
        """, (development_id, user_id))

        if cursor.rowcount == 0:
            raise ValueError(f"Development {development_id} not found or not in 'setup' status")

        if owns_conn:
            conn.commit()
        return True

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def advance_day(user_id, development_id, conn=None):
    """
    Advance the simulation by one day. This is the core simulation loop.

    Steps:
    1. Update phase statuses (blocked → ready based on dependencies + curing)
    2. Dispatch idle crews to the next available phase (FIFO by lot number)
    3. Each crew works their hours_per_day on assigned phase
    4. Log labor, generate BusinessEvent for each crew-day
    5. Complete phases that reach their hours_needed
    6. Complete lots where all phases are done
    7. Increment current_day
    8. Check if development is complete

    Returns: dict with day summary (crews dispatched, phases completed, etc.)
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Fetch development
        cursor.execute("""
            SELECT * FROM sim_developments
            WHERE development_id = ? AND user_id = ?
        """, (development_id, user_id))
        dev = cursor.fetchone()
        if not dev:
            raise ValueError(f"Development {development_id} not found")
        if dev['status'] != 'running':
            raise ValueError(f"Development is '{dev['status']}', must be 'running'")

        dev = _row_to_dict(dev)
        current_day = dev['current_day']
        new_day = current_day + 1
        sim_date = _sim_day_to_date(dev['start_date'], new_day)

        # Get development name for account resolution
        dev_name = dev['name']

        # --- Step 1: Update phase statuses ---
        phases_unblocked = _update_phase_statuses(development_id, new_day, cursor)

        # --- Step 2 & 3: Dispatch crews and work ---
        crew_logs = _dispatch_and_work(
            user_id, development_id, dev_name, new_day, sim_date, cursor, conn
        )

        # --- Step 4: Complete finished phases, handle curing ---
        phases_completed = _complete_phases(development_id, new_day, cursor)

        # --- Step 5: Complete lots where all phases done ---
        lots_completed = _complete_lots(development_id, new_day, cursor)

        # --- Step 6: Increment day ---
        cursor.execute("""
            UPDATE sim_developments
            SET current_day = ?
            WHERE development_id = ?
        """, (new_day, development_id))

        # --- Step 7: Check if all lots complete ---
        cursor.execute("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'completed' THEN 1 END) as done
            FROM sim_lots WHERE development_id = ?
        """, (development_id,))
        lot_counts = _row_to_dict(cursor.fetchone())

        is_complete = lot_counts['total'] > 0 and lot_counts['done'] == lot_counts['total']
        if is_complete:
            cursor.execute("""
                UPDATE sim_developments SET status = 'completed' WHERE development_id = ?
            """, (development_id,))

        if owns_conn:
            conn.commit()

        total_hours = sum(log['hours_worked'] for log in crew_logs)
        total_cost = sum(log['labor_cost'] for log in crew_logs)

        return {
            'day': new_day,
            'date': sim_date,
            'crews_working': len(crew_logs),
            'total_hours': total_hours,
            'total_labor_cost': total_cost,
            'phases_unblocked': phases_unblocked,
            'phases_completed': len(phases_completed),
            'lots_completed': len(lots_completed),
            'development_complete': is_complete,
            'crew_details': crew_logs,
            'lots_done': lot_counts['done'],
            'lots_total': lot_counts['total'],
        }

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def advance_days(user_id, development_id, num_days, conn=None):
    """
    Advance the simulation by multiple days. Stops early if development completes.

    Returns: list of day summaries + overall summary.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        day_results = []
        for _ in range(num_days):
            result = advance_day(user_id, development_id, conn=conn)
            day_results.append(result)
            if result['development_complete']:
                break

        if owns_conn:
            conn.commit()

        total_hours = sum(d['total_hours'] for d in day_results)
        total_cost = sum(d['total_labor_cost'] for d in day_results)
        total_phases_completed = sum(d['phases_completed'] for d in day_results)
        total_lots_completed = sum(d['lots_completed'] for d in day_results)

        return {
            'days_advanced': len(day_results),
            'final_day': day_results[-1]['day'] if day_results else 0,
            'total_hours': total_hours,
            'total_labor_cost': total_cost,
            'total_phases_completed': total_phases_completed,
            'total_lots_completed': total_lots_completed,
            'development_complete': day_results[-1]['development_complete'] if day_results else False,
            'daily_log': day_results,
        }

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


# =============================================================================
# PUBLIC API: Queries
# =============================================================================

def get_development_status(user_id, development_id, conn=None):
    """
    Get full development status: lots progress, crew utilization, financials.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Development info
        cursor.execute("""
            SELECT * FROM sim_developments
            WHERE development_id = ? AND user_id = ?
        """, (development_id, user_id))
        dev = cursor.fetchone()
        if not dev:
            return None
        dev = _row_to_dict(dev)

        # Lot summary
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM sim_lots WHERE development_id = ?
            GROUP BY status
        """, (development_id,))
        lot_summary = {row['status']: row['count'] for row in cursor.fetchall()}

        # Phase summary
        cursor.execute("""
            SELECT lp.status, COUNT(*) as count
            FROM sim_lot_phases lp
            JOIN sim_lots l ON lp.lot_id = l.lot_id
            WHERE l.development_id = ?
            GROUP BY lp.status
        """, (development_id,))
        phase_summary = {row['status']: row['count'] for row in cursor.fetchall()}

        # Total labor
        cursor.execute("""
            SELECT COALESCE(SUM(hours_worked), 0) as total_hours,
                   COALESCE(SUM(labor_cost), 0) as total_cost
            FROM sim_daily_log WHERE development_id = ?
        """, (development_id,))
        labor = _row_to_dict(cursor.fetchone())

        # Crew utilization (days worked / total days)
        cursor.execute("""
            SELECT c.crew_id, c.name, ct.name as crew_type,
                   COUNT(DISTINCT dl.sim_day) as days_worked,
                   COALESCE(SUM(dl.hours_worked), 0) as total_hours
            FROM sim_crews c
            JOIN sim_crew_types ct ON c.crew_type_id = ct.crew_type_id
            LEFT JOIN sim_daily_log dl ON c.crew_id = dl.crew_id
            WHERE c.development_id = ?
            GROUP BY c.crew_id
        """, (development_id,))
        crews = [_row_to_dict(r) for r in cursor.fetchall()]

        for crew in crews:
            if dev['current_day'] > 0:
                crew['utilization_pct'] = round(
                    crew['days_worked'] / dev['current_day'] * 100, 1
                )
            else:
                crew['utilization_pct'] = 0.0

        return {
            **dev,
            'lots': lot_summary,
            'phases': phase_summary,
            'labor': labor,
            'crews': crews,
        }

    finally:
        if owns_conn:
            conn.close()


def get_lot_detail(user_id, development_id, lot_id, conn=None):
    """Get detailed status of a single lot with all phases."""
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT l.*, lt.name as lot_type_name
            FROM sim_lots l
            JOIN sim_lot_types lt ON l.lot_type_id = lt.lot_type_id
            WHERE l.lot_id = ? AND l.development_id = ?
        """, (lot_id, development_id))
        lot = cursor.fetchone()
        if not lot:
            return None
        lot = _row_to_dict(lot)

        # Phases with crew assignment info
        cursor.execute("""
            SELECT lp.*, c.name as assigned_crew_name
            FROM sim_lot_phases lp
            LEFT JOIN sim_crews c ON lp.assigned_crew_id = c.crew_id
            WHERE lp.lot_id = ?
            ORDER BY lp.phase_number
        """, (lot_id,))
        lot['phases'] = [_row_to_dict(r) for r in cursor.fetchall()]

        # Labor log for this lot
        cursor.execute("""
            SELECT dl.sim_day, dl.hours_worked, dl.labor_cost,
                   c.name as crew_name, lp.phase_name
            FROM sim_daily_log dl
            JOIN sim_crews c ON dl.crew_id = c.crew_id
            JOIN sim_lot_phases lp ON dl.lot_phase_id = lp.lot_phase_id
            WHERE lp.lot_id = ?
            ORDER BY dl.sim_day
        """, (lot_id,))
        lot['labor_log'] = [_row_to_dict(r) for r in cursor.fetchall()]

        total_hours = sum(p['hours_completed'] for p in lot['phases'])
        total_needed = sum(p['hours_needed'] for p in lot['phases'])
        lot['progress_pct'] = round(total_hours / total_needed * 100, 1) if total_needed > 0 else 0

        return lot

    finally:
        if owns_conn:
            conn.close()


def get_financial_summary(user_id, development_id, conn=None):
    """
    Get financial summary: labor cost breakdown by phase, budget vs actual,
    account balances.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Development info
        cursor.execute("""
            SELECT name, budget, current_day FROM sim_developments
            WHERE development_id = ? AND user_id = ?
        """, (development_id, user_id))
        dev = cursor.fetchone()
        if not dev:
            return None
        dev = _row_to_dict(dev)

        # Labor cost by phase type
        cursor.execute("""
            SELECT lp.phase_name,
                   COUNT(DISTINCT dl.sim_day || '-' || dl.crew_id) as crew_days,
                   COALESCE(SUM(dl.hours_worked), 0) as total_hours,
                   COALESCE(SUM(dl.labor_cost), 0) as total_cost
            FROM sim_daily_log dl
            JOIN sim_lot_phases lp ON dl.lot_phase_id = lp.lot_phase_id
            JOIN sim_lots l ON lp.lot_id = l.lot_id
            WHERE l.development_id = ?
            GROUP BY lp.phase_name
            ORDER BY MIN(lp.phase_number)
        """, (development_id,))
        cost_by_phase = [_row_to_dict(r) for r in cursor.fetchall()]

        # Total spent
        total_spent = sum(p['total_cost'] for p in cost_by_phase)

        # Account balances
        balances = get_account_balances(user_id, conn=conn)
        # Filter to sim accounts (they're prefixed with development name)
        sim_balances = [b for b in balances if b['account_name'].startswith(f"{dev['name']} —")]

        return {
            'development_name': dev['name'],
            'budget': dev['budget'],
            'total_spent': total_spent,
            'budget_remaining': dev['budget'] - total_spent,
            'budget_used_pct': round(total_spent / dev['budget'] * 100, 1) if dev['budget'] > 0 else 0,
            'current_day': dev['current_day'],
            'cost_by_phase': cost_by_phase,
            'account_balances': sim_balances,
        }

    finally:
        if owns_conn:
            conn.close()


# =============================================================================
# INTERNAL: Phase status management
# =============================================================================

def _update_phase_statuses(development_id, current_day, cursor):
    """
    Update blocked phases to ready when their dependency is met.
    Also transitions curing phases to ready when cure period expires.

    Returns: count of phases unblocked.
    """
    unblocked = 0

    # Handle curing → ready
    cursor.execute("""
        UPDATE sim_lot_phases
        SET status = 'ready', ready_day = ?
        WHERE status = 'curing' AND cure_until_day <= ?
        AND lot_id IN (SELECT lot_id FROM sim_lots WHERE development_id = ?)
    """, (current_day, current_day, development_id))
    unblocked += cursor.rowcount

    # Handle blocked → ready (dependency completed or cured)
    # A phase is ready when its predecessor (by depends_on_phase) is completed
    # AND any cure period has passed.
    cursor.execute("""
        SELECT lp.lot_phase_id, lp.lot_id, lp.phase_number, pt.depends_on_phase
        FROM sim_lot_phases lp
        JOIN sim_phase_templates pt ON lp.template_id = pt.template_id
        WHERE lp.status = 'blocked'
        AND lp.lot_id IN (SELECT lot_id FROM sim_lots WHERE development_id = ?)
    """, (development_id,))
    blocked_phases = cursor.fetchall()

    for bp in blocked_phases:
        bp = _row_to_dict(bp)
        if bp['depends_on_phase'] is None:
            # No dependency — should be ready
            cursor.execute(
                "UPDATE sim_lot_phases SET status = 'ready', ready_day = ? WHERE lot_phase_id = ?",
                (current_day, bp['lot_phase_id'])
            )
            unblocked += 1
            continue

        # Check if predecessor is completed, and get its cure_days
        cursor.execute("""
            SELECT lp.status, lp.completed_day, pt.cure_days
            FROM sim_lot_phases lp
            JOIN sim_phase_templates pt ON lp.template_id = pt.template_id
            WHERE lp.lot_id = ? AND lp.phase_number = ?
        """, (bp['lot_id'], bp['depends_on_phase']))
        pred = cursor.fetchone()

        if pred and pred['status'] == 'completed':
            # Check cure period (cure_days belongs to the predecessor — e.g., foundation cures)
            cure_days = pred['cure_days'] or 0
            if cure_days > 0 and pred['completed_day'] is not None:
                cure_until = pred['completed_day'] + cure_days
                if current_day < cure_until:
                    # Still curing — mark as curing with target day
                    cursor.execute("""
                        UPDATE sim_lot_phases
                        SET status = 'curing', cure_until_day = ?
                        WHERE lot_phase_id = ?
                    """, (cure_until, bp['lot_phase_id']))
                    continue

            # Dependency met, no cure (or cure passed)
            cursor.execute(
                "UPDATE sim_lot_phases SET status = 'ready', ready_day = ? WHERE lot_phase_id = ?",
                (current_day, bp['lot_phase_id'])
            )
            unblocked += 1

    return unblocked


def _dispatch_and_work(user_id, development_id, dev_name, sim_day, sim_date, cursor, conn):
    """
    Assign idle crews to the next available phase (FIFO by lot number),
    then work their hours. Generates a labor BusinessEvent for each crew-day.

    Returns: list of crew log dicts.
    """
    # Get all active crews with their types
    cursor.execute("""
        SELECT c.crew_id, c.name as crew_name, c.hours_per_day,
               c.crew_type_id, ct.name as crew_type_name, ct.hourly_rate
        FROM sim_crews c
        JOIN sim_crew_types ct ON c.crew_type_id = ct.crew_type_id
        WHERE c.development_id = ? AND c.is_active = 1
    """, (development_id,))
    crews = [_row_to_dict(r) for r in cursor.fetchall()]

    crew_logs = []

    for crew in crews:
        # Find work for this crew: phases that are ready or in_progress
        # matching this crew's type, FIFO by lot number then phase number.
        # Prefer continuing in_progress work (already assigned to this crew).
        cursor.execute("""
            SELECT lp.lot_phase_id, lp.lot_id, lp.phase_number, lp.phase_name,
                   lp.hours_needed, lp.hours_completed, lp.status,
                   l.lot_number, l.label
            FROM sim_lot_phases lp
            JOIN sim_lots l ON lp.lot_id = l.lot_id
            WHERE l.development_id = ?
            AND lp.crew_type_id = ?
            AND lp.status IN ('ready', 'in_progress')
            AND lp.hours_completed < lp.hours_needed
            ORDER BY
                CASE WHEN lp.assigned_crew_id = ? THEN 0 ELSE 1 END,
                l.lot_number ASC,
                lp.phase_number ASC
            LIMIT 1
        """, (development_id, crew['crew_type_id'], crew['crew_id']))

        phase = cursor.fetchone()
        if not phase:
            continue  # No work available for this crew type

        phase = _row_to_dict(phase)
        hours_remaining = phase['hours_needed'] - phase['hours_completed']
        hours_worked = min(crew['hours_per_day'], hours_remaining)
        labor_cost = round(hours_worked * crew['hourly_rate'], 2)

        # Update phase progress
        new_hours = phase['hours_completed'] + hours_worked
        new_status = 'in_progress'
        if new_hours >= phase['hours_needed']:
            new_hours = phase['hours_needed']
            # Don't complete here — _complete_phases handles that

        cursor.execute("""
            UPDATE sim_lot_phases
            SET hours_completed = ?,
                status = ?,
                assigned_crew_id = ?,
                started_day = COALESCE(started_day, ?)
            WHERE lot_phase_id = ?
        """, (new_hours, new_status, crew['crew_id'], sim_day, phase['lot_phase_id']))

        # Update lot status
        cursor.execute("""
            UPDATE sim_lots
            SET status = 'in_progress',
                started_day = COALESCE(started_day, ?)
            WHERE lot_id = ? AND status = 'pending'
        """, (sim_day, phase['lot_id']))

        # Generate labor BusinessEvent
        event_result = create_business_event(
            user_id=user_id,
            event_type='labor',
            event_date=sim_date,
            metadata={
                'crew_name': crew['crew_name'],
                'crew_id': crew['crew_id'],
                'hours': hours_worked,
                'hourly_rate': crew['hourly_rate'],
                'lot_label': phase['label'],
                'lot_phase_id': phase['lot_phase_id'],
                'phase_name': phase['phase_name'],
                'sim_day': sim_day,
                'account_prefix': dev_name,
            },
            entity_type='sim_lot_phase',
            entity_id=phase['lot_phase_id'],
            source='auto',
            auto_post=True,
            conn=conn,
        )

        # Log to daily log
        cursor.execute("""
            INSERT INTO sim_daily_log
                (development_id, sim_day, crew_id, lot_phase_id,
                 hours_worked, labor_cost, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (development_id, sim_day, crew['crew_id'],
              phase['lot_phase_id'], hours_worked, labor_cost,
              event_result['event_id']))

        crew_logs.append({
            'crew_name': crew['crew_name'],
            'crew_type': crew['crew_type_name'],
            'lot': phase['label'],
            'phase': phase['phase_name'],
            'hours_worked': hours_worked,
            'labor_cost': labor_cost,
            'event_id': event_result['event_id'],
        })

    return crew_logs


def _complete_phases(development_id, current_day, cursor):
    """
    Mark phases as completed where hours_completed >= hours_needed.
    Handles cure_days by checking phase template.

    Returns: list of completed phase dicts.
    """
    cursor.execute("""
        SELECT lp.lot_phase_id, lp.lot_id, lp.phase_number, lp.phase_name,
               pt.cure_days
        FROM sim_lot_phases lp
        JOIN sim_phase_templates pt ON lp.template_id = pt.template_id
        JOIN sim_lots l ON lp.lot_id = l.lot_id
        WHERE l.development_id = ?
        AND lp.status = 'in_progress'
        AND lp.hours_completed >= lp.hours_needed
    """, (development_id,))
    ready_to_complete = cursor.fetchall()

    completed = []
    for phase in ready_to_complete:
        phase = _row_to_dict(phase)
        cursor.execute("""
            UPDATE sim_lot_phases
            SET status = 'completed', completed_day = ?, assigned_crew_id = NULL
            WHERE lot_phase_id = ?
        """, (current_day, phase['lot_phase_id']))
        completed.append(phase)

    return completed


def _complete_lots(development_id, current_day, cursor):
    """Mark lots as completed where all phases are done."""
    cursor.execute("""
        SELECT l.lot_id, l.label
        FROM sim_lots l
        WHERE l.development_id = ? AND l.status = 'in_progress'
        AND NOT EXISTS (
            SELECT 1 FROM sim_lot_phases lp
            WHERE lp.lot_id = l.lot_id AND lp.status != 'completed'
        )
    """, (development_id,))
    lots_to_complete = cursor.fetchall()

    completed = []
    for lot in lots_to_complete:
        lot = _row_to_dict(lot)
        cursor.execute("""
            UPDATE sim_lots SET status = 'completed', completed_day = ?
            WHERE lot_id = ?
        """, (current_day, lot['lot_id']))
        completed.append(lot)

    return completed


# =============================================================================
# INTERNAL: Helpers
# =============================================================================

def _sim_day_to_date(start_date_str, sim_day):
    """Convert a sim day number to a YYYY-MM-DD date string."""
    start = datetime.strptime(start_date_str, '%Y-%m-%d')
    target = start + timedelta(days=sim_day)
    return target.strftime('%Y-%m-%d')


def _resolve_sim_account(user_id, dev_name, subtype, cursor):
    """
    Resolve a sim account by subtype. Sim accounts are prefixed with the
    development name (e.g., "Oakwood Estates — Cash").
    """
    cursor.execute("""
        SELECT account_id FROM accounts
        WHERE user_id = ? AND subtype = ? AND is_active = 1 AND is_deleted = 0
        AND account_name LIKE ?
    """, (user_id, subtype, f"{dev_name} —%"))
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"No sim account found: {dev_name} — subtype '{subtype}'")
    return row['account_id']
