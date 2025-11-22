"""
Artifact Live - Server Control Panel
Simple GUI to start/stop/reset the Flask and Frontend servers
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import os
import sys
import webbrowser
from pathlib import Path

class ServerControlPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("Artifact Live - Server Control")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        # Server process handle
        self.flask_process = None

        # Setup UI
        self.setup_ui()

        # Set working directory to script location
        self.project_dir = Path(__file__).parent
        os.chdir(self.project_dir)

        # Check for required dependencies
        self.check_dependencies()

    def check_dependencies(self):
        """Check if required Python packages are installed."""
        try:
            # These are the new packages required for Google OAuth
            import requests
            from google.oauth2 import credentials
            from google_auth_oauthlib.flow import Flow
            self.log("✅ All required Python dependencies are installed.")
            return True
        except ImportError as e:
            self.log("=" * 60)
            self.log(f"❌ ERROR: A required Python package is missing: '{e.name}'")
            self.log("This is likely because the new dependencies for Google Login were not installed.")
            self.log("\nINSTRUCTIONS:")
            self.log("1. Close this window.")
            self.log("2. Open a terminal or command prompt.")
            self.log(f"3. Navigate to this directory: {self.project_dir}")
            self.log("4. Run the following command:")
            self.log(f"   pip install -r requirements.txt")
            self.log("5. Restart this Server Control Panel.")
            self.log("=" * 60)
            
            # Update UI to reflect the error
            self.start_btn.config(state=tk.DISABLED)
            self.reset_btn.config(state=tk.DISABLED)
            self.update_status("● Error: Missing Dependencies", "#ef4444")
            return False

    def setup_ui(self):
        # Title
        title_frame = tk.Frame(self.root, bg="#1f2937", pady=20)
        title_frame.pack(fill=tk.X)

        title_label = tk.Label(
            title_frame,
            text="Artifact Live",
            font=("Arial", 24, "bold"),
            bg="#1f2937",
            fg="white"
        )
        title_label.pack()

        subtitle_label = tk.Label(
            title_frame,
            text="Server Control Panel",
            font=("Arial", 12),
            bg="#1f2937",
            fg="#9ca3af"
        )
        subtitle_label.pack()

        # Control Buttons Frame
        control_frame = tk.Frame(self.root, bg="#f3f4f6", pady=20)
        control_frame.pack(fill=tk.X)

        button_style = {
            'font': ('Arial', 11, 'bold'),
            'padx': 20,
            'pady': 10,
            'relief': tk.FLAT,
            'cursor': 'hand2'
        }

        # Start Button
        self.start_btn = tk.Button(
            control_frame,
            text="▶ Start Server",
            bg="#10b981",
            fg="white",
            command=self.start_servers,
            **button_style
        )
        self.start_btn.pack(side=tk.LEFT, padx=10)

        # Stop Button
        self.stop_btn = tk.Button(
            control_frame,
            text="⏹ Stop Server",
            bg="#ef4444",
            fg="white",
            command=self.stop_servers,
            state=tk.DISABLED,
            **button_style
        )
        self.stop_btn.pack(side=tk.LEFT, padx=10)

        # Reset Button
        self.reset_btn = tk.Button(
            control_frame,
            text="🔄 Reset Server",
            bg="#f59e0b",
            fg="white",
            command=self.reset_servers,
            state=tk.DISABLED,
            **button_style
        )
        self.reset_btn.pack(side=tk.LEFT, padx=10)

        # Open Browser Button
        self.browser_btn = tk.Button(
            control_frame,
            text="🌐 Open in Browser",
            bg="#3b82f6",
            fg="white",
            command=self.open_browser,
            state=tk.DISABLED,
            **button_style
        )
        self.browser_btn.pack(side=tk.LEFT, padx=10)

        # Status Frame
        status_frame = tk.Frame(self.root, bg="#f3f4f6", pady=10)
        status_frame.pack(fill=tk.X)

        tk.Label(
            status_frame,
            text="Status:",
            font=("Arial", 10, "bold"),
            bg="#f3f4f6"
        ).pack(side=tk.LEFT, padx=10)

        self.status_label = tk.Label(
            status_frame,
            text="● Server Stopped",
            font=("Arial", 10),
            bg="#f3f4f6",
            fg="#ef4444"
        )
        self.status_label.pack(side=tk.LEFT)

        # URLs Frame
        urls_frame = tk.Frame(self.root, bg="#f3f4f6", pady=5)
        urls_frame.pack(fill=tk.X)

        tk.Label(
            urls_frame,
            text="Application: http://localhost:5000",
            font=("Arial", 9),
            bg="#f3f4f6",
            fg="#6b7280"
        ).pack()

        # Log Output
        log_frame = tk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(
            log_frame,
            text="Server Output:",
            font=("Arial", 10, "bold"),
            anchor=tk.W
        ).pack(fill=tk.X)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=20,
            bg="#1f2937",
            fg="#f3f4f6",
            font=("Consolas", 9),
            state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, message, color="#f3f4f6"):
        """Add message to log output"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def update_status(self, text, color):
        """Update status label"""
        self.status_label.config(text=text, fg=color)

    def start_servers(self):
        """Start Flask server (serves both backend and frontend)"""
        self.log("=" * 60)
        self.log("Starting Artifact Live Server...")
        self.log("=" * 60)

        try:
            # Check if .env exists
            if not os.path.exists('.env'):
                self.log("ERROR: .env file not found!", "#ef4444")
                self.log("Please create .env file with your database configuration.")
                return

            # Start Flask (serves both backend API and frontend files)
            self.log("\n▶ Starting Flask Application on port 5000...")
            self.flask_process = subprocess.Popen(
                [sys.executable, 'app.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # Start reading Flask output in separate thread
            threading.Thread(
                target=self.read_output,
                args=(self.flask_process, "Flask"),
                daemon=True
            ).start()

            # Update UI
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.reset_btn.config(state=tk.NORMAL)
            self.browser_btn.config(state=tk.NORMAL)
            self.update_status("● Server Running", "#10b981")

            self.log("\n✅ Server started successfully!")
            self.log("📌 Application: http://localhost:5000")
            self.log("\nClick 'Open in Browser' to launch the application.")

        except Exception as e:
            self.log(f"\n❌ ERROR: {str(e)}", "#ef4444")
            self.stop_servers()

    def read_output(self, process, name):
        """Read process output and log it"""
        try:
            for line in process.stdout:
                if line.strip():
                    self.log(f"[{name}] {line.strip()}")
        except:
            pass

    def stop_servers(self):
        """Stop server"""
        self.log("\n" + "=" * 60)
        self.log("Stopping server...")
        self.log("=" * 60)

        # Stop Flask
        if self.flask_process:
            self.flask_process.terminate()
            self.flask_process.wait()
            self.flask_process = None
            self.log("⏹ Flask Application stopped")

        # Update UI
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.reset_btn.config(state=tk.DISABLED)
        self.browser_btn.config(state=tk.DISABLED)
        self.update_status("● Server Stopped", "#ef4444")

        self.log("\n✅ Server stopped.\n")

    def reset_servers(self):
        """Reset server (stop then start)"""
        self.log("\n🔄 Resetting server...")
        self.stop_servers()
        # Small delay before restart
        self.root.after(1000, self.start_servers)

    def open_browser(self):
        """Open the application in default browser"""
        self.log("\n🌐 Opening application in browser...")
        webbrowser.open('http://localhost:5000')

    def on_closing(self):
        """Handle window close event"""
        self.stop_servers()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ServerControlPanel(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
