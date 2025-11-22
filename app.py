from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import mysql.connector
from mysql.connector import Error
import bcrypt
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Configure CORS - Allow all origins for development
CORS(app, supports_credentials=True, origins=['http://localhost:8000', 'http://127.0.0.1:8000', 'null'])

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'artifact_live')
}

# ============================================================================
# DATABASE CONNECTION
# ============================================================================

def get_db_connection():
    """Create and return a database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

# ============================================================================
# USER MODEL
# ============================================================================

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    connection = get_db_connection()
    if not connection:
        return None

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_id, username FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()

        if user_data:
            return User(user_data['user_id'], user_data['username'])
        return None
    finally:
        cursor.close()
        connection.close()

# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password required'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'message': 'Database connection failed'}), 500

    try:
        cursor = connection.cursor(dictionary=True)

        # Check if username already exists
        cursor.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            return jsonify({'message': 'Username already exists'}), 400

        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Insert new user
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, password_hash)
        )
        connection.commit()

        # Get the new user
        user_id = cursor.lastrowid
        user = User(user_id, username)
        login_user(user)

        return jsonify({
            'message': 'Registration successful',
            'user': {'id': user_id, 'username': username}
        }), 201

    except Error as e:
        connection.rollback()
        print(f"Registration error: {e}")
        return jsonify({'message': 'Registration failed'}), 500
    finally:
        cursor.close()
        connection.close()

@app.route('/api/login', methods=['POST'])
def login():
    """Log in an existing user"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password required'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'message': 'Database connection failed'}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, username, password_hash FROM users WHERE username = %s",
            (username,)
        )
        user_data = cursor.fetchone()

        if not user_data:
            return jsonify({'message': 'Invalid credentials'}), 401

        # Verify password
        if bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash'].encode('utf-8')):
            user = User(user_data['user_id'], user_data['username'])
            login_user(user)
            return jsonify({
                'message': 'Login successful',
                'user': {'id': user_data['user_id'], 'username': user_data['username']}
            }), 200
        else:
            return jsonify({'message': 'Invalid credentials'}), 401

    except Error as e:
        print(f"Login error: {e}")
        return jsonify({'message': 'Login failed'}), 500
    finally:
        cursor.close()
        connection.close()

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    """Log out the current user"""
    logout_user()
    return jsonify({'message': 'Logout successful'}), 200

@app.route('/api/check_auth', methods=['GET'])
def check_auth():
    """Check if user is authenticated"""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'user': {'id': current_user.id, 'username': current_user.username}
        }), 200
    return jsonify({'authenticated': False}), 401

# ============================================================================
# DASHBOARD / STATS ROUTES
# ============================================================================

@app.route('/api/dashboard/stats', methods=['GET'])
@login_required
def get_dashboard_stats():
    """Get dashboard statistics"""
    connection = get_db_connection()
    if not connection:
        return jsonify({'message': 'Database connection failed'}), 500

    try:
        cursor = connection.cursor(dictionary=True)

        # For now, return placeholder data
        # We'll implement actual queries once the database schema is complete
        stats = {
            'totalProducts': 0,
            'totalInventoryValue': 0.00,
            'lowStockItems': 0,
            'pendingOrders': 0
        }

        return jsonify(stats), 200

    except Error as e:
        print(f"Stats error: {e}")
        return jsonify({'message': 'Failed to fetch stats'}), 500
    finally:
        cursor.close()
        connection.close()

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@login_manager.unauthorized_handler
def unauthorized():
    """Handle unauthorized access"""
    return jsonify({'message': 'Authentication required'}), 401

@app.errorhandler(404)
def not_found(error):
    return jsonify({'message': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'message': 'Internal server error'}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
