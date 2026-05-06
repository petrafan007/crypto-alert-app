#!/usr/bin/env python3
"""
CRYPTO DESKTOP APP - ULTRA DEBUG VERSION
This version has MASSIVE debugging to catch the session transfer issue
"""
import sys
import os
import time
import threading
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path

try:
    from PyQt5.QtWidgets import *
    from PyQt5.QtCore import *
    from PyQt5.QtGui import *
    import requests
except ImportError as e:
    print(f"❌ MISSING DEPENDENCY: {e}")
    print("Run: pip install PyQt5 requests")
    sys.exit(1)

# Ultra-verbose logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('crypto_desktop.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

print("🚀🚀🚀 CRYPTO DESKTOP APP - ULTRA DEBUG VERSION 🚀🚀🚀")
print("=" * 60)
logger.info("🚀 ULTRA DEBUG VERSION STARTING")

class NotificationPoller(QThread):
    """Background thread that polls for notifications"""
    new_notification = pyqtSignal(dict)
    
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.running = True
        print("🔄 NOTIFICATION POLLER CREATED")
        logger.info("🔄 Notification poller created")
    
    def run(self):
        """Main polling loop with ULTRA DEBUG"""
        print("🔄🔄🔄 NOTIFICATION POLLER THREAD STARTED! 🔄🔄🔄")
        logger.info("🔄 Notification poller started")
        
        while self.running:
            try:
                print(f"🔍🔍🔍 [POLL] LOGIN CHECK: is_logged_in = {self.app.is_logged_in}")
                print(f"🔍🔍🔍 [POLL] USERNAME: {getattr(self.app, 'username', 'NONE')}")
                print(f"🔍🔍🔍 [POLL] SESSION EXISTS: {hasattr(self.app, 'session')}")
                
                if hasattr(self.app, 'session') and self.app.session:
                    cookies = dict(self.app.session.cookies)
                    print(f"🔍🔍🔍 [POLL] COOKIES: {len(cookies)} cookies")
                    logger.info(f"🔍 [POLL] Session cookies: {list(cookies.keys())}")
                else:
                    print("🔍🔍🔍 [POLL] NO SESSION OBJECT!")
                    logger.warning("🔍 [POLL] No session object found")
                
                logger.info(f"🔍 [POLL] Login status check: {self.app.is_logged_in}")
                
                if self.app.is_logged_in:
                    print("📡📡📡 LOGGED IN - FETCHING NOTIFICATIONS... 📡📡📡")
                    logger.info("📡 Polling for new notifications...")
                    
                    notifications = self.app.fetch_notifications()
                    
                    print(f"📡📡📡 FETCH RETURNED: {len(notifications)} notifications")
                    logger.info(f"📡 fetch_notifications returned: {len(notifications)} notifications")
                    
                    for notif in notifications:
                        print(f"📡📡📡 EMITTING: {notif.get('symbol')} {notif.get('direction')}")
                        logger.info(f"📡 Emitting notification: {notif.get('symbol')} {notif.get('direction')}")
                        self.new_notification.emit(notif)
                    
                    if notifications:
                        print(f"📨📨📨 EMITTED {len(notifications)} NOTIFICATIONS!")
                        logger.info(f"📨 Emitted {len(notifications)} notifications")
                    else:
                        print("📭📭📭 NO NEW NOTIFICATIONS")
                        logger.info("📭 No new notifications found")
                    
                    time.sleep(15)  # Poll every 15 seconds when logged in
                else:
                    print("⏸️⏸️⏸️ NOT LOGGED IN - WAITING... ⏸️⏸️⏸️")
                    logger.info("⏸️ Not logged in, waiting...")
                    time.sleep(10)  # Check more frequently when not logged in
                    
            except Exception as e:
                print(f"💥💥💥 POLLING ERROR: {type(e).__name__}: {e}")
                logger.error(f"💥 Polling error: {e}")
                time.sleep(30)  # Wait on error
                
    def stop(self):
        """Stop the polling thread"""
        print("🛑 STOPPING NOTIFICATION POLLER")
        logger.info("🛑 Stopping notification poller")
        self.running = False

class LoginDialog(QDialog):
    """Login dialog with ULTRA DEBUG"""
    
    def __init__(self, parent=None, base_url="http://127.0.0.1:5010"):
        super().__init__(parent)
        print("🔐🔐🔐 LOGIN DIALOG CONSTRUCTOR CALLED! 🔐🔐🔐")
        logger.info("🔐 LoginDialog constructor")
        
        self.base_url = base_url
        self.session = requests.Session()
        self.username = ""
        self.password = ""
        self.setup_ui()
        
        print("🔐🔐🔐 LOGIN DIALOG CREATED SUCCESSFULLY! 🔐🔐🔐")
        logger.info("🔐 Login dialog created")
        
    def setup_ui(self):
        """Set up the login UI"""
        self.setWindowTitle("Crypto Desktop Login")
        self.setFixedSize(900, 650)
        self.setModal(True)
        
        # Center the dialog
        self.center_on_screen()
        
        # Layout
        layout = QGridLayout(self)
        layout.setSpacing(25)
        layout.setContentsMargins(60, 40, 60, 40)
        
        # Title
        title = QLabel("🔐 Crypto Desktop Login")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50; margin-bottom: 20px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title, 0, 0, 1, 2)
        
        # Username
        layout.addWidget(QLabel("Username:"), 1, 0)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        self.username_input.setText("YOUR_USERNAME")  # Pre-fill
        layout.addWidget(self.username_input, 1, 1)
        
        # Password
        layout.addWidget(QLabel("Password:"), 2, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setText("YOUR_PASSWORD")  # Pre-fill
        layout.addWidget(self.password_input, 2, 1)
        
        # Status label
        self.status_label = QLabel("Ready to login")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label, 3, 0, 1, 2)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.test_btn = QPushButton("🔧 Test Connection")
        self.test_btn.clicked.connect(self.test_connection)
        button_layout.addWidget(self.test_btn)
        
        self.login_btn = QPushButton("🔐 Login")
        self.login_btn.clicked.connect(self.do_login)
        self.login_btn.setDefault(True)
        button_layout.addWidget(self.login_btn)
        
        cancel_btn = QPushButton("❌ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout, 4, 0, 1, 2)
        
        # Connect Enter key
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self.do_login)
        
        # Focus
        self.username_input.setFocus()
        
        logger.info("🔐 Login dialog UI setup complete")
        
    def center_on_screen(self):
        """Center the dialog on screen"""
        screen = QApplication.desktop().screenGeometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2
        )
        
    def test_connection(self):
        """Test server connection"""
        print("🔧🔧🔧 TESTING CONNECTION... 🔧🔧🔧")
        self.status_label.setText("🔧 Testing server connection...")
        self.test_btn.setEnabled(False)
        
        def test_thread():
            try:
                response = self.session.get(f"{self.base_url}/", timeout=5)
                print(f"🔧🔧🔧 CONNECTION TEST: {response.status_code}")
                self.status_label.setText("✅ Server is reachable!")
            except requests.exceptions.ConnectionError:
                print("🔧🔧🔧 CONNECTION FAILED!")
                self.status_label.setText("❌ Cannot connect to server!")
            except Exception as e:
                print(f"🔧🔧🔧 CONNECTION ERROR: {e}")
                self.status_label.setText(f"❌ Connection error: {str(e)[:50]}")
            finally:
                self.test_btn.setEnabled(True)
                
        threading.Thread(target=test_thread, daemon=True).start()
        
    def do_login(self):
        """Perform login with ULTRA DEBUG"""
        print("🔐🔐🔐 DO_LOGIN FUNCTION CALLED! 🔐🔐🔐")
        logger.info("🔐 do_login function called")
        
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        print(f"🔐🔐🔐 LOGIN ATTEMPT: Username='{username}', Password length={len(password)}")
        logger.info(f"🔐 Login attempt - Username: '{username}', Password length: {len(password)}")
        
        if not username or not password:
            print("🔐🔐🔐 MISSING CREDENTIALS!")
            self.status_label.setText("⚠️ Please enter both username and password")
            return
            
        self.status_label.setText("🔄 Logging in...")
        self.login_btn.setEnabled(False)
        
        def login_thread():
            print("🔍🔍🔍 LOGIN THREAD STARTED! 🔍🔍🔍")
            logger.info("🔍 LOGIN_THREAD starting")
            
            try:
                url = f"{self.base_url}/api/login"
                data = {"username": username, "password": password}
                
                print(f"🔍🔍🔍 MAKING POST TO: {url}")
                print(f"🔍🔍🔍 WITH DATA: {data}")
                logger.info(f"🔍 Making POST to {url}")
                
                response = self.session.post(url, json=data, timeout=10)
                
                print(f"🔍🔍🔍 RESPONSE STATUS: {response.status_code}")
                print(f"🔍🔍🔍 RESPONSE TEXT: {response.text}")
                print(f"🔍🔍🔍 RESPONSE COOKIES: {dict(self.session.cookies)}")
                
                logger.info(f"🔍 Response status: {response.status_code}")
                logger.info(f"🔍 Response text: {response.text}")
                logger.info(f"🔍 Session cookies: {dict(self.session.cookies)}")
                
                if response.status_code == 200:
                    print("✅✅✅ LOGIN SUCCESSFUL! ✅✅✅")
                    logger.info("✅ Login successful!")
                    
                    self.status_label.setText("✅ Login successful!")
                    self.username = username
                    self.password = password
                    
                    print(f"✅✅✅ CREDENTIALS SAVED: {username}")
                    logger.info(f"✅ Credentials saved: {username}")
                    
                    # Force immediate close - multiple methods
                    print("🚪🚪🚪 FORCING DIALOG CLOSE... 🚪🚪🚪")
                    self.accept()  # Direct close
                    self.close()   # Additional close call
                    self.hide()    # Hide as backup
                    
                else:
                    print(f"❌❌❌ LOGIN FAILED: {response.status_code}")
                    logger.error(f"❌ Login failed: {response.status_code} - {response.text}")
                    self.status_label.setText("❌ Login failed. Check credentials.")
                    
            except Exception as e:
                print(f"💥💥💥 LOGIN ERROR: {type(e).__name__}: {e}")
                logger.error(f"💥 Login error: {e}")
                self.status_label.setText(f"💥 Error: {str(e)[:30]}")
            finally:
                print("🔍🔍🔍 LOGIN THREAD FINISHED")
                logger.info("🔍 Login thread finished")
                self.login_btn.setEnabled(True)
                
        threading.Thread(target=login_thread, daemon=True).start()

class CryptoDesktopApp(QMainWindow):
    """Main application class with ULTRA DEBUG"""
    
    def __init__(self):
        super().__init__()
        
        print("🚀🚀🚀 CRYPTO DESKTOP APP CONSTRUCTOR! 🚀🚀🚀")
        logger.info("🚀 CryptoDesktopApp constructor")
        
        self.base_url = "http://127.0.0.1:5010"
        self.session = requests.Session()
        self.is_logged_in = False
        self.username = None
        self.password = None
        self.last_alert_id = 0
        self.shown_notification_ids = set()
        
        print("🚀🚀🚀 BASIC VARS INITIALIZED")
        logger.info("🚀 Basic variables initialized")
        
        # Initialize database
        print("🗄️🗄️🗄️ INITIALIZING DATABASE...")
        self.init_database()
        self.load_last_alert_state()
        
        # Setup system tray
        print("📱📱📱 SETTING UP SYSTEM TRAY...")
        self.setup_system_tray()
        
        # Initialize menu states
        print("📋📋📋 INITIALIZING MENU STATES...")
        self.update_menu_states()
        
        # Start notification poller
        print("🔄🔄🔄 STARTING NOTIFICATION POLLER...")
        logger.info("🔄 Starting notification poller")
        self.poller = NotificationPoller(self)
        self.poller.new_notification.connect(self.handle_notification)
        self.poller.start()
        
        print("🚀🚀🚀 DESKTOP APP FULLY INITIALIZED! 🚀🚀🚀")
        logger.info("🚀 Crypto Desktop App started successfully!")
        
    def init_database(self):
        """Initialize SQLite database"""
        try:
            self.db_path = "crypto_alerts.db"
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER,
                    symbol TEXT,
                    direction TEXT,
                    price REAL,
                    timestamp TEXT,
                    shown INTEGER DEFAULT 0
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            
            print("🗄️🗄️🗄️ DATABASE INITIALIZED")
            logger.info("🗄️ Database initialized")
            
        except Exception as e:
            print(f"💥💥💥 DATABASE ERROR: {e}")
            logger.error(f"💥 Database error: {e}")

    def load_last_alert_state(self):
        """Load last seen notification information from SQLite so we never replay old alerts."""
        try:
            self.shown_notification_ids = set()
            stored_last = None
            max_shown = 0
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Load persisted last alert id if present
            cursor.execute("SELECT value FROM app_state WHERE key = ?", ('last_alert_id',))
            row = cursor.fetchone()
            if row and row[0] is not None:
                try:
                    stored_last = int(row[0])
                except (TypeError, ValueError):
                    logger.warning(f"Invalid last_alert_id in app_state: {row[0]}")
                    stored_last = None
            
            # Build the in-memory cache of known notifications
            cursor.execute("SELECT server_id, shown FROM notifications")
            for server_id, shown in cursor.fetchall():
                if server_id is None:
                    continue
                try:
                    server_id_int = int(server_id)
                except (TypeError, ValueError):
                    logger.debug(f"Skipping non-integer server_id: {server_id}")
                    continue
                
                self.shown_notification_ids.add(server_id_int)
                if shown:
                    max_shown = max(max_shown, server_id_int)
            
            if stored_last is not None:
                self.last_alert_id = stored_last
            elif max_shown:
                self.last_alert_id = max_shown
            elif self.shown_notification_ids:
                self.last_alert_id = max(self.shown_notification_ids)
            else:
                self.last_alert_id = 0
            
            # Ensure anything at or below last_alert_id is marked as shown locally
            if self.last_alert_id:
                cursor.execute(
                    "UPDATE notifications SET shown = 1 WHERE shown = 0 AND server_id <= ?",
                    (self.last_alert_id,)
                )
                conn.commit()
            
            conn.close()
            
            # Persist baseline if it did not exist before
            if stored_last is None and self.last_alert_id:
                self.persist_last_alert_id()
            
            logger.info(f"Loaded last_alert_id={self.last_alert_id}, cached {len(self.shown_notification_ids)} notifications")
        
        except Exception as e:
            logger.error(f"Error loading last alert state: {e}")
            self.last_alert_id = 0
            self.shown_notification_ids = set()
    
    def persist_last_alert_id(self):
        """Persist the latest seen server notification id to disk."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO app_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, ('last_alert_id', str(self.last_alert_id)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to persist last_alert_id: {e}")
    
    def mark_notification_as_shown(self, server_id):
        """Mark a notification as shown/read and persist the state."""
        if server_id is None:
            return
        
        try:
            server_id_int = int(server_id)
        except (TypeError, ValueError):
            logger.warning(f"Cannot mark non-integer notification id as shown: {server_id}")
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE notifications SET shown = 1 WHERE server_id = ?",
                (server_id_int,)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to mark notification {server_id_int} as shown: {e}")
        
        self.shown_notification_ids.add(server_id_int)
        
        if server_id_int > self.last_alert_id:
            self.last_alert_id = server_id_int
            self.persist_last_alert_id()
    
    def save_notification_to_db(self, server_id, symbol, direction, price, timestamp):
        """Save notification to local database"""
        try:
            server_id_int = None
            if server_id is not None:
                try:
                    server_id_int = int(server_id)
                except (TypeError, ValueError):
                    logger.warning(f"Received non-integer server_id when saving notification: {server_id}")
                    server_id_int = None
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if server_id_int is not None:
                cursor.execute(
                    "SELECT shown FROM notifications WHERE server_id = ?",
                    (server_id_int,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    cursor.execute("""
                        UPDATE notifications
                        SET symbol = ?, direction = ?, price = ?, timestamp = ?
                        WHERE server_id = ?
                    """, (symbol, direction, price, timestamp, server_id_int))
                else:
                    cursor.execute("""
                        INSERT INTO notifications (server_id, symbol, direction, price, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    """, (server_id_int, symbol, direction, price, timestamp))
            else:
                cursor.execute("""
                    INSERT INTO notifications (server_id, symbol, direction, price, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (server_id_int, symbol, direction, price, timestamp))
            
            conn.commit()
            conn.close()
            
            print(f"💾💾💾 SAVED NOTIFICATION TO DB: {symbol} {direction}")
            logger.info(f"💾 Saved notification to database: {symbol} {direction}")
            
        except Exception as e:
            print(f"💥💥💥 DB SAVE ERROR: {e}")
            logger.error(f"💥 Database save error: {e}")
    
    def setup_system_tray(self):
        """Setup system tray icon"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("❌❌❌ SYSTEM TRAY NOT AVAILABLE!")
            logger.error("❌ System tray not available")
            return
            
        # Create tray icon
        self.tray_icon = QSystemTrayIcon(self)
        
        # Set Bitcoin icon
        try:
            if os.path.exists('bitcoin_icon.ico'):
                icon = QIcon('bitcoin_icon.ico')
                self.tray_icon.setIcon(icon)
                print("🪙🪙🪙 USING BITCOIN ICON")
            else:
                # Fallback to default icon
                self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
                print("⚠️⚠️⚠️ USING DEFAULT ICON (bitcoin_icon.ico not found)")
        except Exception as e:
            print(f"❌❌❌ ICON ERROR: {e}")
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        
        # Create menu
        self.tray_menu = QMenu()
        
        # Login action
        self.login_action = self.tray_menu.addAction("🔐 Login")
        self.login_action.triggered.connect(self.show_login_dialog)
        
        # Logout action
        self.logout_action = self.tray_menu.addAction("� Logout")
        self.logout_action.triggered.connect(self.logout)
        self.logout_action.setEnabled(False)  # Initially disabled
        
        # Separator
        self.tray_menu.addSeparator()
        
        # Show notifications action
        notifications_action = self.tray_menu.addAction("📋 Show Notifications")
        notifications_action.triggered.connect(self.show_notifications_window)
        
        # Settings action
        settings_action = self.tray_menu.addAction("⚙️ Settings")
        settings_action.triggered.connect(self.show_settings_dialog)
        
        # Force fetch action
        fetch_action = self.tray_menu.addAction("� Force Fetch Notifications")
        fetch_action.triggered.connect(self.debug_fetch_notifications)
        
        # Quit action
        quit_action = self.tray_menu.addAction("❌ Exit")
        quit_action.triggered.connect(self.quit_application)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.setToolTip("Crypto Desktop App")
        self.tray_icon.show()
        
        print("📱📱📱 SYSTEM TRAY SETUP COMPLETE")
        logger.info("📱 System tray initialized")
        
    def show_login_dialog(self):
        """Show the login dialog with ULTRA DEBUG"""
        try:
            print("🔐🔐🔐 SHOWING LOGIN DIALOG! 🔐🔐🔐")
            logger.info("🔐 Showing login dialog")
            
            dialog = LoginDialog(parent=None, base_url=self.base_url)
            
            print("🔐🔐🔐 DIALOG CREATED, WAITING FOR USER...")
            logger.info("🔐 Login dialog created, waiting for user")
            
            result = dialog.exec_()
            print(f"🔐🔐🔐 DIALOG RESULT: {result} (Accepted={QDialog.Accepted})")
            
            if result == QDialog.Accepted:
                print("🔐🔐🔐 LOGIN DIALOG ACCEPTED!")
                logger.info("🔐 Login dialog accepted")
                
                # Transfer session data
                print("🔄🔄🔄 TRANSFERRING SESSION DATA...")
                logger.info("🔄 Transferring session data")
                
                print(f"🔄🔄🔄 BEFORE TRANSFER - is_logged_in: {self.is_logged_in}")
                print(f"🔄🔄🔄 DIALOG USERNAME: {dialog.username}")
                print(f"🔄🔄🔄 DIALOG PASSWORD LENGTH: {len(dialog.password)}")
                print(f"🔄🔄🔄 DIALOG SESSION COOKIES: {dict(dialog.session.cookies)}")
                
                self.username = dialog.username
                self.password = dialog.password
                self.session = dialog.session
                self.is_logged_in = True
                
                print(f"✅✅✅ SESSION TRANSFER COMPLETE!")
                print(f"✅✅✅ Username: {self.username}")
                print(f"✅✅✅ is_logged_in: {self.is_logged_in}")
                print(f"✅✅✅ Session cookies: {dict(self.session.cookies)}")
                
                # Verify session immediately
                print("🧪🧪🧪 TESTING SESSION IMMEDIATELY...")
                try:
                    test_response = self.session.get(f"{self.base_url}/api/notifications", timeout=5)
                    print(f"🧪🧪🧪 IMMEDIATE TEST STATUS: {test_response.status_code}")
                    if test_response.status_code == 200:
                        test_data = test_response.json()
                        print(f"🧪🧪🧪 IMMEDIATE TEST SUCCESS: {len(test_data)} notifications")
                    else:
                        print(f"🧪🧪🧪 IMMEDIATE TEST FAILED: {test_response.text}")
                except Exception as e:
                    print(f"🧪🧪🧪 IMMEDIATE TEST ERROR: {e}")
                
                logger.info(f"✅ Session transfer complete - User: {self.username}")
                logger.info(f"✅ is_logged_in: {self.is_logged_in}")
                logger.info(f"✅ Session cookies: {list(self.session.cookies.keys())}")
                
                # Update menu states
                self.update_menu_states()
                
                # Update tooltip with portfolio info
                self.update_portfolio_tooltip()
                
                self.tray_icon.showMessage(
                    "Login Successful",
                    f"Logged in as {self.username}",
                    QSystemTrayIcon.Information,
                    3000
                )
                
            else:
                print("🔐🔐🔐 LOGIN DIALOG CANCELLED!")
                logger.info("🔐 Login dialog cancelled")
                
        except Exception as e:
            print(f"💥💥💥 LOGIN DIALOG ERROR: {e}")
            logger.error(f"💥 Login dialog error: {e}")
    
    def fetch_notifications(self):
        """Fetch notifications with ULTRA DEBUG"""
        try:
            print("📡📡📡 FETCH_NOTIFICATIONS CALLED! 📡📡📡")
            logger.info("📡 fetch_notifications called")
            
            endpoint = f"{self.base_url}/api/notifications"
            
            print(f"📡📡📡 ENDPOINT: {endpoint}")
            print(f"📡📡📡 SESSION EXISTS: {self.session is not None}")
            print(f"📡📡📡 COOKIES: {dict(self.session.cookies) if self.session else 'NO SESSION'}")
            print(f"📡📡📡 LAST_ALERT_ID: {self.last_alert_id}")
            
            logger.info(f"📡 Fetching from: {endpoint}")
            logger.info(f"📡 Session cookies: {dict(self.session.cookies) if self.session else 'No session'}")
            
            response = self.session.get(endpoint, timeout=10)
            
            print(f"📡📡📡 RESPONSE STATUS: {response.status_code}")
            print(f"📡📡📡 RESPONSE SIZE: {len(response.text)} chars")
            
            logger.info(f"📡 Response status: {response.status_code}")
            
            if response.status_code == 200:
                notifications = response.json()
                print(f"✅✅✅ GOT {len(notifications)} TOTAL NOTIFICATIONS!")
                logger.info(f"✅ Received {len(notifications)} notifications")
                
                # Show sample notifications
                if notifications:
                    print("📋📋📋 SAMPLE NOTIFICATIONS:")
                    for i, notif in enumerate(notifications[-3:]):
                        print(f"  [{i}] ID:{notif.get('id')} {notif.get('symbol')} {notif.get('direction')}")
                
                # Filter for new notifications
                new_notifications = []
                for notif in notifications:
                    raw_notif_id = notif.get('id')
                    try:
                        notif_id = int(raw_notif_id)
                    except (TypeError, ValueError):
                        notif_id = None
                    
                    if notif_id is not None:
                        if notif_id in self.shown_notification_ids:
                            print(f"⏭️⏭️⏭️ SKIPPING ALREADY SHOWN NOTIFICATION ID {notif_id}")
                            continue
                        if notif_id <= self.last_alert_id:
                            print(f"⏭️⏭️⏭️ SKIPPING ID {notif_id} <= last_alert_id {self.last_alert_id}")
                            continue
                        self.last_alert_id = max(self.last_alert_id, notif_id)
                        print(f"🆕🆕🆕 NEW NOTIFICATION: ID {notif_id}")
                    else:
                        print(f"🆕🆕🆕 NEW NOTIFICATION WITHOUT ID: {notif}")
                    
                    new_notifications.append(notif)
                
                print(f"🆕🆕🆕 RETURNING {len(new_notifications)} NEW NOTIFICATIONS")
                logger.info(f"🆕 Returning {len(new_notifications)} new notifications")
                
                return new_notifications
                
            elif response.status_code == 401:
                print("🔒🔒🔒 UNAUTHORIZED - SESSION EXPIRED!")
                logger.warning("🔒 Unauthorized - session expired")
                self.is_logged_in = False
                return []
            else:
                print(f"❌❌❌ FETCH FAILED: {response.status_code}")
                logger.error(f"❌ Fetch failed: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"💥💥💥 FETCH ERROR: {type(e).__name__}: {e}")
            logger.error(f"💥 Fetch error: {e}")
            return []
    
    def debug_fetch_notifications(self):
        """Debug fetch notifications manually"""
        print("🔧🔧🔧 DEBUG FETCH NOTIFICATIONS CALLED! 🔧🔧🔧")
        logger.info("🔧 Debug fetch notifications")
        
        try:
            print(f"🔧🔧🔧 LOGIN STATUS: {self.is_logged_in}")
            print(f"🔧🔧🔧 USERNAME: {self.username}")
            print(f"🔧🔧🔧 SESSION: {self.session is not None}")
            
            if not self.is_logged_in:
                print("❌❌❌ NOT LOGGED IN!")
                message = "❌ You must login first!\n\nCurrent status:\n"
                message += f"- is_logged_in: {self.is_logged_in}\n"
                message += f"- username: {self.username}\n"
                message += f"- session: {self.session is not None}"
                
                QMessageBox.warning(self, "Not Logged In", message)
                return
            
            notifications = self.fetch_notifications()
            
            print(f"🔧🔧🔧 DEBUG FETCH GOT: {len(notifications)} notifications")
            
            message = f"Debug Fetch Results:\n\n"
            message += f"✅ Logged in as: {self.username}\n"
            message += f"✅ Session active: {self.session is not None}\n"
            message += f"✅ Found {len(notifications)} new notifications\n\n"
            
            if notifications:
                message += "Recent notifications:\n"
                for notif in notifications[-5:]:
                    symbol = notif.get('symbol', 'Unknown')
                    direction = notif.get('direction', 'Unknown')
                    notif_id = notif.get('id', 'Unknown')
                    message += f"• ID {notif_id}: {symbol} {direction}\n"
            else:
                message += "No new notifications found."
            
            QMessageBox.information(self, "Debug Fetch Results", message)
            
        except Exception as e:
            print(f"💥💥💥 DEBUG FETCH ERROR: {e}")
            logger.error(f"💥 Debug fetch error: {e}")
            QMessageBox.critical(self, "Debug Fetch Error", f"Error: {e}")
    
    def handle_notification(self, notification):
        """Handle incoming notification"""
        try:
            print(f"📢📢📢 HANDLING NOTIFICATION: {notification}")
            logger.info(f"📢 Handling notification: {notification}")
            
            symbol = notification.get('symbol', 'Unknown')
            direction = notification.get('direction', 'Unknown')
            price = notification.get('current_price', 0)
            timestamp = notification.get('date', '') + ' ' + notification.get('time', '')
            table_type = notification.get('table_type', 'unknown')
            print(f"[DEBUG] Notification table_type: {table_type}")
            logger.info(f"[DEBUG] Notification table_type: {table_type}")
            # Save to local database
            self.save_notification_to_db(notification.get('id'), symbol, direction, price, timestamp)
            # Show desktop notification for ALL notification types (portfolio, watchlist, etc)
            title = f"Crypto Alert: {symbol}"
            if table_type == 'watchlist':
                message = f"[WATCHLIST] {symbol} {direction} alert"
            elif table_type == 'coin' or table_type == 'portfolio':
                message = f"[PORTFOLIO] {symbol} {direction} alert"
            else:
                message = f"{symbol} is moving {direction}"
            if price:
                message += f" (${price})"
            self.tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.Information,
                5000
            )
            print(f"📢📢📢 DESKTOP NOTIFICATION SHOWN: {title} | {message}")
            logger.info(f"📢 Desktop notification shown: {title} | {message}")
            
            self.mark_notification_as_shown(notification.get('id'))
        except Exception as e:
            print(f"💥💥💥 NOTIFICATION HANDLING ERROR: {e}")
            logger.error(f"💥 Notification handling error: {e}")
    
    def quit_application(self):
        """Quit the application"""
        print("🛑🛑🛑 QUITTING APPLICATION")
        logger.info("🛑 Application exit requested")
        self.poller.stop()
        QApplication.quit()

    def logout(self):
        """Logout and clear session"""
        print("🚪🚪🚪 LOGOUT CALLED")
        logger.info("🚪 Logout requested")
        
        self.is_logged_in = False
        self.username = None
        self.password = None
        self.session = requests.Session()  # New clean session
        
        # Update menu states
        self.update_menu_states()
        
        # Update tooltip
        self.tray_icon.setToolTip("Crypto Desktop - Not logged in")
        
        self.tray_icon.showMessage(
            "Logged Out",
            "Successfully logged out",
            QSystemTrayIcon.Information,
            2000
        )
        
        print("✅✅✅ LOGOUT COMPLETE")
        logger.info("✅ Logout complete")
    
    def update_menu_states(self):
        """Update menu item states based on login status"""
        self.login_action.setEnabled(not self.is_logged_in)
        self.logout_action.setEnabled(self.is_logged_in)
    
    def update_portfolio_tooltip(self):
        """Update tray icon tooltip with portfolio info"""
        try:
            if self.is_logged_in:
                # Get portfolio value from server
                response = self.session.get(f"{self.base_url}/api/portfolio_value", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    total_value = data.get('total_value', 0)
                    tooltip = f"Crypto Desktop - {self.username}\nPortfolio: ${total_value:,.2f}"
                else:
                    tooltip = f"Crypto Desktop - {self.username}\nPortfolio: Unable to fetch"
            else:
                tooltip = "Crypto Desktop - Not logged in"
                
            self.tray_icon.setToolTip(tooltip)
            
        except Exception as e:
            logger.error(f"Error updating portfolio tooltip: {e}")
            tooltip = f"Crypto Desktop - {self.username}" if self.is_logged_in else "Crypto Desktop - Not logged in"
            self.tray_icon.setToolTip(tooltip)
    
    def show_notifications_window(self):
        """Show notifications history window"""
        print("📋📋📋 SHOW NOTIFICATIONS WINDOW CALLED")
        
        # Create notifications window
        notifications_window = QDialog(self)
        notifications_window.setWindowTitle("Crypto Notifications History")
        notifications_window.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout(notifications_window)
        
        # Title label
        title_label = QLabel("Notifications History")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        layout.addWidget(title_label)
        
        # Notifications list
        self.notifications_list = QListWidget()
        self.notifications_list.setStyleSheet("""
            QListWidget {
                background-color: #f5f5f5;
                border: 1px solid #ccc;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #ddd;
            }
            QListWidget::item:selected {
                background-color: #007acc;
                color: white;
            }
        """)
        layout.addWidget(self.notifications_list)
        
        # Load notifications from database
        self.load_notifications_list()
        
        # Clear all button
        clear_button = QPushButton("🗑️ Clear All Notifications")
        clear_button.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        clear_button.clicked.connect(self.clear_all_notifications)
        layout.addWidget(clear_button)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        close_button.clicked.connect(notifications_window.close)
        layout.addWidget(close_button)
        
        notifications_window.exec_()
    
    def load_notifications_list(self):
        """Load notifications from database into list widget"""
        try:
            self.notifications_list.clear()
            
            # Get notifications from local database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT symbol, direction, price, timestamp, id 
                FROM notifications 
                ORDER BY id DESC 
                LIMIT 100
            """)
            
            notifications = cursor.fetchall()
            
            if notifications:
                for symbol, direction, price, timestamp, notif_id in notifications:
                    item_text = f"ID {notif_id}: {symbol} {direction} - ${price} at {timestamp}"
                    self.notifications_list.addItem(item_text)
            else:
                self.notifications_list.addItem("No notifications found")
                
            conn.close()
            
        except Exception as e:
            logger.error(f"Error loading notifications: {e}")
            self.notifications_list.addItem(f"Error loading notifications: {e}")
    
    def clear_all_notifications(self):
        """Clear all notifications from database"""
        reply = QMessageBox.question(
            self, 
            "Clear All Notifications", 
            "Are you sure you want to clear all notifications?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM notifications")
                conn.commit()
                conn.close()
                
                # Reload the list
                self.load_notifications_list()
                
                QMessageBox.information(self, "Success", "All notifications cleared!")
                
            except Exception as e:
                logger.error(f"Error clearing notifications: {e}")
                QMessageBox.critical(self, "Error", f"Failed to clear notifications: {e}")
    
    def show_settings_dialog(self):
        """Show settings dialog"""
        print("⚙️⚙️⚙️ SHOW SETTINGS DIALOG CALLED")
        
        # Create settings dialog
        settings_dialog = QDialog(self)
        settings_dialog.setWindowTitle("Settings")
        settings_dialog.setGeometry(300, 300, 400, 200)
        
        layout = QVBoxLayout(settings_dialog)
        
        # Title
        title_label = QLabel("Settings")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        layout.addWidget(title_label)
        
        # Server URL setting
        server_layout = QHBoxLayout()
        server_label = QLabel("Server URL:")
        server_label.setMinimumWidth(100)
        self.server_input = QLineEdit()
        self.server_input.setText(self.base_url)
        self.server_input.setPlaceholderText("http://127.0.0.1:5010")
        
        server_layout.addWidget(server_label)
        server_layout.addWidget(self.server_input)
        layout.addLayout(server_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("💾 Save")
        save_button.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        save_button.clicked.connect(lambda: self.save_settings(settings_dialog))
        
        cancel_button = QPushButton("❌ Cancel")
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        cancel_button.clicked.connect(settings_dialog.close)
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        settings_dialog.exec_()
    
    def save_settings(self, dialog):
        """Save settings"""
        new_url = self.server_input.text().strip()
        
        if not new_url:
            QMessageBox.warning(dialog, "Error", "Server URL cannot be empty!")
            return
        
        if not new_url.startswith('http'):
            new_url = 'http://' + new_url
        
        self.base_url = new_url
        
        # Test connection to new server
        try:
            test_response = requests.get(new_url, timeout=5)
            if test_response.status_code == 200:
                QMessageBox.information(dialog, "Success", f"Settings saved!\nServer: {new_url}")
                dialog.close()
                
                # If logged in, logout since server changed
                if self.is_logged_in:
                    self.logout()
                    QMessageBox.information(self, "Logged Out", "Server changed - please login again")
                    
            else:
                QMessageBox.warning(dialog, "Warning", f"Server responded with status {test_response.status_code}\nSettings saved but server may not be working.")
                dialog.close()
                
        except Exception as e:
            QMessageBox.warning(dialog, "Warning", f"Cannot connect to server: {e}\nSettings saved but please check the URL.")
            dialog.close()

def main():
    """Main function"""
    print("🚀🚀🚀 MAIN FUNCTION CALLED! 🚀🚀🚀")
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("❌❌❌ SYSTEM TRAY NOT AVAILABLE!")
        QMessageBox.critical(None, "System Tray", 
                           "System tray is not available on this system.")
        sys.exit(1)
    
    print("🚀🚀🚀 CREATING CRYPTO DESKTOP APP...")
    crypto_app = CryptoDesktopApp()
    
    print("🚀🚀🚀 SHOWING LOGIN DIALOG...")
    crypto_app.show_login_dialog()
    
    print("🚀🚀🚀 STARTING EVENT LOOP...")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
