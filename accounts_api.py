"""
Artifact Live - Accounts API
Manage chart of accounts
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

load_dotenv()

accounts_api_bp = Blueprint('accounts_api', __name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

@accounts_api_bp.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    """Get all accounts for the current user"""
    user_id = current_user.id

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                a.account_id,
                a.account_name,
                a.account_type,
                a.subtype,
                a.is_system,
                a.is_active,
                COALESCE(SUM(le.debit - le.credit), 0) as balance
            FROM accounts a
            LEFT JOIN ledger le ON a.account_id = le.account_id
            WHERE a.user_id = %s AND a.is_active = TRUE
            GROUP BY a.account_id, a.account_name, a.account_type, a.subtype, a.is_system, a.is_active
            ORDER BY
                FIELD(a.account_type, 'ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE'),
                a.account_name
        """, (user_id,))

        accounts = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(accounts)

    except Error as e:
        return jsonify({'error': str(e)}), 500

@accounts_api_bp.route('/api/accounts', methods=['POST'])
@login_required
def create_account():
    """Create a new account"""
    user_id = current_user.id
    data = request.json

    # Validate required fields
    if not data.get('account_name') or not data.get('account_type'):
        return jsonify({'error': 'Account name and type are required'}), 400

    account_name = data['account_name'].strip()
    account_type = data['account_type']
    subtype = data.get('subtype', '').strip()

    # Validate account_type
    valid_types = ['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE']
    if account_type not in valid_types:
        return jsonify({'error': f'Invalid account type. Must be one of: {", ".join(valid_types)}'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if account with same name already exists
        cursor.execute("""
            SELECT account_id FROM accounts
            WHERE user_id = %s AND account_name = %s AND is_active = TRUE
        """, (user_id, account_name))

        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Account with this name already exists'}), 400

        # Create account
        cursor.execute("""
            INSERT INTO accounts (user_id, account_name, account_type, subtype, is_system)
            VALUES (%s, %s, %s, %s, FALSE)
        """, (user_id, account_name, account_type, subtype))

        account_id = cursor.lastrowid
        conn.commit()

        # Fetch the created account
        cursor.execute("""
            SELECT account_id, account_name, account_type, subtype, is_system, is_active
            FROM accounts WHERE account_id = %s
        """, (account_id,))
        account = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify(account), 201

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500

@accounts_api_bp.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def delete_account(account_id):
    """Soft delete an account (set is_active = FALSE)"""
    user_id = current_user.id

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verify ownership and that it's not a system account
        cursor.execute("""
            SELECT account_id, is_system FROM accounts
            WHERE account_id = %s AND user_id = %s
        """, (account_id, user_id))

        account = cursor.fetchone()
        if not account:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Account not found'}), 404

        if account['is_system']:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Cannot delete system accounts'}), 400

        # Soft delete
        cursor.execute("""
            UPDATE accounts
            SET is_active = FALSE
            WHERE account_id = %s
        """, (account_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'account_id': account_id})

    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
