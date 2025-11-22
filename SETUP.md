# Artifact Live - Setup Instructions

## Prerequisites

- Python 3.8+
- MySQL 8.0+
- Git Bash (Windows) or Terminal (Mac/Linux)

## Database Setup

1. **Start MySQL** (if not already running)

2. **Create the database**:
   ```bash
   mysql -u root -p < init_db.sql
   ```

3. **Verify database creation**:
   ```bash
   mysql -u root -p artifact_live -e "SHOW TABLES;"
   ```

## Backend Setup

1. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows Git Bash
   # OR
   source venv/bin/activate      # Mac/Linux
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Create `.env` file**:
   ```bash
   cp .env.example .env
   ```

4. **Edit `.env` file** with your MySQL credentials:
   ```
   SECRET_KEY=your-secret-key-here
   DB_HOST=localhost
   DB_USER=root
   DB_PASSWORD=your-mysql-password
   DB_NAME=artifact_live
   ```

## Running the Application

### Start the Flask Backend

```bash
python app.py
```

The API server will run on `http://localhost:5000`

### Start the Frontend

Open a new terminal and run a simple HTTP server:

```bash
python -m http.server 8000
```

Then open your browser to `http://localhost:8000`

## Testing

1. Click "Get Started" on the welcome page
2. Click "Register" and create an account
3. You should be logged in and see the dashboard!

## Project Structure

```
Artifact_Live/
├── app.py              # Flask application
├── init_db.sql         # Database schema
├── requirements.txt    # Python dependencies
├── .env               # Environment variables (create from .env.example)
├── index.html         # React frontend
└── README.md          # Project documentation
```

## Database Schema Overview

- **users** - User accounts with bcrypt password hashing
- **products** - Product catalog with SKUs
- **inventory_layers** - FIFO cost tracking
- **vendors** - Vendor management
- **purchase_orders** - PO tracking
- **sales_orders** - Sales order management
- **accounts** - Chart of accounts
- **ledger** - Double-entry accounting ledger

## API Endpoints

### Authentication
- `POST /api/register` - Create new user
- `POST /api/login` - Login
- `POST /api/logout` - Logout
- `GET /api/check_auth` - Check authentication status

### Dashboard
- `GET /api/dashboard/stats` - Get dashboard statistics

## Troubleshooting

### Database Connection Error
- Verify MySQL is running
- Check .env credentials
- Ensure database exists: `mysql -u root -p -e "SHOW DATABASES;"`

### CORS Error
- Make sure frontend is running on port 8000
- Backend should be on port 5000
- Check CORS configuration in app.py

### Password Hash Error
- Ensure bcrypt is installed: `pip install bcrypt`
- Try upgrading: `pip install --upgrade bcrypt`
