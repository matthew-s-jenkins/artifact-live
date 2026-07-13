"""
Construction Development Simulator — Engine

Simulates a land development project: scheduling crews, building houses
through sequential phases, logging labor hours, consuming materials,
and generating real BusinessEvents with balanced double-entry accounting.

Supports two presets:
  - 'mvp':        10 houses, 3 crew types, 5 phases, labor-only
  - 'full_scale': 96 houses + 4 condo buildings, 9 crew types, 10 phases,
                   parallel rough-in, materials/PO system

Usage:
    from services.construction_sim import (
        create_development, start_development, advance_day, advance_days,
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
# PRESET: Full-Scale Configuration (96 houses + 4 condo buildings)
# =============================================================================

FULL_CREW_TYPES = [
    {'name': 'General Labor', 'hourly_rate': 25.00},
    {'name': 'Concrete',      'hourly_rate': 45.00},
    {'name': 'Framing',       'hourly_rate': 40.00},
    {'name': 'Electrical',    'hourly_rate': 35.00},
    {'name': 'Plumbing',      'hourly_rate': 38.00},
    {'name': 'HVAC',          'hourly_rate': 42.00},
    {'name': 'Drywall',       'hourly_rate': 35.00},
    {'name': 'Finish',        'hourly_rate': 32.00},
    {'name': 'Landscaping',   'hourly_rate': 28.00},
]

FULL_CREWS = [
    ('General Labor', 'Site Crew Alpha',      8),
    ('General Labor', 'Site Crew Beta',       8),
    ('General Labor', 'Site Crew Gamma',      8),
    ('General Labor', 'Site Crew Delta',      8),
    ('Concrete',      'Concrete Crew Alpha',  8),
    ('Concrete',      'Concrete Crew Beta',   8),
    ('Concrete',      'Concrete Crew Gamma',  8),
    ('Framing',       'Framing Crew Alpha',   8),
    ('Framing',       'Framing Crew Beta',    8),
    ('Framing',       'Framing Crew Gamma',   8),
    ('Framing',       'Framing Crew Delta',   8),
    ('Electrical',    'Electrical Crew Alpha', 8),
    ('Electrical',    'Electrical Crew Beta',  8),
    ('Plumbing',      'Plumbing Crew Alpha',  8),
    ('Plumbing',      'Plumbing Crew Beta',   8),
    ('HVAC',          'HVAC Crew Alpha',      8),
    ('HVAC',          'HVAC Crew Beta',       8),
    ('Drywall',       'Drywall Crew Alpha',   8),
    ('Drywall',       'Drywall Crew Beta',    8),
    ('Drywall',       'Drywall Crew Gamma',   8),
    ('Finish',        'Finish Crew Alpha',    8),
    ('Finish',        'Finish Crew Beta',     8),
    ('Finish',        'Finish Crew Gamma',    8),
    ('Landscaping',   'Landscaping Crew Alpha', 8),
    ('Landscaping',   'Landscaping Crew Beta',  8),
]

FULL_LOT_TYPE_HOUSE = {
    'name': 'Standard House',
    'category': 'house',
    'unit_count': 1,
}

FULL_LOT_TYPE_CONDO = {
    'name': 'Condo Building',
    'category': 'condo_building',
    'unit_count': 53,
}

# Phase definitions for full-scale houses
# (phase_number, name, crew_type_name, base_hours, depends_on_phases[], cure_days, scales_with_units)
FULL_PHASES_HOUSE = [
    (1,  'Site Prep',           'General Labor', 16,  [],        0, False),
    (2,  'Foundation',          'Concrete',      40,  [1],       3, False),
    (3,  'Framing',             'Framing',       80,  [2],       0, False),
    (4,  'Electrical Rough-In', 'Electrical',    20,  [3],       0, False),
    (5,  'Plumbing Rough-In',   'Plumbing',      20,  [3],       0, False),
    (6,  'HVAC Rough-In',       'HVAC',          20,  [3],       0, False),
    (7,  'Insulation/Drywall',  'Drywall',       40,  [4, 5, 6], 0, False),
    (8,  'Interior Finish',     'Finish',        60,  [7],       0, False),
    (9,  'Exterior',            'Landscaping',   30,  [3],       0, False),
    (10, 'Final/Inspection',    'General Labor',  8,  [8, 9],    0, False),
]

# Phase definitions for condo buildings (scaled hours)
FULL_PHASES_CONDO = [
    (1,  'Site Prep',           'General Labor',  40,  [],        0, False),
    (2,  'Foundation',          'Concrete',      120,  [1],       3, False),
    (3,  'Structural Frame',    'Framing',       300,  [2],       0, False),
    (4,  'Electrical Rough-In', 'Electrical',     70,  [3],       0, False),
    (5,  'Plumbing Rough-In',   'Plumbing',       70,  [3],       0, False),
    (6,  'HVAC Rough-In',       'HVAC',           60,  [3],       0, False),
    (7,  'Insulation/Drywall',  'Drywall',       160,  [4, 5, 6], 0, False),
    (8,  'Unit Finish',         'Finish',         30,  [7],       0, True),  # 30h * 53 units
    (9,  'Common Areas',        'Finish',         80,  [7],       0, False),
    (10, 'Final/Inspection',    'General Labor',  40,  [8, 9],    0, False),
]

# Material catalog: (name, unit, unit_cost, lead_time_days, vendor_name)
FULL_MATERIALS = [
    ('Concrete Mix',    'cubic_yd',  125.00, 2, 'Triangle Concrete'),
    ('Lumber',          'board_ft',    0.85, 3, 'Carolina Lumber Co'),
    ('Rebar & Forms',   'lot',       800.00, 2, 'Triangle Concrete'),
    ('Copper Wire',     'roll',       95.00, 3, 'Raleigh Electric Supply'),
    ('PVC Pipe',        'bundle',     65.00, 3, 'Apex Plumbing Supply'),
    ('HVAC Ductwork',   'kit',       450.00, 5, 'Comfort Air Distributors'),
    ('Insulation',      'roll',       42.00, 2, 'Carolina Lumber Co'),
    ('Drywall Sheets',  'sheet',      12.50, 2, 'Carolina Lumber Co'),
    ('Paint & Trim',    'kit',       350.00, 3, 'Sherwin-Williams'),
    ('Cabinets/Fixtures','set',     2200.00, 7, 'Triangle Cabinet Works'),
    ('Sod & Plants',    'lot',       600.00, 3, 'Green Acres Nursery'),
    ('Roofing',         'square',     85.00, 3, 'Carolina Lumber Co'),
    ('Siding',          'square',     65.00, 3, 'Carolina Lumber Co'),
]

# Materials required per phase: {phase_name: [(material_name, quantity_per_lot)]}
# These map to FULL_PHASES_HOUSE. Condo quantities are multiplied by a factor.
FULL_PHASE_MATERIALS_HOUSE = {
    'Site Prep':           [],  # labor only
    'Foundation':          [('Concrete Mix', 30), ('Rebar & Forms', 1)],
    'Framing':             [('Lumber', 8000), ('Roofing', 25)],
    'Electrical Rough-In': [('Copper Wire', 12)],
    'Plumbing Rough-In':   [('PVC Pipe', 8)],
    'HVAC Rough-In':       [('HVAC Ductwork', 1)],
    'Insulation/Drywall':  [('Insulation', 40), ('Drywall Sheets', 120)],
    'Interior Finish':     [('Paint & Trim', 1), ('Cabinets/Fixtures', 1)],
    'Exterior':            [('Siding', 15), ('Sod & Plants', 1)],
    'Final/Inspection':    [],  # labor only
}

FULL_PHASE_MATERIALS_CONDO = {
    'Site Prep':           [],
    'Foundation':          [('Concrete Mix', 120), ('Rebar & Forms', 4)],
    'Structural Frame':    [('Lumber', 40000), ('Roofing', 80)],
    'Electrical Rough-In': [('Copper Wire', 60)],
    'Plumbing Rough-In':   [('PVC Pipe', 40)],
    'HVAC Rough-In':       [('HVAC Ductwork', 8)],
    'Insulation/Drywall':  [('Insulation', 200), ('Drywall Sheets', 600)],
    'Unit Finish':         [('Paint & Trim', 53), ('Cabinets/Fixtures', 53)],
    'Common Areas':        [('Paint & Trim', 2)],
    'Final/Inspection':    [],
}


# =============================================================================
# PRESETS — Preset configurations for development creation
# =============================================================================

PRESETS = {
    'mvp': {
        'crew_types': MVP_CREW_TYPES,
        'crews': MVP_CREWS,
        'lot_configs': [
            {
                'type': MVP_LOT_TYPE,
                'count': 10,
                'phases': MVP_PHASES,
                'phase_materials': {},
            },
        ],
        'materials': [],
    },
    'full_scale': {
        'crew_types': FULL_CREW_TYPES,
        'crews': FULL_CREWS,
        'lot_configs': [
            {
                'type': FULL_LOT_TYPE_HOUSE,
                'count': 96,
                'phases': FULL_PHASES_HOUSE,
                'phase_materials': FULL_PHASE_MATERIALS_HOUSE,
            },
            {
                'type': FULL_LOT_TYPE_CONDO,
                'count': 4,
                'phases': FULL_PHASES_CONDO,
                'phase_materials': FULL_PHASE_MATERIALS_CONDO,
            },
        ],
        'materials': FULL_MATERIALS,
    },
}


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

def create_development(user_id, name, preset='mvp', num_houses=None,
                       acreage=None, land_cost=0, budget=0,
                       start_date='2026-01-01', conn=None):
    """
    Create a new development from a preset configuration.

    Presets:
      - 'mvp':        10 houses, 3 crew types, 5 phases (Phase 1 behavior)
      - 'full_scale': 96 houses + 4 condo buildings, 9 crew types, 10 phases

    num_houses overrides the first lot_config count if provided (backward compat).

    Returns: dict with development_id and summary counts.
    """
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset '{preset}'. Valid: {', '.join(PRESETS.keys())}")

    config = PRESETS[preset]
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
        if budget > 0:
            _seed_budget(user_id, name, budget, start_date, cursor)

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
        for ct in config['crew_types']:
            cursor.execute("""
                INSERT INTO sim_crew_types (development_id, name, hourly_rate)
                VALUES (?, ?, ?)
            """, (development_id, ct['name'], ct['hourly_rate']))
            crew_type_map[ct['name']] = cursor.lastrowid

        # 5. Create crew instances
        for ct_name, crew_name, hours in config['crews']:
            cursor.execute("""
                INSERT INTO sim_crews (development_id, crew_type_id, name, hours_per_day)
                VALUES (?, ?, ?, ?)
            """, (development_id, crew_type_map[ct_name], crew_name, hours))

        # 6. Create materials catalog (if any)
        material_map = {}  # material_name -> material_id
        for mat_def in config.get('materials', []):
            mat_name, unit, unit_cost, lead_time, vendor = mat_def
            cursor.execute("""
                INSERT INTO sim_materials
                    (development_id, name, unit, unit_cost, lead_time_days, vendor_name)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (development_id, mat_name, unit, unit_cost, lead_time, vendor))
            material_map[mat_name] = cursor.lastrowid

            # Initialize inventory at zero
            cursor.execute("""
                INSERT INTO sim_inventory
                    (development_id, material_id, quantity_on_hand, quantity_on_order)
                VALUES (?, ?, 0, 0)
            """, (development_id, cursor.lastrowid))

        # 7. Create lot types, phase templates, dependencies, and lots
        total_lots = 0
        total_phases = 0
        lot_number = 1  # global lot numbering across all types
        condo_letter = ord('A')

        for lot_cfg in config['lot_configs']:
            lot_type_def = lot_cfg['type']
            count = lot_cfg['count']
            phases = lot_cfg['phases']
            phase_mats = lot_cfg.get('phase_materials', {})

            # Override count for first lot type if num_houses provided
            if num_houses is not None and total_lots == 0:
                count = num_houses

            # Create lot type
            cursor.execute("""
                INSERT INTO sim_lot_types
                    (development_id, name, category, unit_count)
                VALUES (?, ?, ?, ?)
            """, (development_id, lot_type_def['name'], lot_type_def['category'],
                  lot_type_def['unit_count']))
            lot_type_id = cursor.lastrowid

            # Create phase templates for this lot type
            template_ids = {}  # phase_number -> template_id
            is_new_format = len(phases[0]) == 7  # new format has 7 fields

            for phase_def in phases:
                if is_new_format:
                    phase_num, phase_name, ct_name, base_hours, deps, cure_days, swu = phase_def
                else:
                    # Legacy MVP format: (phase_number, name, crew_type, base_hours, depends_on, cure_days)
                    phase_num, phase_name, ct_name, base_hours, deps, cure_days = phase_def
                    swu = False

                cursor.execute("""
                    INSERT INTO sim_phase_templates
                        (lot_type_id, phase_number, phase_name, crew_type_id,
                         base_hours, depends_on_phase, cure_days, scales_with_units)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (lot_type_id, phase_num, phase_name,
                      crew_type_map[ct_name], base_hours,
                      deps if isinstance(deps, int) or deps is None else None,
                      cure_days, 1 if swu else 0))
                template_ids[phase_num] = cursor.lastrowid

                # Create phase-material links
                mat_list = phase_mats.get(phase_name, [])
                for mat_name, qty in mat_list:
                    if mat_name in material_map:
                        cursor.execute("""
                            INSERT INTO sim_phase_materials
                                (template_id, material_id, quantity)
                            VALUES (?, ?, ?)
                        """, (template_ids[phase_num], material_map[mat_name], qty))

            # Insert multi-predecessor dependencies (new format only)
            if is_new_format:
                for phase_def in phases:
                    phase_num, _, _, _, deps, _, _ = phase_def
                    if isinstance(deps, list):
                        for dep_phase_num in deps:
                            if dep_phase_num in template_ids:
                                cursor.execute("""
                                    INSERT OR IGNORE INTO sim_phase_dependencies
                                        (template_id, depends_on_template_id)
                                    VALUES (?, ?)
                                """, (template_ids[phase_num],
                                      template_ids[dep_phase_num]))

            # Determine which phases have dependencies (for initial status)
            phases_with_deps = set()
            if is_new_format:
                for phase_def in phases:
                    phase_num, _, _, _, deps, _, _ = phase_def
                    if isinstance(deps, list) and len(deps) > 0:
                        phases_with_deps.add(phase_num)
            else:
                for phase_def in phases:
                    phase_num, _, _, _, deps, _ = phase_def
                    if deps is not None:
                        phases_with_deps.add(phase_num)

            # Check which phases need materials
            phases_needing_materials = set()
            if material_map:
                for phase_def in phases:
                    pn = phase_def[0]
                    pname = phase_def[1]
                    if phase_mats.get(pname):
                        phases_needing_materials.add(pn)

            # Create lots
            unit_count = lot_type_def.get('unit_count', 1)
            is_condo = lot_type_def['category'] == 'condo_building'

            for i in range(count):
                if is_condo:
                    label = f"Condo Bldg {chr(condo_letter)}"
                    condo_letter += 1
                else:
                    label = f"House #{lot_number:03d}"

                cursor.execute("""
                    INSERT INTO sim_lots
                        (development_id, lot_type_id, lot_number, label, status)
                    VALUES (?, ?, ?, ?, 'pending')
                """, (development_id, lot_type_id, lot_number, label))
                lot_id = cursor.lastrowid
                lot_number += 1

                # Create phase instances for this lot
                for phase_def in phases:
                    if is_new_format:
                        pn, pname, ct_name, base_hours, deps, _, swu = phase_def
                    else:
                        pn, pname, ct_name, base_hours, deps, _ = phase_def
                        swu = False

                    status = 'blocked' if pn in phases_with_deps else 'ready'
                    hours = base_hours * unit_count if swu else base_hours
                    mat_ready = 0 if pn in phases_needing_materials else 1

                    cursor.execute("""
                        INSERT INTO sim_lot_phases
                            (lot_id, template_id, phase_number, phase_name,
                             crew_type_id, hours_needed, hours_completed,
                             status, materials_ready)
                        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """, (lot_id, template_ids[pn], pn, pname,
                          crew_type_map[ct_name], hours, status, mat_ready))

                total_phases += len(phases)

            total_lots += count

        if owns_conn:
            conn.commit()

        return {
            'development_id': development_id,
            'business_id': business_id,
            'name': name,
            'preset': preset,
            'total_lots': total_lots,
            'num_crews': len(config['crews']),
            'total_phases': total_phases,
            'num_materials': len(material_map),
            'status': 'setup',
        }

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def _seed_budget(user_id, dev_name, budget, start_date, cursor):
    """Seed the development's cash account with the budget amount."""
    import uuid as _uuid
    cash_id = _resolve_sim_account(user_id, dev_name, 'CASH', cursor)
    equity_id = _resolve_sim_account(user_id, dev_name, 'EQUITY', cursor)
    seed_uuid = str(_uuid.uuid4())

    seed_event_id = str(_uuid.uuid4())
    cursor.execute("""
        INSERT INTO business_events
            (event_id, user_id, event_type, event_date, status, source,
             metadata, notes, created_by)
        VALUES (?, ?, 'adjustment', ?, 'posted', 'auto', ?, ?, ?)
    """, (seed_event_id, user_id, start_date,
          json.dumps({'reason': f'Initial development budget — {dev_name}'}),
          f'Budget seed for {dev_name}', user_id))

    cursor.execute("""
        INSERT INTO transactions
            (transaction_uuid, event_id, user_id, transaction_date,
             description, is_posted)
        VALUES (?, ?, ?, ?, ?, 1)
    """, (seed_uuid, seed_event_id, user_id, start_date,
          f'Initial development budget — {dev_name}'))
    seed_txn_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO financial_ledger
            (user_id, account_id, transaction_uuid, transaction_id,
             transaction_date, description, debit, credit, reference_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ADJUSTMENT')
    """, (user_id, cash_id, seed_uuid, seed_txn_id, start_date,
          'Cash — development budget', budget, 0.0))

    cursor.execute("""
        INSERT INTO financial_ledger
            (user_id, account_id, transaction_uuid, transaction_id,
             transaction_date, description, debit, credit, reference_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ADJUSTMENT')
    """, (user_id, equity_id, seed_uuid, seed_txn_id, start_date,
          'Owner equity — development investment', 0.0, budget))


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
    1.  Update phase statuses (blocked → ready based on dependencies + curing)
    1a. Receive material deliveries (POs due today)
    1b. Check material readiness for ready phases
    1c. Auto-create POs for phases that need materials
    2.  Dispatch idle crews to the next available phase (FIFO by lot number)
    3.  Each crew works their hours_per_day on assigned phase
    4.  Log labor, generate BusinessEvent for each crew-day
    5.  Consume materials for phases that had work done
    6.  Complete phases that reach their hours_needed
    7.  Complete lots where all phases are done
    8.  Increment current_day
    9.  Process vendor payments due
    10. Check if development is complete

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

        # --- Step 1a: Receive material deliveries ---
        deliveries = _receive_deliveries(
            user_id, development_id, dev_name, new_day, sim_date, cursor, conn
        )

        # --- Step 1b: Check material readiness for ready phases ---
        _check_material_readiness(development_id, cursor)

        # --- Step 1c: Auto-create POs for phases that need materials ---
        pos_created = _auto_create_pos(development_id, new_day, cursor)

        # --- Step 2 & 3: Dispatch crews and work ---
        crew_logs = _dispatch_and_work(
            user_id, development_id, dev_name, new_day, sim_date, cursor, conn
        )

        # --- Step 5: Consume materials for worked phases ---
        materials_consumed = _consume_materials(
            user_id, development_id, dev_name, new_day, sim_date,
            crew_logs, cursor, conn
        )

        # --- Step 6: Complete finished phases, handle curing ---
        phases_completed = _complete_phases(development_id, new_day, cursor)

        # --- Step 7: Complete lots where all phases done ---
        lots_completed = _complete_lots(development_id, new_day, cursor)

        # --- Step 8: Increment day ---
        cursor.execute("""
            UPDATE sim_developments
            SET current_day = ?
            WHERE development_id = ?
        """, (new_day, development_id))

        # --- Step 9: Process vendor payments ---
        payments = _process_vendor_payments(
            user_id, development_id, dev_name, new_day, sim_date, cursor, conn
        )

        # --- Step 10: Check if all lots complete ---
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
            'deliveries': len(deliveries),
            'pos_created': pos_created,
            'materials_consumed': materials_consumed,
            'vendor_payments': len(payments),
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
    Update blocked phases to ready when their dependencies are met.
    Also transitions curing phases to ready when cure period expires.

    Supports both:
    - Legacy single-predecessor (depends_on_phase column) for MVP preset
    - Multi-predecessor (sim_phase_dependencies junction table) for full_scale

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

    # Batch-fetch ALL dependencies for this development into a dict
    # {template_id: [depends_on_template_id, ...]}
    cursor.execute("""
        SELECT d.template_id, d.depends_on_template_id
        FROM sim_phase_dependencies d
        JOIN sim_phase_templates pt ON d.template_id = pt.template_id
        JOIN sim_lot_types lt ON pt.lot_type_id = lt.lot_type_id
        WHERE lt.development_id = ?
    """, (development_id,))
    dep_map = {}
    for row in cursor.fetchall():
        dep_map.setdefault(row['template_id'], []).append(row['depends_on_template_id'])

    # Get all blocked phases
    cursor.execute("""
        SELECT lp.lot_phase_id, lp.lot_id, lp.phase_number, lp.template_id,
               pt.depends_on_phase
        FROM sim_lot_phases lp
        JOIN sim_phase_templates pt ON lp.template_id = pt.template_id
        WHERE lp.status = 'blocked'
        AND lp.lot_id IN (SELECT lot_id FROM sim_lots WHERE development_id = ?)
    """, (development_id,))
    blocked_phases = cursor.fetchall()

    for bp in blocked_phases:
        bp = _row_to_dict(bp)
        template_id = bp['template_id']

        # Check junction table first (new multi-dep model)
        dep_template_ids = dep_map.get(template_id)

        if dep_template_ids:
            # Multi-dependency: ALL predecessors must be completed
            all_met = True
            max_cure_until = 0

            for dep_tmpl_id in dep_template_ids:
                cursor.execute("""
                    SELECT lp.status, lp.completed_day, pt.cure_days
                    FROM sim_lot_phases lp
                    JOIN sim_phase_templates pt ON lp.template_id = pt.template_id
                    WHERE lp.lot_id = ? AND lp.template_id = ?
                """, (bp['lot_id'], dep_tmpl_id))
                pred = cursor.fetchone()

                if not pred or pred['status'] != 'completed':
                    all_met = False
                    break

                cure_days = pred['cure_days'] or 0
                if cure_days > 0 and pred['completed_day'] is not None:
                    cure_until = pred['completed_day'] + cure_days
                    max_cure_until = max(max_cure_until, cure_until)

            if all_met:
                if max_cure_until > current_day:
                    cursor.execute("""
                        UPDATE sim_lot_phases
                        SET status = 'curing', cure_until_day = ?
                        WHERE lot_phase_id = ?
                    """, (max_cure_until, bp['lot_phase_id']))
                else:
                    cursor.execute(
                        "UPDATE sim_lot_phases SET status = 'ready', ready_day = ? WHERE lot_phase_id = ?",
                        (current_day, bp['lot_phase_id'])
                    )
                    unblocked += 1

        elif bp['depends_on_phase'] is not None:
            # Legacy single-predecessor (MVP preset)
            cursor.execute("""
                SELECT lp.status, lp.completed_day, pt.cure_days
                FROM sim_lot_phases lp
                JOIN sim_phase_templates pt ON lp.template_id = pt.template_id
                WHERE lp.lot_id = ? AND lp.phase_number = ?
            """, (bp['lot_id'], bp['depends_on_phase']))
            pred = cursor.fetchone()

            if pred and pred['status'] == 'completed':
                cure_days = pred['cure_days'] or 0
                if cure_days > 0 and pred['completed_day'] is not None:
                    cure_until = pred['completed_day'] + cure_days
                    if current_day < cure_until:
                        cursor.execute("""
                            UPDATE sim_lot_phases
                            SET status = 'curing', cure_until_day = ?
                            WHERE lot_phase_id = ?
                        """, (cure_until, bp['lot_phase_id']))
                        continue

                cursor.execute(
                    "UPDATE sim_lot_phases SET status = 'ready', ready_day = ? WHERE lot_phase_id = ?",
                    (current_day, bp['lot_phase_id'])
                )
                unblocked += 1

        else:
            # No dependency at all — should be ready
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
            AND lp.materials_ready = 1
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
# INTERNAL: Materials & PO System
# =============================================================================

NET_PAYMENT_DAYS = 30  # Pay vendor invoices 30 days after delivery


def _receive_deliveries(user_id, development_id, dev_name, sim_day, sim_date,
                        cursor, conn):
    """
    Deliver POs that are due today. Add materials to inventory and
    create inventory_receipt BusinessEvent for each delivery.

    Returns: list of delivered PO dicts.
    """
    cursor.execute("""
        SELECT po.* FROM sim_purchase_orders po
        WHERE po.development_id = ? AND po.status = 'ordered'
        AND po.delivery_day <= ?
    """, (development_id, sim_day))
    due_pos = [_row_to_dict(r) for r in cursor.fetchall()]

    delivered = []
    for po in due_pos:
        # Get PO lines
        cursor.execute("""
            SELECT pl.*, m.name as material_name, m.unit
            FROM sim_po_lines pl
            JOIN sim_materials m ON pl.material_id = m.material_id
            WHERE pl.po_id = ?
        """, (po['po_id'],))
        lines = [_row_to_dict(r) for r in cursor.fetchall()]

        if not lines:
            continue

        # Add to inventory
        items_for_event = []
        for line in lines:
            cursor.execute("""
                UPDATE sim_inventory
                SET quantity_on_hand = quantity_on_hand + ?,
                    quantity_on_order = MAX(0, quantity_on_order - ?)
                WHERE development_id = ? AND material_id = ?
            """, (line['quantity'], line['quantity'],
                  development_id, line['material_id']))
            items_for_event.append({
                'material': line['material_name'],
                'quantity': line['quantity'],
                'unit_cost': line['unit_cost'],
            })

        # Create inventory_receipt BusinessEvent
        event_result = create_business_event(
            user_id=user_id,
            event_type='inventory_receipt',
            event_date=sim_date,
            metadata={
                'vendor': po['vendor_name'] or 'Unknown',
                'items': items_for_event,
                'po_id': po['po_id'],
                'account_prefix': dev_name,
            },
            entity_type='sim_purchase_order',
            entity_id=po['po_id'],
            source='auto',
            auto_post=True,
            conn=conn,
        )

        # Update PO status
        cursor.execute("""
            UPDATE sim_purchase_orders
            SET status = 'delivered', event_id = ?,
                payment_due_day = ?
            WHERE po_id = ?
        """, (event_result['event_id'], sim_day + NET_PAYMENT_DAYS, po['po_id']))

        delivered.append(po)

    return delivered


def _check_material_readiness(development_id, cursor):
    """
    For each ready phase with materials_ready=0, check if inventory
    has enough of each required material. If so, set materials_ready=1.
    """
    # Get phases waiting for materials
    cursor.execute("""
        SELECT lp.lot_phase_id, lp.template_id
        FROM sim_lot_phases lp
        JOIN sim_lots l ON lp.lot_id = l.lot_id
        WHERE l.development_id = ? AND lp.status = 'ready'
        AND lp.materials_ready = 0
    """, (development_id,))
    waiting = cursor.fetchall()

    for phase in waiting:
        phase = _row_to_dict(phase)
        # Get required materials for this phase template
        cursor.execute("""
            SELECT pm.material_id, pm.quantity,
                   COALESCE(inv.quantity_on_hand, 0) as on_hand
            FROM sim_phase_materials pm
            LEFT JOIN sim_inventory inv
                ON pm.material_id = inv.material_id
                AND inv.development_id = ?
            WHERE pm.template_id = ?
        """, (development_id, phase['template_id']))
        requirements = cursor.fetchall()

        all_available = True
        for req in requirements:
            if req['on_hand'] < req['quantity']:
                all_available = False
                break

        if all_available:
            cursor.execute("""
                UPDATE sim_lot_phases SET materials_ready = 1
                WHERE lot_phase_id = ?
            """, (phase['lot_phase_id'],))


def _auto_create_pos(development_id, sim_day, cursor):
    """
    For ready phases that need materials (materials_ready=0), create
    purchase orders with appropriate lead times.

    Groups orders by vendor to reduce PO count.

    Returns: number of POs created.
    """
    # Find phases that are ready but waiting on materials, and haven't
    # had a PO created yet (check via lot_phase_id in po_lines)
    cursor.execute("""
        SELECT DISTINCT lp.lot_phase_id, lp.template_id, l.label
        FROM sim_lot_phases lp
        JOIN sim_lots l ON lp.lot_id = l.lot_id
        WHERE l.development_id = ? AND lp.status = 'ready'
        AND lp.materials_ready = 0
        AND lp.lot_phase_id NOT IN (
            SELECT DISTINCT pl.lot_phase_id FROM sim_po_lines pl
            WHERE pl.lot_phase_id IS NOT NULL
        )
    """, (development_id,))
    phases_needing = [_row_to_dict(r) for r in cursor.fetchall()]

    if not phases_needing:
        return 0

    # Gather all material needs, grouped by vendor
    # vendor_name -> {material_id -> {qty, unit_cost, lot_phase_ids, lead_time}}
    vendor_orders = {}
    for phase in phases_needing:
        cursor.execute("""
            SELECT pm.material_id, pm.quantity, m.unit_cost,
                   m.vendor_name, m.lead_time_days
            FROM sim_phase_materials pm
            JOIN sim_materials m ON pm.material_id = m.material_id
            WHERE pm.template_id = ?
        """, (phase['template_id'],))

        for req in cursor.fetchall():
            req = _row_to_dict(req)
            vendor = req['vendor_name'] or 'Unknown'
            if vendor not in vendor_orders:
                vendor_orders[vendor] = {}
            mat_id = req['material_id']
            if mat_id not in vendor_orders[vendor]:
                vendor_orders[vendor][mat_id] = {
                    'quantity': 0,
                    'unit_cost': req['unit_cost'],
                    'lead_time': req['lead_time_days'],
                    'lot_phase_ids': [],
                }
            vendor_orders[vendor][mat_id]['quantity'] += req['quantity']
            vendor_orders[vendor][mat_id]['lot_phase_ids'].append(
                phase['lot_phase_id']
            )

    # Create POs grouped by vendor
    pos_created = 0
    for vendor, materials in vendor_orders.items():
        max_lead_time = max(m['lead_time'] for m in materials.values())
        delivery_day = sim_day + max_lead_time
        total_cost = sum(
            m['quantity'] * m['unit_cost'] for m in materials.values()
        )

        cursor.execute("""
            INSERT INTO sim_purchase_orders
                (development_id, vendor_name, order_day, delivery_day,
                 status, total_cost)
            VALUES (?, ?, ?, ?, 'ordered', ?)
        """, (development_id, vendor, sim_day, delivery_day, total_cost))
        po_id = cursor.lastrowid

        # Update on-order quantities and create PO lines
        for mat_id, info in materials.items():
            cursor.execute("""
                UPDATE sim_inventory
                SET quantity_on_order = quantity_on_order + ?
                WHERE development_id = ? AND material_id = ?
            """, (info['quantity'], development_id, mat_id))

            # Create one PO line per lot_phase that needs this material
            qty_per = info['quantity'] / len(info['lot_phase_ids'])
            for lp_id in info['lot_phase_ids']:
                cursor.execute("""
                    INSERT INTO sim_po_lines
                        (po_id, material_id, lot_phase_id, quantity,
                         unit_cost, line_total)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (po_id, mat_id, lp_id, qty_per,
                      info['unit_cost'], qty_per * info['unit_cost']))

        pos_created += 1

    return pos_created


def _consume_materials(user_id, development_id, dev_name, sim_day, sim_date,
                       crew_logs, cursor, conn):
    """
    For each phase that had work done today, consume a proportional
    amount of materials from inventory. Creates material_use BusinessEvents.

    Consumption is proportional: if a crew worked 8 of 40 total hours,
    consume 8/40 of total material requirements.

    Returns: total material cost consumed.
    """
    total_material_cost = 0.0

    # Group crew logs by lot_phase_id to avoid double-consuming
    phases_worked = {}
    for log in crew_logs:
        # We need the lot_phase_id — it's in the event metadata
        # but we can look it up from the daily log we just created
        pass

    # Instead, look at all phases that had work today
    cursor.execute("""
        SELECT dl.lot_phase_id, SUM(dl.hours_worked) as hours_today,
               lp.hours_needed, lp.template_id, lp.phase_name,
               l.label as lot_label
        FROM sim_daily_log dl
        JOIN sim_lot_phases lp ON dl.lot_phase_id = lp.lot_phase_id
        JOIN sim_lots l ON lp.lot_id = l.lot_id
        WHERE dl.development_id = ? AND dl.sim_day = ?
        GROUP BY dl.lot_phase_id
    """, (development_id, sim_day))
    worked_phases = [_row_to_dict(r) for r in cursor.fetchall()]

    for wp in worked_phases:
        # Get material requirements for this phase template
        cursor.execute("""
            SELECT pm.material_id, pm.quantity as total_qty,
                   m.name as material_name, m.unit_cost
            FROM sim_phase_materials pm
            JOIN sim_materials m ON pm.material_id = m.material_id
            WHERE pm.template_id = ?
        """, (wp['template_id'],))
        requirements = cursor.fetchall()

        if not requirements:
            continue  # No materials for this phase (e.g., Site Prep)

        # Proportional consumption: hours_today / hours_needed * total_qty
        ratio = wp['hours_today'] / wp['hours_needed'] if wp['hours_needed'] > 0 else 0
        items_for_event = []
        phase_cost = 0.0

        for req in requirements:
            req = _row_to_dict(req)
            consume_qty = round(req['total_qty'] * ratio, 2)
            if consume_qty <= 0:
                continue

            line_cost = round(consume_qty * req['unit_cost'], 2)
            phase_cost += line_cost

            # Deduct from inventory
            cursor.execute("""
                UPDATE sim_inventory
                SET quantity_on_hand = MAX(0, quantity_on_hand - ?)
                WHERE development_id = ? AND material_id = ?
            """, (consume_qty, development_id, req['material_id']))

            items_for_event.append({
                'material': req['material_name'],
                'quantity': consume_qty,
                'unit_cost': req['unit_cost'],
            })

        if items_for_event and phase_cost > 0:
            create_business_event(
                user_id=user_id,
                event_type='material_use',
                event_date=sim_date,
                metadata={
                    'items': items_for_event,
                    'lot_label': wp['lot_label'],
                    'phase_name': wp['phase_name'],
                    'lot_phase_id': wp['lot_phase_id'],
                    'sim_day': sim_day,
                    'account_prefix': dev_name,
                },
                entity_type='sim_lot_phase',
                entity_id=wp['lot_phase_id'],
                source='auto',
                auto_post=True,
                conn=conn,
            )
            total_material_cost += phase_cost

    return round(total_material_cost, 2)


def _process_vendor_payments(user_id, development_id, dev_name, sim_day,
                             sim_date, cursor, conn):
    """
    Pay delivered POs whose payment is due (delivery + NET_PAYMENT_DAYS).
    Creates vendor_payment BusinessEvent for each.

    Returns: list of paid PO dicts.
    """
    cursor.execute("""
        SELECT po.* FROM sim_purchase_orders po
        WHERE po.development_id = ? AND po.status = 'delivered'
        AND po.payment_due_day <= ?
    """, (development_id, sim_day))
    due_pos = [_row_to_dict(r) for r in cursor.fetchall()]

    paid = []
    for po in due_pos:
        if po['total_cost'] <= 0:
            continue

        event_result = create_business_event(
            user_id=user_id,
            event_type='vendor_payment',
            event_date=sim_date,
            metadata={
                'vendor': po['vendor_name'] or 'Unknown',
                'amount': po['total_cost'],
                'po_reference': po['po_id'],
                'account_prefix': dev_name,
            },
            entity_type='sim_purchase_order',
            entity_id=po['po_id'],
            source='auto',
            auto_post=True,
            conn=conn,
        )

        cursor.execute("""
            UPDATE sim_purchase_orders
            SET status = 'paid', payment_event_id = ?
            WHERE po_id = ?
        """, (event_result['event_id'], po['po_id']))

        paid.append(po)

    return paid


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
