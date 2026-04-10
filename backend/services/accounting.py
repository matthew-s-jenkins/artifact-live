"""
Artifact Live v2 - Accounting Service

The single entry point for all financial operations. Every business event
(purchase, sale, acquisition, adjustment) flows through this module to
generate balanced double-entry journal entries.

Other routes should import from here rather than writing ledger entries directly.

Usage:
    from services.accounting import create_business_event, post_event, void_event

Author: Matthew Jenkins
Date: 2026-04-10
"""

import uuid
import json
import sqlite3
from datetime import datetime
from pathlib import Path


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
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


# =============================================================================
# BALANCE TOLERANCE
# Using REAL for money (matching existing schema). Epsilon tolerance for
# balance validation until the Decimal upgrade.
# =============================================================================

BALANCE_TOLERANCE = 0.005


# =============================================================================
# EVENT TYPE REGISTRY
#
# Each event type defines:
#   description     — human-readable label
#   required_meta   — metadata keys that must be present
#   optional_meta   — metadata keys that are accepted but not required
#   builder         — name of the internal _build_*_entries function
# =============================================================================

EVENT_TYPES = {
    'inventory_purchase': {
        'description': 'Purchase of inventory (parts, systems)',
        'required_meta': ['vendor', 'items'],
        'optional_meta': ['invoice_number', 'payment_method'],
        'builder': '_build_purchase_entries',
    },
    'inventory_sale': {
        'description': 'Sale of inventory (parts, builds)',
        'required_meta': ['items'],
        'optional_meta': ['buyer', 'platform', 'fees', 'shipping_cost', 'listing_url'],
        'builder': '_build_sale_entries',
    },
    'project_acquisition': {
        'description': 'Acquisition of a project/system for flipping',
        'required_meta': ['project_id', 'cost'],
        'optional_meta': ['source', 'payment_method'],
        'builder': '_build_acquisition_entries',
    },
    'adjustment': {
        'description': 'Manual accounting adjustment',
        'required_meta': ['entries'],
        'optional_meta': ['reason'],
        'builder': '_build_manual_entries',
    },
    'labor': {
        'description': 'Labor hours on a construction phase',
        'required_meta': ['crew_name', 'hours', 'hourly_rate', 'lot_label', 'phase_name'],
        'optional_meta': ['crew_id', 'lot_phase_id', 'sim_day'],
        'builder': '_build_labor_entries',
    },
    'material_use': {
        'description': 'Materials consumed on a construction phase',
        'required_meta': ['items', 'lot_label', 'phase_name'],
        'optional_meta': ['lot_phase_id', 'sim_day'],
        'builder': '_build_material_use_entries',
    },
    'vendor_payment': {
        'description': 'Payment to a vendor (AP reduction)',
        'required_meta': ['vendor', 'amount'],
        'optional_meta': ['invoice_number', 'po_reference'],
        'builder': '_build_vendor_payment_entries',
    },
}


# =============================================================================
# PUBLIC API
# =============================================================================

def create_business_event(user_id, event_type, event_date, metadata,
                          entity_type=None, entity_id=None,
                          parent_event_id=None, source='manual',
                          notes=None, auto_post=False, conn=None):
    """
    Create a business event with its transaction and balanced ledger entries.

    Parameters:
        user_id:         int — owner
        event_type:      str — key in EVENT_TYPES
        event_date:      str — YYYY-MM-DD
        metadata:        dict — type-specific data
        entity_type:     str|None — 'project', 'part', 'part_set'
        entity_id:       int|None — FK to relevant entity
        parent_event_id: str|None — UUID of parent event (for composition)
        source:          str — 'manual', 'auto', 'import'
        notes:           str|None
        auto_post:       bool — if True, immediately post the event
        conn:            sqlite3.Connection|None — pass for atomic operations

    Returns:
        dict with event_id, transaction_uuid, status, entries[]

    Raises:
        ValueError for validation failures
    """
    # Validate event type
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"Unknown event_type '{event_type}'. "
            f"Valid types: {', '.join(EVENT_TYPES.keys())}"
        )

    type_def = EVENT_TYPES[event_type]

    # Validate required metadata
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a dict")
    missing = [k for k in type_def['required_meta'] if k not in metadata]
    if missing:
        raise ValueError(
            f"Missing required metadata for {event_type}: {', '.join(missing)}"
        )

    # Validate event_date format
    try:
        datetime.strptime(event_date, '%Y-%m-%d')
    except ValueError:
        raise ValueError("event_date must be YYYY-MM-DD format")

    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()
        event_id = str(uuid.uuid4())
        txn_uuid = str(uuid.uuid4())

        # 1. Create business_events row
        cursor.execute("""
            INSERT INTO business_events
                (event_id, user_id, event_type, parent_event_id,
                 entity_type, entity_id, event_date, status, source,
                 metadata, notes, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
        """, (event_id, user_id, event_type, parent_event_id,
              entity_type, entity_id, event_date, source,
              json.dumps(metadata), notes, user_id))

        # 2. Create transactions row
        description = _build_description(event_type, metadata)
        cursor.execute("""
            INSERT INTO transactions
                (transaction_uuid, event_id, user_id, transaction_date,
                 description, is_posted)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (txn_uuid, event_id, user_id, event_date, description))

        transaction_id = cursor.lastrowid

        # 3. Build and insert ledger entries using the type-specific builder
        builder_name = type_def['builder']
        builder_fn = _BUILDERS[builder_name]
        entries = builder_fn(user_id, metadata, cursor)

        for entry in entries:
            cursor.execute("""
                INSERT INTO financial_ledger
                    (user_id, account_id, transaction_uuid, transaction_id,
                     transaction_date, description, debit, credit,
                     reference_type, reference_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, entry['account_id'], txn_uuid, transaction_id,
                  event_date, entry.get('description', description),
                  entry.get('debit', 0.0), entry.get('credit', 0.0),
                  entry.get('reference_type'), entry.get('reference_id')))

        # 4. Validate balance
        is_balanced, total_dr, total_cr = _check_balance(transaction_id, cursor)
        if not is_balanced:
            raise ValueError(
                f"Imbalanced transaction: DR {total_dr:.2f} != CR {total_cr:.2f} "
                f"(diff: {abs(total_dr - total_cr):.2f})"
            )

        # 5. Auto-post if requested
        status = 'draft'
        if auto_post:
            cursor.execute(
                "UPDATE business_events SET status = 'posted', updated_at = CURRENT_TIMESTAMP WHERE event_id = ?",
                (event_id,)
            )
            cursor.execute(
                "UPDATE transactions SET is_posted = 1 WHERE transaction_id = ?",
                (transaction_id,)
            )
            status = 'posted'

        if owns_conn:
            conn.commit()

        return {
            'event_id': event_id,
            'event_type': event_type,
            'transaction_uuid': txn_uuid,
            'transaction_id': transaction_id,
            'status': status,
            'event_date': event_date,
            'description': description,
            'total_debit': total_dr,
            'total_credit': total_cr,
            'entry_count': len(entries),
        }

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def post_event(user_id, event_id, conn=None):
    """
    Transition event from 'draft' or 'pending' to 'posted'.
    Validates balance before posting.

    Returns: updated event dict
    Raises: ValueError if validation fails
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Fetch event
        cursor.execute(
            "SELECT * FROM business_events WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        event = cursor.fetchone()
        if not event:
            raise ValueError(f"Event {event_id} not found")

        if event['status'] not in ('draft', 'pending'):
            raise ValueError(
                f"Cannot post event in '{event['status']}' status. "
                f"Must be 'draft' or 'pending'."
            )

        # Get transaction and validate balance
        cursor.execute(
            "SELECT transaction_id FROM transactions WHERE event_id = ?",
            (event_id,)
        )
        txn = cursor.fetchone()
        if not txn:
            raise ValueError(f"No transaction found for event {event_id}")

        is_balanced, total_dr, total_cr = _check_balance(txn['transaction_id'], cursor)
        if not is_balanced:
            raise ValueError(
                f"Cannot post: imbalanced (DR {total_dr:.2f} != CR {total_cr:.2f})"
            )

        # Post
        cursor.execute("""
            UPDATE business_events
            SET status = 'posted', updated_at = CURRENT_TIMESTAMP
            WHERE event_id = ?
        """, (event_id,))

        cursor.execute("""
            UPDATE transactions SET is_posted = 1
            WHERE event_id = ?
        """, (event_id,))

        if owns_conn:
            conn.commit()

        return get_event(user_id, event_id, conn=conn)

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def void_event(user_id, event_id, reason=None, conn=None):
    """
    Void a posted event by creating reversal entries.

    Does NOT delete or modify existing ledger entries (immutable ledger).
    Creates a new reversal event with mirror entries.

    Returns: dict with original_event_id, reversal_event_id, reversal_transaction_uuid
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Fetch original event
        cursor.execute(
            "SELECT * FROM business_events WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        event = cursor.fetchone()
        if not event:
            raise ValueError(f"Event {event_id} not found")

        if event['status'] != 'posted':
            raise ValueError(
                f"Can only void 'posted' events. Current status: '{event['status']}'"
            )

        # Fetch original transaction + entries
        cursor.execute(
            "SELECT * FROM transactions WHERE event_id = ?",
            (event_id,)
        )
        orig_txn = cursor.fetchone()

        cursor.execute(
            "SELECT * FROM financial_ledger WHERE transaction_id = ?",
            (orig_txn['transaction_id'],)
        )
        orig_entries = cursor.fetchall()

        # Create reversal event
        reversal_event_id = str(uuid.uuid4())
        reversal_uuid = str(uuid.uuid4())
        reversal_desc = f"REVERSAL of {orig_txn['description']}"
        if reason:
            reversal_desc += f" — {reason}"

        cursor.execute("""
            INSERT INTO business_events
                (event_id, user_id, event_type, parent_event_id,
                 entity_type, entity_id, event_date, status, source,
                 metadata, notes, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'posted', 'system', ?, ?, ?)
        """, (reversal_event_id, user_id,
              event['event_type'] + '_reversal', event_id,
              event['entity_type'], event['entity_id'],
              datetime.now().strftime('%Y-%m-%d'),
              json.dumps({'reversal_of': event_id, 'reason': reason}),
              reason, user_id))

        # Create reversal transaction
        cursor.execute("""
            INSERT INTO transactions
                (transaction_uuid, event_id, user_id, transaction_date,
                 description, is_posted, is_reversal, reversal_of)
            VALUES (?, ?, ?, ?, ?, 1, 1, ?)
        """, (reversal_uuid, reversal_event_id, user_id,
              datetime.now().strftime('%Y-%m-%d'),
              reversal_desc, orig_txn['transaction_uuid']))

        reversal_txn_id = cursor.lastrowid

        # Create mirror ledger entries (swap debit/credit)
        for entry in orig_entries:
            cursor.execute("""
                INSERT INTO financial_ledger
                    (user_id, account_id, transaction_uuid, transaction_id,
                     transaction_date, description, debit, credit,
                     reference_type, reference_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, entry['account_id'], reversal_uuid, reversal_txn_id,
                  datetime.now().strftime('%Y-%m-%d'),
                  f"REVERSAL: {entry['description'] or ''}",
                  entry['credit'], entry['debit'],  # Swapped
                  entry['reference_type'], entry['reference_id']))

        # Mark original as void
        cursor.execute("""
            UPDATE business_events
            SET status = 'void', updated_at = CURRENT_TIMESTAMP
            WHERE event_id = ?
        """, (event_id,))

        if owns_conn:
            conn.commit()

        return {
            'original_event_id': event_id,
            'reversal_event_id': reversal_event_id,
            'reversal_transaction_uuid': reversal_uuid,
        }

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def reconcile_event(user_id, event_id, conn=None):
    """
    Mark a posted event as reconciled (confirmed accurate by account owner).

    Returns: updated event dict
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM business_events WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        event = cursor.fetchone()
        if not event:
            raise ValueError(f"Event {event_id} not found")

        if event['status'] != 'posted':
            raise ValueError(
                f"Can only reconcile 'posted' events. Current status: '{event['status']}'"
            )

        cursor.execute("""
            UPDATE business_events
            SET status = 'reconciled', updated_at = CURRENT_TIMESTAMP
            WHERE event_id = ?
        """, (event_id,))

        if owns_conn:
            conn.commit()

        return get_event(user_id, event_id, conn=conn)

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def validate_balance(transaction_id, conn=None):
    """
    Check that sum(debit) == sum(credit) for a transaction.

    Returns: (is_balanced: bool, total_debit: float, total_credit: float)
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()
        return _check_balance(transaction_id, cursor)
    finally:
        if owns_conn:
            conn.close()


def get_event(user_id, event_id, include_entries=True, conn=None):
    """
    Fetch a single business event with optional transaction and ledger entries.

    Returns: dict with event fields, transaction, and entries list
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM business_events WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        event = cursor.fetchone()
        if not event:
            return None

        result = _row_to_dict(event)
        # Parse metadata JSON
        if result.get('metadata'):
            try:
                result['metadata'] = json.loads(result['metadata'])
            except (json.JSONDecodeError, TypeError):
                pass

        if include_entries:
            cursor.execute("""
                SELECT t.*,
                    (SELECT COUNT(*) FROM financial_ledger fl
                     WHERE fl.transaction_id = t.transaction_id) as entry_count
                FROM transactions t
                WHERE t.event_id = ?
            """, (event_id,))
            txn = cursor.fetchone()

            if txn:
                result['transaction'] = _row_to_dict(txn)

                cursor.execute("""
                    SELECT fl.*, a.account_name, a.account_type, a.subtype, a.normal_balance
                    FROM financial_ledger fl
                    JOIN accounts a ON fl.account_id = a.account_id
                    WHERE fl.transaction_id = ?
                    ORDER BY fl.entry_id
                """, (txn['transaction_id'],))
                result['entries'] = [_row_to_dict(r) for r in cursor.fetchall()]
            else:
                result['transaction'] = None
                result['entries'] = []

        return result

    finally:
        if owns_conn:
            conn.close()


def list_events(user_id, event_type=None, status=None, entity_type=None,
                entity_id=None, parent_event_id=None,
                date_from=None, date_to=None,
                page=1, per_page=50, conn=None):
    """
    Query business events with filtering and pagination.

    Returns: dict with items[], total, page, per_page
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        where_clauses = ["be.user_id = ?"]
        params = [user_id]

        if event_type:
            where_clauses.append("be.event_type = ?")
            params.append(event_type)
        if status:
            where_clauses.append("be.status = ?")
            params.append(status)
        if entity_type:
            where_clauses.append("be.entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            where_clauses.append("be.entity_id = ?")
            params.append(entity_id)
        if parent_event_id:
            where_clauses.append("be.parent_event_id = ?")
            params.append(parent_event_id)
        if date_from:
            where_clauses.append("be.event_date >= ?")
            params.append(date_from)
        if date_to:
            where_clauses.append("be.event_date <= ?")
            params.append(date_to)

        where_sql = " AND ".join(where_clauses)

        # Count total
        cursor.execute(
            f"SELECT COUNT(*) as cnt FROM business_events be WHERE {where_sql}",
            params
        )
        total = cursor.fetchone()['cnt']

        # Fetch page
        offset = (page - 1) * per_page
        cursor.execute(f"""
            SELECT be.*,
                   t.transaction_uuid,
                   t.is_posted
            FROM business_events be
            LEFT JOIN transactions t ON t.event_id = be.event_id
            WHERE {where_sql}
            ORDER BY be.event_date DESC, be.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset])

        items = []
        for row in cursor.fetchall():
            item = _row_to_dict(row)
            if item.get('metadata'):
                try:
                    item['metadata'] = json.loads(item['metadata'])
                except (json.JSONDecodeError, TypeError):
                    pass
            items.append(item)

        return {
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
        }

    finally:
        if owns_conn:
            conn.close()


def get_account_balances(user_id, conn=None):
    """
    Fetch current account balances from the v_account_balances view.

    Returns: list of account balance dicts
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM v_account_balances WHERE user_id = ? ORDER BY account_type, account_name",
            (user_id,)
        )
        return [_row_to_dict(r) for r in cursor.fetchall()]
    finally:
        if owns_conn:
            conn.close()


def get_transaction_detail(user_id, transaction_uuid, conn=None):
    """
    Fetch a transaction by UUID with all its ledger entries.

    Returns: dict with transaction fields and entries[]
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT t.*, be.event_type, be.status as event_status
            FROM transactions t
            JOIN business_events be ON t.event_id = be.event_id
            WHERE t.transaction_uuid = ? AND t.user_id = ?
        """, (transaction_uuid, user_id))
        txn = cursor.fetchone()
        if not txn:
            return None

        result = _row_to_dict(txn)

        cursor.execute("""
            SELECT fl.*, a.account_name, a.account_type, a.subtype, a.normal_balance
            FROM financial_ledger fl
            JOIN accounts a ON fl.account_id = a.account_id
            WHERE fl.transaction_id = ?
            ORDER BY fl.entry_id
        """, (txn['transaction_id'],))
        result['entries'] = [_row_to_dict(r) for r in cursor.fetchall()]

        return result

    finally:
        if owns_conn:
            conn.close()


# =============================================================================
# INTERNAL: Balance check
# =============================================================================

def _check_balance(transaction_id, cursor):
    """
    Check DR == CR for a transaction. Uses epsilon tolerance for REAL arithmetic.

    Returns: (is_balanced, total_debit, total_credit)
    """
    cursor.execute("""
        SELECT COALESCE(SUM(debit), 0) as total_dr,
               COALESCE(SUM(credit), 0) as total_cr
        FROM financial_ledger
        WHERE transaction_id = ?
    """, (transaction_id,))
    row = cursor.fetchone()
    total_dr = row['total_dr']
    total_cr = row['total_cr']
    is_balanced = abs(total_dr - total_cr) < BALANCE_TOLERANCE
    return (is_balanced, total_dr, total_cr)


# =============================================================================
# INTERNAL: Description builder
# =============================================================================

def _build_description(event_type, metadata):
    """Build a human-readable transaction description from event type + metadata."""
    if event_type == 'inventory_purchase':
        vendor = metadata.get('vendor', 'Unknown vendor')
        item_count = len(metadata.get('items', []))
        return f"Purchase from {vendor} ({item_count} item{'s' if item_count != 1 else ''})"

    elif event_type == 'inventory_sale':
        platform = metadata.get('platform', '')
        buyer = metadata.get('buyer', '')
        item_count = len(metadata.get('items', []))
        parts = [p for p in [platform, buyer] if p]
        target = ' — '.join(parts) if parts else 'direct'
        return f"Sale via {target} ({item_count} item{'s' if item_count != 1 else ''})"

    elif event_type == 'project_acquisition':
        source = metadata.get('source', 'unknown source')
        return f"Project acquisition from {source}"

    elif event_type == 'adjustment':
        reason = metadata.get('reason', 'Manual adjustment')
        return reason

    elif event_type == 'labor':
        crew = metadata.get('crew_name', 'crew')
        hours = metadata.get('hours', 0)
        lot = metadata.get('lot_label', '')
        phase = metadata.get('phase_name', '')
        return f"Labor: {crew} — {hours}h on {lot} ({phase})"

    elif event_type == 'material_use':
        lot = metadata.get('lot_label', '')
        phase = metadata.get('phase_name', '')
        item_count = len(metadata.get('items', []))
        return f"Materials consumed — {lot} ({phase}), {item_count} item{'s' if item_count != 1 else ''}"

    elif event_type == 'vendor_payment':
        vendor = metadata.get('vendor', 'Unknown vendor')
        amount = metadata.get('amount', 0)
        return f"Payment to {vendor} — ${amount:,.2f}"

    return f"{event_type} event"


# =============================================================================
# INTERNAL: Account resolver
# =============================================================================

def _resolve_account(user_id, subtype, cursor, name_prefix=None):
    """
    Look up the user's account by subtype (e.g., 'INVENTORY', 'CASH', 'COGS').
    Optional name_prefix narrows to accounts whose name starts with that prefix
    (used by sim to isolate per-development accounts).

    Returns account_id.
    Raises ValueError if not found.
    """
    if name_prefix:
        cursor.execute(
            "SELECT account_id FROM accounts WHERE user_id = ? AND subtype = ? "
            "AND is_active = 1 AND is_deleted = 0 AND account_name LIKE ?",
            (user_id, subtype, f"{name_prefix}%")
        )
    else:
        cursor.execute(
            "SELECT account_id FROM accounts WHERE user_id = ? AND subtype = ? AND is_active = 1 AND is_deleted = 0",
            (user_id, subtype)
        )
    row = cursor.fetchone()
    if not row:
        raise ValueError(
            f"No active account found with subtype '{subtype}'"
            f"{f' and prefix {name_prefix!r}' if name_prefix else ''}"
            f" for user {user_id}. Check chart of accounts setup."
        )
    return row['account_id']


# =============================================================================
# INTERNAL: Entry builders (one per event type)
# =============================================================================

def _build_purchase_entries(user_id, metadata, cursor):
    """
    Build ledger entries for an inventory purchase.

    DR Inventory Asset (total cost)
    CR Cash (total cost)

    Also creates inventory_layers for FIFO tracking.
    """
    items = metadata['items']
    if not items:
        raise ValueError("inventory_purchase requires at least one item")

    inventory_account = _resolve_account(user_id, 'INVENTORY', cursor)
    cash_account = _resolve_account(user_id, 'CASH', cursor)

    total_cost = 0.0
    for item in items:
        qty = item.get('quantity', 1)
        unit_cost = item.get('unit_cost', 0)
        line_cost = qty * unit_cost
        total_cost += line_cost

        # Create FIFO inventory layer
        part_id = item.get('part_id')
        if part_id:
            cursor.execute("""
                INSERT INTO inventory_layers
                    (user_id, part_id, quantity_received, quantity_remaining,
                     unit_cost, received_date, reference_type, reference_id)
                VALUES (?, ?, ?, ?, ?, date('now'), 'PURCHASE', ?)
            """, (user_id, part_id, qty, qty, unit_cost, part_id))

    if total_cost <= 0:
        raise ValueError("Purchase total must be greater than zero")

    return [
        {
            'account_id': inventory_account,
            'debit': total_cost,
            'credit': 0.0,
            'description': f"Inventory purchase — {metadata.get('vendor', '')}",
            'reference_type': 'PURCHASE',
        },
        {
            'account_id': cash_account,
            'debit': 0.0,
            'credit': total_cost,
            'description': f"Cash out — purchase from {metadata.get('vendor', '')}",
            'reference_type': 'PURCHASE',
        },
    ]


def _build_sale_entries(user_id, metadata, cursor):
    """
    Build ledger entries for an inventory sale.

    DR Cash (sale price)
    CR Sales Revenue (sale price)

    DR Cost of Goods Sold (FIFO cost from inventory_layers)
    CR Inventory Asset (FIFO cost)

    DR eBay Fees / Shipping Expense (if applicable)
    CR Cash (fees + shipping)
    """
    items = metadata['items']
    if not items:
        raise ValueError("inventory_sale requires at least one item")

    cash_account = _resolve_account(user_id, 'CASH', cursor)
    revenue_account = _resolve_account(user_id, 'SALES', cursor)
    cogs_account = _resolve_account(user_id, 'COGS', cursor)
    inventory_account = _resolve_account(user_id, 'INVENTORY', cursor)

    total_revenue = 0.0
    total_cogs = 0.0

    for item in items:
        qty = item.get('quantity', 1)
        sale_price = item.get('sale_price', 0)
        total_revenue += qty * sale_price

        # Deplete FIFO layers for cost basis
        part_id = item.get('part_id')
        if part_id:
            cogs_for_item = _deplete_fifo_layers(user_id, part_id, qty, cursor)
            total_cogs += cogs_for_item

    entries = []

    # Revenue side
    if total_revenue > 0:
        entries.append({
            'account_id': cash_account,
            'debit': total_revenue,
            'credit': 0.0,
            'description': 'Cash received — sale',
            'reference_type': 'SALE',
        })
        entries.append({
            'account_id': revenue_account,
            'debit': 0.0,
            'credit': total_revenue,
            'description': 'Sales revenue',
            'reference_type': 'SALE',
        })

    # COGS side
    if total_cogs > 0:
        entries.append({
            'account_id': cogs_account,
            'debit': total_cogs,
            'credit': 0.0,
            'description': 'Cost of goods sold (FIFO)',
            'reference_type': 'SALE',
        })
        entries.append({
            'account_id': inventory_account,
            'debit': 0.0,
            'credit': total_cogs,
            'description': 'Inventory reduction (FIFO)',
            'reference_type': 'SALE',
        })

    # Fees and shipping (reduce cash)
    fees = metadata.get('fees', 0) or 0
    shipping = metadata.get('shipping_cost', 0) or 0

    if fees > 0:
        fees_account = _resolve_account(user_id, 'FEES', cursor)
        entries.append({
            'account_id': fees_account,
            'debit': fees,
            'credit': 0.0,
            'description': f"Marketplace fees ({metadata.get('platform', '')})",
            'reference_type': 'SALE',
        })
        entries.append({
            'account_id': cash_account,
            'debit': 0.0,
            'credit': fees,
            'description': 'Cash out — fees',
            'reference_type': 'SALE',
        })

    if shipping > 0:
        shipping_account = _resolve_account(user_id, 'SHIPPING', cursor)
        entries.append({
            'account_id': shipping_account,
            'debit': shipping,
            'credit': 0.0,
            'description': 'Shipping expense',
            'reference_type': 'SALE',
        })
        entries.append({
            'account_id': cash_account,
            'debit': 0.0,
            'credit': shipping,
            'description': 'Cash out — shipping',
            'reference_type': 'SALE',
        })

    if not entries:
        raise ValueError("Sale must have revenue, COGS, or fee entries")

    return entries


def _build_acquisition_entries(user_id, metadata, cursor):
    """
    Build ledger entries for a project acquisition (buying a whole system).

    DR Inventory Asset (acquisition cost)
    CR Cash (acquisition cost)
    """
    cost = metadata.get('cost', 0)
    if not cost or cost <= 0:
        raise ValueError("project_acquisition requires a positive cost")

    inventory_account = _resolve_account(user_id, 'INVENTORY', cursor)
    cash_account = _resolve_account(user_id, 'CASH', cursor)

    source = metadata.get('source', 'unknown')

    return [
        {
            'account_id': inventory_account,
            'debit': cost,
            'credit': 0.0,
            'description': f"Project acquisition from {source}",
            'reference_type': 'PROJECT',
            'reference_id': metadata.get('project_id'),
        },
        {
            'account_id': cash_account,
            'debit': 0.0,
            'credit': cost,
            'description': f"Cash out — acquisition from {source}",
            'reference_type': 'PROJECT',
            'reference_id': metadata.get('project_id'),
        },
    ]


def _build_manual_entries(user_id, metadata, cursor):
    """
    Build ledger entries from user-provided debit/credit lines.
    The user supplies a list of {account_subtype, debit, credit} dicts.
    """
    raw_entries = metadata.get('entries', [])
    if not raw_entries:
        raise ValueError("adjustment requires at least one entry")

    entries = []
    for raw in raw_entries:
        subtype = raw.get('account_subtype')
        if not subtype:
            raise ValueError("Each entry must have an 'account_subtype'")

        account_id = _resolve_account(user_id, subtype, cursor)
        debit = raw.get('debit', 0) or 0
        credit = raw.get('credit', 0) or 0

        if debit == 0 and credit == 0:
            raise ValueError(f"Entry for {subtype} has no debit or credit")
        if debit > 0 and credit > 0:
            raise ValueError(f"Entry for {subtype} cannot have both debit and credit")

        entries.append({
            'account_id': account_id,
            'debit': float(debit),
            'credit': float(credit),
            'description': metadata.get('reason', 'Manual adjustment'),
            'reference_type': 'ADJUSTMENT',
        })

    return entries


# =============================================================================
# INTERNAL: FIFO layer depletion
# =============================================================================

def _deplete_fifo_layers(user_id, part_id, quantity, cursor):
    """
    Deplete inventory layers in FIFO order for a given part.

    Returns: total cost of depleted quantity (for COGS)
    Raises: ValueError if insufficient inventory
    """
    cursor.execute("""
        SELECT layer_id, quantity_remaining, unit_cost
        FROM inventory_layers
        WHERE user_id = ? AND part_id = ? AND quantity_remaining > 0
        ORDER BY received_date ASC, layer_id ASC
    """, (user_id, part_id))

    layers = cursor.fetchall()
    remaining_to_deplete = quantity
    total_cost = 0.0

    for layer in layers:
        if remaining_to_deplete <= 0:
            break

        available = layer['quantity_remaining']
        take = min(available, remaining_to_deplete)

        total_cost += take * layer['unit_cost']
        new_remaining = available - take

        cursor.execute(
            "UPDATE inventory_layers SET quantity_remaining = ? WHERE layer_id = ?",
            (new_remaining, layer['layer_id'])
        )
        remaining_to_deplete -= take

    if remaining_to_deplete > 0:
        raise ValueError(
            f"Insufficient inventory for part {part_id}: "
            f"needed {quantity}, available {quantity - remaining_to_deplete}"
        )

    return total_cost


# =============================================================================
# INTERNAL: Construction sim entry builders
# =============================================================================

def _build_labor_entries(user_id, metadata, cursor):
    """
    Build ledger entries for construction labor.

    DR Work-In-Progress (hours * rate)
    CR Cash (hours * rate)

    Labor accumulates in WIP while the house is under construction.
    When the house sells, WIP moves to COGS.
    """
    hours = metadata.get('hours', 0)
    hourly_rate = metadata.get('hourly_rate', 0)
    labor_cost = hours * hourly_rate

    if labor_cost <= 0:
        raise ValueError("Labor event requires positive hours and hourly_rate")

    prefix = metadata.get('account_prefix')
    wip_account = _resolve_account(user_id, 'WIP', cursor, name_prefix=prefix)
    cash_account = _resolve_account(user_id, 'CASH', cursor, name_prefix=prefix)

    crew = metadata.get('crew_name', 'crew')
    lot = metadata.get('lot_label', '')
    phase = metadata.get('phase_name', '')

    return [
        {
            'account_id': wip_account,
            'debit': labor_cost,
            'credit': 0.0,
            'description': f"WIP — {crew} labor on {lot} ({phase})",
            'reference_type': 'LABOR',
        },
        {
            'account_id': cash_account,
            'debit': 0.0,
            'credit': labor_cost,
            'description': f"Cash out — labor: {crew}",
            'reference_type': 'LABOR',
        },
    ]


def _build_material_use_entries(user_id, metadata, cursor):
    """
    Build ledger entries for materials consumed on a construction phase.

    DR Work-In-Progress (material cost)
    CR Inventory (material cost — FIFO depletion)

    Materials move from inventory to WIP as they're installed.
    """
    items = metadata.get('items', [])
    if not items:
        raise ValueError("material_use requires at least one item")

    prefix = metadata.get('account_prefix')
    wip_account = _resolve_account(user_id, 'WIP', cursor, name_prefix=prefix)
    inventory_account = _resolve_account(user_id, 'INVENTORY', cursor, name_prefix=prefix)

    total_cost = 0.0
    for item in items:
        qty = item.get('quantity', 1)
        unit_cost = item.get('unit_cost', 0)
        total_cost += qty * unit_cost

    if total_cost <= 0:
        raise ValueError("material_use total cost must be positive")

    lot = metadata.get('lot_label', '')
    phase = metadata.get('phase_name', '')

    return [
        {
            'account_id': wip_account,
            'debit': total_cost,
            'credit': 0.0,
            'description': f"WIP — materials on {lot} ({phase})",
            'reference_type': 'MATERIAL_USE',
        },
        {
            'account_id': inventory_account,
            'debit': 0.0,
            'credit': total_cost,
            'description': f"Inventory consumed — {lot} ({phase})",
            'reference_type': 'MATERIAL_USE',
        },
    ]


def _build_vendor_payment_entries(user_id, metadata, cursor):
    """
    Build ledger entries for a vendor payment.

    DR Accounts Payable (reduce liability)
    CR Cash (money out)
    """
    amount = metadata.get('amount', 0)
    if amount <= 0:
        raise ValueError("vendor_payment requires a positive amount")

    prefix = metadata.get('account_prefix')
    ap_account = _resolve_account(user_id, 'AP', cursor, name_prefix=prefix)
    cash_account = _resolve_account(user_id, 'CASH', cursor, name_prefix=prefix)

    vendor = metadata.get('vendor', 'Unknown')

    return [
        {
            'account_id': ap_account,
            'debit': amount,
            'credit': 0.0,
            'description': f"AP reduction — payment to {vendor}",
            'reference_type': 'VENDOR_PAYMENT',
        },
        {
            'account_id': cash_account,
            'debit': 0.0,
            'credit': amount,
            'description': f"Cash out — payment to {vendor}",
            'reference_type': 'VENDOR_PAYMENT',
        },
    ]


# =============================================================================
# Builder dispatch table
# =============================================================================

_BUILDERS = {
    '_build_purchase_entries': _build_purchase_entries,
    '_build_sale_entries': _build_sale_entries,
    '_build_acquisition_entries': _build_acquisition_entries,
    '_build_manual_entries': _build_manual_entries,
    '_build_labor_entries': _build_labor_entries,
    '_build_material_use_entries': _build_material_use_entries,
    '_build_vendor_payment_entries': _build_vendor_payment_entries,
}
