@echo off
echo ===============================
echo CRYPTO DESKTOP APP BUILDER
echo ===============================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

echo Building Crypto Desktop App...
python build.py

pause
