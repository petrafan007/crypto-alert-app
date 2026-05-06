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

# Notification helper moved to services.notification_service
from services.notification_service import save_notification_record
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

# Database and Logging
from database import db
from log import logger

# Models
from models import (
    Coin, WatchlistCoin, Notification, AIPrompt, AIConversation, 
    StakedCoin, StakingReward, AICache, AIAnalysisSchedule, 
    PriceHistory, DefaultAIPrompt
)
from credentials import User, Credential, UserSetting, DesktopToken
from trading_models import (
    TestOrder, RealOrder, TestPortfolio, TradingSettings, 
    AllActivity, PortfolioValueHistory, StakingOrder
)

# Service Imports
from services.binance_service import (
    fetch_binance_price, sync_binance_account, sync_real_order_statuses_for_user,
    process_binance_trades, update_coins_from_binance_balances, 
    update_average_entry_prices, binance_rate_limiter
)
from services.portfolio_service import (
    compute_portfolio_total_value, record_true_portfolio_value, 
    get_portfolio_data_for_user, get_comprehensive_crypto_data_for_user
)
from services.trading_service import calculate_avg_entry_fifo, get_cost_basis_for_asset
from services.notification_service import (
    send_telegram_message, send_telegram_alert, notify_order_fill,
    save_notification_record
)
from services.credential_service import get_user_credentials, get_user_credentials_dict
from services.staking_service import calculate_staking_value_for_user, binance_us_api_call
from services.common import _coerce_float
from services.analysis_service import calculate_symbol_snapshot, calculate_volatility
from services.scheduler_tasks import (
    background_binance_sync_loop, portfolio_alert_loop, 
    watchlist_alert_loop, volatility_alert_loop, 
    get_last_alert_state, set_last_alert_state, _normalize_threshold
)

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
        start_background_jobs()
        _jobs_started = True
    except Exception as e:
        logger.error(f"Failed to start background jobs: {e}")

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql:///cryptoalertapp?host=/var/run/postgresql&port=5433')
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
# Legacy SQLite configurations removed. Using PostgreSQL via DATABASE_URL.
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
        except Exception:
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


# CORS handling for specific paths
@app.after_request
def _static_cors_headers(resp):
    try:
        if request.path.startswith('/static/assets/'):
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
    except Exception:
        pass
    return resp

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


ALERT_CHECK_INTERVAL = 30
STABLE_COINS = {"USDT", "USDC", "DAI", "TUSD", "USDP", "EURC", "PYUSD"}
AUTO_ALERT_CACHE = {}  # { (symbol, type): { 'value': float, 'updated': datetime } }
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
PRICE_CACHE = {}  # {symbol: (price, timestamp)}
PRICE_CACHE_TTL = 300  # 5 minutes
NEWS_SENTIMENT_CACHE = {}  # {symbol: (sentiment, timestamp)}
NEWS_SENTIMENT_CACHE_TTL = 600  # 10 minutes
# Determine base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, 'app_debug.log')

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







def start_background_jobs():
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
    binance_sync_thread = threading.Thread(target=background_binance_sync_loop, args=(app,), daemon=True)
    binance_sync_thread.start()
    background_threads.append(binance_sync_thread)
    
    # Start portfolio alert loop
    portfolio_alert_thread = threading.Thread(target=portfolio_alert_loop, args=(app,), daemon=True)
    portfolio_alert_thread.start()
    background_threads.append(portfolio_alert_thread)
    
    # Start watchlist alert loop
    watchlist_alert_thread = threading.Thread(target=watchlist_alert_loop, args=(app,), daemon=True)
    watchlist_alert_thread.start()
    background_threads.append(watchlist_alert_thread)
    
    # Start volatility alert loop
    volatility_alert_thread = threading.Thread(target=volatility_alert_loop, args=(app,), daemon=True)
    volatility_alert_thread.start()
    background_threads.append(volatility_alert_thread)
    
    # Start portfolio value recorder (runs hourly)
    portfolio_recorder_thread = threading.Thread(target=portfolio_value_recorder_loop, daemon=True)
    portfolio_recorder_thread.start()
    background_threads.append(portfolio_recorder_thread)

    # Start new AI Scheduler Service
    from services.ai_scheduler import AISchedulerService
    ai_scheduler = AISchedulerService(app)
    ai_scheduler_thread = threading.Thread(target=ai_scheduler.run, daemon=True)
    ai_scheduler_thread.start()
    background_threads.append(ai_scheduler_thread)
    
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
            from services.ai_scheduler import is_user_analysis_window_active
            if not is_user_analysis_window_active(user_id):
                logger.info(f"Skipping sentiment analysis for {username} - outside analysis window")
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
        start_background_jobs()
    
    return len(background_threads) > 0

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
 # (moved) Scheduler to update every 2 hours — moved into start_background_jobs()
 # (Deleted import-time BackgroundScheduler for update_auto_alert_cache; job is added inside start_background_jobs.)

def run_background_jobs_once():
    if not getattr(run_background_jobs_once, "started", False):
        start_background_jobs()
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
    return redirect(url_for('auth.login'))

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
                        found_symbols_local = set(str(s.get('asset', '')).upper() for s in staking_data)
                        if asset in found_symbols_local:
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

@app.route("/trading")
@login_required
def trading_page():
    """Serve the trading page"""
    return serve_react_app()

@app.route("/watchlist")
@login_required
def watchlist_page():
    """Serve the watchlist page"""
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

@app.route('/api/account')
@login_required
def api_account():
    """Get Binance account information including balances"""
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


# In-memory cache for klines data (5-minute TTL)
_KLINES_CACHE = {}
_KLINES_CACHE_TTL = 300  # 5 minutes


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

# Register Blueprints
from routes.auth import auth_bp
from routes.ai import ai_bp
from routes.portfolio import portfolio_bp
from routes.system import system_bp
app.register_blueprint(auth_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(system_bp)

# Start Flask production server only if run directly
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5011, debug=False, use_reloader=False)
c workflow failed for user {user_id}: {e}")
            # Return error message instead of silently failing
            clean_err = str(e).replace('\\n', ' ')[:240]
            ai_response = f"I encountered an error processing your request with web search: {clean_err}. Please try again or check your AI settings."
        
        # Log AI response
        log_ai_conversation(user_id, 'manual', 'ai', ai_response, conversation_id=conversation_id)
        
        return ai_response, conversation_id
        
    except Exception as e:
        logger.error(f"Error in process_ai_conversation for user {user_id}: {e}")
        return "I apologize, but I encountered an error processing your request. Please try again.", conversation_id

# Register Blueprints
from routes.auth import auth_bp
from routes.ai import ai_bp
from routes.portfolio import portfolio_bp
from routes.system import system_bp
app.register_blueprint(auth_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(system_bp)

# Start Flask production server only if run directly
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5011, debug=False, use_reloader=False)
