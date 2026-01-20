"""
Artifact Live v2 - Pricing Calculations API

Server-side calculations for fee estimates, break-even analysis, and project profitability.

Endpoints:
    GET    /api/projects/<id>/summary   - Full financial summary for a project
    GET    /api/pricing-config          - Get user's pricing configuration
    PUT    /api/pricing-config          - Update pricing configuration
    GET    /api/parts/<id>/estimate     - Single part fee breakdown
    POST   /api/calculate               - Ad-hoc fee calculation

Author: Matthew Jenkins
Date: 2026-01-19
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import sqlite3
from pathlib import Path


pricing_bp = Blueprint('pricing', __name__)


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


def get_user_pricing_config(cursor, user_id):
    """Fetch user's pricing config as a dictionary."""
    cursor.execute(
        "SELECT config_key, config_value FROM pricing_config WHERE user_id = ?",
        (user_id,)
    )
    config = {}
    for row in cursor.fetchall():
        config[row['config_key']] = row['config_value']
    return config


def calculate_fees(price, config, weight_class='medium'):
    """
    Calculate eBay fees and shipping estimate for a given price.

    Fee formula:
        eBay Final Value Fee: price * 0.1315
        Payment Processing: price * 0.029 + $0.30
        Total Fees: price * 0.1605 + $0.30
        Net After Fees: price * 0.8395 - $0.30

    Args:
        price: Listing price
        config: User's pricing config dict
        weight_class: 'light', 'medium', or 'heavy'

    Returns:
        dict with fee breakdown
    """
    if price is None or price <= 0:
        return {
            'listing_price': 0,
            'final_value_fee': 0,
            'payment_processing_fee': 0,
            'payment_fixed_fee': 0,
            'promoted_listing_fee': 0,
            'total_fees': 0,
            'shipping_estimate': 0,
            'net_after_fees': 0,
            'net_after_shipping': 0
        }

    # Get rates from config (with defaults)
    final_value_rate = config.get('ebay_final_value_fee', 0.1315)
    processing_rate = config.get('ebay_payment_processing', 0.029)
    fixed_fee = config.get('ebay_payment_fixed', 0.30)
    promoted_rate = config.get('ebay_promoted_listing', 0.0)

    # Shipping estimates by weight class
    shipping_estimates = {
        'light': config.get('shipping_estimate_light', 8.00),
        'medium': config.get('shipping_estimate_medium', 15.00),
        'heavy': config.get('shipping_estimate_heavy', 25.00)
    }

    # Calculate fees
    final_value_fee = price * final_value_rate
    payment_processing_fee = price * processing_rate
    promoted_listing_fee = price * promoted_rate
    total_fees = final_value_fee + payment_processing_fee + fixed_fee + promoted_listing_fee

    # Get shipping estimate
    shipping_estimate = shipping_estimates.get(weight_class, shipping_estimates['medium'])

    # Net calculations
    net_after_fees = price - total_fees
    net_after_shipping = net_after_fees - shipping_estimate

    return {
        'listing_price': round(price, 2),
        'final_value_fee': round(final_value_fee, 2),
        'payment_processing_fee': round(payment_processing_fee, 2),
        'payment_fixed_fee': round(fixed_fee, 2),
        'promoted_listing_fee': round(promoted_listing_fee, 2),
        'total_fees': round(total_fees, 2),
        'shipping_estimate': round(shipping_estimate, 2),
        'net_after_fees': round(net_after_fees, 2),
        'net_after_shipping': round(net_after_shipping, 2)
    }


# =============================================================================
# PRICING CONFIG ENDPOINTS
# =============================================================================

@pricing_bp.route('/pricing-config', methods=['GET'])
@login_required
def get_pricing_config():
    """
    Get user's pricing configuration.

    Returns:
        success: bool
        config: dict of config_key -> config_value
        config_details: array with descriptions
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT config_key, config_value, description FROM pricing_config WHERE user_id = ?",
            (current_user.id,)
        )

        config = {}
        config_details = []

        for row in cursor.fetchall():
            config[row['config_key']] = row['config_value']
            config_details.append({
                'key': row['config_key'],
                'value': row['config_value'],
                'description': row['description']
            })

        conn.close()

        return jsonify(success=True, config=config, config_details=config_details)

    except Exception as e:
        print(f"[PRICING] Get config error: {e}")
        return jsonify(success=False, message="Failed to retrieve pricing config."), 500


@pricing_bp.route('/pricing-config', methods=['PUT'])
@login_required
def update_pricing_config():
    """
    Update user's pricing configuration.

    Request JSON:
        Object with config_key -> config_value pairs
        e.g., {"ebay_final_value_fee": 0.1315, "shipping_estimate_light": 9.00}

    Returns:
        success: bool
        config: updated config dict
    """
    data = request.get_json()

    if not data or not isinstance(data, dict):
        return jsonify(success=False, message="Config object required."), 400

    # Valid config keys
    valid_keys = {
        'ebay_final_value_fee',
        'ebay_payment_processing',
        'ebay_payment_fixed',
        'ebay_promoted_listing',
        'shipping_estimate_light',
        'shipping_estimate_medium',
        'shipping_estimate_heavy'
    }

    # Validate keys
    invalid_keys = set(data.keys()) - valid_keys
    if invalid_keys:
        return jsonify(success=False, message=f"Invalid config keys: {invalid_keys}"), 400

    # Validate values (percentages should be 0-1, amounts should be positive)
    percentage_keys = {'ebay_final_value_fee', 'ebay_payment_processing', 'ebay_promoted_listing'}
    for key, value in data.items():
        if not isinstance(value, (int, float)):
            return jsonify(success=False, message=f"Config value for {key} must be a number."), 400
        if key in percentage_keys:
            if not (0 <= value <= 1):
                return jsonify(success=False, message=f"{key} must be between 0 and 1 (percentage as decimal)."), 400
        else:
            if value < 0:
                return jsonify(success=False, message=f"{key} must be positive."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        for key, value in data.items():
            cursor.execute(
                "UPDATE pricing_config SET config_value = ? WHERE user_id = ? AND config_key = ?",
                (value, current_user.id, key)
            )

        conn.commit()

        # Return updated config
        config = get_user_pricing_config(cursor, current_user.id)

        conn.close()

        return jsonify(success=True, config=config, message="Pricing config updated.")

    except Exception as e:
        print(f"[PRICING] Update config error: {e}")
        return jsonify(success=False, message="Failed to update pricing config."), 500


# =============================================================================
# PROJECT SUMMARY ENDPOINT
# =============================================================================

@pricing_bp.route('/projects/<int:project_id>/summary', methods=['GET'])
@login_required
def get_project_summary(project_id):
    """
    Get full financial summary for a project.

    Returns:
        success: bool
        project: basic project info
        summary: financial summary object containing:
            - acquisition_cost
            - parts_total, parts_for_sale, parts_sold, parts_kept, parts_trashed
            - total_estimated_value
            - total_estimated_fees
            - total_estimated_shipping
            - projected_net_revenue
            - projected_profit
            - profit_margin_percent
            - break_even_per_part
            - actual_revenue (from sold parts)
            - actual_fees (from sold parts)
            - actual_shipping (from sold parts)
            - actual_profit (from sold parts)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify project exists and belongs to user
        cursor.execute("""
            SELECT p.*, s.name as subsection_name
            FROM projects p
            JOIN subsections s ON p.subsection_id = s.subsection_id
            WHERE p.project_id = ? AND p.user_id = ?
        """, (project_id, current_user.id))

        project = cursor.fetchone()
        if not project:
            conn.close()
            return jsonify(success=False, message="Project not found."), 404

        project_dict = row_to_dict(project)
        acquisition_cost = project_dict['acquisition_cost'] or 0

        # Get pricing config
        config = get_user_pricing_config(cursor, current_user.id)

        # Get all parts for this project
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category
            FROM project_parts pp
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.project_id = ?
        """, (project_id,))

        parts = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()

        # Count parts by status
        parts_total = len(parts)
        parts_for_sale = 0  # IN_SYSTEM + LISTED
        parts_sold = 0
        parts_kept = 0
        parts_trashed = 0
        parts_in_project = 0

        # Estimated totals (for parts we plan to sell)
        total_estimated_value = 0
        total_estimated_fees = 0
        total_estimated_shipping = 0

        # Actual totals (from sold parts)
        actual_revenue = 0
        actual_fees = 0
        actual_shipping = 0

        # Track sets to avoid double-counting (sets are sold as single transaction)
        processed_sets = set()

        for part in parts:
            status = part['status']
            set_id = part['set_id']
            weight_class = part['weight_class'] or 'medium'

            # Count by status
            if status == 'SOLD':
                parts_sold += 1
                # Actual sale data
                if part['actual_sale_price']:
                    actual_revenue += part['actual_sale_price']
                if part['fees_paid']:
                    actual_fees += part['fees_paid']
                if part['shipping_paid']:
                    actual_shipping += part['shipping_paid']
            elif status == 'KEPT':
                parts_kept += 1
            elif status == 'TRASHED':
                parts_trashed += 1
            elif status == 'IN_PROJECT':
                parts_in_project += 1
            elif status in ('IN_SYSTEM', 'LISTED'):
                parts_for_sale += 1

                # For set parts, only count the set once
                if set_id:
                    if set_id in processed_sets:
                        continue  # Already counted this set
                    processed_sets.add(set_id)

                # Add estimated value
                if part['estimated_value']:
                    total_estimated_value += part['estimated_value']

                    # Calculate fees for this estimated value
                    fees = calculate_fees(part['estimated_value'], config, weight_class)
                    total_estimated_fees += fees['total_fees']
                    total_estimated_shipping += fees['shipping_estimate']

        # Calculate projections
        projected_net_revenue = total_estimated_value - total_estimated_fees - total_estimated_shipping
        projected_profit = projected_net_revenue - acquisition_cost

        # Profit margin (avoid divide by zero)
        profit_margin_percent = 0
        if acquisition_cost > 0:
            profit_margin_percent = (projected_profit / acquisition_cost) * 100

        # Break-even per part (parts we plan to sell + already sold)
        sellable_parts = parts_for_sale + parts_sold
        break_even_per_part = 0
        if sellable_parts > 0:
            break_even_per_part = acquisition_cost / sellable_parts

        # Actual profit from sold parts
        actual_profit = actual_revenue - actual_fees - actual_shipping - (break_even_per_part * parts_sold) if parts_sold > 0 else 0

        summary = {
            # Counts
            'parts_total': parts_total,
            'parts_for_sale': parts_for_sale,
            'parts_sold': parts_sold,
            'parts_kept': parts_kept,
            'parts_trashed': parts_trashed,
            'parts_in_project': parts_in_project,

            # Acquisition
            'acquisition_cost': round(acquisition_cost, 2),
            'break_even_per_part': round(break_even_per_part, 2),

            # Estimated (for unsold parts)
            'total_estimated_value': round(total_estimated_value, 2),
            'total_estimated_fees': round(total_estimated_fees, 2),
            'total_estimated_shipping': round(total_estimated_shipping, 2),
            'projected_net_revenue': round(projected_net_revenue, 2),
            'projected_profit': round(projected_profit, 2),
            'profit_margin_percent': round(profit_margin_percent, 2),

            # Actual (from sold parts)
            'actual_revenue': round(actual_revenue, 2),
            'actual_fees': round(actual_fees, 2),
            'actual_shipping': round(actual_shipping, 2),
            'actual_profit': round(actual_profit, 2)
        }

        return jsonify(success=True, project=project_dict, summary=summary)

    except Exception as e:
        print(f"[PRICING] Project summary error: {e}")
        return jsonify(success=False, message="Failed to calculate project summary."), 500


# =============================================================================
# PART ESTIMATE ENDPOINT
# =============================================================================

@pricing_bp.route('/parts/<int:part_id>/estimate', methods=['GET'])
@login_required
def get_part_estimate(part_id):
    """
    Get fee breakdown estimate for a single part.

    Query params:
        price: float (optional) - Override estimated_value for calculation

    Returns:
        success: bool
        part: part info
        estimate: fee breakdown
    """
    override_price = request.args.get('price', type=float)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify part exists and belongs to user's project
        cursor.execute("""
            SELECT pp.*, pc.name as catalog_name, pc.category as catalog_category,
                   p.name as project_name, p.acquisition_cost
            FROM project_parts pp
            JOIN projects p ON pp.project_id = p.project_id
            LEFT JOIN parts_catalog pc ON pp.catalog_id = pc.catalog_id
            WHERE pp.part_id = ? AND p.user_id = ?
        """, (part_id, current_user.id))

        part = cursor.fetchone()
        if not part:
            conn.close()
            return jsonify(success=False, message="Part not found."), 404

        part_dict = row_to_dict(part)

        # Get pricing config
        config = get_user_pricing_config(cursor, current_user.id)

        conn.close()

        # Use override price or part's estimated value
        price = override_price if override_price is not None else (part_dict['estimated_value'] or 0)
        weight_class = part_dict['weight_class'] or 'medium'

        estimate = calculate_fees(price, config, weight_class)

        return jsonify(success=True, part=part_dict, estimate=estimate)

    except Exception as e:
        print(f"[PRICING] Part estimate error: {e}")
        return jsonify(success=False, message="Failed to calculate part estimate."), 500


# =============================================================================
# AD-HOC CALCULATION ENDPOINT
# =============================================================================

@pricing_bp.route('/calculate', methods=['POST'])
@login_required
def calculate_ad_hoc():
    """
    Ad-hoc fee calculation without referencing a specific part.

    Request JSON:
        price: float (required) - Listing price
        weight_class: string (optional) - 'light', 'medium', 'heavy' (default: medium)

    Returns:
        success: bool
        calculation: fee breakdown
    """
    data = request.get_json()

    price = data.get('price')
    weight_class = data.get('weight_class', 'medium')

    if price is None:
        return jsonify(success=False, message="price is required."), 400

    if not isinstance(price, (int, float)) or price < 0:
        return jsonify(success=False, message="price must be a positive number."), 400

    if weight_class not in ('light', 'medium', 'heavy'):
        weight_class = 'medium'

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        config = get_user_pricing_config(cursor, current_user.id)

        conn.close()

        calculation = calculate_fees(price, config, weight_class)

        return jsonify(success=True, calculation=calculation)

    except Exception as e:
        print(f"[PRICING] Calculate error: {e}")
        return jsonify(success=False, message="Failed to perform calculation."), 500
