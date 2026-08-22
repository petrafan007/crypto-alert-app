
from datetime import timedelta, datetime
import requests
import threading
from flask import send_file, request, jsonify, render_template, current_app, redirect, url_for
from flask_login import current_user, login_required, login_user, logout_user
from models import Coin, WatchlistCoin, Notification, PriceHistory
from credentials import Credential, User, UserSetting
from core.extensions import db
from log import logger
from routes.helpers import *

import os
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import text

# Database & Models
from core.extensions import db
from models import Notification, Coin, WatchlistCoin, AIPrompt, DefaultAIPrompt
from credentials import User, UserSetting, Credential

# Log
from log import logger

# Service Imports
from services.helpers import format_date_only as _format_date_only
from services.credential_service import get_user_credentials, is_encryption_available, is_persisted_key_available, persist_encryption_key, EncryptionKeyError
from services.binance_service import sync_portfolio_from_binance
from services.portfolio_service import record_true_portfolio_value
from services.analysis_service import get_user_ai_settings
from services.notification_service import save_notification_record

# Stub/Direct logic for system helpers
def fetch_binance_price(symbol): 
    import requests
    try:
        if not symbol.endswith('USD'): symbol = f"{symbol}USD"
        res = requests.get(f"https://api.binance.us/api/v3/ticker/price?symbol={symbol}", timeout=5)
        return float(res.json()['price']) if res.status_code == 200 else None
    except: return None

def get_last_alert_state():
    from services.notification_service import get_alert_state
    return get_alert_state()

def get_user_from_desktop_session():
    return None # Placeholder

from flask import make_response, send_file

# Blueprint Definition
system_bp = Blueprint('system', __name__)



# Extension login endpoint (JWT)
@system_bp.route('/api/extension/login', methods=['POST'])
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


@system_bp.route('/api/desktop/login', methods=['POST'])
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
        
        with current_app.app_context():
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
            secret_key = current_app.config.get('SECRET_KEY', 'desktop-app-secret-key')
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
@system_bp.route('/api/desktop/generate-token', methods=['POST'])
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
        
        with current_app.app_context():
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


@system_bp.route('/api/desktop/notifications')
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


@system_bp.route('/api/desktop/check-update', methods=['GET'])
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


@system_bp.route('/api/desktop/download-update', methods=['GET'])
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
@system_bp.route('/api/notifications')
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
        if str(include_hidden).lower() not in ['1', 'true', 'yes']:
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
@system_bp.route('/api/notifications/<int:notif_id>/hide', methods=['POST'])
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


@system_bp.route('/api/logs/all')
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


@system_bp.route('/api/logs/sync', methods=['POST'])
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


@system_bp.route('/api/logs/import', methods=['POST'])
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



@system_bp.route('/logs.html')
@login_required
def logs_html():
    return jsonify({"error": "Logs page not available in React app"}), 404


@system_bp.route('/api/system/upgrade', methods=['POST'])
@login_required
def api_system_upgrade():
    """Trigger the auto-upgrade script to pull the latest version from GitHub"""
    try:
        import subprocess
        # Check if user is admin (optional, assuming current_user is validated)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(root_dir, 'upgrade.sh')
        
        if not os.path.exists(script_path):
            return jsonify({"success": False, "error": "Upgrade script not found"}), 404
            
        log_path = os.path.join(root_dir, 'upgrade_background.log')
        
        target_version = ""
        if request.is_json:
            target_version = request.json.get("target_version", "")
        
        # Sanitize target_version (only allow alphanumeric, dots, and hyphens)
        import re
        if target_version and not re.match(r'^[\w\.\-]+$', target_version):
            return jsonify({"success": False, "error": "Invalid version format"}), 400

        # Run the script in the background so it doesn't kill the request midway
        # We redirect output to a log file
        cmd = f"/usr/bin/nohup {script_path}"
        if target_version:
            cmd += f" {target_version}"
        cmd += f" > {log_path} 2>&1 &"
        
        # Ensure standard paths are in the environment so system binaries like 'git' and 'date' work
        env = os.environ.copy()
        env['PATH'] = f"{env.get('PATH', '')}:/usr/local/bin:/usr/bin:/bin"

        subprocess.Popen(
            cmd,
            shell=True,
            cwd=root_dir,
            executable='/bin/bash',
            env=env
        )
        
        return jsonify({
            "success": True, 
            "message": "Upgrade initiated. The system will pull the latest version and restart shortly."
        })
    except Exception as e:
        logger.error(f"Error triggering upgrade: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@system_bp.route("/dashboard.html")
@login_required
def dashboard_html():
    record_true_portfolio_value()
    # Serve the React app
    return serve_react_app()


@system_bp.route("/api/logs/taxable")
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


@system_bp.route("/api/alert-status", methods=["GET"])
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



@system_bp.route("/api/staking/dashboard-summary", methods=["GET"])
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



@system_bp.route("/api/staking/dashboard-summary-live", methods=["GET"])
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


# ==================== END STAKING API ROUTES ====================

@system_bp.route("/api/staking/dashboard-summary-dashboard", methods=["GET"])
@system_bp.route("/api/staking/dashboard-summary-dashboard/<path:cache_buster>", methods=["GET"])
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



@system_bp.route("/api/staking/dashboard-view", methods=["POST"])
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


@system_bp.route("/api/settings", methods=["GET", "POST"])
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
            cred = Credential(user_id=current_user.id, username=username)
            db.session.add(cred)
            db.session.commit()
        
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
                'sentiment_analysis_frequency_hours', 'watchlist_sentiment_analysis_frequency_hours',
                'portfolio_schedule_start_time', 'watchlist_schedule_start_time',
                'volatility_hours',
                'ai_provider_fallback', 'ai_model_fallback', 'ai_reasoning_level_fallback',
                'ai_provider_secondary', 'ai_model_secondary', 'ai_reasoning_level_secondary',
                'ai_provider_tertiary', 'ai_model_tertiary', 'ai_reasoning_level_tertiary',
                'ai_reasoning_level',
                'browser_notifications_enabled', 'toast_notifications_enabled'
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
                        'portfolio_review_pre', 'portfolio_review_post',
                        'coin_analysis_pre', 'coin_analysis_post',
                        'sentiment_prompt_pre', 'sentiment_prompt_post',
                        'watchlist_sentiment_prompt_pre', 'watchlist_sentiment_prompt_post'
                    ]
                    for field in prompt_fields:
                        if field in value:
                            setattr(ai_prompts, field, value[field])
                    continue 

                # Explicit column updates
                if key in allowed_fields:
                    if key in ['ai_enabled', 'ai_notifications_enabled', 'ai_web_search_enabled', 'browser_notifications_enabled', 'toast_notifications_enabled']:
                         target_key = 'browser_notifications_enabled' if key == 'toast_notifications_enabled' else key
                         setattr(user_setting, target_key, bool(value))
                    elif key in ['ai_cache_duration_hours', 'ai_max_tokens', 'sentiment_analysis_frequency_hours', 'watchlist_sentiment_analysis_frequency_hours', 'volatility_hours']:
                        try:
                            parsed_value = int(value)
                            if key == 'volatility_hours' and parsed_value < 1:
                                raise ValueError('Volatility Hours must be at least 1')
                            setattr(user_setting, key, parsed_value)
                        except:
                            pass
                    elif key in ['ai_confidence_threshold']:
                        try:
                            setattr(user_setting, key, float(value))
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
                if 'inception_key' in data:
                    cred.inception_key = data['inception_key']
                
                # Secondary (Fallback) Keys
                if 'openai_key_fallback' in data:
                    cred.openai_key_fallback = data['openai_key_fallback']
                if 'zai_key_fallback' in data:
                    cred.zai_key_fallback = data['zai_key_fallback']
                if 'perplexity_key_fallback' in data:
                    cred.perplexity_key_fallback = data['perplexity_key_fallback']
                if 'gemini_key_fallback' in data:
                    cred.gemini_key_fallback = data['gemini_key_fallback']
                if 'inception_key_fallback' in data:
                    cred.inception_key_fallback = data['inception_key_fallback']
                if 'inception_key_secondary' in data:
                    cred.inception_key_fallback = data['inception_key_secondary']

                # Tertiary Keys
                if 'openai_key_tertiary' in data:
                    cred.openai_key_tertiary = data['openai_key_tertiary']
                if 'zai_key_tertiary' in data:
                    cred.zai_key_tertiary = data['zai_key_tertiary']
                if 'perplexity_key_tertiary' in data:
                    cred.perplexity_key_tertiary = data['perplexity_key_tertiary']
                if 'gemini_key_tertiary' in data:
                    cred.gemini_key_tertiary = data['gemini_key_tertiary']
                if 'inception_key_tertiary' in data:
                    cred.inception_key_tertiary = data['inception_key_tertiary']

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
                            user_prompts.watchlist_sentiment_prompt_pre = getattr(defaults, 'watchlist_sentiment_prompt_pre', '')
                            user_prompts.watchlist_sentiment_prompt_post = getattr(defaults, 'watchlist_sentiment_prompt_post', '')
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
            "inception_key": getattr(cred, 'inception_key', None),
            "openai_key_fallback": getattr(cred, 'openai_key_fallback', None),
            "zai_key_fallback": getattr(cred, 'zai_key_fallback', None),
            "perplexity_key_fallback": getattr(cred, 'perplexity_key_fallback', None),
            "gemini_key_fallback": getattr(cred, 'gemini_key_fallback', None),
            "inception_key_fallback": getattr(cred, 'inception_key_fallback', None),
            "openai_key_tertiary": getattr(cred, 'openai_key_tertiary', None),
            "zai_key_tertiary": getattr(cred, 'zai_key_tertiary', None),
            "perplexity_key_tertiary": getattr(cred, 'perplexity_key_tertiary', None),
            "gemini_key_tertiary": getattr(cred, 'gemini_key_tertiary', None),
            "inception_key_tertiary": getattr(cred, 'inception_key_tertiary', None),
            # ai_provider is already in ai_settings, but ensure sync? 
            # ai_settings takes precedence as it handles defaults and user_settings overlay
            "telegram_token": cred.telegram_token,
            "telegram_chat_id": cred.telegram_chat_id,
            "news_api": cred.news_api,
            "brave_search_api_key": getattr(cred, 'brave_search_api_key', None),
            "brave_search_api_key_fallback": getattr(cred, 'brave_search_api_key_fallback', None),
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




@system_bp.route('/api/check-credential')
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

@system_bp.route("/api/update-note", methods=["POST"])
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

@system_bp.route("/api/set-initial-price", methods=["POST"])
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

@system_bp.route("/api/set-custom-pct", methods=["POST"])
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

@system_bp.route("/api/set-alert", methods=["POST"])
@login_required
def set_alert():
    data = request.get_json()
    coin = Coin.query.filter_by(id=data["id"], user_id=current_user.id).first()
    if not coin:
        return jsonify({"error": "Coin not found"}), 404
    coin.alert_enabled = not coin.alert_enabled  # Toggle the alert
    db.session.commit()
    return jsonify({"success": True, "alert_enabled": coin.alert_enabled})

@system_bp.route("/api/set-custom-pct-type", methods=["POST"])
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

@system_bp.route("/api/clear-alert-state", methods=["POST"])
@login_required
def api_clear_alert_state():
    try:
        removed = clear_alert_state(current_user.id)
        return jsonify({"success": True, "removed": removed})
    except Exception as e:
        logger.error(f"/api/clear-alert-state error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@system_bp.route("/api/debug-alerts")
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

@system_bp.route("/api/set-watch-alert", methods=["POST"])
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

@system_bp.route("/api/set-watch-alert-type", methods=["POST"])
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

@system_bp.route('/api/set-volatility-pct', methods=['POST'])
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

def _get_user_binance_free_balance(user_id, asset):
    """Fetch live free balance of USD or USDT for a user from Binance.US"""
    try:
        from credentials import Credential
        from services.credential_service import decrypt_secret
        from binance.client import Client

        creds = Credential.query.filter_by(user_id=user_id).first()
        if not creds:
            return 0.0

        api_key = decrypt_secret(creds.api_key) or decrypt_secret(creds.trading_api_key)
        api_secret = decrypt_secret(creds.api_secret) or decrypt_secret(creds.trading_api_secret)
        if not api_key or not api_secret:
            return 0.0

        client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
        acc = client.get_account()
        for b in acc.get('balances', []):
            if (b.get('asset') or '').upper() == asset.upper():
                return float(b.get('free', 0.0))
        return 0.0
    except Exception as e:
        logger.warning(f"Error checking free balance of {asset} for user {user_id}: {e}")
        return 0.0

@system_bp.route('/api/portfolio/trigger-auto-sell', methods=['POST'])
@login_required
def trigger_auto_sell():
    """Enable or disable Auto-Sell on volatility drop for a portfolio or watchlist coin."""
    try:
        data = request.get_json() or {}
        symbol = (data.get('symbol') or '').upper()
        coin_id = data.get('id')
        table_type = (data.get('table_type') or 'portfolio').lower()
        quote_currency = (data.get('quote_currency') or 'USDT').upper()
        if quote_currency not in ('USD', 'USDT'):
            quote_currency = 'USDT'
        enabled = data.get('enabled', True)
        volatility_pct = data.get('volatility_pct')
        
        user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        vol_hours = int(getattr(user_setting, 'volatility_hours', 24) or 24)
        
        coin = None
        if table_type == 'watchlist':
            if coin_id:
                coin = WatchlistCoin.query.filter_by(user_id=current_user.id, id=coin_id).first()
            if not coin and symbol:
                coin = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
        else:
            if coin_id:
                coin = Coin.query.filter_by(user_id=current_user.id, id=coin_id).first()
            if not coin and symbol:
                coin = Coin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
            
        if not coin:
            return jsonify({"success": False, "error": f"{symbol} not found in {table_type}"}), 404
            
        if enabled:
            if volatility_pct is not None:
                try:
                    coin.volatility_pct = float(volatility_pct)
                except (ValueError, TypeError):
                    pass
            
            pct_val = float(coin.volatility_pct or 0)
            if pct_val <= 0:
                return jsonify({"success": False, "error": "Please set a valid Volatility % greater than 0 before enabling Auto-Sell."}), 400
                
            coin.auto_sell_enabled = True
            coin.auto_sell_volatility_pct = pct_val
            coin.auto_sell_quote_currency = quote_currency
            coin.auto_sell_triggered_at = None
            db.session.commit()
            logger.info(f"Auto-sell ({quote_currency}) enabled for user {current_user.username}: {coin.symbol} at {pct_val}% drop in {vol_hours}h.")
            return jsonify({
                "success": True,
                "message": f"Auto-sell enabled for {coin.symbol}. It will automatically sell for {quote_currency} if the price drops more than {pct_val:.1f}% within {vol_hours} hour(s).",
                "auto_sell_enabled": True,
                "auto_sell_quote_currency": quote_currency,
                "volatility_pct": pct_val,
                "volatility_hours": vol_hours
            })
        else:
            coin.auto_sell_enabled = False
            db.session.commit()
            logger.info(f"Auto-sell disabled for user {current_user.username}: {coin.symbol}")
            return jsonify({
                "success": True,
                "message": f"Auto-sell disabled for {coin.symbol}.",
                "auto_sell_enabled": False
            })
    except Exception as e:
        logger.error(f"Error toggling auto-sell: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@system_bp.route('/api/portfolio/auto-buy-balance-info', methods=['GET'])
@login_required
def get_auto_buy_balance_info():
    """Return live free balance, reserved auto-buy allocations, and available funds for a quote currency."""
    try:
        quote_currency = (request.args.get('quote_currency') or 'USDT').upper()
        if quote_currency not in ('USD', 'USDT'):
            quote_currency = 'USDT'
            
        current_symbol = (request.args.get('symbol') or '').upper()
        current_id = request.args.get('id')
        current_table = (request.args.get('table_type') or 'portfolio').lower()

        free_balance = _get_user_binance_free_balance(current_user.id, quote_currency)

        # Calculate all other active commitments for this quote currency
        portfolio_coins = Coin.query.filter_by(user_id=current_user.id, auto_buy_enabled=True).all()
        watchlist_coins = WatchlistCoin.query.filter_by(user_id=current_user.id, auto_buy_enabled=True).all()

        active_commitments = []
        reserved_total = 0.0

        for c in portfolio_coins:
            c_quote = (getattr(c, 'auto_buy_quote_currency', None) or 'USDT').upper()
            if c_quote == quote_currency:
                c_amt = float(getattr(c, 'auto_buy_amount', 0.0) or 0.0)
                is_current = (current_table == 'portfolio' and (str(c.id) == str(current_id) or c.symbol == current_symbol))
                active_commitments.append({
                    'id': c.id,
                    'symbol': c.symbol,
                    'amount': c_amt,
                    'quote_currency': c_quote,
                    'table_type': 'portfolio',
                    'is_current': is_current
                })
                if not is_current:
                    reserved_total += c_amt

        for w in watchlist_coins:
            w_quote = (getattr(w, 'auto_buy_quote_currency', None) or 'USDT').upper()
            if w_quote == quote_currency:
                w_amt = float(getattr(w, 'auto_buy_amount', 0.0) or 0.0)
                is_current = (current_table == 'watchlist' and (str(w.id) == str(current_id) or w.symbol == current_symbol))
                active_commitments.append({
                    'id': w.id,
                    'symbol': w.symbol,
                    'amount': w_amt,
                    'quote_currency': w_quote,
                    'table_type': 'watchlist',
                    'is_current': is_current
                })
                if not is_current:
                    reserved_total += w_amt

        available_balance = max(0.0, free_balance - reserved_total)

        return jsonify({
            'success': True,
            'quote_currency': quote_currency,
            'free_balance': round(free_balance, 2),
            'reserved_balance': round(reserved_total, 2),
            'available_balance': round(available_balance, 2),
            'active_commitments': active_commitments
        })
    except Exception as e:
        logger.error(f"Error fetching auto-buy balance info: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@system_bp.route('/api/portfolio/trigger-auto-buy', methods=['POST'])
@login_required
def trigger_auto_buy():
    """Enable or disable Auto-Buy on volatility surge for a portfolio or watchlist coin with reserved balance validation."""
    try:
        data = request.get_json() or {}
        symbol = (data.get('symbol') or '').upper()
        coin_id = data.get('id')
        table_type = (data.get('table_type') or 'portfolio').lower()
        quote_currency = (data.get('quote_currency') or 'USDT').upper()
        if quote_currency not in ('USD', 'USDT'):
            quote_currency = 'USDT'
        enabled = data.get('enabled', True)
        amount = data.get('amount')
        volatility_pct = data.get('volatility_pct')

        user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        vol_hours = int(getattr(user_setting, 'volatility_hours', 24) or 24)

        coin = None
        if table_type == 'watchlist':
            if coin_id:
                coin = WatchlistCoin.query.filter_by(user_id=current_user.id, id=coin_id).first()
            if not coin and symbol:
                coin = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
        else:
            if coin_id:
                coin = Coin.query.filter_by(user_id=current_user.id, id=coin_id).first()
            if not coin and symbol:
                coin = Coin.query.filter_by(user_id=current_user.id, symbol=symbol).first()

        if not coin:
            return jsonify({"success": False, "error": f"{symbol} not found in {table_type}"}), 404

        if enabled:
            try:
                alloc_amount = float(amount or 0.0)
            except (ValueError, TypeError):
                alloc_amount = 0.0

            if alloc_amount < 1.00:
                return jsonify({
                    "success": False,
                    "error": f"Minimum allocation amount is $1.00 {quote_currency}."
                }), 400

            # Validate against live free balance and existing reserved commitments
            free_balance = _get_user_binance_free_balance(current_user.id, quote_currency)

            portfolio_coins = Coin.query.filter_by(user_id=current_user.id, auto_buy_enabled=True).all()
            watchlist_coins = WatchlistCoin.query.filter_by(user_id=current_user.id, auto_buy_enabled=True).all()

            reserved_total = 0.0
            other_commitments = []
            for c in portfolio_coins:
                if (getattr(c, 'auto_buy_quote_currency', None) or 'USDT').upper() == quote_currency:
                    if not (table_type == 'portfolio' and (str(c.id) == str(coin_id) or c.symbol == symbol)):
                        c_amt = float(getattr(c, 'auto_buy_amount', 0.0) or 0.0)
                        reserved_total += c_amt
                        other_commitments.append(f"{c.symbol}: ${c_amt:.2f}")

            for w in watchlist_coins:
                if (getattr(w, 'auto_buy_quote_currency', None) or 'USDT').upper() == quote_currency:
                    if not (table_type == 'watchlist' and (str(w.id) == str(coin_id) or w.symbol == symbol)):
                        w_amt = float(getattr(w, 'auto_buy_amount', 0.0) or 0.0)
                        reserved_total += w_amt
                        other_commitments.append(f"{w.symbol}: ${w_amt:.2f}")

            available_to_allocate = max(0.0, free_balance - reserved_total)

            if alloc_amount > available_to_allocate + 0.0001:
                comm_str = f" (already reserved for {', '.join(other_commitments)})" if other_commitments else ""
                return jsonify({
                    "success": False,
                    "error": f"Cannot allocate ${alloc_amount:.2f} {quote_currency}. Available uncommitted balance is ${available_to_allocate:.2f} {quote_currency}{comm_str}."
                }), 400

            if volatility_pct is not None:
                try:
                    coin.volatility_pct = float(volatility_pct)
                except (ValueError, TypeError):
                    pass

            pct_val = float(coin.volatility_pct or 0)
            if pct_val <= 0:
                return jsonify({"success": False, "error": "Please set a valid Volatility % greater than 0 before enabling Auto-Buy."}), 400

            coin.auto_buy_enabled = True
            coin.auto_buy_volatility_pct = pct_val
            coin.auto_buy_quote_currency = quote_currency
            coin.auto_buy_amount = alloc_amount
            coin.auto_buy_triggered_at = None
            db.session.commit()

            logger.info(f"Auto-buy ({quote_currency}) enabled for user {current_user.username}: {coin.symbol} (${alloc_amount:.2f}) at +{pct_val}% surge in {vol_hours}h.")
            return jsonify({
                "success": True,
                "message": f"Auto-buy enabled for {coin.symbol}. It will automatically purchase with ${alloc_amount:.2f} {quote_currency} if the price surges more than {pct_val:.1f}% within {vol_hours} hour(s).",
                "auto_buy_enabled": True,
                "auto_buy_amount": alloc_amount,
                "auto_buy_quote_currency": quote_currency,
                "volatility_pct": pct_val,
                "volatility_hours": vol_hours
            })
        else:
            coin.auto_buy_enabled = False
            db.session.commit()
            logger.info(f"Auto-buy disabled for user {current_user.username}: {coin.symbol}")
            return jsonify({
                "success": True,
                "message": f"Auto-buy disabled for {coin.symbol}.",
                "auto_buy_enabled": False
            })
    except Exception as e:
        logger.error(f"Error toggling auto-buy: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@system_bp.route("/api/mark-onboarding-complete", methods=["POST"])
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

@system_bp.route("/api/support/send", methods=["POST"])
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



@system_bp.route("/api/test-brave-search", methods=['POST'])
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

_TRADING_PAIRS_CACHE = {
    'pairs': None,
    'timestamp': 0
}

FALLBACK_USD_PAIRS = [
    'AAVEUSD', 'ADAUSD', 'ALGOUSD', 'ATOMUSD', 'AVAXUSD', 'BCHUSD', 'BNBUSD', 'BONKUSD',
    'BTCUSD', 'CRVUSD', 'DGBUSD', 'DOGEUSD', 'DOTUSD', 'ENSUSD', 'ETCUSD', 'ETHUSD',
    'FETUSD', 'FLOKIUSD', 'GALAUSD', 'GRTUSD', 'HBARUSD', 'HYPEUSD', 'ICPUSD', 'IOTAUSD',
    'JUPUSD', 'LINKUSD', 'LPTUSD', 'LTCUSD', 'MEUSD', 'NEARUSD', 'ONEUSD', 'OPUSD',
    'PEPEUSD', 'POLUSD', 'RENDERUSD', 'RVNUSD', 'SANDUSD', 'SHIBUSD', 'SOLUSD', 'SUIUSD',
    'SUSD', 'SUSHIUSD', 'THETAUSD', 'TRUMPUSD', 'TRXUSD', 'UNIUSD', 'USDCUSD', 'USDTUSD',
    'VETUSD', 'VTHOUSD', 'XLMUSD', 'XRPUSD', 'ZECUSD', 'ZILUSD'
]

FALLBACK_USDT_PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'ADAUSDT', 'DOGEUSDT', 'SUIUSDT',
    'AVAXUSDT', 'LINKUSDT', 'DOTUSDT', 'NEARUSDT', 'PEPEUSDT', 'SHIBUSDT', 'LTCUSDT', 'UNIUSDT',
    'ATOMUSDT', 'ALGOUSDT', 'BCHUSDT', 'TRXUSDT', 'XLMUSDT', 'FETUSDT', 'RENDERUSDT', 'HBARUSDT',
    'ICPUSDT', 'AAVEUSDT', 'CRVUSDT', 'SANDUSDT', 'GALAUSDT', 'CELRUSDT', 'LPTUSDT', 'ONTUSDT',
    'KSMUSDT', 'BONKUSDT', 'FLOKIUSDT', 'INJUSDT', 'ARBUSDT', 'OPUSDT', 'TIAUSDT', 'SEIUSDT',
    'JUPUSDT', 'ENAUSDT', 'WIFUSDT', 'TRUMPUSDT', 'USDCUSDT'
]

@system_bp.route('/api/trading-pairs')
@login_required
def api_trading_pairs():
    """Get available trading pairs - BINANCE.US VERSION with full USD and USDT coverage"""
    import time
    now = time.time()
    if _TRADING_PAIRS_CACHE['pairs'] and (now - _TRADING_PAIRS_CACHE['timestamp']) < 300:
        return jsonify({'pairs': _TRADING_PAIRS_CACHE['pairs']})

    try:
        res = requests.get('https://api.binance.us/api/v3/exchangeInfo', timeout=5)
        if res.status_code == 200:
            data = res.json()
            symbols = data.get('symbols', [])
            usd_pairs = []
            usdt_pairs = []
            other_pairs = []
            
            for sym in symbols:
                if sym.get('status') != 'TRADING':
                    continue
                symbol = sym.get('symbol', '')
                base = sym.get('baseAsset', '')
                quote = sym.get('quoteAsset', '')
                
                pair_obj = {
                    'id': symbol,
                    'base_currency': base,
                    'quote_currency': quote,
                    'display_name': f"{base}/{quote}",
                    'status': 'online'
                }
                
                if quote == 'USD':
                    usd_pairs.append(pair_obj)
                elif quote == 'USDT':
                    usdt_pairs.append(pair_obj)
                else:
                    other_pairs.append(pair_obj)
            
            # Prioritize major USDT pairs at the very top (BTC/USDT first)
            priority_usdt = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'ADAUSDT', 'DOGEUSDT', 'SUIUSDT']
            def _sort_usdt(p):
                sym = p['id']
                if sym in priority_usdt:
                    return (0, priority_usdt.index(sym))
                return (1, p['base_currency'])

            priority_usd = ['BTCUSD', 'ETHUSD', 'SOLUSD', 'XRPUSD', 'ADAUSD', 'DOGEUSD']
            def _sort_usd(p):
                sym = p['id']
                if sym in priority_usd:
                    return (0, priority_usd.index(sym))
                return (1, p['base_currency'])

            usdt_pairs.sort(key=_sort_usdt)
            usd_pairs.sort(key=_sort_usd)
            other_pairs.sort(key=lambda x: x['base_currency'])
            
            all_pairs = usdt_pairs + usd_pairs + other_pairs
            if all_pairs:
                _TRADING_PAIRS_CACHE['pairs'] = all_pairs
                _TRADING_PAIRS_CACHE['timestamp'] = now
                logger.info(f"Loaded {len(all_pairs)} live Binance.US trading pairs ({len(usdt_pairs)} USDT pairs, {len(usd_pairs)} USD pairs)")
                return jsonify({'pairs': all_pairs})
    except Exception as e:
        logger.error(f"Error fetching live Binance.US exchange info: {e}")

    # Fallback if live exchange info is unreachable
    fallback_pairs = []
    for s in sorted(FALLBACK_USD_PAIRS):
        base = s[:-3]
        fallback_pairs.append({
            'id': s,
            'base_currency': base,
            'quote_currency': 'USD',
            'display_name': f"{base}/USD",
            'status': 'online'
        })
    for s in sorted(FALLBACK_USDT_PAIRS):
        base = s[:-4]
        fallback_pairs.append({
            'id': s,
            'base_currency': base,
            'quote_currency': 'USDT',
            'display_name': f"{base}/USDT",
            'status': 'online'
        })
    return jsonify({'pairs': fallback_pairs})

@system_bp.route('/api/test-simple')
def api_test_simple():
    """Simple test endpoint"""
    return jsonify({"test": "success", "message": "Simple test endpoint is working"})

@system_bp.route('/api/test-db')
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

@system_bp.route('/api/debug/background-jobs', methods=['GET'])
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