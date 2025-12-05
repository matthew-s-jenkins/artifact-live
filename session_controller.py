"""
Session Controller for Artifact Live
Centralized session management using Flask-Login

This module provides:
- User authentication (register, login, logout)
- Session management with secure cookies
- User loader for Flask-Login
- Protected route decorator
- Google OAuth2 integration support

Usage:
    from session_controller import SessionController, User

    # Initialize in your Flask app
    session_ctrl = SessionController(app, get_db_connection_func)

    # Use in routes
    @app.route('/api/protected')
    @login_required
    def protected_route():
        user = session_ctrl.get_current_user()
        return jsonify({"user": user.username})
"""

from flask import jsonify, request, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from functools import wraps


class User(UserMixin):
    """User model for Flask-Login."""

    def __init__(self, user_id, username, email=None):
        self.id = user_id
        self.username = username
        self.email = email


class SessionController:
    """
    Manages user sessions and authentication for Flask applications.

    Features:
    - Flask-Login integration
    - Secure session cookies
    - User authentication
    - Protected routes
    - OAuth2 support
    """

    def __init__(self, app, db_connection_func, login_view='index', session_config=None):
        """
        Initialize the session controller.

        Args:
            app: Flask application instance
            db_connection_func: Function that returns database connection
            login_view: Name of the login route (default: 'index')
            session_config: Optional dict with session cookie configuration
        """
        self.app = app
        self.get_db = db_connection_func
        self.login_manager = LoginManager()

        # Configure session security
        self._configure_session(session_config)

        # Initialize Flask-Login
        self._init_login_manager(login_view)

    def _configure_session(self, session_config=None):
        """Configure session cookie security settings."""
        if session_config is None:
            session_config = {
                'SESSION_COOKIE_SAMESITE': 'Lax',
                'SESSION_COOKIE_HTTPONLY': True,
                'SESSION_COOKIE_SECURE': False,  # Set to True in production with HTTPS
                'REMEMBER_COOKIE_SAMESITE': 'Lax',
                'REMEMBER_COOKIE_HTTPONLY': True
            }

        for key, value in session_config.items():
            self.app.config[key] = value

    def _init_login_manager(self, login_view):
        """Initialize Flask-Login with user loader."""
        self.login_manager.init_app(self.app)
        self.login_manager.login_view = login_view

        @self.login_manager.user_loader
        def load_user(user_id):
            """Load user from database by ID."""
            connection = self.get_db()
            if not connection:
                return None

            try:
                cursor = connection.cursor(dictionary=True)
                cursor.execute("SELECT user_id, username, email FROM users WHERE user_id = %s", (user_id,))
                user_data = cursor.fetchone()

                if user_data:
                    return User(user_data['user_id'], user_data['username'], user_data.get('email'))
                return None
            except Exception as e:
                print(f"Error loading user {user_id}: {e}")
                return None
            finally:
                cursor.close()
                connection.close()

        @self.login_manager.unauthorized_handler
        def unauthorized():
            """Handle unauthorized access attempts."""
            return jsonify({'message': 'Authentication required'}), 401

    def login(self, user, remember=False):
        """
        Log in a user.

        Args:
            user: User object to log in
            remember: Whether to use a remember-me cookie

        Returns:
            bool: True if successful
        """
        login_user(user, remember=remember)
        return True

    def logout(self):
        """
        Log out the current user and clear session.

        Returns:
            Flask response object with cleared cookies
        """
        logout_user()
        session.clear()
        response = jsonify({'message': 'Logout successful'})
        # Clear session cookies
        response.set_cookie('session', '', expires=0)
        response.set_cookie('remember_token', '', expires=0)
        return response

    def get_current_user(self):
        """
        Get the current logged-in user.

        Returns:
            User object or None if not authenticated
        """
        return current_user if current_user.is_authenticated else None

    def is_authenticated(self):
        """
        Check if a user is currently authenticated.

        Returns:
            bool: True if authenticated, False otherwise
        """
        return current_user.is_authenticated

    def create_user_object(self, user_id, username, email=None):
        """
        Create a User object (helper method).

        Args:
            user_id: User ID
            username: Username
            email: Optional email address

        Returns:
            User object
        """
        return User(user_id=user_id, username=username, email=email)


def login_required_api(f):
    """
    Decorator for API routes that require authentication.
    Returns JSON error instead of redirect.

    Usage:
        @app.route('/api/data')
        @login_required_api
        def get_data():
            return jsonify({"data": "sensitive"})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"message": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function


# Export commonly used items
__all__ = ['SessionController', 'User', 'login_required_api', 'login_required', 'current_user']
