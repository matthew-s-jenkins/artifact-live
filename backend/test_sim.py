"""
Integration test: Construction Development Simulator

Creates a development, runs it to completion, validates:
1. All 10 houses complete all 5 phases
2. Every crew-day generates a balanced BusinessEvent
3. Trial balance is balanced (DR == CR)
4. Phase dependencies respected (no framing before foundation)
5. Cure days work (concrete curing delay)

Run: python3 test_sim.py
"""

import sys
import os

# Ensure we can import from the backend directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
import sqlite3

# Use a test database
TEST_DB = Path(__file__).parent / "database" / "test_sim.db"


def setup_test_db():
    """Create a fresh test database with schema + migrations."""
    if TEST_DB.exists():
        TEST_DB.unlink()

    conn = sqlite3.connect(str(TEST_DB))
    cursor = conn.cursor()

    # Run base schema
    schema_path = Path(__file__).parent / "database" / "schema.sql"
    with open(schema_path) as f:
        cursor.executescript(f.read())

    # Run migrations one by one, handling view dependencies.
    # Migration 005 drops/recreates project_parts, which breaks views.
    # We drop dependent views first, let migrations run, then 006 recreates
    # v_account_balances, and we recreate the others.
    migrations_dir = Path(__file__).parent / "database" / "migrations"
    for mig in sorted(migrations_dir.glob("*.sql")):
        # Drop views that reference project_parts before migration 005
        if '005_' in mig.name:
            cursor.executescript("""
                DROP VIEW IF EXISTS v_project_summary;
                DROP VIEW IF EXISTS v_loose_inventory;
            """)

        with open(mig) as f:
            cursor.executescript(f.read())

    # Recreate views that were dropped (006 already recreates v_account_balances)
    cursor.executescript("""
        CREATE VIEW IF NOT EXISTS v_project_summary AS
        SELECT
            p.project_id, p.user_id, p.name, p.acquisition_cost, p.status,
            COUNT(pp.part_id) AS total_parts,
            COUNT(CASE WHEN pp.status IN ('IN_SYSTEM', 'LISTED') THEN 1 END) AS parts_for_sale,
            COUNT(CASE WHEN pp.status = 'SOLD' THEN 1 END) AS parts_sold,
            COALESCE(SUM(pp.estimated_value), 0) AS total_estimated_value,
            COALESCE(SUM(pp.actual_sale_price), 0) AS total_actual_revenue,
            COALESCE(SUM(pp.fees_paid), 0) AS total_fees_paid,
            COALESCE(SUM(pp.shipping_paid), 0) AS total_shipping_paid
        FROM projects p
        LEFT JOIN project_parts pp ON p.project_id = pp.project_id
        GROUP BY p.project_id, p.user_id, p.name, p.acquisition_cost, p.status;

        CREATE VIEW IF NOT EXISTS v_loose_inventory AS
        SELECT
            pp.part_id, pp.subsection_id,
            s.name AS subsection_name,
            pp.catalog_id,
            pc.name AS catalog_name,
            pc.category AS catalog_category,
            pp.custom_name,
            COALESCE(pc.name, pp.custom_name) AS display_name,
            pp.condition, pp.weight_class, pp.estimated_value,
            pp.for_sale, pp.metadata, pp.status, pp.notes, pp.created_at
        FROM project_parts pp
        LEFT JOIN subsections s ON pp.subsection_id = s.subsection_id
        LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
        WHERE pp.project_id IS NULL;
    """)

    # Create a test user
    cursor.execute(
        "INSERT INTO users (email, password_hash) VALUES ('test@test.com', 'fakehash')"
    )

    conn.commit()
    conn.close()
    print(f"[OK] Test database created: {TEST_DB}")


def patch_db_path():
    """Monkey-patch the db path in both services to use our test DB."""
    import services.accounting as acct
    import services.construction_sim as sim

    def _test_conn():
        conn = sqlite3.connect(str(TEST_DB))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    acct.get_db_connection = _test_conn
    sim.get_db_connection = _test_conn


def run_test():
    """Run the full integration test."""
    from services.construction_sim import (
        create_development, start_development, advance_day,
        get_development_status, get_lot_detail, get_financial_summary,
    )
    from services.accounting import get_account_balances

    user_id = 1
    print()
    print("=" * 70)
    print("CONSTRUCTION SIM INTEGRATION TEST")
    print("=" * 70)

    # --- Create development ---
    print("\n1. Creating development (10 houses, $2M budget)...")
    dev = create_development(
        user_id=user_id,
        name='Oakwood Estates',
        num_houses=10,
        acreage=5.0,
        land_cost=200000,
        budget=2000000,
        start_date='2026-01-01',
    )
    dev_id = dev['development_id']
    print(f"   Development #{dev_id}: {dev['name']}")
    print(f"   Lots: {dev['total_lots']}, Crews: {dev['num_crews']}")
    print(f"   Total phases: {dev['total_phases']}")
    assert dev['total_lots'] == 10
    assert dev['total_phases'] == 50  # 10 houses * 5 phases

    # --- Start development ---
    print("\n2. Starting development...")
    start_development(user_id, dev_id)
    status = get_development_status(user_id, dev_id)
    assert status['status'] == 'running'
    print("   Status: running")

    # --- Run simulation to completion ---
    print("\n3. Running simulation day by day...")
    day_count = 0
    max_days = 500  # Safety limit
    phases_completed_total = 0
    lots_completed_total = 0

    while day_count < max_days:
        result = advance_day(user_id, dev_id)
        day_count += 1
        phases_completed_total += result['phases_completed']
        lots_completed_total += result['lots_completed']

        # Print milestones
        if result['lots_completed'] > 0:
            print(f"   Day {result['day']}: {result['lots_completed']} lot(s) completed! "
                  f"({result['lots_done']}/{result['lots_total']} total)")
        if result['development_complete']:
            print(f"\n   DEVELOPMENT COMPLETE on day {result['day']}!")
            break

        # Progress update every 25 days
        if day_count % 25 == 0:
            print(f"   Day {result['day']}: {result['lots_done']}/{result['lots_total']} lots done, "
                  f"{result['crews_working']} crews working")

    assert result['development_complete'], f"Development not complete after {max_days} days!"
    print(f"   Total simulation days: {day_count}")
    print(f"   Total phases completed: {phases_completed_total}")
    assert phases_completed_total == 50, f"Expected 50 phases, got {phases_completed_total}"

    # --- Verify lot details ---
    print("\n4. Verifying lot details...")
    conn = sqlite3.connect(str(TEST_DB))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sim_lots WHERE development_id = ? ORDER BY lot_number", (dev_id,))
    lots = cursor.fetchall()
    assert len(lots) == 10

    for lot in lots:
        assert lot['status'] == 'completed', f"Lot #{lot['lot_number']} is {lot['status']}"
        detail = get_lot_detail(user_id, dev_id, lot['lot_id'])
        assert detail['progress_pct'] == 100.0, f"Lot #{lot['lot_number']} at {detail['progress_pct']}%"

        # Check phase order (each phase started after its predecessor)
        phases = detail['phases']
        for i in range(1, len(phases)):
            prev = phases[i - 1]
            curr = phases[i]
            assert curr['started_day'] >= prev['completed_day'], \
                f"Lot #{lot['lot_number']}: {curr['phase_name']} started (day {curr['started_day']}) " \
                f"before {prev['phase_name']} completed (day {prev['completed_day']})"

    print("   All 10 lots completed with correct phase ordering")

    # --- Verify foundation cure days ---
    print("\n5. Verifying cure days (foundation → framing gap)...")
    cursor.execute("""
        SELECT l.lot_number,
               fp.completed_day as foundation_done,
               frp.started_day as framing_start
        FROM sim_lots l
        JOIN sim_lot_phases fp ON l.lot_id = fp.lot_id AND fp.phase_name = 'Foundation'
        JOIN sim_lot_phases frp ON l.lot_id = frp.lot_id AND frp.phase_name = 'Framing'
        WHERE l.development_id = ?
        ORDER BY l.lot_number
    """, (dev_id,))
    for row in cursor.fetchall():
        gap = row['framing_start'] - row['foundation_done']
        assert gap >= 3, \
            f"Lot #{row['lot_number']}: framing started {gap} days after foundation (need >= 3)"
    print("   All houses have >= 3-day cure gap between foundation and framing")

    # --- Verify BusinessEvents ---
    print("\n6. Verifying BusinessEvents...")
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM business_events WHERE user_id = ? AND event_type = 'labor'
    """, (user_id,))
    labor_events = cursor.fetchone()['cnt']
    print(f"   Labor events generated: {labor_events}")
    assert labor_events > 0, "No labor events generated!"

    # Check all labor events are posted
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM business_events
        WHERE user_id = ? AND event_type = 'labor' AND status != 'posted'
    """, (user_id,))
    unposted = cursor.fetchone()['cnt']
    assert unposted == 0, f"{unposted} labor events are not posted"
    print(f"   All {labor_events} labor events are posted")

    # --- Verify trial balance ---
    print("\n7. Verifying trial balance...")
    cursor.execute("""
        SELECT COALESCE(SUM(debit), 0) as total_dr,
               COALESCE(SUM(credit), 0) as total_cr
        FROM financial_ledger WHERE user_id = ?
    """, (user_id,))
    balance = cursor.fetchone()
    total_dr = balance['total_dr']
    total_cr = balance['total_cr']
    diff = abs(total_dr - total_cr)
    print(f"   Total DR: ${total_dr:,.2f}")
    print(f"   Total CR: ${total_cr:,.2f}")
    print(f"   Difference: ${diff:.4f}")
    assert diff < 0.01, f"TRIAL BALANCE IS OFF by ${diff:.2f}!"
    print("   TRIAL BALANCE: BALANCED")

    # --- Financial summary ---
    print("\n8. Financial summary...")
    financials = get_financial_summary(user_id, dev_id)
    print(f"   Budget: ${financials['budget']:,.2f}")
    print(f"   Total spent: ${financials['total_spent']:,.2f}")
    print(f"   Budget remaining: ${financials['budget_remaining']:,.2f}")
    print(f"   Budget used: {financials['budget_used_pct']}%")
    print(f"   Cost by phase:")
    for phase in financials['cost_by_phase']:
        print(f"     {phase['phase_name']}: ${phase['total_cost']:,.2f} "
              f"({phase['total_hours']:.0f}h, {phase['crew_days']} crew-days)")

    # --- Crew utilization ---
    print("\n9. Crew utilization...")
    status = get_development_status(user_id, dev_id)
    for crew in status['crews']:
        print(f"   {crew['name']} ({crew['crew_type']}): "
              f"{crew['days_worked']} days worked, "
              f"{crew['total_hours']:.0f}h, "
              f"{crew['utilization_pct']}% utilized")

    conn.close()

    print()
    print("=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)
    print(f"\nSummary:")
    print(f"  10 houses built in {day_count} days")
    print(f"  {labor_events} labor BusinessEvents generated")
    print(f"  Trial balance: BALANCED (${total_dr:,.2f})")
    print(f"  Phase dependencies: VERIFIED")
    print(f"  Cure days: VERIFIED")


def cleanup():
    """Remove test database."""
    if TEST_DB.exists():
        TEST_DB.unlink()
        print(f"\n[CLEANUP] Removed {TEST_DB}")


if __name__ == '__main__':
    try:
        setup_test_db()
        patch_db_path()
        run_test()
    except Exception as e:
        print(f"\n[FAIL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup()
