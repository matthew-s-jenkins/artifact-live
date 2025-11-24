from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import mysql.connector
from mysql.connector import Error
import bcrypt
import os
from dotenv import load_dotenv
import requests
from google.oauth2 import credentials
from google_auth_oauthlib.flow import Flow

# Import blueprints
from ingest_api import ingest_bp
from locations_api import locations_bp
from inventory_api import inventory_bp
from financials_api import financials_bp
from accounts_api import accounts_api_bp

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Session configuration
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_HTTPONLY'] = True

# Configure CORS - more restrictive now that we're serving from same origin
CORS(app, supports_credentials=True, origins=['http://localhost:5000', 'http://127.0.0.1:5000'])

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

# Register blueprints
app.register_blueprint(ingest_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(financials_bp)
app.register_blueprint(accounts_api_bp)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'artifact_live')
}

# Google OAuth2 Configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

client_config = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:5000/api/auth/google/callback", "http://127.0.0.1:5000/api/auth/google/callback"]
    }
}

SCOPES = ['https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile', 'openid']

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
    def __init__(self, user_id, username, email=None):
        self.id = user_id
        self.username = username
        self.email = email


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    connection = get_db_connection()
    if not connection:
        return None

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_id, username, email FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()

        if user_data:
            return User(user_data['user_id'], user_data['username'], user_data.get('email'))
        return None
    finally:
        cursor.close()
        connection.close()

# ============================================================================
# STATIC FILE ROUTES
# ============================================================================

@app.route('/')
def index():
    """Serve the login/index page or redirect to home if logged in"""
    if current_user.is_authenticated:
        return redirect('/home.html')
    return send_from_directory('.', 'index.html')

@app.route('/home.html')
def home():
    """Serve the home/workspace selector page"""
    return send_from_directory('.', 'home.html')

@app.route('/dashboard.html')
def dashboard():
    """Serve the dashboard page - requires business_id parameter"""
    business_id = request.args.get('business_id')
    if not business_id:
        # Redirect to home page if no business selected
        return redirect('/home.html')
    return send_from_directory('.', 'dashboard.html')

# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')

    if not username or not password or not email:
        return jsonify({'message': 'Username, password, and email required'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'message': 'Database connection failed'}), 500

    try:
        cursor = connection.cursor(dictionary=True)

        # Check if username or email already exists
        cursor.execute("SELECT user_id FROM users WHERE username = %s OR email = %s", (username, email))
        if cursor.fetchone():
            return jsonify({'message': 'Username or email already exists'}), 400

        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Insert new user
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (username, email, password_hash)
        )
        connection.commit()

        # Get the new user
        user_id = cursor.lastrowid
        user = User(user_id, username, email)
        login_user(user)

        return jsonify({
            'message': 'Registration successful',
            'user': {'id': user_id, 'username': username, 'email': email}
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
            "SELECT user_id, username, email, password_hash FROM users WHERE username = %s",
            (username,)
        )
        user_data = cursor.fetchone()

        if not user_data:
            return jsonify({'message': 'Invalid credentials'}), 401

        # Verify password
        if user_data['password_hash'] and bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash'].encode('utf-8')):
            user = User(user_data['user_id'], user_data['username'], user_data.get('email'))
            login_user(user)
            return jsonify({
                'message': 'Login successful',
                'user': {'id': user_data['user_id'], 'username': user_data['username'], 'email': user_data.get('email')}
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
    session.clear()
    response = jsonify({'message': 'Logout successful'})
    # Clear session cookies
    response.set_cookie('session', '', expires=0)
    response.set_cookie('remember_token', '', expires=0)
    return response, 200

@app.route('/api/check_auth', methods=['GET'])
def check_auth():
    """Check if user is authenticated"""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'user': {'id': current_user.id, 'username': current_user.username, 'email': getattr(current_user, 'email', None)}
        }), 200
    return jsonify({'authenticated': False}), 401

# ============================================================================
# GOOGLE OAUTH2 ROUTES
# ============================================================================

@app.route('/api/auth/google')
def auth_google():
    """Redirect to Google's OAuth 2.0 server"""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({'message': 'Google OAuth not configured'}), 500

    # Disable HTTPS requirement for local development
    import os
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=url_for('auth_google_callback', _external=True)
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/api/auth/google/callback')
def auth_google_callback():
    """Handle the OAuth 2.0 server response"""
    # Disable HTTPS requirement for local development
    import os
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    state = session.get('state')

    if not state or state != request.args.get('state'):
        return jsonify({'message': 'State mismatch error'}), 400

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({'message': 'Google OAuth not configured'}), 500

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for('auth_google_callback', _external=True)
    )

    # Exchange the authorization code for an access token
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    # Get user info
    user_info_service = requests.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        headers={'Authorization': f'Bearer {credentials.token}'}
    )

    if not user_info_service.ok:
        return jsonify({'message': 'Failed to fetch user info'}), 500

    user_info = user_info_service.json()
    email = user_info.get('email')
    username = user_info.get('name')

    if not email:
        return jsonify({'message': 'Email not provided by Google'}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({'message': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user_data = cursor.fetchone()
        
        if user_data:
            # User exists, log them in
            user = User(user_data['user_id'], user_data['username'], user_data.get('email'))
            login_user(user, remember=True)
        else:
            # User does not exist, register and log them in
            # Use email as username if there's no name, or create a unique one
            cursor.execute("SELECT user_id FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                username = f"{username}_{os.urandom(4).hex()}"

            cursor.execute(
                "INSERT INTO users (username, email, google_id) VALUES (%s, %s, %s)",
                (username, email, user_info.get('sub'))
            )
            connection.commit()
            user_id = cursor.lastrowid
            user = User(user_id, username, email)
            login_user(user, remember=True)

        # Redirect to home page (same origin now - no session issues!)
        return redirect('/home.html')

    except Error as e:
        print(f"Google login error: {e}")
        return jsonify({'message': 'Google login failed'}), 500
    finally:
        cursor.close()
        connection.close()


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
    # When running locally, disable OAuthlib's HTTPS verification.
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(debug=True, host='0.0.0.0', port=5000)
