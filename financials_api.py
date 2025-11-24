"""
Artifact Live - Financials API
View ledger, accounting equation, and generate financial statements
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

financials_bp = Blueprint('financials', __name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

@financials_bp.route('/api/financials/accounting_equation', methods=['GET'])
@login_required
def get_accounting_equation():
    """Get the accounting equation: Assets = Liabilities + Equity"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Calculate total assets (DEBIT balance accounts)
        cursor.execute("""
            SELECT COALESCE(SUM(le.debit - le.credit), 0) as total_assets
            FROM ledger le
            JOIN accounts a ON le.account_id = a.account_id
            WHERE a.user_id = %s
                AND a.account_type = 'ASSET'
        """, (user_id,))

        assets = cursor.fetchone()['total_assets']

        # Calculate total liabilities (CREDIT balance accounts)
        cursor.execute("""
            SELECT COALESCE(SUM(le.credit - le.debit), 0) as total_liabilities
            FROM ledger le
            JOIN accounts a ON le.account_id = a.account_id
            WHERE a.user_id = %s
                AND a.account_type = 'LIABILITY'
        """, (user_id,))

        liabilities = cursor.fetchone()['total_liabilities']

        # Calculate total equity (CREDIT balance accounts)
        cursor.execute("""
            SELECT COALESCE(SUM(le.credit - le.debit), 0) as total_equity
            FROM ledger le
            JOIN accounts a ON le.account_id = a.account_id
            WHERE a.user_id = %s
                AND a.account_type = 'EQUITY'
        """, (user_id,))

        equity = cursor.fetchone()['total_equity']

        cursor.close()
        conn.close()

        # Calculate if balanced
        left_side = float(assets)
        right_side = float(liabilities) + float(equity)
        is_balanced = abs(left_side - right_side) < 0.01  # Allow for floating point rounding

        return jsonify({
            'assets': float(assets),
            'liabilities': float(liabilities),
            'equity': float(equity),
            'is_balanced': is_balanced,
            'difference': float(left_side - right_side)
        })

    except Error as e:
        return jsonify({'error': str(e)}), 500

@financials_bp.route('/api/financials/ledger', methods=['GET'])
@login_required
def get_ledger():
    """Get all ledger entries with account details"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get ledger entries
        cursor.execute("""
            SELECT
                le.entry_id,
                le.transaction_uuid,
                le.transaction_date as entry_date,
                le.debit,
                le.credit,
                le.description,
                le.reference_type,
                le.reference_id,
                a.account_id,
                a.account_name,
                a.account_type,
                a.subtype
            FROM ledger le
            JOIN accounts a ON le.account_id = a.account_id
            WHERE a.user_id = %s
            ORDER BY le.transaction_date DESC, le.entry_id DESC
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))

        entries = cursor.fetchall()

        # Convert datetime objects to strings
        for entry in entries:
            if entry['entry_date']:
                entry['entry_date'] = entry['entry_date'].isoformat()

        # Get total count
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM ledger le
            JOIN accounts a ON le.account_id = a.account_id
            WHERE a.user_id = %s
        """, (user_id,))

        total_count = cursor.fetchone()['total']

        cursor.close()
        conn.close()

        return jsonify({
            'entries': entries,
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })

    except Error as e:
        return jsonify({'error': str(e)}), 500

@financials_bp.route('/api/financials/trial_balance', methods=['GET'])
@login_required
def get_trial_balance():
    """Get trial balance - all accounts with their current balances"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get all accounts with their balances
        cursor.execute("""
            SELECT
                a.account_id,
                a.account_name,
                a.account_type,
                a.subtype,
                COALESCE(SUM(le.debit - le.credit), 0) as balance
            FROM accounts a
            LEFT JOIN ledger le ON a.account_id = le.account_id
            WHERE a.user_id = %s
                AND a.is_active = TRUE
            GROUP BY a.account_id, a.account_name, a.account_type, a.subtype
            HAVING ABS(balance) > 0.01
            ORDER BY
                FIELD(a.account_type, 'ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE'),
                a.account_name
        """, (user_id,))

        accounts = cursor.fetchall()

        # Separate debits and credits for trial balance
        total_debits = 0
        total_credits = 0

        for account in accounts:
            balance = float(account['balance'])
            # Normal balance sides: Assets/Expenses = DEBIT, Liabilities/Equity/Revenue = CREDIT
            # Balance is calculated as (debit - credit), so:
            # - Assets/Expenses will be positive (debit normal)
            # - Liabilities/Equity/Revenue will be negative (credit normal)
            if account['account_type'] in ['ASSET', 'EXPENSE']:
                # Debit normal accounts
                account['debit'] = balance if balance > 0 else 0
                account['credit'] = abs(balance) if balance < 0 else 0
                total_debits += account['debit']
                total_credits += account['credit']
            else:  # LIABILITY, EQUITY, REVENUE
                # Credit normal accounts - balance is negative, so negate it for credit column
                account['credit'] = abs(balance) if balance < 0 else 0
                account['debit'] = balance if balance > 0 else 0
                total_debits += account['debit']
                total_credits += account['credit']

        cursor.close()
        conn.close()

        is_balanced = abs(total_debits - total_credits) < 0.01

        return jsonify({
            'accounts': accounts,
            'total_debits': float(total_debits),
            'total_credits': float(total_credits),
            'is_balanced': is_balanced
        })

    except Error as e:
        return jsonify({'error': str(e)}), 500

@financials_bp.route('/api/financials/balance_sheet', methods=['GET'])
@login_required
def get_balance_sheet():
    """Generate Balance Sheet (Statement of Financial Position)"""
    user_id = current_user.id
    business_id = request.args.get('business_id', type=int)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get all asset accounts with balances
        cursor.execute("""
            SELECT
                a.account_name,
                a.subtype,
                COALESCE(SUM(le.debit - le.credit), 0) as balance
            FROM accounts a
            LEFT JOIN ledger le ON a.account_id = le.account_id
            WHERE a.user_id = %s
                AND a.account_type = 'ASSET'
            GROUP BY a.account_id, a.account_name, a.subtype
            HAVING ABS(balance) > 0.01
            ORDER BY a.account_name
        """, (user_id,))

        assets = cursor.fetchall()
        total_assets = sum(float(a['balance']) for a in assets)

        # Get all liability accounts
        cursor.execute("""
            SELECT
                a.account_name,
                a.subtype,
                COALESCE(SUM(le.credit - le.debit), 0) as balance
            FROM accounts a
            LEFT JOIN ledger le ON a.account_id = le.account_id
            WHERE a.user_id = %s
                AND a.account_type = 'LIABILITY'
            GROUP BY a.account_id, a.account_name, a.subtype
            HAVING ABS(balance) > 0.01
            ORDER BY a.account_name
        """, (user_id,))

        liabilities = cursor.fetchall()
        total_liabilities = sum(float(l['balance']) for l in liabilities)

        # Get all equity accounts
        cursor.execute("""
            SELECT
                a.account_name,
                a.subtype,
                COALESCE(SUM(le.credit - le.debit), 0) as balance
            FROM accounts a
            LEFT JOIN ledger le ON a.account_id = le.account_id
            WHERE a.user_id = %s
                AND a.account_type = 'EQUITY'
            GROUP BY a.account_id, a.account_name, a.subtype
            HAVING ABS(balance) > 0.01
            ORDER BY a.account_name
        """, (user_id,))

        equity = cursor.fetchall()
        total_equity = sum(float(e['balance']) for e in equity)

        cursor.close()
        conn.close()

        return jsonify({
            'assets': assets,
            'total_assets': float(total_assets),
            'liabilities': liabilities,
            'total_liabilities': float(total_liabilities),
            'equity': equity,
            'total_equity': float(total_equity),
            'total_liabilities_and_equity': float(total_liabilities + total_equity),
            'is_balanced': abs(total_assets - (total_liabilities + total_equity)) < 0.01
        })

    except Error as e:
        return jsonify({'error': str(e)}), 500

@financials_bp.route('/api/financials/reverse_transaction', methods=['POST'])
@login_required
def reverse_transaction():
    """Reverse a transaction by creating offsetting entries"""
    user_id = current_user.id
    data = request.json
    transaction_uuid = data.get('transaction_uuid')

    if not transaction_uuid:
        return jsonify({'error': 'Transaction UUID is required'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get all entries for this transaction
        cursor.execute("""
            SELECT le.*, a.user_id, a.account_name
            FROM ledger le
            JOIN accounts a ON le.account_id = a.account_id
            WHERE le.transaction_uuid = %s
        """, (transaction_uuid,))

        entries = cursor.fetchall()

        if not entries:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Transaction not found'}), 404

        # Verify ownership
        if entries[0]['user_id'] != user_id:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Unauthorized'}), 403

        # Generate new UUID for the reversing transaction
        import uuid
        reverse_uuid = str(uuid.uuid4())

        # Create reversing entries (swap debits and credits)
        for entry in entries:
            cursor.execute("""
                INSERT INTO ledger (
                    transaction_uuid,
                    account_id,
                    transaction_date,
                    debit,
                    credit,
                    description,
                    reference_type,
                    reference_id
                ) VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s)
            """, (
                reverse_uuid,
                entry['account_id'],
                entry['credit'],  # Swap: credit becomes debit
                entry['debit'],   # Swap: debit becomes credit
                f"REVERSAL: {entry['description']}" if entry['description'] else "REVERSAL",
                'REVERSAL',
                entry['entry_id']  # Reference the original entry
            ))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'reverse_uuid': reverse_uuid}), 200

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
