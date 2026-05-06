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

# Import helpers from main (to be refactored later into services)
from main import (
    serve_react_app,
    get_user_credentials, _format_date_only,
    _coerce_activity_datetime, _dashboard_staking_response, _format_activity_date,
    _respond_with_staking_dashboard_payload, create_extension_jwt, fetch_binance_price,
    get_last_alert_state, get_user_ai_settings, get_user_from_bearer, get_user_from_desktop_session,
    is_encryption_available, is_persisted_key_available, persist_encryption_key, record_true_portfolio_value,
    set_initial_price_on_gift, sync_binance_logs, sync_portfolio_from_binance, EncryptionKeyError,
    ALERT_CHECK_INTERVAL
)

from flask import make_response, send_file

# Blueprint Definition
system_bp = Blueprint('system', __name__)

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
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        update_file_path = os.path.join(base_dir, "desktop_app", "dist", "CryptoDesktopApp.exe")
        
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
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(base_dir, 'upgrade.sh')
        log_path = os.path.join(base_dir, 'upgrade_background.log')
        
        if not os.path.exists(script_path):
            return jsonify({"success": False, "error": "Upgrade script not found"}), 404
            
        # Run the script in the background so it doesn't kill the request midway
        # We redirect output to a log file
        subprocess.Popen(
            f"nohup {script_path} > {log_path} 2>&1 &",
            shell=True,
            executable='/bin/bash'
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


@system_bp.route("/settings")
@login_required
def settings_page():
    """Serve the settings page"""
    return serve_react_app()


@system_bp.route("/dashboard")
@login_required
def dashboard_page():
    """Serve the dashboard page"""
    return serve_react_app()


@system_bp.route("/logs")
@login_required
def logs_page():
    """Serve the logs page"""
    return serve_react_app()


@login_required
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


# ========================
# WORKING DESKTOP ROUTES  
# ========================
# These routes bypass the decorator issues with the original desktop routes

@system_bp.route('/api/desktop/login', methods=['POST'])  
def desktop_login_working():
    """Login endpoint for desktop app using username/password - Working version"""
    return desktop_login()


@system_bp.route('/api/desktop/notifications')
def api_desktop_notifications_working():
    """Get notifications for desktop app - Working version"""  
    return api_desktop_notifications()


@system_bp.route('/api/desktop/generate-token', methods=['POST'])
@login_required
def generate_desktop_token_working():
    """Generate long-lived token for desktop app - Working version"""
    return generate_desktop_token()_token()ept Exception as e:
        logger.error(f"Get settings error: {str(e)}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ========================
# WORKING DESKTOP ROUTES  
# ========================
# These routes bypass the decorator issues with the original desktop routes

@system_bp.route('/api/desktop/login', methods=['POST'])  
def desktop_login_working():
    """Login endpoint for desktop app using username/password - Working version"""
    return desktop_login()


@system_bp.route('/api/desktop/notifications')
def api_desktop_notifications_working():
    """Get notifications for desktop app - Working version"""  
    return api_desktop_notifications()


@system_bp.route('/api/desktop/generate-token', methods=['POST'])
@login_required
def generate_desktop_token_working():
    """Generate long-lived token for desktop app - Working version"""
    return generate_desktop_token()_token()