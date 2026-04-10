"""
Artifact Live v2 - Business Events API

REST endpoints for the BusinessEvent layer. Thin wrappers over the
accounting service — all business logic lives in services/accounting.py.

Endpoints:
    POST   /api/events                     - Create a business event
    GET    /api/events                     - List events (with filters)
    GET    /api/events/<event_id>          - Get single event with entries
    POST   /api/events/<event_id>/post     - Transition to posted
    POST   /api/events/<event_id>/void     - Void with reversal entries
    POST   /api/events/<event_id>/reconcile - Mark as reconciled
    GET    /api/events/<event_id>/children - Child events (composition)
    GET    /api/accounts/balances          - Current account balances
    GET    /api/transactions/<uuid>        - Transaction detail with entries
    GET    /api/event-types                - List available event types

Author: Matthew Jenkins
Date: 2026-04-10
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import sys
from pathlib import Path

# Add backend to path so services module is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
from services.accounting import (
    create_business_event, post_event, void_event, reconcile_event,
    get_event, list_events, get_account_balances, get_transaction_detail,
    EVENT_TYPES,
)


events_bp = Blueprint('events', __name__)


# =============================================================================
# EVENT CRUD
# =============================================================================

@events_bp.route('/events', methods=['POST'])
@login_required
def create_event():
    """
    Create a new business event with transaction and ledger entries.

    Request JSON:
        event_type:      string (required) — key in EVENT_TYPES
        event_date:      string (required) — YYYY-MM-DD
        metadata:        object (required) — type-specific data
        entity_type:     string (optional) — 'project', 'part', 'part_set'
        entity_id:       int (optional)
        parent_event_id: string (optional) — UUID of parent event
        source:          string (optional) — 'manual' (default), 'auto', 'import'
        notes:           string (optional)
        auto_post:       bool (optional) — post immediately (default false)

    Returns:
        success: bool
        event: object with event_id, transaction_uuid, status, etc.
    """
    data = request.get_json()
    if not data:
        return jsonify(success=False, message="Request body required."), 400

    event_type = data.get('event_type', '').strip()
    event_date = data.get('event_date', '').strip()
    metadata = data.get('metadata')

    if not event_type:
        return jsonify(success=False, message="event_type is required."), 400
    if not event_date:
        return jsonify(success=False, message="event_date is required."), 400
    if not metadata or not isinstance(metadata, dict):
        return jsonify(success=False, message="metadata dict is required."), 400

    try:
        result = create_business_event(
            user_id=int(current_user.id),
            event_type=event_type,
            event_date=event_date,
            metadata=metadata,
            entity_type=data.get('entity_type'),
            entity_id=data.get('entity_id'),
            parent_event_id=data.get('parent_event_id'),
            source=data.get('source', 'manual'),
            notes=data.get('notes'),
            auto_post=data.get('auto_post', False),
        )
        return jsonify(success=True, event=result), 201

    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400
    except Exception as e:
        print(f"[EVENTS] Create error: {e}")
        return jsonify(success=False, message="Failed to create event."), 500


@events_bp.route('/events', methods=['GET'])
@login_required
def list_events_route():
    """
    List business events with optional filters.

    Query params:
        event_type:      string — filter by type
        status:          string — filter by status
        entity_type:     string — filter by entity type
        entity_id:       int — filter by entity ID
        parent_event_id: string — filter by parent event
        date_from:       string — YYYY-MM-DD
        date_to:         string — YYYY-MM-DD
        page:            int (default 1)
        per_page:        int (default 50, max 200)

    Returns:
        success: bool
        events: { items: [], total: int, page: int, per_page: int }
    """
    try:
        per_page = min(int(request.args.get('per_page', 50)), 200)
        page = max(int(request.args.get('page', 1)), 1)

        entity_id = request.args.get('entity_id')
        if entity_id is not None:
            entity_id = int(entity_id)

        result = list_events(
            user_id=int(current_user.id),
            event_type=request.args.get('event_type'),
            status=request.args.get('status'),
            entity_type=request.args.get('entity_type'),
            entity_id=entity_id,
            parent_event_id=request.args.get('parent_event_id'),
            date_from=request.args.get('date_from'),
            date_to=request.args.get('date_to'),
            page=page,
            per_page=per_page,
        )
        return jsonify(success=True, events=result)

    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400
    except Exception as e:
        print(f"[EVENTS] List error: {e}")
        return jsonify(success=False, message="Failed to list events."), 500


@events_bp.route('/events/<event_id>', methods=['GET'])
@login_required
def get_event_route(event_id):
    """
    Get a single business event with transaction and ledger entries.

    Returns:
        success: bool
        event: object with full event details, transaction, and entries[]
    """
    try:
        result = get_event(
            user_id=int(current_user.id),
            event_id=event_id,
        )
        if not result:
            return jsonify(success=False, message="Event not found."), 404

        return jsonify(success=True, event=result)

    except Exception as e:
        print(f"[EVENTS] Get error: {e}")
        return jsonify(success=False, message="Failed to get event."), 500


# =============================================================================
# STATUS TRANSITIONS
# =============================================================================

@events_bp.route('/events/<event_id>/post', methods=['POST'])
@login_required
def post_event_route(event_id):
    """
    Post a draft/pending event (transition to 'posted').
    Validates that ledger entries are balanced before posting.

    Returns:
        success: bool
        event: updated event object
    """
    try:
        result = post_event(
            user_id=int(current_user.id),
            event_id=event_id,
        )
        return jsonify(success=True, event=result)

    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400
    except Exception as e:
        print(f"[EVENTS] Post error: {e}")
        return jsonify(success=False, message="Failed to post event."), 500


@events_bp.route('/events/<event_id>/void', methods=['POST'])
@login_required
def void_event_route(event_id):
    """
    Void a posted event. Creates reversal entries (immutable ledger).

    Request JSON (optional):
        reason: string — why the event is being voided

    Returns:
        success: bool
        result: { original_event_id, reversal_event_id, reversal_transaction_uuid }
    """
    data = request.get_json() or {}

    try:
        result = void_event(
            user_id=int(current_user.id),
            event_id=event_id,
            reason=data.get('reason'),
        )
        return jsonify(success=True, result=result)

    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400
    except Exception as e:
        print(f"[EVENTS] Void error: {e}")
        return jsonify(success=False, message="Failed to void event."), 500


@events_bp.route('/events/<event_id>/reconcile', methods=['POST'])
@login_required
def reconcile_event_route(event_id):
    """
    Mark a posted event as reconciled (confirmed accurate).

    Returns:
        success: bool
        event: updated event object
    """
    try:
        result = reconcile_event(
            user_id=int(current_user.id),
            event_id=event_id,
        )
        return jsonify(success=True, event=result)

    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400
    except Exception as e:
        print(f"[EVENTS] Reconcile error: {e}")
        return jsonify(success=False, message="Failed to reconcile event."), 500


# =============================================================================
# CHILD EVENTS (Composition)
# =============================================================================

@events_bp.route('/events/<event_id>/children', methods=['GET'])
@login_required
def list_child_events(event_id):
    """
    List child events of a parent event (composition pattern).

    Returns:
        success: bool
        events: { items: [], total: int, page: int, per_page: int }
    """
    try:
        result = list_events(
            user_id=int(current_user.id),
            parent_event_id=event_id,
        )
        return jsonify(success=True, events=result)

    except Exception as e:
        print(f"[EVENTS] Children error: {e}")
        return jsonify(success=False, message="Failed to list child events."), 500


# =============================================================================
# ACCOUNTS & TRANSACTIONS
# =============================================================================

@events_bp.route('/accounts/balances', methods=['GET'])
@login_required
def get_balances():
    """
    Get current account balances.

    Returns:
        success: bool
        accounts: list of account balance objects
    """
    try:
        balances = get_account_balances(user_id=int(current_user.id))
        return jsonify(success=True, accounts=balances)

    except Exception as e:
        print(f"[EVENTS] Balances error: {e}")
        return jsonify(success=False, message="Failed to get balances."), 500


@events_bp.route('/transactions/<transaction_uuid>', methods=['GET'])
@login_required
def get_transaction_route(transaction_uuid):
    """
    Get a transaction by UUID with all ledger entries.

    Returns:
        success: bool
        transaction: object with entries[]
    """
    try:
        result = get_transaction_detail(
            user_id=int(current_user.id),
            transaction_uuid=transaction_uuid,
        )
        if not result:
            return jsonify(success=False, message="Transaction not found."), 404

        return jsonify(success=True, transaction=result)

    except Exception as e:
        print(f"[EVENTS] Transaction error: {e}")
        return jsonify(success=False, message="Failed to get transaction."), 500


# =============================================================================
# EVENT TYPE REFERENCE
# =============================================================================

@events_bp.route('/event-types', methods=['GET'])
@login_required
def list_event_types():
    """
    List available event types and their metadata requirements.

    Returns:
        success: bool
        types: dict of event type definitions
    """
    types_info = {}
    for key, val in EVENT_TYPES.items():
        types_info[key] = {
            'description': val['description'],
            'required_metadata': val['required_meta'],
            'optional_metadata': val['optional_meta'],
        }
    return jsonify(success=True, types=types_info)
