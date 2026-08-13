
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

# Import extensions if needed

# Create Blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/api/login", methods=["POST"])
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
            
            login_user(new_user)
            return jsonify({"success": True, "redirect": "/settings?new_user=true", "user_id": new_user.id}), 200
            
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            db.session.rollback()
            return jsonify({"error": f"Registration failed: {str(e)}"}), 500
    return jsonify({"error": "GET method not supported"}), 405

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
        if not password or len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
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
    return jsonify({"error": "GET method not supported"}), 405

@auth_bp.route("/register", methods=["POST"])
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
        from credentials import Credential, User, UserSettingSetting, DesktopToken, User
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