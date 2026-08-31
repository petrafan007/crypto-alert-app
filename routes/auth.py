
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

from flask import Blueprint, request, jsonify, session, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash

from core.extensions import db
from credentials import User, Credential, UserSetting
from models import DefaultAIPrompt, AIPrompt
from log import logger
from services.credential_service import get_user_credentials
from credential_security import EncryptionKeyError, decrypt_secret
from services.onboarding_service import (
    ONBOARDING_PAGES,
    exchange_requirement_met,
    seed_new_user_defaults,
)
import json
import re

# Create Blueprint
auth_bp = Blueprint('auth', __name__)


def _onboarding_setting(user_id=None):
    target_user_id = user_id or current_user.id
    setting = UserSetting.query.filter_by(user_id=target_user_id).first()
    if not setting:
        setting = UserSetting(user_id=target_user_id)
        db.session.add(setting)
    return setting


def _valid_password(password):
    return bool(
        password and len(password) >= 12
        and re.search(r'[A-Z]', password)
        and re.search(r'[a-z]', password)
        and re.search(r'\d', password)
        and re.search(r'[^A-Za-z0-9]', password)
    )


@auth_bp.before_app_request
def enforce_required_onboarding():
    """Keep new accounts out of the application until an exchange is verified."""
    if not current_user.is_authenticated:
        return None
    setting = UserSetting.query.filter_by(user_id=current_user.id).first()
    if not setting or not setting.onboarding_required or setting.onboarding_completed:
        return None
    path = request.path
    allowed_exact = {
        '/onboarding', '/api/session', '/api/logout', '/logout',
        '/privacy', '/terms', '/acceptable-use', '/risk-disclosure', '/support',
        '/api/settings', '/api/test-binance-connection',
        '/api/test-webull-connection', '/api/webull/accounts',
        '/api/webull/enabled-accounts', '/api/webull/default-account',
        '/api/webull/portfolio-preview',
        '/api/test-ai-connection-generic', '/api/ai/models',
        '/api/test-brave-search', '/api/trading/2fa/setup',
        '/api/trading/2fa/verify-setup',
    }
    allowed_prefixes = ('/api/onboarding/', '/api/webull-token/', '/assets/', '/static/')
    if path in allowed_exact or any(path.startswith(prefix) for prefix in allowed_prefixes):
        return None
    if path.startswith('/api/'):
        return jsonify({
            'success': False,
            'onboarding_required': True,
            'error': 'Complete onboarding before using the application.',
        }), 428
    return redirect('/onboarding')

@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """API endpoint for logging in. Returns JSON only, with 2FA verification if enabled on profile."""
    import pyotp
    from trading_models import TradingSettings

    data = request.get_json() or request.form or {}
    username = (data.get("username") or "").strip()
    password = data.get("password")
    two_factor_code = (data.get("two_factor_code") or data.get("code") or "").strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required."}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"success": False, "error": "Invalid username or password."}), 401

    # Check if user has 2FA enabled on profile
    settings = TradingSettings.query.filter_by(user_id=user.id).first()
    if settings and settings.totp_secret:
        if not two_factor_code:
            return jsonify({
                "success": False,
                "requires_2fa": True,
                "message": "Two-factor authentication code required."
            }), 200

        try:
            totp = pyotp.TOTP(settings.totp_secret)
            if not totp.verify(two_factor_code, valid_window=1):
                return jsonify({
                    "success": False,
                    "requires_2fa": True,
                    "error": "Invalid 2FA code. Please try again."
                }), 401
        except Exception as totp_err:
            logger.error(f"Error validating login 2FA for {username}: {totp_err}")
            return jsonify({
                "success": False,
                "requires_2fa": True,
                "error": "Failed to verify 2FA code."
            }), 401

    login_user(user, remember=True)
    session.permanent = True
    onboarding = _onboarding_setting(user.id)
    return jsonify({
        "success": True,
        "user": {"username": user.username, "id": user.id},
        "onboarding_required": bool(onboarding.onboarding_required and not onboarding.onboarding_completed),
    })


@auth_bp.route('/api/session', methods=['GET'])
@login_required
def api_session():
    setting = _onboarding_setting()
    return jsonify({
        'success': True,
        'user': {'id': current_user.id, 'username': current_user.username},
        'onboarding_required': bool(setting.onboarding_required and not setting.onboarding_completed),
    })

@auth_bp.route("/api/logout", methods=["POST"])
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

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = (data.get('username') or '').strip()
            password = data.get('password')
            email = (data.get('email') or '').strip().lower()
            accepted_terms = bool(data.get('accepted_terms'))
        else:
            username = request.form.get('username')
            password = request.form.get('password')
            email = (request.form.get('email') or '').strip().lower()
            accepted_terms = request.form.get('accepted_terms') in ('true', '1', 'yes', 'on')
        
        if not username or not password or not email:
            return jsonify({"error": "Username, email, and password are required."}), 400
        if not 3 <= len(username) <= 80:
            return jsonify({"error": "Username must be between 3 and 80 characters."}), 400
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            return jsonify({"error": "Enter a valid email address."}), 400
        if not _valid_password(password):
            return jsonify({"error": "Password must be at least 12 characters and include uppercase, lowercase, number, and special characters."}), 400
        if not accepted_terms:
            return jsonify({"error": "Accept the Terms, Privacy Policy, and trading-risk disclosures to continue."}), 400
        try:
            # Check if user exists
            user = db.session.query(User).filter_by(username=username).first()
            if user:
                return jsonify({"error": "Username already exists"}), 400
            if db.session.query(User).filter_by(email=email).first():
                return jsonify({"error": "An account already uses that email address."}), 400
            
            # Create new user
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.flush()
            
            # Create empty Credential record for the new user
            new_cred = Credential(user_id=new_user.id, username=new_user.username)
            db.session.add(new_cred)

            # Create default UserSetting record
            new_settings = UserSetting(
                user_id=new_user.id,
                onboarding_required=True,
                onboarding_completed=False,
                onboarding_page='security-choice',
                webull_environment='production',
                tax_cost_basis_method='fifo',
            )
            db.session.add(new_settings)
            seed_new_user_defaults(new_user.id, new_settings)
            db.session.commit()
            
            # Log in the new user immediately
            session.permanent = True
            login_user(new_user, remember=True)
            logger.info(f"User {new_user.username} registered successfully and logged in")

            return jsonify({
                "success": True,
                "message": "Account created successfully",
                "redirect": "/onboarding",
                "onboarding_required": True,
                "user": {
                    "id": new_user.id,
                    "username": new_user.username,
                    "email": new_user.email,
                    "onboarding_required": True
                }
            }), 201
            
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            db.session.rollback()
            return jsonify({"error": "Registration failed. Please try again."}), 500
    
    # For GET requests, serve the React app by importing the shared helper
    logger.info("Register GET request, serving React app")
    return serve_react_app()

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    logger.info(f"Login request: method={request.method}")
    if request.method == "POST":
        logger.info("Login POST request received")
        try:
            username = request.form["username"]
            password = request.form["password"]
            logger.info(f"Login attempt for username: {username}")
            
            user = User.query.filter_by(username=username).first()
            logger.info(f"User found: {user is not None}")
                
            if user and user.check_password(password):
                logger.info(f"Password check successful for user: {username}")
                login_user(user, remember=True)
                session.permanent = True
                logger.info("Login successful, redirecting to dashboard")
                return redirect(url_for("dashboard"))
            else:
                logger.error(f"Login failed: invalid username or password for {username}")
                return jsonify({"error": "Invalid username or password"}), 401
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    # For GET requests, serve the React app by importing the shared helper
    logger.info("Login GET request, serving React app")
    return serve_react_app()

@auth_bp.route("/logout")
def logout():
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
    return redirect(url_for("auth.login"))

@auth_bp.route("/reset-password", methods=["GET", "POST"])
@login_required
def reset_password():
    if request.method == "POST":
        password = request.form.get("password")
        if not _valid_password(password):
            return jsonify({"error": "Password must be at least 12 characters and include uppercase, lowercase, number, and special characters."}), 400
        user = db.session.get(User, current_user.id)
        user.pwd_hash = generate_password_hash(password)
        db.session.commit()
        return jsonify({"success": True, "message": "Password updated"})
    
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


@auth_bp.route('/onboarding', methods=['GET', 'POST'])
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
        
    # For GET requests, serve the React app by importing the shared helper
    logger.info("Onboarding GET request, serving React app")
    return serve_react_app()


@auth_bp.route('/api/onboarding/status', methods=['GET'])
@login_required
def onboarding_status():
    from trading_models import TradingSettings

    setting = _onboarding_setting()
    cred = Credential.query.filter_by(user_id=current_user.id).first()
    trading = TradingSettings.query.filter_by(user_id=current_user.id).first()
    try:
        connected_accounts = json.loads(setting.webull_connected_accounts or '[]')
    except (TypeError, ValueError):
        connected_accounts = []
    try:
        enabled_account_ids = json.loads(setting.webull_enabled_account_ids or '[]')
    except (TypeError, ValueError):
        enabled_account_ids = []
    ai_tiers = {}
    for tier, suffix in (('primary', ''), ('secondary', '_fallback'), ('tertiary', '_tertiary')):
        provider_field = 'ai_provider' if tier == 'primary' else f'ai_provider_{tier}'
        model_field = 'ai_model' if tier == 'primary' else f'ai_model_{tier}'
        provider = getattr(setting, provider_field, None)
        encrypted_key = getattr(cred, f'_{provider}_key{suffix}', None) if cred and provider else None
        ai_tiers[tier] = {
            'provider': provider or '',
            'model': getattr(setting, model_field, None) or '',
            'configured': bool(provider and encrypted_key),
        }
    return jsonify({
        'success': True,
        'required': bool(setting.onboarding_required),
        'completed': bool(setting.onboarding_completed),
        'page': setting.onboarding_page or 'security-choice',
        'exchange_choice': setting.onboarding_exchange_choice or '',
        'binance_verified': bool(setting.onboarding_binance_verified),
        'webull_verified': bool(setting.onboarding_webull_verified),
        'exchange_requirement_met': exchange_requirement_met(setting),
        'two_factor_enabled': bool(trading and trading.totp_secret),
        'two_factor_deferred': bool(setting.onboarding_two_factor_deferred),
        'binance_configured': bool(cred and cred._api_key and cred._api_secret),
        'webull_configured': bool(cred and cred._webull_app_key and cred._webull_app_secret),
        'webull_token_status': getattr(cred, 'webull_token_status', None) if cred else None,
        'webull_accounts': connected_accounts,
        'webull_enabled_account_ids': enabled_account_ids,
        'ai_tiers': ai_tiers,
        'ai_skipped': bool(setting.onboarding_ai_skipped),
        'search_skipped': bool(setting.onboarding_search_skipped),
        'telegram_skipped': bool(setting.onboarding_telegram_skipped),
        'search_configured': bool(cred and (cred._brave_search_api_key or cred._news_api)),
        'telegram_configured': bool(cred and cred._telegram_token and cred._telegram_chat_id),
    })


@auth_bp.route('/api/onboarding/progress', methods=['POST'])
@login_required
def onboarding_progress():
    setting = _onboarding_setting()
    data = request.get_json(silent=True) or {}
    if 'page' in data:
        page = str(data.get('page') or '')
        if page not in ONBOARDING_PAGES:
            return jsonify({'success': False, 'error': 'Unknown onboarding page.'}), 400
        setting.onboarding_page = page
    if 'exchange_choice' in data:
        choice = str(data.get('exchange_choice') or '').lower()
        if choice not in {'binance', 'webull', 'both'}:
            return jsonify({'success': False, 'error': 'Choose Binance.US, Webull, or both.'}), 400
        setting.onboarding_exchange_choice = choice
    flag_fields = {
        'two_factor_deferred': 'onboarding_two_factor_deferred',
        'ai_skipped': 'onboarding_ai_skipped',
        'search_skipped': 'onboarding_search_skipped',
        'telegram_skipped': 'onboarding_telegram_skipped',
    }
    for payload_field, model_field in flag_fields.items():
        if payload_field in data:
            setattr(setting, model_field, bool(data[payload_field]))
    db.session.commit()
    return jsonify({'success': True, 'page': setting.onboarding_page})


@auth_bp.route('/api/onboarding/telegram-test', methods=['POST'])
@login_required
def onboarding_telegram_test():
    data = request.get_json(silent=True) or {}
    token = str(data.get('telegram_token') or '').strip()
    chat_id = str(data.get('telegram_chat_id') or '').strip()
    if not token or not chat_id:
        return jsonify({'success': False, 'message': 'Enter both the bot token and chat ID.'}), 400
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': 'Test message from Crypto & Securities Dashboard onboarding.'},
            timeout=10,
        )
        result = response.json() if response.content else {}
        if not response.ok or not result.get('ok'):
            return jsonify({
                'success': False,
                'message': result.get('description') or 'Telegram could not deliver the test message.',
            }), 400
        cred = Credential.query.filter_by(user_id=current_user.id).first()
        if not cred:
            cred = Credential(user_id=current_user.id, username=current_user.username)
            db.session.add(cred)
        cred.telegram_token = token
        cred.telegram_chat_id = chat_id
        setting = _onboarding_setting()
        setting.onboarding_telegram_skipped = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Test message delivered successfully.'})
    except EncryptionKeyError:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Credential encryption is not configured.'}), 500
    except Exception as exc:
        db.session.rollback()
        logger.warning('Telegram onboarding test failed: %s', exc)
        return jsonify({'success': False, 'message': 'Telegram could not deliver the test message.'}), 502


@auth_bp.route('/api/onboarding/finish', methods=['POST'])
@login_required
def onboarding_finish():
    setting = _onboarding_setting()
    if not setting.onboarding_exchange_choice:
        return jsonify({'success': False, 'error': 'Choose at least one exchange.'}), 400
    if not exchange_requirement_met(setting):
        return jsonify({'success': False, 'error': 'Successfully connect at least one selected exchange before opening the Dashboard.'}), 400
    setting.onboarding_completed = True
    setting.onboarding_required = False
    setting.has_seen_onboarding = True
    setting.onboarding_page = 'review'
    db.session.commit()
    return jsonify({'success': True, 'redirect': '/'})



@auth_bp.route('/api/get-credentials')
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

@auth_bp.route("/test-session")
@login_required
def test_session():
    return f"Logged in as: {getattr(current_user, 'username', None)}"

@auth_bp.route("/api/account/delete", methods=["DELETE"])
@login_required
def delete_account():
    try:
        user_id = current_user.id
        username = current_user.username
        
        # 1. Delete records from all tables
        # From models.py
        from models import (
            Coin, WatchlistCoin, Notification, StakedCoin, StakingReward,
            AIPrompt, AIConversation, AICache, AIAnalysisSchedule,
            SentimentHistory, ExternalSentimentSignal,
            WebullAccountSnapshot, WebullActivity, WebullHistoricalOrder, WebullHolding, WebullTestAccount,
            WebullTestPosition, WebullTestOrder
        )
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
        SentimentHistory.query.filter_by(user_id=user_id).delete()
        ExternalSentimentSignal.query.filter_by(user_id=user_id).delete()
        WebullAccountSnapshot.query.filter_by(user_id=user_id).delete()
        WebullActivity.query.filter_by(user_id=user_id).delete()
        WebullHistoricalOrder.query.filter_by(user_id=user_id).delete()
        WebullHolding.query.filter_by(user_id=user_id).delete()
        WebullTestAccount.query.filter_by(user_id=user_id).delete()
        WebullTestPosition.query.filter_by(user_id=user_id).delete()
        WebullTestOrder.query.filter_by(user_id=user_id).delete()
        
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
        logger.error(f"Error deleting account: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete account. Please try again."}), 500

@auth_bp.route('/api/account')
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
