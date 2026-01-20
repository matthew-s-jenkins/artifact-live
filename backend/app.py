"""
Artifact Live v2 - Flask REST API

This module provides a RESTful API for Artifact Live, a business operations platform
for tracking project-based inventory and calculating profitability.

Built from Digital Harvest v5 foundation with game mechanics removed.

Features:
- User authentication with Flask-Login and bcrypt
- Multi-business support with subsections
- Project management (systems/acquisitions/flips)
- Parts tracking with FIFO costing
- Fee calculations for marketplace sales
- Double-entry accounting foundation

Author: Matthew Jenkins
Date: 2026-01-19
License: MIT
"""

from flask import Flask, jsonify, request, send_from_directory, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import json
from decimal import Decimal
import datetime
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# =============================================================================
# CUSTOM JSON ENCODING
# =============================================================================

from flask.json.provider import DefaultJSONProvider

class CustomJSONProvider(DefaultJSONProvider):
    """
    Custom JSON encoder for handling Decimal and datetime objects.
    Decimal -> float, datetime -> ISO 8601 format.
    """
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, datetime.date):
            return obj.isoformat() + 'T12:00:00'
        return super().default(obj)


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def get_db_path():
    """Return path to the SQLite database file."""
    return Path(__file__).parent / "database" / "artifactlive.db"


def get_db_connection():
    """Get a database connection with row factory."""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database_if_needed():
    """Initialize database if it doesn't exist."""
    db_path = get_db_path()
    if not db_path.exists():
        print("[APP] Database not found - creating...")
        from database.init_db import create_database
        create_database()
        print("[APP] Database created successfully")


# =============================================================================
# FLASK APPLICATION SETUP
# =============================================================================

app = Flask(__name__, static_url_path='', static_folder='../frontend')
app.json = CustomJSONProvider(app)

# Security configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.getenv('FLASK_ENV') == 'production'

# Enable CORS for web interface
CORS(app, supports_credentials=True, origins=[
    'http://localhost:5000',
    'http://127.0.0.1:5000',
    'http://localhost:3000',  # React dev server
    'http://127.0.0.1:3000'
])

# Initialize database
init_database_if_needed()


# =============================================================================
# FLASK-LOGIN SETUP
# =============================================================================

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'serve_login_page'


@login_manager.unauthorized_handler
def unauthorized():
    """Handle unauthorized access."""
    if request.path.startswith('/api/'):
        return jsonify(success=False, message="Authorization required. Please log in."), 401
    return redirect(url_for('serve_login_page'))


class User(UserMixin):
    """Flask-Login User class."""
    def __init__(self, id, email):
        self.id = id
        self.email = email


@login_manager.user_loader
def load_user(user_id):
    """Load user from database for Flask-Login."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, email FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        conn.close()
        if user_data:
            return User(id=str(user_data['user_id']), email=user_data['email'])
    except Exception as e:
        print(f"[USER LOADER] Error: {e}")
    return None


# =============================================================================
# HTML SERVING ROUTES
# =============================================================================

@app.route('/')
def serve_index():
    """Serve main page - redirects to login or dashboard."""
    if current_user.is_authenticated:
        return redirect('/dashboard')
    return redirect('/login')


@app.route('/login')
def serve_login_page():
    """Serve login page."""
    return send_from_directory('../frontend', 'index.html')


@app.route('/register')
def serve_register_page():
    """Serve registration page."""
    return send_from_directory('../frontend', 'register.html')


@app.route('/dashboard')
@login_required
def serve_dashboard():
    """Serve main dashboard."""
    return send_from_directory('../frontend', 'dashboard.html')


@app.route('/projects')
@login_required
def serve_projects():
    """Serve projects list page."""
    return send_from_directory('../frontend', 'projects.html')


@app.route('/project/<int:project_id>')
@login_required
def serve_project_detail(project_id):
    """Serve project detail page."""
    return send_from_directory('../frontend', 'project-detail.html')


# =============================================================================
# HEALTH CHECK API
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for verifying API is running.
    Returns 200 if healthy.
    """
    db_ok = False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        db_ok = True
    except Exception as e:
        print(f"[HEALTH] Database check failed: {e}")

    return jsonify({
        "status": "healthy" if db_ok else "unhealthy",
        "database": "connected" if db_ok else "disconnected",
        "version": "2.0.0",
        "timestamp": datetime.datetime.now().isoformat()
    }), 200 if db_ok else 503


# =============================================================================
# AUTHENTICATION API ROUTES
# =============================================================================

@app.route('/api/register', methods=['POST'])
def register_user_api():
    """
    Register a new user account.

    Request JSON:
        email: User's email address
        password: Password (minimum 8 characters)

    Returns:
        success: bool
        message: string
        user_id: int (if successful)
    """
    import bcrypt

    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    # Validation
    if not email or '@' not in email:
        return jsonify(success=False, message="Valid email address required."), 400
    if len(password) < 8:
        return jsonify(success=False, message="Password must be at least 8 characters."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if email exists
        cursor.execute("SELECT user_id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify(success=False, message="Email already registered."), 409

        # Hash password and create user
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, password_hash)
        )
        new_user_id = cursor.lastrowid

        # Create default pricing config for new user
        default_config = [
            ('ebay_final_value_fee', 0.1315, 'eBay Final Value Fee (13.15%)'),
            ('ebay_payment_processing', 0.029, 'Payment processing fee (2.9%)'),
            ('ebay_payment_fixed', 0.30, 'Fixed payment processing fee ($0.30)'),
            ('ebay_promoted_listing', 0.0, 'Promoted listing fee (0% default)'),
            ('shipping_estimate_light', 8.00, 'Shipping for items under 1lb'),
            ('shipping_estimate_medium', 15.00, 'Shipping for items 1-5lb'),
            ('shipping_estimate_heavy', 25.00, 'Shipping for items 5lb+'),
        ]
        for key, value, desc in default_config:
            cursor.execute(
                "INSERT INTO pricing_config (user_id, config_key, config_value, description) VALUES (?, ?, ?, ?)",
                (new_user_id, key, value, desc)
            )

        # Create default accounts (chart of accounts)
        default_accounts = [
            ('Inventory Asset', 'ASSET', 'INVENTORY', 1),
            ('Cash', 'ASSET', 'CASH', 1),
            ('Owner Capital', 'EQUITY', 'OWNER_CAPITAL', 1),
            ('Sales Revenue', 'REVENUE', 'SALES', 1),
            ('Cost of Goods Sold', 'EXPENSE', 'COGS', 1),
            ('eBay Fees', 'EXPENSE', 'FEES', 1),
            ('Shipping Expense', 'EXPENSE', 'SHIPPING', 1),
        ]
        for name, acc_type, subtype, is_system in default_accounts:
            cursor.execute(
                "INSERT INTO accounts (user_id, account_name, account_type, subtype, is_system) VALUES (?, ?, ?, ?, ?)",
                (new_user_id, name, acc_type, subtype, is_system)
            )

        # Create default subsections
        default_subsections = [
            ('Computer Chop Shop', 'PC parting and flipping business', 1),
            ('Keyboards', 'Mechanical keyboard parts inventory', 0),
            ('Electronics', 'Electronics and microcontroller parts inventory', 0),
        ]
        for name, desc, is_business in default_subsections:
            cursor.execute(
                "INSERT INTO subsections (user_id, business_id, name, description, is_business) VALUES (?, NULL, ?, ?, ?)",
                (new_user_id, name, desc, is_business)
            )

        conn.commit()
        conn.close()

        # Log in the new user
        user = User(id=str(new_user_id), email=email)
        login_user(user)

        return jsonify(
            success=True,
            message="Registration successful!",
            user_id=new_user_id
        ), 201

    except Exception as e:
        print(f"[REGISTER] Error: {e}")
        return jsonify(success=False, message="Registration failed. Please try again."), 500


@app.route('/api/login', methods=['POST'])
def login_user_api():
    """
    Authenticate user and create session.

    Request JSON:
        email: User's email address
        password: User's password

    Returns:
        success: bool
        message: string
    """
    import bcrypt

    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify(success=False, message="Email and password are required."), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, email, password_hash FROM users WHERE email = ?",
            (email,)
        )
        user_data = cursor.fetchone()
        conn.close()

        if not user_data:
            return jsonify(success=False, message="Invalid email or password."), 401

        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash'].encode('utf-8')):
            return jsonify(success=False, message="Invalid email or password."), 401

        # Create session
        user = User(id=str(user_data['user_id']), email=user_data['email'])
        login_user(user)

        return jsonify(success=True, message="Login successful!")

    except Exception as e:
        print(f"[LOGIN] Error: {e}")
        return jsonify(success=False, message="Login failed. Please try again."), 500


@app.route('/api/logout', methods=['POST'])
@login_required
def logout_api():
    """Log out current user and clear session."""
    logout_user()
    return jsonify(success=True, message="You have been logged out.")


@app.route('/api/check_auth', methods=['GET'])
def check_auth():
    """Check if user is authenticated and return user info."""
    if current_user.is_authenticated:
        return jsonify(
            authenticated=True,
            user={
                'id': current_user.id,
                'email': current_user.email
            }
        )
    return jsonify(authenticated=False)


# =============================================================================
# IMPORT ROUTE BLUEPRINTS
# =============================================================================

from routes.projects import projects_bp
from routes.parts import parts_bp
from routes.pricing import pricing_bp

app.register_blueprint(projects_bp, url_prefix='/api')
app.register_blueprint(parts_bp, url_prefix='/api')
app.register_blueprint(pricing_bp, url_prefix='/api')


# =============================================================================
# RUN APPLICATION
# =============================================================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') != 'production'

    print("=" * 60)
    print("Artifact Live v2 - Starting Server")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"Debug: {debug}")
    print(f"Database: {get_db_path()}")
    print("=" * 60)

    app.run(host='0.0.0.0', port=port, debug=debug)
