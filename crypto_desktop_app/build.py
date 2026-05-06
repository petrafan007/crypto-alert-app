#!/usr/bin/env python3
"""
Build Script for Crypto Desktop App
Creates a single EXE file
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def run_command(cmd, description):
    """Run command with error handling"""
    print(f"\n🔧 {description}")
    print(f"Command: {cmd}")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            return True
        else:
            print(f"❌ {description} - FAILED")
            print("STDERR:", result.stderr)
            return False
            
    except Exception as e:
        print(f"💥 {description} - EXCEPTION: {e}")
        return False

def clean_build():
    """Clean previous builds"""
    print("🧹 Cleaning previous builds...")
    
    dirs_to_clean = ['build', 'dist', '__pycache__']
    files_to_clean = ['*.spec']
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"   Removed {dir_name}/")
    
    for file_pattern in files_to_clean:
        for file_path in Path('.').glob(file_pattern):
            file_path.unlink()
            print(f"   Removed {file_path}")

def install_dependencies():
    """Install required packages"""
    packages = ['PyQt5', 'requests', 'PyInstaller']
    
    for package in packages:
        success = run_command(f'pip install {package}', f'Installing {package}')
        if not success:
            print(f"⚠️ Failed to install {package}")

def build_exe():
    """Build the EXE"""
    pyinstaller_cmd = [
        'pyinstaller',
        '--onefile',
        '--windowed',
        '--name=CryptoDesktop',
        '--clean',
        '--noconfirm',
        '--icon=bitcoin_icon.ico',
        '--add-data=bitcoin_icon.ico;.',
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui', 
        '--hidden-import=PyQt5.QtWidgets',
        '--hidden-import=requests',
        '--hidden-import=sqlite3',
        'main.py'
    ]
    
    cmd = ' '.join(pyinstaller_cmd)
    return run_command(cmd, "Building EXE with PyInstaller")

def verify_exe():
    """Verify the EXE was created"""
    exe_path = Path('dist/CryptoDesktop.exe')
    
    if exe_path.exists():
        size = exe_path.stat().st_size / (1024 * 1024)
        print(f"✅ EXE created successfully!")
        print(f"   Path: {exe_path.absolute()}")
        print(f"   Size: {size:.1f} MB")
        return True
    else:
        print("❌ EXE not found in dist/ directory")
        return False

def main():
    """Main build process"""
    print("🚀 CRYPTO DESKTOP APP BUILDER")
    print("=" * 40)
    
    if not os.path.exists('main.py'):
        print("❌ main.py not found!")
        return False
    
    clean_build()
    install_dependencies()
    
    success = build_exe()
    
    if success and verify_exe():
        print("\n🎉 BUILD COMPLETED SUCCESSFULLY!")
        print("\nRun: dist/CryptoDesktop.exe")
        return True
    else:
        print("\n❌ BUILD FAILED!")
        return False

if __name__ == "__main__":
    main()
