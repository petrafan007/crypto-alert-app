import os
import sys
import subprocess

def bootstrap():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(base_dir, '.venv')
    if sys.prefix == sys.base_prefix:
        if not os.path.exists(venv_dir):
            subprocess.check_call([sys.executable, '-m', 'venv', venv_dir])
        venv_python = os.path.join(venv_dir, 'Scripts', 'python.exe') if os.name == 'nt' else os.path.join(venv_dir, 'bin', 'python3')
        os.execv(venv_python, [venv_python] + sys.argv)
        sys.exit(0)
    try:
        import flask, flask_sqlalchemy, flask_login, binance, psycopg2, dotenv
    except ImportError:
        requirements_file = os.path.join(base_dir, 'requirements.txt')
        if os.path.exists(requirements_file):
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', requirements_file])
            os.execv(sys.executable, [sys.executable] + sys.argv)
            sys.exit(0)

# Run bootstrap immediately before any third-party imports
bootstrap()

from dotenv import load_dotenv
load_dotenv(override=True)

if __name__ == "__main__":
    pass  # Bootstrap already ran above

from flask import send_file, make_response
from typing import List
from pathlib import Path
from transaction_utils import recalculate_asset_activity
from credential_security import (
    decrypt_secret,
    EncryptionKeyError,
    is_encryption_available,
    is_persisted_key_available,
    normalize_secret_for_storage,
    persist_encryption_key,
)
# Safe import for PyJWT used by extension helpers
try:
    import jwt  # PyJWT
except Exception:
    jwt = None

# Safe import for Flask-Login 
try:
    from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
except Exception:
    # Create stub decorators if flask_login not available yet
    def login_required(f):
        return f
    current_user = None
    UserMixin = object
    LoginManager = object

# Minimal stub so early @app.route decorators don't fail before Flask app is created
if 'app' not in globals():
    class _AppStub:
        def route(self, *args, **kwargs):
            def _decorator(func):
                return func
            return _decorator
    app = _AppStub()

# Helper: create JWT for extension

def create_extension_jwt(user):
    if not jwt:
        raise RuntimeError("PyJWT not installed. Please add PyJWT to requirements and install.")
    payload = {
        "sub": user.id,
        "username": user.username,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow(),
        "scope": "extension"
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm="HS256")
    # PyJWT>=2 returns str; ensure str
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

# Helper: get user from Authorization: Bearer token

def get_user_from_bearer():
    if not jwt:
        raise RuntimeError("PyJWT not installed. Please add PyJWT to requirements and install.")
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth.split(' ', 1)[1].strip()
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        if data.get("scope") != "extension":
            return None
        user_id = data.get('sub')
        return db.session.get(User, user_id)
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        return None

def get_user_from_desktop_session():
    """Get user from desktop app session token (JWT-based)"""
    token = None
    
    # Extract token from Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
    
    if not token:
        logger.warning("No session token provided for desktop authentication")
        return None
    
    try:
        import jwt
        from credentials import User as CredUser
        
        # Decode JWT token
        secret_key = app.config.get('SECRET_KEY', 'desktop-app-secret-key')
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        
        # Verify it's a desktop session token
        if payload.get('type') != 'desktop_session':
            logger.warning("Invalid token type for desktop authentication")
            return None
        
        user_id = payload.get('user_id')
        username = payload.get('username')
        
        if not user_id or not username:
            logger.warning("Invalid token payload for desktop authentication")
            return None
        
        with app.app_context():
            # Get user from credentials database
            cred_user = CredUser.query.get(user_id)
            if not cred_user or cred_user.username != username:
                logger.error(f"No user found for desktop session token user_id: {user_id}")
                return None
            
            # Create a simple user object that matches what the rest of the app expects
            class DesktopUser:
                def __init__(self, cred_user):
                    self.id = cred_user.id
                    self.username = cred_user.username
                    self.email = getattr(cred_user, 'email', '')
            
            return DesktopUser(cred_user)
            
    except jwt.ExpiredSignatureError:
        logger.warning("Desktop session token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid desktop session token: {e}")
        return None
    except Exception as e:
        logger.error(f"Desktop session authentication error: {e}")
        return None

def get_user_from_desktop_token():
    """Get user from desktop app token (long-lived, non-JWT)"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth.split(' ', 1)[1].strip()
    
    try:
        from credentials import DesktopToken, User as CredUser
        with app.app_context():
            # Find active token
            desktop_token = DesktopToken.query.filter_by(token=token, is_active=True).first()
            if not desktop_token:
                logger.warning(f"Invalid or inactive desktop token: {token[:8]}...")
                return None
                
            # Update last_used timestamp
            desktop_token.last_used = datetime.now()
            db.session.commit()
            
            # Get user from credentials database
            cred_user = CredUser.query.get(desktop_token.user_id)
            if not cred_user:
                logger.error(f"No user found for desktop token user_id: {desktop_token.user_id}")
                return None
                
            # Create compatible user object for main app (using credentials User model)
            return cred_user
    except Exception as e:
        logger.error(f"Desktop token authentication error: {e}")
        return None

# Extension login endpoint (JWT)
@app.route('/api/extension/login', methods=['POST'])
def extension_login():
    try:
        body = request.get_json(force=True, silent=True) or {}
        username = body.get('username', '').strip()
        password = body.get('password', '')
        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return jsonify({"error": "Invalid credentials"}), 401
        token = create_extension_jwt(user)
        return jsonify({
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": 24*3600,
            "user_id": user.id,
            "username": user.username
        })
    except Exception as e:
        logger.error(f"extension_login error: {e}")
        return jsonify({"error": "Internal error"}), 500

@app.route('/api/desktop/login', methods=['POST'])
def desktop_login():
    """Login endpoint for desktop app using username/password"""
    try:
        from datetime import datetime, timedelta
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400
        
        # Import User model from credentials
        from credentials import User as CredUser
        
        with app.app_context():
            # Find user in credentials database
            user = CredUser.query.filter_by(username=username).first()
            
            if not user:
                logger.warning(f"Desktop login attempt with invalid username: {username}")
                return jsonify({"error": "Invalid credentials"}), 401
            
            # Verify password using hashed credentials
            if not user.check_password(password):
                logger.warning(f"Desktop login attempt with invalid password for user: {username}")
                return jsonify({"error": "Invalid credentials"}), 401
            
            # Generate a session token (simple approach)
            import secrets
            session_token = secrets.token_urlsafe(32)
            
            # For simplicity, we'll create a temporary JWT-like token
            # In production, you might want to store these in a sessions table
            user_data = {
                "user_id": user.id,
                "username": user.username,
                "session_token": session_token,
                "login_time": datetime.now().isoformat()
            }
            
            # Store session in a simple way (you might want to use Redis or database)
            # For now, we'll just create a simple token that includes user info
            import jwt
            
            # Create JWT token with user info
            payload = {
                "user_id": user.id,
                "username": user.username,
                "exp": datetime.utcnow() + timedelta(days=30),  # 30 day expiration
                "type": "desktop_session"
            }
            
            # Use a simple secret key (in production, use a proper secret)
            secret_key = app.config.get('SECRET_KEY', 'desktop-app-secret-key')
            token = jwt.encode(payload, secret_key, algorithm='HS256')
            
            logger.info(f"Desktop login successful for user: {username}")
            
            return jsonify({
                "success": True,
                "session_token": token,
                "username": user.username,
                "message": "Login successful"
            })
            
    except Exception as e:
        logger.error(f"Desktop login error: {e}")
        return jsonify({"error": "Login failed"}), 500

# Desktop app token management endpoints
@app.route('/api/desktop/generate-token', methods=['POST'])
@login_required
def generate_desktop_token():
    """Generate long-lived token for desktop app"""
    try:
        import secrets
        from credentials import DesktopToken
        
        # Generate secure token
        token = secrets.token_urlsafe(32)
        device_name = request.json.get('device_name', 'Desktop App') if request.json else 'Desktop App'

        # Desktop app token management endpoints
        
        with app.app_context():
            # Deactivate old tokens for this user (optional - keep only one active)
            DesktopToken.query.filter_by(user_id=current_user.id).update({'is_active': False})
            
            # Create new token
            desktop_token = DesktopToken(
                user_id=current_user.id,
                token=token,
                device_name=device_name,
                is_active=True
            )
            db.session.add(desktop_token)
            db.session.commit()
            
        logger.info(f"Generated desktop token for user {current_user.username}")
        return jsonify({
            "token": token,
            "device_name": device_name,
            "created_at": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"generate_desktop_token error: {e}")
        return jsonify({"error": "Internal error"}), 500

@app.route('/api/desktop/notifications')
def api_desktop_notifications():
    """Desktop app specific notification endpoint with session-based auth"""
    user = get_user_from_desktop_session()
    if not user:
        return jsonify({"error": "Invalid or missing session token"}), 401
        
    try:
        since_id = request.args.get('since_id', type=int, default=0)
        limit = request.args.get('limit', default=50, type=int)
        
        # Get notifications using existing logic but for desktop app
        q = Notification.query.filter_by(user_id=user.id)
        q = q.filter(text('(is_hidden IS NULL OR is_hidden = 0)'))  # Exclude hidden
        if since_id:
            q = q.filter(Notification.id > since_id)
        q = q.order_by(Notification.id.desc())
        rows = q.limit(max(1, min(limit, 100))).all()
        
        # Format notifications for desktop app
        notifications = []
        for n in rows:
            notifications.append({
                "id": n.id,
                "user_id": n.user_id,
                "coin_id": n.coin_id,
                "table_type": n.table_type,
                "category": getattr(n, "category", "price_alert"),
                "symbol": n.symbol,
                "date": n.date,
                "time": n.time,
                "crossing_price": n.crossing_price,
                "current_price": n.current_price,
                "direction": n.direction,
                "threshold_type": n.threshold_type,
                "percent_value": n.percent_value,
                "message": getattr(n, "message", None),
                "created_at": n.created_at.isoformat() if n.created_at else None
            })
        
        # Get desktop-specific user settings
        desktop_settings = {
            "notification_sound": True,
            "poll_interval": 60,
            "show_system_notifications": True
        }
        
        return jsonify({
            "notifications": notifications,
            "user_settings": desktop_settings,
            "server_time": datetime.utcnow().isoformat(),
            "total_count": len(notifications)
        })
        
    except Exception as e:
        logger.error(f"api_desktop_notifications error: {e}")
        return jsonify({"error": "Internal error"}), 500

@app.route('/api/desktop/check-update', methods=['GET'])
def check_desktop_update():
    """Check if desktop app updates are available"""
    user = get_user_from_desktop_session()
    if not user:
        return jsonify({"error": "Invalid or expired session token"}), 401
    
    try:
        current_version = request.args.get('current_version', '1.0.0')
        
        # Define the latest version and release info
        # This should be updated when you release new versions
        latest_version = "1.1.0"
        release_notes = """
New Features:
• Improved Windows toast notifications
• Better error handling and logging
• Auto-update system
• Enhanced system tray menu

Bug Fixes:
• Fixed notification deduplication
• Improved API token handling
• Better Windows startup integration
"""
        
        # Simple version comparison (you might want to use semantic versioning)
        update_available = current_version != latest_version
        
        response_data = {
            "update_available": update_available,
            "current_version": current_version,
            "latest_version": latest_version
        }
        
        if update_available:
            response_data.update({
                "version": latest_version,
                "release_notes": release_notes.strip(),
                "download_url": f"{request.url_root}api/desktop/download-update",
                "file_hash": "sha256_hash_would_go_here",  # You'd compute this for the actual file
                "file_size": 15728640,  # Example file size in bytes
                "release_date": "2025-09-11T12:00:00Z"
            })
        
        logger.info(f"Update check for user {user.username}: {current_version} -> {latest_version} (available: {update_available})")
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"check_desktop_update error: {e}")
        return jsonify({"error": "Failed to check for updates"}), 500

@app.route('/api/desktop/download-update', methods=['GET'])
def download_desktop_update():
    """Download desktop app update"""
    user = get_user_from_desktop_session()
    if not user:
        return jsonify({"error": "Invalid or expired session token"}), 401
    
    try:
        # Path to the latest desktop app executable
        update_file_path = "/home/jcavallarojr/crypto_alert_app/desktop_app/dist/CryptoDesktopApp.exe"
        
        if not os.path.exists(update_file_path):
            return jsonify({"error": "Update file not found"}), 404
        
        logger.info(f"Serving desktop app update to user {user.username}")
        
        # Serve the file with proper headers
        return send_file(
            update_file_path,
            as_attachment=True,
            download_name="CryptoDesktopApp.exe",
            mimetype="application/octet-stream"
        )
        
    except Exception as e:
        logger.error(f"download_desktop_update error: {e}")
        return jsonify({"error": "Failed to download update"}), 500

# Notifications fetch for extension (keep for backward compatibility)
@app.route('/api/notifications')
def api_notifications():
    user = get_user_from_bearer()
    if not user:
        # Try session cookie auth (for web frontend)
        from flask_login import current_user
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            user = current_user
        else:
            return jsonify({"error": "Unauthorized"}), 401
    try:
        since_id = request.args.get('since_id', type=int)
        limit = request.args.get('limit', default=100, type=int)
        include_hidden = request.args.get('include_hidden', default='0', type=str)
        q = Notification.query.filter_by(user_id=user.id)
        # Exclude hidden by default
        if not (str(include_hidden).lower() in ['1', 'true', 'yes']):
            q = q.filter(text('(is_hidden IS NULL OR is_hidden = 0)'))
        if since_id:
            q = q.filter(Notification.id > since_id)
        q = q.order_by(Notification.id.desc())
        rows = q.limit(max(1, min(limit, 500))).all()
        # Return newest->oldest as received, or reverse to oldest->newest
        rows = list(reversed(rows))
        result = []
        for n in rows:
            result.append({
                "id": n.id,
                "user_id": n.user_id,
                "coin_id": n.coin_id,
                "table_type": n.table_type,
                "category": getattr(n, "category", "price_alert"),
                "symbol": n.symbol,
                "date": n.date,
                "time": n.time,
                "crossing_price": n.crossing_price,
                "current_price": n.current_price,
                "direction": n.direction,
                "threshold_type": n.threshold_type,
                "percent_value": n.percent_value,
                "message": getattr(n, "message", None)
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"api_notifications error: {e}")
        return jsonify({"error": "Internal error"}), 500

# Hide a notification (set is_hidden=1)
@app.route('/api/notifications/<int:notif_id>/hide', methods=['POST'])
def api_hide_notification(notif_id):
    user = get_user_from_bearer()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        engine_main = db.engine
        with engine_main.begin() as conn:
            conn.execute(
                text('UPDATE notifications SET is_hidden = 1 WHERE user_id = :uid AND id = :id'),
                {"uid": user.id, "id": notif_id}
            )
        return jsonify({"success": True, "id": notif_id})
    except Exception as e:
        logger.error(f"api_hide_notification error: {e}")
        return jsonify({"error": "Internal error"}), 500

# Helper to persist a notification record
def save_notification_record(
    user_id,
    coin_id,
    table_type,
    symbol,
    direction,
    threshold_type,
    percent_value,
    crossing_price,
    current_price,
    category='price_alert',
    message=None,
):
    try:
        import pytz
        et = pytz.timezone('US/Eastern')
        now_et = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(et)
        date_str = now_et.strftime('%m-%d-%Y')
        time_str = now_et.strftime('%I:%M:%S %p %Z')
        rec = Notification(
            user_id=user_id,
            coin_id=coin_id,
            table_type=table_type,
            symbol=symbol,
            date=date_str,
            time=time_str,
            crossing_price=float(crossing_price),
            current_price=float(current_price),
            direction=direction,
            threshold_type=threshold_type,
            percent_value=float(percent_value) if percent_value is not None else None,
            category=category,
            message=message
        )
        db.session.add(rec)
        db.session.commit()
        logger.info(f"[NOTIFY] Saved notification {symbol} {direction} {crossing_price} -> {current_price} ({table_type}) for user {user_id}")
        return rec.id
    except Exception as e:
        logger.error(f"Failed to save notification: {e}")
        db.session.rollback()
        return None
import secrets
import requests
import os
import pprint
import re
import traceback
import time
import threading
import math
import numpy as np
import json
from urllib.parse import urlencode
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Thread
from flask import Flask, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from binance.client import Client
from datetime import datetime, timedelta, time as dt_time, timezone
from decimal import Decimal
from collections import defaultdict, deque
import pytz
import uuid
from textblob import TextBlob
from models import Coin, WatchlistCoin, Notification, AIPrompt, AIConversation, StakedCoin, StakingReward, AICache, AIAnalysisSchedule, PriceHistory, DefaultAIPrompt
from credentials import User, Credential, UserSetting, DesktopToken
from trading_models import TestOrder, RealOrder, TestPortfolio, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder
from log import logger
from core.extensions import db

# Eastern Time utility functions
def get_eastern_now():
    """Get current datetime in Eastern Time"""
    et = pytz.timezone('US/Eastern')
    return datetime.now(et)

def get_eastern_datetime(dt=None):
    """Convert datetime to Eastern Time or get current Eastern Time"""
    et = pytz.timezone('US/Eastern')
    if dt is None:
        return datetime.now(et)
    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(et)

def format_eastern_datetime(dt=None, format_str="%Y-%m-%d %H:%M:%S EST"):
    """Format datetime in Eastern Time"""
    eastern_dt = get_eastern_datetime(dt)
    return eastern_dt.strftime(format_str)

def format_eastern_datetime_ampm(dt=None, format_str="%m/%d/%Y %I:%M %p EST"):
    """Format datetime in Eastern Time with AM/PM format"""
    eastern_dt = get_eastern_datetime(dt)
    return eastern_dt.strftime(format_str)

def get_eastern_now_ampm():
    """Get current Eastern time formatted as AM/PM"""
    return format_eastern_datetime_ampm()

def get_eastern_now_iso():
    """Get current Eastern time in ISO format for JavaScript parsing"""
    return get_eastern_now().isoformat()

def _parse_iso(value, default=None):
    """
    Safely parse a datetime or ISO string into an Eastern-aware datetime.
    Returns `default` when parsing fails.
    """
    try:
        if value is None:
            return default

        # Accept already-materialized datetimes
        if isinstance(value, datetime):
            dt_obj = value
        else:
            dt_obj = datetime.fromisoformat(str(value))

        # Assume UTC when tzinfo is missing, then convert to Eastern
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=pytz.utc)

        return dt_obj.astimezone(pytz.timezone('US/Eastern'))
    except Exception as e:
        logger.error(f"Failed to parse datetime value '{value}': {e}")
        return default

# Safe stub to avoid NameError where build_db_context is referenced

# Helper class for Object interactions if not defined
class ObjectView(object):
    def __init__(self, d):
        self.__dict__ = d

def build_db_context(user_id=None, symbol=None, include_portfolio_summary=False):
    """Build database context for AI analysis including portfolio data, watchlist, and transaction history"""
    try:
        if not user_id:
            return "", {}
            
        context_parts = []
        
        # Get concise portfolio context for portfolio review, market analysis, coin analysis
        if include_portfolio_summary:
            try:
                # Get summary data only - much more concise than full context
                crypto_data = get_comprehensive_crypto_data_for_user(user_id, limit_transactions=10, days_history=7)
                
                # Portfolio Summary (very concise)
                summary = crypto_data.get("summary", {})
                if summary and "error" not in summary:
                    context_parts.append("=== PORTFOLIO SUMMARY ===")
                    context_parts.append(f"Total Coins: {summary.get('total_coins', 0)}")
                    context_parts.append(f"Portfolio Value: ${summary.get('total_portfolio_value', 0):,.2f}")
                    context_parts.append(f"P&L: ${summary.get('portfolio_pnl', 0):,.2f} ({summary.get('portfolio_pnl_pct', 0):+.2f}%)")
                
                # Top 5 Holdings Only (concise)
                portfolio = crypto_data.get("portfolio", [])
                if portfolio:
                    context_parts.append("\n=== TOP HOLDINGS ===")
                    sorted_portfolio = sorted(portfolio, key=lambda x: x.get("current_value", 0), reverse=True)
                    
                    for coin in sorted_portfolio[:5]:  # Only top 5 holdings
                        symbol = coin.get("symbol", "N/A")
                        amount = coin.get("amount", 0)
                        current_value = coin.get("current_value", 0)
                        pct_change = coin.get("pct_change", 0)
                        context_parts.append(f"{symbol}: {amount:.4f} = ${current_value:.2f} ({pct_change:+.2f}%)")
                
                # Recent Transactions (last 5 only)
                transactions = crypto_data.get("recent_transactions", [])
                if transactions:
                    context_parts.append("\n=== RECENT ACTIVITY ===")
                    for tx in transactions[:5]:  # Only last 5 transactions
                        date = tx.get("date", "N/A")[:10]  # Date only, no time
                        tx_type = tx.get("type", "N/A")
                        asset = tx.get("asset", "N/A")
                        amount = tx.get("amount", 0)
                        context_parts.append(f"{date}: {tx_type} {abs(amount):.4f} {asset}")
                        
            except Exception as e:
                logger.warning(f"Could not get portfolio summary for user {user_id}: {e}")
                context_parts.append("=== PORTFOLIO SUMMARY ===")
                context_parts.append("Portfolio data temporarily unavailable")
        
        # Concise watchlist (top 3 only)
        try:
            watchlist_coins = WatchlistCoin.query.filter_by(user_id=user_id, hidden=False).limit(3).all()
            if watchlist_coins:
                context_parts.append("\n=== WATCHLIST (TOP 3) ===")
                for coin in watchlist_coins:
                    context_parts.append(f"{coin.symbol}: ${coin.current_price:.4f}")
        except Exception as e:
            logger.warning(f"Could not get watchlist data for user {user_id}: {e}")
        
        # Join all context (should be much shorter now)
        full_context = "\n".join(context_parts) if context_parts else ""
        
        # Limit total context length to prevent token overflow
        if len(full_context) > 2000:  # Max 2000 characters
            full_context = full_context[:1900] + "\n... (truncated for space)"
        
        # Return context and metadata
        context_metadata = {
            "user_id": user_id,
            "symbol": symbol,
            "include_portfolio_summary": include_portfolio_summary,
            "context_length": len(full_context),
            "has_portfolio_data": "PORTFOLIO SUMMARY" in full_context,
            "has_watchlist_data": "WATCHLIST" in full_context
        }
        
        return full_context, context_metadata
        
    except Exception as e:
        logger.error(f"Error building database context for user {user_id}: {e}")
        return f"Database context error: {str(e)}"[:200], {}

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/static', instance_relative_config=True)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

def serve_react_app():
    """Serve the built React index with cache-busting headers so UI updates ship instantly."""
    index_path = Path(app.static_folder or '') / 'index.html'
    logger.info(f"Serving React index from {index_path}")
    try:
        content = index_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        logger.warning("React index file missing, falling back to send_static_file")
        return app.send_static_file('index.html')

    build_token = str(int(index_path.stat().st_mtime))
    logger.info(f"Serving React index with cache-bust token {build_token}")

    def _add_version(match):
        path = match.group(1)
        quote = match.group(2)
        if '?v=' in path:
            return match.group(0)
        return f'{path}?v={build_token}{quote}'

    content = re.sub(r'(/static/[^"\']+)(["\'])', _add_version, content)

    # Embed staking summary for dashboard to avoid CDN-stale API calls
    if current_user and getattr(current_user, 'is_authenticated', False) and request.path in {'/dashboard', '/dashboard.html', '/'}:
        try:
            cred = get_user_credentials(current_user.username)
            prefetch = _build_staking_dashboard_payload(cred)
            import json
            injection = f"<script>window.__STAKING_SUMMARY__={json.dumps(prefetch)};</script>"
            content = content.replace('<div id="root"></div>', f'{injection}<div id="root"></div>')
        except Exception as prefetch_err:
            logger.error(f"Failed to embed staking prefetch: {prefetch_err}", exc_info=True)

    response = make_response(content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Initialize background threads list
background_threads = []

# Start background jobs once (Flask 3.x: use before_request guard instead of before_first_request)
_jobs_started = False
@app.before_request
def _ensure_background_jobs_once():
    global _jobs_started
    if _jobs_started:
        return
    # avoid starting on CORS preflights
    if request.method == 'OPTIONS':
        return
    try:
        start_background_jobs(app)
        _jobs_started = True
    except Exception as e:
        logger.error(f"Failed to start background jobs: {e}")

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql:///cryptoalertapp?host=/var/run/postgresql&port=5433'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 50,
    'max_overflow': 100,
    'pool_recycle': 1800,
    'pool_pre_ping': True
}
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # Keep users logged in for 30 days

# CRITICAL: Teardown handler to prevent connection leaks
@app.teardown_appcontext
def shutdown_session(exception=None):
    """Remove database session after each request to prevent connection leaks."""
    db.session.remove()

@app.after_request
def after_request_cleanup(response):
    """Additional cleanup to ensure sessions are closed after each request."""
    try:
        db.session.commit()
    except:
        db.session.rollback()
    finally:
        db.session.remove()
    return response


# Database initialization is handled by the db instance from database.py

# Session cookie configuration for persistence - FIXED
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = False  # CHANGED: Allow JS access for debugging
app.config['SESSION_COOKIE_SAMESITE'] = None  # CHANGED: Remove SameSite restriction
app.config['SESSION_COOKIE_NAME'] = 'session'  # CHANGED: Use default Flask session name
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['SESSION_COOKIE_DOMAIN'] = None  # Use default domain
app.config['SESSION_COOKIE_MAX_AGE'] = timedelta(days=30).total_seconds()  # ADDED: Explicit max age
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
app.config['REMEMBER_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['REMEMBER_COOKIE_HTTPONLY'] = False  # CHANGED: Allow JS access
app.config['REMEMBER_COOKIE_NAME'] = 'remember_token'  # CHANGED: Use default Flask-Login name

# Configure additional database for credentials
# app.config['SQLALCHEMY_BINDS'] = {
#     'credentials': 'sqlite:////home/jcavallarojr/crypto_alert_app/instance/credentials.db',
#     'ai_conversations': 'sqlite:////home/jcavallarojr/crypto_alert_app/instance/ai_conversations.db',
#     'exchange_logs': 'sqlite:////home/jcavallarojr/crypto_alert_app/instance/exchange_logs.db'
# }

db.init_app(app)

# ====================================================================
# BACKGROUND JOB SESSION MANAGEMENT
# ====================================================================

def safe_background_iteration(func):
    """
    Decorator for background job iterations to ensure database sessions are properly cleaned up.
    Use this to wrap the BODY of while True loops, not the loop itself.
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Rollback any failed transaction
            try:
                db.session.rollback()
            except:
                pass
            raise
        finally:
            # Always clean up session after each iteration
            try:
                db.session.rollback()  # Rollback any uncommitted changes
            except:
                pass
            try:
                db.session.remove()  # Return connection to pool
            except:
                pass
    return wrapper

class BinanceRateLimiter:
    """Circuit breaker and rate limiter for Binance API calls"""
    def __init__(self, interval_seconds=120):
        self.interval = interval_seconds
        self.last_call_times = {}  # {symbol: timestamp}
        self.failure_counts = {}   # {symbol: count}
        self.circuit_open = False
        self.circuit_open_until = None
        
    def can_call(self, symbol):
        """Check if we can call API for this symbol"""
        if self.circuit_open:
            if time.time() < self.circuit_open_until:
                return False
            else:
                # Circuit breaker timeout expired, try again
                self.circuit_open = False
                self.failure_counts.clear()
        
        last_call = self.last_call_times.get(symbol, 0)
        return (time.time() - last_call) >= self.interval
    
    def record_call(self, symbol):
        """Record successful API call"""
        self.last_call_times[symbol] = time.time()
        if symbol in self.failure_counts:
            self.failure_counts[symbol] = 0
    
    def record_failure(self, symbol):
        """Record failed API call and open circuit if needed"""
        self.failure_counts[symbol] = self.failure_counts.get(symbol, 0) + 1
        
        if self.failure_counts[symbol] >= 5:
            # Open circuit breaker for 30 minutes
            self.circuit_open = True
            self.circuit_open_until = time.time() + 1800
            logger.critical(f"🚨 Circuit breaker OPEN for Binance API after {self.failure_counts[symbol]} failures. Cooling down for 30 minutes.")

# Global rate limiter instance
binance_rate_limiter = BinanceRateLimiter(interval_seconds=120)  # 2 minutes

# CORS handling for extension endpoints (no external dependency)
@app.before_request
def _ext_cors_preflight():
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        h = resp.headers
        h['Access-Control-Allow-Origin'] = '*'
        h['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        h['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        return resp

@app.after_request
def _ext_cors_headers(resp):
    try:
        if request.path.startswith('/api/extension') or request.path.startswith('/api/notifications'):
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        if request.path.startswith('/static/assets/'):
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
    except Exception:
        pass
    return resp

# Register extension routes
app.add_url_rule('/api/extension/login', view_func=extension_login, methods=['POST', 'OPTIONS'])
app.add_url_rule('/api/notifications', view_func=api_notifications, methods=['GET', 'OPTIONS'])

# Extension settings endpoints (JWT auth)
def ext_get_settings():
    user = get_user_from_bearer()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        row = UserSetting.query.filter_by(user_id=user.id).first()
        enabled = True if not row else bool(getattr(row, 'browser_notifications_enabled', True))
        return jsonify({"browser_notifications_enabled": enabled})
    except Exception as e:
        logger.error(f"ext_get_settings error: {e}")
        return jsonify({"error": "Internal error"}), 500

def ext_update_settings():
    user = get_user_from_bearer()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.get_json(force=True, silent=True) or {}
        if 'browser_notifications_enabled' in data:
            val = bool(data['browser_notifications_enabled'])
            row = UserSetting.query.filter_by(user_id=user.id).first()
            if not row:
                row = UserSetting(user_id=user.id)
                db.session.add(row)
            row.browser_notifications_enabled = val
            db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"ext_update_settings error: {e}")
        db.session.rollback()
        return jsonify({"error": "Internal error"}), 500

# Register extension settings routes
app.add_url_rule('/api/extension/settings', view_func=ext_get_settings, methods=['GET', 'OPTIONS'])
app.add_url_rule('/api/extension/settings', view_func=ext_update_settings, methods=['POST', 'OPTIONS'])

# JWT for extension endpoints
# (Removed duplicate import; jwt is imported at the top of this file)

# User Authentication Models (credentials.db)
# User model imported from credentials.py

# Credential model imported from credentials.py

# UserSetting model imported from credentials.py

def get_manual_tax_investment(user_id):
    try:
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        if not setting or setting.tax_manual_invested_updated is None:
            return 0.0
        return float(setting.tax_manual_invested_updated)
    except Exception as e:
        logger.error(f"Failed to fetch manual tax investment for user {user_id}: {e}")
        return 0.0


def set_manual_tax_investment(user_id, amount):
    try:
        amount_value = float(amount or 0.0)
    except (TypeError, ValueError):
        amount_value = 0.0

    try:
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        if not setting:
            setting = UserSetting(user_id=user_id)
            db.session.add(setting)
        
        setting.tax_manual_invested_updated = amount_value
        db.session.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to set manual tax investment for user {user_id}: {e}")
        db.session.rollback()
        return False


def get_user_credentials(username):
    try:
        logger.debug(f"Fetching credentials for user: {username}")
        # Use the consolidated models directly (no context switching needed)
        if current_user and getattr(current_user, 'is_authenticated', False):
            cred = Credential.query.filter_by(user_id=current_user.id).first()
        else:
            cred = Credential.query.filter_by(username=username).first()
        if not cred:
            logger.error(f"No credentials found for user: {username}")
            return None
        logger.debug(f"Credentials fetched for user {username}: {cred}")
        return cred
    except Exception as e:
        logger.error(f"Error fetching credentials for user {username}: {e}", exc_info=True)
        return None


def get_user_credentials_dict(username) -> dict:
    """
    Convenience helper that returns decrypted credential values as a plain dict.
    Falls back to empty strings to match historical behaviour when credentials were missing.
    """
    cred = get_user_credentials(username)
    if not cred:
        return {}

    return {
        "api_key": cred.api_key or "",
        "api_secret": cred.api_secret or "",
        "trading_api_key": cred.trading_api_key or "",
        "trading_api_secret": cred.trading_api_secret or "",
        "openai_key": cred.openai_key or "",
        "zai_key": cred.zai_key or "",
        "perplexity_key": cred.perplexity_key or "",
        "gemini_key": cred.gemini_key or "",
        "ai_provider": getattr(cred, "ai_provider", "") or "",
        "telegram_token": cred.telegram_token or "",
        "telegram_chat_id": cred.telegram_chat_id or "",
        "news_api": cred.news_api or "",
        "brave_search_api_key": cred.brave_search_api_key or "",
        "brave_search_api_key_fallback": cred.brave_search_api_key_fallback or "",
    }

def get_user_ai_prompts(user_id):
    """Get user's AI prompts from the ai_prompts table, creating defaults if none exist"""
    try:
        logger.error(f"=== DEBUG: get_user_ai_prompts called with user_id: {user_id} ===")
        ai_prompts = AIPrompt.query.filter_by(user_id=user_id).first()
        logger.error(f"=== DEBUG: AIPrompt query result: {ai_prompts is not None} ===")
        if not ai_prompts:
            logger.info(f"No AI prompts found for user_id: {user_id}, creating defaults")
            # Create default prompts for the user
            ai_prompts = AIPrompt(
                user_id=user_id,
                market_analysis_pre="",
                market_analysis_post="",
                risk_assessment_pre="",
                risk_assessment_post="",
                portfolio_review_pre="",
                portfolio_review_post="",
                coin_analysis_pre="",
                coin_analysis_post="",
                sentiment_prompt_pre="",
                sentiment_prompt_post=""
            )
            db.session.add(ai_prompts)
            db.session.commit()
            logger.info(f"Created default AI prompts for user_id: {user_id}")
        return ai_prompts
    except Exception as e:
        logger.error(f"Error fetching/creating AI prompts for user_id {user_id}: {e}", exc_info=True)
        db.session.rollback()
        return None

def get_user_ai_settings(username: str) -> dict:
    """
    Return AI/user settings merged with defaults.
    - Loads defaults from database first, fallback to built-in defaults
    - Overlays values from credentials (ai_provider only)
    - Overlays per-user entries from user_settings table
    - Normalizes time strings and fixes '24:00' -> '23:59'
    """
    try:
        # Define fallback defaults
        settings = {
            'ai_enabled': True,
            'ai_provider': 'openai',
            'ai_model': 'gpt-4.1',
            'ai_cache_duration_hours': 1,
            'ai_confidence_threshold': 70,
            'ai_risk_tolerance': 'moderate',
            'ai_analysis_window_start': '08:00',
            'ai_analysis_window_end': '23:59',
            'ai_notifications_enabled': True,
            'ai_max_tokens': 800,
            'ai_web_search_enabled': True,
            'tax_manual_invested_updated': None,
            'tax_cost_basis_method': 'fifo',
            'credentials_encryption_key_configured': False,
            'ai_prompts': {
                'market_analysis_pre': '',
                'market_analysis_post': '',
                'risk_assessment_pre': '',
                'risk_assessment_post': '',
                'portfolio_review_pre': '',
                'portfolio_review_post': '',
                'coin_analysis_pre': '',
                'coin_analysis_post': '',
                'sentiment_prompt_pre': '',
                'sentiment_prompt_post': '',
            },
            'copilot_chat_pre': '',
            'copilot_chat_post': ''
        }

        # Load credentials row for provider (legacy overlay, but UserSetting is authoritative now)
        # Actually, UserSetting table has ai_provider. Credential has it too. 
        # Plan was "UserSetting is authoritative". 
        # But let's check Credential just in case migration missed something or Credential is still used for keys.
        # We will load UserSetting row.
        
        user_obj = User.query.filter_by(username=username).first()
        if user_obj:
            user_setting = UserSetting.query.filter_by(user_id=user_obj.id).first()
            if user_setting:
                settings['ai_enabled'] = user_setting.ai_enabled
                settings['ai_provider'] = user_setting.ai_provider
                settings['ai_provider_fallback'] = user_setting.ai_provider_fallback
                settings['ai_model'] = user_setting.ai_model
                settings['ai_model_fallback'] = user_setting.ai_model_fallback
                settings['ai_risk_tolerance'] = user_setting.ai_risk_tolerance
                settings['ai_confidence_threshold'] = user_setting.ai_confidence_threshold
                settings['ai_notifications_enabled'] = user_setting.ai_notifications_enabled
                settings['ai_analysis_frequency'] = user_setting.ai_analysis_frequency
                settings['ai_cache_duration_hours'] = user_setting.ai_cache_duration_hours
                settings['ai_analysis_window_start'] = user_setting.ai_analysis_window_start
                settings['ai_analysis_window_end'] = user_setting.ai_analysis_window_end
                settings['ai_max_tokens'] = user_setting.ai_max_tokens
                settings['ai_web_search_enabled'] = user_setting.ai_web_search_enabled
                settings['tax_manual_invested_updated'] = user_setting.tax_manual_invested_updated
                settings['tax_cost_basis_method'] = user_setting.tax_cost_basis_method
                settings['credentials_encryption_key_configured'] = user_setting.credentials_encryption_key_configured
                

                # Load Copilot prompts from UserSetting (or fallback to empty -> will hit Defaults later)
                if hasattr(user_setting, 'copilot_chat_pre') and user_setting.copilot_chat_pre:
                    settings['copilot_chat_pre'] = user_setting.copilot_chat_pre
                if hasattr(user_setting, 'copilot_chat_post') and user_setting.copilot_chat_post:
                    settings['copilot_chat_post'] = user_setting.copilot_chat_post

                # Load Sentiment Analysis Frequency
                if hasattr(user_setting, 'sentiment_analysis_frequency_hours'):
                    settings['sentiment_analysis_frequency_hours'] = user_setting.sentiment_analysis_frequency_hours or 24

        # Normalize provider/model pairing
        provider = settings.get('ai_provider', 'openai')
        model = settings.get('ai_model')

        valid_providers = {'openai', 'zai', 'perplexity', 'gemini'}
        if provider not in valid_providers:
            provider = 'openai'
            settings['ai_provider'] = provider

        openai_models = {
            'gpt-5',
            'gpt-5-mini',
            'gpt-5-nano',
            'gpt-4.1',
            'gpt-4.1-mini',
            'gpt-4.1-nano',
            'o4-mini',
            'o3',
            'o3-mini',
        }
        zai_models = {
            'glm-4.7',
            'glm-4.7-flash',
            'glm-4.7-flashx',
        }
        # Perplexity current public models per docs
        perplexity_models = {
            'sonar-pro',
            'sonar',
            'sonar-reasoning',
        }
        gemini_models = {
            'gemini-3-flash-preview',
            'gemini-3-pro-preview',
        }
        default_models = {
            'openai': 'gpt-5',
            'zai': 'glm-4.7-flash',
            'perplexity': 'sonar-medium-online',
            'gemini': 'gemini-3-flash-preview',
        }
        

        if provider == 'openai':
            if model not in openai_models:
                settings['ai_model'] = default_models['openai']
        elif provider == 'zai':
            if model not in zai_models:
                settings['ai_model'] = default_models['zai']
        elif provider == 'perplexity':
            # Backward-compatibility mapping to current models
            legacy_map = {
                'llama-3.1-sonar-small-128k-online': 'sonar',
                'llama-3.1-sonar-large-128k-online': 'sonar-pro',
                'llama-3.1-sonar-small-128k-chat': 'sonar',
                'llama-3.1-sonar-large-128k-chat': 'sonar-pro',
                'sonar-small-online': 'sonar',
                'sonar-medium-online': 'sonar-pro',
                'sonar-small-chat': 'sonar',
                'sonar-medium-chat': 'sonar-pro',
            }
            if model in legacy_map:
                model = legacy_map[model]
                settings['ai_model'] = model
            if model not in perplexity_models:
                settings['ai_model'] = 'sonar-pro'
        elif provider == 'gemini':
            # Map deprecated labels to stable Gemini model slugs
            legacy_gemini_map = {
                'gemini-2.0-pro-exp': 'gemini-2.5-pro-exp',
                'gemini-2.0-flash': 'gemini-2.5-flash',
                'gemini-2.0-flash-exp': 'gemini-2.5-flash-exp',
                'gemini-1.5-pro': 'gemini-1.5-pro-latest',
                'gemini-1.5-flash': 'gemini-1.5-flash-latest',
            }
            if model in legacy_gemini_map:
                model = legacy_gemini_map[model]
                settings['ai_model'] = model
            if model not in gemini_models:
                settings['ai_model'] = default_models['gemini']
        else:
            settings['ai_model'] = default_models['openai']

        def _fix_time(s: str, default: str) -> str:
            try:
                s = (s or '').strip()
                if s == '24:00':
                    return '23:59'
                parts = s.split(':')
                if len(parts) < 2:
                    return default
                hh = int(parts[0])
                mm = int(parts[1])
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    return default
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return default

        settings['ai_analysis_window_start'] = _fix_time(settings.get('ai_analysis_window_start', '08:00'), '08:00')
        settings['ai_analysis_window_end'] = _fix_time(settings.get('ai_analysis_window_end', '23:59'), '23:59')

        # Load user prompts from database and convert to pre/post format
        user_obj = User.query.filter_by(username=username).first()
        if user_obj:
            ai_prompts_obj = get_user_ai_prompts(user_obj.id)
            if ai_prompts_obj:
                settings['ai_prompts'] = {
                    'market_analysis_pre': getattr(ai_prompts_obj, 'market_analysis_pre', settings['ai_prompts']['market_analysis_pre']),
                    'market_analysis_post': getattr(ai_prompts_obj, 'market_analysis_post', settings['ai_prompts']['market_analysis_post']),
                    'risk_assessment_pre': getattr(ai_prompts_obj, 'risk_assessment_pre', settings['ai_prompts']['risk_assessment_pre']),
                    'risk_assessment_post': getattr(ai_prompts_obj, 'risk_assessment_post', settings['ai_prompts']['risk_assessment_post']),
                    'portfolio_review_pre': getattr(ai_prompts_obj, 'portfolio_review_pre', settings['ai_prompts']['portfolio_review_pre']),
                    'portfolio_review_post': getattr(ai_prompts_obj, 'portfolio_review_post', settings['ai_prompts']['portfolio_review_post']),
                    'coin_analysis_pre': getattr(ai_prompts_obj, 'coin_analysis_pre', settings['ai_prompts']['coin_analysis_pre']),
                    'coin_analysis_post': getattr(ai_prompts_obj, 'coin_analysis_post', settings['ai_prompts']['coin_analysis_post']),
                    'sentiment_prompt_pre': getattr(ai_prompts_obj, 'sentiment_prompt_pre', settings['ai_prompts']['sentiment_prompt_pre']),
                    'sentiment_prompt_post': getattr(ai_prompts_obj, 'sentiment_prompt_post', settings['ai_prompts']['sentiment_prompt_post']),
                }
            
            # If copilot prompts still empty, try to load from DefaultAIPrompt via our prompt logic
            if not settings.get('copilot_chat_pre'):
                # We need to manually query DefaultAIPrompt since get_user_ai_prompts returns UserPrompt
                def_prompts = DefaultAIPrompt.query.first()
                if def_prompts:
                    settings['copilot_chat_pre'] = def_prompts.copilot_chat_pre
                    settings['copilot_chat_post'] = def_prompts.copilot_chat_post

        return settings
    except Exception as e:
        logger.error(f"Error building user AI settings for {username}: {e}")
        db.session.rollback()
        # Return fallback defaults if there's an error
        return {
            'ai_enabled': True,
            'ai_provider': 'openai',
            'ai_model': 'gpt-5',
            'ai_cache_duration_hours': 1,
            'ai_confidence_threshold': 70,
            'ai_risk_tolerance': 'moderate',
            'ai_analysis_window_start': '08:00',
            'ai_analysis_window_end': '23:59',
            'ai_notifications_enabled': True,
            'ai_max_tokens': 800,
            'manual_chat_pre': '',
            'manual_chat_post': '',
            'copilot_chat_pre': '',
            'copilot_chat_post': '',
            'ai_prompts': {
                'market_analysis_pre': '',
                'market_analysis_post': '',
                'risk_assessment_pre': '',
                'risk_assessment_post': '',
                'portfolio_review_pre': '',
                'portfolio_review_post': '',
                'coin_analysis_pre': '',
                'coin_analysis_post': '',
                'sentiment_prompt_pre': '',
                'sentiment_prompt_post': '',
            }
        }

# ONE login manager for the entire app
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.session_protection = None  # Disable session protection to prevent logout on refresh
login_manager.remember_cookie_duration = timedelta(days=30)

# --- AI Provider Connection Test Endpoints ---
@app.route('/api/test-openai-connection', methods=['POST', 'GET'])
@login_required
def test_openai_connection():
    try:
        from flask import request
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        # Sanitize model to OpenAI-supported list only
        openai_models = {
            'gpt-5', 'gpt-5-mini', 'gpt-5-nano',
            'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
            'o4-mini', 'o3', 'o3-mini'
        }
        requested_model = payload.get('model')
        model = requested_model if requested_model in openai_models else 'gpt-5'
        key = payload.get('openai_key')

        cred = get_user_credentials(username)
        openai_api_key = key if key else decrypt_secret(getattr(cred, '_openai_key', None))
        if not openai_api_key:
            return jsonify(success=False, message='OpenAI API key missing'), 400
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_api_key, timeout=20.0)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role":"user","content":"ping"}],
                max_completion_tokens=5
            )
            ok = bool(getattr(resp, 'choices', None))
            return jsonify(success=ok, message='OpenAI connection OK' if ok else 'OpenAI responded without choices')
        except Exception as e:
            return jsonify(success=False, message=f'OpenAI error: {e}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@app.route('/api/test-zai-connection', methods=['POST', 'GET'])
@login_required
def test_zai_connection():
    try:
        from flask import request
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        # Sanitize model to Z.AI-supported list only
        zai_models = {
            'glm-4.7', 'glm-4.7-flash', 'glm-4.7-flashx'
        }
        requested_model = payload.get('model')
        model = requested_model if requested_model in zai_models else 'glm-4.7-flash'
        key = payload.get('zai_key')

        cred = get_user_credentials(username)
        zai_api_key = key if key else decrypt_secret(getattr(cred, '_zai_key', None))
        if not zai_api_key:
            return jsonify(success=False, message='Z.AI API key missing'), 400
        try:
            from zai_client import ZAIClient
            client = ZAIClient(zai_api_key)
            resp = client.chat_completion(
                messages=[{"role":"user","content":"ping"}],
                model=model,
                max_tokens=5,
                temperature=0.0
            )
            ok = bool(resp) and resp.get('success')
            return jsonify(success=bool(ok), message='Z.AI connection OK' if ok else f"Z.AI error: {resp}")
        except Exception as e:
            return jsonify(success=False, message=f'Z.AI error: {e}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@app.route('/api/test-perplexity-connection', methods=['POST'])
@login_required
def test_perplexity_connection():
    try:
        from flask import request
        import requests
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        # Sanitize model to current Perplexity models
        allowed = {'sonar-pro', 'sonar', 'sonar-reasoning'}
        requested = payload.get('model')
        model = requested if requested in allowed else 'sonar-pro'
        key = payload.get('perplexity_key')

        cred = get_user_credentials(username)
        api_key = key if key else decrypt_secret(getattr(cred, '_perplexity_key', None))
        if not api_key:
            return jsonify(success=False, message='Perplexity API key missing'), 400
        for m in [model, 'sonar-pro', 'sonar', 'sonar-reasoning']:
            r = requests.post(
                'https://api.perplexity.ai/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': m, 'messages': [{"role":"user","content":"ping"}], 'max_tokens': 5},
                timeout=20
            )
            if r.status_code == 200:
                return jsonify(success=True, message=f'Perplexity connection OK (model {m})')
        return jsonify(success=False, message=f'Perplexity error: {r.text}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@app.route('/api/test-gemini-connection', methods=['POST'])
@login_required
def test_gemini_connection():
    try:
        from flask import request
        import requests
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        model = payload.get('model') or ai_settings.get('ai_model') or 'gemini-2.5-pro'
        key = payload.get('gemini_key')

        cred = get_user_credentials(username)
        api_key = key if key else decrypt_secret(getattr(cred, '_gemini_key', None))
        if not api_key:
            return jsonify(success=False, message='Gemini API key missing'), 400

        contents = [{"role":"user","parts":[{"text":"ping"}]}]
        for api_ver in ['v1beta', 'v1', 'v1alpha']:
            r = requests.post(
                f'https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={api_key}',
                json={'contents': contents},
                timeout=20
            )
            if r.status_code == 200:
                return jsonify(success=True, message=f'Gemini connection OK ({api_ver})')
        # Enhance error message for quota/rate-limit responses
        try:
            err = r.json()
            code = err.get('error', {}).get('code')
            msg = err.get('error', {}).get('message')
            retry_delay = None
            for d in err.get('error', {}).get('details', []) or []:
                if d.get('@type', '').endswith('RetryInfo') and 'retryDelay' in d:
                    retry_delay = d.get('retryDelay')
                    break
            friendly = f"Gemini error (code {code}): {msg}"
            if retry_delay:
                friendly += f" | Suggested retry in {retry_delay}"
            return jsonify(success=False, message=friendly), 429 if code == 429 else 400
        except Exception:
            return jsonify(success=False, message=f'Gemini error: {r.text}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@app.route('/api/test-ai-connection-generic', methods=['POST'])
@login_required
def test_ai_connection_generic():
    """Generic endpoint to test ANY AI provider with a specific key (useful for fallback testing)"""
    try:
        from flask import request
        import requests
        payload = request.get_json(silent=True) or {}
        provider = payload.get('provider')
        api_key = payload.get('api_key')
        model = payload.get('model')

        if not provider or not api_key:
            return jsonify(success=False, message='Provider and API key are required'), 400

        if provider == 'openai':
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key, timeout=10.0)
                # Default to gpt-4o-mini for cheap testing if no model
                test_model = model or 'gpt-4o-mini'
                resp = client.chat.completions.create(
                    model=test_model,
                    messages=[{"role":"user","content":"ping"}],
                    max_completion_tokens=5
                )
                return jsonify(success=True, message=f'OpenAI connection OK ({test_model})')
            except Exception as e:
                return jsonify(success=False, message=f'OpenAI error: {e}'), 400

        elif provider == 'zai':
            try:
                from zai_client import ZAIClient
                client = ZAIClient(api_key)
                test_model = model or 'glm-4.7-flash'
                resp = client.chat_completion(
                    messages=[{"role":"user","content":"ping"}],
                    model=test_model,
                    max_tokens=5
                )
                if resp.get('success'):
                    return jsonify(success=True, message=f'Z.AI connection OK ({test_model})')
                else:
                    return jsonify(success=False, message=f"Z.AI error: {resp.get('error')}"), 400
            except Exception as e:
                return jsonify(success=False, message=f'Z.AI error: {e}'), 400

        elif provider == 'perplexity':
            try:
                test_model = model or 'sonar'
                # Perplexity supported models
                allowed = {'sonar-pro', 'sonar', 'sonar-reasoning', 'llama-3.1-sonar-small-128k-online', 'llama-3.1-sonar-large-128k-online', 'llama-3.1-sonar-huge-128k-online'}
                # Basic validation, but let's be lenient
                r = requests.post(
                    'https://api.perplexity.ai/chat/completions',
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json={'model': test_model, 'messages': [{"role":"user","content":"ping"}], 'max_tokens': 5},
                    timeout=20
                )
                if r.status_code == 200:
                    return jsonify(success=True, message=f'Perplexity connection OK ({test_model})')
                return jsonify(success=False, message=f'Perplexity error: {r.text}'), 400
            except Exception as e:
                return jsonify(success=False, message=f'Perplexity error: {e}'), 400

        elif provider == 'gemini':
            try:
                test_model = model or 'gemini-1.5-flash'
                # Simple generateContent test
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{test_model}:generateContent?key={api_key}"
                r = requests.post(
                    url,
                    headers={'Content-Type': 'application/json'},
                    json={"contents": [{"parts": [{"text": "ping"}]}]},
                    timeout=20
                )
                if r.status_code == 200:
                    return jsonify(success=True, message=f'Gemini connection OK ({test_model})')
                return jsonify(success=False, message=f'Gemini error: {r.text}'), 400
            except Exception as e:
                return jsonify(success=False, message=f'Gemini error: {e}'), 400

        else:
            return jsonify(success=False, message=f'Unsupported provider: {provider}'), 400

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@app.before_request
def debug_session():
    """Debug session and authentication state when explicitly enabled."""
    debug_enabled = str(os.getenv("DEBUG_SESSION_LOGS", "")).lower() in {"1", "true", "yes"}
    if not debug_enabled:
        return
    if request.endpoint and not request.endpoint.startswith('static'):
        logger.info("[SESSION_DEBUG] ==========================================")
        logger.info(f"[SESSION_DEBUG] Path: {request.path}")
        logger.info(f"[SESSION_DEBUG] Method: {request.method}")
        logger.info(f"[SESSION_DEBUG] Remote Addr: {request.remote_addr}")
        logger.info(f"[SESSION_DEBUG] User authenticated: {current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else 'NO_USER'}")
        if hasattr(current_user, 'id'):
            logger.info(f"[SESSION_DEBUG] Current user ID: {current_user.id}")
        logger.info("[SESSION_DEBUG] ==========================================")

# ...rest of the code...

# Move route definitions here, after app is defined
@app.route("/api/login", methods=["POST"])
def api_login():
    """API endpoint for logging in. Returns JSON only."""
    data = request.get_json() or request.form
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required."}), 400
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        login_user(user, remember=True)
        session.permanent = True
        return jsonify({"success": True, "user": {"username": user.username, "id": user.id}})
    return jsonify({"success": False, "error": "Invalid username or password."}), 401

@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    """API endpoint for logging out. Returns JSON only."""
    logger.info(f"Logging out user via API: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    logger.info(f"Session before logout: {dict(session)}")
    logout_user()
    session.clear()
    session.pop('_flashes', None)
    session.pop('user_id', None)  
    session.pop('username', None)
    session.modified = True
    logger.info(f"Session after logout: {dict(session)}")
    logger.info("User logged out successfully via API")
    return jsonify({"success": True})


ALERT_CHECK_INTERVAL = 30
STABLE_COINS = {"USDT", "USDC", "DAI", "TUSD", "USDP", "EURC", "PYUSD"}
AUTO_ALERT_CACHE = {}  # { (symbol, type): { 'value': float, 'updated': datetime } }
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
PRICE_CACHE = {}  # {symbol: (price, timestamp)}
PRICE_CACHE_TTL = 300  # 5 minutes
NEWS_SENTIMENT_CACHE = {}  # {symbol: (sentiment, timestamp)}
NEWS_SENTIMENT_CACHE_TTL = 600  # 10 minutes
LOG_FILE_PATH = '/home/jcavallarojr/crypto_alert_app/app_debug.log'

NEWS_API_RATE_LIMIT = 100
NEWS_API_WINDOW_SECONDS = 24 * 3600
NEWS_API_REQUEST_LOG = {}  # {username: [timestamp, ...]}
NEWS_API_LOCK = threading.Lock()
NEWS_API_DISABLED_UNTIL = {}  # {username: timestamp}

# AI Cache Functions
def get_ai_cache(user_id, cache_key, cache_type):
    """Get cached AI analysis result"""
    try:
        with app.app_context():
            cache_entry = AICache.query.filter(
                AICache.user_id == user_id,
                AICache.cache_key == cache_key,
                AICache.cache_type == cache_type,
                AICache.expires_at > datetime.now()
            ).first()
            
            if cache_entry:
                import json
                return json.loads(cache_entry.data)
            return None
        
    except Exception as e:
        logger.error(f"Error getting AI cache: {e}")
        return None

def set_ai_cache(user_id, cache_key, cache_type, data, hours=4):
    """Set cached AI analysis result"""
    try:
        import json
        from datetime import datetime, timedelta
        
        with app.app_context():
            expires_at = datetime.now() + timedelta(hours=hours)
            
            # Check if exists
            cache_entry = AICache.query.filter_by(
                user_id=user_id,
                cache_key=cache_key,
                cache_type=cache_type
            ).first()
            
            if cache_entry:
                cache_entry.data = json.dumps(data)
                cache_entry.expires_at = expires_at
            else:
                cache_entry = AICache(
                    user_id=user_id,
                    cache_key=cache_key,
                    cache_type=cache_type,
                    data=json.dumps(data),
                    expires_at=expires_at
                )
                db.session.add(cache_entry)
            
            db.session.commit()
            
            logger.info(f"AI cache set: {cache_type} for user {user_id}")
            return True
            
    except Exception as e:
        logger.error(f"Error setting AI cache: {e}")
        return False

def clear_expired_ai_cache():
    """Clear expired AI cache entries"""
    try:
        with app.app_context():
            deleted_count = AICache.query.filter(AICache.expires_at <= datetime.now()).delete()
            db.session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleared {deleted_count} expired AI cache entries")
            
            return deleted_count
        
    except Exception as e:
        logger.error(f"Error clearing expired AI cache: {e}")
        return 0

def is_analysis_window_active():
    """Check if current time is within AI analysis window (8 AM - 12 AM ET)"""
    try:
        from datetime import datetime
        import pytz
        
        # Get current time in Eastern Time
        et_tz = pytz.timezone('US/Eastern')
        now = datetime.now(et_tz)
        
        # Parse window times
        start_time = datetime.strptime("08:00", "%H:%M").time()
        end_time = datetime.strptime("23:59", "%H:%M").time()  # 12 AM next day
        
        current_time = now.time()
        
        # Check if current time is within window
        if start_time <= current_time or current_time < end_time:
            return True
        return False
        
    except Exception as e:
        logger.error(f"Error checking analysis window: {e}")
        return True  # Default to True if error

def is_user_analysis_window_active(start_time_str, end_time_str):
    """Check if current time is within user specific AI analysis window"""
    try:
        now = get_eastern_now()
        settings = {
            'ai_analysis_window_start': start_time_str,
            'ai_analysis_window_end': end_time_str
        }
        start_dt, end_dt = _get_analysis_window_bounds(settings, now)
        return start_dt <= now <= end_dt

    except Exception as e:
        logger.error(f"Error checking analysis window: {e}")
        return True  # Default to True if error


def _get_analysis_window_bounds(settings, reference_dt):
    start_str = settings.get('ai_analysis_window_start', '08:00')
    end_str = settings.get('ai_analysis_window_end', '23:59')

    def _parse_time(value, fallback):
        try:
            parts = value.split(':')
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            hh = max(0, min(23, hh))
            mm = max(0, min(59, mm))
            return dt_time(hh, mm)
        except Exception:
            return fallback

    start_time = _parse_time(start_str, dt_time(8, 0))
    end_time = _parse_time(end_str, dt_time(23, 59))

    start_dt = reference_dt.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
    end_dt = reference_dt.replace(hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt

def should_run_ai_analysis(user_id):
    """Check if AI analysis should run based on schedule and frequency settings"""
    try:
        with app.app_context():
            schedule = AIAnalysisSchedule.query.filter_by(user_id=user_id).first()
            
            user = User.query.filter_by(id=user_id).first()
            if not user:
                return False

            settings = get_user_ai_settings(user.username)
            frequency = settings.get('ai_analysis_frequency', 'daily').lower()
            now = get_eastern_now()
            
            # Helper to get window bounds for today
            window_start, window_end = _get_analysis_window_bounds(settings, now)

            # Initialize schedule if not exists
            if not schedule:
                # If no previous run, we should run now (or at window start if hourly)
                initial_next_run = now
                if frequency == 'hourly':
                    # For hourly, if we are before window, wait for window
                    if now < window_start:
                        initial_next_run = window_start
                    elif now > window_end:
                         # If after window, wait for next day window
                        initial_next_run = window_start + timedelta(days=1)
                
                schedule = AIAnalysisSchedule(
                    user_id=user_id,
                    last_analysis=None,
                    next_analysis=initial_next_run
                )
                db.session.add(schedule)
                db.session.commit()
                
                # If we are ready to run
                return now >= initial_next_run

            last_run = schedule.last_analysis
            
            # If never ran, logic is simpler: check if we hit next_analysis
            if not last_run:
                # Sanity check if we missed the next_analysis by a lot, just run now
                next_analysis_dt = _parse_iso(schedule.next_analysis, default=now)
                if next_analysis_dt and now >= next_analysis_dt:
                    return True
                return False

            # Calculate when we SHOULD run next based on last_run
            last_run_local = _parse_iso(last_run, default=now - timedelta(days=1))
            
            if frequency == 'hourly':
                # HOURLY: Must respect Window AND 1 hour interval
                # 1. Check Window
                if not (window_start <= now <= window_end):
                    return False
                
                # 2. Check 1 hour interval
                next_run_time = last_run_local + timedelta(hours=1)
                return now >= next_run_time

            elif frequency == 'weekly':
                # WEEKLY: Simple 7 day interval, ignore window
                next_run_time = last_run_local + timedelta(days=7)
                return now >= next_run_time
            
            else: # Default 'daily'
                # DAILY: Simple 24 hour interval, ignore window
                next_run_time = last_run_local + timedelta(days=1)
                return now >= next_run_time


    except Exception as e:
        logger.error(f"Error checking AI analysis schedule: {e}")
        return True

def update_ai_analysis_schedule(user_id):
    """Update AI analysis schedule"""
    try:
        with app.app_context():
            # Get user to get username
            user = User.query.filter_by(id=user_id).first()
            if not user:
                return

            # Get user settings for cache duration
            user_settings = get_user_ai_settings(user.username)
            cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)

            now = get_eastern_now()
            window_start, window_end = _get_analysis_window_bounds(user_settings, now)

            next_candidate = now + timedelta(hours=cache_duration_hours)
            if next_candidate < window_start:
                next_run = window_start
            elif next_candidate <= window_end:
                next_run = next_candidate
            else:
                # Schedule for next day start
                next_run = window_start + timedelta(days=1)

            schedule = AIAnalysisSchedule.query.filter_by(user_id=user_id).first()
            if schedule:
                schedule.last_analysis = now
                schedule.next_analysis = next_run
            else:
                schedule = AIAnalysisSchedule(
                    user_id=user_id,
                    last_analysis=now,
                    next_analysis=next_run
                )
                db.session.add(schedule)
            
            db.session.commit()

            logger.info(f"Updated AI analysis schedule for user {user_id}")

    except Exception as e:
        logger.error(f"Error updating AI analysis schedule: {e}")

def is_ai_enabled(username):
    """Check if AI is enabled for user"""
    try:
        user_settings = get_user_ai_settings(username)
        return user_settings.get('ai_enabled', True)
    except Exception as e:
        logger.error(f"Error checking AI enabled status: {e}")
        return True

def is_stablecoin(symbol):
    """Check if a symbol is a stablecoin"""
    stablecoins = {
        'USDT', 'USDC', 'USD', 'USDP', 'DAI', 'BUSD', 'TUSD', 'FRAX', 'USDD', 'GUSD',
        'USDN', 'USDK', 'USDJ', 'USDQ', 'USDS', 'USDX', 'USDY', 'USDZ'
    }
    return symbol.upper() in stablecoins

def generate_conversation_id():
    """Generate unique conversation ID"""
    import uuid
    return str(uuid.uuid4())

def web_search(query, max_results=5, username=None):
    """Perform web search using Brave Search API with dual-key fallback, then DuckDuckGo"""
    import requests
    from urllib.parse import quote
    
    # Try Brave Search with primary and fallback keys
    if username:
        try:
            with app.app_context():
                # Get user's Brave Search API keys from credentials
                cred = Credential.query.filter_by(username=username).first()
                brave_api_key = getattr(cred, 'brave_search_api_key', '') if cred else ''
                brave_api_key_fallback = getattr(cred, 'brave_search_api_key_fallback', '') if cred else ''
                
                # Try primary key first, then fallback key
                for key_name, api_key in [('primary', brave_api_key), ('fallback', brave_api_key_fallback)]:
                    if not api_key or not api_key.strip():
                        continue
                        
                    try:
                        logger.info(f"Attempting Brave Search ({key_name} key) for query: {query}")
                        
                        # Use Brave Search API
                        brave_url = "https://api.search.brave.com/res/v1/web/search"
                        headers = {
                            "Accept": "application/json",
                            "Accept-Encoding": "gzip",
                            "X-Subscription-Token": api_key
                        }
                        params = {
                            "q": query,
                            "count": max_results,
                            "search_lang": "en",
                            "country": "US",
                            "safesearch": "moderate",
                            "freshness": "pd"  # Past day for fresh results
                        }
                        
                        response = requests.get(brave_url, headers=headers, params=params, timeout=15)
                        
                        if response.status_code == 200:
                            data = response.json()
                            results = []
                            
                            # Parse Brave Search results
                            for item in data.get('web', {}).get('results', [])[:max_results]:
                                results.append({
                                    'title': item.get('title', ''),
                                    'snippet': item.get('description', '')[:300],
                                    'url': item.get('url', ''),
                                    'source': f'Brave Search ({key_name})'
                                })
                            
                            if results:
                                logger.info(f"Brave Search ({key_name}) returned {len(results)} results")
                                return results
                            else:
                                logger.warning(f"Brave Search ({key_name}) returned no results")
                                
                        elif response.status_code == 429:
                            logger.warning(f"Brave Search ({key_name}) rate limit exceeded (2000/month)")
                            # Continue to try fallback key if this was primary
                            if key_name == 'primary' and brave_api_key_fallback and brave_api_key_fallback.strip():
                                continue
                        elif response.status_code == 401:
                            logger.error(f"Brave Search ({key_name}) API key invalid")
                        else:
                            logger.warning(f"Brave Search ({key_name}) failed with status {response.status_code}")
                            
                    except Exception as e:
                        logger.error(f"Brave Search ({key_name}) error: {e}")
                
                # If we get here, both Brave keys failed
                logger.info("Both Brave Search API keys exhausted/failed, falling back to DuckDuckGo")
                
        except Exception as e:
            logger.error(f"Error accessing Brave Search credentials: {e}")
    
    # Fallback to DuckDuckGo with retry logic
    for retry in range(2):  # Try twice
        try:
            logger.info(f"Using DuckDuckGo fallback for query: {query} (attempt {retry + 1}/2)")
            
            # Use DuckDuckGo HTML scraping instead of API (more reliable)
            from bs4 import BeautifulSoup
            
            search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                results = []
                
                # Parse search results from HTML
                for result_div in soup.find_all('div', class_='result', limit=max_results):
                    title_elem = result_div.find('a', class_='result__a')
                    snippet_elem = result_div.find('a', class_='result__snippet')
                    
                    if title_elem:
                        results.append({
                            'title': title_elem.get_text(strip=True),
                            'snippet': snippet_elem.get_text(strip=True)[:300] if snippet_elem else '',
                            'url': title_elem.get('href', ''),
                            'source': 'DuckDuckGo'
                        })
                
                if results:
                    logger.info(f"DuckDuckGo returned {len(results)} results")
                    return results
                    
        except Exception as e:
            logger.error(f"DuckDuckGo search attempt {retry + 1} failed: {e}")
            if retry < 1:  # If not last retry
                time.sleep(2)  # Wait 2 seconds before retry
    
    # Final fallback to crypto price lookup if query is crypto-related
    try:
        if 'price' in query.lower() and any(crypto in query.upper() for crypto in ['BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'ADA', 'DOT', 'MATIC', 'LINK', 'UNI']):
            # Extract crypto symbol
            for crypto in ['BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'ADA', 'DOT', 'MATIC', 'LINK', 'UNI']:
                if crypto in query.upper():
                    try:
                        price = fetch_price(crypto)
                        if price is not None:
                            return [{
                                'title': f'{crypto} Current Price',
                                'snippet': f'Current price of {crypto}: ${price:,.2f} USD',
                                'url': 'https://api.binance.us/',
                                'source': 'Binance API'
                            }]
                    except Exception:
                        pass
                        
    except Exception as e:
        logger.error(f"Crypto price fallback failed: {e}")
    
    # Return empty result if all searches fail
    return [{
        'title': 'Search unavailable', 
        'snippet': 'Web search is currently unavailable. Using AI general knowledge.', 
        'url': '',
        'source': 'System'
    }]

def call_ai_with_web_search(username, messages, model=None, user_id=None, prompt_type="coin_analysis", symbol=None, include_db_context=True, amount=None, is_fallback_attempt=False):
    """
    AGENTIC AI WORKFLOW - 3-STAGE PROCESS (like n8n/Flowise):
    
    Stage 1: AI analyzes the original prompt and determines what web search is needed
    Stage 2: Execute multiple targeted web searches to gather current, real-time data  
    Stage 3: AI synthesizes the original prompt + web search results to provide final response
    
    This ensures proper workflow orchestration for ALL AI prompts across the entire app
    Uses DATABASE-STORED USER PROMPTS with {symbol}, {datetime}, and {amount} variable substitution
    """
    provider = 'openai'  # Initialize provider with default value
    try:
        from flask import session
        
        if not user_id:
            user_id = session.get('_user_id')
        
        # Get user's AI settings for max tokens, provider and model
        user_ai_settings = get_user_ai_settings(username)
        max_tokens = user_ai_settings.get('ai_max_tokens', 2000)
        
        # Get credentials directly to avoid circular imports
        cred = get_user_credentials(username)
        if not cred:
            raise ValueError(f"No credentials found for user: {username}")
        
        # Helper: pick the correct key for a provider, allowing fallback→primary reuse
        def _pick_key(p):
            if p == 'openai':
                return decrypt_secret(cred.openai_key_fallback) or decrypt_secret(cred._openai_key)
            if p == 'zai':
                return decrypt_secret(cred.zai_key_fallback) or decrypt_secret(cred._zai_key)
            if p == 'perplexity':
                return decrypt_secret(cred.perplexity_key_fallback) or decrypt_secret(cred._perplexity_key)
            if p == 'gemini':
                return decrypt_secret(cred.gemini_key_fallback) or decrypt_secret(cred._gemini_key)
            return None

        # Get AI provider preference (Primary vs Fallback)
        if is_fallback_attempt:
            provider = user_ai_settings.get('ai_provider_fallback')
            if not provider:
                raise ValueError("Fallback AI provider not configured")
            logger.info(f"⚠️ USING FALLBACK AI PROVIDER: {provider}")
        else:
            provider = user_ai_settings.get('ai_provider', 'openai')
        
        # Get user's chosen model if not explicitly provided (or force fallback model)
        if is_fallback_attempt:
            model = user_ai_settings.get('ai_model_fallback') or user_ai_settings.get('ai_model') or 'gpt-5'
        elif not model:
            model = user_ai_settings.get('ai_model', 'gpt-5')

        # Initialize appropriate AI client directly
        if provider == 'openai':
            openai_api_key = _pick_key('openai')
            if not openai_api_key:
                raise ValueError("OpenAI API key (primary or fallback) not configured")
            from openai import OpenAI
            openai_client = OpenAI(api_key=openai_api_key, timeout=120.0)
        elif provider == 'zai':
            zai_api_key = _pick_key('zai')
            if not zai_api_key:
                raise ValueError("Z.AI API key (primary or fallback) not configured")
            from zai_client import ZAIClient
            zai_client = ZAIClient(zai_api_key)
        elif provider == 'perplexity':
            perplexity_api_key = _pick_key('perplexity')
            if not perplexity_api_key:
                raise ValueError("Perplexity API key (primary or fallback) not configured")
        elif provider == 'gemini':
            gemini_api_key = _pick_key('gemini')
            if not gemini_api_key:
                raise ValueError("Gemini API key (primary or fallback) not configured")
        else:
            raise ValueError(f"Unsupported AI provider: {provider}")
        
        # Extract the original user message
        original_user_message = ""
        for msg in messages:
            if msg.get('role') == 'user':
                original_user_message = msg.get('content', '')
                break
        
        # Get user's custom AI prompts from database
        ai_prompts = get_user_ai_prompts(user_id)
        if not ai_prompts:
            raise ValueError(f"No AI prompts configured for user_id: {user_id}")
        
        # Prepare variables for prompt substitution
        current_datetime = format_eastern_datetime(None, "%Y-%m-%d %H:%M:%S EST")
        symbol_value = symbol if symbol else "CRYPTO"
        amount_value = str(amount) if amount is not None else "0"
        
        # Get appropriate Stage 1 (pre-search) prompt based on prompt_type
        if prompt_type == 'manual':
            stage1_prompt_template = (user_ai_settings.get('copilot_chat_pre') or '').strip()
            # If still empty, strict fallback logic handled by ValueError below (or we can fallback to hardcoded default)
        else:
            stage1_prompt_map = {
                'coin_analysis': ai_prompts.coin_analysis_pre,
                'market_analysis': ai_prompts.market_analysis_pre,
                'portfolio_review': ai_prompts.portfolio_review_pre,
                'risk_assessment': ai_prompts.risk_assessment_pre,
                'sentiment_analysis': ai_prompts.sentiment_prompt_pre
            }
            stage1_prompt_template = stage1_prompt_map.get(prompt_type)
            stage1_prompt_template = (stage1_prompt_template or '').strip()

        if not stage1_prompt_template:
            raise ValueError(f"Missing Stage 1 prompt for {prompt_type}. Configure it in Settings.")
        
        # Substitute variables in Stage 1 prompt (handle {amount} placeholder)
        try:
            stage1_prompt = stage1_prompt_template.format(
                symbol=symbol_value,
                datetime=current_datetime,
                amount=amount_value
            )
        except KeyError:
            # If {amount} is not in the template, use only symbol and datetime
            stage1_prompt = stage1_prompt_template.format(
                symbol=symbol_value,
                datetime=current_datetime
            )
        
        logger.info("=== AGENTIC WORKFLOW STAGE 1: ANALYZING PROMPT FOR WEB SEARCH QUERIES ===")
        logger.info(f"🤖 Provider: {provider} | Model: {model} | Max Tokens: 600")
        
        # STAGE 1: AI analyzes the prompt and determines web search needed
        stage1_messages = [
            {
                "role": "system",
                "content": stage1_prompt
            },
            {
                "role": "user", 
                "content": original_user_message
            }
        ]
        
        # Make Stage 1 AI request to determine search queries
        if provider == 'openai':
            stage1_response = openai_client.chat.completions.create(
                model=model,
                messages=stage1_messages,
                max_completion_tokens=600  # Increased to 600 to fix GPT-5-nano token limit issue
            )
            logger.info("=== STAGE 1 FULL DEBUG ===")
            logger.info(f"Full Stage 1 response object: {stage1_response}")
            logger.info(f"Stage 1 choices: {stage1_response.choices}")
            logger.info(f"Stage 1 message: {stage1_response.choices[0].message}")
            search_queries_text = stage1_response.choices[0].message.content
            logger.info(f"Raw Stage 1 content (before strip): '{search_queries_text}'")
            if search_queries_text:
                search_queries_text = search_queries_text.strip()
            logger.info(f"Raw Stage 1 response (after strip): '{search_queries_text}'")
            logger.info(f"Stage 1 response length: {len(search_queries_text) if search_queries_text else 0}")
            logger.info("=== END STAGE 1 FULL DEBUG ===")
        elif provider == 'zai':
            stage1_response = zai_client.chat_completion(
                messages=stage1_messages,
                model=model,
                max_tokens=600,  # Increased to 600 to match OpenAI fix
                temperature=0.2
            )
            if stage1_response and stage1_response.get('success'):
                search_queries_text = stage1_response.get('content', '').strip()
            else:
                raise Exception(f"Z.AI Stage 1 error: {stage1_response.get('error', 'Unknown error')}")
        elif provider == 'perplexity':
            import requests
            def _px_try(models_to_try):
                last = None
                for m in models_to_try:
                    r = requests.post(
                        "https://api.perplexity.ai/chat/completions",
                        headers={"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"},
                        json={"model": m, "messages": stage1_messages, "max_tokens": 600},
                        timeout=30
                    )
                    if r.status_code == 200:
                        return r
                    last = r
                return last
            px_models = [model, 'sonar-pro', 'sonar', 'sonar-reasoning']
            response = _px_try(px_models)
            if response is not None and response.status_code == 200:
                search_queries_text = response.json()['choices'][0]['message']['content'].strip()
            else:
                raise Exception(f"Perplexity API error: {response.text if response is not None else 'Unknown error'}")
        elif provider == 'gemini':
            import requests
            contents = []
            for msg in stage1_messages:
                role = msg.get("role", "user")
                if role == 'system':
                    role = 'user'
                elif role == 'assistant':
                    role = 'model'
                contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]} )

            def _gemini_try_models(models_to_try):
                last_err = None
                for m in models_to_try:
                    for api_ver in ['v1beta', 'v1', 'v1alpha']:
                        r = requests.post(
                            f"https://generativelanguage.googleapis.com/{api_ver}/models/{m}:generateContent?key={gemini_api_key}",
                            json={"contents": contents}
                        )
                        if r.status_code == 200:
                            return r
                        last_err = r
                return last_err

            stage1_models = [model, 'gemini-3-flash-preview', 'gemini-3-pro-preview']
            response = _gemini_try_models(stage1_models)
            if response is not None and response.status_code == 200:
                search_queries_text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            else:
                raise Exception(f"Gemini API error: {response.text if response is not None else 'Unknown error'}")
        
        # Parse search queries (one per line) - LIMIT TO 2 FOR SPEED
        search_queries = [q.strip() for q in search_queries_text.split('\n') if q.strip()][:2]  # Reduced from 3 to 2
        logger.info(f"✅ Stage 1 SUCCESS - Generated {len(search_queries)} search queries using {provider}/{model}")
        logger.info(f"Stage 1 generated search queries: {search_queries}")
        
        logger.info("=== AGENTIC WORKFLOW STAGE 2: EXECUTING TARGETED WEB SEARCHES (OPTIMIZED) ===")
        logger.info(f"🔍 Executing {len(search_queries)} web searches using Brave Search API")
        
        # STAGE 2: Execute multiple targeted web searches (OPTIMIZED FOR SPEED)
        all_search_results = []
        for i, query in enumerate(search_queries, 1):
            logger.info(f"Executing web search {i}/2: {query}")
            search_results = web_search(query, max_results=2, username=username)  # Reduced from 3 to 2
            
            # Add search metadata
            for result in search_results:
                result['search_query'] = query
                result['search_order'] = i
                
            all_search_results.extend(search_results)
            logger.info(f"✅ Search {i} completed - returned {len(search_results)} results")
            time.sleep(0.2)  # Reduced pause from 0.5 to 0.2
        
        # Format comprehensive search results with proper structure
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
        search_context = f"### REAL-TIME WEB SEARCH RESULTS\n**Retrieved**: {current_time}\n**Searches Performed**: {len(search_queries)}\n**Total Results**: {len(all_search_results)}\n\n"
        
        for i, result in enumerate(all_search_results, 1):
            search_context += f"**RESULT {i}** (Query: \"{result.get('search_query', 'Unknown')}\")\n"
            search_context += f"**Title**: {result.get('title', 'No title')}\n"
            search_context += f"**Content**: {result.get('snippet', 'No content')}\n"
            search_context += f"**Source**: {result.get('source', 'Unknown')} | **URL**: {result.get('url', 'No URL')}\n"
            search_context += "---\n\n"
        
        logger.info("=== AGENTIC WORKFLOW STAGE 3: SYNTHESIZING FINAL AI RESPONSE ===")
        logger.info(f"🤖 Provider: {provider} | Model: {model} | Max Tokens: {max_tokens}")
        logger.info(f"📊 Web Search Results: {len(all_search_results)} results from {len(search_queries)} searches")
        
        # Build database context (portfolio/watchlist/activities/price history)
        try:
            db_context_text, _db_ctx = build_db_context(user_id=user_id, symbol=symbol_value if symbol else None, include_portfolio_summary=(prompt_type in ['portfolio_review','coin_analysis','market_analysis']))
        except Exception as e:
            logger.error(f"Error building database context: {e}")
            db_context_text, _db_ctx = "", {}
        if db_context_text:
            logger.info(f"📚 DB Context included (chars): {len(db_context_text)}")
        else:
            logger.info("📚 DB Context: none available")
        
        # Get appropriate Stage 3 (post-search) prompt based on prompt_type
        if prompt_type == 'manual':
            stage3_prompt_template = (user_ai_settings.get('copilot_chat_post') or '').strip()
        else:
            stage3_prompt_map = {
                'coin_analysis': ai_prompts.coin_analysis_post,
                'market_analysis': ai_prompts.market_analysis_post,
                'portfolio_review': ai_prompts.portfolio_review_post,
                'risk_assessment': ai_prompts.risk_assessment_post,
                'sentiment_analysis': ai_prompts.sentiment_prompt_post
            }
            stage3_prompt_template = stage3_prompt_map.get(prompt_type)
            stage3_prompt_template = (stage3_prompt_template or '').strip()

        if not stage3_prompt_template:
            raise ValueError(f"Missing Stage 3 prompt for {prompt_type}. Configure it in Settings.")
        
        # Substitute variables in Stage 3 prompt and include search context (handle {amount} placeholder)
        try:
            stage3_prompt = stage3_prompt_template.format(
                symbol=symbol_value,
                datetime=current_datetime,
                amount=amount_value
            )
        except KeyError:
            # If {amount} is not in the template, use only symbol and datetime
            stage3_prompt = stage3_prompt_template.format(
                symbol=symbol_value,
                datetime=current_datetime
            )
        
        # STAGE 3: AI synthesizes original prompt + web search results for final response
        risk_tolerance = user_ai_settings.get('ai_risk_tolerance', 'medium')
        
        final_system_prompt = f"""{stage3_prompt}

**Current Date/Time**: {current_datetime}
**User Risk Tolerance**: {risk_tolerance}

### USER DATA CONTEXT
{db_context_text if db_context_text else 'No user DB context available for this request.'}

{search_context}"""
        
        final_messages = [
            {
                "role": "system",
                "content": final_system_prompt
            },
            {
                "role": "user",
                "content": original_user_message
            }
        ]
        
        # Log the complete agentic workflow request
        log_ai_communication("REQUEST", user_id, provider, model, final_messages, prompt_type=f"{prompt_type}_agentic_final")
        
        # Make final AI request with synthesized context
        if provider == 'openai':
            final_response = openai_client.chat.completions.create(
                model=model,
                messages=final_messages,
                max_completion_tokens=max_tokens
            )
        elif provider == 'zai':
            final_response = zai_client.chat_completion(
                messages=final_messages,
                model=model,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            # Convert Z.AI response to OpenAI format
            if final_response and final_response.get('success'):
                content = final_response.get('content', '')
                
                # Create a mock OpenAI response object
                class MockResponse:
                    def __init__(self, content):
                        self.choices = [MockChoice(content)]
                        self.usage = MockUsage()
                
                class MockChoice:
                    def __init__(self, content):
                        self.message = MockMessage(content)
                
                class MockMessage:
                    def __init__(self, content):
                        self.content = content
                
                class MockUsage:
                    def __init__(self):
                        self.prompt_tokens = 0
                        self.completion_tokens = 0
                        self.total_tokens = 0
                
                final_response = MockResponse(content)
            else:
                raise Exception(f"Z.AI final stage error: {final_response.get('error', 'Unknown error')}")
        elif provider == 'perplexity':
            import requests
            def _px_try(models_to_try):
                last = None
                for m in models_to_try:
                    r = requests.post(
                        "https://api.perplexity.ai/chat/completions",
                        headers={"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"},
                        json={"model": m, "messages": final_messages, "max_tokens": max_tokens},
                        timeout=60
                    )
                    if r.status_code == 200:
                        return r
                    last = r
                return last
            px_models = [model, 'sonar-pro', 'sonar', 'sonar-reasoning']
            response = _px_try(px_models)
            if response is not None and response.status_code == 200:
                final_response = response.json()
            else:
                raise Exception(f"Perplexity API error: {response.text if response is not None else 'Unknown error'}")
        elif provider == 'gemini':
            import requests
            contents = []
            for msg in final_messages:
                role = msg.get("role", "user")
                if role == 'system':
                    role = 'user'
                elif role == 'assistant':
                    role = 'model'
                contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]} )

            def _gemini_try_models(models_to_try):
                last_err = None
                for m in models_to_try:
                    for api_ver in ['v1beta', 'v1', 'v1alpha']:
                        r = requests.post(
                            f"https://generativelanguage.googleapis.com/{api_ver}/models/{m}:generateContent?key={gemini_api_key}",
                            json={"contents": contents}
                        )
                        if r.status_code == 200:
                            return r
                        last_err = r
                return last_err

            final_models = [model, 'gemini-3-flash-preview', 'gemini-3-pro-preview']
            response = _gemini_try_models(final_models)
            if response is not None and response.status_code == 200:
                # Convert Gemini response to OpenAI-like format
                class MockResponse:
                    def __init__(self, content):
                        self.choices = [MockChoice(content)]
                        self.usage = MockUsage()
                
                class MockChoice:
                    def __init__(self, content):
                        self.message = MockMessage(content)
                
                class MockMessage:
                    def __init__(self, content):
                        self.content = content
                
                class MockUsage:
                    def __init__(self):
                        self.prompt_tokens = 0
                        self.completion_tokens = 0
                        self.total_tokens = 0
                final_response = MockResponse(response.json()['candidates'][0]['content']['parts'][0]['text'])
            else:
                raise Exception(f"Gemini API error: {response.text if response is not None else 'Unknown error'}")
        
        logger.info(f"=== AGENTIC WORKFLOW COMPLETE: 3-STAGE SUCCESS ({len(search_queries)} searches, {len(all_search_results)} results) ===")
        logger.info(f"🎯 FINAL SUCCESS - Provider: {provider} | Model: {model} | Search Engine: Brave Search API")
        
        # Log the successful agentic workflow response
        log_ai_communication("RESPONSE", user_id, provider, model, final_messages, response=final_response, prompt_type=f"{prompt_type}_agentic_complete")
        
        # Return both the response and the actual Stage 3 FULL prompt (with web search results) for AI Copilot
        return final_response, final_system_prompt  # Return response and the complete Stage 3 prompt with search results
        
    except Exception as e:
        # ROLLBACK FIRST to clear any failed transaction state
        try:
            with app.app_context():
                db.session.rollback()
        except:
            pass

        # Log the error
        log_ai_communication("RESPONSE", user_id, provider, model, messages, error=e, prompt_type=f"{prompt_type}_agentic_error")
        
        # --- NEW FALLBACK LOGIC ---
        if not is_fallback_attempt:
             user_ai_settings = get_user_ai_settings(username)
             fallback_provider = user_ai_settings.get('ai_provider_fallback')
             if fallback_provider:
                 logger.warning(f"🚨 Primary AI Provider ({provider}) failed: {e}. Retrying with Fallback Provider: {fallback_provider}...")
                 try:
                     return call_ai_with_web_search(
                         username, messages, model=None, user_id=user_id, 
                         prompt_type=prompt_type, symbol=symbol, 
                         include_db_context=include_db_context, amount=amount,
                         is_fallback_attempt=True
                     )
                 except Exception as fb_err:
                     logger.error(f"❌ Fallback AI attempt also failed: {fb_err}")
                     # Continue to existing hard fallback or raise
             else:
                 logger.warning(f"Optimization failed and no fallback provider configured: {e}")
        
        
        # If we get here and it's not a fallback attempt, the recursive call in the except block above should have handled it.
        # If it IS a fallback attempt and we're here, it means even the fallback failed.
        raise Exception(f"All AI request methods failed: {e}")

            


def get_coin_id_by_symbol(symbol, user_id):
    """Get coin_id from coins table by symbol and user_id"""
    try:
        with app.app_context():
            coin = Coin.query.filter_by(
                symbol=symbol.upper(), 
                user_id=user_id
            ).first()
            return coin.id if coin else None
    except Exception as e:
        logger.error(f"Error getting coin_id for {symbol}, user {user_id}: {e}")
        return None

def extract_symbol_from_body(body_text):
    """Extract cryptocurrency symbol from conversation body text"""
    if not body_text:
        return None
    
    import re
    # Common patterns for symbol extraction
    patterns = [
        r'\b([A-Z]{2,6})\s+cryptocurrency',  # "ETH cryptocurrency"
        r'analysis\s+for\s+([A-Z]{2,6})',    # "analysis for ETH"
        r'news\s+analysis\s+for\s+([A-Z]{2,6})',  # "news analysis for ETH"
        r'comprehensive\s+.*?\s+for\s+([A-Z]{2,6})',  # "comprehensive analysis for ETH"
        r'Please\s+provide.*?for\s+([A-Z]{2,6})',  # "Please provide analysis for ETH"
        r'\b([A-Z]{2,6})\s+market',          # "ETH market"
        r'\b([A-Z]{2,6})\s+price',           # "ETH price"
        r'about\s+([A-Z]{2,6})\s+',          # "about ETH"
        r'for\s+([A-Z]{2,6})\s+as\s+of',     # "for ETH as of"
        r'([A-Z]{2,6})\s+include',           # "ETH include"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            symbol = match.group(1).upper()
            # Validate it's a reasonable crypto symbol (2-6 chars, not common words)
            if 2 <= len(symbol) <= 6 and symbol not in ['THE', 'AND', 'FOR', 'WITH', 'FROM', 'THAT', 'THIS', 'WILL', 'HAVE', 'BEEN']:
                return symbol
    
    return None

def log_ai_conversation(user_id, prompt_type, sender, body, conversation_id=None, symbol=None):
    """Log AI conversation to database with coin_id linking using ORM"""
    try:
        from models import AIConversation
        
        now = get_eastern_now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%I:%M %p %Z')  # Render local timezone abbreviation
        created_at = now
        
        # Get coin_id if symbol is provided or can be extracted
        coin_id = None
        if symbol:
            coin_id = get_coin_id_by_symbol(symbol, user_id)
        else:
            # Try to extract symbol from body text
            extracted_symbol = extract_symbol_from_body(body)
            if extracted_symbol:
                coin_id = get_coin_id_by_symbol(extracted_symbol, user_id)
        
        new_conv = AIConversation(
            user_id=user_id,
            date=date_str,
            time=time_str,
            prompt_type=prompt_type,
            sender=sender,
            body=body,
            conversation_id=conversation_id,
            coin_id=coin_id,
            created_at=created_at
        )
        
        db.session.add(new_conv)
        db.session.commit()
        
        if coin_id:
            logger.info(f"AI conversation logged: {sender} - {prompt_type} - coin_id: {coin_id}")
        else:
            logger.info(f"AI conversation logged: {sender} - {prompt_type}")
        return True
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error logging AI conversation: {e}")
        return False

def get_ai_conversations_count(user_id, search_term=None, include_hidden=False, filter_sentiment=False, prompt_type=None):
    """Get total count of AI conversations for pagination with optional filtering using ORM"""
    try:
        from models import AIConversation
        query = AIConversation.query.filter_by(user_id=user_id)
        
        # Add hidden filter condition
        if not include_hidden:
            query = query.filter((AIConversation.is_hidden == 0) | (AIConversation.is_hidden.is_(None)))
            
        # Add sentiment/prompt filters
        if filter_sentiment:
            query = query.filter_by(prompt_type='sentiment_analysis')
        if prompt_type:
            query = query.filter_by(prompt_type=prompt_type)
            
        # Add search term if provided
        if search_term:
            query = query.filter(AIConversation.body.ilike(f'%{search_term}%'))
        
        return query.count()
        
    except Exception as e:
        logger.error(f"Error getting AI conversations count: {e}")
        return 0

def get_ai_conversations(user_id, limit=50, offset=0, search_term=None, include_hidden=False, filter_sentiment=False, prompt_type=None):
    """Get AI conversations for user with optional search and sentiment filtering using ORM"""
    try:
        logger.info(f"Getting AI conversations for user {user_id}, limit={limit}, offset={offset}, filter_sentiment={filter_sentiment}")
        from models import AIConversation
        
        query = AIConversation.query.filter_by(user_id=user_id)
        
        # Add hidden filter condition
        if not include_hidden:
            query = query.filter((AIConversation.is_hidden == 0) | (AIConversation.is_hidden.is_(None)))
            
        # Add sentiment/prompt filters
        if filter_sentiment:
            query = query.filter_by(prompt_type='sentiment_analysis')
        if prompt_type:
            query = query.filter_by(prompt_type=prompt_type)
            
        # Add search term if provided
        if search_term:
            query = query.filter(AIConversation.body.ilike(f'%{search_term}%'))
        
        # Add ordering and pagination
        # Use created_at for reliable sorting
        query = query.order_by(
            AIConversation.created_at.desc(),
            AIConversation.id.desc()
        ).limit(limit).offset(offset)
        
        rows = query.all()
        
        logger.info(f"Retrieved {len(rows)} rows from database")
        
        conversations = []
        for row in rows:
            # Convert date to string format to prevent Flask Date object serialization issues
            date_str = row.date.strftime('%Y-%m-%d') if hasattr(row.date, 'strftime') else str(row.date) if row.date else None
            conversations.append({
                'id': row.id,
                'date': date_str,
                'time': row.time,
                'prompt_type': row.prompt_type,
                'sender': row.sender,
                'body': row.body,
                'conversation_id': row.conversation_id,
                'created_at': row.created_at.strftime('%Y-%m-%d %H:%M:%S') if row.created_at and hasattr(row.created_at, 'strftime') else row.created_at
            })
        
        return conversations
        
    except Exception as e:
        logger.error(f"Error getting AI conversations: {e}")
        return []

def get_conversation_context(user_id, conversation_id=None, limit=10):
    """Get recent conversation context for AI responses using ORM"""
    try:
        from models import AIConversation
        
        query = AIConversation.query.filter_by(user_id=user_id)
        
        if conversation_id:
            query = query.filter_by(conversation_id=conversation_id)
            # Ascending order for context within a conversation
            query = query.order_by(AIConversation.id.asc())
        else:
            # Descending order for general recent context
            query = query.order_by(AIConversation.id.desc())
            
        rows = query.limit(limit).all()
        
        context = []
        for row in rows:
            context.append({
                'body': row.body,
                'sender': row.sender,
                'prompt_type': row.prompt_type
            })
        
        return context
        
    except Exception as e:
        logger.error(f"Error getting conversation context: {e}")
        return []

# Test route to verify Flask is working
def test_flask():
    return jsonify({"test": "Flask is working"})

# Ensure the login manager is properly attached
# app.login_manager = login_manager  # This line was causing issues





# Helper: latest conversation row fetcher for prompts/results
ALLOWED_WORKFLOW_TYPES = {'market_analysis', 'risk_assessment', 'portfolio_review'}

def _get_latest_conversation_row(user_id, prompt_type, sender):
    try:
        # Note: Simplified ordering to avoid PostgreSQL type mismatch between
        # timestamp (created_at) and text (date+time concatenation).
        # Ordering by id DESC ensures we always get the most recent row.
        query = AIConversation.query.filter_by(
            user_id=user_id, 
            prompt_type=prompt_type, 
            sender=sender
        ).filter(
            (AIConversation.is_hidden == 0) | (AIConversation.is_hidden == None)
        ).order_by(
            AIConversation.id.desc()
        )
        
        row = query.first()
        
        if not row:
            return None
        
        # Construct created_at timestamp in Eastern time as ISO string
        created_at = None
        if row.created_at:
            try:
                created_at = row.created_at.isoformat()
            except Exception:
                created_at = get_eastern_now_iso()
        elif row.date and row.time:
            try:
                # Parse the date and time into a datetime object
                # Date format: YYYY-MM-DD, Time format: HH:MM AM/PM EST
                date_str = row.date
                time_str = row.time.replace(' EST', '').strip()  # Remove EST suffix
                
                # Combine date and time
                dt_str = f"{date_str} {time_str}"
                
                # Parse the datetime
                dt = datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
                
                # Set timezone to Eastern
                from pytz import timezone
                eastern = timezone('US/Eastern')
                dt_eastern = eastern.localize(dt)
                
                # Convert to ISO format
                created_at = dt_eastern.isoformat()
                
            except Exception as e:
                logger.error(f"Error parsing date/time for conversation {row.id}: {e}")
                # Fallback: use current time
                created_at = get_eastern_now_iso()
        else:
            # Fallback: use current time
            created_at = get_eastern_now_iso()
        
        # Build a consistent dict
        return {
            'id': row.id,
            'user_id': row.user_id,
            'date': row.date,
            'time': row.time,
            'prompt_type': row.prompt_type,
            'sender': row.sender,
            'body': row.body,
            'conversation_id': row.conversation_id,
            'created_at': created_at
        }
    except Exception as e:
        logger.error(f"_get_latest_conversation_row error: {e}")
        return None

# View Prompt endpoints — return latest Stage 3 (user) prompt per section
@app.route('/api/ai/market-analysis-workflow-prompt', methods=['GET'])
@login_required
def api_market_analysis_workflow_prompt():
    row = _get_latest_conversation_row(current_user.id, 'market_analysis', 'user')
    if not row:
        return jsonify({
            'error': 'not_found',
            'message': 'No saved Market Analysis prompt found for current user. Run the workflow first.'
        }), 404
    return jsonify(row)

@app.route('/api/ai/risk-assessment-workflow-prompt', methods=['GET'])
@login_required
def api_risk_assessment_workflow_prompt():
    row = _get_latest_conversation_row(current_user.id, 'risk_assessment', 'user')
    if not row:
        return jsonify({
            'error': 'not_found',
            'message': 'No saved Risk Assessment prompt found for current user. Run the workflow first.'
        }), 404
    return jsonify(row)

@app.route('/api/ai/portfolio-review-workflow-prompt', methods=['GET'])
@login_required
def api_portfolio_review_workflow_prompt():
    row = _get_latest_conversation_row(current_user.id, 'portfolio_review', 'user')
    if not row:
        return jsonify({
            'error': 'not_found',
            'message': 'No saved Portfolio Review prompt found for current user. Run the workflow first.'
        }), 404
    return jsonify(row)

# Latest AI result per section — for dashboard rehydration after reload
@app.route('/api/ai/workflow-latest', methods=['GET'])
@login_required
def api_ai_workflow_latest():
    # type must be one of market_analysis|risk_assessment|portfolio_review
    t = (request.args.get('type') or '').strip().lower().replace('-', '_')
    if t not in ALLOWED_WORKFLOW_TYPES:
        return jsonify({'error': 'invalid_type', 'allowed': list(ALLOWED_WORKFLOW_TYPES)}), 400
    row = _get_latest_conversation_row(current_user.id, t, 'ai')
    if not row:
        return jsonify({'error': 'not_found', 'message': f'No AI result found for {t}. Run the workflow.'}), 404
    return jsonify(row)

# Pre-flight guard to prevent 500s if portfolio review prompts are missing
@app.before_request
def _precheck_portfolio_review_prompts():
    try:
        if request.path == '/api/ai/portfolio-review-workflow' and request.method == 'GET':
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                ai_prompts = get_user_ai_prompts(current_user.id)
                missing = []
                pre = getattr(ai_prompts, 'portfolio_review_pre', None) if ai_prompts else None
                post = getattr(ai_prompts, 'portfolio_review_post', None) if ai_prompts else None
                if not pre or not str(pre).strip():
                    missing.append('portfolio_review_pre')
                if not post or not str(post).strip():
                    missing.append('portfolio_review_post')
                if missing:
                    return jsonify({
                        'success': False,
                        'error': 'missing_prompt',
                        'missing': missing,
                        'message': 'Portfolio Review prompts are missing from credentials.db (ai_prompts). Please populate them in Settings.'
                    }), 400
    except Exception as e:
        # Do not block the request if guard fails; allow route to handle
        logger.error(f"_precheck_portfolio_review_prompts error: {e}")
        return None

# Create all tables for both databases
with app.app_context():
    # Check and repair database integrity BEFORE creating tables
    # logger.info("=== Starting Database Integrity Checks ===")
    # check_and_repair_database_integrity()
    # logger.info("=== Database Integrity Checks Complete ===")
    
    db.create_all()
    # Load SECRET_KEY from credentials DB if present (prod override)
    try:
        from sqlalchemy import text
        # Use default engine (PostgreSQL)
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT secret_key FROM credentials WHERE secret_key IS NOT NULL LIMIT 1")).fetchone()
            if row and row[0]:
                app.config['SECRET_KEY'] = row[0]
                logger.info("SECRET_KEY loaded from PostgreSQL")
            else:
                logger.warning("No SECRET_KEY found in PostgreSQL; using configured default")
    except Exception as e:
        logger.error(f"Failed to load SECRET_KEY from PostgreSQL: {e}")

    
    # AI prompts and desktop tokens tables are now handled by db.create_all() via models
    logger.info("Database tables ensured to exist via SQLAlchemy")

    # Ensure performance indexes exist (safe for SQLite with IF NOT EXISTS)
    try:
        from sqlalchemy import text
        engine_main = db.engine
        with engine_main.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_coins_user_id_symbol ON coins(user_id, symbol)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_watchlist_user_id_symbol ON watchlist(user_id, symbol)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_id_id ON notifications(user_id, id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_id_created_at ON notifications(user_id, created_at)"))
            # Add is_hidden column to notifications if it doesn't exist
            try:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN is_hidden INTEGER DEFAULT 0"))
                logger.info("Added is_hidden column to notifications")
            except Exception:
                # Column likely already exists; ignore error
                pass

        # Table creation is now handled by SQLAlchemy models and db.create_all()
        pass

        logger.info("DB indexes ensured (coins, watchlist, notifications, staking_orders)")
    except Exception as e:
        logger.error(f"Failed to ensure DB indexes: {e}")

def background_price_update_loop():
    """Background job to continuously update prices hourly for all non-hidden portfolio and watchlist coins"""
    logger.info("=== background_price_update_loop STARTED (HOURLY COLLECTION) ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                # Get all active users
                users = User.query.all()
                logger.info(f"[DEBUG] Users found: {[u.id for u in users]}")

                # Get all unique symbols from portfolios and watchlists (NON-HIDDEN ONLY)
                symbols = set()
                from sqlalchemy import text
                for user in users:
                    # Get portfolio symbols (only non-hidden coins with amount > 0)
                    portfolio = db.session.execute(
                        text("SELECT DISTINCT symbol FROM coins WHERE user_id = :user_id AND amount > 0 AND (hidden = FALSE OR hidden IS NULL)"),
                        {'user_id': user.id}
                    ).fetchall()

                    # Get watchlist symbols (only non-hidden watchlist items)
                    watchlist = db.session.execute(
                        text("SELECT DISTINCT symbol FROM watchlist WHERE user_id = :user_id AND (hidden = FALSE OR hidden IS NULL)"),
                        {'user_id': user.id}
                    ).fetchall()

                    # Add to symbols set
                    symbols.update([p[0] for p in portfolio] + [w[0] for w in watchlist])

                # Convert to list and remove any None values
                symbols = [s for s in symbols if s and s != 'USD']

                logger.info(f"[DEBUG] Found NON-HIDDEN symbols for hourly price update: {symbols}")

                if symbols:
                    # Update prices in batches to avoid rate limiting
                    batch_size = 10
                    current_timestamp = int(time.time())
                    
                    for i in range(0, len(symbols), batch_size):
                        batch = symbols[i:i + batch_size]
                        try:
                            # This will update the PRICE_CACHE with fresh prices (Binance first!)
                            prices = fetch_prices_binance_batch(batch)
                            # Update PRICE_CACHE and coins table with new prices
                            for symbol, price in prices.items():
                                if price > 0:
                                    PRICE_CACHE[symbol] = (price, time.time())
                                    
                                    # Store price history in Postgres
                                    try:
                                        # Check if exists to avoid duplicates (simulating INSERT OR IGNORE)
                                        exists = db.session.query(PriceHistory.id).filter_by(
                                            symbol=symbol.upper(), 
                                            timestamp=current_timestamp
                                        ).first()
                                        
                                        if not exists:
                                            history_entry = PriceHistory(
                                                symbol=symbol.upper(),
                                                price=price,
                                                timestamp=current_timestamp,
                                                exchange='binance'
                                            )
                                            db.session.add(history_entry)
                                            db.session.commit()
                                            logger.info(f"Stored {symbol} price history: {price} at {current_timestamp}")
                                    except Exception as history_error:
                                        logger.error(f"Error storing {symbol} price history: {history_error}")
                                        db.session.rollback()
                                    
                                    # Update the coins table with the latest price
                                    try:
                                        db.session.execute(
                                            text("""
                                                UPDATE coins 
                                                SET current = :price, 
                                                    updated_at = CURRENT_TIMESTAMP 
                                                WHERE symbol = :symbol 
                                                AND user_id IN (
                                                    SELECT DISTINCT user_id 
                                                    FROM coins 
                                                    WHERE symbol = :symbol 
                                                    AND amount > 0
                                                )
                                            """),
                                            {'price': price, 'symbol': symbol}
                                        )
                                        
                                        # Also update watchlist table with current price
                                        db.session.execute(
                                            text("""
                                                UPDATE watchlist 
                                                SET current_price = :price 
                                                WHERE symbol = :symbol 
                                                AND user_id IN (
                                                    SELECT DISTINCT user_id 
                                                    FROM watchlist 
                                                    WHERE symbol = :symbol
                                                )
                                            """),
                                            {'price': price, 'symbol': symbol}
                                        )
                                        
                                        db.session.commit()
                                        logger.debug(f"Updated {symbol} price to {price} in coins and watchlist tables")
                                    except Exception as update_error:
                                        db.session.rollback()
                                        logger.error(f"Error updating {symbol} price in tables: {update_error}")
                        except Exception as e:
                            logger.error(f"Error updating prices for batch {i//batch_size + 1}: {e}")

            try:
                iteration()
            except Exception as e:
                logger.error(f"background_price_update_loop iteration error: {e}")
            
            time.sleep(3600)


def portfolio_value_recorder_loop():
    """Background job to record portfolio value every hour"""
    logger.info("=== STARTING PORTFOLIO VALUE RECORDER LOOP ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                logger.info("Running portfolio value recording...")
                start_time = time.time()
                record_true_portfolio_value()
                elapsed = time.time() - start_time
                logger.info(f"Portfolio value recording completed in {elapsed:.2f} seconds")
                logger.info(f"Next run in 1 hour")
            
            try:
                iteration()
            except Exception as e:
                logger.error(f"portfolio_value_recorder_loop iteration error: {e}")
            
            time.sleep(3600)



def ai_dashboard_auto_refresh_loop():
    """Automatic AI Dashboard refresh: runs Market Analysis, Risk Assessment, Portfolio Review
    on user-defined schedule within the configured analysis window. Saves both Stage 3 prompt (user)
    and AI response (ai) to ai_conversations for each run.
    """
    logger.info("Starting AI dashboard auto-refresh loop")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    try:
                        username = user.username
                        settings = get_user_ai_settings(username)
                        if not settings.get('ai_enabled', True):
                            continue
                        start_str = settings.get('ai_analysis_window_start', '08:00')
                        end_str = settings.get('ai_analysis_window_end', '23:59')
                        if not is_user_analysis_window_active(start_str, end_str):
                            continue
                        # Only run if schedule allows
                        if not should_run_ai_analysis(user.id):
                            continue

                        # Execute all three sections sequentially with spacing to avoid rate limits
                        for ptype in ['market_analysis', 'risk_assessment', 'portfolio_review']:
                            try:
                                # Minimal original message; Stage 3 prompt comes from DB
                                messages = [{"role": "user", "content": f"Run {ptype.replace('_',' ')} workflow"}]
                                response, stage3_prompt = call_ai_with_web_search(
                                    username,
                                    messages,
                                    user_id=user.id,
                                    prompt_type=ptype
                                )
                                # Extract AI content
                                try:
                                    analysis_content = response.choices[0].message.content
                                except Exception:
                                    analysis_content = str(response)
                                # Persist conversations
                                log_ai_conversation(user.id, ptype, 'user', stage3_prompt)
                                log_ai_conversation(user.id, ptype, 'ai', analysis_content)
                                # Small delay between workflows to offset rate limits
                                time.sleep(5)
                            except Exception as e:
                                logger.error(f"Auto-refresh {ptype} failed for user {user.id}: {e}")
                                time.sleep(5)
                        # Update next run based on user's cache duration
                        update_ai_analysis_schedule(user.id)
                    except Exception as e:
                        logger.error(f"Auto-refresh loop error for user {getattr(user,'id', 'unknown')}: {e}")
                        try:
                            with app.app_context():
                                db.session.rollback()
                        except:
                            pass
            try:
                iteration()
            except Exception as e:
                logger.error(f"ai_dashboard_auto_refresh_loop iteration error: {e}")
            
            time.sleep(60)

def sentiment_analysis_background_loop():
    """Background job to run sentiment analysis for all non-hidden portfolio coins every 30 minutes"""
    import re
    logger.info("Starting sentiment analysis background job")
    
    # Wait 2 minutes before starting to let the app fully initialize
    time.sleep(120)
    
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                logger.info("Running automated sentiment analysis for all non-hidden portfolio coins...")
                
                # Get all users
                users = User.query.all()
                
                for user_row in users:
                    user_id = user_row.id
                    username = user_row.username
                    
                    try:
                        # Check if AI is enabled for this user
                        if not is_ai_enabled(username):
                            logger.info(f"Skipping sentiment analysis for {username} - AI disabled")
                            continue
                        
                        # Check if we're within the analysis window
                        settings = get_user_ai_settings(username)
                        start_str = settings.get('ai_analysis_window_start', '08:00')
                        end_str = settings.get('ai_analysis_window_end', '23:59')
                        if not is_user_analysis_window_active(start_str, end_str):
                            logger.info(f"Skipping sentiment analysis for {username} - outside analysis window ({start_str} - {end_str})")
                            continue

                        # Get Confidence and Notification settings
                        threshold_raw = settings.get('ai_confidence_threshold', 70)
                        try:
                            confidence_threshold = float(threshold_raw)
                            if confidence_threshold < 1: confidence_threshold *= 100
                        except:
                            confidence_threshold = 70
                        
                        notifications_enabled = settings.get('ai_notifications_enabled', True)
                        
                        # Get all non-hidden coins with non-zero amounts for this user
                        coins = Coin.query.filter_by(user_id=user_id, hidden=False).filter(Coin.amount > 0)\
                            .order_by((Coin.amount * Coin.current).desc()).all()
                        
                        if not coins:
                            logger.info(f"No portfolio coins found for user {username}")
                            continue
                        
                        logger.info(f"Running sentiment analysis for {len(coins)} coins for user {username}")
                        
                        # Process each coin sequentially
                        for coin_row in coins:
                            coin_id = coin_row.id
                            symbol = coin_row.symbol
                            amount = coin_row.amount
                            
                            try:
                                logger.info(f"Processing sentiment for {symbol} (User: {username})")
                                
                                # Get user's sentiment prompts
                                ai_prompts_obj = get_user_ai_prompts(user_id)
                                if not ai_prompts_obj: continue
                                
                                sentiment_pre_prompt = (ai_prompts_obj.sentiment_prompt_pre or "").strip()
                                sentiment_post_prompt = (ai_prompts_obj.sentiment_prompt_post or "").strip()
                                
                                if not sentiment_pre_prompt or not sentiment_post_prompt:
                                    continue

                                user_settings = get_user_ai_settings(username)
                                model = user_settings.get('ai_model', 'gpt-5')

                                # Replace placeholders
                                current_datetime = format_eastern_datetime(None, "%B %d, %Y at %I:%M %p EST")
                                try:
                                    sentiment_pre_prompt = sentiment_pre_prompt.format(symbol=symbol, datetime=current_datetime, amount=str(amount))
                                    sentiment_post_prompt = sentiment_post_prompt.format(symbol=symbol, datetime=current_datetime, amount=str(amount))
                                except:
                                    continue
                                
                                # Inject Confidence Instruction
                                sentiment_post_prompt += "\n\nIMPORTANT: You must include a confidence score in your response in the format: 'Confidence: XX%."

                                snapshot = calculate_symbol_snapshot(symbol)
                                if not snapshot:
                                    time.sleep(5)
                                    continue

                                snapshot_lines = [
                                    f"Holdings: {amount:.6f} {symbol}",
                                    f"Current price: ${snapshot['current_price']:.4f}",
                                    f"Technical signal: {snapshot['signal']} (confidence {snapshot['confidence']}%)"
                                ]
                                snapshot_text = "- " + "\n- ".join(snapshot_lines)
                                
                                sentiment_request = (
                                    "SENTIMENT_ANALYSIS_DATA\n"
                                    f"symbol: {symbol}\n"
                                    f"current_price: {snapshot['current_price']}\n"
                                    f"snapshot:\n{snapshot_text}\n"
                                )

                                # Run 3-stage agentic workflow
                                response, actual_stage3_prompt = call_ai_with_web_search(
                                    username=username,
                                    messages=[
                                        {"role": "system", "content": sentiment_post_prompt},
                                        {"role": "user", "content": sentiment_request}
                                    ],
                                    model=model,
                                    user_id=user_id,
                                    prompt_type="sentiment_analysis",
                                    symbol=symbol,
                                    amount=amount
                                )
                                
                                # Extract result
                                sentiment_response_text = ""
                                if hasattr(response, 'choices') and response.choices:
                                    sentiment_response_text = response.choices[0].message.content.strip()
                                elif isinstance(response, dict) and 'content' in response:
                                    sentiment_response_text = response['content'].strip()
                                else:
                                    sentiment_response_text = str(response).strip()

                                # Parse Confidence
                                confidence = 0
                                conf_match = re.search(r"Confidence:\s*(\d+)", sentiment_response_text, re.IGNORECASE)
                                if conf_match:
                                    confidence = int(conf_match.group(1))

                                # Parse Signal
                                sentiment_result = 'Hold'
                                valid_sentiments = ['Buy', 'Sell', 'Hold']
                                for s in valid_sentiments:
                                    if s.lower() in sentiment_response_text.lower()[:20]: # Check start of string mostly
                                        sentiment_result = s
                                        break
                                
                                # Update Database
                                coin = Coin.query.get(coin_id)
                                if coin:
                                    coin.sentiment = sentiment_result
                                    db.session.commit()
                                
                                # Log Conversation
                                log_ai_conversation(user_id, "sentiment_analysis", "user", actual_stage3_prompt, symbol=symbol)
                                time.sleep(0.1)
                                log_ai_conversation(user_id, "sentiment_analysis", "ai", sentiment_response_text, symbol=symbol)
                                
                                # ALERT LOGIC
                                if notifications_enabled and confidence >= confidence_threshold:
                                    # Send High Confidence Alert
                                    alert_msg = (
                                        f"🚀 AI TRADING SIGNAL: {symbol}\n"
                                        f"Signal: {sentiment_result.upper()}\n"
                                        f"Confidence: {confidence}%\n"
                                        f"Price: ${snapshot['current_price']:.4f}\n"
                                        f"Time: {current_datetime}"
                                    )
                                    send_telegram_message(username, alert_msg)
                                    logger.info(f"Sent AI Trading Alert for {symbol} ({sentiment_result} {confidence}%)")
                                
                                time.sleep(30)
                                
                            except Exception as coin_error:
                                logger.error(f"Error processing sentiment for {symbol}: {coin_error}")
                                continue
                        
                        time.sleep(60)
                        
                    except Exception as user_error:
                        logger.error(f"Error processing user {username}: {user_error}")
                        continue
                
                logger.info("Automated sentiment analysis cycle completed")

            try:
                iteration()
            except Exception as e:
                logger.error(f"sentiment_analysis_background_loop wrapper error: {e}")
            
            time.sleep(1800) # 30 minutes



def start_background_jobs(app):
    """Start all background jobs"""
    logger.info("Starting background jobs")

    # Start background threads
    global background_threads

    # FIXED: All background jobs now have proper session management via @safe_background_iteration
    
    # Start price update loop
    price_thread = threading.Thread(target=background_price_update_loop, daemon=True)
    price_thread.start()
    background_threads.append(price_thread)
    
    # Start Binance sync loop
    binance_sync_thread = threading.Thread(target=background_binance_sync_loop, daemon=True)
    binance_sync_thread.start()
    background_threads.append(binance_sync_thread)
    
    # Start portfolio alert loop
    portfolio_alert_thread = threading.Thread(target=portfolio_alert_loop, daemon=True)
    portfolio_alert_thread.start()
    background_threads.append(portfolio_alert_thread)
    
    # Start watchlist alert loop
    watchlist_alert_thread = threading.Thread(target=watchlist_alert_loop, daemon=True)
    watchlist_alert_thread.start()
    background_threads.append(watchlist_alert_thread)
    
    # Start volatility alert loop
    volatility_alert_thread = threading.Thread(target=volatility_alert_loop, daemon=True)
    volatility_alert_thread.start()
    background_threads.append(volatility_alert_thread)
    
    # Start portfolio value recorder (runs hourly)
    portfolio_recorder_thread = threading.Thread(target=portfolio_value_recorder_loop, daemon=True)
    portfolio_recorder_thread.start()
    background_threads.append(portfolio_recorder_thread)

    # Start AI dashboard auto refresh loop
    ai_auto_thread = threading.Thread(target=ai_dashboard_auto_refresh_loop, daemon=True)
    ai_auto_thread.start()
    background_threads.append(ai_auto_thread)
    
    # Start sentiment analysis loop (runs every 30 minutes)
    sentiment_analysis_thread = threading.Thread(target=sentiment_analysis_background_loop, daemon=True)
    sentiment_analysis_thread.start()
    background_threads.append(sentiment_analysis_thread)
    
    logger.info(f"Started {len(background_threads)} background threads")


def run_sentiment_analysis_for_user(user_id, username, force=False):
    """
    Run sentiment analysis for a specific user's coins.
    Returns the number of coins processed.
    """
    count = 0
    try:
        # Check if AI is enabled for this user
        if not is_ai_enabled(username) and not force:
            logger.info(f"Skipping sentiment analysis for {username} - AI disabled")
            return 0
        
        # Check if we're within the analysis window (skip check if forced)
        settings = get_user_ai_settings(username)
        if not force:
            start_str = settings.get('ai_analysis_window_start', '08:00')
            end_str = settings.get('ai_analysis_window_end', '23:59')
            if not is_user_analysis_window_active(start_str, end_str):
                logger.info(f"Skipping sentiment analysis for {username} - outside analysis window ({start_str} - {end_str})")
                return 0

        # Get Sentiment Frequency
        sentiment_freq_hours = settings.get('sentiment_analysis_frequency_hours', 24)
        if isinstance(sentiment_freq_hours, str):
            try:
                sentiment_freq_hours = float(sentiment_freq_hours)
            except:
                sentiment_freq_hours = 24
        
        # Get Confidence and Notification settings
        threshold_raw = settings.get('ai_confidence_threshold', 70)
        try:
            confidence_threshold = float(threshold_raw)
            if confidence_threshold < 1: confidence_threshold *= 100
        except:
            confidence_threshold = 70
        
        notifications_enabled = settings.get('ai_notifications_enabled', True)
        
        # Get all non-hidden coins with non-zero amounts for this user
        coins = Coin.query.filter_by(user_id=user_id, hidden=False).filter(Coin.amount > 0)\
            .order_by((Coin.amount * Coin.current).desc()).all()
        
        if not coins:
            logger.info(f"No portfolio coins found for user {username}")
            return 0
        
        logger.info(f"Running sentiment analysis for {len(coins)} coins for user {username} (Force: {force})")
        
        # Process each coin sequentially
        for coin_row in coins:
            coin_id = coin_row.id
            symbol = coin_row.symbol
            amount = coin_row.amount
            last_updated = coin_row.sentiment_last_updated
            
            # Check Frequency (skip check if forced)
            if not force and last_updated:
                elapsed = datetime.utcnow() - last_updated
                if elapsed.total_seconds() < (sentiment_freq_hours * 3600):
                    continue # Not due yet
            
            logger.info(f"Sentiment analysis due for {symbol} (Last: {last_updated}). Running...")
            
            try:
                logger.info(f"Processing sentiment for {symbol} (User: {username})")
                
                # Get user's sentiment prompts
                ai_prompts_obj = get_user_ai_prompts(user_id)
                if not ai_prompts_obj: continue
                
                sentiment_pre_prompt = (ai_prompts_obj.sentiment_prompt_pre or "").strip()
                sentiment_post_prompt = (ai_prompts_obj.sentiment_prompt_post or "").strip()
                
                if not sentiment_pre_prompt or not sentiment_post_prompt:
                    continue

                user_settings = get_user_ai_settings(username)
                model = user_settings.get('ai_model', 'gpt-5')

                # Replace placeholders
                current_datetime = format_eastern_datetime(None, "%B %d, %Y at %I:%M %p EST")
                try:
                    sentiment_pre_prompt = sentiment_pre_prompt.format(symbol=symbol, datetime=current_datetime, amount=str(amount))
                    sentiment_post_prompt = sentiment_post_prompt.format(symbol=symbol, datetime=current_datetime, amount=str(amount))
                except:
                    continue
                
                # Inject Confidence Instruction
                sentiment_post_prompt += "\n\nIMPORTANT: You must include a confidence score in your response in the format: 'Confidence: XX%'.\nAlso include 'Sentiment: Buy', 'Sentiment: Sell', or 'Sentiment: Hold'."

                snapshot = calculate_symbol_snapshot(symbol)
                if not snapshot:
                    time.sleep(5)
                    continue

                snapshot_lines = [
                    f"Holdings: {amount:.6f} {symbol}",
                    f"Current price: ${snapshot['current_price']:.4f}",
                    f"Technical signal: {snapshot['signal']} (confidence {snapshot['confidence']}%)"
                ]
                snapshot_text = "- " + "\n- ".join(snapshot_lines)
                
                sentiment_request = (
                    "SENTIMENT_ANALYSIS_DATA\n"
                    f"symbol: {symbol}\n"
                    f"current_price: {snapshot['current_price']}\n"
                    f"snapshot:\n{snapshot_text}\n"
                )

                # Run 3-stage agentic workflow
                response, actual_stage3_prompt = call_ai_with_web_search(
                    username=username,
                    messages=[
                        {"role": "system", "content": sentiment_post_prompt},
                        {"role": "user", "content": sentiment_request}
                    ],
                    model=model,
                    user_id=user_id,
                    prompt_type="sentiment_analysis",
                    symbol=symbol,
                    amount=amount
                )
                
                # Extract result
                sentiment_response_text = ""
                if hasattr(response, 'choices') and response.choices:
                    sentiment_response_text = response.choices[0].message.content.strip()
                elif isinstance(response, dict) and 'content' in response:
                    sentiment_response_text = response['content'].strip()
                else:
                    sentiment_response_text = str(response).strip()

                # Parse Confidence
                confidence = 0
                conf_match = re.search(r"Confidence:\s*(\d+)", sentiment_response_text, re.IGNORECASE)
                if conf_match:
                    confidence = int(conf_match.group(1))

                # Parse Signal (More robust search)
                sentiment_result = 'Hold'
                valid_sentiments = ['Buy', 'Sell', 'Hold']
                normalized_response = sentiment_response_text.lower()
                
                # Check for "Sentiment: X" pattern first
                explicit_match = re.search(r"Sentiment:\s*(Buy|Sell|Hold)", sentiment_response_text, re.IGNORECASE)
                if explicit_match:
                    sentiment_result = explicit_match.group(1).capitalize()
                else:
                    # Fallback: Check occurrence in first 100 chars
                    for s in valid_sentiments:
                        if s.lower() in normalized_response[:100]:
                            sentiment_result = s
                            break
                
                # Update Database
                coin = Coin.query.get(coin_id)
                if coin:
                    coin.sentiment = sentiment_result
                    coin.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
                    count += 1
                
                # Log Conversation
                log_ai_conversation(user_id, "sentiment_analysis", "user", actual_stage3_prompt, symbol=symbol)
                time.sleep(0.1)
                log_ai_conversation(user_id, "sentiment_analysis", "ai", sentiment_response_text, symbol=symbol)
                
                # ALERT LOGIC
                if notifications_enabled and confidence >= confidence_threshold:
                    # Send High Confidence Alert
                    alert_msg = (
                        f"🚀 AI TRADING SIGNAL: {symbol}\n"
                        f"Signal: {sentiment_result.upper()}\n"
                        f"Confidence: {confidence}%\n"
                        f"Price: ${snapshot['current_price']:.4f}\n"
                        f"Time: {current_datetime}"
                    )
                    send_telegram_message(username, alert_msg)
                    logger.info(f"Sent AI Trading Alert for {symbol} ({sentiment_result} {confidence}%)")
                
                time.sleep(5) # Delay between coins
                
            except Exception as coin_error:
                logger.error(f"Error processing sentiment for {symbol}: {coin_error}")
                try:
                    db.session.rollback()
                except:
                    pass

    except Exception as e:
        logger.error(f"Error in user sentiment analysis: {e}")
    
    return count

@app.route('/api/force-sentiment-analysis', methods=['POST'])
@login_required
def force_sentiment_analysis():
    """Force run sentiment analysis for current user"""
    try:
        # Run in a separate thread so valid response returns immediately
        def run_async():
            with app.app_context():
                run_sentiment_analysis_for_user(current_user.id, current_user.username, force=True)
        
        thread = threading.Thread(target=run_async)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Sentiment analysis started in background'
        })
    except Exception as e:
        logger.error(f"Force analysis failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def background_binance_sync_loop():
    """Background job to sync Binance transactions and balances every 5 minutes for all users"""
    logger.info("Starting Binance sync background job")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                # Get all users with Binance API keys
                results = db.session.query(User, Credential)\
                    .join(Credential, User.id == Credential.user_id)\
                    .filter(Credential._api_key.isnot(None), Credential._api_secret.isnot(None))\
                    .all()

                users = []
                for user, cred in results:
                    if cred and cred.api_key and cred.api_secret:
                        users.append(ObjectView({
                            'id': user.id,
                            'username': user.username, 
                            'api_key': cred.api_key, 
                            'api_secret': cred.api_secret
                        }))
                
                logger.info(f"Found {len(users)} users with Binance API keys")
                
                for user in users:
                    try:
                        username = user.username
                        api_key = user.api_key
                        api_secret = user.api_secret
                        
                        # Check if user has Binance credentials
                        if not api_key or not api_secret:
                            logger.warning(f"User {username} is missing Binance API credentials")
                            continue
                        
                        # Initialize Binance client with enhanced error handling
                        from binance.client import Client
                        from binance.exceptions import BinanceAPIException
                        
                        try:
                            logger.info(f"Creating Binance.US client for user {username}")
                            
                            # Initialize Binance.US client with timeout and retry settings
                            client = Client(
                                api_key=api_key,
                                api_secret=api_secret,
                                testnet=False,
                                tld='us',  # Use Binance.US only
                                requests_params={'timeout': 30}
                            )
                            
                            # Test the connection with a simple API call
                            try:
                                account_info = client.get_account()
                                logger.info(f"Binance.US client created successfully for user {username}")
                                logger.info(f"Account type: {account_info.get('accountType', 'N/A')}")
                                
                                # Log balance summary for debugging
                                balances = [b for b in account_info['balances'] if float(b['free']) > 0 or float(b['locked']) > 0]
                                logger.info(f"Found {len(balances)} non-zero balances for user {username}")
                                
                                # Sync account info (balances, trades, etc.)
                                logger.info(f"Starting account sync for user {username}")
                                from types import SimpleNamespace
                                cred_obj = SimpleNamespace(api_key=api_key, api_secret=api_secret)
                                sync_binance_account(user.id, username, client, cred_obj)
                                logger.info(f"Account sync completed for user {username}")
                                
                            except BinanceAPIException as api_err:
                                logger.error(f"Binance.US API error for user {username}: {api_err.status_code} - {api_err.message}")
                                continue
                                
                        except Exception as e:
                            logger.error(f"Failed to initialize Binance.US client for user {username}: {str(e)}", exc_info=True)
                            continue  # Skip this user and continue with next
                        
                    except Exception as e:
                        username = user.username if hasattr(user, 'username') else 'unknown'
                        logger.error(f"Error syncing Binance for user {username}: {str(e)}", exc_info=True)
                        if "code=-1003" in str(e) or "Too much request weight" in str(e):
                            logger.critical("🚨 BINANCE RATE LIMIT HIT! Backing off for 5 minutes...")
                            time.sleep(300)
                
                # Update auto alert cache after syncing all users
                update_auto_alert_cache()
            
            try:
                iteration()
            except Exception as e:
                logger.error(f"background_binance_sync_loop iteration error: {e}")
            
            time.sleep(300) # 5 minutes

    # Note: This loop handles the main sync. Individual user errors are caught inside.
    # If a global rate limit is hit, the inner try/except block needs to propagate it or handle it.
    
    # Let's add specific handling for -1003 (Rate Limit) to the outer loop if it bubbles up,
    # or ensure the inner loop waits long enough.
    # Currently, the inner loop catches everything. We need to be smarter.


def sync_binance_account(user_id, username, client, cred):
    """Synchronize Binance account data with rate limiting to prevent IP bans
    
    Binance.US Rate Limits (per documentation):
    - REQUEST_WEIGHT: 1200 per minute (weight-based)
    - ORDERS: 50 per 10 seconds, 160,000 per day
    - RAW_REQUESTS: 6100 per 5 minutes
    
    Key API weights:
    - get_account(): 10 weight
    - get_my_trades(): 10 weight per symbol
    - get_symbol_ticker(): 1 weight
    - get_exchange_info(): 10 weight
    """
    try:
        logger.info(f"Starting Binance sync for user {user_id} with conservative rate limiting")
        
        # Step 1: Get account info (10 weight)
        # logger.info("Fetching account information...")
        account_info = client.get_account()
        # logger.info(f"Retrieved account info with {len(account_info['balances'])} balance entries")
        
        # Wait 2 seconds to respect rate limits
        time.sleep(2)
        
        # Step 2: Get user's actual balances (non-zero holdings only)
        user_assets = []
        for balance in account_info['balances']:
            asset = balance['asset']
            free = float(balance['free'] or 0)
            locked = float(balance['locked'] or 0)
            total = free + locked
            
            if total > 0:  # Only include assets with actual balance
                user_assets.append(asset)
        
        # logger.info(f"Found {len(user_assets)} assets with non-zero balances: {user_assets}")
        
        # Step 3: Get recent trades ONLY for assets the user holds (conservative approach)
        all_trades = []
        for asset in user_assets:
            if asset in ['USDT', 'USD']:  # Skip USDT and USD as they're quote currencies
                continue
            
            # Try both USD and USDT pairs since Binance.US supports both
            trading_pairs = [f"{asset}USD", f"{asset}USDT"]
            
            for symbol in trading_pairs:
                try:
                    # logger.info(f"Fetching recent trades for {symbol}...")
                    
                    # Get only recent trades (last 100) to minimize API calls
                    # Using 100 instead of 1000 to be more conservative
                    trades = client.get_my_trades(symbol=symbol, limit=100)
                    
                    if trades:
                        all_trades.extend(trades)
                        # logger.info(f"Retrieved {len(trades)} trades for {symbol}")
                    # else:
                        # logger.info(f"No trades found for {symbol}")
                    
                    # Wait 3 seconds between trade requests to avoid rate limits
                    # This gives us 20 requests per minute, well under the limit
                    time.sleep(3)
                    
                except Exception as e:
                    error_msg = str(e)
                    if "1003" in error_msg or "Way too much request weight" in error_msg:
                        logger.error(f"Rate limit hit while fetching trades for {symbol}. Stopping trade sync.")
                        break
                    elif "Invalid symbol" in error_msg or "does not exist" in error_msg.lower():
                        logger.debug(f"Trading pair {symbol} doesn't exist, skipping...")
                        # Don't wait on invalid symbol errors
                        continue
                    else:
                        logger.warning(f"Error getting trades for {symbol}: {error_msg}")
                        # Still wait on error to avoid compounding rate limit issues
                        time.sleep(3)
        
        logger.info(f"Total trades retrieved: {len(all_trades)}")
        
        # Step 4: Process trades and update database
        if all_trades:
            logger.info("Processing trades...")
            process_binance_trades(user_id, all_trades)
        
        # Step 5: Update current balances in coins table from Binance
        logger.info("Updating current balances...")
        update_coins_from_binance_balances(user_id, account_info['balances'], client=client)
        
        # Step 6: Record portfolio total using dashboard-consistent calculation
        logger.info("Calculating portfolio total for history logging...")
        try:
            total_value = compute_portfolio_total_value(
                user_id,
                username=username,
                cred=cred
            )
            total_value = round(total_value, 2)

            # Step 7: Record portfolio value using SQLAlchemy ORM
            if total_value > 0:
                max_retries = 3
                retry_delay = 1
                
                for attempt in range(max_retries):
                    try:
                        # Use SQLAlchemy ORM instead of direct SQLite
                        from trading_models import PortfolioValueHistory
                        import time as time_mod
                        history_record = PortfolioValueHistory(
                            user_id=user_id,
                            value=total_value,
                            timestamp=datetime.utcnow(),
                            date=datetime.utcnow().strftime('%Y-%m-%d')
                        )
                        db.session.add(history_record)
                        db.session.commit()
                        
                        logger.info(f"Recorded portfolio value of ${total_value:.2f} for user {user_id}")
                        break  # Success, exit retry loop
                        
                    except Exception as db_error:
                        db.session.rollback()
                        if "locked" in str(db_error).lower() and attempt < max_retries - 1:
                            logger.warning(f"Database error, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"Failed to record portfolio value after {max_retries} attempts: {db_error}")
                            break
                
        except Exception as e:
            logger.error(f"Error calculating portfolio value: {str(e)}", exc_info=True)
        
        # Update trading order statuses and trigger notifications for filled orders
        sync_real_order_statuses_for_user(user_id, username, client)

        logger.info(f"Successfully completed Binance sync for user {user_id}")
        
    except Exception as e:
        error_msg = str(e)
        if "1003" in error_msg or "Way too much request weight" in error_msg:
            logger.error(f"Rate limit exceeded during Binance sync: {error_msg}")
            logger.error("Sync stopped to prevent IP ban. Will retry next cycle.")
        elif "418" in error_msg:
            logger.error(f"IP banned from Binance API: {error_msg}")
            logger.error("IP is currently banned. Sync will resume when ban expires.")
        else:
            logger.error(f"Error syncing Binance account: {error_msg}", exc_info=True)
        raise


def sync_real_order_statuses_for_user(user_id, username, client):
    """Fetch Binance order statuses and notify user when fills are detected."""
    try:
        orders = RealOrder.query.filter_by(user_id=user_id).all()
        if not orders:
            return

        final_statuses = {'CANCELED', 'REJECTED', 'EXPIRED'}
        polling_statuses = {'NEW', 'PARTIALLY_FILLED', 'PENDING_CANCEL', 'PENDING_CANCELLED', 'STOPPED', 'FILLED'}
        finalized_orders = []
        relevant_orders = []
        for order in orders:
            status = (order.status or '').upper()
            if not order.binance_order_id or not order.symbol:
                continue
            if status in final_statuses:
                if not order.fill_notified:
                    finalized_orders.append(order)
                continue
            if status not in polling_statuses:
                continue
            if order.fill_notified and status in ('FILLED',):
                continue
            relevant_orders.append(order)

        for order in finalized_orders:
            order.fill_notified = True

        if not relevant_orders:
            return

        logger.info(f"Checking {len(relevant_orders)} Binance orders for user {user_id} ({username})")

        any_updates = bool(finalized_orders)
        for order in relevant_orders:
            symbol = str(order.symbol or '').upper()
            order_id = int(order.binance_order_id)

            try:
                order_info = client.get_order(symbol=symbol, orderId=order_id)
            except Exception as api_err:
                logger.warning(f"Failed to fetch order {order_id} for user {user_id}: {api_err}")
                continue

            new_status = (order_info.get('status') or order.status or '').upper()
            executed_qty = float(order_info.get('executedQty') or 0)
            cumulative_quote = float(order_info.get('cummulativeQuoteQty') or 0)
            price = float(order_info.get('price') or order.price or 0)
            update_time = order_info.get('updateTime') or order_info.get('time')

            status_changed = new_status != (order.status or '').upper()
            qty_changed = abs(executed_qty - (order.executed_qty or 0.0)) > 1e-12
            quote_changed = abs(cumulative_quote - (order.cumulative_quote_qty or 0.0)) > 1e-8

            if status_changed:
                logger.info(
                    f"[ORDER] User {user_id} order {order_id} status {order.status} -> {new_status}"
                )
                order.status = new_status
                any_updates = True

            if qty_changed:
                order.executed_qty = executed_qty
                any_updates = True

            if quote_changed:
                order.cumulative_quote_qty = cumulative_quote
                any_updates = True

            if executed_qty > 0:
                fill_price = cumulative_quote / executed_qty if cumulative_quote > 0 else price
                order.avg_fill_price = fill_price

            if update_time:
                try:
                    order.updated_at = datetime.utcfromtimestamp(update_time / 1000)
                except Exception:
                    order.updated_at = datetime.utcnow()

            if new_status == 'FILLED':
                if not order.filled_at:
                    try:
                        order.filled_at = datetime.utcfromtimestamp(update_time / 1000) if update_time else datetime.utcnow()
                    except Exception:
                        order.filled_at = datetime.utcnow()
                    any_updates = True

                if not order.fill_notified:
                    quote_amount = cumulative_quote
                    if quote_amount <= 0 and executed_qty > 0:
                        quote_amount = executed_qty * (price or order.avg_fill_price or order.price or 0.0)

                    notify_order_fill(
                        order,
                        username=username,
                        executed_qty=executed_qty,
                        quote_qty=quote_amount,
                        fill_price=order.avg_fill_price
                    )
                    order.fill_notified = True
                    any_updates = True

            # Pause briefly to respect API rate limits
            time.sleep(0.15)

        if any_updates:
            db.session.commit()
        else:
            db.session.rollback()

    except Exception as exc:
        logger.error(f"Error syncing real order statuses for user {user_id}: {exc}", exc_info=True)
        db.session.rollback()

def process_binance_trades(user_id, trades):
    """Process Binance trades and update all_activities table for tax reporting"""
    if not trades:
        return
        
    # Use SQLAlchemy session
    processed_count = 0
    updated_assets = set()
    
    processed_count = 0
    updated_assets = set()
    
    for trade in trades:
        try:
            # Extract trade data
            trade_time = datetime.utcfromtimestamp(trade['time'] / 1000)
            date_str = trade_time.strftime('%Y-%m-%d %H:%M:%S')
            
            symbol = trade['symbol']
            # Remove USD or USDT from the end to get the asset symbol
            if symbol.endswith('USDT'):
                asset = symbol.replace('USDT', '')
            elif symbol.endswith('USD'):
                asset = symbol.replace('USD', '')
            else:
                asset = symbol  # Fallback if neither suffix found
            
            qty = float(trade['qty'])
            price = float(trade['price'])
            commission = float(trade.get('commission', 0))
            commission_asset = trade.get('commissionAsset', '')
            
            # Determine trade type
            trade_type = 'BUY' if trade['isBuyer'] else 'SELL'
            
            # Calculate proceeds/cost for tax reporting
            usd_value = qty * price
            
            if trade_type == 'BUY':
                proceeds = 0
                # Include commission if it's in USD or USDT (both are $1)
                cost_basis = usd_value + (commission if commission_asset in ['USDT', 'USD'] else 0)
                amount = qty
            else:  # SELL
                # Subtract commission if it's in USD or USDT
                proceeds = usd_value - (commission if commission_asset in ['USDT', 'USD'] else 0)
                cost_basis = 0
                amount = -qty  # Negative for sells
            
            # Create unique transaction ID
            txid = f"binance_{trade['id']}_{symbol}"
            
            # Check if transaction already exists
            existing_tx = AllActivity.query.filter_by(txid=txid).first()
            if not existing_tx:
                new_activity = AllActivity(
                    date=trade_time,
                    type=trade_type,
                    asset=asset,
                    amount=amount,
                    proceeds=proceeds,
                    cost_basis=cost_basis,
                    gain_loss=0,
                    fee=commission,
                    description=f"Binance {trade_type} {qty:.8f} {asset} @ ${price:.2f}",
                    txid=txid,
                    status='completed',
                    details=f"Trade ID: {trade['id']}, Order ID: {trade['orderId']}, Commission: {commission} {commission_asset}",
                    user_id=user_id,
                    avg_entry=price,
                    price_sold_at=price,
                    exchange='binance'
                )
                db.session.add(new_activity)
                processed_count += 1
                logger.info(f"✓ Recorded {trade_type} {qty:.8f} {asset} @ ${price:.2f} on {date_str}")
                updated_assets.add(asset)
            
        except Exception as e:
            logger.error(f"Error processing trade {trade.get('id', 'unknown')}: {str(e)}")
            continue
    
    # Commit all trades at once
    try:
        db.session.commit()
        logger.info(f"Successfully processed {processed_count} new Binance trades for user {user_id}")
        
        # Update average entry prices in coins table for affected assets
        if processed_count > 0:
            update_average_entry_prices(user_id, trades)
            for asset in updated_assets:
                try:
                    recalculate_asset_activity(
                        user_id=user_id,
                        asset=asset,
                        price_provider=lambda sym: fetch_binance_price(sym),
                        logger=logger
                    )
                except Exception as recalc_err:
                    logger.warning(f"Failed to recalculate activity for {asset}: {recalc_err}")
            
    except Exception as e:
        logger.error(f"Error committing trade data: {str(e)}")
        db.session.rollback()


def update_average_entry_prices(user_id, trades):
    """Update average entry prices in coins table based on new trades"""
    try:
        # Use SQLAlchemy session
        # Get unique assets from the trades
        assets = set()
        for trade in trades:
            symbol = trade['symbol']
            # Remove USD or USDT from the end to get the asset symbol
            if symbol.endswith('USDT'):
                asset = symbol.replace('USDT', '')
            elif symbol.endswith('USD'):
                asset = symbol.replace('USD', '')
            else:
                asset = symbol
            assets.add(asset)
        
        for asset in assets:
            try:
                coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()
                target_amount = coin.amount if coin else None

                # Calculate new average entry using FIFO with Reset on Zero Balance
                new_avg_entry, cost_basis, total_amount = calculate_avg_entry_fifo(
                    user_id,
                    asset,
                    target_amount=target_amount
                )
                
                if cost_basis >= 1.0 and total_amount > 0:
                    if coin:
                        coin.avg_entry = new_avg_entry
                        coin.updated_at = datetime.utcnow()
                        db.session.commit()
                        logger.info(
                            f"Updated {asset} average entry: ${new_avg_entry:.6f} "
                            f"(FIFO cost basis: ${cost_basis:.2f}, amount {total_amount:.8f})"
                        )
                else:
                    if coin:
                        coin.avg_entry = 0
                        coin.updated_at = datetime.utcnow()
                        db.session.commit()
                        logger.info(f"Reset {asset} average entry (cost basis ${cost_basis:.2f}, amount {total_amount:.8f})")
                        
            except Exception as e:
                logger.error(f"Error updating average entry for {asset}: {str(e)}")
                continue
        
        # No need to close connections manually with SQLAlchemy
        pass
        
    except Exception as e:
        logger.error(f"Error updating average entry prices: {str(e)}", exc_info=True)


def update_coins_from_binance_balances(user_id, balances, client=None):
    """Update coins table with current balances from Binance.US account and detect USD purchases"""
    try:
        from datetime import datetime, timedelta
        from models import Coin
        from trading_models import AllActivity
        
        updated_count = 0
        added_count = 0
        purchase_transactions = []

        # Track which assets we received from Binance (used to zero out stale rows)
        assets_from_binance = set()

        for balance in balances:
            asset = balance['asset']
            assets_from_binance.add(asset)

            free = float(balance['free'] or 0)
            locked = float(balance['locked'] or 0)
            total = free + locked

            try:
                # Check if coin already exists for this user using ORM
                existing_coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()

                # Special handling for ONT to ensure it's never hidden due to small balance
                if asset == 'ONT' and total > 0:
                    if existing_coin:
                        existing_coin.amount = total
                        existing_coin.hidden = False
                        existing_coin.auto_hidden = False
                        existing_coin.updated_at = datetime.utcnow()
                    else:
                        # Add ONT if missing
                        new_ont = Coin(
                            symbol=asset,
                            user_id=user_id,
                            amount=total,
                            hidden=False,
                            auto_hidden=False,
                            updated_at=datetime.utcnow(),
                            is_manual=False,
                            alert_enabled=True
                        )
                        db.session.add(new_ont)
                    
                    db.session.commit()
                    logger.info(f"Updated ONT balance to {total} for user {user_id}")
                    updated_count += 1
                    continue
                    
                # For other coins, maintain existing small balance behavior
                if total <= 0.00000001:
                    if existing_coin and abs(existing_coin.amount) > 0.00000001:
                        existing_coin.amount = 0
                        existing_coin.updated_at = datetime.utcnow()
                        db.session.commit()
                        logger.info(f"Set {asset} balance to 0 for user {user_id} (Binance reported zero balance)")
                        updated_count += 1
                    continue

                if existing_coin:
                    # Update existing coin's amount and detect USD purchases
                    old_amount = existing_coin.amount
                    amount_increase = total - old_amount

                    if amount_increase > 0.00000001:  # Significant increase detected
                        # Check if this increase came from a recent trade
                        # Look for trades in the last 10 minutes that could account for this increase
                        recent_cutoff = datetime.utcnow() - timedelta(minutes=10)

                        recent_trade_amount = db.session.query(db.func.sum(AllActivity.amount)).filter(
                            AllActivity.user_id == user_id,
                            AllActivity.asset == asset,
                            AllActivity.type == 'BUY',
                            AllActivity.date >= recent_cutoff,
                            AllActivity.status == 'completed'
                        ).scalar() or 0

                        # If the increase is significantly more than recent trades, it's likely a direct USD purchase
                        if amount_increase > recent_trade_amount + 0.00000001:
                            purchase_amount = amount_increase - recent_trade_amount

                            # Get current market price for fee calculation
                            try:
                                current_market_price = 0
                                price_ticker = None
                                
                                # Reuse passed client or create a public one with correct TLD
                                binance_client = client
                                if not binance_client:
                                    from binance.client import Client
                                    binance_client = Client(tld='us')
                                
                                # Try USDT then USD
                                for quote in ['USDT', 'USD']:
                                    try:
                                        price_ticker = binance_client.get_symbol_ticker(symbol=f"{asset}{quote}")
                                        if price_ticker:
                                            current_market_price = float(price_ticker['price'])
                                            break
                                    except:
                                        continue
                                
                                if current_market_price > 0:
                                    # Calculate cost basis (what user paid) - we'll estimate from current balance value
                                    # For direct purchases, we assume they paid slightly more than market price due to spread
                                    estimated_cost_per_unit = current_market_price * 1.01  # Assume 1% spread/fee
                                    cost_basis = purchase_amount * estimated_cost_per_unit

                                    # Calculate fee as the difference between what was paid vs market value
                                    market_value = purchase_amount * current_market_price
                                    fee = cost_basis - market_value

                                    # Create transaction record for direct USD purchase
                                    purchase_transaction = AllActivity(
                                        date=datetime.utcnow(),
                                        type='BUY',
                                        asset=asset,
                                        amount=purchase_amount,
                                        proceeds=0,  # This is a purchase, not a sale
                                        cost_basis=cost_basis,
                                        gain_loss=0,
                                        fee=fee,
                                        description=f"Binance USD BUY {purchase_amount:.8f} {asset} ${estimated_cost_per_unit:.2f}",
                                        txid=None,  # No trade ID for direct purchases
                                        status='completed',
                                        details="Direct USD purchase detected during balance sync",
                                        user_id=user_id,
                                        avg_entry=estimated_cost_per_unit,
                                        exchange='binance'
                                    )

                                    db.session.add(purchase_transaction)
                                    logger.info(f"🔍 Detected USD purchase: {purchase_amount:.8f} {asset} @ ${estimated_cost_per_unit:.2f}")
                                else:
                                    logger.warning(f"Could not find market price for {asset} to log USD purchase")

                            except Exception as e:
                                logger.warning(f"Could not calculate USD purchase details for {asset}: {str(e)}")

                    # Always update the balance from Binance to ensure accuracy
                    current_hidden = existing_coin.hidden
                    current_price = existing_coin.current

                    # Log the balance update for debugging
                    logger.info(f"Updating {asset} balance from Binance: {old_amount:.8f} → {total:.8f}")

                    # Compute USD value if price known
                    usd_value = None
                    try:
                        if current_price is not None:
                            usd_value = float(total) * float(current_price)
                    except Exception as e:
                        logger.warning(f"Error calculating USD value for {asset}: {str(e)}")
                        usd_value = None

                    # Always update the amount and timestamp from Binance
                    existing_coin.amount = total
                    existing_coin.updated_at = datetime.utcnow()

                    # Additionally, if coin is currently hidden and USD value now exceeds $1.00,
                    # auto-unhide it per requirement
                    if current_hidden and usd_value is not None and usd_value >= 1.00:
                        existing_coin.hidden = False
                        logger.info(f"Updated & unhid {asset}: {old_amount:.8f} → {total:.8f}, usd_value=${usd_value:.4f} (≥ $1.00)")
                    else:
                        logger.info(f"Updated {asset}: {old_amount:.8f} → {total:.8f}, hidden={current_hidden}")
                    
                    db.session.commit()
                    updated_count += 1
                else:
                    # Add new coin (this means user bought a new asset via direct USD purchase)
                    # Get current price to set initial values
                    try:
                        current_price = 0
                        price_ticker = None
                        
                        # Reuse passed client or create a public one with correct TLD
                        binance_client = client
                        if not binance_client:
                            from binance.client import Client
                            binance_client = Client(tld='us')
                        
                        # Try USDT then USD
                        for quote in ['USDT', 'USD']:
                            try:
                                price_ticker = binance_client.get_symbol_ticker(symbol=f"{asset}{quote}")
                                if price_ticker:
                                    current_price = float(price_ticker['price'])
                                    break
                            except:
                                continue
                        
                        if current_price > 0:
                            # For new coins, assume this is a direct USD purchase
                            # Estimate what user paid (slightly above market due to spread)
                            estimated_cost_per_unit = current_price * 1.01  # Assume 1% spread
                            cost_basis = total * estimated_cost_per_unit
                            
                            # Calculate fee as spread difference
                            market_value = total * current_price
                            fee = cost_basis - market_value
                            
                            # Calculate average entry from recent transactions (if any exist)
                            avg_entry_query = db.session.query(db.func.avg(AllActivity.avg_entry)).filter(
                                AllActivity.user_id == user_id,
                                AllActivity.asset == asset,
                                AllActivity.type == 'BUY'
                            )
                            
                            avg_entry = avg_entry_query.scalar() or estimated_cost_per_unit
                            
                            # Insert new coin using ORM
                            new_coin = Coin(
                                symbol=asset,
                                user_id=user_id,
                                current=current_price,
                                amount=total,
                                avg_entry=avg_entry,
                                initial_value=total * avg_entry,
                                purchase_date=datetime.utcnow().strftime('%Y-%m-%d'),
                                is_manual=False,
                                alert_enabled=True,
                                hidden=False,
                                updated_at=datetime.utcnow()
                            )
                            db.session.add(new_coin)
                            
                            # Create transaction record for this new asset purchase
                            new_purchase = AllActivity(
                                date=datetime.utcnow(),
                                type='BUY',
                                asset=asset,
                                amount=total,
                                proceeds=0,
                                cost_basis=cost_basis,
                                gain_loss=0,
                                fee=fee,
                                description=f"Binance USD BUY {total:.8f} {asset} ${estimated_cost_per_unit:.2f}",
                                txid=None,
                                status='completed',
                                details="Direct USD purchase detected during balance sync",
                                user_id=user_id,
                                avg_entry=estimated_cost_per_unit,
                                exchange='binance'
                            )
                            db.session.add(new_purchase)
                            db.session.commit()
                            
                            added_count += 1
                            logger.info(f"Added new coin {asset}: {total:.8f} @ ${avg_entry:.2f} (USD purchase detected)")
                        else:
                            # If no price found, we still want to add the coin with 0 price if it has balance
                            new_coin = Coin(
                                symbol=asset,
                                user_id=user_id,
                                current=0,
                                amount=total,
                                avg_entry=0,
                                purchase_date=datetime.utcnow().strftime('%Y-%m-%d'),
                                is_manual=False,
                                alert_enabled=True,
                                hidden=False,
                                updated_at=datetime.utcnow()
                            )
                            db.session.add(new_coin)
                            db.session.commit()
                            added_count += 1
                            logger.info(f"Added new coin {asset}: {total:.8f} (Price not found, set to 0)")
                        
                    except Exception as e:
                        db.session.rollback()
                        logger.warning(f"Could not add new coin {asset}: {str(e)}")
                        continue
                        
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating coin {asset}: {str(e)}")
                continue
        
        # Zero out any existing coins for this user that were NOT present in the
        # Binance balances response.
        try:
            stale_coins = Coin.query.filter(
                Coin.user_id == user_id,
                Coin.symbol.notin_(assets_from_binance),
                Coin.amount > 0.00000001
            ).all()
            
            for coin in stale_coins:
                coin.amount = 0
                coin.updated_at = datetime.utcnow()
                logger.info(f"Set {coin.symbol} balance to 0.0 for user {user_id} (absent from Binance balances)")
                updated_count += 1
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error zeroing absent assets for user {user_id}: {e}")

        logger.info(f"Coins table updated: {updated_count} updated, {added_count} added for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error updating coins from Binance balances: {str(e)}", exc_info=True)


def portfolio_alert_loop():
    logger.info("=== portfolio_alert_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    coins = Coin.query.filter_by(user_id=user.id, alert_enabled=True, hidden=False).all()
                    for coin in coins:
                        symbol = (coin.symbol or '').upper()
                        price = None
                        
                        # Try rate-limited Binance API call
                        if binance_rate_limiter.can_call(symbol):
                            try:
                                price = fetch_binance_price(symbol)
                                if price and price > 0:
                                    binance_rate_limiter.record_call(symbol)
                                    coin.current = price
                                    db.session.commit()
                                else:
                                    binance_rate_limiter.record_failure(symbol)
                                    price = coin.current if coin.current and coin.current > 0 else None
                            except Exception as fetch_err:
                                binance_rate_limiter.record_failure(symbol)
                                logger.warning(f"Binance API failed for {symbol}: {fetch_err}")
                                price = coin.current if coin.current and coin.current > 0 else None
                        else:
                            # Rate limit active, use cached price from DB
                            price = coin.current if coin.current and coin.current > 0 else None
                        
                        if price is None or coin.avg_entry is None:
                            continue

                        # Calculate thresholds
                        down_threshold = None
                        up_threshold = None
                        if coin.custom_lower_type == "%":
                            if coin.custom_lower_pct is not None:
                                down_threshold = round(coin.avg_entry * (1 - float(coin.custom_lower_pct) / 100), 6)
                        elif coin.custom_lower_type == "Auto%":
                            if coin.custom_lower_pct is not None:
                                down_threshold = round(coin.avg_entry * (1 - float(coin.custom_lower_pct) / 100), 6)
                        elif coin.custom_lower_type == "#":
                            if coin.custom_lower_val is not None:
                                down_threshold = round(float(coin.custom_lower_val), 6)

                        if coin.custom_upper_type == "%":
                            if coin.custom_upper_pct is not None:
                                up_threshold = round(coin.avg_entry * (1 + float(coin.custom_upper_pct) / 100), 6)
                        elif coin.custom_upper_type == "Auto%":
                            if coin.custom_upper_pct is not None:
                                up_threshold = round(coin.avg_entry * (1 + float(coin.custom_upper_pct) / 100), 6)
                        elif coin.custom_upper_type == "#":
                            if coin.custom_upper_val is not None:
                                up_threshold = round(float(coin.custom_upper_val), 6)

                        # Check for price crossing thresholds
                        last_alert_down = get_last_alert_state(user.id, symbol, "down", "portfolio", _normalize_threshold(down_threshold))
                        if down_threshold is not None:
                            if price <= down_threshold:
                                if last_alert_down not in ("saved", "sent"):
                                    save_notification_record(user.id, coin.id, 'coin', symbol, 'down', 'price', down_threshold, price, price)
                                    set_last_alert_state(user.id, symbol, "down", "saved", "portfolio", _normalize_threshold(down_threshold))
                                if last_alert_down != "sent":
                                    sent = send_telegram_alert(user.username, symbol, price, "down", down_threshold)
                                    if sent:
                                        set_last_alert_state(user.id, symbol, "down", "sent", "portfolio", _normalize_threshold(down_threshold))
                            elif last_alert_down in ("saved", "sent") and price > down_threshold * 1.01:
                                set_last_alert_state(user.id, symbol, "down", None, "portfolio", _normalize_threshold(down_threshold))

                        # UP alert logic
                        last_alert_up = get_last_alert_state(user.id, symbol, "up", "portfolio", _normalize_threshold(up_threshold))
                        if up_threshold is not None:
                            if price >= up_threshold:
                                if last_alert_up not in ("saved", "sent"):
                                    save_notification_record(user.id, coin.id, 'coin', symbol, 'up', 'price', up_threshold, price, price)
                                    set_last_alert_state(user.id, symbol, "up", "saved", "portfolio", _normalize_threshold(up_threshold))
                                if last_alert_up != "sent":
                                    sent = send_telegram_alert(user.username, symbol, price, "up", up_threshold)
                                    if sent:
                                        set_last_alert_state(user.id, symbol, "up", "sent", "portfolio", _normalize_threshold(up_threshold))
                            elif last_alert_up in ("saved", "sent") and price < up_threshold * 0.99:
                                set_last_alert_state(user.id, symbol, "up", None, "portfolio", _normalize_threshold(up_threshold))

            try:
                iteration()
            except Exception as e:
                logger.error(f"portfolio_alert_loop iteration error: {e}")
            
            time.sleep(120)




def watchlist_alert_loop():
    logger.info("=== watchlist_alert_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    watchlist_coins = WatchlistCoin.query.filter_by(user_id=user.id, alert_enabled=True, hidden=False).all()
                    if not watchlist_coins:
                        continue
                    for coin in watchlist_coins:
                        symbol = (coin.symbol or '').upper()
                        price = None
                        
                        # Try rate-limited Binance API call
                        if binance_rate_limiter.can_call(symbol):
                            try:
                                price = fetch_binance_price(symbol)
                                if price and price > 0:
                                    binance_rate_limiter.record_call(symbol)
                                    # Update current price if possible (Watchlist table usually doesn't have 'current' but some schemas do)
                                    # Adjust based on schema - watchlist often uses current_price
                                    try:
                                        coin.current_price = price
                                        db.session.commit()
                                    except:
                                        pass
                                else:
                                    binance_rate_limiter.record_failure(symbol)
                                    price = getattr(coin, 'current_price', None)
                            except Exception as fetch_err:
                                binance_rate_limiter.record_failure(symbol)
                                logger.warning(f"Binance API failed for watchlist {symbol}: {fetch_err}")
                                price = getattr(coin, 'current_price', None)
                        else:
                            price = getattr(coin, 'current_price', None)
                            
                        if price is None:
                            continue

                        # DOWN alert for watchlist
                        if coin.down_alert is not None:
                            wl_down = round(float(coin.down_alert), 6)
                            last_state = get_last_alert_state(user.id, symbol, "down", source="watchlist", threshold=wl_down)
                            if price <= wl_down:
                                if last_state not in ("saved", "sent"):
                                    save_notification_record(user.id, coin.id, 'watchlist', symbol, 'down', '#', wl_down, price, price)
                                    set_last_alert_state(user.id, symbol, "down", "saved", source="watchlist", threshold=wl_down)
                                if last_state != "sent":
                                    sent = send_telegram_alert(user.username, symbol, price, "down", wl_down)
                                    if sent:
                                        set_last_alert_state(user.id, symbol, "down", "sent", source="watchlist", threshold=wl_down)
                            elif last_state in ("saved", "sent") and price > wl_down * 1.01:
                                set_last_alert_state(user.id, symbol, "down", None, source="watchlist", threshold=wl_down)

                        # UP alert for watchlist
                        if coin.up_alert is not None:
                            wl_up = round(float(coin.up_alert), 6)
                            last_state = get_last_alert_state(user.id, symbol, "up", source="watchlist", threshold=wl_up)
                            if price >= wl_up:
                                if last_state not in ("saved", "sent"):
                                    save_notification_record(user.id, coin.id, 'watchlist', symbol, 'up', '#', wl_up, price, price)
                                    set_last_alert_state(user.id, symbol, "up", "saved", source="watchlist", threshold=wl_up)
                                if last_state != "sent":
                                    sent = send_telegram_alert(user.username, symbol, price, "up", wl_up)
                                    if sent:
                                        set_last_alert_state(user.id, symbol, "up", "sent", source="watchlist", threshold=wl_up)
                            elif last_state in ("saved", "sent") and price < wl_up * 0.99:
                                set_last_alert_state(user.id, symbol, "up", None, source="watchlist", threshold=wl_up)
            try:
                iteration()
            except Exception as e:
                logger.error(f"watchlist_alert_loop iteration error: {e}")
            
            time.sleep(120)



def volatility_alert_loop():
    logger.info("=== volatility_alert_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    credentials = get_user_credentials(user.username)
                    if not credentials or not credentials.api_key or not credentials.api_secret:
                        continue

                    # Local import to avoid circular dependencies if any
                    from binance.client import Client
                    client = Client(credentials.api_key, credentials.api_secret, tld='us')

                    # Check portfolio coins
                    coins = Coin.query.filter(
                        Coin.user_id == user.id,
                        Coin.alert_enabled == True,
                        Coin.volatility_pct != None,
                        Coin.volatility_pct > 0
                    ).all()
                    for coin in coins:
                        check_coin_volatility(user, coin, client, 'portfolio')

                    # Check watchlist coins
                    watchlist_coins = WatchlistCoin.query.filter(
                        WatchlistCoin.user_id == user.id,
                        WatchlistCoin.alert_enabled == True,
                        WatchlistCoin.volatility_pct != None,
                        WatchlistCoin.volatility_pct > 0
                    ).all()
                    for coin in watchlist_coins:
                        check_coin_volatility(user, coin, client, 'watchlist')

            try:
                iteration()
            except Exception as e:
                logger.error(f"volatility_alert_loop iteration error: {e}")
            
            time.sleep(120)



def check_coin_volatility(user, coin, client, table_type):
    symbol = (coin.symbol or '').upper()
    if not symbol.endswith('USD'):
        symbol += 'USD'

    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=1)
        if not klines:
            return

        kline = klines[0]
        open_price = float(kline[1])
        high_price = float(kline[2])
        low_price = float(kline[3])
        close_price = float(kline[4])

        volatility = ((high_price - low_price) / low_price) * 100

        if volatility >= coin.volatility_pct:
            now = datetime.utcnow()
            if coin.last_volatility_alert_time and (now - coin.last_volatility_alert_time) < timedelta(hours=1):
                return  # Don't spam alerts

            direction = "up" if close_price > open_price else "down"
            message = f"{coin.symbol} has high volatility of {volatility:.2f}% in the last minute."

            save_notification_record(
                user_id=user.id,
                coin_id=coin.id,
                table_type=table_type,
                symbol=coin.symbol,
                direction=direction,
                threshold_type='volatility',
                percent_value=volatility,
                crossing_price=close_price,
                current_price=close_price,
                category='volatility_alert',
                message=message
            )

            send_telegram_alert(
                username=user.username,
                symbol=coin.symbol,
                price=close_price,
                direction=f"volatility {direction}",
                threshold=f"{volatility:.2f}%"
            )

            coin.last_volatility_alert_time = now
            db.session.commit()

    except Exception as e:
        logger.error(f"Error checking volatility for {symbol}: {e}")




def update_auto_alerts_for_portfolio():
    with app.app_context():
        coins = Coin.query.all()
        updated = 0
        for coin in coins:
            symbol = coin.symbol.upper()
            # DOWN alert - use custom_lower_pct for Auto% type
            if coin.custom_lower_type == "Auto%":
                val = calculate_auto_alert(symbol, "down", coin.avg_entry)
                coin.custom_lower_pct = val  # Store in custom_lower_pct, not custom_lower_val
                updated += 1
            # UP alert - use custom_upper_pct for Auto% type
            if coin.custom_upper_type == "Auto%":
                val = calculate_auto_alert(symbol, "up", coin.avg_entry)
                coin.custom_upper_pct = val  # Store in custom_upper_pct, not custom_upper_val
                updated += 1
        db.session.commit()
        logger.info(f"[update_auto_alerts_for_portfolio] Updated {updated} auto alert values.")

NEWS_SENTIMENT_CACHE = {}  # {symbol: (sentiment, timestamp)}
NEWS_SENTIMENT_CACHE_TTL = 600  # 10 minutes


def to_eastern(date_str):
    """Convert a UTC date string (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS) to US/Eastern date string."""
    if not date_str:
        return None
    try:
        if len(date_str) > 10:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        else:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Assume input is UTC; do a fixed offset conversion to Eastern based on UTC offset rules is hard
        # For lint safety and to avoid optional dependencies here, return the original date part.
        return dt.strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"to_eastern error: {e}", exc_info=True)
        return date_str
    
#news

def can_use_news_api(username):
    now = time.time()
    with NEWS_API_LOCK:
        until = NEWS_API_DISABLED_UNTIL.get(username)
        if until and now < until:
            return False, until
        reqs = NEWS_API_REQUEST_LOG.get(username, [])
        reqs = [t for t in reqs if now - t < NEWS_API_WINDOW_SECONDS]
        NEWS_API_REQUEST_LOG[username] = reqs
        if len(reqs) >= NEWS_API_RATE_LIMIT:
            NEWS_API_DISABLED_UNTIL[username] = now + NEWS_API_WINDOW_SECONDS
            return False, now + NEWS_API_WINDOW_SECONDS
        return True, None

def log_news_api_request(username):
    now = time.time()
    with NEWS_API_LOCK:
        NEWS_API_REQUEST_LOG.setdefault(username, []).append(now)

def fetch_news_sentiment(symbol, username=None):
    """
    Fetches recent news for the symbol and returns an average sentiment polarity.
    Returns a float: -1 (very negative) to +1 (very positive), or None if rate limited or no key.
    """
    now = time.time()
    cached = NEWS_SENTIMENT_CACHE.get(symbol.upper())
    if cached and now - cached[1] < NEWS_SENTIMENT_CACHE_TTL:
        return cached[0]
    try:
        # Get per-user News API key
        news_api_key = NEWS_API_KEY
        if username:
            # Check if username is actually a user_id (int) or username (str)
            # This is a robust patch to handle both cases without changing all callers immediately
            try:
                # If it looks like an ID or we can resolve it
                user = User.query.filter_by(username=username).first()
                if user:
                    cred = Credential.query.filter_by(user_id=user.id).first()
                else:
                    # Fallback
                    cred = Credential.query.filter_by(username=username).first()
            except Exception:
                 cred = Credential.query.filter_by(username=username).first()

            if cred and cred.news_api:
                news_api_key = cred.news_api
        # If no News API key, treat as optional and return None (N/A)
        if not news_api_key:
            NEWS_SENTIMENT_CACHE[symbol.upper()] = (None, now)
            return None
        # Rate limit check
        if username:
            can_use, disabled_until = can_use_news_api(username)
            if not can_use:
                NEWS_SENTIMENT_CACHE[symbol.upper()] = (None, now)
                return None
            log_news_api_request(username)
        url = f"https://newsapi.org/v2/everything?q={symbol}+crypto&language=en&sortBy=publishedAt&pageSize=10&apiKey={news_api_key}"
        resp = requests.get(url, timeout=10)
        articles = resp.json().get("articles", [])
        if not articles:
            NEWS_SENTIMENT_CACHE[symbol.upper()] = (0, now)
            return 0  # Neutral if no news
        sentiments = []
        for art in articles:
            text = (art.get("title", "") or "") + " " + (art.get("description", "") or "")
            blob = TextBlob(text)
            sentiments.append(blob.sentiment.polarity)
        avg_sent = sum(sentiments) / len(sentiments)
        NEWS_SENTIMENT_CACHE[symbol.upper()] = (avg_sent, now)
        return avg_sent  # -1 to 1
    except Exception as e:
        logger.error(f"News sentiment fetch failed for {symbol}: {e}")
        NEWS_SENTIMENT_CACHE[symbol.upper()] = (0, now)
        return 0

def get_coin_sentiment(symbol, coin=None, current_price=None, username=None):
    """
    Returns the AI-generated sentiment for a coin from the coins table.
    The sentiment is determined by the 3-stage agentic AI workflow and stored in the coins table.
    Valid values are 'Buy', 'Sell', or 'Hold'.
    """
    try:
        if not coin:
            # If coin object not provided, try to get it from the database
            coin = db.session.query(Coin).filter_by(symbol=symbol).first()
            if not coin:
                return "Hold"  # Default if coin not found
        
        # Return the AI-generated sentiment if available
        if hasattr(coin, 'sentiment') and coin.sentiment in ['Buy', 'Sell', 'Hold']:
            return coin.sentiment
            
        # Fallback to 'Hold' if no AI sentiment is available yet
        return "Hold"
        
    except Exception as e:
        logger.error(f"Error in get_coin_sentiment for {symbol}: {e}")
        return "Hold"  # Default on error



def fetch_prices_binance(symbols):
    """
    Fetch prices for multiple symbols at once using Binance API only.
    Returns a dict: {symbol: price}
    """
    try:
        from binance.client import Client
        
        # Get Binance API credentials from environment
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            logger.error("Binance API credentials not found in environment")
            return {}
        
        client = Client(api_key, api_secret, tld='us')
        result = {}
        
        for sym in symbols:
            try:
                symbol_pair = f"{sym}USDT"
                ticker = client.get_symbol_ticker(symbol=symbol_pair)
                price = float(ticker['price'])
                
                # Cache the price
                PRICE_CACHE[sym.upper()] = (price, time.time())
                result[sym.upper()] = price
                
                # Small delay to avoid rate limits
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"Failed to get Binance price for {sym}: {e}")
                continue
        
        return result
        
    except Exception as e:
        logger.error(f"Binance batch price fetch failed: {e}")
        return {}
    
def get_watchlist_action(symbol):
    prices = get_last_7d_prices(symbol)
    if not prices or len(prices) < 3:
        return "Watch"  # Not enough data

    pct_change = (prices[-1] - prices[0]) / prices[0] * 100
    min_price = min(prices)
    min_index = prices.index(min_price)
    # Simple logic:
    # - "Avoid" if price is up >10% in 7d or hit new high in last 2 days
    # - "Buy" if price is near 7d low and has started to rebound in last 1-2 days
    # - Otherwise "Watch"

    if pct_change > 10 or prices[-1] >= max(prices[-3:]):
        return "Avoid"
    if min_index >= len(prices) - 3 and prices[-1] > min_price * 1.03:
        return "Buy"
    return "Watch"

def backfill_7d_prices(symbols):
    """
    Backfill the last 7 days of hourly price data for each symbol into price_history.
    Uses Binance as primary source.
    """
    from datetime import datetime
    
    try:
        from binance.client import Client
        
        with app.app_context():
            # Get Binance API credentials from credentials database
            # We'll use the first available credential that has API keys
            cred = Credential.query.filter(Credential._api_key.isnot(None), Credential._api_secret.isnot(None)).first()
            
            if not cred:
                logger.error("Binance API credentials not found in credentials table for price backfill")
                return

            api_key = cred.api_key
            api_secret = cred.api_secret
            
            if not api_key or not api_secret:
                logger.error("Binance API credentials are empty for price backfill")
                return
            
            client = Client(api_key, api_secret, tld='us')
            
            for symbol in symbols:
                try:
                    symbol_pair = f"{symbol}USDT"
                    
                    # Get 7 days of kline data (1 hour intervals)
                    klines = client.get_historical_klines(symbol_pair, Client.KLINE_INTERVAL_1HOUR, "7 days ago UTC")
                    
                    for kline in klines:
                        timestamp = int(kline[0] // 1000)  # Convert ms to seconds
                        close_price = float(kline[4])  # Close price
                        
                        # Check if exists
                        exists = db.session.query(PriceHistory.id).filter_by(
                            symbol=symbol.upper(),
                            timestamp=timestamp
                        ).first()
                        
                        if not exists:
                            history_entry = PriceHistory(
                                symbol=symbol.upper(),
                                price=close_price,
                                timestamp=timestamp,
                                exchange='binance'
                            )
                            db.session.add(history_entry)
                    
                    db.session.commit()
                    logger.info(f"Backfilled {symbol} from Binance")
                    time.sleep(0.2)  # Rate limiting
                    
                except Exception as e:
                    logger.error(f"Binance backfill failed for {symbol}: {e}")
                    db.session.rollback()
                    continue
                
    except Exception as e:
        logger.error(f"Binance price backfill setup failed: {e}")

# COINBASE FUNCTIONS REMOVED PER INSTRUCTIONS

PRICE_CACHE = {}  # {symbol: (price, timestamp)}
PRICE_CACHE_TTL = 300  # 5 minutes

def fetch_crypto_price(symbol):
    """Fetch crypto price from Binance.US only"""
    symbol = symbol.upper()
    if symbol in STABLE_COINS:
        return 1.0

    try:
        from binance.client import Client
        client = Client(tld='us')
        price, market = _try_binance_symbol_pairs(client, symbol)
        if price is not None:
            return price
    except Exception as e:
        logger.error(f"Binance.US price failed for {symbol}: {e}")

    logger.error(f"Failed to fetch price for {symbol} from Binance.US.")
    return None

def get_active_symbols():
    """Get active symbols from user portfolios"""
    with app.app_context():
        coins = Coin.query.filter_by(hidden=False).all()
        return list({c.symbol.upper() for c in coins})

def set_initial_price_on_gift(user_id, symbol, date_str):
    """
    Sets the avg_entry price for a coin if it was received as a gift/bonus/transfer/receive,
    and only if it does not already have an avg_entry price.
    """
    symbol = symbol.upper()
    coin = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
    if not coin or coin.avg_entry and coin.avg_entry > 0:
        return  # Already set

    # Try to get current price from Binance as approximation
    try:
        current_price = fetch_crypto_price(symbol)
        price = current_price if current_price else 0.0
    except Exception as e:
        logger.error(f"Failed to fetch price for {symbol}: {e}")
        price = 0.0

    if coin:
        coin.avg_entry = price
        coin.purchase_date = _format_date_only(date_str)
        db.session.commit()

def get_latest_purchase_date(symbol):
    row = AllActivity.query.filter_by(asset=symbol, type='BUY').order_by(AllActivity.date.desc()).first()
    return _format_date_only(row.date) if row and row.date else None

# COINBASE FUNCTION REMOVED - Using Binance only per instructions

def update_all_coin_prices_from_binance(user_id):
    """Update coin prices from Binance only - no balance updates"""
    try:
        coins = Coin.query.filter_by(user_id=user_id).all()
        for coin in coins:
            symbol = coin.symbol.upper()
            if symbol in ['USD', 'USDT', 'USDC', 'DAI']:
                coin.current = 1.0
            else:
                # Get price from Binance
                try:
                    price = fetch_crypto_price(symbol)
                    if price:
                        coin.current = price
                except Exception as e:
                    logger.error(f"Failed to get price for {symbol}: {e}")
                    coin.current = 0.0
        db.session.commit()
        logger.info(f"Updated coin prices from Binance for user {user_id}")
    except Exception as e:
        logger.error(f"Error updating coin prices from Binance: {e}")


def _try_binance_symbol_pairs(client, symbol, extra_pairs=None):
    """Try to fetch a price for symbol using common Binance quote pairs."""
    symbol = (symbol or '').upper()
    if not symbol:
        return None, None

    candidate_pairs = [f"{symbol}USDT", f"{symbol}USD"]
    if extra_pairs:
        candidate_pairs.extend(extra_pairs)

    for market in candidate_pairs:
        try:
            ticker = client.get_symbol_ticker(symbol=market)
            price = float(ticker['price'])
            return price, market
        except Exception as fetch_err:
            logger.debug(f"Price lookup failed for {market}: {fetch_err}")
            continue

    return None, None


def fetch_binance_price(symbol):
    """
    Fetch current price from Binance.US exclusively (no fallbacks)
    """
    symbol = symbol.upper()

    if symbol in STABLE_COINS:
        return 1.0

    try:
        from binance.client import Client
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if api_key and api_secret:
            client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
        else:
            client = Client(tld='us')

        price, market = _try_binance_symbol_pairs(client, symbol)
        if price is not None:
            return price

    except Exception as e:
        logger.debug(f"Binance.US client initialization failed: {e}")

    # No fallbacks - return None if Binance.US fails (caller should use database cache)
    logger.warning(f"Binance.US price sources failed for {symbol}, returning None")
    return None

def fetch_prices_binance_batch(symbols):
    """
    Fetch prices for multiple symbols using Binance.US public API (no authentication needed for price data)
    Returns a dict: {symbol: price}
    """
    result = {}

    try:
        from binance.client import Client

        # Create unauthenticated client for public price data (no API keys needed!)
        client = Client(tld='us')
        test_ticker = client.get_symbol_ticker(symbol="BTCUSDT")
        logger.debug(f"Using Binance.US public API for batch price fetch (test: BTC=${test_ticker['price']})")

        # Get prices from Binance.US
        for symbol in symbols:
            try:
                if symbol.upper() in STABLE_COINS:
                    result[symbol] = 1.0
                else:
                    ticker = client.get_symbol_ticker(symbol=f"{symbol.upper()}USDT")
                    result[symbol] = float(ticker['price'])
                    logger.debug(f"Binance.US price for {symbol}: ${result[symbol]}")
            except Exception as e:
                logger.debug(f"Binance.US price failed for {symbol}: {e}")
                result[symbol] = 0.0

        return result

    except Exception as e:
        logger.error(f"Binance.US batch fetch initialization failed: {e}")

    # No fallbacks - return empty result if Binance.US fails
    logger.warning("Binance.US batch fetch failed completely")
    for symbol in symbols:
        result[symbol] = 0.0

    return result

def fetch_price(symbol):
    """Fetch current price from Binance only"""
    return fetch_binance_price(symbol)

def calculate_avg_entry_fifo(user_id, symbol, target_amount=None, dust_threshold_usd=1.0):
    """
    Calculate the weighted-average entry price for the user's *current* holdings of ``symbol``.

    The calculation walks forward through the user's transaction history using FIFO:
    - Buys/receives add new lots at their execution price.
    - Sells/withdrawals consume lots from the front of the queue.
    - Whenever the remaining position is completely closed out or the residual value
      drops below ``dust_threshold_usd`` (default: $1.00), the cost basis resets.

    Returns:
        tuple(avg_entry_price, total_cost_basis, total_amount)
        When no qualifying lots remain the values are (0.0, 0.0, 0.0).
    """
    activities = AllActivity.query.filter_by(user_id=user_id, asset=symbol).order_by(AllActivity.date.asc()).all()

    if not activities:
        return 0.0, 0.0, 0.0

    buys = {'BUY', 'TRANSFER', 'RECEIVE', 'GIFT', 'BONUS'}
    sells = {'SELL', 'WITHDRAWAL', 'SEND'}

    lots = []  # FIFO queue of {"amount": float, "price": float}
    total_amount = 0.0
    total_cost = 0.0

    for activity in activities:
        qty = float(activity.amount or 0.0)
        cost_basis = float(activity.cost_basis or 0.0)
        proceeds = float(activity.proceeds or 0.0)
        fee = float(activity.fee or 0.0)
        avg_entry = float(activity.avg_entry or 0.0)
        price_sold_at = float(activity.price_sold_at or 0.0)
        tx_type = activity.type
        avg_entry = float(avg_entry or 0.0)
        price_sold_at = float(price_sold_at or 0.0)

        if tx_type in buys and qty > 0:
            if avg_entry > 0:
                price = avg_entry
            elif cost_basis > 0:
                price = cost_basis / qty
            elif price_sold_at > 0:
                price = price_sold_at
            else:
                # Fallback: treat as zero-cost transfer
                price = 0.0

            lots.append({"amount": qty, "price": price})
            total_amount += qty
            total_cost += qty * price

        elif tx_type in sells and qty != 0:
            amount_to_remove = abs(qty)

            while amount_to_remove > 0 and lots:
                lot = lots[0]
                removable = min(lot["amount"], amount_to_remove)
                total_amount -= removable
                total_cost -= removable * lot["price"]
                lot["amount"] -= removable
                amount_to_remove -= removable

                if lot["amount"] <= 1e-12:
                    lots.pop(0)

            # If the sell exceeded current lots, wipe everything
            if amount_to_remove > 1e-12:
                lots.clear()
                total_amount = 0.0
                total_cost = 0.0

        # Reset the book if the remaining value is effectively zero
        if total_amount <= 1e-12 or total_cost <= dust_threshold_usd:
            lots.clear()
            total_amount = 0.0
            total_cost = 0.0

    # Align with the actual on-chain/portfolio balance when provided
    if target_amount is not None and total_amount > target_amount + 1e-12:
        excess = total_amount - target_amount
        while excess > 1e-12 and lots:
            lot = lots[0]
            removable = min(lot["amount"], excess)
            total_amount -= removable
            total_cost -= removable * lot["price"]
            lot["amount"] -= removable
            excess -= removable
            if lot["amount"] <= 1e-12:
                lots.pop(0)

    if total_amount <= 0 or total_cost <= 0 or total_cost <= dust_threshold_usd:
        return 0.0, 0.0, 0.0

    avg_entry = total_cost / total_amount
    return avg_entry, total_cost, total_amount

def get_cost_basis_for_asset(user_id, symbol):
    """
    Returns the cost basis for the *current holdings* of a given asset for the user using FIFO.
    """
    coin = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
    target_amount = coin.amount if coin else None
    _, cost_basis, _ = calculate_avg_entry_fifo(user_id, symbol, target_amount=target_amount)
    return cost_basis if cost_basis else 0

def update_avg_entry_for_new_holdings(user_id):
    """
    For each coin with amount > 0, ensure avg_entry is properly calculated from transaction history using FIFO.
    """
    coins = Coin.query.filter_by(user_id=user_id).all()
    updated = False
    for coin in coins:
        avg_entry, cost_basis, total_amount = calculate_avg_entry_fifo(
            user_id,
            coin.symbol,
            target_amount=coin.amount
        )

        if cost_basis >= 1.0 and total_amount > 0:
            target_avg = avg_entry
        else:
            target_avg = 0.0

        if (coin.avg_entry or 0.0) != target_avg:
            coin.avg_entry = target_avg
            coin.updated_at = datetime.utcnow()
            updated = True
            if target_avg > 0:
                logger.info(f"Updated {coin.symbol} avg_entry to ${target_avg:.6f} (cost basis: ${cost_basis:.2f})")
            else:
                logger.info(f"Reset {coin.symbol} avg_entry to $0.00 (cost basis: ${cost_basis:.2f}, amount {total_amount:.8f})")

    if updated:
        db.session.commit()
    
def calculate_auto_alert(symbol, alert_type, avg_entry=None):
    prices = get_last_7d_prices(symbol)
    logger.info(f"[calculate_auto_alert] Prices for {symbol}: {prices}")
    if not prices or (avg_entry is not None and (not avg_entry or avg_entry == 0)):
        logger.warning(f"[calculate_auto_alert] No prices or bad avg_entry for {symbol}. Returning 10.0")
        return 10.0

    try:
        reference_price = avg_entry if avg_entry else prices[0]
        mean_price = np.mean(prices)
        std_pct = np.std(prices) / mean_price * 100 if mean_price else 0

        # Fetch 7d volume from CoinGecko
        # Use default volume since CoinGecko is not allowed (Binance-only)
        try:
            # Could potentially fetch from Binance 24hr ticker but using default for now
            avg_vol = 1000000  # Default volume
        except Exception as e:
            logger.error(f"Error setting volume for {symbol}: {e}")
            avg_vol = 1

        sentiment = fetch_news_sentiment(symbol)  # Replace fetch_sentiment with fetch_news_sentiment
        if sentiment is None:
            sentiment = 0  # Default to neutral if sentiment unavailable
            
        logger.info(f"[calculate_auto_alert] std_pct={std_pct} avg_vol={avg_vol}, sentiment={sentiment}")

        # --- AI-inspired scaling ---
        min_spread = 5
        max_spread = 50

        vol_factor = 1 / (1 + math.exp(-0.25 * (std_pct - 10)))
        vol_norm = min(max((math.log10(avg_vol) - 5) / 5, 0), 1)
        sent_factor = 1 + 0.2 * sentiment

        risk_score = 0.7 * vol_factor + 0.2 * vol_norm + 0.1 * sent_factor
        spread = min_spread + (max_spread - min_spread) * min(max(risk_score, 0), 1)

        spread = round(spread, 2)
        logger.info(f"[calculate_auto_alert] Final value for {symbol} {alert_type}: {spread}")
        return spread
        
    except Exception as e:
        logger.error(f"Error in calculate_auto_alert for {symbol}: {e}")
        return 10.0  # Safe fallback value

def update_auto_alert_cache():
    # Update all cached auto-alerts every 2 hours
    now = datetime.utcnow()
    for key in list(AUTO_ALERT_CACHE.keys()):
        symbol, alert_type = key
        # You can add logic to only update for active coins
        value = calculate_auto_alert(symbol, alert_type)
        AUTO_ALERT_CACHE[key] = {'value': value, 'updated': now}

def cleanup_old_prices():
    """Remove price history older than 30 days using ORM"""
    try:
        from models import PriceHistory
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        # Delete old records using ORM
        PriceHistory.query.filter(PriceHistory.timestamp < cutoff.timestamp()).delete()
        db.session.commit()
        logger.info("Cleaned up old price history records")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cleaning up old prices: {e}")

def record_true_portfolio_value():
    """Record the total portfolio value for all users using the same calculation as the dashboard widget."""
    with app.app_context():
        try:
            from credentials import Credential
            from trading_models import PortfolioValueHistory
            
            # Get all users who have Binance credentials using ORM
            users_with_creds = db.session.query(User).join(
                Credential, User.username == Credential.username
            ).filter(
                db.or_(
                    db.and_(Credential._api_key.isnot(None), Credential._api_secret.isnot(None)),
                    db.and_(Credential.trading_api_key.isnot(None), Credential.trading_api_secret.isnot(None))
                )
            ).all()

            if not users_with_creds:
                logger.warning("No users with valid Binance API credentials found for portfolio recording")
                return

            for user in users_with_creds:
                try:
                    cred_obj = get_user_credentials(user.username)
                    total_value = compute_portfolio_total_value(
                        user.id,
                        username=user.username,
                        cred=cred_obj
                    )
                    total_value = round(total_value, 2)

                    if total_value <= 0:
                        logger.warning(f"No portfolio value to record for user {user.username}")
                        continue

                    # Record history using ORM
                    history_record = PortfolioValueHistory(
                        user_id=user.id,
                        value=total_value,
                        timestamp=datetime.utcnow(),
                        date=datetime.utcnow().strftime('%Y-%m-%d')
                    )
                    db.session.add(history_record)
                    db.session.commit()
                    logger.info(f"Recorded portfolio value of ${total_value:.2f} for user {user.username} (user_id={user.id})")

                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Error recording portfolio value for {user.username}: {e}")

        except Exception as e:
            logger.error(f"Error in record_true_portfolio_value: {e}")

# ---------------------------------------------------------------------------
# Immediate post-trade portfolio snapshot
# ---------------------------------------------------------------------------
_snapshot_cooldown: dict = {}  # user_id -> last trigger timestamp
_SNAPSHOT_COOLDOWN_SECS = 30

def trigger_portfolio_snapshot(user_id: int, username: str) -> None:
    """Fire-and-forget: write a PortfolioValueHistory row immediately after a
    real trade or staking action so the portfolio chart updates at once rather
    than waiting up to 5 minutes for the background sync loop.

    A 30-second per-user cooldown prevents duplicate rows when multiple events
    fire in quick succession.
    """
    now = time.time()
    if now - _snapshot_cooldown.get(user_id, 0) < _SNAPSHOT_COOLDOWN_SECS:
        logger.info(f"[snapshot] Cooldown active — skipping immediate snapshot for user {user_id}")
        return
    _snapshot_cooldown[user_id] = now

    def _run():
        with app.app_context():
            try:
                cred = get_user_credentials(username)
                total_value = compute_portfolio_total_value(user_id, username=username, cred=cred)
                total_value = round(total_value, 2)
                if total_value > 0:
                    from trading_models import PortfolioValueHistory
                    record = PortfolioValueHistory(
                        user_id=user_id,
                        value=total_value,
                        timestamp=datetime.utcnow(),
                        date=datetime.utcnow().strftime('%Y-%m-%d')
                    )
                    db.session.add(record)
                    db.session.commit()
                    logger.info(f"[snapshot] Recorded ${total_value:.2f} for user {user_id} after trade/stake")
            except Exception as exc:
                logger.error(f"[snapshot] Failed to record snapshot for user {user_id}: {exc}")
                try:
                    db.session.rollback()
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()
# ---------------------------------------------------------------------------

# Initialize background threads list
background_threads = []

def ensure_background_jobs():
    """Ensure background jobs are running"""
    global background_threads
    
    # Filter out any dead threads
    background_threads = [t for t in background_threads if t.is_alive()]
    
    # If no background threads are running, start them
    if not background_threads:
        logger.warning("No background threads found, starting them now...")
        start_background_jobs(app)
    
    return len(background_threads) > 0

def _normalize_threshold(threshold):
    try:
        if threshold is None:
            return "none"
        return f"{float(threshold):.6f}"
    except Exception:
        return str(threshold)

def get_last_alert_state(user_id, symbol, direction, source=None, threshold=None):
    """Read last alert state with scoped key support.
    Key format (scoped): user:symbol:direction:source:threshold
    Fallback to legacy unscoped key user:symbol:direction if scoped not present.
    """
    fn = "alert_state.json"
    symbol = (symbol or "").upper()
    legacy_key = f"{user_id}:{symbol}:{direction}"
    scoped_key = None
    if source is not None and threshold is not None:
        scoped_key = f"{user_id}:{symbol}:{direction}:{source}:{_normalize_threshold(threshold)}"
    state = {}
    if os.path.exists(fn):
        try:
            with open(fn, 'r') as f:
                import json as _json
                state = _json.load(f)
        except Exception as e:
            logger.error(f"[ALERT_STATE] Failed to load {fn}: {e}")
            state = {}
    # Prefer scoped
    if scoped_key and scoped_key in state:
        val = state.get(scoped_key)
        logger.info(f"[ALERT_STATE] GET {scoped_key} = {val}")
        return val
    # Fallback legacy
    val = state.get(legacy_key)
    logger.info(f"[ALERT_STATE] GET {legacy_key} = {val} (fallback)")
    return val

def set_last_alert_state(user_id, symbol, direction, value, source=None, threshold=None):
    """Write last alert state using scoped key when source and threshold provided.
    Does not delete legacy keys; maintains backward compatibility.
    """
    fn = "alert_state.json"
    symbol = (symbol or "").upper()
    key = f"{user_id}:{symbol}:{direction}"
    if source is not None and threshold is not None:
        key = f"{user_id}:{symbol}:{direction}:{source}:{_normalize_threshold(threshold)}"
    state = {}
    if os.path.exists(fn):
        try:
            with open(fn, 'r') as f:
                import json as _json
                state = _json.load(f)
        except Exception as e:
            logger.error(f"[ALERT_STATE] Failed to load {fn}: {e}")
            state = {}
    state[key] = value
    with open(fn, 'w') as f:
        import json as _json
        _json.dump(state, f)
    logger.info(f"[ALERT_STATE] SET {key} = {value}")

def clear_alert_state(user_id=None):
    """Clear alert_state entries. If user_id is provided, clear only entries for that user.
    Returns count of entries removed.
    """
    fn = "alert_state.json"
    removed = 0
    if not os.path.exists(fn):
        return removed
    try:
        with open(fn, 'r') as f:
            import json as _json
            state = _json.load(f)
    except Exception:
        state = {}
    if user_id is None:
        removed = len(state)
        with open(fn, 'w') as f:
            import json as _json
            _json.dump({}, f)
        logger.info(f"[ALERT_STATE] Cleared all entries ({removed})")
        return removed
    # filter user-specific keys
    prefix = f"{user_id}:"
    new_state = {k: v for k, v in state.items() if not k.startswith(prefix)}
    removed = len(state) - len(new_state)
    with open(fn, 'w') as f:
        import json as _json
        _json.dump(new_state, f)
    logger.info(f"[ALERT_STATE] Cleared {removed} entries for user {user_id}")
    return removed
 # (moved) Scheduler to update every 2 hours — moved into start_background_jobs(app)
 # (Deleted import-time BackgroundScheduler for update_auto_alert_cache; job is added inside start_background_jobs.)

def run_background_jobs_once():
    if not getattr(run_background_jobs_once, "started", False):
        start_background_jobs(app)
        run_background_jobs_once.started = True


# User loader for Flask-Login (no more context switching!)
@login_manager.user_loader
def load_user(user_id):
    logger.error(f"[USER_LOADER] Called with user_id: {user_id}")
    if not user_id:
        logger.error("[USER_LOADER] No user_id provided")
        return None
    try:
        # Direct query using the consolidated User model
        user = User.query.get(int(user_id))
        logger.error(f"[USER_LOADER] Found user: {user}")
        return user
    except Exception as e:
        logger.error(f"[USER_LOADER] Error: {e}", exc_info=True)
        return None

# Ensure login-required API endpoints return JSON if not authenticated
@login_manager.unauthorized_handler
def unauthorized():
    # If the request is for an API endpoint, return JSON
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Authentication required."}), 401
    # Otherwise, redirect to login page
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()


def set_avg_entry_on_new_buy(user_id, symbol):
    """Update coin average entry based on the latest filled buy activity using ORM"""
    try:
        from trading_models import AllActivity
        symbol = symbol.upper()
        
        # Get the latest filled buy activity using ORM
        latest_buy = AllActivity.query.filter_by(
            asset=symbol, 
            status='FILLED',
            type='BUY'
        ).order_by(AllActivity.date.desc()).first()
        
        if latest_buy and latest_buy.amount > 0:
            try:
                new_avg_entry = (latest_buy.proceeds + latest_buy.fee) / latest_buy.amount
                coin = Coin.query.filter_by(user_id=latest_buy.user_id, symbol=symbol).first()
                if coin:
                    coin.avg_entry = new_avg_entry
                    db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception as e:
        logger.error(f"Error in set_avg_entry_on_new_buy: {e}")

def sync_coin_table_with_logs(user_id):
    """
    For each asset in logs, ensure a Coin exists and update its amount and current price using ORM.
    """
    try:
        from trading_models import AllActivity
        STABLE_COINS = {"USDT", "USDC", "DAI", "TUSD", "USDP", "EURC", "PYUSD", "USD"}
        
        # Get asset amounts using ORM aggregation
        asset_amounts_query = db.session.query(
            AllActivity.asset, 
            db.func.sum(AllActivity.amount)
        ).group_by(AllActivity.asset).all()
        
        asset_amounts = {row[0].upper(): float(row[1] or 0) for row in asset_amounts_query}

        # Fetch prices using Binance only
        def fetch_price(symbol):
            if symbol in STABLE_COINS:
                return 1.0
            try:
                return fetch_binance_price(symbol)
            except Exception:
                return 0.0

        for symbol, amount in asset_amounts.items():
            coin = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if not coin:
                coin = Coin(
                    user_id=user_id,
                    symbol=symbol,
                    avg_entry=1.0 if symbol == "USDT" else 0.0,
                    purchase_date=datetime.utcnow().strftime("%Y-%m-%d"),
                    current=1.0 if symbol == "USDT" else 0.0,
                    amount=0.0
                )
                db.session.add(coin)
            
            # Always update amount and current price
            coin.amount = amount
            coin.current = fetch_price(symbol)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in sync_coin_table_with_logs: {e}")

def get_last_7d_prices(symbol):
    """Get price history for the last 7 days using ORM"""
    try:
        from models import PriceHistory
        cutoff = datetime.utcnow() - timedelta(days=7)
        
        rows = PriceHistory.query.filter(
            PriceHistory.symbol == symbol.upper(),
            PriceHistory.timestamp >= cutoff.timestamp()
        ).order_by(PriceHistory.timestamp.asc()).all()
        
        return [r.price for r in rows]
    except Exception as e:
        logger.error(f"Error in get_last_7d_prices: {e}")
        return []

def sync_coins_with_activities(user_id, assets_to_sync=None):
    """
    Synchronize coins table with all_activities table data using ORM.
    Updates purchase_date, amount, and initial_price based on transaction history.
    """
    try:
        from trading_models import AllActivity
        
        # Get all assets for this user if no specific assets provided
        if assets_to_sync is None:
            assets_query = db.session.query(AllActivity.asset).filter_by(user_id=user_id).distinct().all()
            assets_to_sync = [row[0] for row in assets_query]
            
        for asset in assets_to_sync:
            try:
                # Get the most recent buy price for this asset using ORM
                latest_buy = AllActivity.query.filter_by(
                    user_id=user_id, 
                    asset=asset, 
                    type='BUY'
                ).filter(AllActivity.avg_entry.isnot(None)).order_by(AllActivity.date.desc()).first()
                
                # Calculate total current amount for this asset using ORM
                transactions = AllActivity.query.filter_by(
                    user_id=user_id, 
                    asset=asset
                ).order_by(AllActivity.date.asc()).all()
                
                current_amount = 0.0
                for tx in transactions:
                    if tx.type == 'BUY':
                        current_amount += tx.amount
                    elif tx.type == 'SELL':
                        current_amount -= tx.amount
                    elif tx.type == 'SEND':
                        current_amount -= tx.amount
                    elif tx.type == 'RECEIVE':
                        current_amount += tx.amount
                
                # Update or create coin record
                coin = Coin.query.filter_by(
                    user_id=user_id, 
                    symbol=asset.upper()
                ).first()
                
                if not coin:
                    coin = Coin(
                        user_id=user_id,
                        symbol=asset.upper(),
                        initial_price=0.0,
                        purchase_date=None,
                        amount=0.0
                    )
                    db.session.add(coin)
                    logger.info(f"Created new coin record for {asset}")
                
                # Do NOT overwrite live amount here; live Binance sync sets authoritative balances
                old_amount = coin.amount
                _ = current_amount  # calculated but intentionally not applied
                
                # Update purchase date and initial price from latest buy
                if latest_buy:
                    latest_date = latest_buy.date
                    avg_entry_price = latest_buy.avg_entry
                    
                    purchase_date_only = _format_date_only(latest_date)

                    # Only update if we have a newer purchase date or if purchase_date is empty
                    if not coin.purchase_date or purchase_date_only > (coin.purchase_date or ''):
                        coin.purchase_date = purchase_date_only
                        logger.info(f"Updated {asset} purchase_date: {coin.purchase_date}")

                    # Update avg_entry with the latest buy price
                    if avg_entry_price and avg_entry_price > 0:
                        coin.avg_entry = float(avg_entry_price)
                        logger.info(f"Updated {asset} avg_entry: {coin.avg_entry}")

                logger.info(f"Synced {asset}: amount {old_amount} → {current_amount}, purchase_date: {coin.purchase_date}, avg_entry: {coin.avg_entry}")
                
            except Exception as e:
                logger.error(f"Error syncing coin {asset}: {str(e)}")
                continue
    
    except Exception as e:
        logger.error(f"Error in sync_coins_with_activities: {str(e)}")
        db.session.rollback()
    finally:
        # Commit all changes
        try:
            db.session.commit()
            logger.info(f"Completed coin sync for user {user_id}")
        except Exception as e:
            logger.error(f"Error committing changes: {str(e)}")
            db.session.rollback()

def sync_binance_logs():
    """Sync Binance trade history for every user with Binance credentials."""
    try:
        from binance.client import Client

        users = db.session.query(User.id.label('user_id'), User.username, Credential.api_key, Credential.api_secret)\
            .join(Credential, User.username == Credential.username)\
            .filter(Credential._api_key.isnot(None), Credential._api_secret.isnot(None)).all()

        if not users:
            logger.warning("No Binance API credentials found")
            return

        for user in users:
            user_id = user.user_id
            username = user.username
            api_key = decrypt_secret(user.api_key)
            api_secret = decrypt_secret(user.api_secret)

            if not api_key or not api_secret:
                logger.debug(f"Skipping user {username}: missing Binance credentials")
                continue

            try:
                client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
            except Exception as client_error:
                logger.error(f"Failed to create Binance client for {username}: {client_error}")
                continue

            try:
                account_info = client.get_account()
            except Exception as account_error:
                logger.error(f"Failed to fetch account info for {username}: {account_error}")
                continue

            balances = account_info.get('balances', [])
            assets_with_balance = [
                balance['asset']
                for balance in balances
                if float(balance.get('free') or 0) > 0 or float(balance.get('locked') or 0) > 0
            ]

            if not assets_with_balance:
                logger.info(f"No Binance balances found for user {username}")
                continue

            logger.info(f"Syncing Binance logs for user {username}: {assets_with_balance}")

            all_trades = []
            for asset in assets_with_balance:
                if asset in ('USDT', 'USD'):
                    continue

                for quote in ('USD', 'USDT'):
                    symbol = f"{asset}{quote}"
                    try:
                        trades = client.get_my_trades(symbol=symbol, limit=100)
                        if trades:
                            all_trades.extend(trades)
                            logger.info(f"Found {len(trades)} trades for {symbol} (user {username})")
                    except Exception as pair_error:
                        error_text = str(pair_error)
                        if 'Invalid symbol' in error_text or 'not found' in error_text.lower():
                            logger.debug(f"Trading pair {symbol} unavailable for {username}")
                        else:
                            logger.warning(f"Error fetching trades for {symbol} ({username}): {pair_error}")
                        continue
                    finally:
                        time.sleep(0.2)

            if all_trades:
                process_binance_trades(user_id, all_trades)
            else:
                logger.info(f"No recent trades to record for user {username}")

            try:
                update_coins_from_binance_balances(user_id, balances)
            except Exception as balance_error:
                logger.error(f"Failed to update coins table for {username}: {balance_error}")

        logger.info("Binance logs sync completed successfully")

    except Exception as e:
        logger.error(f"Error in sync_binance_logs: {e}")
        raise

def check_auto_unhide_conditions(user_id, updated_assets):
    """
    Check if any coins should be auto-unhidden based on USD value crossing $0.99 threshold
    """
    # Auto-unhide logic is now fully disabled. Coins can only be unhidden by explicit user action (Unhide Coins UI or /api/unhide-all).
    pass

@app.route('/api/logs/all')
@login_required
def api_logs_all():
    try:
        # Try to sync Binance logs, but don't fail if API is broken
        sync_binance_logs()
    except Exception as e:
        logger.warning(f"Logs sync failed, returning existing data: {str(e)}")
        # Continue with existing data even if sync fails
    
    try:
        from trading_models import AllActivity
        # Use ORM to query logs
        activities = AllActivity.query.filter_by(user_id=current_user.id).order_by(AllActivity.date.desc()).all()
        logger.info(f"Found {len(activities)} log entries for user {current_user.id}")
        
        # Convert to list of dictionaries with proper field names
        result = []
        
        for activity in activities:
            log_dict = {
                'id': activity.id,
                'date': _format_activity_date(activity.date),
                'type': activity.type,
                'asset': activity.asset,
                'amount': activity.amount,
                'proceeds': activity.proceeds,
                'cost_basis': activity.cost_basis,
                'gain_loss': activity.gain_loss,
                'fee': activity.fee,
                'description': activity.description,
                'txid': activity.txid,
                'status': activity.status,
                'details': activity.details,
                'price_sold_at': activity.price_sold_at,
                'exchange': activity.exchange or 'coinbase'  # Default to coinbase for legacy records
            }
            
            # For BUY transactions, calculate cost basis if not set
            if log_dict['type'] == 'BUY' and (log_dict['cost_basis'] is None or log_dict['cost_basis'] == 0):
                cost_basis = float(log_dict['proceeds'] or 0) + float(log_dict['fee'] or 0)
                log_dict['cost_basis'] = cost_basis
                
                # Update database with calculated cost basis using ORM
                try:
                    activity.cost_basis = cost_basis
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Failed to update cost_basis for transaction {log_dict['id']}: {e}")
            
            result.append(log_dict)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error querying logs: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Failed to load logs data"}), 500

@app.route('/api/logs/sync', methods=['POST'])
@login_required
def api_logs_sync():
    """Force sync with Binance to pull latest transactions"""
    try:
        logger.info(f"Manual sync requested by user {current_user.username}")
        sync_binance_logs()
        return jsonify({"success": True, "message": "Binance logs synced successfully"})
    except Exception as e:
        logger.error(f"Error syncing Binance logs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sync-portfolio-from-transactions', methods=['POST'])
@login_required
def api_sync_portfolio_from_transactions():
    """Force sync portfolio with transaction data to fix discrepancies"""
    try:
        sync_coins_from_transactions()
        return jsonify({"success": True, "message": "Portfolio synced with transaction data successfully"})
    except Exception as e:
        logger.error(f"Error syncing portfolio from transactions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logs/import', methods=['POST'])
@login_required
def api_logs_import():
    """Import logs from a JSON payload using ORM"""
    try:
        from trading_models import AllActivity
        data = request.get_json()
        rows = data.get('rows', [])[1:]
        
        for row in rows:
            row_date = _coerce_activity_datetime(row[0]) if len(row) > 0 else None
            # Check if activity already exists (using txid if available, or other fields)
            txid = row[6] if len(row) > 6 else None
            existing = None
            if txid:
                existing = AllActivity.query.filter_by(txid=txid, user_id=current_user.id).first()
            
            if not existing:
                new_activity = AllActivity(
                    date=row_date,
                    type=row[1],
                    asset=row[2],
                    amount=float(row[3] or 0),
                    proceeds=float(row[4] or 0),
                    fee=float(row[5] or 0),
                    txid=txid,
                    status=row[7] if len(row) > 7 else "completed",
                    details=row[8] if len(row) > 8 else "Imported via API",
                    user_id=current_user.id
                )
                db.session.add(new_activity)
            
            typ = (row[1] or "").upper()
            symbol = row[2].upper()
            amount = float(row[3] or 0)
            
            # Ensure Coin exists for ANY asset in logs
            coin = Coin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
            if not coin:
                coin = Coin(
                    user_id=current_user.id,
                    symbol=symbol,
                    initial_price=1.0 if symbol == "USDT" else 0.0,
                    purchase_date=_format_date_only(row_date),
                    current=1.0 if symbol == "USDT" else 0.0,
                    amount=0.0
                )
                db.session.add(coin)
                db.session.commit()
            
            # For GIFT/BONUS/TRANSFER/RECEIVE, update amount and set initial price
            if typ in {"GIFT", "BONUS", "TRANSFER", "RECEIVE"}:
                coin.amount += amount
                db.session.commit()
                set_initial_price_on_gift(current_user.id, symbol, row_date)
        
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error importing logs: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/logs.html')
@login_required
def logs_html():
    return jsonify({"error": "Logs page not available in React app"}), 404

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')
        
        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400
        try:
            # Check if user exists
            user = db.session.query(User).filter_by(username=username).first()
            if user:
                return jsonify({"error": "Username already exists"}), 400
            
            # Create new user
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            
            # Create empty Credential record for the new user
            new_cred = Credential(user_id=new_user.id, username=new_user.username)
            db.session.add(new_cred)
            db.session.commit()

            # Create default UserSetting record
            # Crucial for new columnar structure
            new_settings = UserSetting(user_id=new_user.id)
            db.session.add(new_settings)
            db.session.commit()
            
            # Seed all 10 AI prompts from defaults
            try:
                defaults = DefaultAIPrompt.query.first()
                if defaults:
                    new_prompts = AIPrompt(
                        user_id=new_user.id,
                        market_analysis_pre=defaults.market_analysis_pre,
                        market_analysis_post=defaults.market_analysis_post,
                        risk_assessment_pre=defaults.risk_assessment_pre,
                        risk_assessment_post=defaults.risk_assessment_post,
                        portfolio_review_pre=defaults.portfolio_review_pre,
                        portfolio_review_post=defaults.portfolio_review_post,
                        coin_analysis_pre=defaults.coin_analysis_pre,
                        coin_analysis_post=defaults.coin_analysis_post,
                        sentiment_prompt_pre=defaults.sentiment_prompt_pre,
                        sentiment_prompt_post=defaults.sentiment_prompt_post,
                        news_analysis_pre=getattr(defaults, 'news_analysis_pre', ''),
                        news_analysis_post=getattr(defaults, 'news_analysis_post', '')
                    )
                    db.session.add(new_prompts)
                    db.session.commit()
                    logger.info(f"Seeded 10 AI prompts for new user {new_user.id}")
            except Exception as prompt_err:
                logger.warning(f"Failed to seed prompts for new user: {prompt_err}")
            
            # Log in the new user (if using Flask-Login)
            login_user(new_user)
            return jsonify({"success": True, "redirect": "/settings?new_user=true", "user_id": new_user.id}), 200
            
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            db.session.rollback()
            return jsonify({"error": f"Registration failed: {str(e)}"}), 500
    return jsonify({"error": "GET method not supported"}), 405

@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if request.method == 'POST':
        # No more context switching! Use the consolidated models directly
        if current_user and getattr(current_user, 'is_authenticated', False):
            cred = Credential.query.filter_by(user_id=current_user.id).first()
        else:
             cred = Credential.query.filter_by(username=current_user.username).first()
        if not cred:
            cred = Credential(username=current_user.username)
            db.session.add(cred)
        
        try:
            cred.telegram_token = request.form["telegram_token"]
            cred.telegram_chat_id = request.form["telegram_chat_id"]
            
            # Make News API key optional and save as None if blank
            news_api_key = request.form.get("news_api_key", "").strip()
            cred.news_api = news_api_key if news_api_key else None
            
            db.session.commit()
        except EncryptionKeyError as enc_err:
            logger.error(f"Onboarding credential encryption failed: {enc_err}")
            db.session.rollback()
            return jsonify({"success": False, "error": "Credential encryption key missing. Configure CREDENTIALS_ENCRYPTION_KEY and retry."}), 500
        return jsonify({"success": True, "message": "Credentials saved successfully."})
    return jsonify({"error": "GET method not supported"}), 405

@app.route('/api/check-credential')
@login_required
def check_credential():
    field = request.args.get('field')
    value = request.args.get('value')

    # Basic length check
    if not value or len(value) < 5:
        return jsonify(valid=False, message="This value is too short.")

    if field == "telegram_token":
        try:
            r = requests.get(f"https://api.telegram.org/bot{value}/getMe", timeout=8)
            data = r.json()
            if data.get("ok"):
                return jsonify(valid=True, message="Telegram Bot Token is valid.")
            else:
                return jsonify(valid=False, message="Telegram Bot Token is invalid.")
        except Exception as e:
            return jsonify(valid=False, message=f"Telegram Bot Token check error: {str(e)}")

    if field == "telegram_chat_id":
        token = request.args.get('telegram_token', '')
        if not token:
            return jsonify(valid=True, message="Format looks OK. (Token required for full check)")
        try:
            test_url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": value, "text": "Test message from Crypto Dashboard onboarding."}
            r = requests.post(test_url, data=payload, timeout=8)
            data = r.json()
            if data.get("ok"):
                return jsonify(valid=True, message="Telegram Chat ID is valid and can receive messages.")
            else:
                return jsonify(valid=False, message=f"Telegram Chat ID error: {data.get('description', 'Unknown error')}")
        except Exception as e:
            return jsonify(valid=False, message=f"Telegram Chat ID check error: {str(e)}")

    if field == "news_api_key":
        try:
            url = f"https://newsapi.org/v2/top-headlines?category=business&apiKey={value}"
            r = requests.get(url, timeout=8)
            data = r.json()
            if data.get("status") == "ok":
                return jsonify(valid=True, message="News API Key accepted.")
            else:
                return jsonify(valid=False, message=f"News API Key error: {data.get('message', 'Unknown error')}")
        except Exception as e:
            return jsonify(valid=False, message=f"News API check error: {str(e)}")



    return jsonify(valid=False, message="Unknown field.")

@app.route("/register", methods=["POST"])
def register_user():
    """Register a new user"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No input data provided"}), 400
        
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
        
    username = username.strip()
    
    # Check if user already exists
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists"}), 409
        
    try:
        # Calculate new user_id (max + 1)
        # We need a lock or atomic operation ideally, but for low volume this is acceptable
        max_id = db.session.query(db.func.max(User.id)).scalar() or 0
        new_user_id = max_id + 1
        
        # Create new user
        new_user = User(id=new_user_id, username=username)
        new_user.set_password(password)
        new_user.last_login = datetime.utcnow()
        
        db.session.add(new_user)
        db.session.flush() # Ensure user exists before adding credential
        
        # Create empty credential row
        new_cred = Credential(user_id=new_user.id, username=username)
        db.session.add(new_cred)
        
        db.session.commit()
        
        # Log the user in
        login_user(new_user)
        
        logger.info(f"New user registered: {username} (ID: {new_user_id})")
        
        return jsonify({
            "success": True, 
            "message": "User registered successfully", 
            "user_id": new_user_id,
            "redirect": "/settings?new_user=true"
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error registering user: {e}")
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500

@app.route("/login", methods=["GET", "POST"])
def login():
    logger.info(f"Login request: method={request.method}")
    if request.method == "POST":
        logger.info("Login POST request received")
        try:
            username = request.form["username"]
            password = request.form["password"]
            logger.info(f"Login attempt for username: {username}")
            
            # No more context switching! Use consolidated User model directly
            user = User.query.filter_by(username=username).first()
            logger.info(f"User found: {user is not None}")
                
            if user and user.check_password(password):
                logger.info(f"Password check successful for user: {username}")
                login_user(user, remember=True)  # Enable "remember me" functionality
                session.permanent = True  # Make session permanent (30 days)
                logger.info("Login successful, redirecting to dashboard")
                return redirect(url_for("dashboard"))
            else:
                logger.error(f"Login failed: invalid username or password for {username}")
                return jsonify({"error": "Invalid username or password"}), 401
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    # For GET requests, serve the React app
    logger.info("Login GET request, serving React app")
    return serve_react_app()

@app.route('/api/get-credentials')
@login_required
def api_get_credentials():
    try:
        logger.error(f"api_get_credentials: current_user.username = {str(current_user.username)}")
        username = current_user.username
        # No more context switching! Use the consolidated models directly  
        cred = Credential.query.filter_by(username=username).first()
        logger.error(f"api_get_credentials: cred = {str(cred)}")
        if not cred:
            return jsonify({})
        return jsonify({
                                    "telegram_token": cred.telegram_token or "",
            "telegram_chat_id": cred.telegram_chat_id or "",
            "news_api_key": cred.news_api or ""
        })
    except Exception as e:
        logger.error(f"api_get_credentials ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500


# OAuth endpoints removed - using Binance.US only

@app.route("/logout")
def logout():
    # Industry standard: Clear session and redirect
    logger.info(f"Logging out user via GET: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    logger.info(f"Session before logout: {dict(session)}")
    logout_user()
    session.clear()
    session.pop('_flashes', None)
    session.pop('user_id', None)  
    session.pop('username', None)
    session.modified = True
    logger.info(f"Session after logout: {dict(session)}")
    logger.info("User logged out successfully via GET")
    return redirect(url_for("login"))

@app.route("/api/sync-coins", methods=["POST"])
@login_required
def api_sync_coins():
    """
    MANUAL SYNC: Backfill 7 days of historical price data for existing coins in portfolio.
    Used for recovery when automatic hourly collection missed intervals or after app downtime.
    Does NOT modify portfolio holdings - only updates price data.
    """
    try:
        logger.info(f"Starting price sync for user {current_user.id}")
        
        # Get existing coins from user's portfolio (including hidden ones for recovery)
        coins = Coin.query.filter_by(user_id=current_user.id).all()
        if not coins:
            logger.info(f"Portfolio empty for user {current_user.id}. Attempting initial sync from Binance.")
            success, message = sync_portfolio_from_binance(current_user.id)
            if success:
                coins = Coin.query.filter_by(user_id=current_user.id).all()
            
            if not coins:
                return jsonify({
                    "success": False,
                    "error": "No coins in portfolio. Add some coins first, then sync prices."
                })
        
        symbols = list({c.symbol.upper() for c in coins})
        logger.info(f"Syncing price history for {len(symbols)} symbols: {symbols}")
        
        synced_count = 0
        
        # Update price history for each symbol
        for symbol in symbols:
            try:
                # Delete existing price history for this symbol
                try:
                    PriceHistory.query.filter_by(symbol=symbol.upper()).delete()
                    db.session.commit()
                except Exception as e:
                    logger.error(f"Error clearing price history for {symbol}: {e}")
                    db.session.rollback()
                
                # Use Binance only for price history
                try:
                    backfill_7d_prices([symbol])  # Pass as list since function expects list of symbols
                    logger.info(f"Backfill completed for {symbol}")
                    synced_count += 1
                except Exception as e:
                    logger.warning(f"Binance price fetch failed for {symbol}: {e}")
            
            except Exception as e:
                logger.error(f"Error updating price history for {symbol}: {str(e)}")
                continue
        
        return jsonify({
            "success": True,
            "message": f"Successfully updated price history for {synced_count} of {len(symbols)} coins"
        })
        
    except Exception as e:
        logger.error(f"Error in api_sync_coins: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"Price sync failed: {str(e)}"
        })

@app.route("/reset-password", methods=["GET", "POST"])
@login_required
def reset_password():
    if request.method == "POST":
        password = request.form.get("password")
        if not password or len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        user = db.session.get(User, current_user.id)
        user.pwd_hash = generate_password_hash(password)
        db.session.commit()
        return jsonify({"success": True, "message": "Password updated"})
    
    # For GET requests, return a simple form
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reset Password</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .form-group { margin-bottom: 15px; }
            input[type="password"] { padding: 8px; width: 200px; }
            button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
            button:hover { background: #0056b3; }
        </style>
    </head>
    <body>
        <h2>Reset Password</h2>
        <form method="POST">
            <div class="form-group">
                <label for="password">New Password:</label><br>
                <input type="password" id="password" name="password" required minlength="6">
            </div>
            <button type="submit">Update Password</button>
        </form>
    </body>
    </html>
    '''

@app.route("/api/unhide-all", methods=["POST"])
@login_required
def unhide_all():
    data = request.get_json()
    coin_ids = data.get('coin_ids', [])
    
    if not coin_ids:
        return jsonify({"success": False, "error": "No coins selected"})
    
    # Only unhide the selected coins
    Coin.query.filter(
        Coin.user_id == current_user.id,
        Coin.hidden.is_(True),
        Coin.id.in_(coin_ids)
    ).update(
        {
            Coin.hidden: False,
            Coin.auto_hidden: False,
            Coin.force_visible: True
        },
        synchronize_session=False
    )
    
    db.session.commit()
    return jsonify({"success": True})

@app.route("/")
@login_required
def dashboard():
    # Serve the React app
    return serve_react_app()

@app.route("/dashboard.html")
@login_required
def dashboard_html():
    record_true_portfolio_value()
    # Serve the React app
    return serve_react_app()

# Favicon route to prevent 404 errors
@app.route('/favicon.ico')
def favicon():
    """Return 204 No Content for favicon requests"""
    return '', 204

def sync_coins_from_transactions(user_id=None):
    """
    Synchronize coins table with calculated balances from transaction history using ORM.
    This ensures portfolio matches actual transaction data.
    """
    if user_id is None:
        user_id = current_user.id
        
    try:
        from trading_models import AllActivity
        logger.info(f"Syncing coins table from transactions for user {user_id}")
        
        # Calculate net amounts for each asset from transactions using ORM
        from sqlalchemy import case, func
        
        transaction_assets_query = db.session.query(
            AllActivity.asset,
            func.sum(case(
                (AllActivity.type.in_(['BUY', 'GIFT', 'BONUS', 'TRANSFER', 'RECEIVE']), AllActivity.amount),
                (AllActivity.type == 'SELL', -AllActivity.amount),
                else_=0
            )).label('net_amount'),
            func.min(AllActivity.date).label('first_date'),
            func.avg(case(
                (db.and_(AllActivity.type == 'BUY', AllActivity.amount > 0), AllActivity.proceeds / AllActivity.amount),
                else_=None
            )).label('avg_buy_price')
        ).filter(
            AllActivity.status == 'FILLED',
            AllActivity.user_id == user_id
        ).group_by(AllActivity.asset).having(func.sum(case(
            (AllActivity.type.in_(['BUY', 'GIFT', 'BONUS', 'TRANSFER', 'RECEIVE']), AllActivity.amount),
            (AllActivity.type == 'SELL', -AllActivity.amount),
            else_=0
        )) > 0.000001).all()
        
        logger.info(f"Found {len(transaction_assets_query)} assets with positive balances in transaction history")
        
        # Update coins table with calculated amounts
        for asset, net_amount, first_date, avg_buy_price in transaction_assets_query:
            coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()
            
            if not coin:
                # Create new coin record
                coin = Coin(
                    user_id=user_id,
                    symbol=asset,
                    amount=float(net_amount),
                    initial_price=float(avg_buy_price or 0.0),
                    purchase_date=_format_date_only(first_date),
                    current=float(avg_buy_price or 0.0),
                    hidden=False,
                    alert_enabled=True
                )
                db.session.add(coin)
                logger.info(f"Created new coin record: {asset} with amount {net_amount}")
            else:
                # Do NOT overwrite live amount; live Binance sync sets authoritative balances
                old_amount = coin.amount
                
                # Update initial price if not set or if this is more accurate
                if not coin.initial_price or coin.initial_price == 0:
                    coin.initial_price = float(avg_buy_price or 0.0)
                    
                # Update purchase date if not set
                    if not coin.purchase_date and first_date:
                        coin.purchase_date = _format_date_only(first_date)
                    
                logger.info(f"Updated coin {asset}: amount {old_amount} (calculated net: {net_amount})")
        
        # Hide coins with zero or near-zero amounts (but don't delete them)
        zero_coins = Coin.query.filter(
            Coin.user_id == user_id,
            Coin.amount < 0.000001
        ).all()
        
        for coin in zero_coins:
            if not coin.hidden:
                coin.hidden = True
                coin.auto_hidden = True
                coin.force_visible = False
                coin.alert_enabled = False
                logger.info(f"Hiding coin {coin.symbol} with zero amount: {coin.amount}")
        
        db.session.commit()
        logger.info("Successfully synced coins table with transaction data")
        
    except Exception as e:
        logger.error(f"Error syncing coins from transactions: {e}")
        db.session.rollback()

@app.route('/api/tax/manual-investment', methods=['GET', 'POST'])
@login_required
def api_tax_manual_investment():
    try:
        if request.method == 'GET':
            amount = get_manual_tax_investment(current_user.id)
            return jsonify({
                'success': True,
                'amount': amount
            })

        data = request.get_json(force=True, silent=True) or {}
        amount = _coerce_float(data.get('amount'), 0.0) or 0.0
        updated_amount, updated_at = set_manual_tax_investment(current_user.id, amount)
        return jsonify({
            'success': True,
            'amount': updated_amount,
            'updated_at': updated_at
        })
    except Exception as e:
        logger.error(f"Manual tax investment update failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to update manual investment amount'}), 500


def _parse_transaction_datetime(value):
    """Normalize the transaction timestamp for consistent ordering."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    value = str(value).strip()
    try:
        if value.endswith('Z'):
            return datetime.fromisoformat(value[:-1] + '+00:00')
        dt_obj = datetime.fromisoformat(value)
        if dt_obj.tzinfo is None:
            return dt_obj.replace(tzinfo=timezone.utc)
        return dt_obj.astimezone(timezone.utc)
    except ValueError:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.min.replace(tzinfo=timezone.utc)


def _coerce_activity_datetime(value):
    """Coerce incoming date values to naive UTC datetimes for storage."""
    if isinstance(value, datetime):
        return value
    dt_obj = _parse_transaction_datetime(value)
    if dt_obj.tzinfo is not None:
        return dt_obj.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_obj


def _format_activity_date(value):
    """Format activity dates for JSON responses."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _format_date_only(value):
    """Format a date value as YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]


def _safe_decimal(value):
    """Convert arbitrary numeric-ish values to Decimal safely."""
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    value_str = str(value).strip()
    if not value_str:
        return Decimal('0')
    try:
        return Decimal(value_str)
    except Exception:
        return Decimal('0')


def _load_transaction_details(raw_details):
    """Parse the JSON details payload from the logs database."""
    if not raw_details:
        return {}
    if isinstance(raw_details, dict):
        return raw_details
    try:
        return json.loads(raw_details)
    except Exception:
        return {}


def _is_auto_generated_detail(raw_details):
    """Identify log rows that were synthetic counter-entries."""
    if not raw_details:
        return False
    if isinstance(raw_details, str):
        return raw_details.strip().lower().startswith('auto-generated from')
    return False


def _extract_trade_numbers(details_dict, fallback_fee):
    """Pull total value after fees, filled value, and fees from the detail payload."""
    if not isinstance(details_dict, dict):
        return Decimal('0'), Decimal('0'), fallback_fee

    total_after = _safe_decimal(details_dict.get('total_value_after_fees'))
    filled_value = _safe_decimal(details_dict.get('filled_value'))
    total_fees = _safe_decimal(details_dict.get('total_fees'))

    if total_fees <= 0:
        commission_info = details_dict.get('commission_detail_total')
        if isinstance(commission_info, dict):
            total_fees = _safe_decimal(commission_info.get('total_commission'))

    # Some payloads only include a simple "fee" field
    if total_fees <= 0:
        total_fees = _safe_decimal(details_dict.get('fee'))

    if total_after <= 0 and filled_value > 0 and total_fees > 0:
        total_after = filled_value - total_fees

    fee_used = total_fees if total_fees > 0 else fallback_fee
    return total_after, filled_value, fee_used


def _calculate_portfolio_performance(transactions, coins):
    """
    Derive realized/unrealized performance metrics from raw transaction rows and current holdings.
    Returns a dictionary with totals and per-asset breakdowns.
    """
    real_transactions = []
    for tx in transactions:
        details_raw = tx.get('details')
        if _is_auto_generated_detail(details_raw):
            continue
        asset = (tx.get('asset') or '').upper()
        if not asset:
            continue
        real_transactions.append({
            'id': tx.get('id'),
            'date': tx.get('date'),
            'asset': asset,
            'type': tx.get('type', '').upper(),
            'amount': _safe_decimal(tx.get('amount')),
            'cost_basis': _safe_decimal(tx.get('cost_basis')),
            'proceeds': _safe_decimal(tx.get('proceeds')),
            'fee': _safe_decimal(tx.get('fee')),
            'details': tx.get('details')
        })

    if real_transactions:
        real_transactions.sort(key=lambda item: (_parse_transaction_datetime(item['date']), item['id']))

    fifo_lots = defaultdict(deque)
    realized_pnl = Decimal('0')
    total_fees_paid = Decimal('0')
    total_buy_cost = Decimal('0')
    total_sell_proceeds = Decimal('0')

    for tx in real_transactions:
        tx_type = tx['type']
        amount = tx['amount']
        if amount == 0:
            continue
        details_dict = _load_transaction_details(tx['details'])
        total_after_fees, filled_value, fee_used = _extract_trade_numbers(details_dict, tx['fee'])
        fee_used = fee_used if fee_used > 0 else tx['fee']
        asset = tx['asset']

        if tx_type == 'BUY':
            if amount <= 0:
                continue
            total_fees_paid += fee_used
            if total_after_fees > 0:
                total_cost = total_after_fees
            else:
                total_cost = tx['cost_basis'] + fee_used
            fifo_lots[asset].append({'amount': amount, 'cost': total_cost})
            total_buy_cost += total_cost

        elif tx_type == 'SELL':
            quantity = abs(amount)
            if quantity <= 0:
                continue
            total_fees_paid += fee_used
            if total_after_fees > 0:
                net_proceeds = total_after_fees
            else:
                proceeds = tx['proceeds']
                if proceeds > 0:
                    net_proceeds = proceeds - fee_used
                elif filled_value > 0:
                    net_proceeds = filled_value - fee_used
                else:
                    net_proceeds = proceeds

            total_sell_proceeds += net_proceeds

            cost_total = Decimal('0')
            remaining = quantity
            lots = fifo_lots[asset]

            while remaining > 0 and lots:
                lot = lots[0]
                lot_amount = lot['amount']
                lot_cost = lot['cost']
                if lot_amount <= 0:
                    lots.popleft()
                    continue
                slice_amount = min(remaining, lot_amount)
                proportion = slice_amount / lot_amount
                cost_slice = lot_cost * proportion
                cost_total += cost_slice
                lot['amount'] = lot_amount - slice_amount
                lot['cost'] = lot_cost - cost_slice
                if lot['amount'] <= Decimal('1e-10'):
                    lots.popleft()
                remaining -= slice_amount

            recorded_cost_basis = tx['cost_basis']
            if recorded_cost_basis > 0 and cost_total < recorded_cost_basis:
                cost_total = recorded_cost_basis

            realized_pnl += net_proceeds - cost_total

    remaining_costs = {}
    for asset, lots in fifo_lots.items():
        remaining_cost = Decimal('0')
        remaining_amount = Decimal('0')
        for lot in lots:
            lot_amount = lot['amount']
            lot_cost = lot['cost']
            if lot_amount > 0 and lot_cost > 0:
                remaining_cost += lot_cost
                remaining_amount += lot_amount
        if remaining_amount > 0:
            remaining_costs[asset] = {
                'amount': remaining_amount,
                'cost': remaining_cost
            }

    holdings_value = Decimal('0')
    holdings_cost = Decimal('0')
    holdings_map = {}

    for coin in coins:
        amount = _safe_decimal(getattr(coin, 'amount', 0))
        if amount <= Decimal('0.0000001'):
            continue
        asset = (getattr(coin, 'symbol', '') or '').upper()
        if not asset:
            continue
        current_price = _safe_decimal(getattr(coin, 'current', 0))
        current_value = amount * current_price

        remaining_entry = remaining_costs.get(asset)
        if remaining_entry:
            derived_cost = remaining_entry['cost']
        else:
            initial_value = _safe_decimal(getattr(coin, 'initial_value', 0))
            if initial_value > 0:
                derived_cost = initial_value
            else:
                avg_entry = _safe_decimal(getattr(coin, 'avg_entry', 0))
                derived_cost = avg_entry * amount

        avg_price = derived_cost / amount if amount > 0 else Decimal('0')

        holdings_map[asset] = {
            'amount': float(amount),
            'cost_basis': float(derived_cost),
            'avg_price_per_unit': float(avg_price),
            'current_price': float(current_price),
            'current_value': float(current_value),
            'source': 'portfolio_table'
        }

        holdings_value += current_value
        holdings_cost += derived_cost

    unrealized_pnl = holdings_value - holdings_cost
    total_pnl = realized_pnl + unrealized_pnl

    fifo_snapshot = {
        asset: [
            {
                'amount': float(lot['amount']),
                'cost': float(lot['cost'])
            }
            for lot in lots if lot['amount'] > 0 and lot['cost'] > 0
        ]
        for asset, lots in fifo_lots.items() if any(lot['amount'] > 0 and lot['cost'] > 0 for lot in lots)
    }

    return {
        'realized_pnl': float(realized_pnl),
        'unrealized_pnl': float(unrealized_pnl),
        'total_pnl': float(total_pnl),
        'holdings_value': float(holdings_value),
        'holdings_cost': float(holdings_cost),
        'total_fees_paid': float(total_fees_paid),
        'total_buy_cost': float(total_buy_cost),
        'total_sell_proceeds': float(total_sell_proceeds),
        'holdings_map': holdings_map,
        'fifo_lots': fifo_snapshot
    }


@app.route('/api/tax-report')
@login_required
def api_tax_report():
    """Generate comprehensive tax report with cost basis and gain/loss calculations"""
    try:
        from trading_models import AllActivity
        from models import Coin
        # Use actual Binance balances from coins table, not calculated transaction totals
        # sync_coins_from_transactions() overwrites correct balances with wrong calculated amounts
        
        # Get all completed transactions using ORM
        activities = AllActivity.query.filter(
            AllActivity.user_id == current_user.id,
            AllActivity.status.in_(['FILLED', 'completed'])
        ).order_by(AllActivity.date.asc()).all()
        
        # Convert to list of dictionaries
        transactions = []
        for activity in activities:
            tx_dict = {
                'id': activity.id,
                'date': activity.date,
                'type': activity.type,
                'asset': activity.asset,
                'amount': activity.amount,
                'proceeds': activity.proceeds,
                'cost_basis': activity.cost_basis,
                'gain_loss': activity.gain_loss,
                'fee': activity.fee,
                'txid': activity.txid,
                'status': activity.status,
                'details': activity.details,
                'price_sold_at': activity.price_sold_at,
                'exchange': activity.exchange or 'coinbase'  # Default to coinbase for legacy records
            }
            transactions.append(tx_dict)
        
        # Calculate tax information for each transaction for table display
        tax_data = []
        for tx in transactions:
            asset = tx['asset']
            tx_type = tx['type']
            amount = float(tx['amount'] or 0)
            proceeds = float(tx['proceeds'] or 0)
            fee = float(tx['fee'] or 0)
            date = tx['date']
            
            tax_info = {
                'id': tx['id'],
                'date': _format_activity_date(tx['date']),
                'type': tx_type,
                'asset': asset,
                'amount': amount,
                'proceeds': proceeds,
                'fee': fee,
                'txid': tx['txid'],
                'cost_basis': float(tx['cost_basis'] or 0),  # Use database value
                'gain_loss': float(tx['gain_loss']) if tx['gain_loss'] is not None else None,  # Use database value
                'gain_loss_type': 'short_term' if (tx['gain_loss'] is not None and tx['gain_loss'] > 0) else ('loss' if (tx['gain_loss'] is not None and tx['gain_loss'] < 0) else None),
                'price_sold_at': tx.get('price_sold_at'),  # USDT price at sale/purchase
                'exchange': tx.get('exchange', 'coinbase')  # Exchange source
            }
            
            tax_data.append(tax_info)
        
        # Get actual current holdings from the coins table (which reflects real balances)
        current_coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).all()

        performance = _calculate_portfolio_performance(transactions, current_coins)
        current_holdings = performance['holdings_map']
        portfolio_holdings_value = float(performance['holdings_value'])
        portfolio_holdings_cost = performance['holdings_cost']

        staking_active_value = 0.0
        staking_pending_value = 0.0
        try:
            username = getattr(current_user, 'username', None)
            cred = get_user_credentials(username) if username else None
            # Only attempt if we have credentials to avoid ValueError spam
            if cred and (cred.api_key or cred.openai_key or cred.zai_key):
                 # Try-catch specifically for the configuration error
                try:
                    staking_active_value, staking_pending_value = calculate_staking_value_for_user(
                        cred,
                        current_user.id
                    )
                except ValueError as ve:
                    # Expected if keys are missing/invalid
                    logger.warning(f"Skipping staking value for tax report: {ve}")
                    staking_active_value = 0.0
                    staking_pending_value = 0.0
            else:
                 staking_active_value = 0.0
                 staking_pending_value = 0.0

        except Exception as staking_err:
            logger.error(f"Tax report staking valuation error: {staking_err}", exc_info=True)
            staking_active_value = 0.0
            staking_pending_value = 0.0

        total_staking_value = staking_active_value + staking_pending_value
        combined_holdings_value = portfolio_holdings_value + total_staking_value

        manual_invested = get_manual_tax_investment(current_user.id)
        user_setting_for_tax = UserSetting.query.filter_by(user_id=current_user.id).first()
        manual_updated_at = None  # This field is deprecated in new schema

        # Calculate summary statistics for the table/meta data
        valid_transactions = [t for t in tax_data if t['gain_loss'] is not None]
        sell_transactions = [t for t in valid_transactions if t['type'] == 'SELL']
        
        # Calculate total gain/loss as: Current Holdings Value - (Manual Contributions + Total Fees)
        total_gain_loss = combined_holdings_value - (manual_invested + performance['total_fees_paid'])

        summary = {
            'total_transactions': len(tax_data),  # Total including orphaned
            'valid_transactions': len(valid_transactions),  # Only those with proper cost basis
            'total_buys': len([t for t in tax_data if t['type'] == 'BUY']),
            'total_sells': len([t for t in tax_data if t['type'] == 'SELL']),
            'valid_sells': len(sell_transactions),  # Only sells with cost basis
            'excluded_sells': len([t for t in tax_data if t['type'] == 'SELL' and t['gain_loss'] is None]),
            'total_gifts': len([t for t in tax_data if t['type'] in ['GIFT', 'BONUS', 'TRANSFER', 'RECEIVE']]),
            'total_gain_loss': total_gain_loss,
            'realized_gain': performance['realized_pnl'],
            'unrealized_gain': performance['unrealized_pnl'],
            'manual_invested_amount': manual_invested,
            'manual_invested_updated_at': manual_updated_at,
            'tracked_cost_basis': portfolio_holdings_cost,
            'current_holdings_value': combined_holdings_value,
            'current_holdings_cost_basis': portfolio_holdings_cost,
            'portfolio_holdings_value': portfolio_holdings_value,
            'staking_active_value': staking_active_value,
            'staking_pending_value': staking_pending_value,
            'staking_total_value': total_staking_value,
            'total_fees_paid': performance['total_fees_paid'],
            'total_buy_volume': performance['total_buy_cost'],
            'total_sell_proceeds': performance['total_sell_proceeds'],
            'assets_traded': list(set(t['asset'] for t in tax_data)),
            'assets_with_current_holdings': len(current_holdings),
            'date_range': {
                'start': min(t['date'] for t in tax_data) if tax_data else None,
                'end': max(t['date'] for t in tax_data) if tax_data else None
            }
        }
        
        return jsonify({
            'transactions': tax_data,
            'summary': summary,
            'current_holdings': current_holdings,
            'fifo_lots': performance['fifo_lots']
        })
        
    except Exception as e:
        logger.error(f"Error generating tax report: {str(e)}")
        return jsonify({"error": "Failed to generate tax report"}), 500


@app.route('/api/transactions', methods=['POST'])
@login_required
def add_transaction():
    """Add a new transaction to the all_activities table using ORM"""
    try:
        from trading_models import AllActivity
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['date', 'type', 'asset', 'amount']
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == '':
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Generate unique transaction ID
        import uuid
        import time
        txid = f"manual_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
        activity_date = _coerce_activity_datetime(data['date'])

        # Create new activity using ORM
        new_activity = AllActivity(
            date=activity_date,
            type=data['type'].upper(),
            asset=data['asset'].upper(),
            amount=float(data['amount']) if data['amount'] else 0.0,
            proceeds=float(data.get('proceeds', 0)) if data.get('proceeds') else 0.0,
            cost_basis=float(data.get('cost_basis', 0)) if data.get('cost_basis') else 0.0,
            gain_loss=float(data.get('gain_loss', 0)) if data.get('gain_loss') else 0.0,
            fee=float(data.get('fee', 0)) if data.get('fee') else 0.0,
            description=data.get('description', ''),
            txid=txid,
            status=data.get('status', 'completed'),
            details=data.get('details', 'Manual entry'),
            user_id=current_user.id,
            avg_entry=float(data.get('avg_entry', 0)) if data.get('avg_entry') else 0.0,
            exchange=data.get('exchange', 'manual')
        )
        
        db.session.add(new_activity)
        db.session.commit()
        
        logger.info(f"Added manual transaction: {new_activity.type} {new_activity.amount} {new_activity.asset}")
        
        return jsonify({
            "success": True,
            "message": "Transaction added successfully",
            "txid": txid
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding transaction: {str(e)}")
        return jsonify({"error": "Failed to add transaction"}), 500


PORTFOLIO_HISTORY_RANGE_CONFIG = {
    "4H": {"duration_ms": 4 * 60 * 60 * 1000, "increment_ms": 1 * 60 * 60 * 1000, "points": 4},
    "12H": {"duration_ms": 12 * 60 * 60 * 1000, "increment_ms": 2 * 60 * 60 * 1000, "points": 6},
    "1D": {"duration_ms": 24 * 60 * 60 * 1000, "increment_ms": 4 * 60 * 60 * 1000, "points": 6},
    "3D": {"duration_ms": 72 * 60 * 60 * 1000, "increment_ms": 12 * 60 * 60 * 1000, "points": 6},
    "7D": {"duration_ms": 168 * 60 * 60 * 1000, "increment_ms": 24 * 60 * 60 * 1000, "points": 7},
    "4W": {"duration_ms": 4 * 7 * 24 * 60 * 60 * 1000, "increment_ms": 7 * 24 * 60 * 60 * 1000, "points": 4},
    "3M": {"duration_ms": 90 * 24 * 60 * 60 * 1000, "increment_ms": 30 * 24 * 60 * 60 * 1000, "points": 3},
    "6M": {"duration_ms": 180 * 24 * 60 * 60 * 1000, "increment_ms": 30 * 24 * 60 * 60 * 1000, "points": 6},
    "1Y": {"duration_ms": 365 * 24 * 60 * 60 * 1000, "increment_ms": 30 * 24 * 60 * 60 * 1000, "points": 12},
}


def _compute_portfolio_history_series(user_id, range_key):
    """Return evenly spaced portfolio history points straight from stored values."""
    config = PORTFOLIO_HISTORY_RANGE_CONFIG.get(range_key, PORTFOLIO_HISTORY_RANGE_CONFIG["1D"])
    now_ms = int(time.time() * 1000)
    duration_ms = config["duration_ms"]
    start_ms = now_ms - duration_ms

    end_ts = math.ceil(now_ms / 1000)
    start_ts = max(0, math.floor(start_ms / 1000) - 3600)

    from trading_models import PortfolioValueHistory
    
    # Query portfolio history using ORM
    raw_rows = PortfolioValueHistory.query.filter(
        PortfolioValueHistory.user_id == user_id,
        PortfolioValueHistory.timestamp >= datetime.utcfromtimestamp(start_ts),
        PortfolioValueHistory.timestamp <= datetime.utcfromtimestamp(end_ts)
    ).order_by(PortfolioValueHistory.timestamp.asc()).all()

    if not raw_rows:
        return []

    raw_data = [(int(row.timestamp.timestamp()) * 1000, round(float(row.value), 2)) for row in raw_rows if row.value is not None]
    if not raw_data:
        return []

    chart_data: List[List[float]] = []
    data_len = len(raw_data)
    data_idx = 0
    current_value = raw_data[0][1]

    for i in range(config["points"]):
        target_ms = now_ms - (config["points"] - 1 - i) * config["increment_ms"]

        while data_idx < data_len and raw_data[data_idx][0] <= target_ms:
            current_value = raw_data[data_idx][1]
            data_idx += 1

        chart_data.append([target_ms, current_value])

    return chart_data


@app.route("/api/true-portfolio-history")
@login_required
def api_true_portfolio_history():
    """Return portfolio trend points derived strictly from stored history."""
    try:
        req_range = request.args.get("range", "1D")
        chart_data = _compute_portfolio_history_series(current_user.id, req_range)
        if chart_data:
            values = [point[1] for point in chart_data]
            logger.info(
                f"Portfolio history {req_range}: {len(chart_data)} points "
                f"(min=${min(values):.2f}, max=${max(values):.2f})"
            )
        else:
            logger.info(f"Portfolio history {req_range}: no stored points available")

        response = make_response(jsonify(chart_data))
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    except Exception as e:
        logger.error(f"true-portfolio-history error: {str(e)}")
        return jsonify([])

@app.route("/api/record-portfolio-value", methods=["POST"])
@login_required
def api_record_portfolio_value():
    """Manually record current portfolio value for testing"""
    try:
        # Run the portfolio value recording function
        record_true_portfolio_value()
        return jsonify({
            "success": True,
            "message": "Portfolio value recorded successfully"
        })
    except Exception as e:
        logger.error(f"Error recording portfolio value: {e}")
        return jsonify({
            "success": False,
            "message": f"Error recording portfolio value: {str(e)}"
        }), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error("=== Uncaught Exception ===", exc_info=True)
    return "Internal Server Error", 500

@app.route("/test-session")
@login_required
def test_session():
    return f"Logged in as: {getattr(current_user, 'username', None)}"
@app.route("/api/hide-coin", methods=["POST"])
@login_required
def hide_coin():
    data = request.get_json()
    coin_id = data.get("coin_id") or data.get("id")  # Support both coin_id and id
    hidden = data.get("hidden", True)
    
    logger.info(f"Hide coin request: coin_id={coin_id}, hidden={hidden}, user_id={current_user.id}")
    
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if coin:
        logger.info(f"Found coin: {coin.symbol}, current hidden status: {coin.hidden}")
        coin.hidden = hidden
        if hidden:  # Automatically disable alerts when hiding
            coin.alert_enabled = False
            coin.force_visible = False
            coin.auto_hidden = False
        else:
            coin.auto_hidden = False
            coin.force_visible = True
        db.session.commit()
        logger.info(f"Coin {coin.symbol} hidden status updated to: {coin.hidden}")
        # If unhidden, trigger backfill for this coin
        if not hidden:
            threading.Thread(target=backfill_7d_prices, args=([coin.symbol],), daemon=True).start()
        return jsonify({"success": True})
    else:
        logger.error(f"Coin not found: coin_id={coin_id}, user_id={current_user.id}")
    return jsonify({"success": False, "error": "Coin not found"}), 404

@app.route("/api/set-favorite", methods=["POST"])
@login_required
def set_favorite():
    data = request.get_json()
    coin_id = data.get("id")
    favorite = data.get("favorite", False)
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if coin:
        coin.is_manual = favorite  # Assuming `is_manual` is used for favorite
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Coin not found"}), 404

def get_true_portfolio_value():
    """Get portfolio value from Binance.US account"""
    try:
        from binance.client import Client
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            logger.error("Binance API credentials not found")
            return 0.0
            
        client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
        account = client.get_account()
        
        total_value = 0.0
        for balance in account['balances']:
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])
            total = free + locked
            
            if total > 0:
                if asset == 'USD' or asset in ['USDT', 'USDC', 'BUSD']:
                    total_value += total
                else:
                    try:
                        price = fetch_binance_price(asset)
                        if price and price > 0:
                            total_value += total * price
                    except Exception as e:
                        logger.debug(f"Failed to get price for {asset}: {e}")
        
        return round(total_value, 2)
    except Exception as e:
        logger.error(f"Binance portfolio value error: {str(e)}")
        return 0.0
    
def coin_to_dict(c):
    return {
        "id": c.id,
        "symbol": c.symbol,
        "avg_entry": round(c.avg_entry or 0, 6),
        "current": round(c.current or 0, 6),
        "amount": round(c.amount or 0, 6),
        "current_value": round((c.current or 0) * (c.amount or 0), 6),
        "custom_lower_pct": c.custom_lower_pct,
        "custom_upper_pct": c.custom_upper_pct,
        "alert_enabled": c.alert_enabled,
        "favorite": c.is_manual,
        "hidden": c.hidden,
        "auto_hidden": c.auto_hidden,
        "force_visible": c.force_visible,
        "pct_change": round(((c.current - c.avg_entry) / c.avg_entry * 100) if c.avg_entry else 0.0, 6),
    }

@app.route("/api/pionex-price")
@login_required
def api_pionex_price():
    symbol = request.args.get("symbol", "").upper()
    try:
        # Pionex uses lowercase and USDT pairs, e.g., piusdt
        pair = f"{symbol.lower()}usdt"
        url = f"https://api.pionex.com/api/v1/market/ticker?symbol={pair}"
        r = requests.get(url, timeout=10)
        data = r.json()
        price = float(data["data"]["price"])
        return jsonify({"price": price})
    except Exception as e:
        return jsonify({"price": None, "error": str(e)})
    
@app.route("/api/binance-price")
@login_required
def api_binance_price():
    symbol = request.args.get("symbol", "").upper()
    price = fetch_binance_price(symbol)
    return jsonify({"price": price})


def apply_auto_visibility_rules(coin, current_value):
    """Apply automatic hide/unhide rules based on USD value thresholds."""
    changed = False
    try:
        value = float(current_value or 0.0)
    except (TypeError, ValueError):
        value = 0.0

    # More lenient threshold: unhide if > $0.10, hide if < $0.01
    if value >= 0.10:
        if coin.auto_hidden:
            if coin.hidden:
                coin.hidden = False
                changed = True
            coin.auto_hidden = False
            changed = True
        # If manually hidden, we respect it unless it's auto_hidden
    elif value < 0.01:
        if not coin.force_visible and not coin.is_manual:
            if not coin.hidden:
                coin.hidden = True
                changed = True
            if not coin.auto_hidden:
                coin.auto_hidden = True
                changed = True
    
    return changed

COINGECKO_CHART_CACHE = {}  # {slug: (data, timestamp)}
COINGECKO_CHART_CACHE_TTL = 300  # 5 minutes


@app.route("/api/chart_history/<symbol>")
@login_required
def chart_history(symbol):
    """Get price history for the last 7 days and return 7 evenly spaced points using ORM"""
    try:
        from models import PriceHistory
        now = int(time.time())
        cutoff = now - 7 * 24 * 60 * 60
        
        # Get all price points for the last 7 days using ORM
        rows = PriceHistory.query.filter(
            PriceHistory.symbol == symbol.upper(),
            PriceHistory.timestamp >= cutoff
        ).order_by(PriceHistory.timestamp.asc()).all()
        
        if not rows:
            return jsonify({"prices": []})

        # Build 7 points: latest at now, then at now-1d, now-2d, ..., now-6d
        points = []
        timestamps = [row.timestamp for row in rows]
        prices = [row.price for row in rows]
        
        for i in range(6, -1, -1):  # 6 days ago to today
            target_ts = now - i * 24 * 60 * 60
            # Find the latest price at or before target_ts
            idx = None
            for j in range(len(timestamps)):
                if timestamps[j] > target_ts:
                    break
                idx = j
            
            if idx is not None:
                points.append([target_ts * 1000, prices[idx]])
            else:
                # If no earlier price, use the earliest available
                points.append([target_ts * 1000, prices[0]])
        
        return jsonify({"prices": points})
    except Exception as e:
        logger.error(f"chart_history: Exception for {symbol}: {e}", exc_info=True)
        return jsonify({"prices": [], "error": str(e)}), 200

@app.route("/api/coingecko_chart/<slug>")
def coingecko_chart(slug):
    now = time.time()
    # Serve from cache if fresh
    cached = COINGECKO_CHART_CACHE.get(slug)
    if cached and now - cached[1] < COINGECKO_CHART_CACHE_TTL:
        return jsonify(cached[0])
    url = f"https://api.coingecko.com/api/v3/coins/{slug}/market_chart?vs_currency=usd&days=7"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 429:
            # Fallback: use local DB
            prices = get_last_7d_prices(slug.upper())
            if prices and len(prices) >= 2:
                # Synthesize CoinGecko-like response
                now_ms = int(time.time()) * 1000
                step = 24 * 60 * 60 * 1000 // max(len(prices)-1, 1)
                price_points = [[now_ms - step * (len(prices)-1-i), p] for i, p in enumerate(prices)]
                data = {"prices": price_points}
                return jsonify(data)
            return jsonify({"error": "CoinGecko rate limit reached and no local data available."}), 429
        if r.status_code != 200:
            return jsonify({"error": f"CoinGecko error {r.status_code} for slug {slug}"}), 404
        data = r.json()
        if "prices" not in data or not data["prices"]:
            # Fallback: use local DB
            prices = get_last_7d_prices(slug.upper())
            if prices and len(prices) >= 2:
                now_ms = int(time.time()) * 1000
                step = 24 * 60 * 60 * 1000 // max(len(prices)-1, 1)
                price_points = [[now_ms - step * (len(prices)-1-i), p] for i, p in enumerate(prices)]
                data = {"prices": price_points}
                return jsonify(data)
            return jsonify({"error": f"No price data for slug {slug}"}), 404
        COINGECKO_CHART_CACHE[slug] = (data, now)
        return jsonify(data)
    except Exception as e:
        # Fallback: use local DB
        prices = get_last_7d_prices(slug.upper())
        if prices and len(prices) >= 2:
            now_ms = int(time.time()) * 1000
            step = 24 * 60 * 60 * 1000 // max(len(prices)-1, 1)
            price_points = [[now_ms - step * (len(prices)-1-i), p] for i, p in enumerate(prices)]
            data = {"prices": price_points}
            return jsonify(data)
        return jsonify({"error": str(e)}), 500

@app.route("/api/logs/taxable")
@login_required
def api_logs_taxable():
    """Get taxable logs (SELL transactions) using ORM"""
    try:
        from trading_models import AllActivity
        rows = AllActivity.query.filter_by(
            user_id=current_user.id,
            type='SELL',
            status='FILLED'
        ).order_by(AllActivity.date.desc()).all()
        
        result = []
        for r in rows:
            result.append({
                'date': r.date.strftime('%Y-%m-%d %H:%M:%S') if isinstance(r.date, datetime) else r.date,
                'type': r.type,
                'asset': r.asset,
                'amount': r.amount,
                'proceeds': r.proceeds,
                'cost_basis': r.cost_basis,
                'gain_loss': r.gain_loss,
                'fee': r.fee,
                'description': r.description,
                'txid': r.txid
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in api_logs_taxable: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/coin-data-live")
@login_required
def api_coin_data_live():
    """Live data endpoint for background refresh - Binance only"""
    try:
        logger.error("=== API_COIN_DATA_LIVE CALLED ===")
        coins = Coin.query.filter_by(user_id=current_user.id).all()
        logger.error(f"[LIVE] DB coins: {[c.symbol for c in coins]}")
        logger.error(f"[LIVE] User ID: {current_user.id}")
        logger.error(f"[LIVE] Total coins found: {len(coins)}")

        portfolio = []
        visibility_changed = False
        price_changed = False

        def _to_float(val):
            try:
                if isinstance(val, str):
                    return float(val.replace(',', '').strip())
                return float(val)
            except Exception:
                return 0.0

        for coin in coins:
            try:
                symbol = (coin.symbol or '').upper()
                logger.error(f"[LIVE] Processing coin: {symbol}")
                amount = _to_float(coin.amount)
                logger.error(f"[LIVE] {symbol} amount: {amount}")

                current_price = coin.current or 0.0
                if not current_price:
                    try:
                        current_price = fetch_crypto_price(coin.symbol)
                        coin.current = current_price
                        price_changed = True
                    except Exception as e:
                        logger.error(f"[LIVE] Failed to fetch price for {symbol}: {e}")
                        try:
                            current_price = float((coin.avg_entry or 0)) if not isinstance(coin.avg_entry, str) else float(coin.avg_entry.replace(',', '').strip())
                        except Exception:
                            current_price = 0.0

                current_value = amount * current_price if current_price else 0.0
                logger.error(f"[LIVE] {symbol} current_value: {current_value}")

                if apply_auto_visibility_rules(coin, current_value):
                    visibility_changed = True

                if coin.hidden:
                    logger.error(f"[LIVE] {symbol} skipped: hidden flag")
                    continue

                if amount <= 0 and not coin.force_visible:
                    logger.error(f"[LIVE] {symbol} skipped: amount <= 0 and not force_visible")
                    continue

                avg_entry_val = _to_float(coin.avg_entry)
                pct_change = 0.0
                if avg_entry_val > 0:
                    pct_change = ((current_price - avg_entry_val) / avg_entry_val) * 100

                sentiment = get_coin_sentiment(symbol, coin, current_price, current_user.username)

                logger.error(f"[LIVE] {symbol} included in portfolio response")
                portfolio.append({
                    "id": coin.id,
                    "symbol": symbol,
                    "amount": amount,
                    "initial_price": avg_entry_val,
                    "avg_entry": avg_entry_val,
                    "initial_value": (coin.initial_value if _to_float(coin.initial_value) > 0 else (avg_entry_val * amount if avg_entry_val and amount else 0.0)),
                    "purchase_date": coin.purchase_date,
                    "current_price": current_price,
                    "current_value": current_value,
                    "pct_change": pct_change,
                    "sentiment": sentiment,
                    "alert_enabled": coin.alert_enabled,
                    "note": coin.note,
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "custom_lower_type": coin.custom_lower_type or "#",
                    "custom_upper_type": coin.custom_upper_type or "#",
                    "down_alert": coin.custom_lower_val,
                    "up_alert": coin.custom_upper_val,
                    "favorite": coin.is_manual,
                    "force_visible": coin.force_visible,
                    "force_visible": coin.force_visible,
                    "volatility_pct": coin.volatility_pct,
                    "sentiment_last_updated": coin.sentiment_last_updated.isoformat() if hasattr(coin, 'sentiment_last_updated') and coin.sentiment_last_updated else None
                })
            except Exception as e:
                logger.error(f"[LIVE] Error processing coin {getattr(coin,'symbol','?')}: {e}", exc_info=True)
                try:
                    symbol = (coin.symbol or '').upper()
                    amount = _to_float(getattr(coin, 'amount', 0))
                    avg_entry_val = _to_float(getattr(coin, 'avg_entry', 0))
                    current_price = _to_float(getattr(coin, 'current', 0)) or avg_entry_val
                    current_value = amount * (current_price or 0)
                    logger.error(f"[LIVE] {symbol} fallback included in portfolio response")
                    portfolio.append({
                        "id": getattr(coin, 'id', None),
                        "symbol": symbol,
                        "amount": amount,
                        "initial_price": avg_entry_val,
                        "avg_entry": avg_entry_val,
                        "initial_value": (getattr(coin, 'initial_value', 0) if _to_float(getattr(coin, 'initial_value', 0)) > 0 else (avg_entry_val * amount if avg_entry_val and amount else 0.0)),
                        "purchase_date": getattr(coin, 'purchase_date', None),
                        "current_price": current_price,
                        "current_value": current_value,
                        "pct_change": 0.0,
                        "sentiment": getattr(coin, 'sentiment', 'Hold'),
                        "alert_enabled": getattr(coin, 'alert_enabled', True),
                        "note": getattr(coin, 'note', ''),
                        "custom_lower_val": getattr(coin, 'custom_lower_val', None),
                        "custom_upper_val": getattr(coin, 'custom_upper_val', None),
                        "custom_lower_type": (getattr(coin, 'custom_lower_type', None) or "#"),
                        "custom_upper_type": (getattr(coin, 'custom_upper_type', None) or "#"),
                        "down_alert": getattr(coin, 'custom_lower_val', None),
                        "up_alert": getattr(coin, 'custom_upper_val', None),
                        "favorite": getattr(coin, 'is_manual', False),
                        "force_visible": getattr(coin, 'force_visible', False),
                        "force_visible": getattr(coin, 'force_visible', False),
                        "volatility_pct": getattr(coin, 'volatility_pct', None),
                        "sentiment_last_updated": getattr(coin, 'sentiment_last_updated', None).isoformat() if getattr(coin, 'sentiment_last_updated', None) else None
                    })
                except Exception:
                    logger.error(f"[LIVE] {symbol} fallback failed, coin skipped")
                    pass

        if visibility_changed or price_changed:
            db.session.commit()

        logger.error(f"[LIVE] Final portfolio response: {[c['symbol'] for c in portfolio]}")
        return jsonify({"portfolio": portfolio})

    except Exception as e:
        logger.error(f"Error in api_coin_data_live: {e}")
        db.session.rollback()
        return jsonify({"portfolio": [], "error": "Error retrieving portfolio data"}), 500


@app.route("/api/coin-data")
@login_required
def api_coin_data():
    """Get user's cryptocurrency portfolio data with Binance balance sync"""
    logger.error("=== API_COIN_DATA CALLED ===")
    try:
        coins = Coin.query.filter_by(user_id=current_user.id).all()
        # logger.error(f"[DEBUG] DB coins: {[c.symbol for c in coins]}")
        # logger.error(f"[DEBUG] User ID: {current_user.id}")
        # logger.error(f"[DEBUG] Total coins found: {len(coins)}")

        portfolio = []
        visibility_changed = False
        price_changed = False

        def _to_float(val):
            try:
                if isinstance(val, str):
                    return float(val.replace(',', '').strip())
                return float(val)
            except Exception:
                return 0.0

        for coin in coins:
            try:
                symbol = coin.symbol.upper()
                # logger.error(f"[DEBUG] Processing coin: {symbol}")
                amount = _to_float(coin.amount)
                # logger.error(f"[DEBUG] {symbol} amount: {amount}")

                if symbol in ['USD', 'USDT', 'USDC', 'DAI']:
                    current_price = 1.0
                else:
                    try:
                        current_price = fetch_binance_price(symbol)
                        if current_price and current_price > 0:
                            coin.current = current_price
                            price_changed = True
                        else:
                            current_price = coin.current or _to_float(coin.avg_entry) or 0
                    except Exception as e:
                        logger.error(f"Failed to fetch price for {symbol}: {e}")
                        current_price = coin.current or _to_float(coin.avg_entry) or 0

                current_value = amount * current_price if current_price else 0
                # logger.error(f"[DEBUG] {symbol} current_value: {current_value}")

                if apply_auto_visibility_rules(coin, current_value):
                    visibility_changed = True

                if coin.hidden:
                    # logger.error(f"[DEBUG] {symbol} skipped: hidden flag")
                    continue

                if amount <= 0 and not coin.force_visible:
                    # logger.error(f"[DEBUG] {symbol} skipped: amount <= 0 and not force_visible")
                    continue

                cost_basis = get_cost_basis_for_asset(current_user.id, symbol)
                avg_entry_val = _to_float(coin.avg_entry)
                pct_change = round(((current_price - avg_entry_val) / avg_entry_val * 100), 6) if avg_entry_val and current_price else 0.0
                purchase_date = coin.purchase_date

                # logger.error(f"[DEBUG] {symbol} included in portfolio response")
                portfolio.append({
                    "id": coin.id,
                    "symbol": symbol,
                    "initial_price": avg_entry_val,
                    "avg_entry": avg_entry_val,
                    "initial_value": (coin.initial_value if _to_float(coin.initial_value) > 0 else (avg_entry_val * amount if avg_entry_val and amount else 0.0)),
                    "purchase_date": purchase_date,
                    "current_price": current_price,
                    "amount": amount,
                    "cost_basis": cost_basis,
                    "current_value": round(current_value, 6),
                    "pct_change": pct_change,
                    "custom_lower_pct": coin.custom_lower_pct,
                    "custom_upper_pct": coin.custom_upper_pct,
                    "custom_lower_type": coin.custom_lower_type or "#",
                    "custom_upper_type": coin.custom_upper_type or "#",
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "down_alert": coin.custom_lower_val,
                    "up_alert": coin.custom_upper_val,
                    "alert_enabled": coin.alert_enabled,
                    "favorite": coin.is_manual,
                    "hidden": coin.hidden,
                    "has_note": False,
                    "hasPendingOrder": False,
                    "sentiment": coin.sentiment or get_coin_sentiment(symbol, coin=coin, current_price=current_price, username=current_user.username),
                    "force_visible": coin.force_visible,
                    "volatility_pct": coin.volatility_pct,
                    "sentiment_last_updated": coin.sentiment_last_updated.isoformat() if hasattr(coin, 'sentiment_last_updated') and coin.sentiment_last_updated else None
                })
            except Exception as e:
                logger.error(f"[api_coin_data] Error processing coin {getattr(coin,'symbol','?')}: {e}", exc_info=True)
                continue

        if visibility_changed or price_changed:
            db.session.commit()

        # logger.error(f"[DEBUG] Final portfolio response: {[c['symbol'] for c in portfolio]}")
        return jsonify({"portfolio": portfolio})
    except Exception as e:
        logger.error(f"api_coin_data error: {str(e)}")
        logger.error(f"Exception type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"Unexpected error in api_coin_data: {str(e)}")
        return jsonify({"portfolio": []})

@app.route("/api/portfolio-history")
@login_required
def api_portfolio_history():
    """Legacy endpoint retained for compatibility; delegates to true portfolio history."""
    try:
        points = _compute_portfolio_history_series(current_user.id, request.args.get("range", "1D"))
        response = make_response(jsonify(points))
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
    except Exception as e:
        logger.error(f"api_portfolio_history error: {str(e)}")
        return jsonify([])
    
@app.route("/api/update-note", methods=["POST"])
@login_required
def api_update_note():
    """Update note for a coin or watchlist item"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
            
        coin_id = data.get("coin_id")
        note = data.get("note", "")
        
        if not coin_id:
            return jsonify({"success": False, "error": "coin_id is required"}), 400
        
        # First try to find in portfolio coins table
        coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
        if coin:
            coin.note = note
            db.session.commit()
            logger.info(f"Updated note for portfolio coin {coin.symbol} (id={coin_id}): {note[:50]}...")
            return jsonify({"success": True, "message": "Portfolio note updated"})
        
        # If not found in portfolio, try watchlist table
        watchlist_coin = WatchlistCoin.query.filter_by(id=coin_id, user_id=current_user.id).first()
        if watchlist_coin:
            watchlist_coin.note = note
            db.session.commit()
            logger.info(f"Updated note for watchlist coin {watchlist_coin.symbol} (id={coin_id}): {note[:50]}...")
            return jsonify({"success": True, "message": "Watchlist note updated"})
        
        return jsonify({"success": False, "error": "Coin not found in portfolio or watchlist"}), 404
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating note: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/set-initial-price", methods=["POST"])
@login_required
def api_set_initial_price():
    data = request.get_json()
    coin_id = data.get("id")
    price = float(data.get("price", 0.0))
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if coin:
        coin.initial_price = price
        coin.is_manual = True
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Coin not found"}), 404

@app.route("/api/delete-coin", methods=["POST"])
@login_required
def api_delete_coin():
    data = request.get_json()
    coin_id = data.get("id")
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if coin:
        db.session.delete(coin)
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Coin not found"}), 404

@app.route("/api/set-custom-pct", methods=["POST"])
@login_required
def set_custom_pct():
    data = request.get_json()
    coin_id = data.get("id")
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if not coin:
        return jsonify({"success": False, "error": "Coin not found"})
    
    # Handle percentage values - store in custom_lower_pct/custom_upper_pct
    if "custom_lower_pct" in data:
        val = data["custom_lower_pct"]
        coin.custom_lower_pct = float(val) if val not in ("", None) else None
    if "custom_upper_pct" in data:
        val = data["custom_upper_pct"]
        coin.custom_upper_pct = float(val) if val not in ("", None) else None
    
    # Handle number values - store in custom_lower_val/custom_upper_val
    if "custom_lower_val" in data:
        val = data["custom_lower_val"]
        coin.custom_lower_val = float(val) if val not in ("", None) else None
    if "custom_upper_val" in data:
        val = data["custom_upper_val"]
        coin.custom_upper_val = float(val) if val not in ("", None) else None
    
    # Handle type changes
    if "custom_lower_type" in data:
        coin.custom_lower_type = data["custom_lower_type"]
    if "custom_upper_type" in data:
        coin.custom_upper_type = data["custom_upper_type"]
    
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/set-alert", methods=["POST"])
@login_required
def set_alert():
    data = request.get_json()
    coin = Coin.query.filter_by(id=data["id"], user_id=current_user.id).first()
    if not coin:
        return jsonify({"error": "Coin not found"}), 404
    coin.alert_enabled = not coin.alert_enabled  # Toggle the alert
    db.session.commit()
    return jsonify({"success": True, "alert_enabled": coin.alert_enabled})

@app.route("/api/set-custom-pct-type", methods=["POST"])
@login_required
def set_custom_pct_type():
    d = request.get_json()
    logger.info(f"[set-custom-pct-type] Received data: {d}")
    
    coin = Coin.query.filter_by(id=d["id"], user_id=current_user.id).first()
    if not coin:
        return jsonify({"error": "Coin not found"}), 404
    
    direction = d.get("type", "")  # "down" or "up"
    pct_type = d.get("pct_type", "#")  # "#", "%", or "Auto%"
    value = d.get("value")  # The text box value
    
    if direction == "down":
        coin.custom_lower_type = pct_type
        
        if pct_type == "#":
            # Number type - store in custom_lower_val, clear custom_lower_pct (rounded to 2 decimal places)
            coin.custom_lower_val = round(float(value), 2) if value != '' and value is not None else None
            coin.custom_lower_pct = None
            logger.info(f"[set-custom-pct-type] Set {coin.symbol} down_alert (#) to {coin.custom_lower_val}")
            
        elif pct_type == "%":
            # Percentage type - store in custom_lower_pct, clear custom_lower_val (rounded to 2 decimal places)
            coin.custom_lower_pct = round(float(value), 2) if value != '' and value is not None else None
            coin.custom_lower_val = None
            logger.info(f"[set-custom-pct-type] Set {coin.symbol} down_alert (%) to {coin.custom_lower_pct}")
            
        elif pct_type == "Auto%":
            # Auto percentage - calculate value automatically, store in custom_lower_pct (rounded to 2 decimal places)
            coin.custom_lower_val = None
            auto_value = calculate_auto_alert(coin.symbol, "down", coin.avg_entry)
            coin.custom_lower_pct = round(auto_value, 2) if auto_value is not None else None
            logger.info(f"[set-custom-pct-type] Set {coin.symbol} down_alert (Auto%) to {coin.custom_lower_pct}")
            
    elif direction == "up":
        coin.custom_upper_type = pct_type
        
        if pct_type == "#":
            # Number type - store in custom_upper_val, clear custom_upper_pct (rounded to 2 decimal places)
            coin.custom_upper_val = round(float(value), 2) if value != '' and value is not None else None
            coin.custom_upper_pct = None
            logger.info(f"[set-custom-pct-type] Set {coin.symbol} up_alert (#) to {coin.custom_upper_val}")
            
        elif pct_type == "%":
            # Percentage type - store in custom_upper_pct, clear custom_upper_val (rounded to 2 decimal places)
            coin.custom_upper_pct = round(float(value), 2) if value != '' and value is not None else None
            coin.custom_upper_val = None
            logger.info(f"[set-custom-pct-type] Set {coin.symbol} up_alert (%) to {coin.custom_upper_pct}")
            
        elif pct_type == "Auto%":
            # Auto percentage - calculate value automatically, store in custom_upper_pct (rounded to 2 decimal places)
            coin.custom_upper_val = None
            auto_value = calculate_auto_alert(coin.symbol, "up", coin.initial_price)
            coin.custom_upper_pct = round(auto_value, 2) if auto_value is not None else None
            logger.info(f"[set-custom-pct-type] Set {coin.symbol} up_alert (Auto%) to {coin.custom_upper_pct}")
    
    db.session.commit()
    
    # Return the updated values so frontend can update display
    response_data = {"success": True}
    if direction == "down":
        response_data["custom_lower_type"] = coin.custom_lower_type
        response_data["custom_lower_val"] = coin.custom_lower_val
        response_data["custom_lower_pct"] = coin.custom_lower_pct
    elif direction == "up":
        response_data["custom_upper_type"] = coin.custom_upper_type
        response_data["custom_upper_val"] = coin.custom_upper_val
        response_data["custom_upper_pct"] = coin.custom_upper_pct
    
    return jsonify(response_data)

@app.route("/api/clear-alert-state", methods=["POST"])
@login_required
def api_clear_alert_state():
    try:
        removed = clear_alert_state(current_user.id)
        return jsonify({"success": True, "removed": removed})
    except Exception as e:
        logger.error(f"/api/clear-alert-state error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/debug-alerts")
@login_required
def debug_alerts():
    """Debug endpoint to check alert system status"""
    try:
        # Check if user has ETH with alerts enabled
        eth_coin = Coin.query.filter_by(
            user_id=current_user.id, 
            symbol='ETH', 
            alert_enabled=True, 
            hidden=False
        ).first()
        
        if not eth_coin:
            return jsonify({
                "error": "No ETH coin found with alerts enabled",
                "user_coins": [c.symbol for c in Coin.query.filter_by(user_id=current_user.id).all()]
            })
        
        # Get current price
        current_price = fetch_crypto_price('ETH')
        
        # Calculate thresholds
        thresholds = {}
        if eth_coin.custom_upper_type == "#" and eth_coin.custom_upper_val:
            thresholds['up_threshold'] = round(float(eth_coin.custom_upper_val), 6)
        elif eth_coin.custom_upper_type in ["%", "Auto%"] and eth_coin.custom_upper_pct:
            thresholds['up_threshold'] = round(eth_coin.initial_price * (1 + float(eth_coin.custom_upper_pct) / 100), 6)
        
        if eth_coin.custom_lower_type == "#" and eth_coin.custom_lower_val:
            thresholds['down_threshold'] = round(float(eth_coin.custom_lower_val), 6)
        elif eth_coin.custom_lower_type in ["%", "Auto%"] and eth_coin.custom_lower_pct:
            thresholds['down_threshold'] = round(eth_coin.initial_price * (1 - float(eth_coin.custom_lower_pct) / 100), 6)
        
        # Check alert state
        alert_states = {}
        if 'up_threshold' in thresholds:
            alert_states['up_state'] = get_last_alert_state(
                current_user.id, 'ETH', 'up', 
                source="portfolio", 
                threshold=thresholds['up_threshold']
            )
        if 'down_threshold' in thresholds:
            alert_states['down_state'] = get_last_alert_state(
                current_user.id, 'ETH', 'down', 
                source="portfolio", 
                threshold=thresholds['down_threshold']
            )
        
        return jsonify({
            "user_id": current_user.id,
            "eth_coin": {
                "id": eth_coin.id,
                "symbol": eth_coin.symbol,
                "alert_enabled": eth_coin.alert_enabled,
                "hidden": eth_coin.hidden,
                "initial_price": eth_coin.initial_price,
                "custom_upper_type": eth_coin.custom_upper_type,
                "custom_upper_val": eth_coin.custom_upper_val,
                "custom_upper_pct": eth_coin.custom_upper_pct,
                "custom_lower_type": eth_coin.custom_lower_type,
                "custom_lower_val": eth_coin.custom_lower_val,
                "custom_lower_pct": eth_coin.custom_lower_pct
            },
            "current_price": current_price,
            "thresholds": thresholds,
            "alert_states": alert_states,
            "price_crossed_up": current_price >= thresholds.get('up_threshold', 0) if 'up_threshold' in thresholds else False,
            "price_crossed_down": current_price <= thresholds.get('down_threshold', 999999) if 'down_threshold' in thresholds else False
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/alert-status", methods=["GET"])
@login_required
def api_alert_status():
    """Get alert system status and verify scoped logic is active"""
    try:
        # Get current alert state for user's coins
        status = {
            "alert_check_interval": ALERT_CHECK_INTERVAL,
            "portfolio_coins": [],
            "watchlist_coins": [],
            "alert_state_sample": {}
        }
        
        # Portfolio coins status
        coins = Coin.query.filter_by(user_id=current_user.id, alert_enabled=True, hidden=False).all()
        for coin in coins[:5]:  # Limit to first 5 for status
            symbol = (coin.symbol or '').upper()
            price = fetch_binance_price(symbol)
            
            down_threshold = None
            up_threshold = None
            if coin.custom_lower_type == "%" and coin.custom_lower_pct is not None:
                down_threshold = round(coin.initial_price * (1 - float(coin.custom_lower_pct) / 100), 6) if coin.initial_price else None
            elif coin.custom_lower_type == "#" and coin.custom_lower_val is not None:
                down_threshold = round(float(coin.custom_lower_val), 6)
                
            if coin.custom_upper_type == "%" and coin.custom_upper_pct is not None:
                up_threshold = round(coin.initial_price * (1 + float(coin.custom_upper_pct) / 100), 6) if coin.initial_price else None
            elif coin.custom_upper_type == "#" and coin.custom_upper_val is not None:
                up_threshold = round(float(coin.custom_upper_val), 6)
            
            coin_status = {
                "symbol": symbol,
                "price": price,
                "down_threshold": down_threshold,
                "up_threshold": up_threshold,
                "scoped_states": {}
            }
            
            # Check scoped alert states
            if down_threshold is not None:
                down_state = get_last_alert_state(current_user.id, symbol, "down", source="portfolio", threshold=down_threshold)
                coin_status["scoped_states"]["down"] = down_state
            if up_threshold is not None:
                up_state = get_last_alert_state(current_user.id, symbol, "up", source="portfolio", threshold=up_threshold)
                coin_status["scoped_states"]["up"] = up_state
                
            status["portfolio_coins"].append(coin_status)
        
        # Watchlist coins status
        wl_coins = WatchlistCoin.query.filter_by(user_id=current_user.id, alert_enabled=True, hidden=False).all()
        for coin in wl_coins[:5]:  # Limit to first 5
            symbol = (coin.symbol or '').upper()
            price = fetch_binance_price(symbol)
            
            coin_status = {
                "symbol": symbol,
                "price": price,
                "down_alert": coin.down_alert,
                "up_alert": coin.up_alert,
                "scoped_states": {}
            }
            
            if coin.down_alert is not None:
                down_state = get_last_alert_state(current_user.id, symbol, "down", source="watchlist", threshold=round(float(coin.down_alert), 6))
                coin_status["scoped_states"]["down"] = down_state
            if coin.up_alert is not None:
                up_state = get_last_alert_state(current_user.id, symbol, "up", source="watchlist", threshold=round(float(coin.up_alert), 6))
                coin_status["scoped_states"]["up"] = up_state
                
            status["watchlist_coins"].append(coin_status)
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"api_alert_status error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/auto-alert")
@login_required
def api_auto_alert():
    coin_id = request.args.get("id")
    symbol = request.args.get("symbol")
    alert_type = request.args.get("type")
    try:
        now = datetime.utcnow()
        cache_key = None
        initial_price = None

        # Portfolio coin
        if coin_id:
            coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
            if not coin:
                logger.error(f"[auto-alert] Coin not found for id={coin_id}")
                return jsonify({"value": 10.0})
            symbol = coin.symbol
            initial_price = coin.initial_price
            cache_key = (symbol, alert_type)
        elif symbol:
            cache_key = (symbol.upper(), alert_type)
            wl = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol.upper()).first()
            if wl:
                initial_price = None  # Use first price from get_last_7d_prices

        # Check cache
        cached = AUTO_ALERT_CACHE.get(cache_key)
        if cached and (datetime.utcnow() - cached['updated']) < timedelta(hours=2):
            logger.error(f"[auto-alert] Returning cached value for {cache_key}: {cached['value']}")
            return jsonify({"value": cached['value']})

        # Calculate and cache
        value = calculate_auto_alert(symbol, alert_type, initial_price)
        logger.error(f"[auto-alert] Calculated value for {symbol} {alert_type}: {value} (initial_price={initial_price})")
        AUTO_ALERT_CACHE[cache_key] = {'value': value, 'updated': now}
        return jsonify({"value": value})
    except Exception as e:
        logger.error(f"auto-alert error: {str(e)}")
        return jsonify({"value": 10.0})

# ====== Watchlist API =========
@app.route("/api/watchlist")
@login_required
def api_watchlist():
    wl = WatchlistCoin.query.filter_by(user_id=current_user.id, hidden=False).all()
    
    # Use stored current prices for instant response
    watchlist_data = []
    for w in wl:
        current_price = w.current_price or 0.0
        
        watchlist_data.append({
            "symbol": w.symbol,
            "alert_enabled": w.alert_enabled,
            "down_val": w.down_alert,
            "up_val": w.up_alert,
            "note": w.note,
            "favorite": w.favorite,
            "hidden": w.hidden,
            "action": "Watch",  # Simplified to avoid database locks
            "current_price": current_price,
            "sentiment": w.sentiment or "Watch",
            "volatility_pct": w.volatility_pct
        })
    
    return jsonify(watchlist_data)

@app.route("/api/watchlist-live")
@login_required
def api_watchlist_live():
    """Live watchlist data for background refresh"""
    wl = WatchlistCoin.query.filter_by(user_id=current_user.id, hidden=False).all()
    
    # Fetch current prices for all watchlist items
    watchlist_data = []
    for w in wl:
        try:
            # Try to get current price from Binance
            current_price = fetch_binance_price(w.symbol)
            # Save to database for next load
            w.current_price = current_price
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to fetch price for {w.symbol}: {e}")
            current_price = w.current_price or 0.0
        
        watchlist_data.append({
            "symbol": w.symbol,
            "alert_enabled": w.alert_enabled,
            "down_val": w.down_alert,
            "up_val": w.up_alert,
            "note": w.note,
            "favorite": w.favorite,
            "hidden": w.hidden,
            "action": "Watch",  # Simplified to avoid database locks
            "current_price": current_price,
            "sentiment": w.sentiment or "Watch",
            "volatility_pct": w.volatility_pct
        })
    
    return jsonify(watchlist_data)

@app.route("/api/watchlist/add", methods=["POST"])
@login_required
def api_watchlist_add():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    if not symbol:
        return jsonify({"success": False, "error": "Missing symbol"}), 400
    exists = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if exists:
        return jsonify({"success": True})
    wl = WatchlistCoin(symbol=symbol, user_id=current_user.id)
    db.session.add(wl)
    db.session.commit()
    # Trigger backfill for this symbol in a background thread
    threading.Thread(target=backfill_7d_prices, args=([symbol],), daemon=True).start()
    return jsonify({"success": True})

@app.route("/api/watchlist/remove", methods=["POST"])
@login_required
def api_watchlist_remove():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    wl = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if wl:
        db.session.delete(wl)
        db.session.commit()
    return jsonify({"success": True})

@app.route("/api/hidden-coins")
@login_required
def api_hidden_coins():
    try:
        try:
            update_all_coin_prices_from_binance(current_user.id)
            db.session.commit()  # Ensure all changes are saved
        except Exception as e:
            logger.error(f"Failed to update coin prices: {str(e)}")
            db.session.rollback()
        coins = Coin.query.filter_by(user_id=current_user.id, hidden=True).all()
        logger.debug(f"Hidden coins for user {current_user.id}: {[c.symbol for c in coins]}")
        result = [coin_to_dict(c) for c in coins]
        logger.debug(f"/api/hidden-coins result: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"/api/hidden-coins failed: {str(e)}", exc_info=True)
        # Always return a valid JSON list, never a 500
        return jsonify([])

# ==================== STAKING API ROUTES ====================

def binance_us_api_call(cred, endpoint, method='GET', params_dict=None, use_trading_keys=False):
    """Helper function to make signed Binance.US API calls.

    Forces IPv4 (AF_INET) to avoid Binance.US error -71012 'IPv6 not supported'.
    """
    import hashlib
    import hmac
    import time
    import socket
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.connection import allowed_gai_family
    from urllib.parse import urlencode

    if not cred:
        raise ValueError("Missing Binance credentials")

    api_key = getattr(cred, 'api_key', None)
    api_secret = getattr(cred, 'api_secret', None)

    # Note: use_trading_keys is deprecated as keys are now unified, but kept for signature compatibility
    if not api_key or not api_secret:
        raise ValueError("Binance API key/secret not configured")

    # ── Force IPv4 so Binance.US never receives an IPv6 connection ──────────
    class _IPv4Adapter(HTTPAdapter):
        """Requests transport adapter that resolves hostnames to IPv4 only."""
        def send(self, *args, **kwargs):
            _orig = allowed_gai_family
            import urllib3.util.connection as _conn
            _conn.allowed_gai_family = lambda: socket.AF_INET
            try:
                return super().send(*args, **kwargs)
            finally:
                _conn.allowed_gai_family = _orig

    session = requests.Session()
    session.mount("https://", _IPv4Adapter())
    # ────────────────────────────────────────────────────────────────────────

    timestamp = int(time.time() * 1000)

    # Build params
    if params_dict is None:
        params_dict = {}
    params_dict['timestamp'] = timestamp

    # Create signature
    query_string = urlencode(params_dict, doseq=True)
    signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    # Add signature to params
    full_url = f"https://api.binance.us{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}

    # Make request
    if method == 'GET':
        response = session.get(full_url, headers=headers, timeout=10)
    elif method == 'POST':
        response = session.post(full_url, headers=headers, timeout=10)
    else:
        raise ValueError(f"Unsupported method: {method}")

    return response


def calculate_staking_value_for_user(cred, user_id=None):
    """Return tuple (active_value_usd, pending_value_usd) for Binance.US staking balances."""
    active_value = 0.0
    pending_value = 0.0

    if not cred:
        return active_value, pending_value

    target_user_id = user_id or getattr(current_user, 'id', None)

    def _fallback_price(symbol, default=None):
        if target_user_id is None:
            return default
        try:
            from models import Coin as CoinModel
            coin_record = CoinModel.query.filter_by(user_id=target_user_id, symbol=symbol).first()
            if coin_record:
                candidate = coin_record.current or coin_record.avg_entry
                if candidate and candidate > 0:
                    return float(candidate)
        except Exception as fallback_err:
            logger.debug(f"Fallback price lookup failed for {symbol}: {fallback_err}")
        return default

    # Track which assets/symbols we found via API to avoid double counting
    found_symbols = set()

    active_api_ok = False
    try:
        balance_response = binance_us_api_call(
            cred,
            '/sapi/v1/staking/stakingBalance',
            method='GET',
            use_trading_keys=True
        )
        if balance_response.status_code == 200:
            active_api_ok = True
            balance_payload = balance_response.json()
            staking_items = balance_payload.get('data', [])
            for staked in staking_items:
                asset = str(staked.get('asset', '')).upper()
                # Binance Staking API uses 'stakingAmount', not 'amount'
                amount = _coerce_float(staked.get('stakingAmount'), 0.0)
                if amount == 0.0: # Fallback if stakingAmount is missing or zero
                    amount = _coerce_float(staked.get('amount'), 0.0)
                
                if not asset or amount <= 0:
                    continue
                
                found_symbols.add(asset)
                
                try:
                    price = fetch_binance_price(asset)
                except Exception as price_err:
                    logger.debug(f"Staking valuation price lookup failed for {asset}: {price_err}")
                    price = _fallback_price(asset)
                if not price:
                    continue
                active_value += amount * price
        else:
            logger.error(f"Staking balance valuation error: {balance_response.status_code} - {balance_response.text}")
    except Exception as staking_err:
        logger.error(f"Error calculating staking active value: {staking_err}", exc_info=True)

    pending_api_ok = False
    try:
        history_response = binance_us_api_call(
            cred,
            '/sapi/v1/staking/history',
            method='GET',
            params_dict={'limit': 200},
            use_trading_keys=True
        )
        if history_response.status_code == 200:
            pending_api_ok = True
            history_payload = history_response.json()
            if isinstance(history_payload, dict):
                history_entries = history_payload.get('data', [])
            else:
                history_entries = history_payload

            for entry in history_entries:
                status_raw = str(entry.get('status', '')).upper()
                if status_raw in {'SUCCESS', 'COMPLETED', 'FAILED', 'CANCELLED', 'CANCELED'}:
                    continue
                asset = str(entry.get('asset', '')).upper()
                amount = _coerce_float(entry.get('amount'), 0.0) or 0.0
                if not asset or amount <= 0:
                    continue
                try:
                    price = fetch_binance_price(asset)
                except Exception as price_err:
                    logger.debug(f"Pending staking valuation price lookup failed for {asset}: {price_err}")
                    price = _fallback_price(asset)
                if not price:
                    continue
                pending_value += amount * price
        else:
            logger.error(f"Staking history valuation error: {history_response.status_code} - {history_response.text}")
    except Exception as pending_err:
        logger.error(f"Error calculating pending staking value: {pending_err}", exc_info=True)

    # Merge local tables when Binance APIs omit data (or fail)
    if target_user_id is not None:
        try:
            from models import StakedCoin
            staked_records = StakedCoin.query.filter_by(user_id=target_user_id).all()
            for record in staked_records:
                asset = (record.symbol or '').upper()
                amount = float(record.amount or 0.0)
                status = (record.status or 'active').lower()
                
                # If we already found this asset in API, skip local active record
                if active_api_ok and status == 'active' and asset in found_symbols:
                    continue
                
                if not asset or amount <= 0:
                    continue
                
                price = None
                try:
                    price = fetch_binance_price(asset)
                except Exception as price_err:
                    logger.debug(f"Local staking fallback price lookup failed for {asset}: {price_err}")
                if not price:
                    price = _fallback_price(asset)
                if not price:
                    continue
                
                # Determine if we should add to active or pending
                # Inclusion of 'unstaking' in active_value ensures it shows in totals
                if status == 'unstaking':
                    active_value += amount * price
                else:
                    active_value += amount * price
                
        except Exception as local_err:
            logger.error(f"Local staking fallback lookup failed: {local_err}", exc_info=True)

    if pending_value <= 0.0 and target_user_id is not None and not pending_api_ok:
        try:
            fallback_pending = 0.0
            pending_orders = StakingOrder.query.filter_by(user_id=target_user_id, action='stake').all()
            for row in pending_orders:
                status_raw = str(row.status or '').upper()
                if status_raw in {'COMPLETED', 'SUCCESS', 'FAILED', 'CANCELLED', 'CANCELED', 'REJECTED'}:
                    continue
                asset = str(row.symbol or '').upper()
                amount = float(row.amount or 0.0)
                if not asset or amount <= 0:
                    continue
                usd_value = row.usd_value
                if usd_value is None or usd_value <= 0:
                    price = None
                    try:
                        price = fetch_binance_price(asset)
                    except Exception as price_err:
                        logger.debug(f"Pending staking fallback price lookup failed for {asset}: {price_err}")
                    if not price:
                        price = _fallback_price(asset)
                    if not price:
                        continue
                    usd_value = amount * price
                fallback_pending += float(usd_value)
            if fallback_pending > 0:
                pending_value = fallback_pending
        except Exception as local_pending_err:
            logger.error(f"Local pending staking fallback lookup failed: {local_pending_err}", exc_info=True)

    return active_value, pending_value


def build_staking_balance_view(cred, asset_param=None):
    """Consolidated staking balance data used by both balance and dashboard endpoints."""
    default_summary = {
        'activeCount': 0,
        'pendingCount': 0,
        'activeUsd': 0.0,
        'pendingUsd': 0.0,
        'totalUsd': 0.0,
        'avgApy': 0.0
    }
    default_result = {
        'balances': [],
        'activePositions': [],
        'pendingPositions': [],
        'pendingTransactions': [],
        'summary': default_summary,
        'totalStakedValue': 0.0
    }

    try:
        api_key = getattr(cred, 'api_key', None) or getattr(cred, 'trading_api_key', None)
        api_secret = getattr(cred, 'api_secret', None) or getattr(cred, 'trading_api_secret', None)
        if not api_key or not api_secret:
            logger.warning("Binance API credentials not configured")
            return default_result

        params = {}
        if asset_param:
            params['asset'] = asset_param
        
        from models import Coin as CoinModel
        user_id = getattr(current_user, 'id', None)

        def get_local_price(symbol, default=None):
            if not user_id:
                return default
            try:
                coin_record = CoinModel.query.filter_by(user_id=user_id, symbol=symbol).first()
                if coin_record:
                    candidate = coin_record.current or coin_record.avg_entry
                    if candidate and candidate > 0:
                        return float(candidate)
            except Exception as fallback_err:
                logger.debug(f"Fallback price lookup failed for {symbol}: {fallback_err}")
            return default
        
        # Fetch product metadata so we can override stale APR/APY coming from the balance endpoint.
        asset_metadata = {}
        asset_metadata_by_product = {}
        # Flag to track if the main balance API call succeeded
        active_api_ok = False
        
        try:
            balance_response = binance_us_api_call(
                cred,
                '/sapi/v1/staking/stakingBalance',
                method='GET',
                use_trading_keys=True
            )
            
            if balance_response.status_code == 200:
                balance_payload = balance_response.json()
                if isinstance(balance_payload, dict) and (balance_payload.get('success') is True or balance_payload.get('code') == '000000'):
                    staking_data = balance_payload.get('data', [])
                    active_api_ok = True
                elif isinstance(balance_payload, list):
                    staking_data = balance_payload
                    active_api_ok = True
                else:
                    logger.warning(f"Unexpected staking API payload: {str(balance_payload)[:200]}")
                    # The original code had a symbol/product_key assignment here that was out of context.
                    # Removing it to maintain syntactic correctness and logical flow.
                    # symbol = str(asset_info.get('stakingAsset') or asset_info.get('asset') or '').upper()
                    # product_key = str(asset_info.get('productId') or asset_info.get('product') or '') or None
                    # if symbol:
                    #     asset_metadata.setdefault(symbol, asset_info)
                    #     if product_key:
                    #         asset_metadata_by_product[f"{symbol}:{product_key}"] = asset_info
            else:
                logger.error(f"Binance staking balance API error: {balance_response.status_code} - {balance_response.text}")
                return default_result # Return early if the main balance API call fails
        except Exception as e:
            logger.error(f"Error fetching Binance staking balance: {e}", exc_info=True)
            return default_result # Return early on exception

        # The original code had an asset metadata fetch here.
        # This block is now moved to after the main balance fetch, or its logic needs to be re-evaluated.
        # For now, I'm assuming the user's intent was to replace the main balance fetch.
        # If the asset metadata fetch is still needed, it should be re-added separately.

        # Original asset metadata fetch (re-inserting it here as it's distinct from the balance call)
        try:
            asset_response = binance_us_api_call(
                cred,
                '/sapi/v1/staking/asset',
                method='GET',
                use_trading_keys=True
            )
            if asset_response.status_code == 200:
                asset_payload = asset_response.json()
                if isinstance(asset_payload, dict) and 'data' in asset_payload:
                    asset_iterable = asset_payload.get('data') or []
                else:
                    asset_iterable = asset_payload or []

                for asset_info in asset_iterable:
                    symbol = str(asset_info.get('stakingAsset') or asset_info.get('asset') or '').upper()
                    product_key = str(asset_info.get('productId') or asset_info.get('product') or '') or None
                    if symbol:
                        asset_metadata.setdefault(symbol, asset_info)
                        if product_key:
                            asset_metadata_by_product[f"{symbol}:{product_key}"] = asset_info
            else:
                logger.warning(
                    "Binance staking asset metadata request failed (%s): %s",
                    asset_response.status_code,
                    asset_response.text,
                )
        except Exception as meta_err:
            logger.error(f"Failed to fetch staking asset metadata: {meta_err}", exc_info=True)

        def get_asset_metadata(symbol: str, product_id=None):
            normalized = (symbol or '').upper()
            if not normalized:
                return None
            if product_id:
                prod_key = f"{normalized}:{product_id}"
                if prod_key in asset_metadata_by_product:
                    logger.debug(f"Using cached staking metadata for {normalized} product {product_id}")
                    return asset_metadata_by_product[prod_key]
            if normalized in asset_metadata:
                logger.debug(f"Using cached staking metadata for {normalized}")
                return asset_metadata[normalized]
            try:
                params = {'stakingAsset': normalized}
                if product_id:
                    params['productId'] = product_id
                logger.debug(f"Fetching staking asset metadata for {normalized} with params {params}")
                detail_resp = binance_us_api_call(
                    cred,
                    '/sapi/v1/staking/asset',
                    method='GET',
                    params_dict=params,
                    use_trading_keys=True,
                )
                if detail_resp.status_code == 200:
                    detail_payload = detail_resp.json()
                    if isinstance(detail_payload, list):
                        asset_entries = detail_payload
                    elif isinstance(detail_payload, dict):
                        asset_entries = detail_payload.get('data') or []
                    else:
                        asset_entries = []
                    selected_entry = None
                    for entry in asset_entries:
                        entry_symbol = str(entry.get('stakingAsset') or entry.get('asset') or '').upper()
                        entry_product = entry.get('productId') or entry.get('product')
                        if entry_symbol:
                            asset_metadata.setdefault(entry_symbol, entry)
                            if entry_product:
                                asset_metadata_by_product[f"{entry_symbol}:{entry_product}"] = entry
                        if product_id and entry_product and str(entry_product) == str(product_id):
                            selected_entry = entry
                    if selected_entry:
                        logger.debug(f"Fetched product-specific metadata for {normalized} product {product_id}: {selected_entry}")
                        return selected_entry
                    if asset_entries:
                        logger.debug(f"Fetched metadata for {normalized}: {asset_entries[0]}")
                        return asset_entries[0]
                else:
                    logger.debug(
                        "Binance staking asset detail lookup failed for %s (%s): %s",
                        normalized,
                        detail_resp.status_code,
                        detail_resp.text,
                    )
            except Exception as detail_err:
                logger.debug(f"Failed to fetch staking metadata for {normalized}: {detail_err}")
            return asset_metadata.get(normalized)

        response = binance_us_api_call(
            cred,
            '/sapi/v1/staking/stakingBalance',
            method='GET',
            params_dict=params,
            use_trading_keys=True
        )

        if response.status_code != 200:
            logger.error(f"Binance staking balance API error: {response.status_code} - {response.text}")
            return default_result

        result = response.json()
        staking_data = result.get('data', [])

        # Pending transactions (history)
        pending_transactions = []
        try:
            history_response = binance_us_api_call(
                cred,
                '/sapi/v1/staking/history',
                method='GET',
                params_dict={'limit': 200},
                use_trading_keys=True
            )
            if history_response.status_code == 200:
                history_data = history_response.json()
                if isinstance(history_data, dict):
                    history_data = history_data.get('data', [])

                for txn in history_data:
                    status_raw = str(txn.get('status', '')).upper()
                    txn_type_raw = str(txn.get('type', '')).lower()
                    txn_type = 'stake' if 'stake' in txn_type_raw else 'unstake' if 'unstake' in txn_type_raw else txn_type_raw

                    if status_raw and status_raw not in {'SUCCESS', 'COMPLETED', 'FAILED', 'CANCELLED', 'CANCELED'}:
                        # Skip unstake transactions - they are shown in Active list via unstakeInProgress
                        if txn_type == 'unstake':
                            continue
                        
                        asset = str(txn.get('asset', '')).upper()
                        
                        # Skip if this asset is already in the staking balance API response
                        # This prevents duplicates when the same position appears in both balance and history
                        if asset in found_symbols:
                            continue
                        
                        amount = _coerce_float(txn.get('amount'), 0.0) or 0.0

                        price = None
                        current_value = 0.0
                        if asset:
                            try:
                                price = fetch_binance_price(asset)
                                current_value = amount * price
                            except Exception as price_err:
                                logger.debug(f"Price lookup failed for {asset} (history pending): {price_err}")
                                price = get_local_price(asset)
                                if price:
                                    current_value = amount * price

                        pending_transactions.append({
                            'tranId': txn.get('tranId'),
                            'asset': asset,
                            'type': txn_type,
                            'amount': amount,
                            'status': status_raw,
                            'initiatedTime': txn.get('initiatedTime'),
                            'currentPrice': price,
                            'currentValue': round(current_value, 2) if current_value else 0.0,
                            'source': 'history'
                        })
        except Exception as hist_err:
            logger.error(f"Failed to fetch staking history for pending transactions: {hist_err}", exc_info=True)

        # Local database lookups
        try:
            from models import StakedCoin
            staked_coin_records = StakedCoin.query.filter_by(user_id=current_user.id).all()
        except Exception as db_err:
            logger.error(f"Failed to load local StakedCoin records: {db_err}")
            staked_coin_records = []

        db_lookup = {}
        for record in staked_coin_records:
            key = record.symbol.upper()
            db_lookup.setdefault(key, []).append(record)

        active_like_statuses = {
            'STAKED',
            'ACTIVE',
            'HOLDING',
            'SUCCESS',
            'RUNNING',
            'EARNING',
            'LOCKED',
            'HOLDING',
            'SUCCESS',
            'RUNNING',
            'EARNING',
            'LOCKED',
            'COMPLETED',
            # User request: These should appear in Active list
            'UNSTAKING',
            'REDEEMING',
            'UNBONDING',
        }
        pending_like_statuses = {
            'PROTOCOL_BONDING',
            'BONDING',
            'PENDING',
            'PROCESSING',
            'WAITING',
            'WAIT',
            'QUEUED',
            'PENDING_SUBSCRIPTION',
            'PENDING_PURCHASE',
            'PENDING_REDEMPTION'
        }
        failure_statuses = {'FAILED', 'CANCELLED', 'CANCELED'}
        pending_keywords = ('PEND', 'QUEUE', 'BOND', 'PROCESS', 'WAIT')

        def classify_status(raw_status: str, pending_balance_value=None) -> str:
            status_upper = (raw_status or '').strip().upper()
            if status_upper in active_like_statuses:
                return 'active'
            if status_upper in pending_like_statuses or status_upper in failure_statuses:
                return 'pending'
            if status_upper:
                for keyword in pending_keywords:
                    if keyword in status_upper:
                        return 'pending'
                # Unknown but present status defaults to active to match Binance dashboard behavior
                return 'active'
            # Binance occasionally omits status entirely; fall back to pending flag if provided.
            if pending_balance_value and pending_balance_value > 0:
                return 'pending'
            return 'active'

        def display_status(raw_status: str, fallback: str = 'Pending') -> str:
            status_upper = (raw_status or '').strip().upper()
            if not status_upper:
                return fallback
            mapping = {
                'STAKED': 'Staked',
                'ACTIVE': 'Active',
                'HOLDING': 'Active',
                'SUCCESS': 'Active',
                'RUNNING': 'Active',
                'EARNING': 'Active',
                'LOCKED': 'Locked',
                'UNSTAKING': 'Unstaking',
                'REDEEMING': 'Unstaking',
                'UNBONDING': 'Unbonding',
                'PROCESSING': 'Processing',
                'PENDING': 'Pending',
                'PENDING_SUBSCRIPTION': 'Pending Subscription',
                'PENDING_PURCHASE': 'Pending Purchase',
                'PENDING_REDEMPTION': 'Pending Redemption',
                'PROTOCOL_BONDING': 'Protocol Bonding',
                'BONDING': 'Bonding',
                'WAITING': 'Pending',
                'WAIT': 'Pending',
                'QUEUED': 'Queued',
                'FAILED': 'Failed',
                'CANCELLED': 'Cancelled',
                'CANCELED': 'Cancelled',
                'COMPLETED': 'Completed'
            }
            return mapping.get(status_upper, status_upper.title())

        positions = []
        active_positions = []
        pending_positions = []
        active_usd = 0.0
        pending_usd = 0.0
        total_usd = 0.0
        total_apy = 0.0
        found_symbols = set()
        assets_with_unstake_in_progress = set()  # Track assets being unstaked

        for staked in staking_data:
            asset = str(staked.get('asset', '')).upper()
            if asset:
                 found_symbols.add(asset)

            # Binance Staking API uses 'stakingAmount', not 'amount'
            staking_amount = _coerce_float(staked.get('stakingAmount'), 0.0)
            if staking_amount == 0.0: # Fallback if stakingAmount is missing or zero
                staking_amount = _coerce_float(staked.get('amount'), 0.0)

            pending_balance = None
            for key in ('pendingBalance', 'pendingAmount', 'pending'):
                if key in staked and staked.get(key) is not None:
                    pending_balance = _coerce_float(staked.get(key), None)
                    if pending_balance:
                        break
            
            # Check for unstakeInProgress field - this is the key indicator from Binance
            unstake_in_progress = _coerce_float(staked.get('unstakeInProgress'), 0.0)
            
            status_raw = staked.get('status') or ''
            
            # Force status to 'unstaking' if unstakeInProgress > 0
            if unstake_in_progress > 0:
                status_category = 'active'  # Goes in Active list
                status_raw = 'UNSTAKING'     # But labeled as Unstaking
                assets_with_unstake_in_progress.add(asset)  # Track for pending_balance check
            else:
                status_category = classify_status(status_raw, pending_balance)

            current_price = None
            current_value = 0.0
            if asset:
                try:
                    current_price = fetch_binance_price(asset)
                    current_value = staking_amount * current_price
                except Exception as price_err:
                    logger.debug(f"Price lookup failed for {asset} (balance): {price_err}")
                    current_price = get_local_price(asset)
                    if current_price:
                        current_value = staking_amount * current_price

            apr_value = _coerce_float(staked.get('apr'), 0.0) or 0.0
            apy_value = _coerce_float(staked.get('apy'), 0.0) or 0.0

            product_hint = staked.get('productId') or staked.get('positionId')
            metadata = get_asset_metadata(asset, product_hint)
            if not metadata:
                logger.warning(
                    "Missing Binance staking metadata for asset %s product_hint=%s raw_keys=%s",
                    asset,
                    product_hint,
                    {k: staked.get(k) for k in ('asset', 'productId', 'positionId', 'apy', 'apr', 'status')},
                )
            if metadata:
                meta_apr = _coerce_float(metadata.get('apr'), None)
                meta_apy = _coerce_float(metadata.get('apy'), None)
                if meta_apr is not None:
                    apr_value = meta_apr
                if meta_apr and meta_apr > 0 and (meta_apy is None or meta_apy <= 0 or meta_apr > meta_apy):
                    apy_value = meta_apr
                    logger.debug(
                        "Binance metadata APY fallback: using APR %.4f for %s (product_hint=%s, raw_apy=%s)",
                        meta_apr,
                        asset,
                        product_hint,
                        meta_apy,
                    )
                elif meta_apy is not None and meta_apy > 0:
                    apy_value = meta_apy
                else:
                    logger.warning(
                        "Binance metadata missing APY for asset %s (product_hint=%s): %s",
                        asset,
                        product_hint,
                        metadata,
                    )
                logger.debug(
                    "Applied Binance staking metadata for %s product_hint=%s → apr=%s apy=%s (raw=%s)",
                    asset,
                    product_hint,
                    apr_value,
                    apy_value,
                    metadata,
                )

            position = {
                'asset': asset,
                'amount': staking_amount,
                'currentValue': round(current_value, 2) if current_value else 0.0,
                'currentPrice': current_price,
                'rewardAsset': staked.get('rewardAsset', asset),
                'apr': apr_value,
                'apy': apy_value,
                'autoRestake': staked.get('autoRestake', False),
                'positionId': staked.get('positionId') or staked.get('productId'),
                'productId': staked.get('productId'),
                'id': staked.get('positionId') or staked.get('productId'),
                'statusRaw': status_raw,
                'statusCategory': status_category,
                'status': status_category,
                'statusLabel': display_status(status_raw, 'Active' if status_category == 'active' else 'Pending'),
                'valueCurrency': 'USD',
                'binanceData': staked
            }

            symbol_key = asset
            if symbol_key in db_lookup:
                records = db_lookup[symbol_key]
                # Try to match by amount with tolerance
                best_match_idx = -1
                min_diff = float('inf')
                for i, rec in enumerate(records):
                    diff = abs(rec.amount - staking_amount)
                    if diff < min_diff:
                        min_diff = diff
                        best_match_idx = i
                
                # Tolerance: 10% or 0.01 absolute
                if best_match_idx != -1 and (min_diff < (staking_amount * 0.1) or min_diff < 0.01):
                    record = records.pop(best_match_idx)
                    if not records:
                        del db_lookup[symbol_key]
                    
                    position['localStakedCoinId'] = record.id
                    position['localUnstakeAvailableAt'] = record.unstake_available_at.isoformat() if record.unstake_available_at else None
                    position['localStatus'] = record.status
                    position['id'] = record.id

            positions.append(position)

            total_usd += current_value
            if status_category == 'active':
                active_positions.append(position)
                active_usd += current_value
                total_apy += apy_value
            else:
                pending_positions.append(position)
                pending_usd += current_value

        # Add remaining local records that weren't in API response
        for symbol_key, records in db_lookup.items():
            for record in records:
                # If API worked, trust it for active positions of this symbol
                # BUG FIX: Only skip if this symbol was specifically found in the API response.
                # If API worked but this symbol is missing, it might be in redemption/omitted.
                status = (record.status or 'active').lower()
                asset = record.symbol.upper()
                if active_api_ok and status == 'active' and asset in found_symbols:
                    logger.debug(f"Skipping stale local active record for {record.symbol} as API response contains it")
                    continue
                
                asset = record.symbol.upper()
                amount = record.amount
                
                current_price = None
                current_value = 0.0
                try:
                    current_price = fetch_binance_price(asset)
                    current_value = amount * current_price
                except Exception:
                    current_price = get_local_price(asset)
                    if current_price:
                        current_value = amount * current_price
                
                local_position = {
                    'asset': asset,
                    'stakingAmount': amount,
                    'currentValue': round(current_value, 2) if current_value else 0.0,
                    'currentPrice': current_price,
                    'rewardAsset': record.reward_asset or asset,
                    'apr': record.apr,
                    'apy': record.apy,
                    'autoRestake': record.auto_restake,
                    'positionId': f"local_{record.id}",
                    'id': record.id,
                    'statusRaw': record.status.upper() if record.status else 'ACTIVE',
                    'statusCategory': 'active', # Keep in active category as requested for UI grouping
                    'status': record.status if record.status else 'active',
                    'statusLabel': display_status(record.status or 'ACTIVE', 'Active'),
                    'valueCurrency': 'USD',
                    'binanceData': {},
                    'localStakedCoinId': record.id,
                    'source': 'local_db'
                }
                
                positions.append(local_position)
                active_positions.append(local_position)
                active_usd += current_value
                total_usd += current_value
                if record.apy:
                    total_apy += record.apy

            if pending_balance and pending_balance > 0 and asset not in assets_with_unstake_in_progress:
                pending_price = current_price
                pending_value = 0.0
                if pending_price:
                    pending_value = pending_balance * pending_price
                else:
                    try:
                        pending_price = fetch_binance_price(asset)
                        pending_value = pending_balance * pending_price
                    except Exception as price_err:
                        logger.debug(f"Price lookup failed for pending balance {asset}: {price_err}")
                        pending_price = get_local_price(asset)
                        if pending_price:
                            pending_value = pending_balance * pending_price

                pending_entry = {
                    'asset': asset,
                    'stakingAmount': pending_balance,
                    'currentValue': round(pending_value, 2) if pending_value else 0.0,
                    'currentPrice': pending_price,
                    'statusRaw': 'PENDING_BALANCE',
                    'statusCategory': 'pending',
                    'status': 'pending',
                    'statusLabel': 'Pending',
                    'valueCurrency': 'USD',
                    'detail': 'Pending balance reported by Binance.US'
                }

                pending_positions.append(pending_entry)
                pending_usd += pending_value
                total_usd += pending_value

        combined_pending = {}
        for pos in pending_positions:
            key = f"balance:{pos.get('positionId') or pos.get('asset')}:{pos.get('statusRaw')}"
            combined_pending[key] = pos

        for txn in pending_transactions:
            key = f"history:{txn.get('tranId') or txn.get('asset')}:{txn.get('type')}:{txn.get('status')}"
            if key not in combined_pending:
                combined_pending[key] = {
                    'asset': txn.get('asset'),
                    'stakingAmount': txn.get('amount'),
                    'currentValue': txn.get('currentValue'),
                    'currentPrice': txn.get('currentPrice'),
                    'statusRaw': txn.get('status'),
                    'statusCategory': 'pending',
                    'status': 'pending',
                    'statusLabel': display_status(txn.get('status'), 'Pending'),
                    'type': txn.get('type'),
                    'initiatedTime': txn.get('initiatedTime'),
                    'source': txn.get('source'),
                    'tranId': txn.get('tranId')
                }
                pending_usd += txn.get('currentValue') or 0.0
                total_usd += txn.get('currentValue') or 0.0

        active_count = len(active_positions)
        avg_apy = 0.0
        if active_count > 0:
            avg_apy = total_apy / active_count

        summary = {
            'activeCount': active_count,
            'pendingCount': len(combined_pending),
            'activeUsd': round(active_usd, 2),
            'pendingUsd': round(pending_usd, 2),
            'totalUsd': round(total_usd, 2),
            'avgApy': round(avg_apy * 100, 2)
        }

        logger.info(f"Staking balance summary for user {getattr(current_user, 'id', 'n/a')}: {summary}")
        return {
            'balances': positions,
            'activePositions': active_positions,
            'pendingPositions': list(combined_pending.values()),
            'pendingTransactions': pending_transactions,
            'summary': summary,
            'totalStakedValue': summary['totalUsd']
        }

    except Exception as e:
        logger.error(f"Error building staking balance view: {e}", exc_info=True)
        return default_result


def binance_has_staking_permission(cred):
    """Best-effort check to see if the key can access staking endpoints."""
    try:
        # Probe the staking listing endpoint - Binance.US returns 403/401 when the
        # key lacks Earn/Staking access, otherwise it responds with 200 + JSON.
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        if response.status_code == 200:
            return True

        # Interpret common “permission denied” signals; allow other statuses to fall through.
        try:
            payload = response.json()
            message = str(payload.get('msg') or payload)
        except ValueError:
            message = response.text

        lower_msg = (message or '').lower()
        if response.status_code in (401, 403) or 'permission' in lower_msg or 'not authorized' in lower_msg:
            return False

        logger.warning(
            "Binance staking permission probe returned unexpected status %s: %s",
            response.status_code,
            message,
        )
        return None
    except Exception as exc:
        logger.error(f"Failed to inspect Binance staking permissions: {exc}", exc_info=True)
        return None

@app.route("/api/staking/assets", methods=["GET"])
@login_required
def api_staking_assets():
    """Get available staking assets with details from Binance.US API
    Doc: GET /sapi/v1/staking/asset"""
    try:
        cred = get_user_credentials(current_user.username)
        
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured for staking")
            return jsonify([])
        
        # Call Binance.US staking asset information endpoint
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        
        if response.status_code == 200:
            staking_assets = response.json()
            logger.info(f"Retrieved {len(staking_assets)} staking assets from Binance.US")
            return jsonify(staking_assets)
        else:
            logger.error(f"Binance.US staking API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Critical error in api_staking_assets: {e}", exc_info=True)
        return jsonify([])

@app.route("/api/staking/stakeable-coins", methods=["GET"])
@login_required
def api_stakeable_coins():
    """Get list of stakeable coin symbols from Binance.US API
    Doc: GET /sapi/v1/staking/asset (extract stakingAsset symbols)"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify([])
        
        # Call Binance.US staking asset information endpoint
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        
        if response.status_code == 200:
            staking_assets = response.json()
            # Extract just the stakingAsset symbols
            stakeable_coins = [asset.get('stakingAsset') for asset in staking_assets if asset.get('stakingAsset')]
            logger.info(f"Retrieved {len(stakeable_coins)} stakeable coins from Binance.US API")
            return jsonify(stakeable_coins)
        else:
            logger.error(f"Binance.US staking API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error in api_stakeable_coins: {e}")
        return jsonify([])

@app.route("/api/staking/stake", methods=["POST"])
@login_required
def api_stake_asset():
    """Stake an asset using Binance.US API
    Doc: POST /sapi/v1/staking/stake
    Params: stakingAsset, amount, autoRestake (optional), twofa_token (optional)"""
    try:
        from models import StakedCoin
        data = request.get_json()
        
        staking_asset = data.get('stakingAsset', '').upper()
        amount = float(data.get('amount', 0))
        auto_restake = data.get('autoRestake', True)
        twofa_token = data.get('twofa_token')
        
        if not staking_asset or amount <= 0:
            return jsonify({"error": "Invalid staking asset or amount"}), 400
        
        # Check if 2FA is required
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_enabled:
            if not twofa_token:
                return jsonify({"error": "2FA verification required", "requires_2fa": True}), 403
            
            # Verify 2FA token from session
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data:
                return jsonify({"error": "Invalid or expired 2FA token"}), 403
            
            # Check if token is still valid (2 minutes)
            from datetime import datetime
            token_timestamp = token_data.get('timestamp', 0)
            if datetime.utcnow().timestamp() - token_timestamp > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({"error": "2FA token expired. Please verify again."}), 403
            
            # Verify user ID matches
            if token_data.get('user_id') != current_user.id:
                return jsonify({"error": "Invalid 2FA token"}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get user credentials
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        permission_check = binance_has_staking_permission(cred)
        if permission_check is False:
            return jsonify({
                "error": "Your Binance trading API key does not have Earn/Staking permissions enabled.",
                "action": "Update the API key on Binance.US to allow Earn/Staking or create a new key with that permission."
            }), 403
        
        # Find the coin in portfolio
        coin = Coin.query.filter_by(user_id=current_user.id, symbol=staking_asset).first()
        if not coin:
            return jsonify({"error": f"{staking_asset} not found in portfolio"}), 404
        
        if coin.amount < amount:
            return jsonify({"error": f"Insufficient balance. Available: {coin.amount} {staking_asset}"}), 400
        
        # Call Binance.US staking API
        # POST /sapi/v1/staking/stake
        params = {
            'stakingAsset': staking_asset,
            'amount': str(amount),
            'autoRestake': str(auto_restake).lower()
        }
        
        try:
            logger.info(f"Calling Binance staking API for {current_user.username}: {params}")
            response = binance_us_api_call(cred, '/sapi/v1/staking/stake', method='POST', params_dict=params, use_trading_keys=True)
            
            if response.status_code == 200:
                result = response.json()
                
                # Deduct from coins table
                coin.amount -= amount
                
                # Get staking asset info for APR/APY
                asset_response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', params_dict={'stakingAsset': staking_asset}, use_trading_keys=True)
                product_info = {}
                if asset_response.status_code == 200:
                    assets = asset_response.json()
                    if isinstance(assets, list) and len(assets) > 0:
                        product_info = assets[0]
                
                # Add to staked_coins table
                staked_coin = StakedCoin(
                    user_id=current_user.id,
                    symbol=staking_asset,
                    amount=amount,
                    stake_transaction_id=result.get('data', {}).get('purchaseRecordId', ''),
                    apr=float(product_info.get('apr', 0)),
                    apy=float(product_info.get('apy', 0)),
                    reward_asset=product_info.get('rewardAsset', staking_asset),
                    unstaking_period_hours=int(product_info.get('unstakingPeriod', 168)),
                    auto_restake=auto_restake,
                    status='active'
                )
                
                db.session.add(staked_coin)
                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)

                # Record staking transaction in exchange_logs (staking_orders)
                try:
                    engine_logs = db.engine
                    metadata = {
                        'purchaseRecordId': result.get('data', {}).get('purchaseRecordId', ''),
                        'raw_response': result
                    }
                    usd_value = None
                    try:
                        price = fetch_binance_price(staking_asset)
                        usd_value = float(price) * float(amount) if price else None
                    except Exception:
                        usd_value = None

                    from trading_models import StakingOrder
                    
                    # Record staking transaction using ORM
                    new_staking_order = StakingOrder(
                        user_id=current_user.id,
                        symbol=staking_asset,
                        action='stake',
                        amount=float(amount),
                        status='completed',
                        transaction_id=result.get('data', {}).get('purchaseRecordId', ''),
                        auto_restake=auto_restake,
                        apr=float(product_info.get('apr', 0)),
                        apy=float(product_info.get('apy', 0)),
                        reward_asset=product_info.get('rewardAsset', staking_asset),
                        usd_value=usd_value,
                        extra_metadata=json.dumps(metadata)
                    )
                    
                    db.session.add(new_staking_order)
                    db.session.commit()
                except Exception as log_err:
                    logger.error(f"Failed to insert staking_orders record: {log_err}", exc_info=True)
                
                logger.info(f"Successfully staked {amount} {staking_asset} for user {current_user.username}")
                return jsonify({
                    "success": True,
                    "message": f"Successfully staked {amount} {staking_asset}",
                    "purchaseRecordId": result.get('data', {}).get('purchaseRecordId', '')
                })
            elif response.status_code == 401:
                logger.error(f"Binance staking API authorization error: {response.text}")
                return jsonify({
                    "error": "Binance rejected the staking request due to missing permissions.",
                    "details": "Enable Earn/Staking on the trading API key in Binance.US and try again.",
                    "requires_staking_permission": True
                }), 403
            else:
                logger.error(f"Binance staking API error: {response.status_code} - {response.text}")
                return jsonify({"error": f"Staking failed: {response.text}"}), response.status_code
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Binance staking API error: {e}", exc_info=True)
            return jsonify({"error": f"Staking failed: {str(e)}"}), 500
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_stake_asset: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/staking/unstake", methods=["POST"])
@login_required
def api_unstake_asset():
    """Unstake an asset using Binance.US API
    Doc: POST /sapi/v1/staking/unstake
    Params: stakedCoinId, amount, twofa_token (optional)"""
    try:
        from models import StakedCoin
        data = request.get_json()
        
        staked_coin_id = data.get('stakedCoinId')
        amount = float(data.get('amount', 0))
        twofa_token = data.get('twofa_token')
        
        if not staked_coin_id or amount <= 0:
            return jsonify({"error": "Invalid staked coin ID or amount"}), 400

        # Check if 2FA is required
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_enabled:
            if not twofa_token:
                return jsonify({"error": "2FA verification required", "requires_2fa": True}), 403
            
            # Verify 2FA token from session
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data:
                return jsonify({"error": "Invalid or expired 2FA token"}), 403
            
            # Check if token is still valid (2 minutes)
            from datetime import datetime
            token_timestamp = token_data.get('timestamp', 0)
            if datetime.utcnow().timestamp() - token_timestamp > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({"error": "2FA token expired. Please verify again."}), 403
            
            # Verify user ID matches
            if token_data.get('user_id') != current_user.id:
                return jsonify({"error": "Invalid 2FA token"}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get user credentials
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400
        
        # Find the staked coin
        staked_coin = StakedCoin.query.filter_by(id=staked_coin_id, user_id=current_user.id).first()
        if not staked_coin:
            return jsonify({"error": "Staked position not found"}), 404
        
        if staked_coin.amount < amount:
            return jsonify({"error": f"Insufficient staked balance. Available: {staked_coin.amount}"}), 400
        
        # Call Binance.US unstake API
        # POST /sapi/v1/staking/unstake
        params = {
            'stakingAsset': staked_coin.symbol,
            'amount': str(amount)
        }
        
        try:
            response = binance_us_api_call(cred, '/sapi/v1/staking/unstake', method='POST', params_dict=params, use_trading_keys=True)
            
            if response.status_code == 200:
                result = response.json()
                
                # Calculate when unstaking completes
                unstaking_hours = staked_coin.unstaking_period_hours or 168
                available_at = datetime.utcnow() + timedelta(hours=unstaking_hours)

                if abs(staked_coin.amount - amount) < 1e-10:
                    # Full unstake - update existing record
                    staked_coin.status = 'unstaking'
                    staked_coin.unstake_requested_at = datetime.utcnow()
                    staked_coin.unstake_available_at = available_at
                else:
                    # Partial unstake - keep existing record active but reduced
                    # Create a NEW record for the unstaking part
                    staked_coin.amount -= amount
                    
                    new_unstaking_record = StakedCoin(
                        user_id=staked_coin.user_id,
                        symbol=staked_coin.symbol,
                        amount=amount,
                        staked_at=staked_coin.staked_at,
                        stake_transaction_id=staked_coin.stake_transaction_id,
                        apr=staked_coin.apr,
                        apy=staked_coin.apy,
                        reward_asset=staked_coin.reward_asset,
                        unstaking_period_hours=staked_coin.unstaking_period_hours,
                        auto_restake=staked_coin.auto_restake,
                        status='unstaking',
                        unstake_requested_at=datetime.utcnow(),
                        unstake_available_at=available_at
                    )
                    db.session.add(new_unstaking_record)

                # Log a local StakingOrder for immediate history feedback
                try:
                    from trading_models import StakingOrder
                    new_order = StakingOrder(
                        user_id=current_user.id,
                        symbol=staked_coin.symbol,
                        amount=amount,
                        action='unstake',
                        status='PROCESSING',
                        timestamp=datetime.utcnow(),
                        usd_value=0.0 # Will be updated by sync
                    )
                    db.session.add(new_order)
                except Exception as order_err:
                    logger.warning(f"Failed to log local unstake order: {order_err}")
                
                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)
                
                logger.info(f"Successfully initiated unstake of {amount} {staked_coin.symbol} for user {current_user.username}")
                return jsonify({
                    "success": True,
                    "message": f"Unstaking {amount} {staked_coin.symbol}. Available in {unstaking_hours} hours",
                    "unstakeAvailableAt": available_at.isoformat()
                })
            else:
                logger.error(f"Binance unstaking API error: {response.status_code} - {response.text}")
                return jsonify({"error": f"Unstaking failed: {response.text}"}), response.status_code
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Binance unstaking API error: {e}", exc_info=True)
            return jsonify({"error": f"Unstaking failed: {str(e)}"}), 500
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_unstake_asset: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# Dust / Small Balance Conversion Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/dust/assets", methods=["GET"])
@login_required
def api_dust_assets():
    """GET /sapi/v1/asset/query/dust-assets — list convertible dust balances.
    Query param: toAsset (BNB|BTC|ETH|USDT, default BNB)
    """
    try:
        to_asset = request.args.get("toAsset", "BNB").upper()
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        response = binance_us_api_call(
            cred,
            "/sapi/v1/asset/query/dust-assets",
            method="GET",
            params_dict={"toAsset": to_asset},
            use_trading_keys=False,
        )

        if response.status_code == 200:
            data = response.json()
            return jsonify({"success": True, "data": data})
        else:
            logger.error(f"Binance dust-assets error: {response.status_code} {response.text}")
            return jsonify({"success": False, "error": response.text}), response.status_code

    except Exception as exc:
        logger.error(f"Error in api_dust_assets: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/dust/convert", methods=["POST"])
@login_required
def api_dust_convert():
    """POST /sapi/v1/asset/dust — convert selected dust assets.
    Body JSON: { fromAssets: ["LTC","XRP",...], toAsset: "BNB", twofa_token: "<token>" }
    """
    try:
        data = request.get_json() or {}
        from_assets = data.get("fromAssets", [])
        to_asset = (data.get("toAsset") or "BNB").upper()
        twofa_token = data.get("twofa_token")

        if not from_assets:
            return jsonify({"error": "No assets selected for conversion"}), 400
        if to_asset not in ("BNB", "BTC", "ETH", "USDT"):
            return jsonify({"error": f"Invalid toAsset: {to_asset}"}), 400

        # 2FA check
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_secret:
            if not twofa_token:
                return jsonify({"error": "2FA verification required", "requires_2fa": True}), 403
            token_data = session.get(f"2fa_verified_{twofa_token}")
            if not token_data or token_data.get("user_id") != current_user.id:
                return jsonify({"error": "Invalid or expired 2FA token", "requires_2fa": True}), 403
            if datetime.utcnow().timestamp() - token_data.get("timestamp", 0) > 120:
                session.pop(f"2fa_verified_{twofa_token}", None)
                return jsonify({"error": "2FA token expired. Please verify again.", "requires_2fa": True}), 403
            session.pop(f"2fa_verified_{twofa_token}", None)

        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        # Build params — Binance expects fromAsset repeated for each coin
        params = {"toAsset": to_asset}
        for asset in from_assets:
            params.setdefault("fromAsset", [])
            if isinstance(params["fromAsset"], list):
                params["fromAsset"].append(asset)
            else:
                params["fromAsset"] = [params["fromAsset"], asset]

        # binance_us_api_call flattens lists automatically via requests
        response = binance_us_api_call(
            cred,
            "/sapi/v1/asset/dust",
            method="POST",
            params_dict=params,
            use_trading_keys=False,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(
                f"Dust conversion success for user {current_user.id}: "
                f"{from_assets} -> {to_asset}"
            )
            # Trigger immediate portfolio snapshot so chart updates without waiting 5 min
            trigger_portfolio_snapshot(current_user.id, current_user.username)
            return jsonify({"success": True, "data": result})
        else:
            logger.error(f"Binance dust convert error: {response.status_code} {response.text}")
            return jsonify({"success": False, "error": response.text}), response.status_code

    except Exception as exc:
        logger.error(f"Error in api_dust_convert: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/dust/history", methods=["GET"])
@login_required
def api_dust_history():
    """GET /sapi/v1/asset/query/dust-logs — dust conversion history."""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        params = {}
        if request.args.get("startTime"):
            params["startTime"] = request.args.get("startTime")
        if request.args.get("endTime"):
            params["endTime"] = request.args.get("endTime")

        response = binance_us_api_call(
            cred,
            "/sapi/v1/asset/query/dust-logs",
            method="GET",
            params_dict=params,
            use_trading_keys=False,
        )

        if response.status_code == 200:
            return jsonify({"success": True, "data": response.json()})
        else:
            return jsonify({"success": False, "error": response.text}), response.status_code

    except Exception as exc:
        logger.error(f"Error in api_dust_history: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500

# ---------------------------------------------------------------------------

@app.route("/api/staking/balance", methods=["GET"])
@login_required
def api_staking_balance():
    """Get user's staking balances from Binance.US API
    Doc: GET /sapi/v1/staking/stakingBalance
    Optional param: asset"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify({'balances': [], 'totalStakedValue': 0})
        
        # Call Binance.US staking balance endpoint
        asset_param = request.args.get('asset')
        overview = build_staking_balance_view(cred, asset_param)
        logger.info(f"/api/staking/balance response summary: {overview.get('summary')}")
        return jsonify(overview)
    
    except Exception as e:
        logger.error(f"Error in api_staking_balance: {e}", exc_info=True)
        return jsonify({
            'balances': [],
            'activePositions': [],
            'pendingPositions': [],
            'pendingTransactions': [],
            'summary': {
                'activeCount': 0,
                'pendingCount': 0,
                'activeUsd': 0.0,
                'pendingUsd': 0.0,
                'totalUsd': 0.0
            },
            'totalStakedValue': 0.0
        })

@app.route("/api/staking/history", methods=["GET"])
@login_required
def api_staking_history():
    """Get staking transaction history from Binance.US API
    Doc: GET /sapi/v1/staking/history
    Optional params: asset, startTime, endTime, page, limit"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify([])
        
        # Call Binance.US staking history endpoint
        # GET /sapi/v1/staking/history
        params = {}
        if request.args.get('asset'):
            params['asset'] = request.args.get('asset')
        if request.args.get('startTime'):
            params['startTime'] = request.args.get('startTime')
        if request.args.get('endTime'):
            params['endTime'] = request.args.get('endTime')
        if request.args.get('page'):
            params['page'] = request.args.get('page')
        if request.args.get('limit'):
            params['limit'] = request.args.get('limit')
        
        response = binance_us_api_call(cred, '/sapi/v1/staking/history', method='GET', params_dict=params, use_trading_keys=True)
        
        if response.status_code == 200:
            history_data = response.json()
            if isinstance(history_data, dict):
                history_entries = history_data.get('data', [])
            else:
                history_entries = history_data

            normalized = []
            for entry in history_entries:
                status_raw = str(entry.get('status', '')).upper()
                entry_type_raw = str(entry.get('type', '')).lower()
                
                # Check for unstake/redeem FIRST to avoid mislabeling as stake
                if 'unstake' in entry_type_raw or 'redeem' in entry_type_raw:
                    entry_type = 'unstake'
                elif 'stake' in entry_type_raw:
                    entry_type = 'stake'
                else:
                    entry_type = entry_type_raw or 'unknown'

                normalized.append({
                    'asset': str(entry.get('asset', '')).upper(),
                    'amount': _coerce_float(entry.get('amount'), entry.get('amount')) or 0.0,
                    'type': entry_type,
                    'initiatedTime': entry.get('initiatedTime'),
                    'status': status_raw if status_raw else 'UNKNOWN',
                    'tranId': entry.get('tranId'),
                    'raw': entry
                })

            logger.info(f"Retrieved {len(normalized)} staking history records from Binance.US")
            return jsonify(normalized)
        else:
            logger.error(f"Binance staking history API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error in api_staking_history: {e}", exc_info=True)
        return jsonify([])

@app.route("/api/staking/rewards", methods=["GET"])
@login_required
def api_staking_rewards():
    """Get staking rewards history from Binance.US API
    Doc: GET /sapi/v1/staking/stakingRewardsHistory
    Optional params: asset, startTime, endTime, page, limit"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify([])
        
        # Call Binance.US staking rewards history endpoint
        # GET /sapi/v1/staking/stakingRewardsHistory
        params = {}
        if request.args.get('asset'):
            params['asset'] = request.args.get('asset')
        if request.args.get('startTime'):
            params['startTime'] = request.args.get('startTime')
        if request.args.get('endTime'):
            params['endTime'] = request.args.get('endTime')
        if request.args.get('page'):
            params['page'] = request.args.get('page')
        if request.args.get('limit'):
            params['limit'] = request.args.get('limit')
        
        response = binance_us_api_call(cred, '/sapi/v1/staking/stakingRewardsHistory', method='GET', params_dict=params, use_trading_keys=True)
        
        if response.status_code == 200:
            result = response.json()
            # Response format: {"code":"000000","message":"success","data":[{...}],"total":1,"success":true}
            rewards_data = result.get('data', [])
            
            # Convert string values to floats for frontend compatibility
            for r in rewards_data:
                if 'usdValue' in r:
                    try:
                        r['usdValue'] = float(r['usdValue'])
                    except (ValueError, TypeError):
                        r['usdValue'] = 0.0
                if 'amount' in r:
                    try:
                        r['amount'] = float(r['amount'])
                    except (ValueError, TypeError):
                        r['amount'] = 0.0
                        
            logger.info(f"Retrieved {len(rewards_data)} staking reward records from Binance.US")
            return jsonify(rewards_data)
        else:
            logger.error(f"Binance staking rewards API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error in api_staking_rewards: {e}", exc_info=True)
        return jsonify([])

def _build_staking_dashboard_payload(cred):
    overview = build_staking_balance_view(cred)
    summary = overview.get('summary', {}) or {}
    logger.info(
        "Staking dashboard summary raw overview for %s: %s",
        getattr(current_user, 'username', 'unknown'),
        summary
    )

    total_combined_value = summary.get('totalUsd', 0.0)
    active_value = summary.get('activeUsd', 0.0)
    pending_value = summary.get('pendingUsd', 0.0)
    active_positions = summary.get('activeCount', 0)
    pending_positions = summary.get('pendingCount', 0)
    avg_apy_percent = summary.get('avgApy', 0.0)

    today_rewards_usd = 0.0
    total_rewards_usd = 0.0
    
    # Calculate all-time rewards from DB
    try:
        from models import StakingReward
        rewards = StakingReward.query.filter_by(user_id=current_user.id).all()
        for r in rewards:
            if r.usd_value:
                total_rewards_usd += r.usd_value
    except Exception as db_reward_err:
        logger.error(f"Failed to calculate total staking rewards from DB: {db_reward_err}")

    try:
        today_start_ms = int(datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        rewards_params = {'startTime': today_start_ms}
        # Note: binance_us_api_call uses unified api_key now, use_trading_keys arg is ignored but kept for compatibility
        rewards_response = binance_us_api_call(
            cred,
            '/sapi/v1/staking/stakingRewardsHistory',
            method='GET',
            params_dict=rewards_params,
            use_trading_keys=True
        )

        if rewards_response.status_code == 200:
            rewards_result = rewards_response.json()
            rewards_data = rewards_result.get('data', [])
            for reward in rewards_data:
                usd_value = float(reward.get('usdValue', 0))
                today_rewards_usd += usd_value
    except Exception as reward_err:
        logger.error(f"Failed to get today's staking rewards: {reward_err}")

    payload = {
        'totalStakedValue': round(total_combined_value, 2),
        'activePositions': active_positions,
        'pendingPositions': pending_positions,
        'todayRewards': round(today_rewards_usd, 2),
        'totalRewards': round(total_rewards_usd, 2),
        'avgApy': round(avg_apy_percent, 2),
        'activeValue': round(active_value, 2),
        'pendingValue': round(pending_value, 2),
        'totalValue': round(total_combined_value, 2)
    }
    logger.info(f"Staking dashboard summary response: {payload}")
    return payload


def _respond_with_staking_dashboard_payload(cred):
    payload = _build_staking_dashboard_payload(cred)
    response = make_response(jsonify(payload))
    cache_header = 'no-store, no-cache, must-revalidate, max-age=0, private'
    response.headers['Cache-Control'] = cache_header
    response.headers['CDN-Cache-Control'] = 'no-store'
    response.headers['Surrogate-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/api/staking/dashboard-summary", methods=["GET"])
@login_required
def api_staking_dashboard_summary():
    """Legacy staking summary endpoint (kept for compatibility)."""
    try:
        cred = get_user_credentials(current_user.username)
        portfolio_key = getattr(cred, 'api_key', None)
        portfolio_secret = getattr(cred, 'api_secret', None)
        trading_key = getattr(cred, 'trading_api_key', None)
        trading_secret = getattr(cred, 'trading_api_secret', None)

        if not cred or not ((portfolio_key and portfolio_secret) or (trading_key and trading_secret)):
            logger.warning(
                "Staking dashboard summary: missing Binance credentials "
                "(portfolio_key=%s, trading_key=%s)",
                bool(portfolio_key and portfolio_secret),
                bool(trading_key and trading_secret)
            )
            return jsonify({
                'totalStakedValue': 0,
                'activePositions': 0,
                'pendingPositions': 0,
                'todayRewards': 0,
                'avgApy': 0,
                'activeValue': 0,
                'pendingValue': 0,
                'totalValue': 0
            })
        
        return _respond_with_staking_dashboard_payload(cred)
    
    except Exception as e:
        logger.error(f"Error in api_staking_dashboard_summary: {e}", exc_info=True)
        return jsonify({
            'totalStakedValue': 0,
            'activePositions': 0,
            'pendingPositions': 0,
            'todayRewards': 0,
            'avgApy': 0,
            'activeValue': 0,
            'pendingValue': 0,
            'totalValue': 0
        })


@app.route("/api/staking/dashboard-summary-live", methods=["GET"])
@login_required
def api_staking_dashboard_summary_live():
    """Cache-busting variant used by the dashboard widget."""
    try:
        cred = get_user_credentials(current_user.username)
        return _respond_with_staking_dashboard_payload(cred)
    except Exception as exc:
        logger.error(f"Error in api_staking_dashboard_summary_live: {exc}", exc_info=True)
        fallback = {
            'totalStakedValue': 0,
            'activePositions': 0,
            'pendingPositions': 0,
            'todayRewards': 0,
            'avgApy': 0,
            'activeValue': 0,
            'pendingValue': 0,
            'totalValue': 0
        }
        response = make_response(jsonify(fallback))
        response.headers['Cache-Control'] = 'no-store'
        return response


def _dashboard_staking_response(cred):
    if not cred:
        response = make_response(jsonify({
            'totalStakedValue': 0,
            'activePositions': 0,
            'pendingPositions': 0,
            'todayRewards': 0,
            'avgApy': 0,
            'activeValue': 0,
            'pendingValue': 0,
            'totalValue': 0
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
    return _respond_with_staking_dashboard_payload(cred)


@app.route("/api/staking/dashboard-summary-dashboard", methods=["GET"])
@app.route("/api/staking/dashboard-summary-dashboard/<path:cache_buster>", methods=["GET"])
@login_required
def api_staking_dashboard_summary_dashboard(cache_buster=None):
    """Dedicated endpoint for the dashboard widget to avoid CDN cache collisions."""
    try:
        cred = get_user_credentials(current_user.username)
        portfolio_key = getattr(cred, 'api_key', None)
        portfolio_secret = getattr(cred, 'api_secret', None)
        trading_key = getattr(cred, 'trading_api_key', None)
        trading_secret = getattr(cred, 'trading_api_secret', None)

        if not cred or not ((portfolio_key and portfolio_secret) or (trading_key and trading_secret)):
            logger.warning(
                "Dashboard staking summary: missing Binance credentials "
                "(portfolio_key=%s, trading_key=%s)",
                bool(portfolio_key and portfolio_secret),
                bool(trading_key and trading_secret)
            )
            return _dashboard_staking_response(None)

        return _dashboard_staking_response(cred)
    except Exception as exc:
        logger.error(f"Error in api_staking_dashboard_summary_dashboard: {exc}", exc_info=True)
        fallback = {
            'totalStakedValue': 0,
            'activePositions': 0,
            'pendingPositions': 0,
            'todayRewards': 0,
            'avgApy': 0,
            'activeValue': 0,
            'pendingValue': 0,
            'totalValue': 0
        }
        response = make_response(jsonify(fallback))
        response.headers['Cache-Control'] = 'no-store'
        return response


@app.route("/api/staking/dashboard-view", methods=["POST"])
@login_required
def api_staking_dashboard_view():
    """POST variant to bypass intermediary caches for the dashboard widget."""
    try:
        cred = get_user_credentials(current_user.username)
        return _dashboard_staking_response(cred)
    except Exception as exc:
        logger.error(f"Error in api_staking_dashboard_view: {exc}", exc_info=True)
        fallback = {
            'totalStakedValue': 0,
            'activePositions': 0,
            'pendingPositions': 0,
            'todayRewards': 0,
            'avgApy': 0,
            'activeValue': 0,
            'pendingValue': 0,
            'totalValue': 0
        }
        response = make_response(jsonify(fallback))
        response.headers['Cache-Control'] = 'no-store'
        return response

# ==================== END STAKING API ROUTES ====================

def compute_portfolio_total_value(user_id, username=None, cred=None, include_staking=True):
    """Return the portfolio total exactly as displayed in the dashboard widget."""
    total_value = 0.0
    regular_total = 0.0
    staking_total = 0.0

    logger.error(f"[VALUE_DEBUG] Starting calculation for user {user_id}")
    logger.error(f"[VALUE_DEBUG] Creds present: {bool(cred)}")
    try:
        portfolio = get_portfolio_data_for_user(user_id)
        for coin in portfolio:
            val = coin.get("current_value") or 0.0
            regular_total += val
            logger.error(f"[VALUE_DEBUG] Asset {coin['symbol']}: {val}")
        total_value = regular_total
        logger.error(f"[VALUE_DEBUG] Total regular value: {regular_total}")
    except Exception as portfolio_err:
        logger.error(f"Portfolio aggregation error for user {user_id}: {portfolio_err}", exc_info=True)
        return 0.0

    if not include_staking:
        return total_value

    try:
        if cred is None:
            resolved_username = username
            if not resolved_username:
                try:
                    user_obj = User.query.filter_by(id=user_id).first()
                    if user_obj:
                        resolved_username = user_obj.username
                except Exception as lookup_err:
                    logger.debug(f"Username lookup failed for user {user_id}: {lookup_err}")
            if resolved_username:
                cred = get_user_credentials(resolved_username)
        if cred:
            staking_active, staking_pending = calculate_staking_value_for_user(cred, user_id)
            staking_total = staking_active + staking_pending
            total_value += staking_total
            logger.error(f"[VALUE_DEBUG] Total staking value: {staking_total}")
    except Exception as staking_err:
        logger.error(f"Staking aggregation error for user {user_id}: {staking_err}", exc_info=True)

    logger.error(f"[VALUE_DEBUG] Final combined value for user {user_id}: {total_value}")
    return total_value


@app.route("/api/true-portfolio-value")
@login_required
def api_true_portfolio_value():
    """Database-only portfolio value for instant loading"""
    logger.error(f"=== API_TRUE_PORTFOLIO_VALUE CALLED for user {current_user.id} (path: {request.full_path}) ===")
    logger.error(f"[DEBUG_PV] Headers: {dict(request.headers)}")
    try:
        total_value = compute_portfolio_total_value(
            current_user.id,
            username=getattr(current_user, "username", None)
        )
        result = {"total_value": round(total_value, 2)}
        logger.error(f"[JSON_DEBUG] Response for user {current_user.id}: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Database portfolio value error: {str(e)}")
        return jsonify({"total_value": 0.0})

@app.route("/api/true-portfolio-value-live")
@login_required
def api_true_portfolio_value_live():
    """Live portfolio value for background refresh using Binance data"""
    logger.error(f"=== API_TRUE_PORTFOLIO_VALUE_LIVE CALLED for user {current_user.id} ===")
    try:
        total_value = compute_portfolio_total_value(
            current_user.id,
            username=getattr(current_user, "username", None)
        )
        result = {"total_value": total_value}
        logger.error(f"[JSON_DEBUG] Live Response for user {current_user.id}: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting live portfolio value: {e}")
        # Fallback to stored data
        coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).all()
        total_value = sum((coin.amount or 0) * (coin.current or 0) for coin in coins)
        try:
            cred = get_user_credentials(current_user.username)
            staking_active, staking_pending = calculate_staking_value_for_user(cred, current_user.id)
            total_value += staking_active + staking_pending
        except Exception:
            pass
        return jsonify({"total_value": total_value})

def _coerce_float(value, default=None):
    """Safely convert user-provided values to float, returning default on failure."""
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def send_telegram_message(username, message, admin_notify=True):
    """
    Send a plain text Telegram message using stored user credentials.
    Returns True if the message was sent successfully.
    """
    try:
        cred = get_user_credentials(username)
        if not cred or not cred.telegram_token or not cred.telegram_chat_id:
            logger.error(f"[TELEGRAM] Missing Telegram credentials for user: {username}")
            if admin_notify:
                logger.error(f"[ADMIN] Telegram alert failed for user {username}: missing credentials.")
            return False

        url = f"https://api.telegram.org/bot{cred.telegram_token}/sendMessage"
        payload = {'chat_id': cred.telegram_chat_id, 'text': message}

        try:
            response = requests.post(url, data=payload, timeout=10)
            logger.info(f"[TELEGRAM] Sent? {response.status_code} response: {response.text}")
            if response.status_code != 200:
                logger.error(f"[TELEGRAM] ERROR: {response.status_code} - {response.text}")
                if admin_notify:
                    logger.error(f"[ADMIN] Telegram alert failed for user {username}: {response.text}")
                return False
            return True
        except Exception as exc:
            logger.error(f"[TELEGRAM] Exception: {exc}", exc_info=True)
            if admin_notify:
                logger.error(f"[ADMIN] Telegram alert exception for user {username}: {exc}")
            return False
    except Exception as e:
        logger.error(f"[TELEGRAM] Unexpected error while sending generic message: {e}", exc_info=True)
        if admin_notify:
            logger.error(f"[ADMIN] Telegram alert unexpected error for user {username}: {e}")
        return False


def send_telegram_alert(username, symbol, price, alert_type, threshold, admin_notify=True):
    """
    Unified Telegram alert sender. Logs all failures and can notify admin on failure.
    Returns True if sent, False otherwise.
    """
    try:
        import pytz
        symbol = str(symbol).upper()
        price = round(float(price), 6)
        threshold = round(float(threshold), 6)
        alert_type_str = "fell below" if alert_type == "down" else "rose above"
        eastern = pytz.timezone("US/Eastern")
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_eastern = now_utc.astimezone(eastern)
        time_str = now_eastern.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        msg = (
            f"⚠️ {symbol} alert: Price {alert_type_str} {threshold:.6f} USDT. "
            f"Current price: {price:.6f}\n"
            f"{time_str}"
        )
        return send_telegram_message(username, msg, admin_notify=admin_notify)
    except Exception as e:
        logger.error(f"[TELEGRAM] Unexpected error: {e}", exc_info=True)
        if admin_notify:
            logger.error(f"[ADMIN] Telegram alert unexpected error for user {username}: {e}")
        return False


def _split_symbol_pair(symbol):
    """Return base and quote assets inferred from a trading symbol."""
    if not symbol:
        return '', 'USDT'
    symbol = str(symbol).upper()
    for quote in ('USDT', 'USD'):
        if symbol.endswith(quote):
            return symbol[:-len(quote)], quote
    return symbol, 'USDT'


def _format_asset_amount(amount):
    """Format asset quantities with sensible precision."""
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    if abs(value) >= 1:
        formatted = f"{value:.4f}".rstrip('0').rstrip('.')
    else:
        formatted = f"{value:.8f}".rstrip('0').rstrip('.')
    return formatted or "0"


def _format_quote_amount(amount):
    """Format quote asset (USDT) values with currency-like precision."""
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    abs_value = abs(value)
    if abs_value >= 1000:
        formatted = f"{value:,.2f}"
    elif abs_value >= 1:
        formatted = f"{value:.2f}"
    else:
        formatted = f"{value:.4f}".rstrip('0').rstrip('.')
    return formatted or "0"


def notify_order_fill(order, username, executed_qty, quote_qty, fill_price=None):
    """Send Telegram and desktop notifications for a filled order."""
    try:
        executed_value = float(executed_qty or 0.0)
        quote_value = float(quote_qty or 0.0)
        base_asset, quote_asset = _split_symbol_pair(order.symbol)
        quote_asset_label = quote_asset or 'USDT'

        quantity_str = _format_asset_amount(executed_value)
        quote_str = _format_quote_amount(quote_value)

        side_text = (order.side or 'BUY').lower()
        readable_side = 'buy' if side_text == 'buy' else 'sell'

        plain_message = f"Your {readable_side} order in the amount of {quantity_str} {base_asset} worth {quote_str} {quote_asset_label} was filled."

        # Send Telegram message (log failures so the desktop app can still surface the alert)
        telegram_sent = send_telegram_message(username, plain_message)
        if not telegram_sent:
            logger.warning(f"[ORDER-FILL] Telegram delivery failed for user {username}")

        # Determine coin reference for desktop notification
        coin = Coin.query.filter_by(user_id=order.user_id, symbol=base_asset).first()
        coin_id = coin.id if coin else 0

        # Fallback price calculation
        effective_price = fill_price
        if effective_price is None:
            if executed_value > 0 and quote_value > 0:
                effective_price = quote_value / executed_value
            else:
                effective_price = order.avg_fill_price or order.price or 0.0

        notification_id = save_notification_record(
            user_id=order.user_id,
            coin_id=coin_id,
            table_type='portfolio',
            symbol=base_asset,
            direction='filled',
            threshold_type='order_fill',
            percent_value=effective_price,
            crossing_price=executed_value,
            current_price=quote_value,
            category='order_fill',
            message=plain_message
        )

        logger.info(
            f"[ORDER-FILL] Notification recorded for order {order.binance_order_id} "
            f"(user {order.user_id}) with ID {notification_id}"
        )
        return notification_id
    except Exception as exc:
        logger.error(
            f"Failed to dispatch order fill notification for user {getattr(order, 'user_id', 'unknown')}: {exc}",
            exc_info=True
        )
        return None

@app.route("/api/set-watch-alert", methods=["POST"])
@login_required
def set_watch_alert():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    direction = data.get("direction")
    value = data.get("value", None)
    alert_enabled = data.get("alert_enabled", None)
    
    logger.info(f"set_watch_alert called: symbol={symbol}, direction={direction}, value={value}, alert_enabled={alert_enabled}")
    
    w = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if not w:
        logger.error(f"Watchlist coin not found: {symbol}")
        return jsonify({"success": False, "error": "Watchlist coin not found"})
    
    logger.info(f"Found watchlist coin: {w.symbol}, current down_alert={w.down_alert}, up_alert={w.up_alert}")
    
    if direction == "down":
        w.down_alert = round(float(value), 2) if value not in ("", None) else None
        logger.info(f"Updated down_alert to: {w.down_alert}")
    elif direction == "up":
        w.up_alert = round(float(value), 2) if value not in ("", None) else None
        logger.info(f"Updated up_alert to: {w.up_alert}")
    
    if alert_enabled is not None:
        w.alert_enabled = bool(alert_enabled)
        logger.info(f"Updated alert_enabled to: {w.alert_enabled}")
    
    db.session.commit()
    logger.info("Database committed successfully")
    return jsonify({"success": True})   



@app.route("/api/set-watch-alert-type", methods=["POST"])
@login_required
def set_watch_alert_type():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    _ = data.get("direction")
    _ = data.get("type")
    
    w = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if not w:
        return jsonify({"success": False, "error": "Watchlist coin not found"})
    
    # For watchlist, we don't need to store alert types since we're using direct values
    # This endpoint is just for compatibility with the frontend
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/set-volatility-pct', methods=['POST'])
@login_required
def set_volatility_pct():
    data = request.get_json()
    table_type = data.get('table_type')
    volatility_pct = data.get('volatility_pct')

    if table_type == 'portfolio':
        coin_id = data.get('id')
        coin = Coin.query.filter_by(user_id=current_user.id, id=coin_id).first()
    elif table_type == 'watchlist':
        symbol = data.get('symbol')
        coin = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    else:
        return jsonify({"success": False, "error": "Invalid table type"})

    if coin:
        coin.volatility_pct = volatility_pct
        db.session.commit()
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Coin not found"})

@app.route("/api/set-watchlist-favorite", methods=["POST"])
@login_required
def set_watchlist_favorite():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    favorite = data.get("favorite", False)
    w = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if w:
        w.favorite = favorite
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Watchlist coin not found"}), 404

@app.route("/settings")
@login_required
def settings_page():
    """Serve the settings page"""
    return serve_react_app()

@app.route("/dashboard")
@login_required
def dashboard_page():
    """Serve the dashboard page"""
    return serve_react_app()

@app.route("/trading")
@login_required
def trading_page():
    """Serve the trading page"""
    return serve_react_app()

@app.route("/logs")
@login_required
def logs_page():
    """Serve the logs page"""
    return serve_react_app()

@app.route("/portfolio")
@login_required
def portfolio_page():
    """Serve the portfolio page"""
    return serve_react_app()

@app.route("/watchlist")
@login_required
def watchlist_page():
    """Serve the watchlist page"""
    return serve_react_app()

@app.route("/ai-dashboard")
@login_required
def ai_dashboard_page():
    """Serve the AI dashboard page (legacy route)"""
    return serve_react_app()

@app.route("/ai-analysis")
@login_required
def ai_analysis_page():
    """Serve the AI Analysis page (new route)"""
    return serve_react_app()

@app.route("/staking")
@login_required
def staking_page():
    """Serve the staking page"""
    return serve_react_app()

@app.route("/tax-report")
@login_required
def tax_report_page():
    """Serve the tax report page"""
    return serve_react_app()

@app.route("/help")
@login_required
def help_page():
    """Serve the help page"""
    return serve_react_app()

@app.route("/api/ai/settings", methods=["GET", "POST"])
@login_required
def api_ai_settings():
    """Handle AI settings GET and POST requests"""
    try:
        # Get the current user
        username = current_user.username
        if not username:
            return jsonify({"error": "User not authenticated"}), 401
        
        if request.method == "GET":
            # Return AI settings
            logger.error(f"=== DEBUG: api_ai_settings GET called for user: {username} ===")
            ai_settings = get_user_ai_settings(username)
            logger.error(f"=== DEBUG: Base AI settings loaded ===")
            
            # Get user object to get user_id for AI prompts
            logger.error(f"=== DEBUG: Querying User with username: {username} ===")
            user_obj = User.query.filter_by(username=username).first()
            logger.error(f"=== DEBUG: User query result: {user_obj is not None} ===")
            logger.error(f"=== DEBUG: User object found: {user_obj is not None} ===")
            if user_obj:
                logger.error(f"=== DEBUG: User ID: {user_obj.id} ===")
                # Get AI prompts from database
                ai_prompts = get_user_ai_prompts(user_obj.id)
                logger.error(f"=== DEBUG: AI prompts found: {ai_prompts is not None} ===")
                if ai_prompts:
                    # Convert AI prompts to the format expected by frontend
                    ai_settings['ai_prompts'] = {
                        'market_analysis_pre': ai_prompts.market_analysis_pre or '',
                        'market_analysis_post': ai_prompts.market_analysis_post or '',
                        'risk_assessment_pre': ai_prompts.risk_assessment_pre or '',
                        'risk_assessment_post': ai_prompts.risk_assessment_post or '',
                        'portfolio_review_pre': ai_prompts.portfolio_review_pre or '',
                        'portfolio_review_post': ai_prompts.portfolio_review_post or '',
                        'coin_analysis_pre': ai_prompts.coin_analysis_pre or '',
                        'coin_analysis_post': ai_prompts.coin_analysis_post or '',
                        'sentiment_prompt_pre': ai_prompts.sentiment_prompt_pre or '',
                        'sentiment_prompt_post': ai_prompts.sentiment_prompt_post or ''
                    }
                    logger.error("=== DEBUG: AI prompts added to settings ===")
                else:
                    logger.error("=== DEBUG: No AI prompts found, using defaults ===")
            else:
                logger.error("=== DEBUG: User not found in database! ===")
            
            # Remove the old ai_custom_prompts if it exists
            if 'ai_custom_prompts' in ai_settings:
                del ai_settings['ai_custom_prompts']
                
            logger.error("=== DEBUG: Final AI settings response generated ===")
            return jsonify(ai_settings)
        
        elif request.method == "POST":
            # Save AI settings
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400
            
            # Update AI settings in database
            user_obj = User.query.filter_by(username=username).first()
            if not user_obj:
                return jsonify({"error": "User not found"}), 404

            cred = Credential.query.filter_by(user_id=user_obj.id).first()
            if not cred:
                cred = Credential(user_id=user_obj.id, username=username)
                db.session.add(cred)
            
            # Handle API keys separately
            if 'openai_key' in data:
                cred.openai_key = data.pop('openai_key')
            if 'zai_key' in data:
                cred.zai_key = data.pop('zai_key')
            if 'perplexity_key' in data:
                cred.perplexity_key = data.pop('perplexity_key')
            if 'gemini_key' in data:
                cred.gemini_key = data.pop('gemini_key')

            # Update each setting
            # Update UserSetting columns
            user_setting = UserSetting.query.filter_by(user_id=user_obj.id).first()
            if not user_setting:
                user_setting = UserSetting(user_id=user_obj.id)
                db.session.add(user_setting)
            
            # Map of allowed fields to update
            allowed_fields = [
                'ai_enabled', 'ai_provider', 'ai_model', 'ai_risk_tolerance',
                'ai_confidence_threshold', 'ai_notifications_enabled', 'ai_analysis_frequency',
                'ai_cache_duration_hours', 'ai_analysis_window_start', 'ai_analysis_window_end',
                'ai_max_tokens', 'ai_web_search_enabled', 'tax_manual_invested_updated', 
                'tax_cost_basis_method'
            ]

            for key, value in data.items():
                logger.error(f"=== DEBUG LOOP: checking key '{key}' against allowed list. In list? {key in allowed_fields} ===")
                if key == "ai_prompts" and isinstance(value, dict):
                    # Update AIPrompt fields for this user
                    ai_prompts = AIPrompt.query.filter_by(user_id=user_obj.id).first()
                    if not ai_prompts:
                        ai_prompts = AIPrompt(user_id=user_obj.id)
                        db.session.add(ai_prompts)
                    # Update all known prompt fields if present in payload
                    prompt_fields = [
                        'market_analysis_pre', 'market_analysis_post',
                        'risk_assessment_pre', 'risk_assessment_post',
                        'portfolio_review_pre', 'portfolio_review_post',
                        'coin_analysis_pre', 'coin_analysis_post',
                        'sentiment_prompt_pre', 'sentiment_prompt_post'
                    ]
                    for field in prompt_fields:
                        if field in value:
                            setattr(ai_prompts, field, value[field])
                    continue 

                # Explicit column updates
                if key in allowed_fields:
                    logger.error(f"=== DEBUG: Updating {key} to {value} ===")
                    # Handle type conversions if necessary (frontend sends JSON types, DB expects specific types)
                    # For boolean fields
                    if key in ['ai_enabled', 'ai_notifications_enabled', 'ai_web_search_enabled']:
                         setattr(user_setting, key, bool(value))
                    # For int fields
                    elif key in ['ai_cache_duration_hours', 'ai_max_tokens']:
                        try:
                            setattr(user_setting, key, int(value))
                        except:
                            pass
                    # For float fields
                    elif key in ['ai_confidence_threshold']:
                        try:
                            setattr(user_setting, key, float(value))
                        except:
                            pass
                    # For string fields
                    else:
                        setattr(user_setting, key, str(value))
            db.session.commit()
            return jsonify({"success": True, "message": "AI settings updated"})
            
    except Exception as e:
        logger.error(f"Error in AI settings endpoint: {e}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/check-trade-permission")
@login_required
def check_trade_permission():
    """Check if user's Binance API key has Spot Trading permissions.
    
    Uses GET /api/v3/account which returns canTrade: true when trading is enabled.
    Per Binance.US docs: https://docs.binance.us/
    """
    try:
        username = current_user.username
        logger.error(f"[TRADE_PERMISSION] Check requested for user: {username} (ID: {current_user.id})")
        cred = get_user_credentials(username)
        
        if not cred or not cred.api_key or not cred.api_secret:
            logger.error(f"[TRADE_PERMISSION] No API key configured for {username}")
            return jsonify({
                "has_api_key": False,
                "has_permission": False,
                "message": "No Binance API key configured."
            }), 200
        
        # IMPORTANT: /api/v3/account returns ACCOUNT capabilities, not API KEY restrictions!
        # canTrade=true just means the account TYPE supports trading, not that the API key has permission.
        # We need to test with an endpoint that requires trading permission to detect read-only keys.
        
        try:
            # Verify which API key we're using
            api_key_suffix = cred.api_key[-15:] if len(cred.api_key) > 15 else cred.api_key
            logger.error(f"[TRADE_PERMISSION] Testing API key permissions for {username} (key ends with: ...{api_key_suffix})")
            
            # IMPORTANT: /api/v3/openOrders doesn't respect API key restrictions (Binance bug)
            # Instead, try to place a TEST order which requires actual trading permission
            test_response = binance_us_api_call(
                cred,
                '/api/v3/order/test',
                method='POST',
                use_trading_keys=True,
                params_dict={
                    'symbol': 'BTCUSDT',
                    'side': 'BUY',
                    'type': 'LIMIT',
                    'timeInForce': 'GTC',
                    'quantity': '0.001',
                    'price': '10000'  # Very low price, won't execute
                }
            )
            
            logger.error(f"[TRADE_PERMISSION] Test order endpoint status: {test_response.status_code}")
            logger.error(f"[TRADE_PERMISSION] Test order response: {test_response.text[:200]}")
            
            if test_response.status_code == 200:
                # Successfully accessed trading endpoint - has permission
                logger.error(f"[TRADE_PERMISSION] ✅ {username} HAS trading permission (test order succeeded)")
                return jsonify({
                    "has_api_key": True,
                    "has_permission": True,
                    "message": ""
                }), 200
            else:
                # API returned an error (400, 401, 403, etc.)
                # Check if it's specifically a PERMISSION error
                error_code = None
                error_msg = f"API returned status {test_response.status_code}"
                try:
                    error_data = test_response.json()
                    error_code = error_data.get('code')
                    error_msg = error_data.get('msg', error_msg)
                except:
                    pass
                
                logger.warning(f"[TRADE_PERMISSION] Test order returned error {test_response.status_code}: code={error_code}, msg={error_msg}")

                # CRITICAL LOGIC: 
                # Error -2015 is "Invalid API-key, IP, or permissions for action" --> PERMISSION DENIED
                # Error -1013 is "Filter failure" --> PERMISSION GRANTED (but params bad)
                # Error -1022 is "Signature validation failed" --> PERMISSION UNKNOWN (assume OK)
                
                if error_code == -2015:
                    logger.error(f"[TRADE_PERMISSION] ❌ {username} DOES NOT have trading permission (error -2015)")
                    return jsonify({
                        "has_api_key": True,
                        "has_permission": False,
                        "message": "Spot Trading is not enabled for your API key."
                    }), 200
                else:
                    # Any other error means we passed the permission check but failed on params/balance/filters
                    # This implies the user DOES have trading permissions (or we can't tell, so give benefit of doubt)
                    logger.info(f"[TRADE_PERMISSION] ✅ {username} has permission (ignoring error {error_code}: {error_msg})")
                    return jsonify({
                        "has_api_key": True,
                        "has_permission": True,
                        "message": f"Trading permission verified (ignoring {error_msg})"
                    }), 200
                
        except Exception as api_err:
            logger.warning(f"Trade permission check failed: {api_err}")
            return jsonify({
                "has_api_key": True,
                "has_permission": False,
                "message": f"API key error: {str(api_err)}"
            }), 200
            
    except Exception as e:
        logger.error(f"Error checking trade permission: {e}")
        return jsonify({"has_api_key": False, "has_permission": False, "message": "Server error"}), 500

@app.route("/api/mark-onboarding-complete", methods=["POST"])
@login_required
def mark_onboarding_complete():
    """Mark the user as having seen the onboarding modal."""
    try:
        user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not user_setting:
            user_setting = UserSetting(user_id=current_user.id)
            db.session.add(user_setting)
        
        user_setting.has_seen_onboarding = True
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        logger.error(f"Error marking onboarding complete: {e}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/support/send", methods=["POST"])
def send_support_message():
    """Send support contact form message via email."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders
    
    try:
        full_name = request.form.get('fullName', '').strip()
        email = request.form.get('email', '').strip()
        topic = request.form.get('topic', '').strip()
        message = request.form.get('message', '').strip()
        
        # Validation
        if not email:
            return jsonify({"error": "Email address is required"}), 400
        if not topic:
            return jsonify({"error": "Topic is required"}), 400
        if not message:
            return jsonify({"error": "Message is required"}), 400
        if len(message) > 5000:
            return jsonify({"error": "Message must be 5000 characters or less"}), 400
        
        # Valid topics
        valid_topics = ['Billing', 'Technical Issue', 'Suggestions', 'Questions', 
                       'Account Access', 'Content Feedback', 'Other']
        if topic not in valid_topics:
            return jsonify({"error": "Invalid topic selected"}), 400
        
        # Build email
        support_email = "petrafan007@gmail.com"
        
        msg = MIMEMultipart()
        msg['From'] = email
        msg['To'] = support_email
        msg['Subject'] = f"[Crypto Alert App] {topic}"
        
        # Email body
        body = f"""New support message from Crypto Alert App:

From: {full_name or 'Not provided'}
Email: {email}
Topic: {topic}

Message:
{message}
"""
        msg.attach(MIMEText(body, 'plain'))
        
        # Handle attachment
        attachment = request.files.get('attachment')
        if attachment and attachment.filename:
            # Validate file size (100 MB)
            attachment.seek(0, 2)  # Seek to end
            file_size = attachment.tell()
            attachment.seek(0)  # Reset to beginning
            
            if file_size > 100 * 1024 * 1024:
                return jsonify({"error": "Attachment must be less than 100 MB"}), 400
            
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{attachment.filename}"')
            msg.attach(part)
        
        # Send email using localhost SMTP (assuming local mail server)
        # For Gmail, you would need app passwords and SSL
        try:
            # Try sendmail first (local)
            import subprocess
            email_content = msg.as_string()
            process = subprocess.Popen(
                ['/usr/sbin/sendmail', '-t', '-oi'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(email_content.encode())
            
            if process.returncode != 0:
                logger.error(f"Sendmail failed: {stderr.decode()}")
                # Fallback to direct SMTP if available
                raise Exception("Sendmail failed, trying SMTP")
                
        except Exception as sendmail_err:
            logger.warning(f"Sendmail not available: {sendmail_err}")
            # Try localhost SMTP
            try:
                with smtplib.SMTP('localhost', 25) as server:
                    server.sendmail(email, support_email, msg.as_string())
            except Exception as smtp_err:
                logger.error(f"SMTP also failed: {smtp_err}")
                # Log the message anyway so we don't lose it
                logger.info(f"SUPPORT MESSAGE (email failed): From={email}, Topic={topic}, Message={message[:200]}...")
                # Still return success - message logged
        
        logger.info(f"Support message received from {email} about {topic}")
        return jsonify({"success": True, "message": "Message sent successfully"}), 200
        
    except Exception as e:
        logger.error(f"Error sending support message: {e}")
        return jsonify({"error": "Failed to send message. Please try again."}), 500

@app.route("/api/tax-report/export", methods=["GET"])
@login_required
def export_tax_report_csv():
    try:
        from trading_models import AllActivity
        import io
        import csv
        
        activities = AllActivity.query.filter_by(user_id=current_user.id).order_by(AllActivity.date.desc()).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Headers
        writer.writerow(['Date', 'Type', 'Asset', 'Amount', 'Price Traded At', 'Proceeds', 'Fee', 'Cost Basis', 'Gain/Loss', 'Description', 'Exchange', 'TxID'])
        
        for act in activities:
            writer.writerow([
                act.date,
                act.type,
                act.asset,
                act.amount,
                act.price_sold_at or '',
                act.proceeds or 0,
                act.fee or 0,
                act.cost_basis or 0,
                act.gain_loss or 0,
                act.description or '',
                act.exchange or '',
                act.txid or ''
            ])
            
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f"crypto_tax_report_{datetime.now().strftime('%Y%m%d')}.csv"
        )
    except Exception as e:
        logger.error(f"Error exporting tax report: {e}")
        return jsonify({"error": "Failed to export tax report"}), 500

@app.route("/api/account/delete", methods=["DELETE"])
@login_required
def delete_account():
    try:
        user_id = current_user.id
        username = current_user.username
        
        # 1. Delete records from all tables
        # From models.py
        from models import Coin, WatchlistCoin, Notification, StakedCoin, StakingReward, AIPrompt, AIConversation, AICache, AIAnalysisSchedule
        Coin.query.filter_by(user_id=user_id).delete()
        WatchlistCoin.query.filter_by(user_id=user_id).delete()
        Notification.query.filter_by(user_id=user_id).delete()
        
        # Handle dependencies (StakingReward -> StakedCoin)
        StakingReward.query.filter_by(user_id=user_id).delete()
        StakedCoin.query.filter_by(user_id=user_id).delete()
        
        AIPrompt.query.filter_by(user_id=user_id).delete()
        AIConversation.query.filter_by(user_id=user_id).delete()
        AICache.query.filter_by(user_id=user_id).delete()
        AIAnalysisSchedule.query.filter_by(user_id=user_id).delete()
        
        # From trading_models.py
        from trading_models import TestOrder, RealOrder, TestPortfolio, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder
        TestOrder.query.filter_by(user_id=user_id).delete()
        RealOrder.query.filter_by(user_id=user_id).delete()
        TestPortfolio.query.filter_by(user_id=user_id).delete()
        TradingSettings.query.filter_by(user_id=user_id).delete()
        AllActivity.query.filter_by(user_id=user_id).delete()
        PortfolioValueHistory.query.filter_by(user_id=user_id).delete()
        StakingOrder.query.filter_by(user_id=user_id).delete()
        
        # From credentials.py
        from credentials import Credential, UserSetting, DesktopToken, User
        Credential.query.filter_by(user_id=user_id).delete()
        UserSetting.query.filter_by(user_id=user_id).delete()
        DesktopToken.query.filter_by(user_id=user_id).delete()
        
        # Finally delete the user
        User.query.filter_by(id=user_id).delete()
        
        db.session.commit()
        
        logger.info(f"USER DELETED: {username} (ID: {user_id}) and all associated data.")
        
        # Logout the user
        logout_user()
        
        return jsonify({"success": True, "message": "Account deleted successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting account for user {current_user.id}: {e}")
        return jsonify({"error": "Failed to delete account. Please try again."}), 500

@login_required
@app.route("/api/settings", methods=["GET", "POST"])
@login_required
def api_settings():
    """Get user settings and API keys"""
    try:
        # Get the current user
        print(f"=== DEBUG: current_user authenticated={current_user.is_authenticated} ===", flush=True)
        print(f"=== DEBUG: current_user.id={current_user.id if hasattr(current_user, 'id') else 'NO_ID'} ===", flush=True)
        print(f"=== DEBUG: current_user.username type={type(current_user.username) if hasattr(current_user, 'username') else 'NO_USERNAME_ATTR'} ===", flush=True)
        print(f"=== DEBUG: current_user={current_user}, username=NOT_SET_YET ===", flush=True)
        _ = current_user.id
        username = current_user.username
        if not username:
            return jsonify({"error": "User not authenticated"}), 401

        
        # Get user from credentials database
        # No more context switching! Use the consolidated models directly
        cred = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not cred:
            return jsonify({"error": "No credentials found"}), 404
        
        # Get AI settings
        ai_settings = get_user_ai_settings(username)
        encryption_active = is_encryption_available()
        encryption_persisted = is_persisted_key_available()
        
        if request.method == "POST":
            data = request.get_json()
            
            # --- START UserSetting Logic ---
            # Update UserSetting columns
            user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
            if not user_setting:
                user_setting = UserSetting(user_id=current_user.id)
                db.session.add(user_setting)
            
            allowed_fields = [
                'ai_enabled', 'ai_provider', 'ai_model', 'ai_risk_tolerance',
                'ai_confidence_threshold', 'ai_notifications_enabled', 'ai_analysis_frequency',
                'ai_cache_duration_hours', 'ai_analysis_window_start', 'ai_analysis_window_end',
                'ai_max_tokens', 'ai_web_search_enabled', 'tax_manual_invested_updated', 
                'tax_cost_basis_method', 'copilot_chat_pre', 'copilot_chat_post',
                'sentiment_analysis_frequency_hours', 'ai_provider_fallback', 'ai_model_fallback'
            ]

            for key, value in data.items():
                if key == "ai_prompts" and isinstance(value, dict):
                    # Update AIPrompt fields
                    ai_prompts = AIPrompt.query.filter_by(user_id=current_user.id).first()
                    if not ai_prompts:
                        ai_prompts = AIPrompt(user_id=current_user.id)
                        db.session.add(ai_prompts)
                    prompt_fields = [
                        'market_analysis_pre', 'market_analysis_post',
                        'risk_assessment_pre', 'risk_assessment_post',
                        'portfolio_review_pre', 'portfolio_review_post',
                        'coin_analysis_pre', 'coin_analysis_post',
                        'sentiment_prompt_pre', 'sentiment_prompt_post'
                    ]
                    for field in prompt_fields:
                        if field in value:
                            setattr(ai_prompts, field, value[field])
                    continue 

                # Explicit column updates
                if key in allowed_fields:
                    if key in ['ai_enabled', 'ai_notifications_enabled', 'ai_web_search_enabled']:
                         setattr(user_setting, key, bool(value))
                    elif key in ['ai_cache_duration_hours', 'ai_max_tokens']:
                        try:
                            setattr(user_setting, key, int(value))
                        except:
                            pass
                    elif key in ['ai_confidence_threshold']:
                        try:
                            setattr(user_setting, key, float(value))
                        except:
                            pass
                    elif key in ['ai_confidence_threshold']:
                        try:
                            setattr(user_setting, key, float(value))
                        except:
                            pass
                    elif key in ['sentiment_analysis_frequency_hours']:
                        try:
                            setattr(user_setting, key, int(value))
                        except:
                            pass
                    else:
                        setattr(user_setting, key, str(value))
            # --- END UserSetting Logic ---

            encryption_key_value = data.pop('credentials_encryption_key', None)
            data.pop('credentials_encryption_key_configured', None)
            data.pop('credentials_encryption_key_persisted', None)
            
            if encryption_key_value is not None:
                cleaned_key = encryption_key_value.strip()
                if cleaned_key:
                    try:
                        persist_encryption_key(cleaned_key)
                        encryption_active = True
                        encryption_persisted = True
                    except EncryptionKeyError as enc_err:
                        logger.error("Invalid encryption key provided: %s", enc_err)
                        return jsonify({
                            "success": False,
                            "message": "Encryption key invalid. Provide a valid 32-byte key or base64 string."
                        }), 400

            try:
                if 'api_key' in data:
                    cred.api_key = data['api_key']
                if 'api_secret' in data:
                    cred.api_secret = data['api_secret']
                # DEPRECATED: trading_api_key/secret are now unified with api_key/secret
                # We do NOT update them here to prevent overwriting with stale frontend data
                if 'openai_key' in data:
                    cred.openai_key = data['openai_key']
                if 'zai_key' in data:
                    cred.zai_key = data['zai_key']
                if 'perplexity_key' in data:
                    cred.perplexity_key = data['perplexity_key']
                if 'gemini_key' in data:
                    cred.gemini_key = data['gemini_key']
                
                # Fallback Keys
                if 'openai_key_fallback' in data:
                    cred.openai_key_fallback = data['openai_key_fallback']
                if 'zai_key_fallback' in data:
                    cred.zai_key_fallback = data['zai_key_fallback']
                if 'perplexity_key_fallback' in data:
                    cred.perplexity_key_fallback = data['perplexity_key_fallback']
                if 'gemini_key_fallback' in data:
                    cred.gemini_key_fallback = data['gemini_key_fallback']

                if 'ai_provider' in data:
                    cred.ai_provider = data['ai_provider']
                if 'brave_search_api_key' in data:
                    cred.brave_search_api_key = data['brave_search_api_key']
                if 'brave_search_api_key_fallback' in data:
                    cred.brave_search_api_key_fallback = data['brave_search_api_key_fallback']
                
                # Check for Default Prompt Migration if AI is being enabled/configured
                # If we have an AI provider set, ensure prompts exist
                # Check for Default Prompt Migration if AI is being enabled/configured
                # We check if AI is enabled in the incoming data OR if provider is set
                should_check_prompts = False
                if 'ai_enabled' in data and data['ai_enabled']:
                    should_check_prompts = True
                    logger.info("Auto-fill Trigger: AI Enabled via UI")
                elif cred.ai_provider and cred.ai_provider != 'none':
                    should_check_prompts = True
                    logger.info(f"Auto-fill Trigger: AI Provider set to {cred.ai_provider}")
                
                if should_check_prompts:
                    logger.info("Checking if AI prompts need seeding...")
                    user_prompts = AIPrompt.query.get(current_user.id)
                    defaults = DefaultAIPrompt.query.first()
                    
                    if defaults:
                        if not user_prompts:
                            logger.info(f"Creating new AIPrompt record for user {current_user.id}")
                            user_prompts = AIPrompt(user_id=current_user.id)
                            db.session.add(user_prompts)
                        
                        # Apply defaults if fields are empty
                        if not user_prompts.market_analysis_pre:
                            logger.info(f"Seeding default prompts into record for user {current_user.id}")
                            user_prompts.market_analysis_pre = defaults.market_analysis_pre
                            user_prompts.market_analysis_post = defaults.market_analysis_post
                            user_prompts.risk_assessment_pre = defaults.risk_assessment_pre
                            user_prompts.risk_assessment_post = defaults.risk_assessment_post
                            user_prompts.portfolio_review_pre = defaults.portfolio_review_pre
                            user_prompts.portfolio_review_post = defaults.portfolio_review_post
                            user_prompts.coin_analysis_pre = defaults.coin_analysis_pre
                            user_prompts.coin_analysis_post = defaults.coin_analysis_post
                            user_prompts.sentiment_prompt_pre = defaults.sentiment_prompt_pre
                            user_prompts.sentiment_prompt_post = defaults.sentiment_prompt_post
                            user_prompts.news_analysis_pre = defaults.news_analysis_pre
                            user_prompts.news_analysis_post = defaults.news_analysis_post

                db.session.commit()
                
                # TRIGGER AUTO-SYNC if API keys were updated
                if 'api_key' in data or 'api_secret' in data:
                    logger.info(f"API keys updated for user {current_user.id}. Triggering portfolio sync.")
                    try:
                        sync_portfolio_from_binance(current_user.id)
                    except Exception as e:
                        logger.error(f"Post-settings portfolio sync failed: {e}")

            except EncryptionKeyError as enc_err:
                logger.error(f"Encryption key error while saving credentials: {enc_err}")
                db.session.rollback()
                return jsonify({
                    "success": False,
                    "error": "Credential encryption key is not configured. Add a Fernet key in Settings before saving secrets."
                }), 500
        
        response = ai_settings.copy()
        
        # Overlay credentials
        response.update({
            "api_key": cred.api_key,
            "api_secret": cred.api_secret,
            # Legacy fields maintained for frontend compatibility if needed, but values redirected
            "trading_api_key": getattr(cred, 'trading_api_key', None),
            "trading_api_secret": getattr(cred, 'trading_api_secret', None),
            "openai_key": cred.openai_key,
            "zai_key": getattr(cred, 'zai_key', None),
            "perplexity_key": getattr(cred, 'perplexity_key', None),
            "gemini_key": getattr(cred, 'gemini_key', None),
            # ai_provider is already in ai_settings, but ensure sync? 
            # ai_settings takes precedence as it handles defaults and user_settings overlay
            "telegram_token": cred.telegram_token,
            "telegram_chat_id": cred.telegram_chat_id,
            "news_api": cred.news_api,
            "brave_search_api_key": getattr(cred, 'brave_search_api_key', None),
            "brave_search_api_key_fallback": getattr(cred, 'brave_search_api_key_fallback', None),
            
            # Encryption status
            "credentials_encryption_key": "", # Never return the key
            "credentials_encryption_key_configured": bool(encryption_active),
            "credentials_encryption_key_persisted": bool(encryption_persisted),
        })
        
        return jsonify(response)
    except Exception as e:
        logger.error(f"Get settings error: {str(e)}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/ai/models', methods=['GET'])
@login_required
def get_ai_models():
    # These are the hardcoded models from the settings validation logic
    openai_models = {
        'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1', 'gpt-4.1-mini',
        'gpt-4.1-nano', 'o4-mini', 'o3', 'o3-mini',
    }
    zai_models = {
        'glm-4.7', 'glm-4.7-flash', 'glm-4.7-flashx',
    }
    perplexity_models = {
        'sonar-pro', 'sonar', 'sonar-reasoning',
    }
    gemini_models = {
        'gemini-3-flash-preview', 'gemini-3-pro-preview',
    }
    
    # Create a dictionary of labels for the models
    model_labels = {
        'gpt-5': 'GPT-5',
        'gpt-5-mini': 'GPT-5 Mini',
        'gpt-5-nano': 'GPT-5 Nano',
        'gpt-4.1': 'GPT-4.1',
        'gpt-4.1-mini': 'GPT-4.1 Mini',
        'gpt-4.1-nano': 'GPT-4.1 Nano',
        'o4-mini': 'o4 Mini',
        'o3': 'o3',
        'o3-mini': 'o3 Mini',
        'glm-4.7': 'GLM-4.7',
        'glm-4.7-flash': 'GLM-4.7 Flash',
        'glm-4.7-flashx': 'GLM-4.7 FlashX',
        'sonar-pro': 'Sonar Pro',
        'sonar': 'Sonar',
        'sonar-reasoning': 'Sonar Reasoning',
        'gemini-3-flash-preview': 'Gemini 3 Flash (preview)',
        'gemini-3-pro-preview': 'Gemini 3 Pro (preview)',
    }
    
    def get_model_options(models):
        return sorted([{'value': m, 'label': model_labels.get(m, m)} for m in models], key=lambda x: x['label'])

    return jsonify({
        'openai': get_model_options(openai_models),
        'zai': get_model_options(zai_models),
        'perplexity': get_model_options(perplexity_models),
        'gemini': get_model_options(gemini_models),
    })

@app.route("/api/test-binance-connection", methods=["GET", "POST"])
@login_required
def api_test_binance_connection():
    """Test Binance.US Portfolio API connection (production only, no testnet)"""
    try:
        # ALWAYS use production Binance.US - testnet is geo-restricted for US users
        api_key = None
        api_secret = None
        testnet = False  # Force production for US users
        
        # Check if keys provided in request body (for testing new keys)
        if request.method == 'POST':
            data = request.get_json() or {}
            api_key = data.get('api_key')
            api_secret = data.get('api_secret')
        
        # Fallback to credentials from database
        if not api_key or not api_secret:
            # Get credentials from credentials table
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if creds:
                api_key = decrypt_secret(creds.api_key)
                api_secret = decrypt_secret(creds.api_secret)
            
        if not api_key or not api_secret:
            return jsonify({
                "success": False,
                "message": "Binance API key and secret are required"
            }), 400
            
        # Import Binance client

        from binance.client import Client
        from binance.exceptions import BinanceAPIException
        
        # If we get a location restriction error, default to testnet and inform user
        location_restricted = False
        binance_type = "Binance"
        
        # Connect to Binance.US only (US users cannot use regular Binance)
        connection_attempts = []
        
        try:
            logger.info(f"Attempting Binance.US connection with testnet={testnet}")
            client = Client(
                api_key,
                api_secret,
                testnet=testnet,
                tld='us',
                requests_params={
                    'timeout': 15,  # Increased timeout
                }
            )
            binance_type = "Binance.US"
            account = client.get_account()
            logger.info("Binance.US connection successful")
            
        except BinanceAPIException as api_e:
            connection_attempts.append(f"Binance.US: {api_e.message}")
            logger.warning(f"Binance.US failed: {api_e.message}")
            
            return jsonify({
                "success": False,
                "message": "Binance.US connection failed",
                "details": f"API Error: {api_e.message}",
                "suggestion": "For US users: 1) Verify your Binance.US API keys are correct, 2) Ensure your Binance.US account is verified, 3) Check API permissions include 'Read Info'",
                "attempts": connection_attempts
            }), 400
                
        except Exception as e:
            connection_attempts.append(f"Binance.US: {str(e)}")
            logger.warning(f"Binance.US connection failed: {e}")
            
            return jsonify({
                "success": False,
                "message": "Binance.US connection failed",
                "details": f"Connection Error: {str(e)}",
                "suggestion": "For US users: 1) Verify your Binance.US API keys are correct, 2) Check your network connection, 3) Ensure your Binance.US account is verified",
                "attempts": connection_attempts
            }), 400
            
        # Get balances (filter out zero balances)
        balances = [
            {"asset": b['asset'], "free": b['free'], "locked": b['locked']}
            for b in account['balances'] 
            if float(b['free']) > 0 or float(b['locked']) > 0
        ]
        
        # Update last connection time
        try:
            user_obj = User.query.filter_by(username=current_user.username).first()
            if user_obj:
                user_obj.binance_connected = True
                user_obj.binance_connected_at = datetime.utcnow()
                db.session.commit()
        except Exception as e:
            logger.warning(f"Could not update connection timestamp: {e}")
        
        success_message = f"{binance_type} {'Testnet ' if testnet else ''}API connection successful"
        if location_restricted:
            success_message += " (automatically switched to testnet due to location restrictions)"
        
        return jsonify({
            "success": True,
            "message": success_message,
            "location_restricted": location_restricted,
            "using_testnet": testnet,
            "account": {
                "makerCommission": account.get('makerCommission'),
                "takerCommission": account.get('takerCommission'),
                "buyerCommission": account.get('buyerCommission'),
                "sellerCommission": account.get('sellerCommission'),
                "canTrade": account.get('canTrade'),
                "canWithdraw": account.get('canWithdraw'),
                "canDeposit": account.get('canDeposit'),
                "balances": balances
            }
        })
        
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e.message}")
        return jsonify({
            "success": False,
            "message": f"Binance API error: {e.message}",
            "code": e.code,
            "suggestion": "Check your API credentials and try enabling testnet mode"
        }), 400
        
    except Exception as e:
        logger.error(f"Binance connection test failed: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Connection test failed: {str(e)}",
            "suggestion": "Check your network connection and API credentials"
        }), 500

@app.route("/api/test-trading-connection", methods=["POST"])
@login_required
def api_test_trading_connection():
    """Test Binance.US Trading API connection"""
    try:
        data = request.get_json()
        trading_api_key = data.get('trading_api_key')
        trading_api_secret = data.get('trading_api_secret')
        
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                "success": False,
                "message": "Trading API key and secret are required"
            }), 400
        
        # Import Binance client
        from binance.client import Client
        from binance.exceptions import BinanceAPIException
        
        try:
            logger.info(f"Testing Binance.US Trading API connection for user {current_user.username}")
            client = Client(
                trading_api_key,
                trading_api_secret,
                testnet=False,
                tld='us',
                requests_params={
                    'timeout': 15,
                }
            )
            
            # Test API connection and permissions
            account = client.get_account()
            
            # Check if trading is enabled
            can_trade = account.get('canTrade', False)
            
            if not can_trade:
                return jsonify({
                    "success": False,
                    "message": "Trading is not enabled for this API key. Please enable SPOT trading permissions."
                }), 400
            
            logger.info("Binance.US Trading API connection successful")
            
            return jsonify({
                "success": True,
                "message": "Trading API connection successful! SPOT trading is enabled.",
                "account": {
                    "canTrade": can_trade,
                    "canWithdraw": account.get('canWithdraw'),
                    "canDeposit": account.get('canDeposit')
                }
            })
            
        except BinanceAPIException as api_e:
            logger.warning(f"Binance.US Trading API failed: {api_e.message}")
            return jsonify({
                "success": False,
                "message": f"Binance.US API Error: {api_e.message}",
                "suggestion": "Verify your Trading API credentials are correct and have SPOT trading permissions"
            }), 400
            
    except Exception as e:
        logger.error(f"Trading connection test failed: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Connection test failed: {str(e)}",
            "suggestion": "Check your network connection and Trading API credentials"
        }), 500

def log_ai_communication(direction, user_id, provider, model, messages, response=None, error=None, prompt_type="test", api_key=None):
    """Log all AI API communications for debugging"""
    try:
        # Resolve username safely without session (which fails in background threads)
        username = "unknown"
        if user_id:
            try:
                user = db.session.get(User, user_id)
                if user:
                    username = user.username
            except:
                pass
        
        logger.info(f"\n{'='*80}")
        logger.info(f"🔍 {provider.upper()} COMMUNICATION LOG - {direction.upper()}")
        logger.info(f"👤 User: {username} (ID: {user_id})")
        logger.info(f"🤖 Provider: {provider}")
        logger.info(f"🤖 Model: {model}")
        logger.info(f"📝 Prompt Type: {prompt_type}")
        logger.info(f"⏰ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*80}")
        
        if direction == "REQUEST":
            logger.info(f"📤 SENDING TO {provider.upper()}:")
            if api_key:
                logger.info(f"   API Key: {api_key[:10]}...")
            else:
                logger.info("   API Key: [not available]")
            logger.info(f"   Messages: {len(messages)} message(s)")
            for i, msg in enumerate(messages):
                logger.info(f"   Message {i+1}: {msg['role']} - {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}")
        
        elif direction == "RESPONSE":
            if response:
                logger.info(f"📥 RECEIVED FROM {provider.upper()}:")
                logger.info("   Status: SUCCESS")
                try:
                    if hasattr(response, 'choices'):
                        # OpenAI format
                        content = response.choices[0].message.content
                        logger.info(f"   Response: {content}")
                        if hasattr(response, 'usage'):
                            logger.info(f"   Usage: {response.usage}")
                    else:
                        # Unified format
                        content = response.get('content', '')
                        logger.info(f"   Response: {content}")
                        if 'usage' in response:
                            logger.info(f"   Usage: {response['usage']}")
                except Exception as e:
                    logger.error(f"   Error parsing response: {e}")
            elif error:
                logger.info(f"📥 RECEIVED FROM {provider.upper()}:")
                logger.info("   Status: ERROR")
                logger.info(f"   Error Type: {type(error).__name__}")
                logger.info(f"   Error Message: {str(error)}")
                
                # Check for specific error types
                if "authentication" in str(error).lower() or "invalid" in str(error).lower():
                    logger.info("   🔴 DETECTED: Authentication/API Key Error")
                elif "quota" in str(error).lower() or "billing" in str(error).lower():
                    logger.info("   🔴 DETECTED: Quota/Billing Error")
                elif "rate" in str(error).lower():
                    logger.info("   🟡 DETECTED: Rate Limit Error")
        
        logger.info("{}\n".format('='*80))
        
    except Exception as e:
        logger.error(f"❌ Error in {provider.upper()} logging: {e}")

@app.route("/api/test-openai-connection")
@login_required
def api_test_openai_connection():
    """Test OpenAI API connection with proper error detection"""
    try:
        # Get current user
        username = current_user.username
        user_id = current_user.id
        
        # Use the proper database access method
        cred = get_user_credentials(username)
            
        if not cred or not cred.openai_key:
            return jsonify({
                "success": False,
                "message": "No OpenAI API key configured"
            }), 400
        
        # Test OpenAI connection using the new client format
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cred.openai_key)
            # Get user's preferred model for testing - this will apply normalization
            user_settings = get_user_ai_settings(username)
            test_model = user_settings.get('ai_model', 'gpt-5')
            
            # Prepare test message
            test_messages = [{"role": "user", "content": "Hello"}]
            
            # Log the request
            log_ai_communication("REQUEST", user_id, "openai", test_model, test_messages, prompt_type="connection_test", api_key=cred.openai_key)
            
            # Make the API call
            response = client.chat.completions.create(
                model=test_model,
                messages=test_messages,
                max_completion_tokens=5
            )
            
            # Log the successful response
            log_ai_communication("RESPONSE", user_id, "openai", test_model, test_messages, response=response, prompt_type="connection_test", api_key=cred.openai_key)
            
            return jsonify({
                "success": True,
                "message": "OpenAI connection successful - API key is valid"
            })
            
        except ImportError:
            log_ai_communication("RESPONSE", user_id, "openai", test_model, test_messages, error=ImportError("OpenAI package not installed"), prompt_type="connection_test", api_key=cred.openai_key)
            return jsonify({
                "success": False,
                "message": "OpenAI package not installed"
            }), 400
            
        except Exception as openai_error:
            # Log the error response
            log_ai_communication("RESPONSE", user_id, "openai", test_model, test_messages, error=openai_error, prompt_type="connection_test", api_key=cred.openai_key)
            
            error_msg = str(openai_error)
            _ = type(openai_error).__name__
            
            # Check for specific error types
            if "authentication" in error_msg.lower() or "invalid" in error_msg.lower() or "revoked" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Error: The API key is not valid or has been revoked"
                }), 400
            elif "quota" in error_msg.lower() or "billing" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Error: API quota exceeded or billing issue"
                }), 400
            elif "rate" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Error: Rate limit exceeded"
                }), 400
            else:
                return jsonify({
                    "success": False,
                    "message": f"OpenAI connection failed: {error_msg}"
                }), 400
            
    except Exception as e:
        logger.error(f"Test OpenAI connection error: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route("/api/test-zai-connection")
@login_required
def api_test_zai_connection():
    """Test Z.AI API connection with proper error detection"""
    try:
        # Get the current user
        user_id = current_user.id
        username = current_user.username
        
        # Use the proper database access method
        cred = get_user_credentials(username)
            
        if not cred:
            logger.error(f"No credentials found for user {username}")
            return jsonify({
                "success": False,
                "message": "No credentials found"
            }), 400
            
        if not cred.zai_key:
            logger.error(f"No Z.AI API key configured for user {username}")
            return jsonify({
                "success": False,
                "message": "No Z.AI API key configured"
            }), 400
        
        # Test Z.AI connection
        try:
            from zai_client import ZAIClient
            # Prepare test message
            test_messages = [{"role": "user", "content": "Hello"}]
            # Log the request
            log_ai_communication("REQUEST", user_id, "zai", "glm-4.7-flash", test_messages, prompt_type="connection_test", api_key=cred.zai_key)
            # Make the API call through our wrapper
            result = ZAIClient(cred.zai_key).chat_completion(test_messages, model="glm-4.7-flash", max_tokens=5)
            if result.get("success"):
                log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, response=result, prompt_type="connection_test", api_key=cred.zai_key)
                return jsonify({"success": True, "message": "Z.AI connection successful - API key is valid"})
            else:
                log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, error=Exception(result.get("error")), prompt_type="connection_test", api_key=cred.zai_key)
                return jsonify({"success": False, "message": f"Z.AI error: {result.get('error')}"}), 500
        except ImportError:
            return jsonify({"success": False, "message": "Z.AI client wrapper not available"}), 500
            
        except ImportError:
            log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, error=ImportError("Z.AI package not installed"), prompt_type="connection_test", api_key=cred.zai_key)
            return jsonify({
                "success": False,
                "message": "Z.AI package not installed"
            }), 500
            
        except Exception as zai_error:
            log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, error=zai_error, prompt_type="connection_test", api_key=cred.zai_key)
            error_msg = str(zai_error)
            
            # Provide specific error messages based on error type
            if "authentication" in error_msg.lower() or "invalid" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Invalid Z.AI API key - please check your key"
                }), 400
            elif "quota" in error_msg.lower() or "billing" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Z.AI billing issue - please check your account"
                }), 400
            elif "rate" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Z.AI rate limit exceeded - please try again later"
                }), 429
            else:
                return jsonify({
                    "success": False,
                    "message": f"Z.AI connection failed: {error_msg}"
                }), 500
                
    except Exception as e:
        logger.error(f"Test Z.AI connection error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/test-brave-search", methods=['POST'])
@login_required
def api_test_brave_search():
    """Test Brave Search API key validity"""
    try:
        data = request.get_json()
        brave_api_key = data.get('brave_search_api_key') or data.get('api_key')
        
        if not brave_api_key:
            return jsonify({
                "success": False,
                "message": "No Brave Search API key provided"
            }), 400
        
        # Test Brave Search API with a simple query
        import requests
        
        test_url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": brave_api_key
        }
        params = {
            "q": "test query",
            "count": 1
        }
        
        response = requests.get(test_url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            # API key is valid
            data = response.json()
            return jsonify({
                "success": True,
                "message": "Brave Search API key is valid",
                "usage": "Unknown"  # Brave doesn't always return usage in test calls
            })
        elif response.status_code == 401:
            return jsonify({
                "success": False,
                "message": "Invalid Brave Search API key"
            }), 400
        elif response.status_code == 429:
            return jsonify({
                "success": False,
                "message": "Brave Search API rate limit exceeded (2000/month limit reached)"
            }), 429
        else:
            return jsonify({
                "success": False,
                "message": f"Brave Search API error: {response.status_code}"
            }), 400
            
    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "message": "Brave Search API request timed out"
        }), 500
    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "message": f"Brave Search API request failed: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Test Brave Search API error: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Unexpected error: {str(e)}"
        }), 500

# Trading API Endpoints
@app.route('/api/trading-pairs')
@login_required
def api_trading_pairs():
    """Get available trading pairs - BINANCE VERSION"""
    logger.info("Trading pairs API called (Binance mode)")
    # Return Binance.US trading pairs exclusively
    # Return Binance.US trading pairs exclusively
    binance_pairs = [
        {'id': 'USDTUSD', 'base_currency': 'USDT', 'quote_currency': 'USD', 'display_name': 'USDT-USD', 'status': 'online'},
        {'id': 'BTCUSD', 'base_currency': 'BTC', 'quote_currency': 'USD', 'display_name': 'Bitcoin-USD', 'status': 'online'},
        {'id': 'ETHUSD', 'base_currency': 'ETH', 'quote_currency': 'USD', 'display_name': 'Ethereum-USD', 'status': 'online'},
        {'id': 'BTCUSDT', 'base_currency': 'BTC', 'quote_currency': 'USDT', 'display_name': 'Bitcoin-USDT', 'status': 'online'},
        {'id': 'ETHUSDT', 'base_currency': 'ETH', 'quote_currency': 'USDT', 'display_name': 'Ethereum-USDT', 'status': 'online'},
        {'id': 'SOLUSDT', 'base_currency': 'SOL', 'quote_currency': 'USDT', 'display_name': 'Solana-USDT', 'status': 'online'},
        {'id': 'ADAUSDT', 'base_currency': 'ADA', 'quote_currency': 'USDT', 'display_name': 'Cardano-USDT', 'status': 'online'},
        {'id': 'SUIUSDT', 'base_currency': 'SUI', 'quote_currency': 'USDT', 'display_name': 'Sui-USDT', 'status': 'online'}
    ]
    return jsonify({'pairs': binance_pairs})

@app.route('/api/market-data/<symbol>')
@login_required
def api_market_data(symbol):
    """Get market data for a specific symbol from Binance"""
    try:
        # Get Binance credentials for the user
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({'error': 'Binance API credentials not configured'}), 401
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({'error': 'Binance API credentials not configured'}), 401
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            tld='us'  # Use Binance.US
        )
        
        # Get 24hr ticker data
        ticker_symbol = f"{symbol}USDT" if not symbol.endswith('USDT') else symbol
        ticker = client.get_24hr_ticker(symbol=ticker_symbol)
        
        market_data = {
            'price': float(ticker['lastPrice']),
            'change_24h': float(ticker['priceChangePercent']),
            'high_24h': float(ticker['highPrice']),
            'low_24h': float(ticker['lowPrice']),
            'volume_24h': float(ticker['volume'])
        }
        
        return jsonify(market_data)
        
    except Exception as e:
        logger.error(f"Error fetching market data for {symbol}: {e}")
        return jsonify({'error': 'Failed to fetch market data'}), 500
        return jsonify(market_data)
    except Exception as e:
        logger.error(f"Market data error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/place-order', methods=['POST'])
@login_required
def api_place_order():
    """Place a trading order on Binance"""
    try:
        data = request.get_json()
        side = data.get('side')  # BUY or SELL
        symbol = data.get('symbol')  # e.g., 'BTCUSDT'
        order_type = data.get('order_type')  # MARKET, LIMIT
        quantity = data.get('quantity')
        price = data.get('price')  # Required for LIMIT orders
        
        if not all([side, symbol, order_type, quantity]):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        # Get Binance credentials for the user
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({'success': False, 'error': 'Binance API credentials not configured'}), 401
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({'success': False, 'error': 'Binance API credentials not configured'}), 401
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            tld='us'  # Use Binance.US
        )
        
        # Place order on Binance
        try:
            if order_type.upper() == 'MARKET':
                if side.upper() == 'BUY':
                    order = client.order_market_buy(
                        symbol=symbol,
                        quantity=quantity
                    )
                else:
                    order = client.order_market_sell(
                        symbol=symbol,
                        quantity=quantity
                    )
            elif order_type.upper() == 'LIMIT':
                if not price:
                    return jsonify({'success': False, 'error': 'Price required for limit orders'})
                
                if side.upper() == 'BUY':
                    order = client.order_limit_buy(
                        symbol=symbol,
                        quantity=quantity,
                        price=str(price)
                    )
                else:
                    order = client.order_limit_sell(
                        symbol=symbol,
                        quantity=quantity,
                        price=str(price)
                    )
            else:
                return jsonify({'success': False, 'error': f'Unsupported order type: {order_type}'})
            
            logger.info(f"Binance order placed successfully: {order['orderId']}")
            
            # Log the transaction to the logs database
            try:
                from trading_models import AllActivity
                
                # Extract base symbol from trading pair
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    base_symbol = symbol[:-3]
                elif symbol.endswith('USDT'):
                    base_symbol = symbol[:-4]
                else:
                    base_symbol = symbol
                
                # Calculate proceeds and fees from order response
                executed_qty = float(order.get('executedQty', quantity))
                fills = order.get('fills', [])
                
                total_commission = 0.0
                avg_price = 0.0
                
                if fills:
                    total_price = sum(float(fill['price']) * float(fill['qty']) for fill in fills)
                    total_qty = sum(float(fill['qty']) for fill in fills)
                    avg_price = total_price / total_qty if total_qty > 0 else 0
                    total_commission = sum(float(fill['commission']) for fill in fills)
                else:
                    avg_price = float(order.get('price', price or 0))
                
                proceeds = executed_qty * avg_price
                
                # Create new activity using ORM
                new_activity = AllActivity(
                    date=datetime.utcnow(),
                    type=side.upper(),
                    asset=base_symbol.upper(),
                    amount=executed_qty if side.upper() == 'BUY' else -executed_qty,
                    proceeds=proceeds,
                    fee=total_commission,
                    txid=f"binance_{order['orderId']}",
                    status=order['status'],
                    details=f"Binance {order_type} order: {order['orderId']}",
                    avg_entry=avg_price,
                    user_id=current_user.id,
                    exchange='binance'
                )
                
                db.session.add(new_activity)
                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)
                logger.info(f"Transaction logged to database: {base_symbol} {side}")
                
                # Update the portfolio to reflect the trade
                try:
                    from models import db, Coin
                    from datetime import datetime
                    
                    # Get the executed quantity and price
                    executed_qty = float(order.get('executedQty', quantity))
                    avg_price = float(order.get('price', price or 0))
                    
                    # Update the coins table
                    if side.upper() == 'BUY':
                        # For buys, add to the existing amount or create a new entry
                        coin = Coin.query.filter_by(user_id=current_user.id, symbol=base_symbol).first()
                        if coin:
                            # Update existing coin
                            new_amount = coin.amount + executed_qty
                            new_avg_entry = ((coin.amount * coin.avg_entry) + (executed_qty * avg_price)) / new_amount
                            coin.amount = new_amount
                            coin.avg_entry = new_avg_entry
                            coin.auto_hidden = False  # Ensure coin is visible after buying
                        else:
                            # Create new coin entry
                            coin = Coin(
                                user_id=current_user.id,
                                symbol=base_symbol,
                                amount=executed_qty,
                                avg_entry=avg_price,
                                current=avg_price,
                                is_manual=False,
                                auto_hidden=False
                            )
                            db.session.add(coin)
                        
                        # Update USDT balance (subtract cost)
                        total_cost = executed_qty * avg_price
                        usdt_coin = Coin.query.filter_by(user_id=current_user.id, symbol='USDT').first()
                        if usdt_coin:
                            usdt_coin.amount -= total_cost
                    else:
                        # For sells, reduce the amount or remove the coin if fully sold
                        coin = Coin.query.filter_by(user_id=current_user.id, symbol=base_symbol).first()
                        if coin:
                            new_amount = coin.amount - executed_qty
                            if new_amount <= 0:
                                # Remove the coin if fully sold
                                db.session.delete(coin)
                            else:
                                coin.amount = new_amount
                            
                            # Update USDT balance (add proceeds)
                            total_proceeds = executed_qty * avg_price
                            usdt_coin = Coin.query.filter_by(user_id=current_user.id, symbol='USDT').first()
                            if usdt_coin:
                                usdt_coin.amount += total_proceeds
                            else:
                                usdt_coin = Coin(
                                    user_id=current_user.id,
                                    symbol='USDT',
                                    amount=total_proceeds,
                                    avg_entry=1.0,
                                    current=1.0,
                                    is_manual=False
                                )
                                db.session.add(usdt_coin)
                    
                    db.session.commit()
                    logger.info(f"Portfolio updated for {base_symbol} {side} order")
                    
                except Exception as update_error:
                    logger.error(f"Failed to update portfolio: {update_error}")
                    # Don't fail the entire request, just log the error
                
            except Exception as log_e:
                logger.error(f"Failed to log transaction: {log_e}")
            
            return jsonify({
                'success': True,
                'order_id': order['orderId'],
                'status': order['status'],
                'executed_qty': order.get('executedQty', '0'),
                'message': f'Order placed successfully on Binance',
                'portfolio_updated': True
            })
            
        except Exception as binance_e:
            logger.error(f"Binance order failed: {binance_e}")
            return jsonify({
                'success': False,
                'error': f'Order placement failed: {str(binance_e)}'
            }), 500
        
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


def build_order_config(order_type, side, amount, data, symbol):
    """Build the order configuration for different order types"""
    params = {
        'symbol': symbol,
        'side': side,
        'type': order_type,
    }

    if order_type == 'MARKET':
        if side == 'BUY' and data.get('quoteQuantity'):
             params['quoteOrderQty'] = data.get('quoteQuantity')
        else:
            params['quantity'] = amount
    else: # For LIMIT, STOP_LOSS, etc.
        params['quantity'] = amount

    if order_type in ['LIMIT', 'LIMIT_MAKER', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT']:
        limit_price = data.get('price')
        if not limit_price:
            raise ValueError("Limit price required for limit orders")
        params['price'] = limit_price
    
    if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
        params['timeInForce'] = data.get('timeInForce', 'GTC')

    if order_type in ['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT', 'OCO']:
        stop_price = data.get('stopPrice')
        if not stop_price:
            raise ValueError("Stop price required for stop orders")
        params['stopPrice'] = stop_price

    if order_type == 'OCO':
        stop_limit_price = data.get('stopLimitPrice')
        if not stop_limit_price:
            raise ValueError("Stop limit price required for OCO orders")
        params['stopLimitPrice'] = stop_limit_price
        params['stopLimitTimeInForce'] = data.get('stopLimitTimeInForce', 'GTC')

    return params




def sync_portfolio_from_binance(user_id):
    """Sync portfolio with Binance.US account balances
    
    Args:
        user_id: ID of the user to sync
    """
    try:
        from models import db, Coin
        from binance.client import Client
        
        # Get user's Binance API credentials
        creds = Credential.query.filter_by(user_id=user_id).first()
        
        if not creds:
            logger.error(f"No Binance API credentials found for user {user_id}")
            return False, "Binance API credentials not configured"
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            logger.error(f"Encrypted Binance credentials unavailable for user {user_id}")
            return False, "Binance API credentials not configured"
        
        # Initialize Binance client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            tld='us'  # Use Binance.US
        )
        
        # Get account info from Binance
        try:
            account = client.get_account()
        except Exception as e:
            logger.error(f"Failed to fetch Binance account: {e}")
            return False, f"Failed to fetch Binance account: {str(e)}"
        
        # Get all non-zero balances
        balances = [b for b in account['balances'] if float(b['free']) > 0 or float(b['locked']) > 0]
        
        # Get current prices for all coins
        prices = {}
        tickers = client.get_all_tickers()
        for ticker in tickers:
            symbol = ticker['symbol']
            # Prioritize USDT pairs, then USD
            if symbol.endswith('USDT'):
                base_asset = symbol[:-4]
                prices[base_asset] = float(ticker['price'])
            elif symbol.endswith('USD'):
                base_asset = symbol[:-3]
                # Only set if not already set by USDT
                if base_asset not in prices:
                    prices[base_asset] = float(ticker['price'])
        
        # Update or create coin entries
        updated_coins = set()
        for balance in balances:
            symbol = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])
            total = free + locked
            
            if total <= 0:
                continue
                
            # Get current price if available
            current_price = prices.get(symbol, 0)
            
            # Update or create coin entry
            coin = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if coin:
                # Update existing coin
                coin.amount = total
                coin.current = current_price
                coin.auto_hidden = False
                if coin.amount > 0:
                    coin.hidden = False
            else:
                # Create new coin entry
                coin = Coin(
                    user_id=user_id,
                    symbol=symbol,
                    amount=total,
                    current=current_price,
                    avg_entry=current_price if current_price > 0 else 0,
                    is_manual=False,
                    auto_hidden=False,
                    hidden=False
                )
                db.session.add(coin)
            
            updated_coins.add(symbol)
        
        # Commit all changes
        db.session.commit()
        logger.info(f"Successfully synced portfolio for user {user_id}. Updated {len(updated_coins)} coins.")
        
        # Update prices for all coins
        update_all_coin_prices_from_binance(user_id)
        
        return True, f"Successfully synced {len(updated_coins)} assets"
        
    except Exception as e:
        logger.error(f"Error syncing portfolio from Binance: {e}")
        if db.session:
            db.session.rollback()
        return False, str(e)

@app.route('/api/sync-portfolio', methods=['POST'])
@login_required
def api_sync_portfolio():
    """Manually sync portfolio data from Binance"""
    try:
        # First sync balances from Binance
        success, message = sync_portfolio_from_binance(current_user.id)
        if not success:
            return jsonify({'success': False, 'error': message}), 500
            
        # Then update all coin prices
        update_all_coin_prices_from_binance(current_user.id)
        
        logger.info(f"Manual portfolio sync completed for user {current_user.id}")
        return jsonify({
            'success': True, 
            'message': message + ' and updated all prices'
        })
    except Exception as e:
        logger.error(f"Manual portfolio sync failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/orders')
@login_required
def api_orders():
    """Get order history from Binance with robust error handling"""
    import traceback
    try:
        # Get Binance credentials from database
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        if not creds:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        # Initialize Binance client
        try:
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}\n{traceback.format_exc()}")
            return jsonify({'orders': [], 'message': f'Failed to initialize Binance client: {str(e)}'}), 502
        # Get all orders for all symbols
        orders = []
        try:
            account = client.get_account()
            traded_symbols = set()
            for balance in account['balances']:
                try:
                    asset = balance['asset']
                    # Only add valid crypto assets (skip fiat, dust, etc.)
                    if not asset or asset in ('USD', 'USDT', 'BUSD', 'USDC', 'EUR', 'GBP', 'TRY', 'AUD', 'BRL', 'RUB', 'IDRT', 'NGN', 'UAH', 'ZAR', 'DAI', 'PAX', 'TUSD', 'USDP', 'SUSD', 'GUSD', 'VAI', 'UST', 'EURS', 'BIDR', 'BVND', 'FDUSD', 'TRXUP', 'TRXDOWN'):
                        continue
                    if float(balance['free']) > 0 or float(balance['locked']) > 0:
                        symbol = asset + 'USDT'
                        traded_symbols.add(symbol)
                except Exception as e:
                    logger.warning(f"Error processing balance entry: {e}")
                    continue
            limited_symbols = list(traded_symbols)[:5]
            for symbol in limited_symbols:
                try:
                    symbol_orders = client.get_all_orders(symbol=symbol, limit=20)
                    for order in symbol_orders:
                        orders.append({
                            'order_id': order.get('orderId'),
                            'symbol': order.get('symbol'),
                            'side': order.get('side'),
                            'type': order.get('type'),
                            'quantity': order.get('origQty'),
                            'price': order.get('price'),
                            'status': order.get('status'),
                            'time': order.get('time'),
                            'executed_quantity': order.get('executedQty')
                        })
                except Exception as e:
                    if "Too much request weight" in str(e) or "rate limit" in str(e).lower():
                        logger.warning(f"Rate limit hit while fetching orders for {symbol}")
                        break
                    else:
                        logger.warning(f"Failed to get orders for {symbol}: {e}")
                    continue
            orders.sort(key=lambda x: x['time'] if x['time'] is not None else 0, reverse=True)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching Binance orders: {e}\n{traceback.format_exc()}")
            if "Too much request weight" in error_msg or "rate limit" in error_msg.lower():
                return jsonify({
                    'orders': [],
                    'message': 'Rate limit reached. Please wait a moment before refreshing orders.',
                    'rate_limited': True
                }), 429
            elif "API-key" in error_msg or "Invalid API-key" in error_msg or "permissions" in error_msg:
                return jsonify({
                    'orders': [],
                    'message': 'Invalid Binance API key or permissions. Please check your credentials.',
                    'error_code': 'invalid_binance_credentials'
                }), 400
            elif "Service unavailable" in error_msg or "restricted location" in error_msg:
                return jsonify({'orders': [], 'message': 'Binance.US service unavailable or restricted in your location.'}), 503
            else:
                return jsonify({'orders': [], 'message': f'Error fetching orders: {str(e)}'}), 502
        return jsonify({'orders': orders[:50]})
    except Exception as e:
        logger.error(f"Error in api_orders: {e}\n{traceback.format_exc()}")
        return jsonify({'orders': [], 'message': f'Internal server error: {str(e)}'}), 500


@app.route('/api/transaction-history')
@login_required  
def api_transaction_history():
    """Get transaction history from Binance"""
    try:
        # Return empty for now - can be implemented later if needed
        return jsonify({'transactions': []})
    except Exception as e:
        logger.error(f"Transaction history error: {str(e)}")
        return jsonify({'transactions': [], 'message': 'Unable to fetch transactions'})

@app.route('/api/account')
@login_required
def api_account():
    """Get Binance account information including balances"""
    import traceback
    try:
        # Get Binance credentials from database
        # Get Binance credentials from database
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'balances': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'balances': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        
        # Initialize Binance client
        try:
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}\n{traceback.format_exc()}")
            return jsonify({'balances': [], 'message': f'Failed to initialize Binance client: {str(e)}'}), 502
        
        # Fetch account info
        try:
            account_info = client.get_account()
            logger.info(f"Retrieved account info with {len(account_info.get('balances', []))} balance entries")
            return jsonify({
                'balances': account_info.get('balances', []),
                'canTrade': account_info.get('canTrade', False),
                'canWithdraw': account_info.get('canWithdraw', False),
                'canDeposit': account_info.get('canDeposit', False)
            })
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching account info: {e}\n{traceback.format_exc()}")
            
            if "Too much request weight" in error_msg or "rate limit" in error_msg.lower():
                return jsonify({
                    'balances': [],
                    'message': 'Rate limit reached. Please wait before refreshing.',
                    'rate_limited': True
                }), 429
            elif "API-key" in error_msg or "Invalid API-key" in error_msg:
                return jsonify({
                    'balances': [],
                    'message': 'Invalid Binance API credentials',
                    'error_code': 'invalid_binance_credentials'
                }), 400
            else:
                return jsonify({'balances': [], 'message': f'Error: {str(e)}'}), 502
                
    except Exception as e:
        logger.error(f"Error in api_account: {e}\n{traceback.format_exc()}")
        return jsonify({'balances': [], 'message': f'Internal error: {str(e)}'}), 500


@app.route('/api/pending-orders')
@login_required
def api_pending_orders():
    """Get all pending (open) orders from Binance.US for portfolio highlighting"""
    import traceback
    try:
        # Get Binance credentials from database
        # Get Binance credentials from database
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'pending_orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'pending_orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        
        # Initialize Binance client
        try:
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}\n{traceback.format_exc()}")
            return jsonify({'pending_orders': [], 'message': f'Failed to initialize Binance client: {str(e)}'}), 502
        
        # Fetch all open orders (no symbol filter = get all)
        try:
            open_orders = client.get_open_orders()
            
            # Parse and format orders for frontend
            pending_orders = []
            asset_visibility = {}
            for order in open_orders:
                symbol = order.get('symbol', '')
                # Extract asset from symbol (remove USDT or USD suffix)
                asset = symbol.replace('USDT', '').replace('USD', '')
                
                order_type = order.get('type', 'LIMIT')
                side = order.get('side', '')  # BUY or SELL
                price = float(order.get('price', 0))
                stop_price = float(order.get('stopPrice', 0)) if order.get('stopPrice') else None
                quantity = float(order.get('origQty', 0))
                
                # Determine order direction text
                if side == 'SELL':
                    if stop_price:
                        # Stop-limit sell: triggers when price drops below stop price
                        direction = 'drops below'
                        trigger_price = stop_price
                    else:
                        # Regular limit sell: executes when price rises to limit price
                        direction = 'rises above'
                        trigger_price = price
                else:  # BUY
                    if stop_price:
                        direction = 'rises above'
                        trigger_price = stop_price
                    else:
                        direction = 'drops below'
                        trigger_price = price
                
                # Check if this is an OCO order (has both stop and limit)
                is_oco = order.get('type') == 'STOP_LOSS_LIMIT' and order.get('stopPrice') and order.get('price')
                quote_amount = quantity * (trigger_price or price or 0.0)
                asset_upper = asset.upper()
                ref_price = trigger_price or price or 0.0
                if asset_upper:
                    asset_visibility[asset_upper] = max(asset_visibility.get(asset_upper, 0.0), ref_price)
                
                pending_orders.append({
                    'order_id': order.get('orderId'),
                    'symbol': symbol,
                    'asset': asset,
                    'side': side,
                    'type': order_type,
                    'price': price,
                    'stop_price': stop_price,
                    'quantity': quantity,
                    'status': order.get('status'),
                    'time': order.get('time'),
                    'is_oco': is_oco,
                    'direction': direction,
                    'trigger_price': trigger_price,
                    'quantity_usdt': quote_amount
                })
            
            coin_updates = False
            for asset_symbol, price_hint in asset_visibility.items():
                coin = Coin.query.filter_by(user_id=current_user.id, symbol=asset_symbol).first()
                if coin:
                    if coin.hidden:
                        coin.hidden = False
                        coin_updates = True
                    if coin.auto_hidden:
                        coin.auto_hidden = False
                        coin_updates = True
                    if not coin.force_visible:
                        coin.force_visible = True
                        coin_updates = True
                    if coin.amount is None:
                        coin.amount = 0.0
                        coin_updates = True
                    if price_hint and (not coin.current or coin.current == 0):
                        coin.current = price_hint
                        coin_updates = True
                else:
                    coin = Coin(
                        user_id=current_user.id,
                        symbol=asset_symbol,
                        amount=0.0,
                        current=price_hint or 0.0,
                        avg_entry=price_hint or 0.0,
                        initial_value=0.0,
                        purchase_date=datetime.utcnow().strftime('%Y-%m-%d'),
                        alert_enabled=True,
                        is_manual=False,
                        hidden=False,
                        auto_hidden=False,
                        force_visible=True
                    )
                    db.session.add(coin)
                    coin_updates = True

            if coin_updates:
                db.session.commit()

            logger.info(f"Retrieved {len(pending_orders)} pending orders for user {current_user.username}")
            return jsonify({'pending_orders': pending_orders})
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching pending orders: {e}\n{traceback.format_exc()}")
            
            if "Too much request weight" in error_msg or "rate limit" in error_msg.lower():
                return jsonify({
                    'pending_orders': [],
                    'message': 'Rate limit reached. Please wait before refreshing.',
                    'rate_limited': True
                }), 429
            elif "API-key" in error_msg or "Invalid API-key" in error_msg:
                return jsonify({
                    'pending_orders': [],
                    'message': 'Invalid Binance API credentials',
                    'error_code': 'invalid_binance_credentials'
                }), 400
            else:
                return jsonify({'pending_orders': [], 'message': f'Error: {str(e)}'}), 502
                
    except Exception as e:
        logger.error(f"Error in api_pending_orders: {e}\n{traceback.format_exc()}")
        return jsonify({'pending_orders': [], 'message': f'Internal error: {str(e)}'}), 500


@app.route('/api/portfolio-analysis')
@login_required
def api_portfolio_analysis():
    """Get AI-powered portfolio analysis"""
    try:
        # Get current portfolio data
        coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).all()
        
        if not coins:
            return jsonify({
                'total_value': 0,
                'holdings_count': 0,
                'diversification_score': 0,
                'risk_level': 'Low',
                'recommendations': ['No holdings found']
            })
        
        total_value = 0
        holdings = []
        
        for coin in coins:
            current_price = fetch_price(coin.symbol)
            value = coin.amount * current_price
            total_value += value
            
            holdings.append({
                'symbol': coin.symbol,
                'amount': coin.amount,
                'value': value,
                'price': current_price
            })
        
        # Calculate diversification score
        if total_value > 0:
            weights = [h['value'] / total_value for h in holdings]
            diversification_score = min(100, int(100 * (1 - sum(w**2 for w in weights))))
        else:
            diversification_score = 0
        
        # Determine risk level
        if total_value > 10000:
            risk_level = 'High'
        elif total_value > 5000:
            risk_level = 'Medium'
        else:
            risk_level = 'Low'
        
        # Generate recommendations
        recommendations = []
        if diversification_score < 50:
            recommendations.append("Consider diversifying your portfolio across more assets")
        if len(holdings) < 3:
            recommendations.append("Consider adding more assets to reduce concentration risk")
        if total_value > 10000:
            recommendations.append("Consider implementing stop-loss orders for risk management")
        
        return jsonify({
            'total_value': total_value,
            'holdings_count': len(holdings),
            'diversification_score': diversification_score,
            'risk_level': risk_level,
            'recommendations': recommendations
        })
    except Exception as e:
        logger.error(f"Portfolio analysis error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cancel-order/<order_id>', methods=['POST'])
@login_required
def api_cancel_order(order_id):
    """Cancel an existing Binance order with optional 2FA verification"""
    try:
        data = request.get_json() or {}
        symbol = (data.get('symbol') or '').upper()
        two_factor_code = (data.get('two_factor_code') or '').strip()

        if not symbol:
            return jsonify({'error': 'Symbol is required for order cancellation'}), 400

        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_secret:
            if not two_factor_code:
                return jsonify({'error': 'Two-factor code is required', 'requires_2fa': True}), 400
            try:
                import pyotp
                totp = pyotp.TOTP(settings.totp_secret)
                if not totp.verify(two_factor_code, valid_window=1):
                    return jsonify({'error': 'Invalid two-factor code', 'requires_2fa': True}), 400
            except Exception as totp_err:
                logger.error(f"2FA verification failed: {totp_err}")
                return jsonify({'error': 'Two-factor verification failed', 'requires_2fa': True}), 400

        # Use SQLAlchemy ORM instead of direct SQLite
        creds = Credential.query.filter_by(user_id=current_user.id).first()

        if not creds:
            return jsonify({
                'error': 'No Binance credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400

        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        portfolio_api_key = creds.api_key
        portfolio_api_secret = creds.api_secret

        api_key = trading_api_key or portfolio_api_key
        api_secret = trading_api_secret or portfolio_api_secret

        if not api_key or not api_secret:
            return jsonify({
                'error': 'Binance trading credentials are incomplete',
                'error_code': 'missing_trading_credentials'
            }), 400

        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )

        try:
            result = client.cancel_order(symbol=symbol, orderId=int(order_id))

            try:
                order_record = RealOrder.query.filter(
                    RealOrder.user_id == current_user.id,
                    RealOrder.binance_order_id == int(order_id)
                ).first()

                if order_record:
                    order_record.status = result.get('status', 'CANCELED')
                    order_record.canceled_at = datetime.utcnow()
                    order_record.updated_at = datetime.utcnow()
                    db.session.commit()
            except Exception as db_err:
                logger.warning(f"Failed to update local order after cancellation: {db_err}")
                db.session.rollback()

            return jsonify({
                'success': True,
                'message': 'Order cancelled successfully',
                'order_id': result.get('orderId'),
                'symbol': result.get('symbol'),
                'status': result.get('status')
            })
        except Exception as e:
            logger.error(f"Failed to cancel Binance order {order_id}: {e}")
            return jsonify({'error': f'Failed to cancel order: {str(e)}'}), 400

    except Exception as e:
        logger.error(f"Cancel order error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/order-status/<order_id>')
@login_required
def api_order_status(order_id):
    """Get detailed status of a specific Binance order"""
    try:
        # Get Binance credentials
        # Get Binance credentials
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'error': 'No Binance credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({
                'error': 'No Binance credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol from query parameters
        symbol = request.args.get('symbol')
        if not symbol:
            return jsonify({'error': 'Symbol parameter is required'}), 400
        
        # Get order status
        try:
            order = client.get_order(symbol=symbol, orderId=int(order_id))
            return jsonify({
                'order_id': order.get('orderId'),
                'symbol': order.get('symbol'),
                'status': order.get('status'),
                'side': order.get('side'),
                'type': order.get('type'),
                'quantity': order.get('origQty'),
                'executed_quantity': order.get('executedQty'),
                'price': order.get('price'),
                'time': order.get('time')
            })
        except Exception as e:
            logger.error(f"Failed to get Binance order status {order_id}: {e}")
            return jsonify({'error': f'Failed to get order status: {str(e)}'}), 400
            
    except Exception as e:
        logger.error(f"Order status error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ========================================
# TRADING SYSTEM ENDPOINTS (Binance.US)
# ========================================

@app.route('/api/trading/settings', methods=['GET'])
@login_required
def get_trading_settings():
    """Get trading settings for current user"""
    try:
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if not settings:
            # Create default settings
            settings = TradingSettings(
                user_id=current_user.id,
                test_mode_enabled=True,
                max_order_size_usd=1000.0,
                require_2fa=False
            )
            db.session.add(settings)
            db.session.commit()
        
        return jsonify({
            'success': True,
            'settings': settings.to_dict()
        })
    except Exception as e:
        logger.error(f"Error fetching trading settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/settings', methods=['POST'])
@login_required
def update_trading_settings():
    """Update trading settings for current user"""
    try:
        data = request.get_json()
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if not settings:
            settings = TradingSettings(user_id=current_user.id)
            db.session.add(settings)
        
        # Update settings
        if 'test_mode_enabled' in data:
            settings.test_mode_enabled = bool(data['test_mode_enabled'])
        if 'max_order_size_usd' in data:
            settings.max_order_size_usd = float(data['max_order_size_usd'])
        if 'daily_loss_limit_usd' in data:
            settings.daily_loss_limit_usd = float(data['daily_loss_limit_usd'])
        if 'require_2fa' in data:
            settings.require_2fa = bool(data['require_2fa'])
        
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Updated trading settings for user {current_user.id}")
        return jsonify({
            'success': True,
            'settings': settings.to_dict()
        })
    except Exception as e:
        logger.error(f"Error updating trading settings: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/order-types', methods=['GET'])
def get_trading_order_types():
    """Get canonical list of supported Binance.US spot order types and TimeInForce options"""
    try:
        # Canonical Binance.US spot order types (authoritative source)
        order_types = [
            {
                'value': 'MARKET',
                'label': 'Market Order',
                'description': 'Execute immediately at current market price',
                'requires_price': False,
                'requires_stop_price': False,
                'requires_time_in_force': False
            },
            {
                'value': 'LIMIT',
                'label': 'Limit Order',
                'description': 'Execute at specified price or better',
                'requires_price': True,
                'requires_stop_price': False,
                'requires_time_in_force': True
            },
            {
                'value': 'STOP_LOSS',
                'label': 'Stop Loss',
                'description': 'Market order triggered when price reaches stop price',
                'requires_price': False,
                'requires_stop_price': True,
                'requires_time_in_force': False
            },
            {
                'value': 'STOP_LOSS_LIMIT',
                'label': 'Stop Loss Limit',
                'description': 'Limit order triggered at stop price',
                'requires_price': True,
                'requires_stop_price': True,
                'requires_time_in_force': True
            },
            {
                'value': 'TAKE_PROFIT',
                'label': 'Take Profit',
                'description': 'Market order to secure profits at target price',
                'requires_price': False,
                'requires_stop_price': True,
                'requires_time_in_force': False
            },
            {
                'value': 'TAKE_PROFIT_LIMIT',
                'label': 'Take Profit Limit',
                'description': 'Limit order to secure profits',
                'requires_price': True,
                'requires_stop_price': True,
                'requires_time_in_force': True
            },
            {
                'value': 'LIMIT_MAKER',
                'label': 'Limit Maker',
                'description': 'Post-only limit order (maker fee only)',
                'requires_price': True,
                'requires_stop_price': False,
                'requires_time_in_force': True
            },
            {
                'value': 'OCO',
                'label': 'OCO (One-Cancels-Other)',
                'description': 'Combine limit and stop-loss orders - when one executes, the other cancels',
                'requires_price': True,
                'requires_stop_price': True,
                'requires_time_in_force': False,
                'requires_stop_limit_price': True
            }
        ]
        
        # TimeInForce options for limit orders
        time_in_force_options = [
            {
                'value': 'GTC',
                'label': 'GTC - Good Till Cancel',
                'description': 'Order remains active until filled or cancelled'
            },
            {
                'value': 'IOC',
                'label': 'IOC - Immediate or Cancel',
                'description': 'Immediately execute as much as possible, cancel remainder'
            },
            {
                'value': 'FOK',
                'label': 'FOK - Fill or Kill',
                'description': 'Must fill entire order immediately or cancel'
            }
        ]
        
        return jsonify({
            'success': True,
            'order_types': order_types,
            'time_in_force_options': time_in_force_options
        })
        
    except Exception as e:
        logger.error(f"Error fetching order types: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# In-memory cache for klines data (5-minute TTL)
_KLINES_CACHE = {}
_KLINES_CACHE_TTL = 300  # 5 minutes

@app.route('/api/trading/klines/<symbol>', methods=['GET'])
def get_trading_klines(symbol):
    """
    Proxy endpoint for Binance.US klines/candlestick data with caching.
    Query params: interval (default: 1d), limit (default: 1000)
    """
    try:
        symbol = symbol.upper()
        interval = request.args.get('interval', '1d')  # 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M
        limit = int(request.args.get('limit', 1000))  # Max 1000 per Binance API
        
        # Check cache
        cache_key = f"{symbol}_{interval}_{limit}"
        now = time.time()
        if cache_key in _KLINES_CACHE:
            cached_data, cached_time = _KLINES_CACHE[cache_key]
            if now - cached_time < _KLINES_CACHE_TTL:
                logger.debug(f"Returning cached klines for {cache_key}")
                return jsonify({
                    'success': True,
                    'symbol': symbol,
                    'interval': interval,
                    'klines': cached_data,
                    'cached': True
                })
        
        # Get Binance.US credentials (use portfolio API keys for read-only price data)
        creds = Credential.query.filter(
            Credential._api_key.isnot(None), 
            Credential._api_secret.isnot(None)
        ).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )
        
        # Fetch klines from Binance.US
        # Returns: [[timestamp, open, high, low, close, volume, close_time, quote_asset_volume, trades, ...], ...]
        try:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        except Exception as api_err:
            err_msg = str(api_err)
            logger.error(f"Failed to fetch klines for {symbol}: {err_msg}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'Failed to fetch market data: {err_msg}'}), 502
        
        # Transform to frontend-friendly format
        formatted_klines = []
        for k in klines:
            formatted_klines.append({
                'time': int(k[0]) / 1000,  # Convert to seconds for Lightweight Charts
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5])
            })
        
        # Cache the result
        _KLINES_CACHE[cache_key] = (formatted_klines, now)
        
        logger.info(f"Fetched {len(formatted_klines)} klines for {symbol} ({interval})")
        return jsonify({
            'success': True,
            'symbol': symbol,
            'interval': interval,
            'klines': formatted_klines,
            'cached': False
        })
        
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error fetching klines for {symbol}: {err_msg}")
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500


@app.route('/api/trading/transactions/<symbol>', methods=['GET'])
@login_required
def get_trading_transactions(symbol):
    """
    Get user's buy/sell transactions for a specific symbol to display on chart.
    Returns list of transactions with timestamps for chart markers.
    """
    try:
        base_asset = symbol.replace('USDT', '').replace('USD', '').upper()
        transactions = []
        from trading_models import AllActivity
        
        # Query all_activities using ORM
        rows = AllActivity.query.filter(
            AllActivity.user_id == current_user.id,
            AllActivity.asset == base_asset,
            AllActivity.type.in_(['BUY', 'SELL']),
            AllActivity.exchange == 'binance'
        ).order_by(AllActivity.date.asc()).all()

        for row in rows:
            try:
                date_text = row.date
                # Try common formats
                if isinstance(date_text, datetime):
                    date_obj = date_text
                else:
                    try:
                        date_obj = datetime.strptime(date_text, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        # Fallback: attempt ISO format
                        try:
                            date_obj = datetime.fromisoformat(date_text.replace('Z', '+00:00'))
                        except Exception:
                            logger.warning(f"Unrecognized date format in all_activities: {date_text}")
                            continue
                
                timestamp = int(date_obj.timestamp())

                price_value = None
                if row.avg_entry is not None:
                    price_value = float(row.avg_entry)
                elif row.price_sold_at is not None:
                    price_value = float(row.price_sold_at)
                else:
                    # Skip if no price available
                    continue

                transactions.append({
                    'time': timestamp,
                    'type': row.type,
                    'amount': abs(float(row.amount)) if row.amount is not None else 0.0,
                    'price': price_value
                })
            except Exception as parse_err:
                logger.warning(f"Failed to parse transaction row: {parse_err}")
                continue

        logger.info(f"Retrieved {len(transactions)} transactions for {base_asset}")
        return jsonify({
            'success': True,
            'symbol': base_asset,
            'transactions': transactions
        })
        
    except Exception as e:
        logger.error(f"Error fetching transactions for {symbol}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/symbol-info/<symbol>', methods=['GET'])
@login_required
def get_symbol_info(symbol):
    """Get trading rules and filters for a specific symbol"""
    try:
        symbol = symbol.upper()
        
        # Get Binance.US Trading credentials
        # Get Binance.US credentials
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        trading_api_key = decrypt_secret(creds.trading_api_key)
        trading_api_secret = decrypt_secret(creds.trading_api_secret)
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Symbol {symbol} not found or not available for trading.'}), 404
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'filters': filters
        })
        
    except Exception as e:
        logger.error(f"Error getting symbol info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def get_symbol_filters(client, symbol):
    """Get trading filters for a specific symbol from Binance.US"""
    try:
        exchange_info = client.get_exchange_info()
        for sym in exchange_info['symbols']:
            if sym['symbol'] == symbol:
                filters = {}
                for f in sym['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        filters['minQty'] = float(f['minQty'])
                        filters['maxQty'] = float(f['maxQty'])
                        filters['stepSize'] = float(f['stepSize'])
                    elif f['filterType'] == 'PRICE_FILTER':
                        filters['minPrice'] = float(f['minPrice'])
                        filters['maxPrice'] = float(f['maxPrice'])
                        filters['tickSize'] = float(f['tickSize'])
                    elif f['filterType'] == 'MIN_NOTIONAL':
                        filters['minNotional'] = float(f.get('minNotional', f.get('notional', 0)))
                    elif f['filterType'] == 'NOTIONAL':
                        filters['minNotional'] = float(f.get('minNotional', 0))
                filters['baseAssetPrecision'] = sym['baseAssetPrecision']
                filters['quotePrecision'] = sym['quotePrecision']
                return filters
        return None
    except Exception as e:
        logger.error(f"Error getting symbol filters: {e}")
        return None


# Lightweight in-memory cache for exchange info / trade fees to reduce weight
_EXCHANGE_INFO_CACHE = {
    'timestamp': None,
    'exchange_info': None,
    'fees': {}
}

def get_cached_exchange_info(client, force_refresh=False):
    """Return exchange info and cache it for short periods to reduce request weight."""
    import time
    now = time.time()
    # Refresh every 60 seconds by default
    if force_refresh or not _EXCHANGE_INFO_CACHE['timestamp'] or (now - (_EXCHANGE_INFO_CACHE['timestamp'] or 0)) > 60:
        try:
            info = client.get_exchange_info()
            _EXCHANGE_INFO_CACHE['exchange_info'] = info
            _EXCHANGE_INFO_CACHE['timestamp'] = now
            return info
        except Exception as e:
            logger.error(f"Failed to refresh exchange info: {e}")
            return _EXCHANGE_INFO_CACHE.get('exchange_info')
    return _EXCHANGE_INFO_CACHE.get('exchange_info')


def get_trade_fee_for_symbol(client, symbol):
    """Retrieve actual maker/taker fee for a symbol using Binance API (get_trade_fee).
    Cache results per-symbol briefly to avoid weight spikes."""
    try:
        # Use cached value if present and recent
        import time
        if symbol in _EXCHANGE_INFO_CACHE['fees']:
            fee_entry = _EXCHANGE_INFO_CACHE['fees'][symbol]
            if time.time() - fee_entry.get('ts', 0) < 60:
                return fee_entry['fee']

        # get_trade_fee returns a list with fee info per symbol
        fee_info = client.get_trade_fee(symbol=symbol)
        # Expected structure: [{'symbol': 'BTCUSDT', 'maker': '0.001', 'taker': '0.001'}]
        if isinstance(fee_info, list) and len(fee_info) > 0:
            maker = float(fee_info[0].get('maker', 0.0))
            taker = float(fee_info[0].get('taker', 0.0))
            fee = {'maker': maker, 'taker': taker}
            _EXCHANGE_INFO_CACHE['fees'][symbol] = {'fee': fee, 'ts': time.time()}
            return fee
        # Fallback: return None
        return None
    except Exception as e:
        logger.error(f"Failed to get trade fee for {symbol}: {e}")
        return None


def format_quantity(quantity, step_size):
    """Format quantity to match step size requirement"""
    from decimal import Decimal, ROUND_DOWN
    
    # Convert to Decimal for precise arithmetic
    qty = Decimal(str(quantity))
    step = Decimal(str(step_size))
    
    # Calculate precision from step size
    step_str = f"{step:.10f}".rstrip('0')
    precision = len(step_str.split('.')[-1]) if '.' in step_str else 0
    
    # Round down to step size
    qty = (qty / step).quantize(Decimal('1'), rounding=ROUND_DOWN) * step
    
    # Format with correct precision
    if precision == 0:
        return int(qty)
    else:
        return float(qty.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN))


def format_price(price, tick_size):
    """Format price to match tick size requirement"""
    from decimal import Decimal, ROUND_DOWN
    
    if price <= 0:
        return 0.0
    
    # Convert to Decimal for precise arithmetic
    prc = Decimal(str(price))
    tick = Decimal(str(tick_size))
    
    # Calculate precision from tick size
    tick_str = f"{tick:.10f}".rstrip('0')
    precision = len(tick_str.split('.')[-1]) if '.' in tick_str else 0
    
    # Round down to tick size
    prc = (prc / tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick
    
    # Format with correct precision
    if precision == 0:
        return int(prc)
    else:
        return float(prc.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN))


@app.route('/api/trading/test-order', methods=['POST'])
@login_required
def place_test_order():
    """Place a test order (validates with Binance.US but doesn't execute)"""
    import traceback
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'side', 'type', 'quantity']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        base_asset = symbol.replace('USDT', '').replace('USD', '')
        side = data['side'].upper()  # BUY or SELL
        order_type = data['type'].upper()  # MARKET, LIMIT, etc.
        quantity_input = _coerce_float(data.get('quantity'))
        quote_amount = _coerce_float(
            data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount')
        )
        price = _coerce_float(data.get('price'), 0.0) or 0.0
        quantity = quantity_input or 0.0
        
        # Validate order type
        valid_order_types = ['MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']
        if order_type not in valid_order_types:
            return jsonify({'success': False, 'error': f'Invalid order type. Must be one of: {", ".join(valid_order_types)}'}), 400
        
        # Check if 2FA is required
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_secret:
            # Verify 2FA token
            twofa_token = data.get('twofa_token')
            if not twofa_token:
                return jsonify({'success': False, 'error': '2FA verification required', 'requires_2fa': True}), 403
            
            # Check token validity
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data or token_data['user_id'] != current_user.id:
                return jsonify({'success': False, 'error': '2FA verification invalid or expired', 'requires_2fa': True}), 403
            
            # Check if token is not older than 2 minutes
            if (datetime.utcnow().timestamp() - token_data['timestamp']) > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({'success': False, 'error': '2FA verification expired. Please verify again.', 'requires_2fa': True}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get Binance.US Trading credentials
        # Get Binance.US credentials
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        trading_api_key = decrypt_secret(creds.trading_api_key)
        trading_api_secret = decrypt_secret(creds.trading_api_secret)
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters and format values according to Binance.US rules
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading rules for {symbol}. Please check the symbol is valid.'}), 400

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
        except Exception as price_err:
            logger.error(f"Failed to fetch current price for {symbol}: {price_err}")
            current_price = 0.0

        quantity = quantity_input
        if not quantity or quantity <= 0:
            reference_price = price if price > 0 else current_price
            if (not reference_price or reference_price <= 0) and quote_amount and quote_amount > 0:
                try:
                    ticker = client.get_symbol_ticker(symbol=symbol)
                    reference_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
                    current_price = reference_price
                except Exception as refill_err:
                    logger.error(f"Failed to refresh price for {symbol}: {refill_err}")
                    reference_price = None
            if quote_amount and quote_amount > 0 and reference_price and reference_price > 0:
                quantity = quote_amount / reference_price
            else:
                return jsonify({
                    'success': False,
                    'error': 'Unable to determine order quantity. Please enter a value or wait for prices to refresh.'
                }), 400
        if quantity <= 0:
            return jsonify({'success': False, 'error': 'Quantity must be greater than zero.'}), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        # Validate quantity is within bounds
        if formatted_quantity < filters['minQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too small. Minimum quantity for {symbol} is {filters["minQty"]}. You entered {quantity} which rounds to {formatted_quantity}.'
            }), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too large. Maximum quantity for {symbol} is {filters["maxQty"]}. You entered {quantity}.'
            }), 400
        
        # Format price according to PRICE_FILTER
        if price > 0:
            formatted_price = format_price(price, filters['tickSize'])
            if formatted_price < filters['minPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too low. Minimum price for {symbol} is {filters["minPrice"]}. You entered {price}.'
                }), 400
            if formatted_price > filters['maxPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too high. Maximum price for {symbol} is {filters["maxPrice"]}. You entered {price}.'
                }), 400
        else:
            formatted_price = 0.0
        
        # Validate order using Binance.US test endpoint
        try:
            test_params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': formatted_quantity
            }
            
            # Add price for LIMIT orders
            if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
                if formatted_price <= 0:
                    return jsonify({'success': False, 'error': 'Price is required for LIMIT orders'}), 400
                
                # Check MIN_NOTIONAL (minimum order value)
                order_value = formatted_quantity * formatted_price
                if 'minNotional' in filters and order_value < filters['minNotional']:
                    return jsonify({
                        'success': False, 
                        'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is ${order_value:.2f}. Please increase quantity or price.'
                    }), 400
                
                test_params['price'] = formatted_price
                test_params['timeInForce'] = 'GTC'  # Good Till Cancel
            
            # Add stopPrice for STOP orders
            if order_type in ['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT']:
                stop_price_str = data.get('stopPrice', '0')
                stop_price = float(stop_price_str) if stop_price_str and stop_price_str.strip() else 0.0
                if stop_price <= 0:
                    return jsonify({'success': False, 'error': f'stopPrice is required for {order_type} orders'}), 400
                
                # Format stop price
                formatted_stop_price = format_price(stop_price, filters['tickSize'])
                test_params['stopPrice'] = formatted_stop_price

                if order_type in ['STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT']:
                    if formatted_price <= 0:
                        return jsonify({'success': False, 'error': 'Limit price must be greater than 0 for stop-limit orders'}), 400
                    if side == 'BUY' and formatted_price < formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For buy stop-limit orders, limit price must be greater than or equal to stop price to avoid immediate execution.'}), 400
                    if side == 'SELL' and formatted_price > formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For sell stop-limit orders, limit price must be less than or equal to stop price to avoid immediate execution.'}), 400
            
            # For MARKET orders, check MIN_NOTIONAL using current price
            if order_type == 'MARKET' and 'minNotional' in filters:
                try:
                    ticker = client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    order_value = formatted_quantity * current_price
                    if order_value < filters['minNotional']:
                        return jsonify({
                            'success': False, 
                            'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is approximately ${order_value:.2f} at current market price. Please increase quantity.'
                        }), 400
                except Exception as price_error:
                    logger.warning(f"Could not check MIN_NOTIONAL for MARKET order: {price_error}")
            
            # Validate with Binance test endpoint
            client.create_test_order(**test_params)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Binance order validation failed: {e}\n{traceback.format_exc()}")
            
            # Parse Binance error for more specific messaging
            if 'LOT_SIZE' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid quantity. The quantity has too many decimal places or doesn\'t meet the step size requirement for {symbol}. Please adjust your order quantity.'
                }), 400
            elif 'MIN_NOTIONAL' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Order value too small. The total order value (quantity × price) is below the minimum required for {symbol}. Please increase your quantity or choose a different trading pair.'
                }), 400
            elif 'PRICE_FILTER' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid price. The price has too many decimal places or is outside the allowed range for {symbol}. Please adjust your price.'
                }), 400
            elif 'INSUFFICIENT_BALANCE' in error_msg or 'insufficient balance' in error_msg.lower():
                return jsonify({
                    'success': False, 
                    'error': f'Insufficient balance. You don\'t have enough funds to place this order. Please reduce the quantity or add more funds.'
                }), 400
            elif 'Invalid API-key' in error_msg or 'API-key' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': 'API key invalid or expired. Please check your Binance.US API credentials in Settings and ensure they have trading permissions enabled.'
                }), 401
            elif 'IP' in error_msg and 'permissions' in error_msg.lower():
                return jsonify({
                    'success': False, 
                    'error': 'IP not whitelisted. Your current IP address is not authorized for API trading. Please add your IP to the whitelist in your Binance.US API settings.'
                }), 403
            else:
                # Generic error with full details
                return jsonify({
                    'success': False, 
                    'error': f'Order validation failed: {error_msg}'
                }), 400
        
        # Get current market price for simulation
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            current_price = formatted_price if formatted_price > 0 else 0
        
        # Calculate fill price for simulation
        if order_type == 'MARKET':
            fill_price = current_price
        elif order_type in ['LIMIT', 'LIMIT_MAKER']:
            fill_price = formatted_price
        else:
            # For stop orders, use formatted stop price
            if 'stopPrice' in test_params:
                fill_price = test_params['stopPrice']
            else:
                fill_price = current_price
        
        # Handle stopPrice for creating order record
        stop_price_for_record = None
        if 'stopPrice' in test_params:
            stop_price_for_record = test_params['stopPrice']
        
        # Get API-provided fee rates for accurate simulation
        fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
        # Use taker fee for simulation (most conservative)
        fee_rate = fee_info.get('taker', 0.001)
        simulated_commission = formatted_quantity * fill_price * fee_rate
        
        # Create test order record with formatted values
        test_order = TestOrder(
            user_id=current_user.id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=formatted_quantity,  # Use formatted quantity
            price=formatted_price if formatted_price > 0 else None,  # Use formatted price
            stop_price=stop_price_for_record,
            time_in_force='GTC' if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER'] else None,
            status='FILLED',  # Simulate immediate fill for test orders
            simulated_fill_price=fill_price,
            simulated_fill_time=datetime.utcnow(),
            created_at=datetime.utcnow(),
            notes=f'Simulated commission: ${simulated_commission:.4f} ({fee_rate*100:.2f}% API rate)'
        )
        
        db.session.add(test_order)
        
        # Update test portfolio with formatted quantity and API-provided fee rate
        update_test_portfolio(current_user.id, symbol, side, formatted_quantity, fill_price, fee_rate)
        
        db.session.commit()
        
        logger.info(f"Test order placed successfully for user {current_user.id}: {symbol} {side} {formatted_quantity} @ {fill_price}")
        
        return jsonify({
            'success': True,
            'order': test_order.to_dict(),
            'message': f'Test order validated and simulated successfully. Quantity adjusted from {quantity} to {formatted_quantity} to match trading rules.',
            'formatted_values': {
                'quantity': formatted_quantity,
                'price': formatted_price,
                'original_quantity': quantity,
                'original_price': price
            }
        })
        
    except Exception as e:
        logger.error(f"Error placing test order: {e}\n{traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def update_test_portfolio(user_id, symbol, side, quantity, price, fee_rate=None):
    """Update test portfolio after simulated order fill - updates both base asset and USDT"""
    try:
        # Extract base asset from symbol (e.g., BTC from BTCUSDT)
        base_asset = symbol.replace('USDT', '').replace('USD', '')
        
        # Use provided fee_rate or fallback to 0.001 (0.1% default)
        if fee_rate is None:
            fee_rate = 0.001
        
        # Calculate total cost including commission (Binance fee from API)
        total_trade_value = quantity * price
        commission = total_trade_value * fee_rate
        
        # Get or create portfolio entry for base asset
        portfolio = TestPortfolio.query.filter_by(
            user_id=user_id,
            symbol=base_asset
        ).first()
        
        if not portfolio:
            portfolio = TestPortfolio(
                user_id=user_id,
                symbol=base_asset,
                quantity=0.0,
                avg_entry_price=0.0,
                total_cost_basis=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                last_updated=datetime.utcnow()
            )
            db.session.add(portfolio)
        
        # Get or create USDT portfolio entry
        usdt_portfolio = TestPortfolio.query.filter_by(
            user_id=user_id,
            symbol='USDT'
        ).first()
        
        if not usdt_portfolio:
            # Initialize with starting balance if first time
            usdt_portfolio = TestPortfolio(
                user_id=user_id,
                symbol='USDT',
                quantity=10000.0,  # Start with $10,000 USDT for testing
                avg_entry_price=1.0,
                total_cost_basis=10000.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                last_updated=datetime.utcnow()
            )
            db.session.add(usdt_portfolio)
            logger.info(f"Initialized USDT balance for user {user_id}: $10,000")
        
        # Update quantity based on side
        if side == 'BUY':
            # Deduct USDT (cost + commission)
            total_cost = total_trade_value + commission
            usdt_portfolio.quantity -= total_cost
            
            # Add base asset
            old_cost = portfolio.quantity * portfolio.avg_entry_price
            new_cost = total_trade_value + commission  # Include commission in cost basis
            total_cost_sum = old_cost + new_cost
            
            portfolio.quantity += quantity
            portfolio.avg_entry_price = total_cost_sum / portfolio.quantity if portfolio.quantity > 0 else price
            portfolio.total_cost_basis = total_cost_sum
            
            logger.info(f"BUY: Added {quantity} {base_asset} @ ${price:.2f}, Cost: ${total_cost:.2f} (inc. ${commission:.2f} commission)")
            logger.info(f"USDT balance: ${usdt_portfolio.quantity:.2f}")
            
        elif side == 'SELL':
            # Calculate realized P&L before selling
            if portfolio.quantity > 0:
                sell_cost_basis = portfolio.avg_entry_price * quantity
                sell_proceeds = total_trade_value - commission  # Subtract commission from proceeds
                realized_gain = sell_proceeds - sell_cost_basis
                portfolio.realized_pnl += realized_gain
            
            # Remove base asset
            portfolio.quantity -= quantity
            portfolio.total_cost_basis = portfolio.quantity * portfolio.avg_entry_price
            
            # Add USDT (proceeds - commission)
            usdt_received = total_trade_value - commission
            usdt_portfolio.quantity += usdt_received
            
            # If quantity goes to zero or negative, reset
            if portfolio.quantity <= 0:
                portfolio.quantity = 0.0
                portfolio.avg_entry_price = 0.0
                portfolio.total_cost_basis = 0.0
            
            logger.info(f"SELL: Removed {quantity} {base_asset} @ ${price:.2f}, Proceeds: ${usdt_received:.2f} (after ${commission:.2f} commission)")
            logger.info(f"USDT balance: ${usdt_portfolio.quantity:.2f}")
        
        portfolio.last_updated = datetime.utcnow()
        usdt_portfolio.last_updated = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"Updated test portfolio: {base_asset} - Qty: {portfolio.quantity}, Avg Price: ${portfolio.avg_entry_price:.2f}")
        
    except Exception as e:
        logger.error(f"Error updating test portfolio: {e}")
        db.session.rollback()
        raise


def ensure_auto_watchlist_entry(user_id, symbol, trade_price):
    """Ensure a watchlist entry exists for auto-hidden coins with alerts configured."""
    try:
        lower_alert = round(trade_price * 0.9, 6)
        upper_alert = round(trade_price * 1.1, 6)
    except (TypeError, ValueError):
        lower_alert = None
        upper_alert = None

    existing = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol.upper()).first()
    if existing:
        if existing.action and existing.action != 'AutoWatch':
            # Respect manually managed watchlist entries
            return
        existing.down_alert = lower_alert
        existing.up_alert = upper_alert
        existing.alert_enabled = True
        existing.hidden = False
        existing.action = 'AutoWatch'
        existing.current_price = trade_price
    else:
        watch = WatchlistCoin(
            user_id=user_id,
            symbol=symbol.upper(),
            down_alert=lower_alert,
            up_alert=upper_alert,
            alert_enabled=True,
            note='Auto-added after position closed',
            favorite=False,
            hidden=False,
            action='AutoWatch',
            current_price=trade_price,
            sentiment='Watch'
        )
        db.session.add(watch)


def remove_auto_watchlist_entry(user_id, symbol):
    """Remove auto-managed watchlist entries once a position is re-established."""
    watch = WatchlistCoin.query.filter_by(
        user_id=user_id,
        symbol=symbol.upper(),
        action='AutoWatch'
    ).first()
    if watch:
        db.session.delete(watch)


def update_portfolio_from_real_order(user_id, symbol, side, quantity, price, commission, commission_asset, order_id):
    """Update coins table and all_activities (tax report) after real order fills"""
    try:
        # Extract base asset from symbol (e.g., BTC from BTCUSDT)
        base_asset = symbol.replace('USDT', '').replace('USD', '')
        
        # Convert commission to USD if needed
        commission_usd = commission
        if commission_asset != 'USDT' and commission_asset != 'USD':
            # Commission was paid in crypto, need to convert to USD
            commission_usd = commission * price
        
        # 1. Update coins table
        coin = Coin.query.filter_by(user_id=user_id, symbol=base_asset).first()
        previous_avg_entry = coin.avg_entry if coin else 0.0
        
        if side == 'BUY':
            if not coin:
                # Create new coin entry
                coin = Coin(
                    user_id=user_id,
                    symbol=base_asset,
                    amount=quantity,
                    current=price,
                    avg_entry=price,
                    initial_value=quantity * price,
                    purchase_date=datetime.now().strftime('%Y-%m-%d'),
                    alert_enabled=True,
                    is_manual=False,
                    hidden=False,
                    auto_hidden=False,
                    force_visible=False
                )
                db.session.add(coin)
                logger.info(f"Created new coin entry for {base_asset}: {quantity} @ ${price}")
            else:
                # Update existing coin
                old_total_cost = coin.amount * coin.avg_entry
                new_cost = quantity * price
                new_total = old_total_cost + new_cost
                
                coin.amount += quantity
                coin.avg_entry = new_total / coin.amount if coin.amount > 0 else price
                coin.current = price
                logger.info(f"Updated coin {base_asset}: New amount={coin.amount}, New avg_entry=${coin.avg_entry:.2f}")
            
            if coin:
                total_value = (coin.amount or 0) * price
                if total_value >= 1.0:
                    coin.hidden = False
                    coin.auto_hidden = False
                    coin.force_visible = False
                remove_auto_watchlist_entry(user_id, base_asset)
        
        elif side == 'SELL':
            if coin:
                coin.amount -= quantity
                coin.current = price
                if coin.amount <= 0:
                    coin.amount = 0
                logger.info(f"Updated coin {base_asset} after sell: New amount={coin.amount}")
                remaining_value = (coin.amount or 0) * price
                if remaining_value < 1.0:
                    coin.hidden = True
                    coin.auto_hidden = True
                    coin.force_visible = False
                    coin.alert_enabled = False
                    ensure_auto_watchlist_entry(user_id, base_asset, price)
                else:
                    remove_auto_watchlist_entry(user_id, base_asset)
            else:
                ensure_auto_watchlist_entry(user_id, base_asset, price)

        # Recalculate average entry using full trade history (resets when under $1)
        if coin:
            recalculated_avg, recalculated_cost, recalculated_amount = calculate_avg_entry_fifo(
                user_id,
                base_asset,
                target_amount=coin.amount
            )
            if recalculated_cost >= 1.0 and recalculated_amount > 0:
                coin.avg_entry = recalculated_avg
            else:
                coin.avg_entry = 0.0
            logger.debug(
                f"[AVG_ENTRY] {base_asset} -> amount={recalculated_amount:.8f}, "
                f"cost=${recalculated_cost:.2f}, avg=${coin.avg_entry:.6f}"
            )
        
        # 2. Add transaction to all_activities (for tax reporting)
        # Use exchange_logs database (use the configured engines map)
        activity_db = db.engine

        transaction_date = datetime.utcnow()
        txid = f"binance_{order_id}_{symbol}"

        if side == 'BUY':
            # For buys: cost_basis includes fees, proceeds is NULL
            cost_basis = (quantity * price) + commission_usd
            proceeds = None
            amount_value = quantity  # Positive for buys
        else:  # SELL
            # For sells: proceeds excludes fees, cost_basis based on pre-trade average
            proceeds = (quantity * price) - commission_usd
            reference_avg = previous_avg_entry if previous_avg_entry else (coin.avg_entry if coin else 0.0)
            cost_basis = reference_avg * quantity if reference_avg else (quantity * price)
            amount_value = -quantity  # Negative for sells

        # Insert into all_activities using SQLAlchemy ORM
        description = f"{side} {quantity} {base_asset} @ ${price:.2f}"
        details = f"Order ID: {order_id}, Commission: {commission} {commission_asset}"
        
        new_activity = AllActivity(
            date=transaction_date,
            type=side,
            asset=base_asset,
            amount=amount_value,
            proceeds=proceeds,
            cost_basis=cost_basis,
            fee=commission_usd,
            description=description,
            txid=txid,
            status='completed',
            details=details,
            user_id=user_id,
            avg_entry=price,
            price_sold_at=price,
            exchange='binance'
        )
        db.session.add(new_activity)
        db.session.commit()

        logger.info(f"Added {side} transaction to all_activities: {description}")
        
    except Exception as e:
        logger.error(f"Error updating portfolio from real order: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


@app.route('/api/trading/orders', methods=['GET'])
@login_required
def get_trading_orders():
    """Get order history (test or real based on settings)"""
    try:
        # Check if user is in test mode
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        test_mode = settings.test_mode_enabled if settings else True
        
        # Get filter parameters
        limit = int(request.args.get('limit', 50))
        symbol = request.args.get('symbol')
        
        if test_mode:
            # Get test orders
            query = TestOrder.query.filter_by(user_id=current_user.id)
            if symbol:
                query = query.filter_by(symbol=symbol.upper())
            orders = query.order_by(TestOrder.created_at.desc()).limit(limit).all()
        else:
            # Get real orders
            query = RealOrder.query.filter_by(user_id=current_user.id)
            if symbol:
                query = query.filter_by(symbol=symbol.upper())
            orders = query.order_by(RealOrder.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'test_mode': test_mode,
            'orders': [order.to_dict() for order in orders]
        })
        
    except Exception as e:
        logger.error(f"Error fetching trading orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/real-orders', methods=['GET'])
@login_required
def get_real_orders_only():
    """Get REAL order history only (never returns test orders)"""
    try:
        # Get filter parameters
        limit_param = request.args.get('limit', '50')
        unlimited = False
        try:
            if isinstance(limit_param, str) and limit_param.lower() in ('all', '*', 'infinite'):
                unlimited = True
                limit = 50
            else:
                limit_value = int(limit_param)
                if limit_value <= 0:
                    unlimited = True
                    limit = 50
                else:
                    limit = limit_value
        except (TypeError, ValueError):
            limit = 50
        symbol = request.args.get('symbol')
        symbol_filter = symbol.upper() if symbol else None

        combined_orders = {}
        symbols_to_check = set()
        activity_records = []

        def normalize_timestamp(value):
            if not value:
                return None
            try:
                v = str(value)
                if v.endswith('Z'):
                    v = v.replace('Z', '+00:00')
                return datetime.fromisoformat(v).isoformat()
            except Exception:
                try:
                    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").isoformat()
                except Exception:
                    return str(value)

        def add_order(unique_key, payload):
            if not payload:
                return
            created_at = payload.get('created_at')
            combined_orders[unique_key] = payload if unique_key not in combined_orders else (
                payload if created_at and created_at > combined_orders[unique_key].get('created_at', '')
                else combined_orders[unique_key]
            )

        # Include locally stored real orders (placed via the app)
        query = RealOrder.query.filter_by(user_id=current_user.id)
        if symbol_filter:
            query = query.filter_by(symbol=symbol_filter)
        query = query.order_by(RealOrder.created_at.desc())
        if not unlimited:
            query = query.limit(limit)
        stored_orders = query.all()

        for order in stored_orders:
            key = f"binance-{order.symbol}-{order.binance_order_id}" if order.binance_order_id else f"real-{order.id}"
            order_dict = {
                'id': order.binance_order_id or f"real-{order.id}",
                'symbol': order.symbol,
                'side': order.side,
                'order_type': order.type,
                'quantity': float(order.quantity or 0.0),
                'price': float(order.price or 0.0),
                'filled_quantity': float(order.executed_qty or order.quantity or 0.0),
                'filled_price': float(order.avg_fill_price or order.price or 0.0),
                'status': order.status or 'UNKNOWN',
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'updated_at': order.updated_at.isoformat() if order.updated_at else None,
                'source': 'app'
            }
            add_order(key, order_dict)

        if symbol_filter:
            symbols_to_check.add(symbol_filter)
        else:
            symbols_to_check.update({o.symbol for o in stored_orders if o.symbol})
            try:
                user_coins = Coin.query.filter_by(user_id=current_user.id).all()
                for coin in user_coins:
                    sym = (coin.symbol or '').upper()
                    if sym and sym not in ['USD', 'USDT']:
                        symbols_to_check.add(f"{sym}USDT")
                        symbols_to_check.add(f"{sym}USD")
            except Exception as coin_err:
                logger.warning(f"Failed to gather portfolio symbols for order history: {coin_err}")

        activity_rows = query_logs_db(
            '''SELECT date, type, asset, amount, fee, status, details, txid, price_sold_at
               FROM all_activities
               WHERE user_id = ? AND status IN ("FILLED", "completed")''',
            (current_user.id,)
        )

        activity_records = []
        for activity in activity_rows:
            details_str = activity.get('details') or ''
            details_json = None
            if details_str:
                json_start = details_str.find('{')
                if json_start >= 0:
                    try:
                        details_json = json.loads(details_str[json_start:])
                    except Exception:
                        details_json = None
            if details_json:
                activity['__details_json__'] = details_json
                product_id = details_json.get('product_id')
                if product_id:
                    symbols_to_check.add(product_id.replace('-', '').upper())
                activity_records.append(activity)
            else:
                activity_records.append(activity)

        cleaned_symbols = {s for s in symbols_to_check if s}

        # Attempt to fetch Binance order history directly
        try:
            # Fetch credentials using ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()

            if creds:
                trading_api_key = creds.trading_api_key
                trading_api_secret = creds.trading_api_secret
                portfolio_api_key = creds.api_key
                portfolio_api_secret = creds.api_secret

                api_key = trading_api_key or portfolio_api_key
                api_secret = trading_api_secret or portfolio_api_secret

                if api_key and api_secret:
                    from binance.client import Client
                    client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')

                    for trading_symbol in cleaned_symbols:
                        try:
                            if unlimited:
                                fetched_orders = []
                                next_start = None
                                while True:
                                    params = {'symbol': trading_symbol, 'limit': 500}
                                    if next_start:
                                        params['startTime'] = next_start
                                    batch = client.get_all_orders(**params)
                                    if not batch:
                                        break
                                    fetched_orders.extend(batch)
                                    if len(batch) < 500:
                                        break
                                    last_time = batch[-1].get('time') or batch[-1].get('updateTime')
                                    if not last_time:
                                        break
                                    next_start = last_time + 1
                                    time.sleep(0.2)
                            else:
                                fetched_orders = client.get_all_orders(symbol=trading_symbol, limit=min(limit, 500))

                            for o in fetched_orders:
                                order_id = o.get('orderId')
                                key = f"binance-{trading_symbol}-{order_id}"

                                created_at = o.get('time') or o.get('updateTime')
                                if created_at:
                                    created_at_iso = datetime.fromtimestamp(created_at / 1000).isoformat()
                                else:
                                    created_at_iso = None

                                orig_qty = float(o.get('origQty') or 0.0)
                                executed_qty = float(o.get('executedQty') or 0.0)
                                price = float(o.get('price') or 0.0)
                                cumulative_quote = float(o.get('cummulativeQuoteQty') or 0.0)

                                filled_price = 0.0
                                if executed_qty > 0:
                                    if cumulative_quote > 0:
                                        filled_price = cumulative_quote / executed_qty
                                    else:
                                        filled_price = price
                                elif price > 0:
                                    filled_price = price

                                payload = {
                                    'id': order_id or key,
                                    'symbol': trading_symbol,
                                    'side': o.get('side'),
                                    'order_type': o.get('type'),
                                    'quantity': orig_qty,
                                    'price': price,
                                    'filled_quantity': executed_qty,
                                    'filled_price': filled_price,
                                    'status': o.get('status'),
                                    'created_at': created_at_iso,
                                    'updated_at': datetime.fromtimestamp(o['updateTime'] / 1000).isoformat() if o.get('updateTime') else created_at_iso,
                                    'source': 'binance'
                                }

                                add_order(key, payload)

                        except Exception as binance_err:
                            logger.warning(f"Failed to fetch Binance orders for {trading_symbol}: {binance_err}")
                            continue
                else:
                    logger.warning("Binance credentials found but incomplete for order history fetch")
            else:
                logger.warning("No Binance credentials found for real order history")
        except Exception as cred_err:
            logger.warning(f"Could not fetch Binance order history: {cred_err}")

        # Merge historical records from all_activities (fills from other sources)
        for activity in activity_records:
            details_json = activity.get('__details_json__') or {}
            order_id = details_json.get('order_id') or activity.get('txid')
            product_id = details_json.get('product_id')
            if not order_id or not product_id:
                continue

            if activity.get('asset', '').upper() == 'USDT' and 'Auto-generated' in (activity.get('details') or ''):
                continue

            side = (details_json.get('side') or activity.get('type') or '').upper()
            quantity = details_json.get('filled_size') or activity.get('amount')
            price = details_json.get('average_filled_price') or activity.get('price_sold_at')

            try:
                quantity_val = float(quantity) if quantity not in (None, '') else 0.0
            except Exception:
                quantity_val = 0.0

            try:
                price_val = float(price) if price not in (None, '') else 0.0
            except Exception:
                price_val = 0.0

            payload = {
                'id': order_id,
                'symbol': product_id.replace('-', '').upper(),
                'side': side or 'UNKNOWN',
                'order_type': (details_json.get('order_type') or activity.get('type') or 'UNKNOWN').upper(),
                'quantity': quantity_val,
                'price': price_val,
                'filled_quantity': quantity_val,
                'filled_price': price_val,
                'status': activity.get('status', 'FILLED') or 'FILLED',
                'created_at': normalize_timestamp(details_json.get('created_time') or activity.get('date')),
                'updated_at': normalize_timestamp(details_json.get('last_fill_time') or details_json.get('created_time') or activity.get('date')),
                'source': 'history'
            }

            add_order(f"binance-{payload['symbol']}-{order_id}", payload)

        # Sort and limit
        order_list = list(combined_orders.values())
        order_list.sort(key=lambda o: o.get('created_at') or '', reverse=True)
        limited_orders = order_list if unlimited else order_list[:limit]

        return jsonify({
            'success': True,
            'orders': limited_orders
        })

    except Exception as e:
        logger.error(f"Error fetching real orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/2fa/setup', methods=['POST'])
@login_required
def setup_2fa():
    """Generate and return a new TOTP secret for 2FA setup"""
    try:
        import pyotp
        import qrcode
        import io
        import base64
        
        # Generate a new secret
        secret = pyotp.random_base32()
        
        # Create provisioning URI for QR code
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=current_user.username,
            issuer_name='Crypto Dashboard Trading'
        )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        # Store secret temporarily (not confirmed until verified)
        session['pending_totp_secret'] = secret
        
        return jsonify({
            'success': True,
            'secret': secret,
            'qr_code': f'data:image/png;base64,{img_base64}',
            'provisioning_uri': provisioning_uri
        })
        
    except Exception as e:
        logger.error(f"Error setting up 2FA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/2fa/verify-setup', methods=['POST'])
@login_required
def verify_2fa_setup():
    """Verify 2FA code and enable 2FA for trading"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Code is required'}), 400
        
        # Get pending secret from session
        secret = session.get('pending_totp_secret')
        if not secret:
            return jsonify({'success': False, 'error': 'No pending 2FA setup found. Please start setup again.'}), 400
        
        # Verify code
        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return jsonify({'success': False, 'error': 'Invalid code. Please try again.'}), 400
        
        # Save secret to database
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if not settings:
            settings = TradingSettings(user_id=current_user.id)
            db.session.add(settings)
        
        settings.totp_secret = secret
        settings.require_2fa = True
        settings.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Clear session
        session.pop('pending_totp_secret', None)
        
        return jsonify({
            'success': True,
            'message': '2FA enabled successfully!'
        })
        
    except Exception as e:
        logger.error(f"Error verifying 2FA setup: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    """Disable 2FA for trading (requires code verification)"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Code is required to disable 2FA'}), 400
        
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if not settings or not settings.totp_secret:
            return jsonify({'success': False, 'error': '2FA is not enabled'}), 400
        
        # Verify code before disabling
        totp = pyotp.TOTP(settings.totp_secret)
        if not totp.verify(code, valid_window=1):
            return jsonify({'success': False, 'error': 'Invalid code. Please try again.'}), 400
        
        # Disable 2FA
        settings.totp_secret = None
        settings.require_2fa = False
        settings.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '2FA disabled successfully'
        })
        
    except Exception as e:
        logger.error(f"Error disabling 2FA: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/2fa/verify', methods=['POST'])
@login_required
def verify_2fa_code():
    """Verify a 2FA code for order placement"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Code is required'}), 400
        
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if not settings or not settings.totp_secret:
            return jsonify({'success': False, 'error': '2FA is not enabled'}), 400
        
        # Verify code
        totp = pyotp.TOTP(settings.totp_secret)
        if not totp.verify(code, valid_window=1):
            return jsonify({'success': False, 'error': 'Invalid or expired code. Please try again.'}), 400
        
        # Generate a temporary token valid for 2 minutes
        import secrets
        token = secrets.token_urlsafe(32)
        session[f'2fa_verified_{token}'] = {
            'user_id': current_user.id,
            'timestamp': datetime.utcnow().timestamp()
        }
        
        return jsonify({
            'success': True,
            'token': token,
            'message': '2FA verified successfully'
        })
        
    except Exception as e:
        logger.error(f"Error verifying 2FA code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/portfolio', methods=['GET'])
@login_required
def get_test_portfolio():
    """Get test portfolio holdings"""
    try:
        holdings = TestPortfolio.query.filter_by(user_id=current_user.id).filter(
            TestPortfolio.quantity > 0
        ).all()
        
        logger.error(f"[TEST_PORTFOLIO] Found {len(holdings)} holdings for user {current_user.username}")
        
        # Get current prices for each holding
        from binance.client import Client
        
        # Get credentials for price fetching
        # Get credentials for price fetching using ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if creds:
            api_key = creds.api_key
            api_secret = creds.api_secret
        else:
            api_key = api_secret = None

        logger.error(f"[TEST_PORTFOLIO] Credentials found: {bool(api_key)}")
        
        portfolio_data = []
        
        if api_key and api_secret:
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
            
            for holding in holdings:
                try:
                    logger.error(f"[TEST_PORTFOLIO] Processing {holding.symbol}, quantity: {holding.quantity}")
                    
                    # Handle stablecoins (USDT, USDC, BUSD, etc.) with $1.00 price
                    if holding.symbol in ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD']:
                        current_price = 1.0
                        logger.error(f"[TEST_PORTFOLIO] {holding.symbol} is stablecoin, price = 1.0")
                    else:
                        # Fetch real-time price from Binance
                        symbol = holding.symbol + 'USDT'
                        ticker = client.get_symbol_ticker(symbol=symbol)
                        current_price = float(ticker['price'])
                        logger.error(f"[TEST_PORTFOLIO] {holding.symbol} price from API: {current_price}")
                    
                    current_value = holding.quantity * current_price
                    cost_basis = holding.quantity * holding.avg_entry_price
                    pnl = current_value - cost_basis
                    pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0
                    
                    portfolio_data.append({
                        'symbol': holding.symbol,
                        'quantity': holding.quantity,
                        'average_price': holding.avg_entry_price,
                        'current_price': current_price,
                        'current_value': current_value,
                        'cost_basis': cost_basis,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'last_updated': holding.last_updated.isoformat() if holding.last_updated else None
                    })
                except Exception as e:
                    logger.warning(f"Failed to get price for {holding.symbol}: {e}")
                    # Add holding with null price data
                    portfolio_data.append({
                        'symbol': holding.symbol,
                        'quantity': holding.quantity,
                        'average_price': holding.avg_entry_price,
                        'current_price': None,
                        'current_value': None,
                        'cost_basis': holding.quantity * holding.avg_entry_price,
                        'pnl': None,
                        'pnl_pct': None,
                        'last_updated': holding.last_updated.isoformat() if holding.last_updated else None
                    })
        
        return jsonify({
            'success': True,
            'holdings': portfolio_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching test portfolio: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/portfolio/backfill', methods=['POST'])
@login_required
def backfill_test_portfolio():
    """Backfill test portfolio with actual coin holdings from the coins table AND USDT from Binance"""
    try:
        from binance.client import Client
        
        # Get all coins for the user
        user_coins = Coin.query.filter_by(user_id=current_user.id).all()
        
        if not user_coins:
            return jsonify({
                'success': False,
                'error': 'No coins found in your portfolio to backfill'
            }), 400
        
        backfilled_count = 0
        
        # Backfill regular coins from coins table
        for coin in user_coins:
            # Skip if no amount or hidden
            if not coin.amount or coin.amount <= 0 or coin.hidden:
                continue
            
            # Check if already exists in test portfolio
            existing = TestPortfolio.query.filter_by(
                user_id=current_user.id,
                symbol=coin.symbol
            ).first()
            
            # Use avg_entry or current price as the entry price
            entry_price = coin.avg_entry or coin.current or 0
            
            if existing:
                # Update existing
                existing.quantity = coin.amount
                existing.avg_entry_price = entry_price
                existing.total_cost_basis = coin.amount * entry_price
                existing.last_updated = datetime.utcnow()
                logger.info(f"Updated test portfolio for {coin.symbol}: {coin.amount} @ ${existing.avg_entry_price}")
            else:
                # Create new
                test_holding = TestPortfolio(
                    user_id=current_user.id,
                    symbol=coin.symbol,
                    quantity=coin.amount,
                    avg_entry_price=entry_price,
                    total_cost_basis=coin.amount * entry_price,
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                    last_updated=datetime.utcnow()
                )
                db.session.add(test_holding)
                logger.info(f"Added test portfolio for {coin.symbol}: {coin.amount} @ ${test_holding.avg_entry_price}")
            
            backfilled_count += 1
        
        # Now fetch USDT balance from Binance
        try:
            # Get credentials for Binance API
            # Get credentials for Binance API using ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()

            api_key = creds.api_key if creds else None
            api_secret = creds.api_secret if creds else None

            if api_key and api_secret:
                client = Client(
                    api_key=api_key,
                    api_secret=api_secret,
                    testnet=False,
                    tld='us'
                )
                
                # Get account info to fetch USDT balance
                account_info = client.get_account()
                
                # Find USDT balance
                usdt_balance = 0.0
                for balance in account_info['balances']:
                    if balance['asset'] == 'USDT':
                        usdt_balance = float(balance['free']) + float(balance['locked'])
                        break
                
                if usdt_balance > 0:
                    # Check if USDT already exists in test portfolio
                    existing_usdt = TestPortfolio.query.filter_by(
                        user_id=current_user.id,
                        symbol='USDT'
                    ).first()
                    
                    if existing_usdt:
                        # Update existing USDT
                        existing_usdt.quantity = usdt_balance
                        existing_usdt.avg_entry_price = 1.0
                        existing_usdt.total_cost_basis = usdt_balance
                        existing_usdt.last_updated = datetime.utcnow()
                        logger.info(f"Updated test portfolio USDT: ${usdt_balance:.2f}")
                    else:
                        # Create new USDT entry
                        test_usdt = TestPortfolio(
                            user_id=current_user.id,
                            symbol='USDT',
                            quantity=usdt_balance,
                            avg_entry_price=1.0,
                            total_cost_basis=usdt_balance,
                            realized_pnl=0.0,
                            unrealized_pnl=0.0,
                            last_updated=datetime.utcnow()
                        )
                        db.session.add(test_usdt)
                        logger.info(f"Added test portfolio USDT: ${usdt_balance:.2f}")
                    
                    backfilled_count += 1
                else:
                    logger.warning("No USDT balance found in Binance account")
            else:
                logger.warning("No Binance API credentials found, skipping USDT backfill")
                
        except Exception as e:
            logger.error(f"Error fetching USDT balance from Binance: {e}")
            # Continue without USDT if there's an error
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully backfilled {backfilled_count} holding(s) into test portfolio',
            'count': backfilled_count
        })
        
    except Exception as e:
        logger.error(f"Error backfilling test portfolio: {e}\n{traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/test-orders', methods=['GET'])
@login_required
def get_test_orders():
    """Get all test orders for the user"""
    try:
        limit = int(request.args.get('limit', 100))
        symbol = request.args.get('symbol')
        
        query = TestOrder.query.filter_by(user_id=current_user.id)
        
        if symbol:
            query = query.filter_by(symbol=symbol.upper())
        
        test_orders = query.order_by(TestOrder.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'orders': [order.to_dict() for order in test_orders]
        })
        
    except Exception as e:
        logger.error(f"Error fetching test orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/place-order', methods=['POST'])
@login_required
def place_real_order():
    """Place a REAL order on Binance.US (requires test mode to be disabled)"""
    import traceback
    try:
        # Check trading settings
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if not settings or settings.test_mode_enabled:
            return jsonify({
                'success': False,
                'error': 'Real trading is disabled. Please disable test mode in settings to place real orders.'
            }), 403
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'side', 'type', 'quantity']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()
        order_type = data['type'].upper()
        quantity_input = _coerce_float(data.get('quantity'))
        price = _coerce_float(data.get('price'), 0.0) or 0.0
        quote_amount = _coerce_float(
            data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount')
        )
        
        # Check if 2FA is required (ALWAYS for real orders)
        if settings.require_2fa and settings.totp_secret:
            # Verify 2FA token
            twofa_token = data.get('twofa_token')
            if not twofa_token:
                return jsonify({'success': False, 'error': '2FA verification required for real orders', 'requires_2fa': True}), 403
            
            # Check token validity
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data or token_data['user_id'] != current_user.id:
                return jsonify({'success': False, 'error': '2FA verification invalid or expired', 'requires_2fa': True}), 403
            
            # Check if token is not older than 2 minutes
            if (datetime.utcnow().timestamp() - token_data['timestamp']) > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({'success': False, 'error': '2FA verification expired. Please verify again.', 'requires_2fa': True}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get Binance.US Trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters and latest price data
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading rules for {symbol}. Please check the symbol is valid.'}), 400

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
        except Exception as price_err:
            logger.warning(f"Failed to fetch current price for {symbol}: {price_err}")
            current_price = 0.0

        quantity = quantity_input or 0.0
        if quantity <= 0:
            reference_price = price if price > 0 else current_price
            if (not reference_price or reference_price <= 0) and quote_amount and quote_amount > 0:
                try:
                    ticker = client.get_symbol_ticker(symbol=symbol)
                    reference_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
                    current_price = reference_price
                except Exception as refill_err:
                    logger.error(f"Failed to refresh price for {symbol}: {refill_err}")
                    reference_price = None
            if quote_amount and quote_amount > 0 and reference_price and reference_price > 0:
                quantity = quote_amount / reference_price

        if quantity is None or quantity <= 0:
            return jsonify({
                'success': False,
                'error': 'Unable to determine order quantity. Please enter a value or wait for prices to refresh.'
            }), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        # Validate quantity is within bounds
        if formatted_quantity < filters['minQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too small. Minimum quantity for {symbol} is {filters["minQty"]}. You entered {quantity} which rounds to {formatted_quantity}.'
            }), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too large. Maximum quantity for {symbol} is {filters["maxQty"]}. You entered {quantity}.'
            }), 400
        
        # Format price according to PRICE_FILTER
        if price > 0:
            formatted_price = format_price(price, filters['tickSize'])
            if formatted_price < filters['minPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too low. Minimum price for {symbol} is {filters["minPrice"]}. You entered {price}.'
                }), 400
            if formatted_price > filters['maxPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too high. Maximum price for {symbol} is {filters["maxPrice"]}. You entered {price}.'
                }), 400
        else:
            formatted_price = 0.0
        
        # Get current price for order size validation
        try:
            reference_price_for_value = formatted_price if formatted_price > 0 else current_price
            if not reference_price_for_value or reference_price_for_value <= 0:
                raise ValueError("Unable to determine current market price for valuation.")
            order_value_usd = formatted_quantity * reference_price_for_value
            
            # Check MIN_NOTIONAL
            if 'minNotional' in filters and order_value_usd < filters['minNotional']:
                return jsonify({
                    'success': False, 
                    'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is ${order_value_usd:.2f}. Please increase quantity or price.'
                }), 400
            
            # Check max order size
            if order_value_usd > settings.max_order_size_usd:
                return jsonify({
                    'success': False,
                    'error': f'Order size ${order_value_usd:.2f} exceeds maximum allowed ${settings.max_order_size_usd:.2f}'
                }), 400
        except Exception as e:
            logger.error(f"Failed to validate order size: {e}")
            return jsonify({'success': False, 'error': f'Failed to validate order: {str(e)}'}), 400
        
        # Place REAL order on Binance.US
        try:
            logger.info(f"Placing real order with params: {{'symbol': '{symbol}', 'side': '{side}', 'type': '{order_type}', 'quantity': {formatted_quantity}, 'price': {formatted_price}, 'order_value_usd': {order_value_usd}}}")
            order_params = build_order_config(order_type, side, formatted_quantity, data, symbol)
            
            # PLACE THE REAL ORDER
            order_response = client.create_order(**order_params)
            
            # Extract fill details
            executed_qty = float(order_response.get('executedQty', 0))
            fills = order_response.get('fills', [])
            avg_fill_price = float(fills[0].get('price', 0)) if fills else (price if price > 0 else current_price)
            total_commission = sum(float(f.get('commission', 0)) for f in fills)
            commission_asset = fills[0].get('commissionAsset', 'USDT') if fills else 'USDT'

            success_payload = {
                'success': True,
                'order': None,
                'binance_order_id': order_response['orderId'],
                'message': f'Real order placed successfully. Quantity adjusted from {quantity} to {formatted_quantity} to match trading rules.' if quantity != formatted_quantity else 'Real order placed successfully',
                'formatted_values': {
                    'quantity': formatted_quantity,
                    'price': formatted_price,
                    'original_quantity': quantity,
                    'original_price': price
                }
            }

            try:
                real_order = RealOrder(
                    user_id=current_user.id,
                    binance_order_id=order_response['orderId'],
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=formatted_quantity,
                    price=formatted_price if formatted_price > 0 else None,
                    stop_price=order_params.get('stopPrice'),
                    time_in_force=order_response.get('timeInForce'),
                    status=order_response['status'],
                    executed_qty=executed_qty,
                    cumulative_quote_qty=float(order_response.get('cummulativeQuoteQty', 0)),
                    avg_fill_price=avg_fill_price,
                    commission=total_commission,
                    commission_asset=commission_asset,
                    binance_client_order_id=order_response.get('clientOrderId'),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    filled_at=datetime.utcnow() if order_response['status'] == 'FILLED' else None,
                    order_response=json.dumps(order_response)
                )

                db.session.add(real_order)
                if order_response['status'] == 'FILLED':
                    real_order.fill_notified = True

                if order_response['status'] == 'FILLED' and executed_qty > 0:
                    update_portfolio_from_real_order(
                        user_id=current_user.id,
                        symbol=symbol,
                        side=side,
                        quantity=executed_qty,
                        price=avg_fill_price,
                        commission=total_commission,
                        commission_asset=commission_asset,
                        order_id=order_response['orderId']
                    )
                    notify_order_fill(
                        real_order,
                        username=current_user.username,
                        executed_qty=executed_qty,
                        quote_qty=float(order_response.get('cummulativeQuoteQty', 0)),
                        fill_price=avg_fill_price
                    )

                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)
                success_payload['order'] = real_order.to_dict()

                try:
                    recalculate_asset_activity(
                        user_id=current_user.id,
                        asset=base_asset,
                        price_provider=lambda sym: fetch_binance_price(sym),
                        logger=logger
                    )
                except Exception as recalc_err:
                    logger.warning(f"Failed to recalculate activity after real order for {base_asset}: {recalc_err}")

                logger.info(f"REAL ORDER PLACED for user {current_user.id}: {symbol} {side} {formatted_quantity} @ {avg_fill_price} - Order ID: {order_response['orderId']}")
            except Exception as post_err:
                logger.error(f"Order {order_response['orderId']} placed but post-processing failed: {post_err}", exc_info=True)
                db.session.rollback()

            return jsonify(success_payload)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to place real order: {error_msg}\n{traceback.format_exc()}")
            if "API-key" in error_msg or "Invalid Api-Key" in error_msg or "invalid api-key" in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'Order placement failed: {error_msg}'}), 400

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error in place_real_order: {err_msg}\n{traceback.format_exc()}")
        db.session.rollback()
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500


@app.route('/api/trading/fees/<symbol>', methods=['GET'])
@login_required
def get_trading_fees(symbol):
    """Get actual trading fees for a symbol from Binance.US"""
    try:
        symbol = symbol.upper()
        
        # ALWAYS fetch actual fees from Binance.US API
        # Test mode only affects order execution, not fee display
        # Get Binance trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No trading API credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key:
            return jsonify({
                'success': False,
                'error': 'No trading API credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Method 1: Try to get symbol-specific trading fee
        try:
            # Call the trading fee API endpoint
            fee_data = client.get_trade_fee(symbol=symbol)
            logger.info(f"Binance.US get_trade_fee() raw response: {fee_data}")
            
            if fee_data and len(fee_data) > 0:
                symbol_fee = fee_data[0]
                logger.info(f"Symbol fee data: {symbol_fee}")
                maker_rate = float(symbol_fee.get('makerCommission', 0.001))
                taker_rate = float(symbol_fee.get('takerCommission', 0.001))
                
                logger.info(f"Parsed rates - Maker: {maker_rate}, Taker: {taker_rate}")
                
                return jsonify({
                    'success': True,
                    'fees': {
                        'maker': f"{maker_rate:.6f}",
                        'taker': f"{taker_rate:.6f}",
                        'makerRate': maker_rate,
                        'takerRate': taker_rate
                    }
                })
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Could not fetch symbol-specific fees: {err_msg}\n{traceback.format_exc()}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
        
        # Method 2: Fall back to account-level commission rates
        try:
            account = client.get_account()
            logger.info(f"Binance.US account data keys: {list(account.keys())}")
            
            commission_rates = account.get('commissionRates', {})
            logger.info(f"Binance.US commission rates (raw): {commission_rates}")
            
            if commission_rates:
                # Binance.US returns BASE rates as decimal strings (e.g., "0.00400000" = 0.4%)
                # These are BEFORE any BNB discount (5% off if using BNB for fees)
                # The actual fee at order time will be lower if BNB is enabled
                maker_rate = float(commission_rates.get('maker', '0.001'))
                taker_rate = float(commission_rates.get('taker', '0.004'))
                logger.info(f"✅ BASE rates (before BNB discount): Maker={maker_rate:.4f} ({maker_rate*100:.2f}%), Taker={taker_rate:.4f} ({taker_rate*100:.2f}%)")
            else:
                # Old format: makerCommission/takerCommission (in basis points)
                # 10 basis points = 0.1%, 40 basis points = 0.4%
                maker_commission = account.get('makerCommission', 10)
                taker_commission = account.get('takerCommission', 40)
                logger.info(f"Got old format commission (basis points): makerCommission={maker_commission}, takerCommission={taker_commission}")
                
                maker_rate = float(maker_commission) / 10000
                taker_rate = float(taker_commission) / 10000
                logger.info(f"Converted to rates - Maker: {maker_rate:.4f} ({maker_rate*100:.2f}%), Taker: {taker_rate:.4f} ({taker_rate*100:.2f}%)")
            
            return jsonify({
                'success': True,
                'fees': {
                    'maker': f"{maker_rate:.6f}",
                    'taker': f"{taker_rate:.6f}",
                    'makerRate': maker_rate,
                    'takerRate': taker_rate
                }
            })
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error fetching account commission rates: {err_msg}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            # Last resort: use default Binance.US rates (0.1% maker, 0.4% taker)
            return jsonify({
                'success': True,
                'fees': {
                    'maker': '0.001000',
                    'taker': '0.001000',
                    'makerRate': 0.001,
                    'takerRate': 0.001
                }
            })

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error in get_trading_fees: {err_msg}\n{traceback.format_exc()}")
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500


@app.route('/api/trading/price/<symbol>', methods=['GET'])
@login_required
def get_current_price(symbol):
    """Get current market price for a trading pair"""
    try:
        symbol = symbol.upper()
        
        # Get Binance credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        api_key = creds.api_key
        api_secret = creds.api_secret
        if not api_key or not api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get current price
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
        except Exception as api_err:
            err_msg = str(api_err)
            logger.error(f"Error fetching price ticker for {symbol}: {err_msg}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'Failed to fetch price: {err_msg}'}), 502
        base_price = float(ticker['price'])
        
        # Parse symbol to get base and quote assets
        if symbol.endswith('USD') and not symbol.endswith('USDT'):
            base_asset = symbol[:-3]
            quote_asset = 'USD'
        elif symbol.endswith('USDT'):
            base_asset = symbol[:-4]
            quote_asset = 'USDT'
        else:
            base_asset = symbol
            quote_asset = 'USDT'
        
        return jsonify({
            'success': True,
            'prices': {
                'base': base_price,  # Price of base asset in quote asset
                'quote': 1.0,  # Quote asset is always 1 (USDT/USD)
                'base_asset': base_asset,
                'quote_asset': quote_asset
            }
        })
        
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error fetching price for {symbol}: {err_msg}")
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500


@app.route('/api/trading/balances/<symbol>', methods=['GET'])
@login_required
def get_trading_balances(symbol):
    """Get user balances for trading pair assets
    
    If test mode is enabled: fetch from test_portfolio table
    If test mode is disabled: fetch from Binance.US API
    """
    try:
        symbol = symbol.upper()
        
        # Properly extract base and quote assets
        # For USDTUSD: base=USDT, quote=USD
        # For BTCUSD: base=BTC, quote=USD
        # For BTCUSDT: base=BTC, quote=USDT
        if symbol.endswith('USD') and not symbol.endswith('USDT'):
            # USD pairs (e.g., BTCUSD, USDTUSD)
            base_asset = symbol[:-3]  # Remove 'USD' suffix
            quote_asset = 'USD'
        elif symbol.endswith('USDT'):
            # USDT pairs (e.g., BTCUSDT)
            base_asset = symbol[:-4]  # Remove 'USDT' suffix
            quote_asset = 'USDT'
        else:
            # Fallback
            base_asset = symbol
            quote_asset = 'USDT'
        
        # Check if user is in test mode
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        test_mode = settings.test_mode_enabled if settings else True
        
        logger.info(f"[BALANCE] Fetching balances for {symbol} (base={base_asset}, quote={quote_asset}), test_mode={test_mode}")
        
        if test_mode:
            # Get balances from test portfolio
            base_holding = TestPortfolio.query.filter_by(
                user_id=current_user.id,
                symbol=base_asset
            ).first()
            
            quote_holding = TestPortfolio.query.filter_by(
                user_id=current_user.id,
                symbol=quote_asset
            ).first()
            
            base_free = base_holding.quantity if base_holding else 0.0
            quote_free = quote_holding.quantity if quote_holding else 0.0
            
            logger.info(f"[BALANCE] Test portfolio: {base_asset}={base_free:.8f}, {quote_asset}={quote_free:.8f}")
            
            return jsonify({
                'success': True,
                'balances': {
                    'base': base_free,
                    'base_locked': 0.0,
                    'base_total': base_free,
                    'quote': quote_free,
                    'quote_locked': 0.0,
                    'quote_total': quote_free,
                    'base_asset': base_asset,
                    'quote_asset': quote_asset
                },
                'test_mode': True
            })
        else:
            # Get actual balances from Binance.US API using SQLAlchemy ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if not creds:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US API credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            # Credential model properties auto-decrypt values
            # Try trading credentials first, fall back to portfolio credentials
            trading_api_key = creds.trading_api_key
            trading_api_secret = creds.trading_api_secret
            portfolio_api_key = creds.api_key
            portfolio_api_secret = creds.api_secret
            api_key = trading_api_key or portfolio_api_key
            api_secret = trading_api_secret or portfolio_api_secret
            
            if not api_key or not api_secret:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US API credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
            
            # Get account info directly from Binance.US
            try:
                account = client.get_account()
            except Exception as api_err:
                err_msg = str(api_err)
                logger.error(f"[BALANCE] Binance API error for {symbol}: {err_msg}")
                if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                    return jsonify({
                        'success': False,
                        'error': 'Invalid Binance API credentials',
                        'error_code': 'invalid_trading_credentials'
                    }), 400
                return jsonify({
                    'success': False,
                    'error': f'Failed to fetch balances: {err_msg}'
                }), 502
            
            # Extract only the relevant asset balances
            base_free = 0
            base_locked = 0
            quote_free = 0
            quote_locked = 0
            
            for balance in account['balances']:
                asset = balance['asset']
                if asset in [base_asset, quote_asset]:
                    free_balance = float(balance['free'])
                    locked_balance = float(balance.get('locked', 0))
                    total_balance = free_balance + locked_balance
                    
                    if asset == base_asset:
                        base_free = free_balance
                        base_locked = locked_balance
                    elif asset == quote_asset:
                        quote_free = free_balance
                        quote_locked = locked_balance
                    
                    logger.info(f"[BALANCE] Real Binance: {asset}: free={free_balance:.8f}, locked={locked_balance:.8f}, total={total_balance:.8f}")
            
            return jsonify({
                'success': True,
                'balances': {
                    'base': base_free,
                    'base_locked': base_locked,
                    'base_total': base_free + base_locked,
                    'quote': quote_free,
                    'quote_locked': quote_locked,
                    'quote_total': quote_free + quote_locked,
                    'base_asset': base_asset,
                    'quote_asset': quote_asset
                },
                'test_mode': False
            })
        
    except Exception as e:
        logger.error(f"Error fetching balances for {symbol}: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/open-orders', methods=['GET'])
@login_required
def get_open_orders():
    """Get all open orders"""
    try:
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if settings and settings.test_mode_enabled:
            # Get open test orders
            open_orders = TestOrder.query.filter_by(
                user_id=current_user.id
            ).filter(
                TestOrder.status.in_(['NEW', 'PARTIALLY_FILLED'])
            ).order_by(TestOrder.created_at.desc()).all()
            
            return jsonify({
                'success': True,
                'orders': [order.to_dict() for order in open_orders]
            })
        else:
            # Get real open orders from Binance using SQLAlchemy ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if not creds:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US trading credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            # Credential model properties auto-decrypt values
            trading_api_key = creds.trading_api_key
            trading_api_secret = creds.trading_api_secret
            if not trading_api_key or not trading_api_secret:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US trading credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            from binance.client import Client
            client = Client(
                api_key=trading_api_key,
                api_secret=trading_api_secret,
                testnet=False,
                tld='us'
            )
            
            try:
                open_orders = client.get_open_orders()
            except Exception as api_err:
                err_msg = str(api_err)
                logger.error(f"Error fetching open orders from Binance: {err_msg}")
                if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                    return jsonify({
                        'success': False,
                        'error': 'Invalid Binance API credentials',
                        'error_code': 'invalid_trading_credentials'
                    }), 400
                return jsonify({
                    'success': False,
                    'error': f'Failed to fetch open orders: {err_msg}'
                }), 502
            
            return jsonify({
                'success': True,
                'orders': open_orders
            })
        
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/test-oco-order', methods=['POST'])
@login_required
def place_test_oco_order():
    """Place a test OCO order (validates with Binance.US but doesn't execute)"""
    import traceback
    try:
        data = request.get_json()
        
        # Validate required fields for OCO
        required_fields = ['symbol', 'side', 'quantity', 'price', 'stopPrice', 'stopLimitPrice']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()  # BUY or SELL
        quantity = float(data['quantity'])
        price = float(data['price'])
        stop_price = float(data['stopPrice'])
        stop_limit_price = float(data['stopLimitPrice'])
        stop_limit_time_in_force = data.get('stopLimitTimeInForce', 'GTC')
        
        # Validate prices
        if price <= 0 or stop_price <= 0 or stop_limit_price <= 0:
            return jsonify({'success': False, 'error': 'All prices must be greater than 0'}), 400
        
        # Get Binance.US Trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters to format quantity properly
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading filters for {symbol}'}), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        if formatted_quantity < filters['minQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} is below minimum {filters["minQty"]}'}), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} exceeds maximum {filters["maxQty"]}'}), 400
        
        # Update quantity to formatted value
        quantity = formatted_quantity
        
        # Validate OCO order with Binance.US (Note: Binance doesn't have a test endpoint for OCO, so we skip validation)
        # Get current market price for simulation
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            current_price = price
        
        # Validate price relationships
        if side == 'SELL':
            if not (price > current_price > stop_price):
                return jsonify({'success': False, 'error': 'For SELL OCO: Limit Price > Market Price > Stop Price'}), 400
        else:  # BUY
            if not (price < current_price < stop_price):
                return jsonify({'success': False, 'error': 'For BUY OCO: Limit Price < Market Price < Stop Price'}), 400
        
        # Use API-provided fees when possible
        fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
        # For simulation assume taker fee for immediate fills
        fee_rate = fee_info.get('taker', 0.001)

        # Balance check: ensure user has enough quote asset (e.g., USDT) to cover limit order + fees
        # Get balances from Binance account (or simulated account for test mode)
        try:
            account_info = client.get_account()
            # Properly extract base and quote assets
            if symbol.endswith('USD') and not symbol.endswith('USDT'):
                quote_asset = 'USD'
            else:
                quote_asset = 'USDT'
                
            balances = {b['asset']: float(b['free']) for b in account_info.get('balances', [])}
            available_quote = balances.get(quote_asset, 0.0)
        except Exception:
            available_quote = None

        # Calculate required quote - for OCO buy, we must afford the most expensive leg
        check_price = max(price, stop_limit_price) if side == 'BUY' else price
        required_quote = quantity * check_price
        estimated_fee = required_quote * fee_rate

        if available_quote is not None and (required_quote + estimated_fee) > available_quote:
            # Try to reduce quantity in steps until it fits available balance
            step = filters['stepSize']
            from decimal import Decimal
            qty_dec = Decimal(str(quantity))
            step_dec = Decimal(str(step))
            price_dec = Decimal(str(price))
            fee_rate_dec = Decimal(str(fee_rate))
            max_qty = Decimal(str(filters['maxQty']))
            min_qty = Decimal(str(filters['minQty']))

            while qty_dec >= min_qty:
                req = qty_dec * price_dec
                fee_est = req * fee_rate_dec
                if (req + fee_est) <= Decimal(str(available_quote)):
                    break
                qty_dec -= step_dec

            if qty_dec < min_qty:
                return jsonify({'success': False, 'error': 'Insufficient balance to place OCO order even after adjusting quantity.'}), 400

            # Format quantity back
            quantity = float(format_quantity(float(qty_dec), filters['stepSize']))
            required_quote = quantity * price
            estimated_fee = required_quote * fee_rate

        # Create test order records (OCO creates 2 orders)
        # Limit order (simulate filled leg)
        limit_order = TestOrder(
            user_id=current_user.id,
            symbol=symbol,
            side=side,
            type='LIMIT_MAKER',  # Fixed: use 'type' not 'order_type'
            quantity=quantity,
            price=price,
            status='FILLED',  # Simulate immediate fill
            simulated_fill_price=price,
            simulated_fill_time=datetime.utcnow(),
            created_at=datetime.utcnow()
        )

        # Stop limit order (not filled in simulation, cancelled by limit fill)
        stop_order = TestOrder(
            user_id=current_user.id,
            symbol=symbol,
            side=side,
            type='STOP_LOSS_LIMIT',  # Fixed: use 'type' not 'order_type'
            quantity=quantity,
            price=stop_limit_price,
            stop_price=stop_price,
            status='CANCELED',  # Other leg cancelled in OCO
            created_at=datetime.utcnow()
        )
        
        db.session.add(limit_order)
        db.session.add(stop_order)
        
        # Update test portfolio (only for the filled leg)
        update_test_portfolio(current_user.id, symbol, side, quantity, price)
        
        db.session.commit()
        
        logger.info(f"Test OCO order placed for user {current_user.id}: {symbol} {side} {quantity}")
        
        return jsonify({
            'success': True,
            'orders': [limit_order.to_dict(), stop_order.to_dict()],
            'message': 'Test OCO order validated and simulated successfully'
        })
        
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error placing test OCO order: {err_msg}\n{traceback.format_exc()}")
        db.session.rollback()
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500


@app.route('/api/trading/oco-order', methods=['POST'])
@login_required
def place_real_oco_order():
    """Place a real OCO order on Binance.US"""
    import traceback
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'side', 'quantity', 'price', 'stopPrice', 'stopLimitPrice']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()
        quantity = float(data['quantity'])
        price = float(data['price'])
        stop_price = float(data['stopPrice'])
        stop_limit_price = float(data['stopLimitPrice'])
        stop_limit_time_in_force = data.get('stopLimitTimeInForce', 'GTC')
        
        # Validate prices
        if price <= 0 or stop_price <= 0 or stop_limit_price <= 0:
            return jsonify({'success': False, 'error': 'All prices must be greater than 0'}), 400
        
        # Get Binance.US Trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters to format quantity properly
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading filters for {symbol}'}), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        if formatted_quantity < filters['minQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} is below minimum {filters["minQty"]}'}), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} exceeds maximum {filters["maxQty"]}'}), 400
        
        # Update quantity to formatted value
        quantity = formatted_quantity
        
        # For BUY orders, check USDT balance and adjust quantity if needed to account for fees
        if side == 'BUY':
            try:
                # Get account balance
                account = client.get_account()
                # Properly extract base and quote assets
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    quote_asset = 'USD'
                elif symbol.endswith('USDT'):
                    quote_asset = 'USDT'
                else:
                    quote_asset = 'USDT'

                available_balance = 0.0
                for balance in account['balances']:
                    if balance['asset'] == quote_asset:
                        available_balance = float(balance['free'])
                        break
                
                # Calculate required balance including 0.1% Binance fee
                # For OCO buy, we must afford the most expensive of the two orders
                check_price = max(price, stop_limit_price) if side == 'BUY' else price
                required_balance = quantity * check_price * 1.001  # Add 0.1% for trading fee
                
                logger.info(f"OCO Balance Check: Available {quote_asset}: {available_balance:.8f}, Required: {required_balance:.8f}")
                
                # If insufficient balance, try to reduce quantity slightly to fit within available balance
                if required_balance > available_balance:
                    # Calculate maximum quantity we can afford with fees using the safety price
                    max_affordable_quantity = (available_balance * 0.999) / check_price  # Leave 0.1% buffer for fees
                    adjusted_quantity = format_quantity(max_affordable_quantity, filters['stepSize'])
                    
                    # Check if adjusted quantity is still valid
                    if adjusted_quantity >= filters['minQty']:
                        logger.warning(f"Adjusted OCO quantity from {quantity} to {adjusted_quantity} due to balance constraints")
                        quantity = adjusted_quantity
                    else:
                        return jsonify({
                            'success': False, 
                            'error': f'Insufficient {quote_asset} balance. Available: {available_balance:.8f}, Required: {required_balance:.8f} (including fees)'
                        }), 400
                        
            except Exception as balance_err:
                logger.error(f"Balance check failed: {balance_err}")
                # Continue anyway - let Binance reject if truly insufficient
        
        # Place real OCO order
        try:
            # Use API-provided fees and validate balance similar to test path
            fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
            fee_rate = fee_info.get('taker', 0.001)

            # Get balances
            try:
                # Properly extract quote asset
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    quote_asset = 'USD'
                elif symbol.endswith('USDT'):
                    quote_asset = 'USDT'
                else:
                    quote_asset = 'USDT'
                
                account_info = client.get_account()
                balances = {b['asset']: float(b['free']) for b in account_info.get('balances', [])}
                available_quote = balances.get(quote_asset, 0.0)
            except Exception:
                available_quote = None

            # Calculate required quote for the limit leg
            required_quote = quantity * price
            estimated_fee = required_quote * fee_rate

            if available_quote is not None and (required_quote + estimated_fee) > available_quote:
                # Try to reduce quantity to fit
                step = filters['stepSize']
                from decimal import Decimal
                qty_dec = Decimal(str(quantity))
                step_dec = Decimal(str(step))
                price_dec = Decimal(str(price))
                fee_rate_dec = Decimal(str(fee_rate))
                min_qty = Decimal(str(filters['minQty']))

                while qty_dec >= min_qty:
                    req = qty_dec * price_dec
                    fee_est = req * fee_rate_dec
                    if (req + fee_est) <= Decimal(str(available_quote)):
                        break
                    qty_dec -= step_dec

                if qty_dec < min_qty:
                    return jsonify({'success': False, 'error': 'Insufficient balance to place OCO order even after adjusting quantity.'}), 400

                quantity = float(format_quantity(float(qty_dec), filters['stepSize']))
                required_quote = quantity * price
                estimated_fee = required_quote * fee_rate

            order_response = client.create_oco_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                stopPrice=stop_price,
                stopLimitPrice=stop_limit_price,
                stopLimitTimeInForce=stop_limit_time_in_force
            )
            
            # Save both legs of the OCO to database
            order_list_id = order_response['orderListId']
            
            # Save both legs of the OCO to database - avoid invalid kwarg 'binance_order_list_id'
            for order_report in order_response.get('orderReports', []):
                ro = RealOrder(
                    user_id=current_user.id,
                    binance_order_id=order_report.get('orderId'),
                    symbol=order_report.get('symbol'),
                    side=order_report.get('side'),
                    type=order_report.get('type'),
                    quantity=float(order_report.get('origQty', 0)),
                    price=float(order_report.get('price')) if float(order_report.get('price', 0) or 0) > 0 else None,
                    stop_price=float(order_report.get('stopPrice')) if float(order_report.get('stopPrice', 0) or 0) > 0 else None,
                    status=order_report.get('status'),
                    executed_qty=float(order_report.get('executedQty', 0)),
                    commission=0,
                    order_response=str(order_report),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(ro)
            
            db.session.commit()
            trigger_portfolio_snapshot(current_user.id, current_user.username)
            
            logger.info(f"Real OCO order placed for user {current_user.id}: {symbol} {side} {quantity}")
            
            return jsonify({
                'success': True,
                'orderListId': order_list_id,
                'orders': order_response['orderReports'],
                'message': 'Real OCO order placed successfully'
            })
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to place real OCO order: {error_msg}\n{traceback.format_exc()}")
            if "API-key" in error_msg or "Invalid Api-Key" in error_msg or "invalid api-key" in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'OCO order placement failed: {error_msg}'}), 400

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error in place_real_oco_order: {err_msg}\n{traceback.format_exc()}")
        db.session.rollback()
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500


# AI Trading Integration Endpoints

@app.route('/api/test-simple')
def api_test_simple():
    """Simple test endpoint"""
    return jsonify({"test": "success", "message": "Simple test endpoint is working"})

@app.route('/api/test-db')
@login_required
def api_test_db():
    """Test database connection and user lookup using ORM"""
    try:
        logger.info('=== Testing database connection ===')
        from credentials import User, UserSetting
        
        # Test user lookup
        user = User.query.filter_by(username=current_user.username).first()
        
        if user:
            user_id = user.id
            logger.info(f'=== User found: {user_id} ===')
            
            # Test inserting/updating a setting using ORM
            setting = UserSetting.query.filter_by(user_id=user_id, setting_key='test_key').first()
            if not setting:
                setting = UserSetting(user_id=user_id, setting_key='test_key', setting_value='test_value')
                db.session.add(setting)
            else:
                setting.setting_value = 'test_value'
            
            db.session.commit()
            
            return jsonify({"success": True, "user_id": user_id, "message": "Database test successful"})
        else:
            return jsonify({"error": "User not found"}), 404
            
    except Exception as e:
        print(f'=== Database test error: {e} ===', flush=True)
        import traceback
        print(f'=== Traceback: {traceback.format_exc()} ===', flush=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/ai/market-analysis')
@login_required
def api_ai_market_analysis():
    """Get overall market analysis using OpenAI with caching"""
    try:
        # Check cache first
        cache_key = f"market_analysis_{current_user.id}"
        cached_result = get_ai_cache(current_user.id, cache_key, "market_analysis")
        
        if cached_result:
            logger.info(f"Returning cached market analysis for user {current_user.id}")
            return jsonify(cached_result)
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            logger.info(f"AI is disabled for user {current_user.id}")
            return jsonify({
                "sentiment": "neutral",
                "risk_level": "moderate", 
                "confidence": 50,
                "summary": "AI analysis is disabled. Enable AI in Settings to use this feature.",
                "full_analysis": "AI analysis is disabled.",
                "key_insights": ["AI is disabled", "Enable AI in Settings", "Check AI killswitch setting"]
            })
        
        # Check if we're in the analysis window or if this is a manual request
        user_settings = get_user_ai_settings(current_user.username)
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59')
        
        if not is_user_analysis_window_active(analysis_window_start, analysis_window_end):
            logger.info(f"Outside analysis window for user {current_user.id}")
            return jsonify({
                "sentiment": "neutral",
                "risk_level": "moderate", 
                "confidence": 50,
                "summary": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use 'Run Analysis Now' for manual analysis.",
                "full_analysis": "Outside scheduled analysis window.",
                "key_insights": ["Outside analysis window", "Use manual analysis button", f"Window: {analysis_window_start} - {analysis_window_end}"]
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        current_timestamp = format_eastern_datetime(None, "%Y-%m-%d %H:%M:%S EST")
        risk_appetite = user_settings.get('ai_risk_tolerance', 'moderate')
        confidence_threshold = user_settings.get('ai_confidence_threshold', 75)

        prompt = (
            "MARKET_ANALYSIS_DATA\n"
            f"datetime: {current_timestamp}\n"
            f"risk_appetite: {risk_appetite}\n"
            f"confidence_threshold: {confidence_threshold}\n"
        )
        
        # Call AI API with web search (always enabled)
        try:
            # Get model setting
            model = user_settings.get('ai_model', 'gpt-5')
            
            # Get AI prompts from database
            ai_prompts_obj = get_user_ai_prompts(current_user.id)
            system_content = (ai_prompts_obj.market_analysis_post or "").strip() if ai_prompts_obj else ""
            if not system_content:
                return jsonify({
                    "error": "Missing market analysis post prompt. Configure it in Settings."
                }), 400
            
            response, _ = call_ai_with_web_search(
                username=current_user.username,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                model=model,
                user_id=current_user.id,
                prompt_type="market_analysis",
                include_db_context=False
            )
            
            analysis = response.choices[0].message.content
            
            # Log the AI conversation
            log_ai_conversation(current_user.id, "market_analysis", "user", prompt)
            log_ai_conversation(current_user.id, "market_analysis", "ai", analysis)
            
            # Parse the response to extract structured data
            result = {
                "sentiment": extract_sentiment(analysis),
                "risk_level": extract_risk_level(analysis),
                "confidence": extract_confidence(analysis),
                "summary": analysis[:200] + "..." if len(analysis) > 200 else analysis,
                "full_analysis": analysis,
                "key_insights": extract_key_insights(analysis)
            }
            
            # Cache the result
            cache_duration = user_settings.get('ai_cache_duration_hours', 4)
            set_ai_cache(current_user.id, cache_key, "market_analysis", result, cache_duration)
            
            # Update analysis schedule
            update_ai_analysis_schedule(current_user.id)
            
            return jsonify(result)
            
        except Exception as openai_error:
            logger.error(f"OpenAI API error: {openai_error}")
            return jsonify({"error": "Failed to get AI analysis"}), 500
            
    except Exception as e:
        logger.error(f"Error in market analysis: {str(e)}")
        return jsonify({"error": str(e)}), 500

def get_portfolio_data_for_user(user_id):
    """Helper function to get comprehensive portfolio data from all crypto databases
    
    Args:
        user_id: ID of the user
    """
    logger.error(f"[PORTFOLIO_DEBUG] get_portfolio_data_for_user called for {user_id}")
    try:
        def get_cost_basis_from_transactions(user_id):
            """Derive current cost basis for each asset from transaction history."""
            try:
                from trading_models import AllActivity
                # Query all_activities using ORM
                rows = AllActivity.query.filter(
                    AllActivity.user_id == user_id,
                    AllActivity.asset.isnot(None),
                    AllActivity.asset != ''
                ).order_by(AllActivity.date.asc(), AllActivity.id.asc()).all()

                aggregates = {}
                for row in rows:
                    symbol = (row.asset or '').upper()
                    if not symbol:
                        continue
                    amount = row.amount or 0.0
                    cost_component = row.cost_basis or 0.0
                    info = aggregates.setdefault(symbol, {'quantity': 0.0, 'cost_basis': 0.0})
                    prev_qty = info['quantity']
                    prev_cost = info['cost_basis']
                    if amount > 0:
                        # Purchases increase both quantity and cost basis (include fees)
                        info['quantity'] = prev_qty + amount
                        info['cost_basis'] = prev_cost + max(cost_component, 0.0)
                    elif amount < 0:
                        sold_qty = abs(amount)
                        remaining_qty = max(prev_qty - sold_qty, 0.0)
                        # Use logged cost_basis when available; otherwise fall back to average cost
                        if cost_component and cost_component > 0:
                            reduction = cost_component
                        else:
                            avg_cost = (prev_cost / prev_qty) if prev_qty > 0 else 0.0
                            reduction = avg_cost * sold_qty
                        info['quantity'] = remaining_qty
                        info['cost_basis'] = max(prev_cost - reduction, 0.0)
                    # Ignore zero-amount entries
                    if info['quantity'] < 1e-9:
                        info['quantity'] = 0.0
                    if info['cost_basis'] < 1e-6:
                        info['cost_basis'] = 0.0
                return aggregates
            except Exception as cb_error:
                logger.error(f"Error computing cost basis from transactions for user {user_id}: {cb_error}")
                return {}

        cost_basis_map = get_cost_basis_from_transactions(user_id)

        # Get all coins for the user (including hidden ones to check for auto-unhide)
        all_coins = Coin.query.filter_by(user_id=user_id).all()
        
        portfolio = []
        for coin in all_coins:
            try:
                symbol = coin.symbol.upper()
                amount = float(coin.amount or 0.0)
                
                # Fetch/lookup current price
                if symbol in ['USD', 'USDT', 'USDC', 'DAI']:
                    current_price = 1.0
                else:
                    current_price = coin.current or float(coin.avg_entry or 0)
                
                current_value = amount * current_price if current_price else 0
                
                # Apply visibility check (logical, not necessarily DB update here for speed)
                is_manual_visible = not coin.hidden
                should_be_visible = current_value >= 1.0 or is_manual_visible or coin.force_visible
                
                if not should_be_visible:
                    continue
                    
                # If we're here, the coin should be in the portfolio
                # DO NOT skip stablecoins for portfolio display!
                # Ensure current_price is valid, fallback to avg_entry if needed
                current_price = coin.current if coin.current and coin.current > 0 else (coin.avg_entry or 0)
                current_value = amount * current_price if current_price else 0.0

                cost_info = cost_basis_map.get(coin.symbol.upper())
                if cost_info and cost_info.get('quantity', 0) > 0 and coin.amount > 0:
                    effective_avg_entry = cost_info['cost_basis'] / cost_info['quantity'] if cost_info['quantity'] > 0 else 0.0
                    derived_cost_basis = effective_avg_entry * coin.amount
                elif coin.initial_value and coin.initial_value > 0:
                    effective_avg_entry = (coin.initial_value / coin.amount) if coin.amount else coin.avg_entry or 0
                    derived_cost_basis = coin.initial_value
                else:
                    effective_avg_entry = coin.avg_entry or 0
                    derived_cost_basis = effective_avg_entry * coin.amount if coin.amount else 0
                derived_cost_basis = max(derived_cost_basis, 0.0)

                # Guard against divide-by-zero if holdings are zero
                if coin.amount <= 0:
                    effective_avg_entry = 0
                    derived_cost_basis = 0

                pct_change = 0
                if effective_avg_entry and effective_avg_entry > 0:
                    pct_change = ((current_price - effective_avg_entry) / effective_avg_entry) * 100

                coin_data = {
                    "id": coin.id,
                    "symbol": coin.symbol,
                    "amount": coin.amount,
                    "avg_entry": effective_avg_entry,
                    "initial_value": derived_cost_basis,
                    "purchase_date": coin.purchase_date,
                    "current_price": current_price,
                    "current_value": current_value,
                    "pct_change": pct_change,
                    "sentiment": getattr(coin, 'sentiment', None),
                    "alert_enabled": coin.alert_enabled,
                    "note": coin.note,
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "custom_lower_type": coin.custom_lower_type,
                    "custom_upper_type": coin.custom_upper_type
                }

                portfolio.append(coin_data)
            except Exception as e:
                logger.error(f"Error processing coin {coin.symbol}: {e}", exc_info=True)
                continue
        
        return portfolio
    except Exception as e:
        logger.error(f"Error getting portfolio data: {e}")
        return []

def get_comprehensive_crypto_data_for_user(user_id, limit_transactions=50, days_history=30):
    """Get comprehensive crypto data including portfolio, transactions, and portfolio history using ORM"""
    try:
        from trading_models import AllActivity, PortfolioValueHistory
        data = {
            "portfolio": [],
            "recent_transactions": [],
            "portfolio_value_history": [],
            "summary": {}
        }
        
        # 1. Get Portfolio Holdings
        portfolio_data = get_portfolio_data_for_user(user_id)
        data["portfolio"] = portfolio_data
        
        # 2. Get Recent Transactions using ORM
        transactions = AllActivity.query.filter_by(user_id=user_id).order_by(AllActivity.date.desc()).limit(limit_transactions).all()
        for tx in transactions:
            data["recent_transactions"].append({
                "date": tx.date,
                "type": tx.type,
                "asset": tx.asset,
                "amount": tx.amount,
                "proceeds": tx.proceeds,
                "cost_basis": tx.cost_basis,
                "gain_loss": tx.gain_loss,
                "fee": tx.fee,
                "description": tx.description,
                "txid": tx.txid,
                "status": tx.status,
                "details": tx.details
            })
        
        # 3. Get Portfolio Value History (last N days) using ORM
        cutoff_date = datetime.now() - timedelta(days=days_history)
        history = PortfolioValueHistory.query.filter(
            PortfolioValueHistory.user_id == user_id,
            PortfolioValueHistory.timestamp >= cutoff_date
        ).order_by(PortfolioValueHistory.timestamp.desc()).all()
        
        for entry in history:
            data["portfolio_value_history"].append({
                "timestamp": int(entry.timestamp.timestamp()) if entry.timestamp else 0,
                "date": entry.timestamp.strftime('%Y-%m-%d %H:%M:%S') if entry.timestamp else entry.date,
                "value": entry.value
            })
        
        # 4. Calculate Summary Statistics
        total_portfolio_value = sum(coin.get("current_value", 0) for coin in data["portfolio"])
        total_initial_value = sum(coin.get("initial_value", 0) for coin in data["portfolio"])
        portfolio_pnl = total_portfolio_value - total_initial_value if total_initial_value > 0 else 0
        portfolio_pnl_pct = (portfolio_pnl / total_initial_value * 100) if total_initial_value > 0 else 0
        
        # Calculate recent transaction summary (last 7 days)
        recent_cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        recent_buys = sum(1 for tx in data["recent_transactions"] 
                         if tx["type"] and "buy" in tx["type"].lower() and tx["date"] >= recent_cutoff)
        recent_sells = sum(1 for tx in data["recent_transactions"] 
                          if tx["type"] and "sell" in tx["type"].lower() and tx["date"] >= recent_cutoff)
        
        data["summary"] = {
            "total_coins": len(data["portfolio"]),
            "total_portfolio_value": total_portfolio_value,
            "total_initial_value": total_initial_value,
            "portfolio_pnl": portfolio_pnl,
            "portfolio_pnl_pct": portfolio_pnl_pct,
            "recent_transactions_count": len(data["recent_transactions"]),
            "recent_buys_7d": recent_buys,
            "recent_sells_7d": recent_sells,
            "portfolio_history_days": len(data["portfolio_value_history"])
        }
        
        logger.info(f"Comprehensive crypto data retrieved for user {user_id}: "
                   f"{data['summary']['total_coins']} coins, "
                   f"{data['summary']['recent_transactions_count']} transactions, "
                   f"{data['summary']['portfolio_history_days']} history points")
        
        return data
        
    except Exception as e:
        logger.error(f"Error getting comprehensive crypto data: {e}")
        return {
            "portfolio": [],
            "recent_transactions": [],
            "portfolio_value_history": [],
            "summary": {"error": str(e)}
        }

def get_watchlist_data_for_user(user_id, exchange='binance'):
    """Helper function to get watchlist data directly from database
    
    Args:
        user_id: ID of the user
        exchange: Exchange name ('binance'), defaults to 'binance'
    """
    try:
        watchlist_coins = WatchlistCoin.query.filter_by(
            user_id=user_id, 
            hidden=False,
            exchange=exchange
        ).all()
        
        watchlist = []
        
        for coin in watchlist_coins:
            try:
                # Skip stablecoins for AI analysis
                if is_stablecoin(coin.symbol):
                    logger.info(f"Skipping stablecoin {coin.symbol} for AI analysis")
                    continue
                    
                current_price = coin.current_price if coin.current_price and coin.current_price > 0 else 0
                
                coin_data = {
                    "id": coin.id,
                    "symbol": coin.symbol,
                    "exchange": coin.exchange or 'binance',  # Default to binance
                    "current_price": current_price,
                    "down_alert": coin.down_alert,
                    "up_alert": coin.up_alert,
                    "alert_enabled": coin.alert_enabled,
                    "note": coin.note,
                    "favorite": coin.favorite,
                    "action": coin.action,
                    "sentiment": getattr(coin, 'sentiment', None),
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "custom_lower_type": coin.custom_lower_type,
                    "custom_upper_type": coin.custom_upper_type
                }
                
                watchlist.append(coin_data)
            except Exception as e:
                logger.error(f"Error processing watchlist coin {coin.symbol}: {e}")
                continue
        
        return watchlist
    except Exception as e:
        logger.error(f"Error getting watchlist data: {e}")
        return []

@app.route('/api/ai/recommendations')
@login_required
def api_ai_recommendations():
    """Get AI trading recommendations using OpenAI with caching"""
    try:
        # Check cache first
        cache_key = f"recommendations_{current_user.id}"
        cached_result = get_ai_cache(current_user.id, cache_key, "recommendations")
        
        if cached_result:
            logger.info(f"Returning cached recommendations for user {current_user.id}")
            return jsonify(cached_result)
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            logger.info(f"AI is disabled for user {current_user.id}")
            return jsonify({
                "recommendations": [],
                "message": "AI analysis is disabled. Enable AI in Settings to use this feature."
            })
        
        # Check analysis frequency and usage limits
        user_settings = get_user_ai_settings(current_user.username)
        analysis_frequency = user_settings.get('ai_analysis_frequency', 'daily')
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59') if analysis_frequency == 'hourly' else '23:59'
        
        # Check for recent manual analysis (within last 30 minutes)
        recent_analysis = False
        daily_analysis_done = False
        
        try:
            # Use SQLAlchemy ORM instead of legacy SQLite
            from datetime import datetime, timedelta
            
            # Check for RECENT (cooldown) logic regardless of frequency
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            recent_count = AIConversation.query.filter(
                AIConversation.user_id == current_user.id,
                AIConversation.prompt_type == 'market_analysis',
                AIConversation.created_at >= cutoff
            ).count()
            recent_analysis = recent_count > 0

            # Daily Frequency Logic: Check if ANY analysis occurred TODAY
            if analysis_frequency == 'daily':
                # Get start of day in Eastern Time (approximated by server time for now, or use get_eastern_now if available contextually)
                # Using server local time for consistency with database logging usually
                now_local = datetime.now()
                start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                
                daily_count = AIConversation.query.filter(
                    AIConversation.user_id == current_user.id,
                    AIConversation.prompt_type == 'market_analysis',
                    AIConversation.sender == 'ai', # Only count completed AI responses
                    AIConversation.created_at >= start_of_day
                ).count()
                
                if daily_count > 0:
                    daily_analysis_done = True

        except Exception as e:
            logger.error(f"Error checking recent analysis: {e}")
        
        # If Daily and one is done -> Stop.
        if analysis_frequency == 'daily' and daily_analysis_done:
            logger.info(f"Daily analysis already completed for user {current_user.id}")
            return jsonify({
                "recommendations": [],
                "message": "Daily analysis already completed for today. Check back tomorrow or use 'Run Analysis Now'."
            })

        # Check window
        if not is_user_analysis_window_active(analysis_window_start, analysis_window_end) and not recent_analysis:
            logger.info(f"Outside analysis window and no recent analysis for user {current_user.id}")
            return jsonify({
                "recommendations": [],
                "message": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use 'Run Analysis Now' for manual analysis."
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        confidence_threshold = user_settings.get('ai_confidence_threshold', 75)
        
        # Get portfolio data to analyze (excluding stablecoins)
        portfolio = get_portfolio_data_for_user(current_user.id)
        non_stablecoin_portfolio = [coin for coin in portfolio if not is_stablecoin(coin.get('symbol', ''))]
        
        # If only stablecoins in portfolio, return empty recommendations
        if not non_stablecoin_portfolio:
            logger.info(f"Only stablecoins in portfolio for user {current_user.id}, skipping recommendations")
            return jsonify({
                "recommendations": [],
                "message": "Portfolio contains only stablecoins. No trading recommendations needed for stable assets."
            })
        
        # Get risk assessment request prompt template (no hardcoded defaults)
        recommendations = []
        
        # Get model setting
        model = user_settings.get('ai_model', 'gpt-5')
        
        # Analyze each coin in portfolio (excluding stablecoins)
        for coin in non_stablecoin_portfolio[:5]:  # Limit to top 5 non-stablecoin coins
            try:
                symbol = coin['symbol']
                current_price = coin.get('current_price', 0)
                
                if current_price <= 0:
                    continue
                
                # Get price history
                price_data = get_last_7d_prices(symbol)
                if not price_data or len(price_data) < 2:
                    continue
                
                # Calculate basic technical indicators
                price_change = ((price_data[-1] - price_data[0]) / price_data[0]) * 100
                volatility = calculate_volatility(price_data)
                
                # Create AI prompt for this specific coin
                full_prompt = (
                    "RISK_ASSESSMENT_DATA\n"
                    f"symbol: {symbol}\n"
                    f"current_price: {current_price}\n"
                    f"price_change: {price_change}\n"
                    f"volatility: {volatility}\n"
                    f"amount: {coin.get('amount', 0)}\n"
                    f"current_value: {coin.get('current_value', 0)}\n"
                    f"risk_tolerance: {user_settings.get('ai_risk_tolerance', 'moderate')}\n"
                )
                
                # Call AI API with web search (always enabled)
                try:
                    # Get AI prompts from database
                    ai_prompts_obj = get_user_ai_prompts(current_user.id)
                    system_content = (ai_prompts_obj.risk_assessment_post or "").strip() if ai_prompts_obj else ""
                    if not system_content:
                        raise ValueError("Missing risk assessment post prompt. Configure it in Settings.")
                    
                    response, _ = call_ai_with_web_search(
                        username=current_user.username,
                        messages=[
                            {"role": "system", "content": system_content},
                            {"role": "user", "content": full_prompt}
                        ],
                        model=model,
                        user_id=current_user.id,
                        prompt_type="risk_assessment",
                        symbol=symbol
                    )
                    
                    analysis = response.choices[0].message.content
                    
                    # Log the AI conversation
                    log_ai_conversation(current_user.id, "risk_assessment", "user", full_prompt)
                    log_ai_conversation(current_user.id, "risk_assessment", "ai", analysis)
                    
                    # Parse the AI response
                    signal, confidence, entry_price, stop_loss, take_profit, reasoning = parse_ai_recommendation(analysis, current_price)
                    
                    # Only include if confidence meets threshold
                    if confidence >= confidence_threshold:
                        recommendations.append({
                            "symbol": symbol,
                            "signal": signal,
                            "confidence": round(confidence, 1),
                            "current_price": round(current_price, 2),
                            "price_change": round(price_change, 2),
                            "entry_price": round(entry_price, 2),
                            "stop_loss": round(stop_loss, 2),
                            "take_profit": round(take_profit, 2),
                            "reasoning": reasoning,
                            "ai_analysis": analysis
                        })
                        
                except Exception as openai_error:
                    logger.error(f"OpenAI API error for {symbol}: {openai_error}")
                    # Fallback to basic analysis
                    signal, confidence, entry_price, stop_loss, take_profit, reasoning = basic_recommendation_analysis(price_change, volatility, current_price)
                    
                    if confidence >= confidence_threshold:
                        recommendations.append({
                            "symbol": symbol,
                            "signal": signal,
                            "confidence": round(confidence, 1),
                            "current_price": round(current_price, 2),
                            "price_change": round(price_change, 2),
                            "entry_price": round(entry_price, 2),
                            "stop_loss": round(stop_loss, 2),
                            "take_profit": round(take_profit, 2),
                            "reasoning": reasoning
                        })
                    
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue
        
        # Sort by confidence
        recommendations.sort(key=lambda x: x['confidence'], reverse=True)
        
        result = {
            "recommendations": recommendations,
            "total": len(recommendations)
        }
        
        # Cache the result
        cache_duration = user_settings.get('ai_cache_duration_hours', 4)
        set_ai_cache(current_user.id, cache_key, "recommendations", result, cache_duration)
        
        # Update analysis schedule
        update_ai_analysis_schedule(current_user.id)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/ai/portfolio-analysis')
@login_required
def api_ai_portfolio_analysis():
    """Get AI portfolio analysis using OpenAI with caching"""
    try:
        # Check cache first
        cache_key = f"portfolio_analysis_{current_user.id}"
        cached_result = get_ai_cache(current_user.id, cache_key, "portfolio_analysis")
        
        if cached_result:
            logger.info(f"Returning cached portfolio analysis for user {current_user.id}")
            return jsonify(cached_result)
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            logger.info(f"AI is disabled for user {current_user.id}")
            return jsonify({
                "health_score": 50,
                "diversification_score": 50,
                "risk_adjusted_return": 50,
                "recommendations": ["AI analysis is disabled. Enable AI in Settings to use this feature."],
                "ai_analysis": "AI analysis is disabled."
            })
        
        # Check if analysis should run
        if not should_run_ai_analysis(current_user.id) and not is_analysis_window_active():
            logger.info(f"AI analysis not scheduled for user {current_user.id}")
            return jsonify({
                "health_score": 50,
                "diversification_score": 50,
                "risk_adjusted_return": 50,
                "recommendations": ["Analysis not scheduled. Use 'Run Analysis Now' button for manual analysis."],
                "ai_analysis": "Analysis not scheduled."
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        
        # Get portfolio data (excluding stablecoins)
        portfolio = get_portfolio_data_for_user(current_user.id)
        non_stablecoin_portfolio = [coin for coin in portfolio if not is_stablecoin(coin.get('symbol', ''))]
        
        if not portfolio:
            return jsonify({
                "health_score": 0,
                "diversification_score": 0,
                "risk_adjusted_return": 0,
                "recommendations": ["No portfolio data available for analysis"]
            })
        
        # If only stablecoins in portfolio, return special analysis
        if not non_stablecoin_portfolio:
            logger.info(f"Only stablecoins in portfolio for user {current_user.id}, returning stablecoin analysis")
            return jsonify({
                "health_score": 100,
                "diversification_score": 50,
                "risk_adjusted_return": 100,
                "recommendations": [
                    "Portfolio contains only stablecoins",
                    "Stablecoins provide price stability but limited growth potential",
                    "Consider adding some volatile assets for growth opportunities",
                    "Current portfolio is very low risk"
                ],
                "ai_analysis": "Portfolio consists entirely of stablecoins, which are designed to maintain a stable value. This provides excellent price stability but limited growth potential. Consider diversifying with some volatile assets for growth opportunities."
            })
        
        # Calculate basic portfolio metrics (NO initial_value)
        total_value = sum(coin.get('current_value', 0) for coin in portfolio)
        # Build summary with amount and current value for each coin
        portfolio_summary = []
        for coin in portfolio:
            symbol = coin['symbol']
            amount = coin.get('amount', 0)
            current_price = coin.get('current_price', 0)
            current_value = coin.get('current_value', 0)
            portfolio_summary.append(f"{symbol}: {amount:.6f} @ ${current_price:.2f} = ${current_value:.2f}")
        portfolio_summary_text = "\n".join(portfolio_summary)
        prompt = (
            "PORTFOLIO_REVIEW_DATA\n"
            f"total_coins: {len(portfolio)}\n"
            f"total_value: {total_value}\n"
            f"risk_tolerance: {user_settings.get('ai_risk_tolerance', 'moderate')}\n"
            f"confidence_threshold: {user_settings.get('ai_confidence_threshold', 75)}\n"
            "portfolio_summary:\n"
            f"{portfolio_summary_text}\n"
        )
        
        # Call OpenAI API with web search
        try:
            # Get model setting
            model = user_settings.get('ai_model', 'gpt-5')
            
            # Get AI prompts from database
            ai_prompts_obj = get_user_ai_prompts(current_user.id)
            system_content = (ai_prompts_obj.portfolio_review_post or "").strip() if ai_prompts_obj else ""
            if not system_content:
                return jsonify({
                    "error": "Missing portfolio review post prompt. Configure it in Settings."
                }), 400
            
            response, _ = call_ai_with_web_search(
                username=current_user.username,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                model=model,
                user_id=current_user.id,
                prompt_type="portfolio_review"
            )
            
            analysis = response.choices[0].message.content
            
            # Log the AI conversation
            log_ai_conversation(current_user.id, "portfolio_review", "user", prompt)
            log_ai_conversation(current_user.id, "portfolio_review", "ai", analysis)
            
            # Parse the AI response
            health_score, diversification_score, risk_adjusted_return, recommendations = parse_portfolio_analysis(analysis)
            
            result = {
                "health_score": round(health_score, 1),
                "diversification_score": round(diversification_score, 1),
                "risk_adjusted_return": round(risk_adjusted_return, 1),
                "recommendations": recommendations,
                "ai_analysis": analysis
            }
            
            # Cache the result
            cache_duration = user_settings.get('ai_cache_duration_hours', 4)
            set_ai_cache(current_user.id, cache_key, "portfolio_analysis", result, cache_duration)
            
            # Update analysis schedule
            update_ai_analysis_schedule(current_user.id)
            
            return jsonify(result)
            
        except Exception as openai_error:
            logger.error(f"OpenAI API error: {openai_error}")
            # Fallback to basic analysis
            return basic_portfolio_analysis(portfolio, total_value, total_initial_value)
            
    except Exception as e:
        logger.error(f"Error in portfolio analysis: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/ai/market-analysis/<symbol>')
@login_required
def api_ai_symbol_analysis(symbol):
    """Get detailed AI analysis for a specific symbol"""
    try:
        # Get price data
        price_data = get_last_7d_prices(symbol)
        if not price_data or len(price_data) < 2:
            return jsonify({"error": "Insufficient price data"}), 400
        
        snapshot = calculate_symbol_snapshot(symbol)
        if not snapshot:
            return jsonify({"error": "Insufficient price data"}), 400

        reasoning = (
            f"Analysis of {symbol} shows a {snapshot['price_change_7d']:.1f}% price change over 7 days. "
            f"Current price is ${snapshot['current_price']:.2f} with {snapshot['volatility']:.1%} volatility. "
            f"Technical indicators suggest a {snapshot['signal'].lower()} signal with {snapshot['confidence']}% confidence. "
            f"Recommended entry at ${snapshot['entry_price']:.2f} with stop loss at ${snapshot['stop_loss']:.2f} "
            f"and take profit at ${snapshot['take_profit']:.2f}."
        )

        return jsonify({
            "symbol": symbol,
            "signal": snapshot['signal'],
            "overall_confidence": snapshot['confidence'],
            "sentiment_score": max(0, min(100, 50 + (snapshot['price_change_7d'] * 2))),
            "risk_level": max(0, min(100, int(snapshot['volatility'] * 100))),
            "current_price": snapshot['current_price'],
            "entry_price": snapshot['entry_price'],
            "stop_loss": snapshot['stop_loss'],
            "take_profit": snapshot['take_profit'],
            "technical_indicators": snapshot['technical_indicators'],
            "price_metrics": {
                "pct_1d": snapshot['pct_1d'],
                "pct_3d": snapshot['pct_3d'],
                "pct_7d": snapshot['pct_7d']
            },
            "patterns": snapshot['patterns'],
            "reasoning": reasoning,
            "risk_factors": snapshot['risk_factors'],
            "recommendation": {
                "signal": snapshot['signal'],
                "confidence": snapshot['confidence'],
                "technical_score": snapshot['technical_score'],
                "risk_penalty": max(0, min(20, int(snapshot['volatility'] * 100)))
            },
            "data_source": "price_history (Binance.US 7d hourly)",
            "series_window": {
                "points": len(price_data)
            }
        })
        
    except Exception as e:
        logger.error(f"Error in symbol analysis: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/ai/smart-alerts')
@login_required
def api_ai_smart_alerts():
    """Get smart alerts based on AI analysis"""
    try:
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            return jsonify({
                'alerts': [],
                'total': 0,
                'high_priority': 0,
                'message': 'AI analysis is disabled. Enable AI in Settings to use this feature.'
            })
        
        # Check if we're in the analysis window OR if there's recent analysis activity
        # Check analysis frequency and settings
        user_settings = get_user_ai_settings(current_user.username)
        analysis_frequency = user_settings.get('ai_analysis_frequency', 'daily')
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59') if analysis_frequency == 'hourly' else '23:59'
        
        # Check for recent manual analysis (within last 30 minutes)
        recent_analysis = False
        daily_analysis_done = False
        
        try:
            # Use SQLAlchemy ORM instead of legacy SQLite
            from datetime import datetime, timedelta
            
            # Check for RECENT (cooldown) logic
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            recent_count = AIConversation.query.filter(
                AIConversation.user_id == current_user.id,
                AIConversation.prompt_type == 'market_analysis',
                AIConversation.created_at >= cutoff
            ).count()
            recent_analysis = recent_count > 0

            # Daily Frequency Logic: Check if ANY analysis occurred TODAY
            if analysis_frequency == 'daily':
                # Get start of day in Eastern Time (approximated by server time)
                now_local = datetime.now()
                start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                
                daily_count = AIConversation.query.filter(
                    AIConversation.user_id == current_user.id,
                    AIConversation.prompt_type == 'market_analysis',
                    AIConversation.sender == 'ai',
                    AIConversation.created_at >= start_of_day
                ).count()
                
                if daily_count > 0:
                    daily_analysis_done = True
                    
        except Exception as e:
            logger.error(f"Error checking recent analysis: {e}")
        
        # If Daily and one is done -> Stop, unless we want alerts to be checked regardless? 
        # Usually smart alerts are DERIVED from analysis. If analysis is done, we might just want to RETURN the alerts from database?
        # But for now let's respect the user request to not "trigger" things multiple times.
        if analysis_frequency == 'daily' and daily_analysis_done:
             # Just return existing alerts if available, or empty if we consider the "Action" of checking to be the trigger.
             # Ideally we should fetch stored alerts. But the current implementation generates them on the fly?
             # Line 15922: alerts = generate_smart_alerts_for_user(current_user.id)
             # Let's assume generate_smart_alerts checks DB.
             # If the user's main complaint is "API USAGE", we should avoid calls.
             # generate_smart_alerts might call LLM if not cached?
             pass 

        if not is_user_analysis_window_active(analysis_window_start, analysis_window_end) and not recent_analysis:
            return jsonify({
                'alerts': [],
                'total': 0,
                'high_priority': 0,
                'message': f'Analysis window: {analysis_window_start} - {analysis_window_end}. Use "Run Analysis Now" for manual analysis.'
            })
        
        alerts = generate_smart_alerts_for_user(current_user.id)
        return jsonify({
            'alerts': alerts,
            'total': len(alerts),
            'high_priority': len([a for a in alerts if a.get('priority') == 'high'])
        })
    except Exception as e:
        logger.error(f"Error in smart alerts: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/recommendation-score/<symbol>')
@login_required
def api_ai_recommendation_score(symbol):
    """Get detailed recommendation scoring for a specific symbol"""
    try:
        # Get price data
        price_data = get_last_7d_prices(symbol)
        if not price_data or len(price_data) < 7:
            return jsonify({'error': 'Insufficient price data'}), 400
        
        # Get sentiment
        sentiment = fetch_news_sentiment(symbol)
        
        # Calculate volatility
        returns = [(price_data[i] - price_data[i-1]) / price_data[i-1] for i in range(1, len(price_data))]
        volatility = np.std(returns) if returns else 0
        
        # Prepare analysis data
        analysis_data = {
            'price_data': price_data,
            'sentiment': sentiment,
            'volatility': volatility,
            'portfolio_correlation': 0.5,  # Placeholder - could be calculated vs user's portfolio
            'market_timing': 0.6  # Placeholder - could be based on market cycles
        }
        
        # Score the recommendation
        confidence_score = score_recommendation(symbol, analysis_data)
        
        # Get technical indicators
        sma_7 = np.mean(price_data[-7:])
        sma_14 = np.mean(price_data[-14:]) if len(price_data) >= 14 else sma_7
        current_price = price_data[-1]
        
        # Calculate RSI
        gains = [max(price_data[i] - price_data[i-1], 0) for i in range(1, len(price_data))]
        losses = [max(price_data[i-1] - price_data[i], 0) for i in range(1, len(price_data))]
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs))
        
        return jsonify({
            'symbol': symbol,
            'confidence_score': round(confidence_score, 1),
            'technical_indicators': {
                'sma_7': round(sma_7, 2),
                'sma_14': round(sma_14, 2),
                'rsi': round(rsi, 1),
                'current_price': round(current_price, 2)
            },
            'sentiment_score': round(abs(sentiment) * 100, 1),
            'volatility_score': round((1 - volatility) * 100, 1),
            'analysis_factors': {
                'trend_strength': 'strong_uptrend' if current_price > sma_7 > sma_14 else 'strong_downtrend' if current_price < sma_7 < sma_14 else 'sideways',
                'momentum': 'bullish' if current_price > sma_7 else 'bearish',
                'rsi_signal': 'oversold' if rsi < 30 else 'overbought' if rsi > 70 else 'neutral'
            }
        })
        
    except Exception as e:
        logger.error(f"Error in recommendation scoring: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/background-jobs', methods=['GET'])
@login_required
def debug_background_jobs():
    """Debug endpoint to check and restart background jobs"""
    try:
        # Ensure background jobs are running
        jobs_running = ensure_background_jobs()
        
        # Get status of all background threads
        thread_status = []
        for i, t in enumerate(background_threads):
            thread_status.append({
                'id': i,
                'name': t.name,
                'alive': t.is_alive(),
                'daemon': t.daemon,
                'ident': t.ident
            })
        
        return jsonify({
            'success': True,
            'jobs_running': jobs_running,
            'threads': thread_status,
            'thread_count': len(background_threads)
        })
    except Exception as e:
        logger.error(f"Error checking background jobs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/ai/conversations')
@login_required
def api_ai_conversations():
    """Get AI conversations for user with optional filtering"""
    try:
        # Check if user is authenticated
        if not current_user.is_authenticated:
            logger.error("User not authenticated for AI conversations")
            return jsonify({'error': 'User not authenticated'}), 401
        
        limit = request.args.get('limit', 10, type=int)  # Default to 10 for pagination
        offset = request.args.get('offset', 0, type=int)
        search_term = request.args.get('search', None)
        include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
        filter_sentiment = request.args.get('filter_sentiment', 'false').lower() == 'true'
        prompt_type_filter = request.args.get('prompt_type')
        
        logger.info(f"Getting AI conversations for user {current_user.id}, limit={limit}, offset={offset}, filter_sentiment={filter_sentiment}")
        
        conversations = get_ai_conversations(
            current_user.id, 
            limit, 
            offset, 
            search_term, 
            include_hidden,
            filter_sentiment,
            prompt_type_filter
        )
        
        # Get total count with the same filters
        total_count = get_ai_conversations_count(
            current_user.id, 
            search_term, 
            include_hidden,
            filter_sentiment,
            prompt_type_filter
        )
        
        logger.info(f"Retrieved {len(conversations)} conversations out of {total_count} total")
        
        return jsonify({
            'conversations': conversations,
            'total': total_count,
            'has_more': (offset + len(conversations)) < total_count,
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        logger.error(f"Error getting AI conversations: {e}")
        # Return empty conversations instead of 500 error
        return jsonify({
            'conversations': [],
            'total': 0,
            'error': 'Failed to load conversations'
        })

@app.route('/api/ai/conversation', methods=['POST'])
@login_required
def api_ai_conversation():
    """Process user message and get AI response"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        conversation_id = data.get('conversation_id', None)
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Process the conversation
        ai_response, conversation_id = process_ai_conversation(current_user.id, message, conversation_id)
        
        return jsonify({
            'response': ai_response,
            'conversation_id': conversation_id
        })
        
    except Exception as e:
        logger.error(f"Error processing AI conversation: {e}")
        return jsonify({
            'response': 'I apologize, but I encountered an error processing your request. Please try again later.',
            'conversation_id': conversation_id
        })

@app.route('/api/ai/conversations/<int:message_id>', methods=['DELETE'])
@login_required
def api_delete_ai_conversation(message_id):
    """Delete a specific AI conversation message using ORM"""
    try:
        from models import AIConversation
        # Find the message and verify ownership
        message = AIConversation.query.filter_by(id=message_id, user_id=current_user.id).first()
        
        if not message:
            return jsonify({'error': 'Message not found or access denied'}), 404
        
        # Delete the message
        db.session.delete(message)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting AI conversation: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/conversations/<int:message_id>/archive', methods=['PATCH'])
@login_required
def api_archive_ai_conversation(message_id):
    """Archive a specific AI conversation message using ORM"""
    try:
        from models import AIConversation
        # Find the message and verify ownership
        message = AIConversation.query.filter_by(id=message_id, user_id=current_user.id).first()
        
        if not message:
            return jsonify({'error': 'Message not found or access denied'}), 404
        
        # Archive the message (set is_hidden = True)
        message.is_hidden = True
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error archiving AI conversation: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/news-analysis', methods=['POST'])
@login_required
def api_ai_news_analysis():
    """Get AI news analysis for a specific coin using 3-stage agentic workflow with coin_analysis prompts"""
    try:
        data = request.get_json()
        symbol = data.get('symbol', '').upper()
        use_cache = data.get('use_cache', False)
        force_fresh = data.get('force_fresh', False)
        
        if not symbol:
            return jsonify({'error': 'Symbol is required'}), 400
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            return jsonify({
                'error': 'AI analysis is disabled. Enable AI in Settings to use this feature.'
            }), 400
        
        # Check for cached analysis if use_cache is True and not forcing fresh
        if use_cache and not force_fresh:
            try:
                # Get coin_id for this symbol and user (check both portfolio and watchlist)
                coin_id = get_coin_id_by_symbol(symbol, current_user.id)
                
                # If not in portfolio, check if it's in watchlist
                if not coin_id:
                    from models import WatchlistCoin
                    watchlist_coin = WatchlistCoin.query.filter_by(
                        user_id=current_user.id, 
                        symbol=symbol.upper(),
                        hidden=False
                    ).first()
                    
                    if not watchlist_coin:
                        return jsonify({
                            'error': f'Coin {symbol} not found in your portfolio or watchlist.',
                            'no_coin': True
                        }), 404
                
                # Check ai_conversations for recent coin analysis (last 2 hours) by coin_id
                from datetime import datetime, timedelta
                cutoff_time = datetime.utcnow() - timedelta(hours=2)
                
                # Use SQLAlchemy ORM instead of legacy SQLite
                cached_row = AIConversation.query.filter(
                    AIConversation.user_id == current_user.id,
                    AIConversation.coin_id == coin_id,
                    AIConversation.prompt_type == 'coin_analysis',
                    AIConversation.sender == 'ai',
                    AIConversation.created_at >= cutoff_time
                ).order_by(AIConversation.id.desc()).first()
                
                if cached_row:
                    cached_analysis = cached_row.body
                    # Format the timestamp
                    try:
                        timestamp_formatted = cached_row.created_at.strftime("%B %d, %Y at %I:%M %p UTC") if cached_row.created_at else "Unknown"
                    except Exception:
                        timestamp_formatted = str(cached_row.created_at)
                    
                    return jsonify({
                        'symbol': symbol,
                        'analysis': cached_analysis,
                        'timestamp': timestamp_formatted,
                        'prompt_used': 'Cached analysis',
                        'cached': True
                    })
                else:
                    # NO CACHE EXISTS - Return error instead of falling back to fresh analysis
                    return jsonify({
                        'error': f'No cached analysis found for {symbol}. Use the refresh button (🔄) to generate fresh analysis.',
                        'no_cache': True
                    }), 404
            except Exception as cache_error:
                logger.warning(f"Cache check failed for {symbol}: {cache_error}")
                return jsonify({
                    'error': f'Cache check failed for {symbol}. Use the refresh button (🔄) to generate fresh analysis.',
                    'cache_error': True
                }), 500
        
        # Get user's AI prompts from database (NO HARDCODING)
        ai_prompts_obj = get_user_ai_prompts(current_user.id)
        if not ai_prompts_obj:
            return jsonify({
                'error': 'No AI prompts configured. Please check your settings.'
            }), 400
            
        # Use coin_analysis prompts for the 3-stage workflow
        coin_pre_prompt = ai_prompts_obj.coin_analysis_pre
        coin_post_prompt = ai_prompts_obj.coin_analysis_post
        if not coin_pre_prompt or not coin_post_prompt:
            return jsonify({'error': 'coin_analysis_pre and coin_analysis_post must be set in the database.'}), 400

        # Replace placeholders
        current_datetime = format_eastern_datetime(None, "%B %d, %Y at %I:%M %p EST")
        coin_pre_prompt = coin_pre_prompt.replace('{symbol}', symbol).replace('{datetime}', current_datetime)
        coin_post_prompt = coin_post_prompt.replace('{symbol}', symbol).replace('{datetime}', current_datetime)

        # Get model setting
        user_settings = get_user_ai_settings(current_user.username)
        model = user_settings.get('ai_model', 'gpt-5')

        # Capture current_user attributes before threading (Flask-Login context not available in threads)
        username = current_user.username
        user_id = current_user.id

        # === Gather coin data for the specific symbol ===
        from models import Coin
        coin_obj = Coin.query.filter_by(user_id=user_id, symbol=symbol, hidden=False).first()
        
        # Get coin_id for logging
        coin_id = coin_obj.id if coin_obj else None

        # Prepare the user's original message for the 3-stage agentic workflow
        original_user_message = (
            "NEWS_ANALYSIS_DATA\n"
            f"symbol: {symbol}\n"
            f"datetime: {current_datetime}\n"
        )

        try:
            # Call the 3-stage agentic workflow with proper message structure
            # The call_ai_with_web_search function will:
            # 1. Use coin_analysis_pre for Stage 1 (search query generation)
            # 2. Execute web searches in Stage 2
            # 3. Use coin_analysis_post for Stage 3 (final analysis with search results)
            ai_response, stage3_prompt = call_ai_with_web_search(
                username=username,
                messages=[{"role": "user", "content": original_user_message}],
                model=model,
                user_id=user_id,
                prompt_type="coin_analysis",
                symbol=symbol,
                amount=coin_obj.amount if coin_obj else None
            )

            if not ai_response:
                raise Exception("No response received from AI analysis")

            analysis = ai_response.choices[0].message.content

            # Log the AI conversation for copilot sidebar with proper timing
            log_ai_conversation(user_id, "coin_analysis", "user", original_user_message, symbol=symbol, coin_id=coin_id)
            time.sleep(0.1)
            log_ai_conversation(user_id, "coin_analysis", "ai", analysis, symbol=symbol, coin_id=coin_id)

            return jsonify({
                'symbol': symbol,
                'analysis': analysis,
                'timestamp': current_datetime,
                'prompt_used': f"Coin Pre: {coin_pre_prompt[:100]}..., Coin Post: {coin_post_prompt[:100]}...",
                'cached': False
            })

        except Exception as analysis_error:
            logger.error(f"Error during AI analysis for {symbol}: {analysis_error}")
            return jsonify({
                'error': f'AI analysis failed: {str(analysis_error)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Error in news analysis endpoint: {e}")
        return jsonify({'error': str(e)}), 500
            
    except Exception as e:
        logger.error(f"Error in news analysis: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/run-analysis', methods=['POST'])
@login_required
def api_run_ai_analysis():
    """Manually trigger AI analysis"""
    try:
        from datetime import datetime
        
        # Get user's portfolio
        portfolio = get_portfolio_data_for_user(current_user.id)
        
        if not portfolio:
            return jsonify({
                'success': False,
                'message': 'No portfolio data found. Add some coins to your portfolio first.',
                'results': []
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        
        # Run analysis for all unhidden portfolio coins
        analysis_results = []
        conversation_id = generate_conversation_id()
        
        for coin in portfolio:
            symbol = coin['symbol']
            current_price = coin.get('current_price', 0)
            
            if current_price <= 0:
                continue
            
            # Get price data
            price_data = get_last_7d_prices(symbol)
            if not price_data or len(price_data) < 2:
                continue
            
            # Calculate basic metrics
            price_change = ((price_data[-1] - price_data[0]) / price_data[0]) * 100
            volatility = calculate_volatility(price_data)
            
            # Run market analysis
            try:
                market_prompt = (
                    "MARKET_ANALYSIS_COIN_DATA\n"
                    f"symbol: {symbol}\n"
                    f"current_price: {current_price}\n"
                    f"price_change: {price_change}\n"
                    f"volatility: {volatility}\n"
                )
                
                # Log the prompt
                log_ai_conversation(current_user.id, "market_analysis", "user", market_prompt, conversation_id)
                
                # Get AI prompts from database
                ai_prompts_obj = get_user_ai_prompts(current_user.id)
                system_content = (ai_prompts_obj.market_analysis_post or "").strip() if ai_prompts_obj else ""
                if not system_content:
                    logger.error(f"Missing market analysis post prompt for user {current_user.username}. Configure it in Settings.")
                    continue
                
                # Use the web search enabled AI function
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": market_prompt}
                ]
                
                response, _ = call_ai_with_web_search(
                    username=current_user.username,
                    messages=messages,
                    user_id=current_user.id,
                    prompt_type="market_analysis"
                )
                
                ai_response = response.choices[0].message.content
                
                # Log the response
                log_ai_conversation(current_user.id, "market_analysis", "ai", ai_response, conversation_id, symbol)
                
                # Coin analysis table removed - all AI conversations are now stored in ai_conversations table
                # The conversation is already logged above via log_ai_conversation()
                
                analysis_results.append({
                    'symbol': symbol,
                    'analysis': ai_response,
                    'price_change': price_change,
                    'volatility': volatility
                })
                
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue
        
        return jsonify({
            'success': True,
            'results': analysis_results,
            'conversation_id': conversation_id,
            'message': f'Analysis completed for {len(analysis_results)} coins'
        })
        
    except Exception as e:
        logger.error(f"Error running AI analysis: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai/coin-analysis', methods=['GET', 'POST'])
@login_required
def api_ai_coin_analysis():
    """Get coin analysis data or run new analysis for both portfolio and watchlist coins"""
    try:
        if request.method == 'GET':
            # Get all coin analysis for current user (both portfolio and watchlist) using ORM
            from models import Coin, WatchlistCoin
            
            # Get portfolio coins (excluding hidden)
            portfolio_coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).order_by(Coin.symbol).all()
            
            # Get watchlist coins (excluding hidden)
            watchlist_coins = WatchlistCoin.query.filter_by(user_id=current_user.id, hidden=False).order_by(WatchlistCoin.symbol).all()
            
            # Coin analysis table was removed - all AI conversations are now in ai_conversations table
            # Return empty analysis list since the coin_analysis table no longer exists
            coin_analyses = []
                    
            return jsonify({'coin_analyses': coin_analyses})
            
        elif request.method == 'POST':
            # POST method: Run new analysis for a specific coin
            data = request.get_json()
            source = data.get('source', 'portfolio')  # 'portfolio' or 'watchlist'
            coin_id = data.get('coin_id')
            watchlist_coin_id = data.get('watchlist_coin_id')
            
            # Validate parameters
            if source == 'portfolio' and not coin_id:
                return jsonify({"error": "coin_id is required for portfolio analysis"}), 400
            elif source == 'watchlist' and not watchlist_coin_id:
                return jsonify({"error": "watchlist_coin_id is required for watchlist analysis"}), 400
            
            # Get coin symbol from database using ORM
            from models import Coin, WatchlistCoin
            
            if source == 'portfolio':
                coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
            else:  # watchlist
                coin = WatchlistCoin.query.filter_by(id=watchlist_coin_id, user_id=current_user.id).first()
            
            if not coin:
                return jsonify({"error": "Coin not found"}), 404
            
            symbol = coin.symbol
            
            # Check if AI is enabled
            if not is_ai_enabled(current_user.username):
                return jsonify({"error": "AI is disabled"}), 403
            
            # Get AI settings and prompts from database - never hardcode prompts per instructions
            user_settings = get_user_ai_settings(current_user.username)

            # Format prompt with variables - use human-readable date format
            current_datetime = format_eastern_datetime(None, '%B %d, %Y at %I:%M %p EST')
            formatted_prompt = (
                "COIN_ANALYSIS_DATA\n"
                f"symbol: {symbol}\n"
                f"datetime: {current_datetime}\n"
            )
            
            # Enhanced logging for debugging
            logger.info("=== COIN ANALYSIS DEBUG ===")
            logger.info(f"Symbol: {symbol}")
            logger.info(f"Source: {source}")
            logger.info(f"Coin ID: {coin_id}")
            logger.info(f"Watchlist Coin ID: {watchlist_coin_id}")
            logger.info(f"Formatted Prompt: {formatted_prompt}")
            logger.info(f"Current Datetime: {current_datetime}")
            logger.info("=== END COIN ANALYSIS DEBUG ===")
            
            # Call AI API
            try:
                # Get user AI settings to determine provider and model
                user_settings = get_user_ai_settings(current_user.username)
                ai_provider = user_settings.get('ai_provider', 'openai')
                model_name = user_settings.get('ai_model', 'gpt-5')
                
                # Log the full prompt being sent to AI
                logger.info("=== FULL PROMPT TO AI ===")
                # Get AI prompts from database
                ai_prompts_obj = get_user_ai_prompts(current_user.id)
                system_content = (ai_prompts_obj.coin_analysis_post or "").strip() if ai_prompts_obj else ""
                if not system_content:
                    return jsonify({"error": "Missing coin analysis post prompt. Configure it in Settings."}), 400
                
                logger.info(f"System message: {system_content}")
                logger.info(f"User message: {formatted_prompt}")
                logger.info(f"Provider: {ai_provider}")
                logger.info(f"Model: {model_name}")
                logger.info("=== END FULL PROMPT TO AI ===")
                
                response, _ = call_ai_with_web_search(
                    username=current_user.username,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": formatted_prompt}
                    ],
                    user_id=current_user.id,
                    prompt_type="coin_analysis",
                    symbol=symbol  # Pass the symbol for variable substitution
                )
                
                # Handle different response formats
                logger.info("=== AI RESPONSE DEBUG ===")
                logger.info(f"Response type: {type(response)}")
                logger.info(f"Response: {response}")
                
                if hasattr(response, 'choices') and response.choices:
                    # OpenAI format
                    analysis_report = response.choices[0].message.content
                    logger.info(f"OpenAI format - Analysis report: {analysis_report}")
                elif isinstance(response, dict) and 'content' in response:
                    # Z.AI format
                    analysis_report = response['content']
                    logger.info(f"Z.AI format - Analysis report: {analysis_report}")
                    logger.info(f"Z.AI content length: {len(analysis_report) if analysis_report else 0}")
                    logger.info(f"Z.AI content is empty: {analysis_report == ''}")
                elif isinstance(response, dict) and 'error' in response:
                    # Error response from Z.AI
                    error_msg = response.get('error', {}).get('message', 'Unknown error')
                    logger.error(f"Z.AI Error: {error_msg}")
                    raise Exception(f"AI API error: {error_msg}")
                else:
                    # Fallback for other formats
                    analysis_report = str(response)
                    logger.info(f"Fallback format - Analysis report: {analysis_report}")
                
                # Check if analysis report is empty
                if not analysis_report or analysis_report.strip() == '':
                    logger.error(f"EMPTY ANALYSIS REPORT! Response was: {response}")
                    raise Exception("AI returned empty analysis report")
                
                logger.info("=== END AI RESPONSE DEBUG ===")
                
                # Log the conversation for sidebar display in proper order
                try:
                    # Generate a shared conversation ID to group the request and response
                    conversation_id = generate_conversation_id()
                    
                    # FIXED: Log the user's FULL request FIRST with timestamp to ensure proper order
                    import time
                    time.sleep(0.1)  # Small delay to ensure proper ordering
                    
                    log_ai_conversation(
                        user_id=current_user.id,
                        prompt_type="coin_analysis",
                        sender="user",
                        body=formatted_prompt,  # Use the FULL prompt that was sent to AI, not just "Analyze {symbol}"
                        conversation_id=conversation_id
                    )
                    
                    # Small delay to ensure the AI response comes after the user message
                    time.sleep(0.1)
                    
                    # Log the AI's response SECOND
                    try:
                        log_ai_conversation(
                            user_id=current_user.id,
                            prompt_type="coin_analysis",
                            sender="ai",
                            body=analysis_report,
                            conversation_id=conversation_id
                        )
                        logger.info(f"Coin analysis conversation logged for {symbol} with conversation_id: {conversation_id}")
                    except Exception as e:
                        logger.error(f"Error logging coin analysis conversation: {e}")
                except Exception as e:
                    logger.error(f"Conversation logging failed: {e}")
                
                # Coin analysis storage removed - all AI conversations now stored in ai_conversations table
                # The conversation is already logged above via log_ai_conversation()
                # No need for separate coin_analysis table storage
                
                return jsonify({
                    "success": True,
                    "report": analysis_report,
                    "ordinal": 1,  # Default ordinal since we're not tracking in separate table
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "time": datetime.now().strftime('%H:%M:%S')
                })
                
            except Exception as e:
                logger.error(f"Error in coin analysis: {e}")
                return jsonify({"error": f"Analysis failed: {str(e)}"}), 500
                
    except Exception as e:
        logger.error(f"Error in coin analysis endpoint: {e}")
        return jsonify({"error": str(e)}), 500


# Helper functions for AI analysis
def extract_sentiment(analysis):
    """Extract sentiment from AI analysis"""
    analysis_lower = analysis.lower()
    if 'bullish' in analysis_lower:
        return 'bullish'
    elif 'bearish' in analysis_lower:
        return 'bearish'
    else:
        return 'neutral'

def extract_risk_level(analysis):
    """Extract risk level from AI analysis"""
    analysis_lower = analysis.lower()
    if 'high risk' in analysis_lower or 'high-risk' in analysis_lower:
        return 'high'
    elif 'low risk' in analysis_lower or 'low-risk' in analysis_lower:
        return 'low'
    else:
        return 'moderate'

def extract_confidence(analysis):
    """Extract confidence level from AI analysis"""
    import re
    # Look for percentage patterns like "75%" or "confidence: 80"
    confidence_match = re.search(r'(\d+)%', analysis)
    if confidence_match:
        return int(confidence_match.group(1))
    return 75  # Default confidence

def extract_key_insights(analysis):
    """Extract key insights from AI analysis"""
    # Simple extraction - split by sentences and take first few
    sentences = analysis.split('.')
    insights = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 20]
    return insights[:3]  # Return first 3 insights

def parse_ai_recommendation(analysis, current_price):
    """Parse AI recommendation response"""
    import re
    
    # Default values
    signal = "HOLD"
    confidence = 50
    entry_price = current_price
    stop_loss = current_price * 0.95
    take_profit = current_price * 1.15
    reasoning = analysis
    
    try:
        # Extract signal
        analysis_lower = analysis.lower()
        if 'buy' in analysis_lower:
            signal = "BUY"
        elif 'sell' in analysis_lower:
            signal = "SELL"
        
        # Extract confidence
        confidence = extract_confidence(analysis)
        
        # Extract price targets
        price_matches = re.findall(r'\$(\d+(?:\.\d+)?)', analysis)
        if len(price_matches) >= 3:
            try:
                entry_price = float(price_matches[0])
                stop_loss = float(price_matches[1])
                take_profit = float(price_matches[2])
            except (ValueError, IndexError):
                pass
        
        return signal, confidence, entry_price, stop_loss, take_profit, reasoning
        
    except Exception as e:
        logger.error(f"Error parsing AI recommendation: {e}")
        return signal, confidence, entry_price, stop_loss, take_profit, reasoning

def parse_portfolio_analysis(analysis):
    """Parse AI portfolio analysis response"""
    try:
        # Simple parsing - extract numbers and recommendations
        _ = analysis.lower()
        
        # Extract scores (0-100)
        import re
        scores = re.findall(r'(\d+(?:\.\d+)?)', analysis)
        scores = [float(s) for s in scores if 0 <= float(s) <= 100]
        
        health_score = scores[0] if len(scores) > 0 else 50
        diversification_score = scores[1] if len(scores) > 1 else 50
        risk_adjusted_return = scores[2] if len(scores) > 2 else 50
        
        # Extract recommendations
        recommendations = []
        lines = analysis.split('\n')
        for line in lines:
            if any(word in line.lower() for word in ['recommend', 'suggest', 'consider', 'improve']):
                recommendations.append(line.strip())
        
        if not recommendations:
            recommendations = ["Review portfolio allocation", "Consider diversification", "Monitor risk levels"]
        
        return health_score, diversification_score, risk_adjusted_return, recommendations[:3]
        
    except Exception as e:
        logger.error(f"Error parsing portfolio analysis: {e}")
        return 50, 50, 50, ["Analysis parsing failed"]

def calculate_volatility(price_data):
    """Calculate volatility from price data"""
    try:
        if not price_data or len(price_data) < 2:
            return 0.0
        
        prices = []
        for p in price_data:
            if isinstance(p, (int, float)):
                prices.append(float(p))
            elif isinstance(p, dict):
                prices.append(float(p.get('price', 0)))
            elif hasattr(p, 'price'):
                prices.append(float(getattr(p, 'price')))
        
        if len(prices) < 2:
            return 0.0
        
        # Calculate daily returns
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                returns.append((prices[i] - prices[i-1]) / prices[i-1])
        
        if not returns:
            return 0.0
        
        # Calculate standard deviation
        import statistics
        return statistics.stdev(returns) if len(returns) > 1 else 0.0
        
    except Exception as e:
        logger.error(f"Error calculating volatility: {e}")
        return 0.0

def basic_recommendation_analysis(price_change, volatility, current_price):
    """Basic recommendation analysis without AI"""
    signal = "HOLD"
    confidence = 50
    reasoning = "Basic technical analysis based on price movement and volatility"
    
    if price_change > 0.05:  # 5% gain
        signal = "SELL" if volatility > 0.1 else "HOLD"
        confidence = 60
    elif price_change < -0.05:  # 5% loss
        signal = "BUY" if volatility < 0.15 else "HOLD"
        confidence = 55
    
    entry_price = current_price
    stop_loss = current_price * 0.95
    take_profit = current_price * 1.10
    
    return signal, confidence, entry_price, stop_loss, take_profit, reasoning

def basic_portfolio_analysis(portfolio, total_value, total_initial_value):
    """Basic portfolio analysis without AI"""
    try:
        health_score = 75
        diversification_score = min(100, len(portfolio) * 20)  # More coins = better diversification
        
        # Calculate return
        if total_initial_value > 0:
            return_pct = ((total_value - total_initial_value) / total_initial_value) * 100
            risk_adjusted_return = max(0, min(100, 50 + return_pct))
        else:
            risk_adjusted_return = 50
        
        recommendations = [
            "Monitor portfolio performance regularly",
            "Consider rebalancing if needed",
            "Diversify across different cryptocurrencies"
        ]
        
        return health_score, diversification_score, risk_adjusted_return, recommendations
        
    except Exception as e:
        logger.error(f"Error in basic portfolio analysis: {e}")
        return 50, 50, 50, ["Analysis failed"]

# WIDGET API ENDPOINTS

@app.route('/api/widgets/fear-greed', methods=['GET'])
def api_fear_greed_index():
    """Proxy endpoint for Fear & Greed Index to avoid CORS issues"""
    try:
        import requests
        response = requests.get('https://api.alternative.me/fng/', timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error fetching Fear & Greed Index: {e}")
        return jsonify({"error": "Failed to fetch Fear & Greed Index"}), 500

@app.route('/api/widgets/cbbi', methods=['GET'])
def api_cbbi_data():
    """Proxy endpoint for CBBI data to avoid CORS issues"""
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get('https://colintalkscrypto.com/cbbi/data/latest.json', 
                              timeout=10, 
                              headers=headers,
                              verify=True)
        response.raise_for_status()
        data = response.json()
        
        # Extract the Confidence data which contains the actual CBBI values (not 2YMA)
        if isinstance(data, dict):
            if 'Confidence' in data:
                # Use Confidence data which is the actual CBBI score
                cbbi_data = data['Confidence']
                return jsonify({"confidence": cbbi_data})
            elif 'confidence' in data and 'Confidence' in data['confidence']:
                # Data is structured differently - extract Confidence
                return jsonify({"confidence": data['confidence']['Confidence']})
            elif 'confidence' not in data:
                # Raw timestamp data - wrap it properly (fallback)
                return jsonify({"confidence": data})
            else:
                # Already has proper structure
                return jsonify(data)
        else:
            # Unexpected data format
            raise Exception("Unexpected API response format")
            
    except Exception as e:
        logger.error(f"Error fetching CBBI data: {e}")
        # Return mock data if the real API fails
        from datetime import datetime
        current_timestamp = int(datetime.now().timestamp())
        mock_data = {
            "confidence": {
                str(current_timestamp): 0.25  # 25% confidence (moderate risk)
            }
        }
        return jsonify(mock_data)

# NEW AI TRADING DASHBOARD ENDPOINTS - 3-STAGE AGENTIC WORKFLOWS

@app.route('/api/ai/market-analysis-workflow', methods=['GET'])
@login_required
def api_market_analysis_workflow():
    """Execute 3-stage agentic Market Analysis workflow using user's custom prompts"""
    try:
        from datetime import timedelta
        from models import AIConversation
        username = current_user.username
        user_id = current_user.id
        
        # Get user's AI settings for cache and analysis window
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59')
        
        logger.info(f"[AI_DEBUG] Settings for {username}: Window={analysis_window_start}-{analysis_window_end}, Cache={cache_duration_hours}h")
        
        # Check if we're in the analysis window (unless manual request)
        manual_request = request.args.get('manual', 'false').lower() == 'true'
        if not manual_request and not is_user_analysis_window_active(analysis_window_start, analysis_window_end):
            logger.info(f"[AI_DEBUG] User {username} outside analysis window ({analysis_window_start}-{analysis_window_end})")
            
            # Identify most recent cache (expired or not) to show instead of blank
            last_conv = AIConversation.query.filter_by(
                user_id=user_id, 
                prompt_type='market_analysis_workflow',
                sender='ai'
            ).order_by(AIConversation.created_at.desc()).first()
            
            if last_conv:
                try:
                    cached_data = json.loads(last_conv.body)
                    cached_data['cache_info'] = {
                        "status": "expired_window_inactive",
                        "cached_at": last_conv.created_at.isoformat(),
                        "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except:
                    pass

            return jsonify({
                "success": False,
                "message": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use manual refresh for off-hours analysis.",
                "stage1": {"status": "skipped", "reason": "outside_analysis_window"},
                "stage2": {"status": "skipped", "reason": "outside_analysis_window"},
                "stage3": {"status": "skipped", "reason": "outside_analysis_window"},
                "cache_info": {"status": "analysis_window_inactive"}
            })
        
        # Check 4-hour scheduling (unless manual request)
        if not manual_request and not should_run_ai_analysis(user_id):
            logger.info(f"[AI_DEBUG] User {username} skipped due to schedule (run recently)")
            
            # Identify most recent cache (expired or not) to show instead of blank
            last_conv = AIConversation.query.filter_by(
                user_id=user_id, 
                prompt_type='market_analysis_workflow',
                sender='ai'
            ).order_by(AIConversation.created_at.desc()).first()
            
            if last_conv:
                try:
                    cached_data = json.loads(last_conv.body)
                    cached_data['cache_info'] = {
                        "status": "expired_schedule_blocked",
                        "cached_at": last_conv.created_at.isoformat(),
                        "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except:
                    pass

            return jsonify({
                "success": False,
                "message": f"AI analysis scheduled every {cache_duration_hours} hours. Use manual refresh to run immediately.",
                "stage1": {"status": "skipped", "reason": "schedule_not_ready"},
                "stage2": {"status": "skipped", "reason": "schedule_not_ready"},
                "stage3": {"status": "skipped", "reason": "schedule_not_ready"},
                "cache_info": {"status": "schedule_blocked"}
            })
        
        # Check cache unless manual request
        if not manual_request:
            # Check for recent cached analysis
            from datetime import timedelta
            cache_timestamp = datetime.utcnow() - timedelta(hours=cache_duration_hours)
            
            # models imported at top
            cached_result = AIConversation.query.filter(
                AIConversation.user_id == user_id,
                AIConversation.prompt_type == 'market_analysis_workflow',
                AIConversation.sender == 'ai',
                AIConversation.created_at > cache_timestamp
            ).order_by(AIConversation.created_at.desc()).first()
            
            if cached_result:
                logger.info(f"[AI_DEBUG] Cache HIT for {username}")
                try:
                    cached_data = json.loads(cached_result.body)
                    cached_data['cache_info'] = {
                        "status": "cache_hit",
                        "cached_at": cached_result.created_at.isoformat(),
                        "expires_at": (cached_result.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse cached market analysis for user {user_id}")
            else:
                logger.info(f"[AI_DEBUG] Cache MISS for {username}")
        
        logger.info(f"=== MARKET ANALYSIS WORKFLOW START - User: {username} ===")
        
        # Capture the start time for accurate "generated_at" timestamp
        analysis_start_time = get_eastern_now_iso()
        
        # Execute 3-stage agentic workflow for market analysis
        # NOTE: call_ai_with_web_search will use the proper database prompts from ai_prompts table
        # We just need to provide a simple trigger message to start the workflow
        market_analysis_messages = [
            {
                "role": "user",
                "content": "Market analysis request"  # This gets replaced by the actual Stage 3 prompt
            }
        ]
        
        # Execute the agentic workflow - this will return response and actual Stage 3 prompt
        response, actual_user_prompt = call_ai_with_web_search(
            username=username,
            messages=market_analysis_messages,
            user_id=user_id,
            prompt_type='market_analysis',  # Uses market_analysis_pre and market_analysis_post from database
            symbol=None,
            model=None  # Use user's preferred model
        )
        
        # Extract the analysis content
        if hasattr(response, 'choices') and response.choices:
            analysis_content = response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format")
        
        # Structure the response with workflow stages
        workflow_result = {
            "success": True,
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "completed",
                "description": "Data Gathering - Generated targeted search queries for current market information"
            },
            "stage2": {
                "status": "completed", 
                "description": "Web Search - Executed searches for real-time market data and news"
            },
            "stage3": {
                "status": "completed",
                "description": "Analysis Synthesis - Combined search results with user prompts for comprehensive analysis",
                "content": analysis_content
            },
            "analysis": {
                "content": analysis_content,
                "type": "market_analysis",
                "generated_at": analysis_start_time
            },
            "cache_info": {
                "status": "fresh_analysis",
                "generated_at": analysis_start_time,
                "expires_at": (get_eastern_now() + timedelta(hours=cache_duration_hours)).isoformat()
            }
        }
        
        # Save conversations to AI Copilot sidebar using the ACTUAL Stage 3 prompt
        try:
            import time
            
            # Use the ACTUAL Stage 3 prompt that was sent to AI (not hardcoded)
            # Log user message first 
            log_ai_conversation(user_id, "market_analysis", "user", actual_user_prompt)
            
            # Add small delay to ensure proper chronological order
            time.sleep(0.1)
            
            # Then log ai response 
            log_ai_conversation(user_id, "market_analysis", "ai", analysis_content)
            
            logger.info(f"Market analysis conversations saved to AI Copilot for user {user_id}")
            
        except Exception as conversation_error:
            logger.error(f"Failed to save market analysis conversations: {conversation_error}")
        
        # Store workflow result in AIConversation table for caching only
        try:
            now = get_eastern_now()
            ai_conversation = AIConversation(
                user_id=user_id,
                date=now.strftime('%Y-%m-%d'),
                time=now.strftime('%I:%M %p %Z'),
                prompt_type='market_analysis_workflow',
                sender='ai',
                body=json.dumps(workflow_result),
                created_at=now,
                is_hidden=1  # Hidden from AI Copilot since it's already saved by log_ai_conversation
            )
            db.session.add(ai_conversation)
            db.session.commit()
            logger.info(f"Market analysis workflow cache stored for user {user_id}")
            
            # Update the AI analysis schedule based on user settings
            update_ai_analysis_schedule(user_id)
            
        except Exception as db_error:
            logger.error(f"Failed to store market analysis cache: {db_error}")
            # Continue without caching
        
        logger.info(f"=== MARKET ANALYSIS WORKFLOW COMPLETE - User: {username} ===")
        return jsonify(workflow_result)
        
    except Exception as e:
        logger.error(f"Market analysis workflow error for user {username}: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e),
            "stage1": {"status": "failed", "error": str(e)},
            "stage2": {"status": "failed", "error": str(e)},
            "stage3": {"status": "failed", "error": str(e)},
            "cache_info": {"status": "error"}
        }), 500

@app.route('/api/ai/risk-assessment-workflow', methods=['GET'])
@login_required
def api_risk_assessment_workflow():
    """Execute 3-stage agentic Risk Assessment workflow using user's custom prompts"""
    try:
        from datetime import timedelta
        from models import AIConversation
        username = current_user.username
        user_id = current_user.id
        manual_request = request.args.get('manual', 'false').lower() == 'true'
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)

        # Always run for manual requests, otherwise check schedule/cache
        if not manual_request:
            if not should_run_ai_analysis(user_id):
                # Identify most recent cache (expired or not) to show instead of blank
                last_conv = AIConversation.query.filter_by(
                    user_id=user_id, 
                    prompt_type='risk_assessment_workflow',
                    sender='ai'
                ).order_by(AIConversation.created_at.desc()).first()
                
                if last_conv:
                    try:
                        cached_data = json.loads(last_conv.body)
                        cached_data['cache_info'] = {
                            "status": "expired_schedule_blocked",
                            "cached_at": last_conv.created_at.isoformat(),
                            "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                        }
                        return jsonify(cached_data)
                    except:
                        pass
                
                return jsonify({
                    "success": False,
                    "message": f"AI analysis scheduled every {cache_duration_hours} hours. Use manual refresh to run immediately.",
                    "stage1": {"status": "skipped", "reason": "schedule_not_ready"},
                    "stage2": {"status": "skipped", "reason": "schedule_not_ready"},
                    "stage3": {"status": "skipped", "reason": "schedule_not_ready"},
                    "cache_info": {"status": "schedule_blocked"}
                })
            cache_timestamp = datetime.now() - timedelta(hours=cache_duration_hours)
            cached_result = db.session.query(AIConversation).filter(
                AIConversation.user_id == user_id,
                AIConversation.prompt_type == 'risk_assessment_workflow',
                AIConversation.sender == 'ai',
                AIConversation.created_at > cache_timestamp
            ).order_by(AIConversation.created_at.desc()).first()
            if cached_result:
                try:
                    cached_data = json.loads(cached_result.body)
                    cached_data['cache_info'] = {
                        "status": "cache_hit",
                        "cached_at": cached_result.created_at.isoformat(),
                        "expires_at": (cached_result.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse cached risk assessment for user {user_id}")

        logger.info(f"=== RISK ASSESSMENT WORKFLOW START - User: {username} ===")
        analysis_start_time = get_eastern_now_iso()

        # === STAGE 1: Send risk_assessment_pre to AI ===
        ai_prompts = get_user_ai_prompts(user_id)
        if not ai_prompts or not ai_prompts.risk_assessment_pre:
            raise Exception("No risk_assessment_pre prompt configured for this user.")
        stage1_prompt = ai_prompts.risk_assessment_pre
        stage1_messages = [{"role": "system", "content": stage1_prompt}]
        # Send to AI (Stage 1)
        stage1_response, _ = call_ai_with_web_search(
            username=username,
            messages=stage1_messages,
            user_id=user_id,
            prompt_type='risk_assessment',
            symbol=None,
            model=None
        )
        if hasattr(stage1_response, 'choices') and stage1_response.choices:
            stage1_content = stage1_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 1")

        # === STAGE 2: Brave search + coin data + risk_assessment_post ===
        # Gather non-stablecoin, non-hidden coins
        from models import Coin
        coins = Coin.query.filter_by(user_id=user_id, hidden=False).all()
        non_stablecoins = [c for c in coins if not is_stablecoin(c.symbol)]
        coin_data_lines = []
        for c in non_stablecoins:
            amount = float(c.amount or 0.0)
            current_price = float(c.current or 0.0)
            current_value = current_price * amount
            coin_data_lines.append(
                f"{c.symbol}: {amount:.6f} (value: ${current_value:,.2f} @ ${current_price:.4f})"
            )
        coin_data = "\n".join(coin_data_lines)

        # Use Brave search results from Stage 1 (already included in call_ai_with_web_search context)
        if not ai_prompts.risk_assessment_post:
            raise Exception("No risk_assessment_post prompt configured for this user.")
        stage2_prompt = ai_prompts.risk_assessment_post
        # Combine context
        stage2_context = f"{stage2_prompt}\n\nUSER COIN DATA:\n{coin_data if coin_data else 'No non-stablecoin holdings.'}"
        stage2_messages = [
            {"role": "system", "content": stage2_context},
            {"role": "user", "content": stage1_content}
        ]
        # Send to AI (Stage 2)
        stage2_response, actual_user_prompt = call_ai_with_web_search(
            username=username,
            messages=stage2_messages,
            user_id=user_id,
            prompt_type='risk_assessment',
            symbol=None,
            model=None
        )
        if hasattr(stage2_response, 'choices') and stage2_response.choices:
            analysis_content = stage2_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 2")

        # === LOGGING ===
        import time
        log_ai_conversation(user_id, "risk_assessment", "user", actual_user_prompt)
        time.sleep(0.1)
        log_ai_conversation(user_id, "risk_assessment", "ai", analysis_content)

        # === RESPONSE ===
        workflow_result = {
            "success": True,
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "completed",
                "description": "Sent risk_assessment_pre to AI"
            },
            "stage2": {
                "status": "completed",
                "description": "Brave search + coin data + risk_assessment_post sent to AI"
            },
            "stage3": {
                "status": "completed",
                "description": "AI generated holistic risk assessment",
                "content": analysis_content
            },
            "analysis": {
                "content": analysis_content,
                "type": "risk_assessment",
                "generated_at": analysis_start_time
            },
            "cache_info": {
                "status": "fresh_analysis",
                "generated_at": analysis_start_time,
                "expires_at": (get_eastern_now() + timedelta(hours=cache_duration_hours)).isoformat()
            }
        }

        # Store workflow result in AIConversation table for caching only
        try:
            now = get_eastern_now()
            ai_conversation = AIConversation(
                user_id=user_id,
                date=now.strftime('%Y-%m-%d'),
                time=now.strftime('%I:%M %p %Z'),
                prompt_type='risk_assessment_workflow',
                sender='ai',
                body=json.dumps(workflow_result),
                created_at=now,
                is_hidden=1
            )
            db.session.add(ai_conversation)
            db.session.commit()
            logger.info(f"Risk assessment workflow cache stored for user {user_id}")
            update_ai_analysis_schedule(user_id)
        except Exception as db_error:
            logger.error(f"Failed to store risk assessment cache: {db_error}")

        logger.info(f"=== RISK ASSESSMENT WORKFLOW COMPLETE - User: {username} ===")
        return jsonify(workflow_result)

    except Exception as e:
        logger.error(f"Risk assessment workflow error for user {username}: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e),
            "stage1": {"status": "failed", "error": str(e)},
            "stage2": {"status": "failed", "error": str(e)},
            "stage3": {"status": "failed", "error": str(e)},
            "cache_info": {"status": "error"}
        }), 500

@app.route('/api/ai/portfolio-review-workflow', methods=['GET', 'POST'])
@login_required
def api_portfolio_review_workflow():
    """Trigger Portfolio Review workflow and return immediate response to avoid timeout"""
    try:
        from datetime import timedelta
        from models import AIConversation
        username = current_user.username
        user_id = current_user.id
        manual_request = request.args.get('manual', 'false').lower() == 'true'
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59')

        # Always run for manual requests, otherwise check schedule/cache
        if not manual_request:
            if not is_user_analysis_window_active(analysis_window_start, analysis_window_end):
                # Identify most recent cache (expired or not) to show instead of blank
                last_conv = AIConversation.query.filter_by(
                    user_id=user_id, 
                    prompt_type='portfolio_review_workflow',
                    sender='ai'
                ).order_by(AIConversation.created_at.desc()).first()
                if last_conv:
                    try:
                        cached_data = json.loads(last_conv.body)
                        cached_data['cache_info'] = {
                            "status": "expired_window_inactive",
                            "cached_at": last_conv.created_at.isoformat(),
                            "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                        }
                        return jsonify(cached_data)
                    except:
                        pass
                return jsonify({
                    "success": False,
                    "message": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use manual refresh for off-hours analysis.",
                    "status": "outside_window"
                })
            
            if not should_run_ai_analysis(user_id):
                # Identify most recent cache (expired or not) to show instead of blank
                last_conv = AIConversation.query.filter_by(
                    user_id=user_id, 
                    prompt_type='portfolio_review_workflow',
                    sender='ai'
                ).order_by(AIConversation.created_at.desc()).first()
                if last_conv:
                    try:
                        cached_data = json.loads(last_conv.body)
                        cached_data['cache_info'] = {
                            "status": "expired_schedule_blocked",
                            "cached_at": last_conv.created_at.isoformat(),
                            "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                        }
                        return jsonify(cached_data)
                    except:
                        pass
                return jsonify({
                    "success": False,
                    "message": f"AI analysis scheduled every {cache_duration_hours} hours. Use manual refresh to run immediately.",
                    "status": "schedule_blocked"
                })
            cache_timestamp = datetime.now() - timedelta(hours=cache_duration_hours)
            cached_result = db.session.query(AIConversation).filter(
                AIConversation.user_id == user_id,
                AIConversation.prompt_type == 'portfolio_review_workflow',
                AIConversation.sender == 'ai',
                AIConversation.created_at > cache_timestamp
            ).order_by(AIConversation.created_at.desc()).first()
            if cached_result:
                try:
                    cached_data = json.loads(cached_result.body)
                    eastern_time = get_eastern_datetime(cached_result.created_at)
                    cached_data['timestamp'] = format_eastern_datetime_ampm(eastern_time)
                    cached_data['status'] = 'cache_hit'
                    if 'analysis' in cached_data and 'generated_at' in cached_data['analysis']:
                        cached_data['analysis']['generated_at'] = format_eastern_datetime_ampm(eastern_time)
                    return jsonify(cached_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse cached portfolio review for user {user_id}")

        logger.info(f"=== PORTFOLIO REVIEW WORKFLOW START (SYNC) - User: {username} ===")
        analysis_start_time = get_eastern_now_iso()

        # === STAGE 1: Send portfolio_review_pre to AI ===
        ai_prompts = get_user_ai_prompts(user_id)
        if not ai_prompts or not ai_prompts.portfolio_review_pre:
            raise Exception("No portfolio_review_pre prompt configured for this user.")
        stage1_prompt = ai_prompts.portfolio_review_pre
        stage1_messages = [
            {"role": "user", "content": stage1_prompt}
        ]
        # Send to AI (Stage 1)
        stage1_response, _ = call_ai_with_web_search(
            username=username,
            messages=stage1_messages,
            user_id=user_id,
            prompt_type='portfolio_review',
            symbol=None,
            model=None
        )
        if hasattr(stage1_response, 'choices') and stage1_response.choices:
            stage1_content = stage1_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 1")

        # === STAGE 2: Brave search + coin data + portfolio_review_post ===
        from models import Coin
        coins = Coin.query.filter_by(user_id=user_id, hidden=False).all()
        non_stablecoins = [c for c in coins if not is_stablecoin(c.symbol)]
        coin_data = "\n".join([f"{c.symbol}: {c.amount} (value: ${c.amount * c.current if c.current else 0:.2f})" for c in non_stablecoins])

        if not ai_prompts.portfolio_review_post:
            raise Exception("No portfolio_review_post prompt configured for this user.")
        stage2_prompt = ai_prompts.portfolio_review_post
        stage2_context = f"{stage2_prompt}\n\nUSER COIN DATA:\n{coin_data if coin_data else 'No non-stablecoin holdings.'}"
        stage2_messages = [
            {"role": "system", "content": stage2_context},
            {"role": "user", "content": stage1_content}
        ]
        # Send to AI (Stage 2)
        stage2_response, actual_user_prompt = call_ai_with_web_search(
            username=username,
            messages=stage2_messages,
            user_id=user_id,
            prompt_type='portfolio_review',
            symbol=None,
            model=None
        )
        if hasattr(stage2_response, 'choices') and stage2_response.choices:
            analysis_content = stage2_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 2")

        # === LOGGING ===
        import time
        log_ai_conversation(user_id, "portfolio_review", "user", actual_user_prompt)
        time.sleep(0.1)
        log_ai_conversation(user_id, "portfolio_review", "ai", analysis_content)

        # === RESPONSE ===
        workflow_result = {
            "success": True,
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "completed",
                "description": "Sent portfolio_review_pre to AI"
            },
            "stage2": {
                "status": "completed",
                "description": "Brave search + coin data + portfolio_review_post sent to AI"
            },
            "stage3": {
                "status": "completed",
                "description": "AI generated holistic portfolio review",
                "content": analysis_content
            },
            "analysis": {
                "content": analysis_content,
                "type": "portfolio_review",
                "generated_at": analysis_start_time
            },
            "status": "completed"
        }

        # Store workflow result in AIConversation table for caching
        try:
            now = get_eastern_now()
            ai_conversation = AIConversation(
                user_id=user_id,
                date=now.strftime('%Y-%m-%d'),
                time=now.strftime('%I:%M %p %Z'),
                prompt_type='portfolio_review_workflow',
                sender='ai',
                body=json.dumps(workflow_result),
                created_at=now,
                is_hidden=1
            )
            db.session.add(ai_conversation)
            db.session.commit()
            logger.info(f"Portfolio review workflow cache stored for user {user_id}")
            update_ai_analysis_schedule(user_id)
            logger.info(f"Next analysis scheduled for user {user_id}")
        except Exception as db_error:
            logger.error(f"Failed to store portfolio review cache: {db_error}")

        logger.info(f"=== PORTFOLIO REVIEW WORKFLOW COMPLETE (SYNC) - User: {username} ===")
        return jsonify(workflow_result)

    except Exception as e:
        logger.error(f"Portfolio review workflow error for user {username}: {e}", exc_info=True)
        try:
            db.session.rollback()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "failed",
                "description": f"Portfolio review failed: {str(e)}"
            },
            "stage2": {"status": "skipped", "description": "Skipped due to error"},
            "stage3": {"status": "failed", "description": "Analysis failed"},
            "analysis": None,
            "status": "error"
        }), 500
        


@app.route('/api/ai/portfolio-review-results', methods=['GET'])
@login_required
def api_portfolio_review_results():
    """Get cached Portfolio Review results without triggering new analysis"""
    try:
        from datetime import timedelta
        username = current_user.username
        user_id = current_user.id
        
        # Get user's AI settings for cache duration
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)
        
        # Look for recent cached results
        cache_timestamp = datetime.now() - timedelta(hours=cache_duration_hours)
        cached_result = db.session.query(AIConversation).filter(
            AIConversation.user_id == user_id,
            AIConversation.prompt_type == 'portfolio_review_workflow',
            AIConversation.sender == 'ai',
            AIConversation.created_at > cache_timestamp
        ).order_by(AIConversation.created_at.desc()).first()
        
        if cached_result:
            try:
                cached_data = json.loads(cached_result.body)
                # Fix timezone - convert UTC created_at to Eastern time with AM/PM format
                eastern_time = get_eastern_datetime(cached_result.created_at)
                cached_data['timestamp'] = format_eastern_datetime_ampm(eastern_time)
                if 'analysis' in cached_data and 'generated_at' in cached_data['analysis']:
                    cached_data['analysis']['generated_at'] = format_eastern_datetime_ampm(eastern_time)
                if 'cache_info' in cached_data:
                    cached_data['cache_info']['generated_at'] = format_eastern_datetime_ampm(eastern_time)
                    cached_data['cache_info']['expires_at'] = (eastern_time + timedelta(hours=cache_duration_hours)).isoformat()
                
                return jsonify(cached_data)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse cached portfolio review for user {user_id}")
        
        # No cached results found
        return jsonify({
            "success": False,
            "message": "No recent portfolio review found. Click 'Refresh Portfolio Review' to generate new analysis.",
            "cache_info": {"status": "no_cache"}
        })
        
    except Exception as e:
        logger.error(f"Portfolio review results error for user {username}: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "cache_info": {"status": "error"}
        }), 500

@app.route('/api/ai/copilot-results', methods=['GET'])
@login_required
def api_ai_copilot_results():
    """Consolidate all three workflow results for AI Copilot sidebar with proper formatting"""
    try:
        username = current_user.username
        user_id = current_user.id
        
        # Get recent workflow results from the last 24 hours
        since_timestamp = datetime.now() - timedelta(hours=24)
        
        # Query all three workflow types
        workflow_conversations = db.session.query(AIConversation).filter(
            AIConversation.user_id == user_id,
            AIConversation.prompt_type.in_(['market_analysis_workflow', 'risk_assessment_workflow', 'portfolio_review_workflow']),
            AIConversation.sender == 'ai',
            AIConversation.created_at > since_timestamp,
            AIConversation.is_hidden == 0
        ).order_by(AIConversation.created_at.desc()).all()
        
        copilot_messages = []
        
        # Process each workflow result for copilot display
        for conversation in workflow_conversations:
            try:
                workflow_data = json.loads(conversation.body)
                
                # Extract workflow type and content
                workflow_type = conversation.prompt_type.replace('_workflow', '').replace('_', ' ').title()
                analysis_content = workflow_data.get('analysis', {}).get('content', '')
                
                if analysis_content:
                    # Format as user request followed by AI response
                    user_request = f"Run {workflow_type} using the 3-stage agentic workflow"
                    
                    # Add user message
                    copilot_messages.append({
                        "sender": "user",
                        "body": user_request,
                        "created_at": conversation.created_at.isoformat(),
                        "workflow_type": conversation.prompt_type,
                        "display_type": "workflow_request"
                    })
                    
                    # Add AI response with workflow info
                    ai_response_body = f"🤖 **{workflow_type} Complete** (3-Stage Agentic Workflow)\n\n"
                    
                    # Add stage information
                    if workflow_data.get('stage1', {}).get('status') == 'completed':
                        ai_response_body += "✅ **Stage 1:** " + workflow_data['stage1'].get('description', 'Data gathering completed') + "\n"
                    if workflow_data.get('stage2', {}).get('status') == 'completed':
                        ai_response_body += "✅ **Stage 2:** " + workflow_data['stage2'].get('description', 'Web search completed') + "\n"
                    if workflow_data.get('stage3', {}).get('status') == 'completed':
                        ai_response_body += "✅ **Stage 3:** " + workflow_data['stage3'].get('description', 'Analysis completed') + "\n\n"
                    
                    # Add analysis content (truncated for sidebar)
                    if len(analysis_content) > 500:
                        ai_response_body += analysis_content[:500] + "...\n\n*Click to view full analysis*"
                    else:
                        ai_response_body += analysis_content
                    
                    # Add cache information
                    cache_info = workflow_data.get('cache_info', {})
                    if cache_info.get('expires_at'):
                        expires_at = datetime.fromisoformat(cache_info['expires_at'].replace('Z', '+00:00'))
                        ai_response_body += f"\n\n📅 *Cache expires: {expires_at.strftime('%m/%d %I:%M %p')}*"
                    
                    copilot_messages.append({
                        "sender": "agent",
                        "body": ai_response_body,
                        "created_at": conversation.created_at.isoformat(),
                        "workflow_type": conversation.prompt_type,
                        "display_type": "workflow_response",
                        "full_content": analysis_content,
                        "cache_expires": cache_info.get('expires_at')
                    })
                    
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse workflow conversation {conversation.id}: {e}")
                continue
        
        # Sort messages chronologically (oldest first for proper conversation flow)
        copilot_messages.sort(key=lambda x: x['created_at'])
        
        # Add summary statistics
        workflow_stats = {
            "total_workflows": len(workflow_conversations),
            "market_analysis_count": len([c for c in workflow_conversations if c.prompt_type == 'market_analysis_workflow']),
            "risk_assessment_count": len([c for c in workflow_conversations if c.prompt_type == 'risk_assessment_workflow']),
            "portfolio_review_count": len([c for c in workflow_conversations if c.prompt_type == 'portfolio_review_workflow']),
            "time_range": "24 hours",
            "last_updated": get_eastern_now().isoformat()
        }
        
        # --- Add full transaction history for Copilot deep queries ---
        # Use get_comprehensive_crypto_data_for_user with no transaction limit
        try:
            full_crypto_data = get_comprehensive_crypto_data_for_user(user_id, limit_transactions=1000000, days_history=3650)  # 10+ years, all txns
            all_transactions = full_crypto_data.get("recent_transactions", [])
        except Exception as e:
            logger.error(f"Failed to get full transaction history for Copilot: {e}")
            all_transactions = []

        response_data = {
            "success": True,
            "messages": copilot_messages,
            "stats": workflow_stats,
            "timestamp": get_eastern_now().isoformat(),
            "all_transactions": all_transactions  # <-- Full transaction history for Copilot sidebar
        }

        logger.info(f"AI Copilot results compiled for user {username}: {len(copilot_messages)} messages from {len(workflow_conversations)} workflows, {len(all_transactions)} transactions included")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"AI Copilot results error for user {username}: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "messages": [],
            "stats": {},
            "timestamp": get_eastern_now().isoformat()
        }), 500

# Stub functions for missing functionality
def generate_smart_alerts_for_user(user_id):
    """Generate smart alerts for user - stub implementation"""
    return []

def score_recommendation(symbol, analysis_data):
    """Score recommendation - stub implementation"""
    return 75

def get_comprehensive_portfolio_context(user_id):
    """Get comprehensive portfolio data from all crypto databases for AI context"""
    try:
        # Use our new comprehensive data function
        crypto_data = get_comprehensive_crypto_data_for_user(user_id, limit_transactions=30, days_history=30)
        
        context_parts = []
        
        # 1. Portfolio Summary
        summary = crypto_data.get("summary", {})
        if summary:
            context_parts.append("=== PORTFOLIO SUMMARY ===")
            if "error" not in summary:
                context_parts.append(f"Total Coins: {summary.get('total_coins', 0)}")
                context_parts.append(f"Total Portfolio Value: ${summary.get('total_portfolio_value', 0):,.2f}")
                context_parts.append(f"Total Initial Investment: ${summary.get('total_initial_value', 0):,.2f}")
                context_parts.append(f"Unrealized P&L: ${summary.get('portfolio_pnl', 0):,.2f} ({summary.get('portfolio_pnl_pct', 0):+.2f}%)")
                context_parts.append(f"Recent Activity (7d): {summary.get('recent_buys_7d', 0)} buys, {summary.get('recent_sells_7d', 0)} sells")
            else:
                context_parts.append(f"Error: {summary['error']}")
        
        # 2. Current Holdings Details
        portfolio = crypto_data.get("portfolio", [])
        if portfolio:
            context_parts.append("\n=== CURRENT HOLDINGS ===")
            # Sort by current value (highest first)
            sorted_portfolio = sorted(portfolio, key=lambda x: x.get("current_value", 0), reverse=True)
            
            for coin in sorted_portfolio[:15]:  # Top 15 holdings
                symbol = coin.get("symbol", "N/A")
                amount = coin.get("amount", 0)
                current_price = coin.get("current_price", 0)
                current_value = coin.get("current_value", 0)
                pct_change = coin.get("pct_change", 0)
                purchase_date = coin.get("purchase_date", "N/A")
                sentiment = coin.get("sentiment", "")
                note = coin.get("note", "")
                
                holding_line = f"{symbol}: {amount:.6f} @ ${current_price:.4f} = ${current_value:.2f} ({pct_change:+.2f}%)"
                if purchase_date and purchase_date != "N/A":
                    holding_line += f" [purchased: {purchase_date}]"
                if sentiment:
                    holding_line += f" [sentiment: {sentiment}]"
                if note:
                    holding_line += f" [note: {note[:50]}...]" if len(note) > 50 else f" [note: {note}]"
                
                context_parts.append(holding_line)
        else:
            context_parts.append("\n=== CURRENT HOLDINGS ===")
            context_parts.append("No active positions")
        
        # 3. Recent Transaction History
        transactions = crypto_data.get("recent_transactions", [])
        if transactions:
            context_parts.append("\n=== RECENT TRANSACTIONS ===")
            
            # Calculate total realized gains from recent transactions
            total_realized_gains = sum(tx.get("gain_loss", 0) for tx in transactions if tx.get("gain_loss"))
            
            # Get TOTAL fees paid from ALL transactions (not just recent) using ORM
            try:
                from trading_models import AllActivity
                from sqlalchemy import func
                
                total_fees_all_time = db.session.query(func.sum(AllActivity.fee)).filter(
                    AllActivity.user_id == user_id,
                    AllActivity.fee.isnot(None),
                    AllActivity.fee > 0
                ).scalar() or 0
            except Exception as e:
                logger.warning(f"Could not calculate total fees for user {user_id}: {e}")
                total_fees_all_time = 0
            
            if total_realized_gains != 0:
                context_parts.append(f"Total Realized Gains/Losses: ${total_realized_gains:,.2f}")
            if total_fees_all_time > 0:
                context_parts.append(f"**Total Fees Paid (ALL TIME): ${total_fees_all_time:,.2f}**")
            
            context_parts.append("Recent Activity:")
            for tx in transactions[:20]:  # Latest 20 transactions
                date = tx.get("date", "N/A")
                tx_type = tx.get("type", "N/A")
                asset = tx.get("asset", "N/A")
                amount = tx.get("amount", 0)
                proceeds = tx.get("proceeds")
                cost_basis = tx.get("cost_basis")
                gain_loss = tx.get("gain_loss")
                fee = tx.get("fee")
                exchange = tx.get("exchange", "")
                
                tx_line = f"{date}: {tx_type} {amount:.6f} {asset}"
                if proceeds is not None:
                    tx_line += f" for ${proceeds:.2f}"
                if gain_loss is not None and gain_loss != 0:
                    tx_line += f" (P&L: ${gain_loss:+.2f})"
                if fee is not None and fee > 0:
                    tx_line += f" [fee: ${fee:.2f}]"
                if exchange:
                    tx_line += f" [{exchange}]"
                
                context_parts.append(tx_line)
        else:
            context_parts.append("\n=== RECENT TRANSACTIONS ===")
            context_parts.append("No transaction history available")
        
        # 4. Portfolio Value History & Performance Trends
        value_history = crypto_data.get("portfolio_value_history", [])
        if len(value_history) >= 2:
            context_parts.append("\n=== PORTFOLIO PERFORMANCE TRENDS ===")
            
            current_value = value_history[0].get("value", 0)
            oldest_value = value_history[-1].get("value", 0)
            period_days = len(value_history)
            
            if oldest_value > 0:
                total_change_pct = ((current_value - oldest_value) / oldest_value) * 100
                context_parts.append(f"Current Portfolio Value: ${current_value:,.2f}")
                context_parts.append(f"{period_days}-day Performance: {total_change_pct:+.2f}%")
            
            # Weekly performance if we have enough data
            if len(value_history) >= 7:
                week_ago_value = value_history[6].get("value", 0)
                if week_ago_value > 0:
                    weekly_change = ((current_value - week_ago_value) / week_ago_value) * 100
                    context_parts.append(f"7-day Performance: {weekly_change:+.2f}%")
            
            # Add recent value points for trend analysis
            context_parts.append("Recent Value History:")
            for entry in value_history[:10]:  # Last 10 data points
                date = entry.get("date", "N/A")
                value = entry.get("value", 0)
                context_parts.append(f"  {date}: ${value:,.2f}")
        else:
            context_parts.append("\n=== PORTFOLIO PERFORMANCE TRENDS ===")
            context_parts.append("Insufficient historical data for trend analysis")
        
        # Join all context parts
        full_context = "\n".join(context_parts)
        
        logger.info(f"Generated comprehensive portfolio context for user {user_id}: "
                   f"{len(portfolio)} holdings, {len(transactions)} transactions, "
                   f"{len(value_history)} value history points")
        
        return full_context
        
    except Exception as e:
        logger.error(f"Error getting comprehensive portfolio context: {e}")
        return f"Portfolio data temporarily unavailable: {str(e)}"
        return "Portfolio data temporarily unavailable"

def process_ai_conversation(user_id, message, conversation_id):
    """
    Process AI conversation with 3-STAGE AGENTIC WORKFLOW and WEB SEARCH
    
    CRITICAL: Follows CryptoAppInstructions.md Rule #11
    - MUST use call_ai_with_web_search for ALL AI interactions
    - MUST include Brave Search API (with DuckDuckGo fallback)
    - MUST honor user's AI provider/model settings (never hardcode)
    """
    try:
        # Get user object
        user = User.query.filter_by(id=user_id).first()
        if not user:
            return "User not found. Please try logging in again.", conversation_id
        
        # Ensure we always have a conversation identifier for persistence/threading
        if not conversation_id:
            conversation_id = f"manual-{uuid.uuid4().hex}"
        
        # Check if AI is enabled (instruction #11 - honor AI Integration Settings)
        if not is_ai_enabled(user.username):
            return "AI analysis is disabled. Please enable AI in your Settings to use this feature.", conversation_id
        
        # Get user's AI settings (instruction #11 - never hardcode AI providers/models)
        user_settings = get_user_ai_settings(user.username)
        
        # Log user message first
        log_ai_conversation(user_id, 'manual', 'user', message, conversation_id=conversation_id)
        
        logger.info(f"🤖 AI Copilot chat started for user {user_id} with 3-stage agentic workflow + web search")
        
        # Get comprehensive portfolio context for AI
        try:
            portfolio_context = get_comprehensive_portfolio_context(user_id)
        except Exception as e:
            logger.warning(f"Could not get comprehensive portfolio context for user {user_id}: {e}")
            portfolio_context = ""

        # Get recent conversation history for context (last 5 exchanges)
        try:
            # Use SQLAlchemy ORM instead of legacy SQLite
            recent_conversations = AIConversation.query.filter_by(
                user_id=user_id,
                prompt_type='manual'
            ).order_by(AIConversation.id.desc()).limit(10).all()

            conversation_lines = []
            for conv in reversed(recent_conversations):
                role = "User" if conv.sender == "user" else "Assistant"
                body_snippet = (conv.body or "")[:200]
                conversation_lines.append(f"{role}: {body_snippet}...")
            conversation_context = "\n".join(conversation_lines)
        except Exception as e:
            logger.warning(f"Could not get conversation history: {e}")
            conversation_context = ""

        def _trim_context(text, limit):
            if not text or limit <= 0:
                return ""
            if len(text) <= limit:
                return text
            return text[:max(0, limit - 3)] + "..."

        max_tokens = int(user_settings.get('ai_max_tokens', 2000) or 2000)
        max_context_chars = max(1000, max_tokens * 4)
        portfolio_budget = int(max_context_chars * 0.4)
        conversation_budget = max_context_chars - portfolio_budget
        portfolio_context = _trim_context(portfolio_context, portfolio_budget)
        conversation_context = _trim_context(conversation_context, conversation_budget)

        manual_prompt = (
            "MANUAL_CHAT_DATA\n"
            f"user_message: {message}\n"
            "portfolio_context:\n"
            f"{portfolio_context}\n"
            "conversation_context:\n"
            f"{conversation_context}\n"
        )

        # Prepare messages for 3-stage agentic workflow
        messages = [
            {"role": "user", "content": manual_prompt}
        ]
        
        # Get AI provider and model from user settings
        ai_provider = user_settings.get('ai_provider', 'openai')
        model = user_settings.get('ai_model', 'gpt-5')
        
        logger.info(f"🔍 Calling 3-stage agentic workflow: Provider={ai_provider}, Model={model}")
        
        # CRITICAL: Use call_ai_with_web_search for 3-stage agentic workflow with web search
        # This ensures Brave Search API (with DuckDuckGo fallback) is ALWAYS used
        try:
            response, full_stage3_prompt = call_ai_with_web_search(
                username=user.username,
                messages=messages,
                model=model,
                user_id=user_id,
                prompt_type='manual',
                symbol=None,
                include_db_context=True
            )
            
            # Extract AI response text
            if hasattr(response, 'choices'):
                ai_response = response.choices[0].message.content
            else:
                ai_response = str(response)
            
            logger.info(f"✅ 3-stage agentic workflow completed successfully - response length: {len(ai_response)} chars")
            
        except Exception as e:
            logger.error(f"❌ 3-stage agentic workflow failed for user {user_id}: {e}")
            # Return error message instead of silently failing
            clean_err = str(e).replace('\\n', ' ')[:240]
            ai_response = f"I encountered an error processing your request with web search: {clean_err}. Please try again or check your AI settings."
        
        # Log AI response
        log_ai_conversation(user_id, 'manual', 'ai', ai_response, conversation_id=conversation_id)
        
        return ai_response, conversation_id
        
    except Exception as e:
        logger.error(f"Error in process_ai_conversation for user {user_id}: {e}")
        return "I apologize, but I encountered an error processing your request. Please try again.", conversation_id

# ========================
# WORKING DESKTOP ROUTES  
# ========================
# These routes bypass the decorator issues with the original desktop routes

@app.route('/api/desktop/login', methods=['POST'])  
def desktop_login_working():
    """Login endpoint for desktop app using username/password - Working version"""
    return desktop_login()

@app.route('/api/desktop/notifications')
def api_desktop_notifications_working():
    """Get notifications for desktop app - Working version"""  
    return api_desktop_notifications()

@app.route('/api/desktop/generate-token', methods=['POST'])
@login_required
def generate_desktop_token_working():
    """Generate long-lived token for desktop app - Working version"""
    return generate_desktop_token()

# Start Flask production server only if run directly

if __name__ == '__main__':
    from routes.auth import auth_bp
    from routes.ai import ai_bp
    from routes.portfolio import portfolio_bp
    from routes.system import system_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(system_bp)
    
    from utils import get_app_port
    port = get_app_port()
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
