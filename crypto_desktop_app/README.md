# Crypto Alerts Desktop App

A Windows desktop application that receives crypto alerts from your Crypto Alert App server.

## Features

- System tray notification app with Bitcoin icon
- Real-time crypto alerts and notifications
- Notifications history window
- Settings dialog for server configuration
- Portfolio value tooltip
- Local SQLite database for notification storage
- Login/logout state management

## Building the Windows Executable

1. Install Python 3.x on Windows
2. Install required packages:
   ```
   pip install pyqt5 plyer requests
   ```
3. Run the build script:
   ```
   python build.py
   ```
   Or use the batch file:
   ```
   build.bat
   ```

This will create a Windows executable in the `dist/` folder that can be distributed without requiring Python to be installed.

## Files

- `main.py` - Main application code (978 lines)
- `build.py` - Build script for creating Windows executable
- `build.bat` - Windows batch file to run the build
- `bitcoin_icon.ico` - Bitcoin icon for system tray
- `README.md` - This documentation

## Usage

1. Run the executable
2. Right-click the Bitcoin icon in the system tray
3. Use "Login" to connect to your crypto server
4. View notifications history, settings, and portfolio value from the menu
5. Notifications will appear as Windows toast notifications

The app polls the server every 15 seconds for new alerts when logged in.
