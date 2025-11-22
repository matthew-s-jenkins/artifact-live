# Packaging Artifact Live as an Executable

This guide explains how to package Artifact Live (and your other Flask projects) as standalone .exe files.

## Option 1: Quick Development Run (Recommended for Now)

Just double-click **`RUN.bat`** - it will:
- Start the Flask backend
- Start the frontend server
- Open your browser automatically

## Option 2: Build Standalone Executable

### Prerequisites

1. Install PyInstaller:
```bash
pip install pyinstaller
```

### Build the Executable

**Method 1: Use the batch file**
```bash
build_exe.bat
```

**Method 2: Manual build**
```bash
pyinstaller build_exe.spec --clean
```

### What Gets Created

```
dist/
└── ArtifactLive.exe    # Standalone executable (~50-80MB)
```

### Running the Executable

1. **Copy required files to `dist/` folder**:
   - `.env` (with your database credentials)
   - Make sure MySQL is installed and accessible

2. **Initialize database** (first time only):
   ```bash
   mysql -u root -p < init_db.sql
   ```

3. **Run the executable**:
   ```bash
   cd dist
   ArtifactLive.exe
   ```

4. **Open browser** to `http://localhost:5000`
   - The frontend (index.html) will be served by Flask
   - Everything runs from a single .exe!

## For Your Other Projects (Perfect Books, Digital Harvest)

### Perfect Books

1. Navigate to Perfect Books folder:
```bash
cd C:\Projects\Perfect_Books
```

2. Create `build_exe.spec`:
```python
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['app.py'],
    datas=[('index.html', '.'), ('static', 'static')],
    hiddenimports=['flask', 'flask_cors', 'flask_login', 'mysql.connector', 'bcrypt'],
)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='PerfectBooks', console=True)
```

3. Build:
```bash
pyinstaller build_exe.spec --clean
```

### Digital Harvest

Same process - create spec file and build!

## Advanced: Remove Console Window

In `build_exe.spec`, change:
```python
console=True,  # Shows command prompt window
```
to:
```python
console=False,  # Runs in background (no console)
```

**WARNING**: If `console=False`, you won't see error messages. Keep it `True` during development.

## Adding a Custom Icon

1. Create or download a `.ico` file (256x256px recommended)
2. Save it as `icon.ico` in your project folder
3. In `build_exe.spec`, change:
```python
icon=None
```
to:
```python
icon='icon.ico'
```

## Troubleshooting

### "Module not found" errors
Add missing modules to `hiddenimports` in the spec file:
```python
hiddenimports=[
    'flask',
    'flask_cors',
    'flask_login',
    'mysql.connector',
    'bcrypt',
    'dotenv',
    'your_missing_module_here'
],
```

### Executable is too large
- Use UPX compression (already enabled in spec file)
- Exclude unnecessary packages in `excludes`

### Database connection fails
- Make sure `.env` is in the same folder as the .exe
- Verify MySQL is running: `mysql -u root -p -e "SHOW DATABASES;"`

## Distribution

To distribute your app to other computers:

1. **Create a zip file** with:
   - `ArtifactLive.exe`
   - `.env.example` (not your actual .env!)
   - `init_db.sql`
   - `README.md`

2. **User instructions**:
   - Install MySQL
   - Copy `.env.example` to `.env` and configure
   - Run `init_db.sql` to create database
   - Run `ArtifactLive.exe`

## Pro Tip: Create an Installer

For a professional installer (like Setup.exe):
- Use **Inno Setup** (free) - https://jrsoftware.org/isinfo.php
- Or **NSIS** - https://nsis.sourceforge.io/

This creates a proper Windows installer that handles:
- Installation to Program Files
- Desktop shortcuts
- Start menu entries
- Uninstaller

## Build All Your Projects at Once

Create `C:\Projects\build_all.bat`:
```batch
@echo off
cd C:\Projects\Artifact_Live
call build_exe.bat

cd C:\Projects\Perfect_Books
call build_exe.bat

cd C:\Projects\Digital_Harvest
call build_exe.bat

echo All projects built!
pause
```
