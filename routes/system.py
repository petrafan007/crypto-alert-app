
from datetime import timedelta, datetime, timezone
import requests
import threading
import time
from flask import send_file, request, jsonify, render_template, current_app, redirect, url_for, session
from flask_login import current_user, login_required, login_user, logout_user
from models import Coin, WatchlistCoin, Notification, PriceHistory
from credentials import Credential, User, UserSetting
from core.extensions import db
from log import logger
from routes.helpers import *

import os
import json
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import text

# Database & Models
from core.extensions import db
from models import Notification, Coin, WatchlistCoin, AIPrompt, DefaultAIPrompt, WebullAccountSnapshot, WebullHolding, WebullTestPosition
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
from services.webull_service import (
    WebullConnectionError,
    check_webull_access_token,
    create_webull_access_token,
    get_webull_accounts,
    get_webull_market_bars,
    get_webull_market_snapshot,
    get_webull_futures_catalog,
    get_webull_futures_contracts,
    get_webull_futures_snapshot,
    get_webull_option_snapshot,
    get_webull_option_chain_data,
    get_webull_stock_movers,
    get_webull_open_orders,
    get_webull_order_history,
    get_webull_portfolio_preview,
    place_webull_order,
    cancel_webull_order,
    normalize_webull_environment,
    parse_webull_expiry,
    get_webull_event_categories,
    get_webull_event_duration_options,
    get_webull_event_bars,
    get_webull_event_market,
    get_webull_event_markets,
    validate_webull_event_order_market,
    FALLBACK_US_FUTURES_PRODUCTS,
    test_webull_connection,
)
from services.webull_import_service import import_webull_orders, import_webull_portfolio_snapshot
from services.webull_option_service import option_contract_label, resolve_option_contract

_EVENT_UNDERLYING_HISTORY_CACHE = {}
_EVENT_UNDERLYING_HISTORY_CACHE_TTL_SECONDS = 30


def _event_underlying_history_points(raw_bars):
    points_by_time = {}
    for raw_bar in raw_bars or []:
        try:
            timestamp = int(float(raw_bar.get('time')))
            price = float(raw_bar.get('close'))
        except (AttributeError, TypeError, ValueError):
            continue
        if timestamp > 0 and price > 0:
            points_by_time[timestamp] = {'timestamp': timestamp, 'price': price}
    return [points_by_time[timestamp] for timestamp in sorted(points_by_time)]


def _get_public_crypto_minute_history(symbol):
    clean_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
    base_symbol = clean_symbol[:-3] if clean_symbol.endswith('USD') else clean_symbol
    if not base_symbol:
        raise WebullConnectionError('Choose a crypto symbol before loading Event price history.')
    from binance.client import Client

    client = Client(tld='us')
    for pair in (f'{base_symbol}USDT', f'{base_symbol}USD'):
        try:
            bars = client.get_klines(symbol=pair, interval='1m', limit=16)
            points = [
                {'timestamp': int(bar[0]) // 1000, 'price': float(bar[4])}
                for bar in bars or []
                if len(bar) > 4 and float(bar[4]) > 0
            ]
            if len(points) >= 16:
                return points, 'binance_us'
        except Exception:
            continue
    raise WebullConnectionError(f'No public one-minute history is available for {base_symbol}.')


def _get_event_underlying_history(credential, environment, symbol, instrument_type):
    clean_type = str(instrument_type or '').strip().upper()
    clean_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
    if clean_type == 'CRYPTO':
        return _get_public_crypto_minute_history(clean_symbol)
    if clean_type not in {'EQUITY', 'STOCK', 'ETF'}:
        raise WebullConnectionError('This Event Contract underlying does not support one-minute history.')
    bars = get_webull_market_bars(
        credential.webull_app_key, credential.webull_app_secret, environment,
        credential.webull_access_token, symbol=clean_symbol,
        instrument_type='EQUITY', interval='M1', limit=20,
    )
    points = _event_underlying_history_points(bars)
    if len(points) < 16:
        raise WebullConnectionError(f'Webull returned insufficient one-minute history for {clean_symbol}.')
    return points, 'webull'


def _webull_holding_for_current_user(holding_id):
    """Resolve a dashboard ``webull-<id>`` reference without trusting its owner."""
    raw_id = str(holding_id or '').removeprefix('webull-')
    try:
        return WebullHolding.query.filter_by(id=int(raw_id), user_id=current_user.id).first()
    except (TypeError, ValueError):
        return None


WEBULL_OPTION_CONTRACT_MULTIPLIER = 100
WEBULL_OPTION_STRIKE_EPSILON = 0.0001
WEBULL_OPTION_STRATEGIES = {
    'SINGLE', 'COVERED_STOCK', 'VERTICAL', 'STRADDLE', 'STRANGLE', 'CALENDAR',
    'BUTTERFLY', 'CONDOR', 'IRON_BUTTERFLY', 'IRON_CONDOR',
    'COLLAR_WITH_STOCK', 'DIAGONAL',
}


def _webull_number(value, default=0.0):
    try:
        if value is None or value == '':
            return default
        numeric = float(str(value).replace(',', '').replace('$', '').strip())
        return numeric if numeric == numeric else default
    except (TypeError, ValueError):
        return default


def _webull_option_value(position, *keys):
    """Read a contract field from current or legacy Webull position shapes."""
    if not isinstance(position, dict):
        return None
    details = next((
        position.get(key) for key in ('option', 'option_contract', 'optionContract', 'instrument')
        if isinstance(position.get(key), dict)
    ), {})
    for source in (position, details):
        for key in keys:
            value = source.get(key)
            if value not in (None, ''):
                return value
    return None


def _webull_option_expiry(value):
    if value is None or value == '':
        return ''
    parsed = parse_webull_expiry(value)
    if parsed:
        return parsed.strftime('%Y-%m-%d')
    return str(value).strip()[:10]


def _webull_position_matches_option_contract(position, *, underlying_symbol, option_type, option_strike, option_expiration):
    if str(position.get('instrument_type') or '').strip().upper() not in {'OPTION', 'OPTIONS'}:
        return False
    position_underlying = str(_webull_option_value(position, 'underlying_symbol', 'underlyingSymbol', 'underlying') or '').strip().upper()
    position_type = str(_webull_option_value(position, 'option_type', 'optionType', 'put_call', 'putCall') or '').strip().upper()
    position_expiry = _webull_option_expiry(_webull_option_value(position, 'option_expire_date', 'optionExpireDate', 'expiration_date', 'expirationDate', 'expiry_date'))
    position_strike = _webull_number(_webull_option_value(position, 'strike_price', 'strikePrice', 'strike'), None)
    requested_strike = _webull_number(option_strike, None)
    return (
        position_underlying == str(underlying_symbol or '').strip().upper()
        and position_type == str(option_type or '').strip().upper()
        and position_expiry == _webull_option_expiry(option_expiration)
        and position_strike is not None
        and requested_strike is not None
        and abs(position_strike - requested_strike) <= WEBULL_OPTION_STRIKE_EPSILON
    )


def _live_webull_option_order_capability(credential, environment, account_id, *, underlying_symbol, option_type, option_strike, option_expiration):
    """Return fresh USD cash and exact held-contract quantity for an order preflight.

    This intentionally reads Webull for every option-order attempt rather than
    trusting a possibly stale browser or database snapshot. A failed read is a
    failed preflight; the order is never forwarded without current capability.
    """
    preview = get_webull_portfolio_preview(
        credential.webull_app_key,
        credential.webull_app_secret,
        environment,
        credential.webull_access_token,
        account_ids=[account_id],
    )
    account = next((item for item in preview if str(item.get('account_id') or '') == str(account_id)), None)
    if not account:
        raise WebullConnectionError('Webull did not return the selected account. Refresh the Webull connection and try again.')
    balance = account.get('balance') if isinstance(account.get('balance'), dict) else {}
    available_cash = max(0.0, _webull_number(
        balance.get('total_cash_balance', balance.get('cash_balance', balance.get('settled_cash', 0.0)))
    ))
    owned_contracts = sum(
        max(0.0, _webull_number(position.get('quantity')))
        for position in (account.get('positions') or [])
        if isinstance(position, dict) and _webull_position_matches_option_contract(
            position,
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            option_strike=option_strike,
            option_expiration=option_expiration,
        )
    )
    return available_cash, owned_contracts


def _live_webull_event_owned_contracts(credential, environment, account_id, *, symbol, event_outcome):
    """Return the provider's currently available quantity for one exact Yes/No position."""
    preview = get_webull_portfolio_preview(
        credential.webull_app_key,
        credential.webull_app_secret,
        environment,
        credential.webull_access_token,
        account_ids=[account_id],
    )
    account = next((item for item in preview if str(item.get('account_id') or '') == str(account_id)), None)
    if not account:
        raise WebullConnectionError('Webull did not return the selected Event Contract account.')
    clean_symbol = str(symbol or '').strip().upper()
    clean_outcome = str(event_outcome or '').strip().upper()
    available = 0.0
    for position in account.get('positions') or []:
        if not isinstance(position, dict) or str(position.get('instrument_type') or '').strip().upper() != 'EVENT':
            continue
        position_symbol = str(position.get('underlying_symbol') or position.get('symbol') or '').strip().upper()
        suffix_match = position_symbol.rsplit(' ', 1) if position_symbol.endswith((' YES', ' NO')) else (position_symbol, '')
        position_outcome = str(position.get('event_outcome') or suffix_match[1] or '').strip().upper()
        if suffix_match[0] != clean_symbol or position_outcome != clean_outcome:
            continue
        available += max(0.0, _webull_number(
            position.get('available_quantity', position.get('quantity', position.get('amount', 0.0)))
        ))
    return available


def _webull_event_connection(setting=None):
    setting = setting or UserSetting.query.filter_by(user_id=current_user.id).first()
    credential = Credential.query.filter_by(user_id=current_user.id).first()
    environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
    if (
        not credential or credential.webull_token_status != 'NORMAL'
        or credential.webull_token_environment != environment or not credential.webull_access_token
    ):
        raise WebullConnectionError('Connect Webull before loading Event Contracts.')
    return credential, environment


def _preflight_webull_event_order(data, setting=None):
    if str(data.get('order_type') or '').strip().upper() != 'LIMIT':
        raise WebullConnectionError('Webull event contract orders support Limit orders only.')
    if str(data.get('time_in_force') or 'DAY').strip().upper() != 'DAY':
        raise WebullConnectionError('Webull event contract orders support Day time in force only.')
    side = str(data.get('side') or '').strip().upper()
    if side not in {'BUY', 'SELL'}:
        raise WebullConnectionError('Webull event contract orders support Buy and Sell only.')
    if str(data.get('event_outcome') or '').strip().lower() not in {'yes', 'no'}:
        raise WebullConnectionError('Event contracts require choosing Yes or No for the outcome.')
    try:
        quantity = float(data.get('quantity'))
        limit_price = float(data.get('limit_price'))
    except (TypeError, ValueError) as exc:
        raise WebullConnectionError('Enter a valid Event Contract quantity and limit price.') from exc

    credential, environment = _webull_event_connection(setting)
    market = get_webull_event_market(
        credential.webull_app_key, credential.webull_app_secret,
        environment, credential.webull_access_token,
        symbol=data.get('symbol'), force=True,
    )
    validate_webull_event_order_market(
        market, side=side, quantity=quantity, limit_price=limit_price,
    )
    return market


def _webull_json_collection(raw_value, expected_type, fallback):
    """Decode a persisted Webull collection without letting bad legacy JSON leak into a response."""
    try:
        value = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except Exception:
        value = fallback
    return value if isinstance(value, expected_type) else fallback


def _webull_account_aliases(setting):
    aliases = _webull_json_collection(getattr(setting, 'webull_account_aliases', '{}') or '{}', dict, {})
    return {
        str(account_id).strip(): str(label).strip()
        for account_id, label in aliases.items()
        if str(account_id).strip() and str(label).strip()
    }


def _webull_cached_accounts(setting):
    return _webull_json_collection(getattr(setting, 'webull_connected_accounts', '[]') or '[]', list, [])


def _webull_enabled_account_ids(setting):
    return {
        str(account_id).strip()
        for account_id in _webull_json_collection(
            getattr(setting, 'webull_enabled_account_ids', '[]') or '[]', list, []
        )
        if str(account_id).strip()
    }


def _webull_known_account_ids(setting):
    return {
        str(account.get('account_id')).strip()
        for account in _webull_cached_accounts(setting)
        if isinstance(account, dict) and str(account.get('account_id') or '').strip()
    }


def _webull_allowed_account_ids(setting):
    """Return the connected accounts the user has enabled for Webull operations.

    Older settings used an empty enabled list to mean every cached account, so
    retain that safe compatibility behavior while still rejecting an explicit
    account that is not known to the authenticated user.
    """
    known = _webull_known_account_ids(setting)
    enabled = _webull_enabled_account_ids(setting)
    return known.intersection(enabled) if enabled else known


def _require_webull_account_access(setting, account_id):
    clean_account_id = str(account_id or '').strip()
    if not clean_account_id:
        raise WebullConnectionError('Choose a Webull account.')
    allowed = _webull_allowed_account_ids(setting)
    if not allowed:
        raise WebullConnectionError('Refresh and enable a connected Webull account before trading or managing its orders.')
    if clean_account_id not in allowed:
        raise WebullConnectionError('Choose one of your enabled Webull accounts.')
    return clean_account_id


def _webull_account_is_crypto(setting, account_id):
    """Classify a connected account from the server-only account metadata."""
    clean_account_id = str(account_id or '').strip()
    for account in _webull_cached_accounts(setting):
        if not isinstance(account, dict) or str(account.get('account_id') or '').strip() != clean_account_id:
            continue
        identity = ' '.join(str(account.get(key) or '') for key in (
            'account_class', 'account_type', 'account_sub_type', 'account_label', 'account_name',
        )).lower()
        return 'crypto' in identity
    return False


def _require_webull_instrument_account_match(setting, account_id, instrument_type):
    """Keep crypto-only and non-crypto Webull accounts in their own asset lanes."""
    clean_type = str(instrument_type or 'EQUITY').strip().upper()
    if clean_type in {'COIN', 'TOKEN'}:
        clean_type = 'CRYPTO'
    if clean_type in {'FUTURE', 'FUTURES'}:
        clean_type = 'FUTURES'
    if clean_type in {'EVENT', 'EVENTS', 'EVENT_CONTRACT', 'EVENT_CONTRACTS'}:
        clean_type = 'EVENT'
    is_crypto_account = _webull_account_is_crypto(setting, account_id)
    if is_crypto_account and clean_type != 'CRYPTO':
        raise WebullConnectionError('This is a Crypto Webull account. Choose the Crypto asset class to place an order from it.')
    if not is_crypto_account and clean_type == 'CRYPTO':
        raise WebullConnectionError('Crypto orders require a Crypto Webull account. Choose a Crypto account to continue.')
    return clean_type


def _webull_account_response(accounts, *, aliases=None, snapshots=None, enabled_ids=None):
    """Expose only the browser-safe Webull account fields.

    Raw Webull account numbers are used server-side solely to derive the mask,
    then deliberately omitted from every browser response.  Imported balances
    are local snapshots, so rendering buying power never performs an account
    read or accidentally uses a different provider's cash balance.
    """
    aliases = aliases or {}
    snapshots = snapshots or {}
    enabled_ids = set(enabled_ids or [])
    response_accounts = []
    for raw_account in accounts or []:
        if not isinstance(raw_account, dict):
            continue
        account_id = str(raw_account.get('account_id') or '').strip()
        if not account_id:
            continue
        account_number = str(raw_account.get('account_number') or '').strip()
        masked = (
            str(raw_account.get('account_id_masked') or '').strip()
            or (f'••••{account_number[-4:]}' if len(account_number) >= 4 else f'••••{account_id[-4:]}')
        )
        original_label = str(
            raw_account.get('account_label') or raw_account.get('account_name')
            or raw_account.get('account_type') or 'Webull Account'
        ).strip()
        item = {
            'account_id': account_id,
            'account_label': aliases.get(account_id) or original_label,
            'account_class': raw_account.get('account_class', ''),
            'account_type': raw_account.get('account_type', 'CASH'),
            'account_name': aliases.get(account_id) or original_label,
            'account_id_masked': masked,
        }
        raw_balance = raw_account.get('balance')
        if isinstance(raw_balance, dict):
            item['balance'] = {
                key: raw_balance.get(key) for key in (
                    'total_asset_currency', 'total_cash_balance', 'total_market_value',
                    'total_net_liquidation_value', 'total_unrealized_profit_loss', 'total_day_profit_loss',
                )
            }
        snapshot = snapshots.get(account_id)
        if snapshot and 'balance' not in item:
            get_value = snapshot.get if isinstance(snapshot, dict) else lambda key, default=None: getattr(snapshot, key, default)
            item['balance'] = {
                'total_asset_currency': get_value('currency', 'USD') or 'USD',
                'total_cash_balance': get_value('total_cash_balance', 0.0) or 0.0,
                'total_market_value': get_value('total_market_value', 0.0) or 0.0,
                'total_net_liquidation_value': get_value('total_net_liquidation_value', 0.0) or 0.0,
                'total_unrealized_profit_loss': get_value('total_unrealized_profit_loss'),
            }
        if enabled_ids is not None:
            item['is_enabled'] = not enabled_ids or account_id in enabled_ids
        response_accounts.append(item)
    return response_accounts

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


def _cancellation_2fa_error(data):
    """Return a cancellation 2FA error message, or ``None`` when verified.

    The UI always presents the native six-digit confirmation modal.  When the
    user has trading 2FA enabled, this server-side check is the authority that
    prevents a Webull or app-trigger cancellation from bypassing that modal.
    """
    from trading_models import TradingSettings

    settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
    if not settings or not getattr(settings, 'require_2fa', False) or not getattr(settings, 'totp_secret', None):
        return None

    code = str((data or {}).get('two_factor_code') or (data or {}).get('twofa_code') or '').strip()
    if len(code) != 6 or not code.isdigit():
        return 'A valid 6-digit two-factor authentication code is required to cancel this order.'

    try:
        import pyotp
        if not pyotp.TOTP(settings.totp_secret).verify(code, valid_window=1):
            return 'Invalid or expired two-factor authentication code.'
    except Exception as exc:
        logger.error('Cancellation 2FA verification failed: %s', exc)
        return 'Two-factor authentication verification failed.'
    return None


GITHUB_RELEASES_API_URL = 'https://api.github.com/repos/petrafan007/crypto-alert-app/releases'


def _is_prerelease(release):
    """Return whether a GitHub release is a beta/prerelease."""
    tag_name = str(release.get('tag_name') or '')
    return bool(release.get('prerelease')) or '-' in tag_name


def fetch_latest_github_release(include_beta=False):
    """Fetch the newest eligible published release from GitHub without caching it."""
    response = requests.get(
        GITHUB_RELEASES_API_URL,
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'Crypto-Securities-Dashboard-Updater',
        },
        params={'per_page': 100},
        timeout=10,
    )
    response.raise_for_status()
    releases = response.json()
    if not isinstance(releases, list):
        raise ValueError('GitHub returned an invalid release list')

    eligible_releases = [
        release for release in releases
        if not release.get('draft')
        and release.get('tag_name')
        and (include_beta or not _is_prerelease(release))
    ]
    if not eligible_releases:
        raise LookupError('No eligible GitHub release is available')

    # GitHub returns releases newest first, but explicitly comparing timestamps
    # keeps the result correct if its response ordering ever changes.
    return max(
        eligible_releases,
        key=lambda release: release.get('published_at') or release.get('created_at') or '',
    )


def _include_beta_from_value(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}



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
                "download_url": url_for("system.download_desktop_update", _external=True),
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
    """Trigger the upgrade script for the latest eligible GitHub release."""
    try:
        import subprocess
        # Check if user is admin (optional, assuming current_user is validated)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(root_dir, 'upgrade.sh')
        
        if not os.path.exists(script_path):
            return jsonify({"success": False, "error": "Upgrade script not found"}), 404
            
        log_path = os.path.join(root_dir, 'upgrade_background.log')
        
        payload = request.get_json(silent=True) or {}
        include_beta = _include_beta_from_value(payload.get('include_beta'), default=True)
        latest_release = fetch_latest_github_release(include_beta=include_beta)
        target_version = latest_release['tag_name']

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
            "message": f"Upgrade to {target_version} initiated. The app will restart shortly.",
            "target_version": target_version,
        })
    except (requests.RequestException, LookupError, ValueError) as e:
        logger.error(f"Unable to resolve the latest GitHub release: {e}")
        return jsonify({"success": False, "error": "Unable to retrieve the latest GitHub release. Please try again."}), 502
    except Exception as e:
        logger.error(f"Error triggering upgrade: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@system_bp.route('/api/system/latest-release', methods=['GET'])
@login_required
def api_system_latest_release():
    """Return the latest published GitHub release for the in-app updater."""
    try:
        include_beta = _include_beta_from_value(request.args.get('include_beta'), default=True)
        release = fetch_latest_github_release(include_beta=include_beta)
        response = jsonify({
            'tag_name': release['tag_name'],
            'name': release.get('name') or release['tag_name'],
            'published_at': release.get('published_at'),
            'prerelease': _is_prerelease(release),
        })
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        return response
    except (requests.RequestException, LookupError, ValueError) as e:
        logger.error(f"Unable to retrieve the latest GitHub release: {e}")
        return jsonify({"error": "Unable to retrieve the latest GitHub release. Please try again."}), 502


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
            data = request.get_json() or {}
            existing_webull_environment = getattr(
                UserSetting.query.filter_by(user_id=current_user.id).first(),
                'webull_environment', None,
            ) or 'production'
            from services.sentiment_outcome_service import (
                SENTIMENT_THRESHOLD_FIELDS,
                validate_sentiment_chart_range,
                validate_sentiment_threshold_payload,
                validate_sentiment_window_payload,
            )
            window_values, window_errors = validate_sentiment_window_payload(data)
            if window_errors:
                return jsonify({"success": False, "message": "Sentiment windows are invalid.", "errors": window_errors}), 400
            data.update(window_values)
            if any(field in data for field in SENTIMENT_THRESHOLD_FIELDS):
                threshold_values, threshold_errors = validate_sentiment_threshold_payload(
                    data, require_all=True
                )
                if threshold_errors:
                    return jsonify({
                        "success": False,
                        "message": "Sentiment values are invalid. Directional Correct thresholds must be at least 0.01%; directional Wrong and Hold steady values may be 0.00%; Hold Wrong must be greater than Hold steady; all values allow at most two decimal places.",
                        "errors": threshold_errors,
                    }), 400
                data.update(threshold_values)
            if 'sentiment_chart_default_range' in data:
                chart_range, chart_range_error = validate_sentiment_chart_range(
                    data['sentiment_chart_default_range']
                )
                if chart_range_error:
                    return jsonify({
                        "success": False,
                        "message": chart_range_error,
                        "errors": {"sentiment_chart_default_range": chart_range_error},
                    }), 400
                data['sentiment_chart_default_range'] = chart_range
            if 'automated_trigger_confirmation_minutes' in data:
                try:
                    confirmation_minutes = int(data['automated_trigger_confirmation_minutes'])
                except (TypeError, ValueError):
                    confirmation_minutes = 0
                if not 1 <= confirmation_minutes <= 1440:
                    return jsonify({
                        "success": False,
                        "message": "Automated Trigger Confirmation Window must be a whole number from 1 through 1440 minutes.",
                        "errors": {"automated_trigger_confirmation_minutes": "Enter a whole number from 1 through 1440."},
                    }), 400
                data['automated_trigger_confirmation_minutes'] = confirmation_minutes
            if 'webull_environment' in data:
                try:
                    data['webull_environment'] = normalize_webull_environment(data['webull_environment'])
                except WebullConnectionError as exc:
                    return jsonify({"success": False, "message": str(exc)}), 400
            
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
                'sentiment_history_lookback_hours', 'watchlist_sentiment_history_lookback_hours',
                'sentiment_forecast_horizon_hours', 'watchlist_sentiment_forecast_horizon_hours',
                'portfolio_schedule_start_time', 'watchlist_schedule_start_time',
                'volatility_hours', 'automated_trigger_confirmation_minutes', 'ai_outcome_neutral_threshold_pct', 'max_slippage_pct',
                'webull_environment',
                'sentiment_chart_default_range',
                *SENTIMENT_THRESHOLD_FIELDS,
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
                    elif key in ['ai_cache_duration_hours', 'ai_max_tokens', 'sentiment_analysis_frequency_hours', 'watchlist_sentiment_analysis_frequency_hours', 'sentiment_history_lookback_hours', 'watchlist_sentiment_history_lookback_hours', 'sentiment_forecast_horizon_hours', 'watchlist_sentiment_forecast_horizon_hours', 'volatility_hours', 'automated_trigger_confirmation_minutes']:
                        try:
                            parsed_value = int(value)
                            if key == 'volatility_hours' and parsed_value < 1:
                                raise ValueError('Volatility Hours must be at least 1')
                            setattr(user_setting, key, parsed_value)
                        except:
                            pass
                    elif key in ['ai_confidence_threshold', 'ai_outcome_neutral_threshold_pct', 'max_slippage_pct', *SENTIMENT_THRESHOLD_FIELDS]:
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
                webull_credentials_changed = any(
                    data.get(field) and data[field] != '********'
                    for field in ('webull_app_key', 'webull_app_secret')
                )
                webull_environment_changed = (
                    'webull_environment' in data
                    and data['webull_environment'] != existing_webull_environment
                )
                if 'api_key' in data:
                    cred.api_key = data['api_key']
                if 'api_secret' in data:
                    cred.api_secret = data['api_secret']
                if data.get('webull_app_key') and data['webull_app_key'] != '********':
                    cred.webull_app_key = data['webull_app_key']
                if data.get('webull_app_secret') and data['webull_app_secret'] != '********':
                    cred.webull_app_secret = data['webull_app_secret']
                if webull_credentials_changed or webull_environment_changed:
                    # A Webull access token is bound to the app credentials and
                    # environment that created it. Do not ever reuse it elsewhere.
                    cred.clear_webull_access_token()
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
        webull_settings = UserSetting.query.filter_by(user_id=current_user.id).first()
        
        # Overlay credentials
        response.update({
            "api_key": cred.api_key,
            "api_secret": cred.api_secret,
            # Webull credentials remain server-side. Only expose whether both
            # encrypted values are available so the UI can safely mask them.
            "webull_configured": bool(cred.webull_app_key and cred.webull_app_secret),
            "webull_environment": getattr(webull_settings, 'webull_environment', None) or 'production',
            "webull_account_selection_mode": getattr(webull_settings, 'webull_account_selection_mode', None) or 'all',
            "webull_default_account_id": getattr(webull_settings, 'webull_default_account_id', None),
            "webull_token_status": (
                getattr(cred, 'webull_token_status', None)
                if getattr(cred, 'webull_token_environment', None)
                == (getattr(webull_settings, 'webull_environment', None) or 'production')
                else None
            ),
            "webull_token_expires_at": (
                cred.webull_token_expires_at.isoformat()
                if getattr(cred, 'webull_token_expires_at', None) else None
            ),
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


@system_bp.route('/api/test-webull-connection', methods=['POST'])
@login_required
def api_test_webull_connection():
    """Verify Webull credentials with a read-only account-list request."""
    try:
        data = request.get_json(silent=True) or {}
        app_key = data.get('webull_app_key')
        app_secret = data.get('webull_app_secret')
        environment = data.get('webull_environment', 'production')
        credentials = None

        # A masked field means the user is testing already-saved credentials.
        if app_key == '********':
            app_key = None
        if app_secret == '********':
            app_secret = None
        if not app_key or not app_secret:
            credentials = Credential.query.filter_by(user_id=current_user.id).first()
            app_key = app_key or getattr(credentials, 'webull_app_key', None)
            app_secret = app_secret or getattr(credentials, 'webull_app_secret', None)

        stored_token = None
        if credentials and getattr(credentials, 'webull_token_environment', None) == environment:
            stored_token = getattr(credentials, 'webull_access_token', None)
        result = test_webull_connection(app_key, app_secret, environment, stored_token)
        account_types = ', '.join(result['account_types']) or 'no account types returned'
        return jsonify({
            'success': True,
            'message': (
                f"Webull {result['environment']} connection successful. "
                f"Found {result['account_count']} account(s): {account_types}."
            ),
            **result,
        })
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull connection test failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to test the Webull connection.'}), 500


def _webull_token_payload(token_details, environment, *, account_result=None):
    """Return token state without leaking the token or App credentials to the browser."""
    status = token_details['status']
    payload = {
        'success': status == 'NORMAL',
        'status': status,
        'environment': environment,
        'expires_at': token_details.get('expires'),
        'verification_required': status == 'PENDING',
    }
    if status == 'PENDING':
        payload['message'] = (
            'Webull sent a verification request. In the Webull app, open Menu → Messages → '
            'OpenAPI Notifications, open the latest message, choose Check Now, and confirm the SMS code. '
            'Then return here and select Check Webull Verification within five minutes.'
        )
    elif status == 'NORMAL':
        accounts = account_result or {}
        account_types = ', '.join(accounts.get('account_types', [])) or 'no account types returned'
        payload.update({
            'success': True,
            'account_count': accounts.get('account_count', 0),
            'account_types': accounts.get('account_types', []),
            'message': (
                f'Webull {environment} connection verified. Found '
                f"{accounts.get('account_count', 0)} account(s): {account_types}."
            ),
        })
    else:
        payload['message'] = f'Webull reported the verification token as {status}. Start verification again.'
    return payload


def _store_webull_token(credential, token_details, environment):
    credential.webull_access_token = token_details['token']
    credential.webull_token_environment = environment
    credential.webull_token_status = token_details['status']
    credential.webull_token_expires_at = parse_webull_expiry(token_details.get('expires'))


@system_bp.route('/api/webull-token/initiate', methods=['POST'])
@login_required
def api_initiate_webull_token():
    """Create the server-side Webull token and begin its app/SMS verification flow."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if not credential or not credential.webull_app_key or not credential.webull_app_secret:
            return jsonify({
                'success': False,
                'message': 'Save your Webull App Key and App Secret before starting verification.',
            }), 400

        # Do not issue duplicate SMS challenges while an existing request is active.
        if (
            credential.webull_access_token
            and credential.webull_token_environment == environment
            and credential.webull_token_status == 'PENDING'
        ):
            return jsonify(_webull_token_payload({
                'status': 'PENDING', 'expires': credential.webull_token_expires_at.isoformat()
                if credential.webull_token_expires_at else None,
            }, environment))
        if (
            credential.webull_access_token
            and credential.webull_token_environment == environment
            and credential.webull_token_status == 'NORMAL'
        ):
            account_result = test_webull_connection(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token,
            )
            return jsonify(_webull_token_payload({
                'status': 'NORMAL', 'expires': credential.webull_token_expires_at.isoformat()
                if credential.webull_token_expires_at else None,
            }, environment, account_result=account_result))

        token_details = create_webull_access_token(
            credential.webull_app_key, credential.webull_app_secret, environment
        )
        _store_webull_token(credential, token_details, environment)
        db.session.commit()

        account_result = None
        if token_details['status'] == 'NORMAL':
            account_result = test_webull_connection(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token,
            )
        return jsonify(_webull_token_payload(token_details, environment, account_result=account_result))
    except WebullConnectionError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        logger.error('Webull token initiation failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to start Webull verification.'}), 500


@system_bp.route('/api/webull-token/status', methods=['POST'])
@login_required
def api_check_webull_token_status():
    """Check a pending Webull token after the user approves it in the Webull app."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if not credential or not credential.webull_access_token:
            return jsonify({'success': False, 'message': 'Start Webull verification first.'}), 400
        if credential.webull_token_environment != environment:
            credential.clear_webull_access_token()
            db.session.commit()
            return jsonify({'success': False, 'message': 'The saved Webull token belongs to another environment. Start verification again.'}), 400

        token_details = check_webull_access_token(
            credential.webull_app_key, credential.webull_app_secret,
            credential.webull_access_token, environment,
        )
        _store_webull_token(credential, token_details, environment)
        if token_details['status'] in {'INVALID', 'EXPIRED'}:
            credential.clear_webull_access_token()
            db.session.commit()
            return jsonify(_webull_token_payload(token_details, environment))

        account_result = None
        if token_details['status'] == 'NORMAL':
            account_result = test_webull_connection(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token,
            )
        db.session.commit()
        return jsonify(_webull_token_payload(token_details, environment, account_result=account_result))
    except WebullConnectionError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        logger.error('Webull token status check failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to check Webull verification.'}), 500


@system_bp.route('/api/webull/accounts', methods=['GET'])
@login_required
def api_webull_accounts():
    """Discover Webull accounts only; no balances, positions, orders, or data import occurs here."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential
            or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment
            or not credential.webull_access_token
        ):
            return jsonify({
                'success': False,
                'message': 'Verify your Webull connection before discovering accounts.',
            }), 400

        refresh = request.args.get('refresh', '').lower() in ('true', '1', 'yes')
        cached_accounts = _webull_cached_accounts(setting)
        enabled_ids = sorted(_webull_enabled_account_ids(setting))
        aliases = _webull_account_aliases(setting)
        snapshots = {
            str(snapshot.account_id): snapshot
            for snapshot in WebullAccountSnapshot.query.filter_by(user_id=current_user.id).all()
            if snapshot.account_id
        }

        if not refresh and cached_accounts:
            return jsonify({
                'success': True,
                'environment': environment,
                'accounts': _webull_account_response(
                    cached_accounts, aliases=aliases, snapshots=snapshots, enabled_ids=enabled_ids,
                ),
                'enabled_account_ids': enabled_ids,
                'default_account_id': getattr(setting, 'webull_default_account_id', None),
                'message': f'Loaded {len(cached_accounts)} connected Webull account(s).',
            })

        accounts = get_webull_accounts(
            credential.webull_app_key, credential.webull_app_secret,
            environment, credential.webull_access_token,
        )

        display_accounts = []
        for account in accounts:
            acc_id = str(account['account_id'])
            display_accounts.append({
                'account_id': acc_id,
                # Raw account numbers are intentionally not persisted in the
                # account-selection cache.  The browser needs only an opaque
                # account reference and a stable, masked label.
                'account_id_masked': (
                    f"••••{str(account.get('account_number') or '')[-4:]}"
                    if len(str(account.get('account_number') or '')) >= 4
                    else (f"••••{acc_id[-4:]}" if acc_id else '••••')
                ),
                'account_label': str(account.get('account_label') or account.get('account_name') or account.get('account_type') or 'Webull Account'),
                'account_class': account.get('account_class', ''),
                'account_type': account.get('account_type', 'CASH'),
                'account_name': str(account.get('account_label') or account.get('account_name') or account.get('account_type') or 'Webull Account'),
            })

        if not enabled_ids:
            enabled_ids = [a['account_id'] for a in display_accounts]

        setting.webull_connected_accounts = json.dumps(display_accounts)
        setting.webull_enabled_account_ids = json.dumps(enabled_ids)
        db.session.commit()

        return jsonify({
            'success': True,
            'environment': environment,
            'accounts': _webull_account_response(
                display_accounts, aliases=aliases, snapshots=snapshots, enabled_ids=enabled_ids,
            ),
            'enabled_account_ids': enabled_ids,
            'default_account_id': getattr(setting, 'webull_default_account_id', None),
            'message': f'Found {len(display_accounts)} Webull account(s).',
        })
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull account discovery failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to discover Webull accounts.'}), 500


@system_bp.route('/api/webull/enabled-accounts', methods=['PUT', 'POST'])
@login_required
def api_save_webull_enabled_accounts():
    """Save which Webull accounts the user wants visible/enabled in trading and navigation."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not setting:
            setting = UserSetting(user_id=current_user.id)
            db.session.add(setting)

        data = request.get_json(silent=True) or {}
        new_enabled = data.get('enabled_account_ids')
        if not isinstance(new_enabled, list):
            return jsonify({'success': False, 'message': 'Invalid enabled_account_ids payload.'}), 400

        enabled_ids = [str(x).strip() for x in new_enabled if str(x).strip()]
        known_ids = _webull_known_account_ids(setting)
        if known_ids and not set(enabled_ids).issubset(known_ids):
            return jsonify({'success': False, 'message': 'Choose only connected Webull accounts.'}), 400
        setting.webull_enabled_account_ids = json.dumps(enabled_ids)
        if setting.webull_default_account_id and setting.webull_default_account_id not in enabled_ids:
            setting.webull_default_account_id = None
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        if (
            enabled_ids and credential
            and credential.webull_token_status == 'NORMAL'
            and credential.webull_token_environment == (setting.webull_environment or 'production')
        ):
            setting.onboarding_webull_verified = True
        db.session.commit()

        return jsonify({
            'success': True,
            'enabled_account_ids': enabled_ids,
            'message': 'Enabled Webull accounts saved successfully.',
        })
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to save enabled Webull accounts: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to save account selections.'}), 500


@system_bp.route('/api/webull/default-account', methods=['PUT', 'POST'])
@login_required
def api_save_webull_default_account():
    """Persist the account selected by default on the Webull Trading page."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not setting:
            setting = UserSetting(user_id=current_user.id)
            db.session.add(setting)
        account_id = str((request.get_json(silent=True) or {}).get('account_id') or '').strip()
        if account_id:
            try:
                _require_webull_account_access(setting, account_id)
            except WebullConnectionError as exc:
                return jsonify({'success': False, 'message': str(exc)}), 400
        setting.webull_default_account_id = account_id or None
        db.session.commit()
        return jsonify({
            'success': True,
            'default_account_id': setting.webull_default_account_id,
            'message': 'Webull default trading account saved.',
        })
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to save Webull default account: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to save the default Webull account.'}), 500


@system_bp.route('/api/webull/portfolio-preview', methods=['GET'])
@login_required
def api_webull_portfolio_preview():
    """Read and display all user-selected Webull balances/positions; never writes portfolio data."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        selection_mode = getattr(setting, 'webull_account_selection_mode', None) or 'all'
        if selection_mode != 'all':
            return jsonify({'success': False, 'message': 'No Webull accounts are selected for preview.'}), 400
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Verify your Webull connection before loading the preview.'}), 400

        enabled_ids = _webull_enabled_account_ids(setting)
        aliases = _webull_account_aliases(setting)

        allowed_account_ids = _webull_allowed_account_ids(setting)
        preview = get_webull_portfolio_preview(
            credential.webull_app_key, credential.webull_app_secret,
            environment, credential.webull_access_token,
            account_ids=allowed_account_ids or None,
        )
        accounts = []
        for account in preview:
            balance = account.get('balance') if isinstance(account.get('balance'), dict) else {}
            positions = account.get('positions') or []
            acc_id = str(account.get('account_id') or '')
            account_payload = {
                'account_id': acc_id,
                'account_id_masked': (
                    f"••••{str(account.get('account_number') or '')[-4:]}"
                    if len(str(account.get('account_number') or '')) >= 4
                    else (f"••••{acc_id[-4:]}" if acc_id else '••••')
                ),
                'account_label': str(account.get('account_label') or account.get('account_name') or account.get('account_type') or 'Webull Account'),
                'account_class': account.get('account_class', ''),
                'account_type': account.get('account_type', 'CASH'),
                'account_name': str(account.get('account_label') or account.get('account_name') or account.get('account_type') or 'Webull Account'),
                'balance': {
                    key: balance.get(key) for key in (
                        'total_asset_currency', 'total_cash_balance', 'total_market_value',
                        'total_net_liquidation_value', 'total_unrealized_profit_loss', 'total_day_profit_loss',
                    )
                },
                'positions': [{
                    key: position.get(key) for key in (
                        'symbol', 'instrument_type', 'quantity', 'last_price', 'cost_price',
                        'unrealized_profit_loss', 'currency',
                    )
                } for position in positions if isinstance(position, dict)],
            }
            accounts.extend(_webull_account_response(
                [account_payload], aliases=aliases, enabled_ids=enabled_ids,
            ))
        return jsonify({
            'success': True,
            'selection_mode': 'all',
            'accounts': accounts,
            'aliases': aliases,
            'message': f'Loaded a read-only preview for {len(accounts)} Webull account(s).',
        })
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull portfolio preview failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load the Webull portfolio preview.'}), 500


@system_bp.route('/api/webull/account-aliases', methods=['PUT', 'POST'])
@login_required
def api_save_webull_account_aliases():
    """Save user-customized nicknames/aliases for connected Webull accounts."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not setting:
            setting = UserSetting(user_id=current_user.id)
            db.session.add(setting)

        data = request.get_json(silent=True) or {}
        new_aliases = data.get('aliases') or {}
        if not isinstance(new_aliases, dict):
            return jsonify({'success': False, 'message': 'Invalid aliases payload.'}), 400

        current_raw = getattr(setting, 'webull_account_aliases', '{}') or '{}'
        try:
            current_aliases = json.loads(current_raw) if isinstance(current_raw, str) else (current_raw or {})
        except Exception:
            current_aliases = {}

        for k, v in new_aliases.items():
            key_str = str(k).strip()
            val_str = str(v).strip()
            if val_str:
                current_aliases[key_str] = val_str
            elif key_str in current_aliases:
                del current_aliases[key_str]

        setting.webull_account_aliases = json.dumps(current_aliases)
        db.session.commit()
        return jsonify({
            'success': True,
            'aliases': current_aliases,
            'message': 'Webull account nicknames saved successfully.',
        })
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to save Webull account aliases: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to save account nicknames.'}), 500


@system_bp.route('/api/webull/portfolio-sync', methods=['POST'])
@login_required
def api_webull_portfolio_sync():
    """Import a current all-account Webull snapshot for unified, read-only display."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if getattr(setting, 'webull_account_selection_mode', None) not in (None, 'all'):
            return jsonify({'success': False, 'message': 'No Webull accounts are selected for import.'}), 400
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Verify your Webull connection before importing its portfolio.'}), 400
        allowed_account_ids = _webull_allowed_account_ids(setting)
        requested_ids = (request.get_json(silent=True) or {}).get('account_ids')
        if requested_ids is not None:
            if not isinstance(requested_ids, list):
                return jsonify({'success': False, 'message': 'Invalid account import selection.'}), 400
            requested_set = {str(value).strip() for value in requested_ids if str(value).strip()}
            allowed_set = set(allowed_account_ids or [])
            if not requested_set or not requested_set.issubset(allowed_set):
                return jsonify({'success': False, 'message': 'Choose only enabled Webull accounts for import.'}), 400
            allowed_account_ids = sorted(requested_set)
        preview = get_webull_portfolio_preview(
            credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
            account_ids=allowed_account_ids or None,
        )
        result = import_webull_portfolio_snapshot(current_user.id, preview)
        imported_orders = 0
        history_warning = None
        try:
            historical_orders = get_webull_order_history(
                credential.webull_app_key, credential.webull_app_secret,
                environment, credential.webull_access_token,
            )
            imported_orders = import_webull_orders(current_user.id, historical_orders)
        except WebullConnectionError as exc:
            history_warning = str(exc)
            logger.warning('Webull portfolio snapshot saved but order history refresh failed: %s', exc)
        return jsonify({
            'success': True, 'accounts': result['accounts'], 'positions': result['positions'], 'orders': imported_orders,
            'history_warning': history_warning,
            'message': f"Imported {result['positions']} Webull position(s) and {imported_orders} order(s) from {result['accounts']} account(s). Webull rows are read-only.",
        })
    except WebullConnectionError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        logger.error('Webull portfolio import failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to import the Webull portfolio.'}), 500


@system_bp.route('/api/webull/open-orders', methods=['GET'])
@login_required
def api_webull_open_orders():
    """Return Webull open orders for read-only combined order views or simulated paper open orders."""
    try:
        account_id = request.args.get('account_id')
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        paper_mode_enabled = bool(getattr(setting, 'webull_test_mode_enabled', False))
        paper_requested = account_id == 'TEST_PAPER_ACCOUNT' or request.args.get('test_mode') in {'true', '1'}
        if paper_mode_enabled and account_id and account_id != 'TEST_PAPER_ACCOUNT':
            return jsonify({
                'success': True,
                'orders': [],
                'message': 'Live Webull orders are hidden while Test Mode is active.',
            })
        if paper_mode_enabled:
            from services.webull_paper_trading_service import get_webull_test_orders
            orders = get_webull_test_orders(current_user.id)
            working_orders = [o for o in orders if o.get('status') in {'Working', 'Open'}]
            return jsonify({'success': True, 'orders': working_orders})
        if paper_requested:
            return jsonify({
                'success': True,
                'orders': [],
                'message': 'Paper orders are hidden while Webull Test Mode is disabled.',
            })

        credential = Credential.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': True, 'orders': [], 'message': 'Webull is not connected.'})

        account_id = request.args.get('account_id')
        if account_id:
            account_id = _require_webull_account_access(setting, account_id)
        orders = get_webull_open_orders(
            credential.webull_app_key, credential.webull_app_secret,
            environment, credential.webull_access_token,
            account_id=account_id,
        )
        import_webull_orders(current_user.id, orders)
        if not account_id:
            allowed_ids = _webull_allowed_account_ids(setting)
            orders = [
                order for order in orders
                if str(order.get('_webull_account_id') or '') in allowed_ids
            ]
        return jsonify({'success': True, 'orders': orders})
    except WebullConnectionError as exc:
        logger.warning('Webull open-order lookup failed: %s', exc)
        return jsonify({'success': False, 'orders': [], 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull open-order lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'orders': [], 'message': 'Unable to load Webull open orders.'}), 500


@system_bp.route('/api/webull/test/account-summary', methods=['GET'])
@login_required
def api_webull_test_account_summary():
    """Retrieve simulated paper trading balances, buying power, and P&L."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not bool(getattr(setting, 'webull_test_mode_enabled', False)):
            return jsonify({'success': False, 'message': 'Enable Webull Test Mode to view the paper account.'}), 409
        from services.webull_paper_trading_service import get_webull_test_account_summary
        summary = get_webull_test_account_summary(current_user.id)
        return jsonify({'success': True, 'summary': summary})
    except Exception as exc:
        logger.error(f"[PAPER_TRADING] Failed to get account summary: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 500


@system_bp.route('/api/webull/test/deposit', methods=['POST'])
@login_required
def api_webull_test_deposit():
    """Deposit or reset fake money in the simulated paper account."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not bool(getattr(setting, 'webull_test_mode_enabled', False)):
            return jsonify({'success': False, 'message': 'Enable Webull Test Mode before changing paper funds.'}), 409
        data = request.get_json(silent=True) or {}
        amount = float(data.get('amount') or 1000.0)
        reset = bool(data.get('reset', False))
        from services.webull_paper_trading_service import deposit_fake_money
        res = deposit_fake_money(current_user.id, amount, reset=reset)
        return jsonify(res)
    except Exception as exc:
        logger.error(f"[PAPER_TRADING] Deposit failed: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 400


@system_bp.route('/api/webull/test/positions', methods=['GET'])
@login_required
def api_webull_test_positions():
    """Retrieve all simulated paper trading positions."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not bool(getattr(setting, 'webull_test_mode_enabled', False)):
            return jsonify({'success': True, 'positions': []})
        from services.webull_paper_trading_service import get_webull_test_positions
        positions = get_webull_test_positions(current_user.id)
        return jsonify({'success': True, 'positions': positions})
    except Exception as exc:
        logger.error(f"[PAPER_TRADING] Failed to get positions: {exc}", exc_info=True)
        return jsonify({'success': False, 'positions': [], 'message': str(exc)}), 500


@system_bp.route('/api/webull/test/orders', methods=['GET'])
@login_required
def api_webull_test_orders():
    """Retrieve simulated paper trading orders history."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not bool(getattr(setting, 'webull_test_mode_enabled', False)):
            return jsonify({'success': True, 'orders': []})
        from services.webull_paper_trading_service import get_webull_test_orders
        orders = get_webull_test_orders(current_user.id)
        return jsonify({'success': True, 'orders': orders})
    except Exception as exc:
        logger.error(f"[PAPER_TRADING] Failed to get orders: {exc}", exc_info=True)
        return jsonify({'success': False, 'orders': [], 'message': str(exc)}), 500


@system_bp.route('/api/webull/test/toggle', methods=['POST', 'PUT'])
@login_required
def api_webull_test_toggle():
    """Toggle Webull test mode (paper trading) on or off."""
    try:
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get('enabled', False))
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        if not setting:
            setting = UserSetting(user_id=current_user.id)
            db.session.add(setting)
        setting.webull_test_mode_enabled = enabled
        db.session.commit()
        return jsonify({'success': True, 'enabled': enabled, 'message': f"Webull Test Mode {'enabled' if enabled else 'disabled'}."})
    except Exception as exc:
        logger.error(f"[PAPER_TRADING] Toggle failed: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 500


@system_bp.route('/api/webull/test/status', methods=['GET'])
@login_required
def api_webull_test_status():
    """Check if Webull test mode is active for current user."""
    setting = UserSetting.query.filter_by(user_id=current_user.id).first()
    enabled = bool(getattr(setting, 'webull_test_mode_enabled', False))
    return jsonify({'success': True, 'enabled': enabled})


@system_bp.route('/api/webull/orders/place', methods=['POST'])
@login_required
def api_webull_place_order():
    """Place an order through Webull OpenAPI or simulated paper engine."""
    try:
        data = request.get_json(silent=True) or {}
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        test_mode_param = data.get('test_mode')
        req_account_id = data.get('account_id')
        paper_mode_enabled = bool(getattr(setting, 'webull_test_mode_enabled', False))
        paper_requested = test_mode_param is True or req_account_id == 'TEST_PAPER_ACCOUNT'
        if paper_requested and not paper_mode_enabled:
            return jsonify({
                'success': False,
                'message': 'Enable Webull Test Mode before placing a simulated paper order.',
            }), 409
        # The persisted server setting is authoritative. A stale or modified
        # browser payload cannot opt out of Test Mode and reach live trading.
        is_test_order = paper_mode_enabled
        event_market = None
        if str(data.get('instrument_type') or '').strip().upper() == 'EVENT':
            try:
                event_market = _preflight_webull_event_order(data, setting)
                data['_event_market_rules'] = event_market.get('rules') or {}
            except WebullConnectionError as exc:
                return jsonify({'success': False, 'message': str(exc)}), 400
        if is_test_order:
            data['test_mode'] = True
            data['account_id'] = 'TEST_PAPER_ACCOUNT'
            from services.webull_paper_trading_service import execute_webull_test_order
            try:
                res = execute_webull_test_order(current_user.id, data)
                return jsonify(res)
            except Exception as test_err:
                db.session.rollback()
                logger.error(f"[PAPER_ORDER] Simulation failed: {test_err}")
                return jsonify({'success': False, 'message': str(test_err)}), 400

        credential = Credential.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Webull is not connected or token has expired.'}), 400

        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')
        symbol = data.get('symbol')
        instrument_type = data.get('instrument_type', 'EQUITY')
        option_type = data.get('option_type', 'CALL')
        option_strike = data.get('option_strike')
        option_expiration = data.get('option_expiration')
        option_underlying_symbol = data.get('option_underlying_symbol')
        option_strategy = str(data.get('option_strategy') or 'SINGLE').strip().upper()
        option_legs = data.get('option_legs')
        side = data.get('side')
        order_type = data.get('order_type')
        quantity = data.get('quantity')
        limit_price = data.get('limit_price')
        stop_price = data.get('stop_price')
        trailing_type = data.get('trailing_type')
        trailing_stop_step = data.get('trailing_stop_step')
        time_in_force = data.get('time_in_force', 'DAY')
        support_trading_session = data.get('support_trading_session', 'CORE')

        # Stock trading parameters from Webull Stock Orders API
        entrust_type = data.get('entrust_type', 'QTY')
        total_cash_amount = data.get('total_cash_amount')
        algo_type = data.get('algo_type')
        algo_start_time = data.get('algo_start_time')
        algo_end_time = data.get('algo_end_time')
        max_target_percent = data.get('max_target_percent')
        target_vol_percent = data.get('target_vol_percent')
        combo_type = data.get('combo_type', 'NORMAL')
        client_combo_order_id = data.get('client_combo_order_id')
        combo_orders = data.get('combo_orders')
        bracket_take_profit_price = data.get('bracket_take_profit_price')
        bracket_stop_loss_price = data.get('bracket_stop_loss_price')
        bracket_stop_loss_limit_price = data.get('bracket_stop_loss_limit_price')
        event_outcome = data.get('event_outcome')

        try:
            account_id = _require_webull_account_access(setting, account_id)
            instrument_type = _require_webull_instrument_account_match(setting, account_id, instrument_type)
        except WebullConnectionError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400

        is_combo = bool(combo_orders and isinstance(combo_orders, list))
        if not is_combo:
            if not symbol:
                return jsonify({'success': False, 'message': 'Choose an instrument symbol.'}), 400
            if not side:
                return jsonify({'success': False, 'message': 'Choose an order side (BUY, SELL, or SHORT).'}), 400
            if not order_type:
                return jsonify({'success': False, 'message': 'Choose a valid order type.'}), 400
            if str(instrument_type).upper() == 'EQUITY' and str(entrust_type).upper() == 'AMOUNT':
                try:
                    if float(total_cash_amount or 0) < 5.0:
                        return jsonify({'success': False, 'message': 'Total cash amount must be at least $5.00 for fractional orders.'}), 400
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': 'Enter a valid total cash amount ($ USD).'}), 400
            elif not quantity:
                return jsonify({'success': False, 'message': 'Enter an order quantity.'}), 400

        if str(instrument_type).upper() == 'EQUITY':
            try:
                is_fractional = (str(entrust_type).upper() == 'AMOUNT') or (quantity is not None and not float(quantity).is_integer())
            except (TypeError, ValueError):
                is_fractional = False
            if is_fractional:
                if str(support_trading_session or 'CORE').upper() != 'CORE':
                    return jsonify({'success': False, 'message': 'Fractional stock and ETF orders are supported only during Regular Hours (CORE).'}), 400
                if str(order_type or '').upper() != 'MARKET':
                    return jsonify({'success': False, 'message': 'Webull supports fractional stock and ETF orders as Market orders only.'}), 400

        # Crypto safety guard: isolate crypto from equity-only features
        if str(instrument_type).upper() == 'CRYPTO':
            if str(side).upper() not in {'BUY', 'SELL'}:
                return jsonify({'success': False, 'message': 'Crypto orders support BUY and SELL only.'}), 400
            if str(order_type).upper() not in {'MARKET', 'LIMIT', 'STOP_LOSS_LIMIT'}:
                return jsonify({'success': False, 'message': 'Crypto orders support Market, Limit, and Stop Loss Limit only.'}), 400

        # Options use their documented single-leg contract fields. Reject an
        # unsupported ticket before a 2FA token is consumed or an API request
        # is attempted. A fresh Webull preflight is the authority for cash and
        # contract ownership, so the browser cannot sell an unowned contract.
        if str(instrument_type).upper() in {'OPTION', 'OPTIONS'}:
            if option_strategy not in WEBULL_OPTION_STRATEGIES:
                return jsonify({
                    'success': False,
                    'message': 'Choose a Webull OpenAPI-supported option strategy. Ratio strategies are not documented by the API.',
                }), 400
            if option_strategy != 'SINGLE':
                if not isinstance(option_legs, list) or len(option_legs) < 2:
                    return jsonify({'success': False, 'message': 'The selected option strategy requires at least two fully defined legs.'}), 400
                for index, leg in enumerate(option_legs, start=1):
                    if not isinstance(leg, dict):
                        return jsonify({'success': False, 'message': f'Option strategy leg {index} is invalid.'}), 400
                    leg_instrument = str(leg.get('instrument_type') or 'OPTION').strip().upper()
                    if leg_instrument not in {'OPTION', 'EQUITY'}:
                        return jsonify({'success': False, 'message': f'Option strategy leg {index} must be an option or stock leg.'}), 400
                    if str(leg.get('side') or '').strip().upper() not in {'BUY', 'SELL'}:
                        return jsonify({'success': False, 'message': f'Option strategy leg {index} requires a Buy or Sell side.'}), 400
                    try:
                        if float(leg.get('quantity') or 0) <= 0:
                            raise ValueError()
                    except (TypeError, ValueError):
                        return jsonify({'success': False, 'message': f'Option strategy leg {index} requires a positive quantity.'}), 400
                    if leg_instrument == 'OPTION':
                        if str(leg.get('option_type') or '').strip().upper() not in {'CALL', 'PUT'}:
                            return jsonify({'success': False, 'message': f'Option strategy leg {index} requires CALL or PUT.'}), 400
                        try:
                            if float(leg.get('strike_price') or 0) <= 0:
                                raise ValueError()
                            datetime.strptime(str(leg.get('option_expire_date') or ''), '%Y-%m-%d')
                        except (TypeError, ValueError):
                            return jsonify({'success': False, 'message': f'Option strategy leg {index} requires a valid strike and expiration.'}), 400
            normalized_option_type = {'STOP': 'STOP_LOSS', 'STOP_LIMIT': 'STOP_LOSS_LIMIT'}.get(str(order_type or '').upper(), str(order_type or '').upper())
            if normalized_option_type not in {'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
                return jsonify({'success': False, 'message': 'Webull options support Limit, Stop Loss, and Stop Loss Limit orders only.'}), 400
            normalized_side = str(side or '').strip().upper()
            if normalized_side not in {'BUY', 'SELL'}:
                return jsonify({'success': False, 'message': 'Webull option orders support Buy and Sell only.'}), 400
            try:
                option_quantity = float(quantity)
                if option_quantity <= 0 or not option_quantity.is_integer():
                    raise ValueError()
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Webull option orders require a whole number of contracts.'}), 400
            normalized_call_put = str(option_type or '').strip().upper()
            if normalized_call_put not in {'CALL', 'PUT'}:
                return jsonify({'success': False, 'message': 'Choose CALL or PUT for the option contract.'}), 400
            try:
                normalized_strike = float(option_strike)
                if normalized_strike <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Webull option orders require a positive contract strike price.'}), 400
            normalized_expiration = _webull_option_expiry(option_expiration)
            try:
                datetime.strptime(normalized_expiration, '%Y-%m-%d')
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Webull option orders require an expiration date in YYYY-MM-DD format.'}), 400
            normalized_underlying = str(option_underlying_symbol or symbol or '').strip().upper()
            if not normalized_underlying:
                return jsonify({'success': False, 'message': 'Webull option orders require an underlying stock symbol.'}), 400
            try:
                has_valid_limit_price = float(limit_price) > 0
            except (TypeError, ValueError):
                has_valid_limit_price = False
            try:
                has_valid_stop_price = float(stop_price) > 0
            except (TypeError, ValueError):
                has_valid_stop_price = False
            if normalized_option_type in ('LIMIT', 'STOP_LOSS_LIMIT') and not has_valid_limit_price:
                return jsonify({'success': False, 'message': 'Options limit orders require a positive limit price.'}), 400
            if normalized_option_type in ('STOP_LOSS', 'STOP_LOSS_LIMIT') and not has_valid_stop_price:
                return jsonify({'success': False, 'message': 'Options stop orders require a positive stop price.'}), 400
            if normalized_side == 'BUY' and normalized_option_type == 'STOP_LOSS':
                return jsonify({'success': False, 'message': 'Use a Limit or Stop Loss Limit order to buy options so the maximum premium remains covered by available USD.'}), 400

            available_cash, owned_contracts = _live_webull_option_order_capability(
                credential,
                environment,
                account_id,
                underlying_symbol=normalized_underlying,
                option_type=normalized_call_put,
                option_strike=normalized_strike,
                option_expiration=normalized_expiration,
            )
            if option_strategy == 'SINGLE' and normalized_side == 'SELL':
                if owned_contracts + WEBULL_OPTION_STRIKE_EPSILON < option_quantity:
                    return jsonify({
                        'success': False,
                        'message': (
                            'Options Sell orders can close only an exact owned contract '
                            f'(same underlying, CALL/PUT, strike, and expiration). Available contracts: {owned_contracts:g}.'
                        ),
                    }), 400
            elif option_strategy == 'SINGLE':
                premium = float(limit_price)
                single_contract_cost = premium * WEBULL_OPTION_CONTRACT_MULTIPLIER
                total_cost = single_contract_cost * option_quantity
                if available_cash + WEBULL_OPTION_STRIKE_EPSILON < single_contract_cost:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient USD to purchase one contract. It requires ${single_contract_cost:,.2f}; current Webull cash is ${available_cash:,.2f}.',
                    }), 400
                if available_cash + WEBULL_OPTION_STRIKE_EPSILON < total_cost:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient USD for {int(option_quantity)} contract(s). Estimated premium is ${total_cost:,.2f}; current Webull cash is ${available_cash:,.2f}.',
                    }), 400

        if str(instrument_type).upper() == 'FUTURES':
            normalized_futures_type = {'STOP': 'STOP_LOSS', 'STOP_LIMIT': 'STOP_LOSS_LIMIT'}.get(str(order_type or '').upper(), str(order_type or '').upper())
            if normalized_futures_type not in {'MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TRAILING_STOP_LOSS'}:
                return jsonify({'success': False, 'message': 'Webull futures support Market, Limit, Stop Loss, Stop Loss Limit, and Trailing Stop Loss orders.'}), 400
            if str(side or '').strip().upper() not in {'BUY', 'SELL'}:
                return jsonify({'success': False, 'message': 'Webull futures orders support Buy and Sell only.'}), 400
            try:
                futures_quantity = float(quantity)
                if futures_quantity <= 0 or not futures_quantity.is_integer():
                    raise ValueError()
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Webull futures orders require a whole number of contracts.'}), 400
            if str(time_in_force or 'DAY').upper() not in {'DAY', 'GTC'}:
                return jsonify({'success': False, 'message': 'Webull futures orders support DAY or GTC time in force.'}), 400
            try:
                has_valid_limit_price = float(limit_price) > 0
            except (TypeError, ValueError):
                has_valid_limit_price = False
            try:
                has_valid_stop_price = float(stop_price) > 0
            except (TypeError, ValueError):
                has_valid_stop_price = False
            if normalized_futures_type in {'LIMIT', 'STOP_LOSS_LIMIT'} and not has_valid_limit_price:
                return jsonify({'success': False, 'message': 'Futures limit orders require a positive limit price.'}), 400
            if normalized_futures_type in {'STOP_LOSS', 'STOP_LOSS_LIMIT'} and not has_valid_stop_price:
                return jsonify({'success': False, 'message': 'Futures stop orders require a positive stop price.'}), 400
            if normalized_futures_type == 'TRAILING_STOP_LOSS':
                if str(trailing_type or '').strip().upper() not in {'AMOUNT', 'PERCENTAGE'}:
                    return jsonify({'success': False, 'message': 'Choose an amount or percentage for the futures trailing stop.'}), 400
                try:
                    if float(trailing_stop_step) <= 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': 'Futures trailing stops require a positive trail amount or percentage.'}), 400
            clean_futures_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
            tradable_contracts = get_webull_futures_contracts(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token, symbol=clean_futures_symbol,
            )
            if not any(str(contract.get('symbol') or '').upper() == clean_futures_symbol for contract in tradable_contracts):
                return jsonify({
                    'success': False,
                    'message': 'Choose an exact tradable Webull futures contract from the Futures Contract Setup before placing an order.',
                }), 400

        if str(instrument_type).upper() == 'EVENT' and str(side or '').strip().upper() == 'SELL':
            try:
                event_quantity = float(quantity)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Enter a valid Event Contract quantity.'}), 400
            owned_event_contracts = _live_webull_event_owned_contracts(
                credential,
                environment,
                account_id,
                symbol=symbol,
                event_outcome=event_outcome,
            )
            if owned_event_contracts + WEBULL_OPTION_STRIKE_EPSILON < event_quantity:
                return jsonify({
                    'success': False,
                    'message': (
                        'Event Contract Sell orders can only close an exact owned Yes/No position. '
                        f'Available contracts: {owned_event_contracts:g}.'
                    ),
                }), 400

        # Enforce 2FA verification if enabled for user
        from trading_models import TradingSettings
        trading_settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if trading_settings and getattr(trading_settings, 'require_2fa', False) and getattr(trading_settings, 'totp_secret', None):
            twofa_token = data.get('twofa_token')
            twofa_code = data.get('twofa_code') or data.get('two_factor_code')
            verified = False
            if twofa_token:
                token_data = session.get(f'2fa_verified_{twofa_token}')
                if token_data and token_data.get('user_id') == current_user.id:
                    if time.time() - token_data.get('timestamp', 0) <= 120:
                        verified = True
                        session.pop(f'2fa_verified_{twofa_token}', None)
            if not verified and twofa_code:
                import pyotp
                totp = pyotp.TOTP(trading_settings.totp_secret)
                if totp.verify(str(twofa_code).strip(), valid_window=1):
                    verified = True

            if not verified:
                return jsonify({
                    'success': False,
                    'message': 'Two-factor authentication (2FA) verification is required to place orders.',
                    'requires_2fa': True,
                }), 403

        result = place_webull_order(
            credential.webull_app_key, credential.webull_app_secret,
            environment, credential.webull_access_token,
            account_id=account_id,
            symbol=symbol,
            instrument_type=instrument_type,
            option_type=option_type,
            option_strike=option_strike,
            option_expiration=option_expiration,
            option_underlying_symbol=option_underlying_symbol,
            option_strategy=option_strategy,
            option_legs=option_legs,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            trailing_type=trailing_type,
            trailing_stop_step=trailing_stop_step,
            time_in_force=time_in_force,
            support_trading_session=support_trading_session,
            entrust_type=entrust_type,
            total_cash_amount=total_cash_amount,
            algo_type=algo_type,
            algo_start_time=algo_start_time,
            algo_end_time=algo_end_time,
            max_target_percent=max_target_percent,
            target_vol_percent=target_vol_percent,
            combo_type=combo_type,
            client_combo_order_id=client_combo_order_id,
            combo_orders=combo_orders,
            bracket_take_profit_price=bracket_take_profit_price,
            bracket_stop_loss_price=bracket_stop_loss_price,
            bracket_stop_loss_limit_price=bracket_stop_loss_limit_price,
            event_outcome=event_outcome,
            event_market=event_market,
        )
        logger.info(f"Webull order placed successfully: user={current_user.id} account={account_id} symbol={symbol} side={side} order_id={result.get('order_id')}")
        order_msg = (
            f"Webull combo order ({result.get('legs_count', 2)} legs) submitted successfully."
            if result.get('client_combo_order_id')
            else f"Webull {side} order for {quantity or total_cash_amount} {symbol} submitted successfully."
        )
        return jsonify({
            'success': True,
            'message': order_msg,
            'order': result,
        })
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull order placement failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to place this Webull order. Try again.'}), 500


@system_bp.route('/api/webull/events/categories', methods=['GET'])
@login_required
def api_webull_event_categories():
    """Return available Webull Event Contract categories."""
    try:
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        credential, environment = _webull_event_connection(setting)
        categories = get_webull_event_categories(
            credential.webull_app_key,
            credential.webull_app_secret,
            environment,
            credential.webull_access_token,
        )
        return jsonify({'success': True, 'categories': categories, 'source': 'webull'})
    except WebullConnectionError as exc:
        logger.error('Error fetching Webull event categories: %s', exc)
        return jsonify({'success': False, 'categories': [], 'message': str(exc)}), 502


@system_bp.route('/api/webull/events/durations', methods=['GET'])
@login_required
def api_webull_event_durations():
    """Return provider-backed Event durations without discovering markets."""
    try:
        category_id = request.args.get('category_id') or request.args.get('category')
        if not str(category_id or '').strip():
            return jsonify({'success': False, 'duration_options': [], 'message': 'Choose an Event Contract category first.'}), 400
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        credential, environment = _webull_event_connection(setting)
        duration_options = get_webull_event_duration_options(
            credential.webull_app_key,
            credential.webull_app_secret,
            environment,
            credential.webull_access_token,
            category_id=category_id,
        )
        return jsonify({'success': True, 'duration_options': duration_options, 'source': 'webull'})
    except WebullConnectionError as exc:
        logger.error('Error fetching Webull event durations: %s', exc)
        return jsonify({'success': False, 'duration_options': [], 'message': str(exc)}), 502


@system_bp.route('/api/webull/events/markets', methods=['GET'])
@login_required
def api_webull_event_markets():
    """Return available Webull Event Contract markets/instruments."""
    try:
        category_id = request.args.get('category_id') or request.args.get('category')
        symbol = str(request.args.get('symbol') or '').strip().upper()
        query = request.args.get('query') or request.args.get('q')
        duration = request.args.get('duration') or request.args.get('frequency')
        search_requested = request.args.get('search') == '1'
        try:
            limit = max(1, min(int(request.args.get('limit') or 10), 50))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'markets': [], 'message': 'Limit must be a whole number from 1 to 50.'}), 400
        if not symbol and (not search_requested or not str(query or '').strip()):
            return jsonify({
                'success': True,
                'markets': [],
                'total_matches': 0,
                'catalog_matches': 0,
                'verified_matches': 0,
                'has_more': False,
                'partial': False,
                'loading': False,
                'message': '',
                'status': 'idle',
                'source': 'webull',
            })
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        credential, environment = _webull_event_connection(setting)
        if symbol:
            market = get_webull_event_market(
                credential.webull_app_key, credential.webull_app_secret,
                environment, credential.webull_access_token,
                symbol=symbol, force=False,
            )
            result = {
                'markets': [market],
                'total_matches': 1,
                'catalog_matches': 1,
                'verified_matches': 1,
                'has_more': False,
                'partial': False,
                'loading': False,
                'status': 'exact_market',
                'catalog_as_of': market.get('quote_as_of'),
            }
        else:
            result = get_webull_event_markets(
                credential.webull_app_key, credential.webull_app_secret,
                environment, credential.webull_access_token,
                category_id=category_id, query=query, duration=duration, limit=limit,
                force=request.args.get('refresh') == '1',
                progressive=True,
            )
        return jsonify({'success': True, **result, 'source': 'webull'})
    except WebullConnectionError as exc:
        logger.error('Error fetching Webull event markets: %s', exc)
        return jsonify({'success': False, 'markets': [], 'message': str(exc)}), 502


@system_bp.route('/api/webull/events/position', methods=['GET'])
@login_required
def api_webull_event_position():
    """Return exact contract facts and chart data for an owned Event position."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        outcome = str(request.args.get('event_outcome') or '').strip().lower()
        account_id = str(request.args.get('account_id') or '').strip()
        timespan = str(request.args.get('timespan') or 'M1').strip().upper()
        try:
            count = max(1, min(int(request.args.get('count') or 200), 1200))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Chart count must be a whole number from 1 to 1200.'}), 400
        if not symbol:
            return jsonify({'success': False, 'message': 'Choose an Event Contract position first.'}), 400
        if outcome not in {'yes', 'no'}:
            return jsonify({'success': False, 'message': 'The Event Contract position must identify a Yes or No outcome.'}), 400

        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        credential, environment = _webull_event_connection(setting)
        market = get_webull_event_market(
            credential.webull_app_key,
            credential.webull_app_secret,
            environment,
            credential.webull_access_token,
            symbol=symbol,
            force=False,
        )
        chart_message = ''
        try:
            bars = get_webull_event_bars(
                credential.webull_app_key,
                credential.webull_app_secret,
                environment,
                credential.webull_access_token,
                symbol=symbol,
                timespan=timespan,
                count=count,
            )
        except WebullConnectionError as exc:
            logger.warning('Webull Event position chart unavailable for %s: %s', symbol, exc)
            bars = []
            chart_message = 'Webull did not return chart history for this contract.'

        available_quantity = None
        if account_id and request.args.get('test_mode') != '1':
            available_quantity = _live_webull_event_owned_contracts(
                credential,
                environment,
                account_id,
                symbol=symbol,
                event_outcome=outcome,
            )
        return jsonify({
            'success': True,
            'market': market,
            'bars': bars,
            'available_quantity': available_quantity,
            'server_time': datetime.now(timezone.utc).isoformat(),
            'chart_message': chart_message,
            'source': 'webull',
        })
    except WebullConnectionError as exc:
        logger.error('Error fetching Webull Event position details: %s', exc)
        return jsonify({'success': False, 'message': str(exc)}), 502


@system_bp.route('/api/webull/orders/cancel', methods=['POST'])
@login_required
def api_webull_cancel_order():
    """Cancel an open Webull order or simulated paper order."""
    try:
        data = request.get_json(silent=True) or {}
        order_id = str(data.get('order_id') or data.get('client_order_id') or data.get('id') or '')
        account_id = data.get('account_id') or data.get('_webull_account_id')
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        paper_mode_enabled = bool(getattr(setting, 'webull_test_mode_enabled', False))
        paper_requested = order_id.startswith('SIM_') or account_id == 'TEST_PAPER_ACCOUNT' or data.get('test_mode')
        if paper_requested and not paper_mode_enabled:
            return jsonify({
                'success': False,
                'message': 'Paper orders cannot be changed while Webull Test Mode is disabled.',
            }), 409
        if paper_mode_enabled:
            if not order_id.startswith('SIM_'):
                return jsonify({
                    'success': False,
                    'message': 'Live Webull orders are hidden and cannot be changed while Test Mode is active.',
                }), 409
            from services.webull_paper_trading_service import cancel_webull_test_order
            return jsonify(cancel_webull_test_order(current_user.id, order_id))

        two_factor_error = _cancellation_2fa_error(data)
        if two_factor_error:
            return jsonify({'success': False, 'message': two_factor_error, 'requires_2fa': True}), 403

        credential = Credential.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Webull is not connected or token has expired.'}), 400

        account_id = data.get('account_id') or data.get('_webull_account_id')
        client_order_id = data.get('client_order_id')
        order_id = data.get('order_id') or data.get('orderId') or data.get('id')

        try:
            account_id = _require_webull_account_access(setting, account_id)
        except WebullConnectionError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400
        if not client_order_id and not order_id:
            return jsonify({'success': False, 'message': 'Order identifier is required to cancel.'}), 400

        result = cancel_webull_order(
            credential.webull_app_key, credential.webull_app_secret,
            environment, credential.webull_access_token,
            account_id=account_id,
            client_order_id=client_order_id,
            order_id=order_id,
        )
        logger.info(f"Webull order cancelled: user={current_user.id} account={account_id} order={order_id or client_order_id}")
        return jsonify({
            'success': True,
            'result': result,
            'message': 'Webull order cancelled successfully.',
        })
    except WebullConnectionError as exc:
        logger.warning('Webull order cancellation failed: %s', exc)
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull order cancellation error: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'Order cancellation failed: {exc}'}), 500


def _fetch_fallback_stock_movers():
    """Fallback stock movers using popular large/mid-cap equities via yfinance."""
    import yfinance as yf
    symbols = ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", "PLTR", "COIN", "MARA", "RIOT", "NFLX", "INTC", "BABA", "UBER", "DIS", "BA", "PYPL", "SOFI"]
    try:
        tickers = yf.Tickers(' '.join(symbols))
        items = []
        for sym in symbols:
            try:
                t = tickers.tickers.get(sym)
                if not t:
                    continue
                fi = t.fast_info
                p = float(getattr(fi, 'last_price', 0) or getattr(fi, 'regularMarketPrice', 0) or 0)
                pc = float(getattr(fi, 'previous_close', 0) or getattr(fi, 'regularMarketPreviousClose', 0) or 0)
                if p > 0 and pc > 0:
                    change = ((p - pc) / pc) * 100
                    items.append({
                        'symbol': sym,
                        'name': sym,
                        'price': round(p, 2),
                        'change': round(change, 2),
                        'currency': 'USD'
                    })
            except Exception:
                continue
        gainers = sorted([i for i in items if i['change'] >= 0], key=lambda x: x['change'], reverse=True)
        losers = sorted([i for i in items if i['change'] < 0], key=lambda x: x['change'])
        return gainers, losers
    except Exception as exc:
        logger.warning("yfinance stock movers fallback failed: %s", exc)
        return [], []


@system_bp.route('/api/webull/stock-movers', methods=['GET'])
@login_required
def api_webull_stock_movers():
    """Return top U.S. stock movers, prioritizing Webull OpenAPI with resilient yfinance fallback."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            credential and credential.webull_token_status == 'NORMAL'
            and credential.webull_token_environment == environment and credential.webull_access_token
        ):
            try:
                gainers = get_webull_stock_movers(
                    credential.webull_app_key, credential.webull_app_secret, environment,
                    credential.webull_access_token, direction='DESC',
                )
                losers = get_webull_stock_movers(
                    credential.webull_app_key, credential.webull_app_secret, environment,
                    credential.webull_access_token, direction='ASC',
                )
                if gainers or losers:
                    return jsonify({'success': True, 'gainers': gainers, 'losers': losers, 'source': 'webull'})
            except Exception as wb_exc:
                logger.info('Webull stock movers request failed (%s); attempting yfinance fallback.', wb_exc)

        # Resilient fallback to yfinance
        yf_gainers, yf_losers = _fetch_fallback_stock_movers()
        if yf_gainers or yf_losers:
            return jsonify({'success': True, 'gainers': yf_gainers, 'losers': yf_losers, 'source': 'yfinance'})

        return jsonify({'success': False, 'gainers': [], 'losers': [], 'message': 'Unable to load U.S. stock movers.'}), 200
    except Exception as exc:
        logger.error('Webull stock-movers lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'gainers': [], 'losers': [], 'message': 'Unable to load U.S. stock movers.'}), 200


@system_bp.route('/api/webull/market-bars', methods=['GET'])
@login_required
def api_webull_market_bars():
    """Return read-only Webull historical bars for a selected imported holding."""
    try:
        holding_ref = str(request.args.get('holding_id') or '').strip()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        paper_mode_enabled = bool(getattr(setting, 'webull_test_mode_enabled', False))
        paper_position = None
        if holding_ref.startswith('paper_pos_'):
            try:
                paper_position = WebullTestPosition.query.filter_by(
                    id=int(holding_ref.removeprefix('paper_pos_')),
                    user_id=current_user.id,
                ).first()
            except (TypeError, ValueError):
                paper_position = None
            if not paper_mode_enabled or not paper_position:
                return jsonify({'success': False, 'bars': [], 'message': 'That paper holding is unavailable in the current mode.'}), 404
        elif paper_mode_enabled:
            return jsonify({'success': False, 'bars': [], 'message': 'Live holdings are hidden while Webull Test Mode is active.'}), 409
        if holding_ref.startswith('webull-'):
            holding_ref = holding_ref.split('webull-', 1)[1]
        holding = None
        if not paper_position:
            try:
                holding_id = int(holding_ref)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'bars': [], 'message': 'Choose an imported Webull holding before loading market data.'}), 400
            holding = WebullHolding.query.filter_by(id=holding_id, user_id=current_user.id).first()
            if not holding:
                return jsonify({'success': False, 'bars': [], 'message': 'That Webull holding is unavailable.'}), 404
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'bars': [], 'message': 'Verify your Webull connection before loading market data.'}), 400

        if holding and str(holding.instrument_type or '').upper() == 'OPTION' and not holding.instrument_id:
            holding = resolve_option_contract(
                holding, credential.webull_app_key, credential.webull_app_secret,
                environment, credential.webull_access_token,
            )

        bars = get_webull_market_bars(
            credential.webull_app_key, credential.webull_app_secret, environment,
            credential.webull_access_token,
            symbol=paper_position.symbol if paper_position else holding.symbol,
            instrument_type=paper_position.instrument_type if paper_position else holding.instrument_type,
            interval=request.args.get('interval', 'D'),
            limit=request.args.get('limit', 120),
            instrument_id=None if paper_position else holding.instrument_id,
        )
        return jsonify({'success': True, 'bars': bars})
    except WebullConnectionError as exc:
        logger.warning('Webull market-data lookup failed: %s', exc)
        return jsonify({'success': False, 'bars': [], 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull market-data lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'bars': [], 'message': 'Unable to load Webull market data.'}), 500


@system_bp.route('/api/webull/market-snapshot', methods=['GET'])
@login_required
def api_webull_market_snapshot():
    """Return a current, read-only quote for the Webull trade ticket."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        instrument_type = str(request.args.get('instrument_type') or 'EQUITY').strip().upper()
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Verify your Webull connection before loading a market quote.'}), 400
        snapshot = get_webull_market_snapshot(
            credential.webull_app_key, credential.webull_app_secret, environment,
            credential.webull_access_token, symbol=symbol, instrument_type=instrument_type,
        )
        return jsonify({'success': True, 'snapshot': snapshot})
    except WebullConnectionError as exc:
        logger.warning('Webull market snapshot lookup failed: %s', exc)
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull market snapshot lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load the Webull market quote.'}), 500


@system_bp.route('/api/webull/events/underlying-history', methods=['GET'])
@login_required
def api_webull_event_underlying_history():
    """Return a compact, cached one-minute price window for an Event underlying."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        instrument_type = str(request.args.get('instrument_type') or '').strip().upper()
        if not symbol or instrument_type not in {'CRYPTO', 'EQUITY', 'STOCK', 'ETF'}:
            return jsonify({'success': False, 'message': 'Choose a supported Event Contract underlying.'}), 400

        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if instrument_type != 'CRYPTO' and (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Verify your Webull connection before loading Event price history.'}), 400

        cache_key = (current_user.id, instrument_type, symbol, environment)
        now = time.time()
        cached = _EVENT_UNDERLYING_HISTORY_CACHE.get(cache_key)
        if cached and now - cached['updated_at'] < _EVENT_UNDERLYING_HISTORY_CACHE_TTL_SECONDS:
            return jsonify({'success': True, 'symbol': symbol, 'source': cached['source'], 'points': cached['points'], 'cached': True})

        points, source = _get_event_underlying_history(credential, environment, symbol, instrument_type)
        _EVENT_UNDERLYING_HISTORY_CACHE[cache_key] = {'updated_at': now, 'source': source, 'points': points}
        return jsonify({'success': True, 'symbol': symbol, 'source': source, 'points': points, 'cached': False})
    except WebullConnectionError as exc:
        logger.warning('Event underlying history lookup failed: %s', exc)
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Event underlying history lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load Event Contract price history.'}), 500


@system_bp.route('/api/webull/futures/catalog', methods=['GET'])
@login_required
def api_webull_futures_catalog():
    """Return the authenticated Webull futures product catalogue for the ticket."""
    try:
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': True, 'classes': [], 'products': FALLBACK_US_FUTURES_PRODUCTS})
        catalog = get_webull_futures_catalog(
            credential.webull_app_key, credential.webull_app_secret, environment,
            credential.webull_access_token,
        )
        return jsonify({'success': True, **catalog})
    except Exception as exc:
        logger.warning('Webull futures catalog lookup notice: %s. Serving standard catalog.', exc)
        return jsonify({'success': True, 'classes': [], 'products': FALLBACK_US_FUTURES_PRODUCTS})


@system_bp.route('/api/webull/futures/contracts', methods=['GET'])
@login_required
def api_webull_futures_contracts():
    """Look up exact tradable Webull futures contract codes."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        if not symbol:
            return jsonify({'success': False, 'contracts': [], 'message': 'Enter a futures contract code, for example ESZ5.'}), 400
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'contracts': [], 'message': 'Verify your Webull connection before loading futures contracts.'}), 400
        contracts = get_webull_futures_contracts(
            credential.webull_app_key, credential.webull_app_secret, environment,
            credential.webull_access_token, symbol=symbol,
        )
        return jsonify({'success': True, 'contracts': contracts})
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'contracts': [], 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull futures contract lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'contracts': [], 'message': 'Unable to load Webull futures contracts.'}), 500


@system_bp.route('/api/webull/futures/market-data', methods=['GET'])
@login_required
def api_webull_futures_market_data():
    """Return an entitled, read-only futures quote for the selected contract."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        if not symbol:
            return jsonify({'success': False, 'message': 'Choose a futures contract before loading its quote.'}), 400
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if (
            not credential or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment or not credential.webull_access_token
        ):
            return jsonify({'success': False, 'message': 'Verify your Webull connection before loading a futures quote.'}), 400
        quote = get_webull_futures_snapshot(
            credential.webull_app_key, credential.webull_app_secret, environment,
            credential.webull_access_token, symbol=symbol,
        )
        return jsonify({'success': True, 'quote': quote})
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull futures quote lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load the Webull futures quote.'}), 500


@system_bp.route('/api/webull/option-market-data', methods=['GET'])
@login_required
def api_webull_option_market_data():
    """Return one option's immutable contract identity and read-only quote/Greeks."""
    try:
        holding_ref = str(request.args.get('holding_id') or '').strip()
        if holding_ref.startswith('webull-'):
            holding_ref = holding_ref.split('webull-', 1)[1]
        holding = WebullHolding.query.filter_by(id=int(holding_ref), user_id=current_user.id).first()
        if not holding or str(holding.instrument_type or '').upper() != 'OPTION':
            return jsonify({'success': False, 'message': 'Choose an imported Webull option holding.'}), 404
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if not credential or credential.webull_token_status != 'NORMAL' or credential.webull_token_environment != environment or not credential.webull_access_token:
            return jsonify({'success': False, 'message': 'Verify your Webull connection before loading option market data.'}), 400
        if not holding.instrument_id:
            holding = resolve_option_contract(holding, credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token)
        contract = {
            'label': option_contract_label(holding), 'symbol': holding.symbol,
            'instrument_id': holding.instrument_id, 'underlying_symbol': holding.underlying_symbol,
            'expiration': holding.option_expiration, 'strike': holding.option_strike,
            'type': holding.option_type, 'multiplier': holding.option_multiplier,
        }
        try:
            quote = get_webull_option_snapshot(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token, symbol=holding.symbol, instrument_id=holding.instrument_id,
            )
            return jsonify({'success': True, 'contract': contract, 'quote': quote, 'quote_available': True})
        except WebullConnectionError as quote_exc:
            # The static contract remains useful even if OPRA is not entitled,
            # delayed, closed, or temporarily unavailable.
            return jsonify({'success': True, 'contract': contract, 'quote': None, 'quote_available': False, 'message': str(quote_exc)})
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Choose an imported Webull option holding.'}), 400
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull option market-data lookup failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load Webull option market data.'}), 500


@system_bp.route('/api/webull/options/expirations', methods=['GET'])
@login_required
def api_webull_options_expirations():
    """Return all valid option expiration dates and DTE counts for an underlying symbol."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        if not symbol:
            return jsonify({'success': False, 'message': 'An underlying symbol is required.'}), 400
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        app_key = credential.webull_app_key if credential else None
        app_secret = credential.webull_app_secret if credential else None
        access_token = credential.webull_access_token if credential else None
        data = get_webull_option_chain_data(
            app_key, app_secret, environment, access_token, underlying_symbol=symbol
        )
        return jsonify({
            'success': True,
            'underlying_symbol': data['underlying_symbol'],
            'underlying_price': data['underlying_price'],
            'underlying_prev_close': data['underlying_prev_close'],
            'underlying_change_pct': data['underlying_change_pct'],
            'market_status': data['market_status'],
            'expirations': data['expirations'],
            'selected_expiration': data['selected_expiration'],
        })
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull options expirations lookup failed for %s: %s', request.args.get('symbol'), exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load options expirations.'}), 500


@system_bp.route('/api/webull/options/chain', methods=['GET'])
@login_required
def api_webull_options_chain():
    """Return full strike-aligned option chain (Calls and Puts) for an underlying and expiration."""
    try:
        symbol = str(request.args.get('symbol') or '').strip().upper()
        expiration = str(request.args.get('expiration') or '').strip()
        if not symbol:
            return jsonify({'success': False, 'message': 'An underlying symbol is required.'}), 400
        credential = Credential.query.filter_by(user_id=current_user.id).first()
        setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        app_key = credential.webull_app_key if credential else None
        app_secret = credential.webull_app_secret if credential else None
        access_token = credential.webull_access_token if credential else None
        data = get_webull_option_chain_data(
            app_key, app_secret, environment, access_token,
            underlying_symbol=symbol, expiration_date=expiration or None
        )
        response = jsonify(data)
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response
    except WebullConnectionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        logger.error('Webull option chain lookup failed for %s: %s', request.args.get('symbol'), exc, exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load option chain.'}), 500


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
            payload = {"chat_id": value, "text": "Test message from Crypto & Securities Dashboard onboarding."}
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
    data = request.get_json() or {}
    coin_id = data.get("id")
    coin = None
    if coin_id is not None:
        try:
            coin = Coin.query.filter_by(id=int(coin_id), user_id=current_user.id).first()
        except (ValueError, TypeError):
            pass
    if not coin:
        sym = data.get('symbol') or (str(coin_id) if isinstance(coin_id, str) and not coin_id.isdigit() else None)
        if sym:
            sym_clean = str(sym).upper()
            from models import WebullHolding
            wb_holding = WebullHolding.query.filter_by(symbol=sym_clean, user_id=current_user.id).first()
            if wb_holding:
                wb_holding.alert_enabled = not wb_holding.alert_enabled
                db.session.commit()
                return jsonify({"success": True, "alert_enabled": wb_holding.alert_enabled})
            coin = Coin.query.filter_by(symbol=sym_clean, user_id=current_user.id).first()
            if not coin:
                coin = Coin(symbol=sym_clean, user_id=current_user.id, alert_enabled=True, amount=0.0)
                db.session.add(coin)
                db.session.commit()
                return jsonify({"success": True, "alert_enabled": True})
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
    if d.get('table_type') == 'webull':
        holding = _webull_holding_for_current_user(d.get('id'))
        if not holding:
            return jsonify({"error": "Webull holding not found"}), 404
        direction = d.get('type', '')
        pct_type = d.get('pct_type', '#')
        if direction not in {'down', 'up'} or pct_type not in {'#', '%'}:
            return jsonify({"error": "Webull alerts use a price or percentage threshold."}), 400
        try:
            value = round(float(d.get('value')), 2) if d.get('value') not in ('', None) else None
        except (TypeError, ValueError):
            return jsonify({"error": "Alert value must be a number."}), 400
        prefix = 'custom_lower' if direction == 'down' else 'custom_upper'
        setattr(holding, f'{prefix}_type', pct_type)
        setattr(holding, f'{prefix}_val', value if pct_type == '#' else None)
        setattr(holding, f'{prefix}_pct', value if pct_type == '%' else None)
        holding.alert_enabled = bool(
            holding.custom_lower_val is not None or holding.custom_lower_pct is not None
            or holding.custom_upper_val is not None or holding.custom_upper_pct is not None
        )
        db.session.commit()
        return jsonify({
            'success': True, 'alert_enabled': holding.alert_enabled,
            'custom_lower_type': holding.custom_lower_type, 'custom_lower_val': holding.custom_lower_val,
            'custom_lower_pct': holding.custom_lower_pct, 'custom_upper_type': holding.custom_upper_type,
            'custom_upper_val': holding.custom_upper_val, 'custom_upper_pct': holding.custom_upper_pct,
        })
    
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

    if table_type == 'webull':
        coin = _webull_holding_for_current_user(data.get('id'))
    elif table_type == 'portfolio':
        coin_id = data.get('id')
        coin = Coin.query.filter_by(user_id=current_user.id, id=coin_id).first()
    elif table_type == 'watchlist':
        symbol = data.get('symbol')
        coin = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    else:
        return jsonify({"success": False, "error": "Invalid table type"})

    if coin:
        coin.volatility_pct = volatility_pct
        try:
            new_pct = float(volatility_pct) if volatility_pct is not None else None
        except (ValueError, TypeError):
            new_pct = None
        # Keep active auto-buy/auto-sell trigger snapshots in sync so the live
        # trigger price/threshold reflects the newly edited volatility % immediately.
        if new_pct is not None:
            if getattr(coin, 'auto_buy_enabled', False):
                coin.auto_buy_volatility_pct = new_pct
            if getattr(coin, 'auto_sell_enabled', False):
                coin.auto_sell_volatility_pct = new_pct
        db.session.commit()
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Coin not found"})

@system_bp.route('/api/toggle-sentiment-tracking', methods=['POST'])
@login_required
def toggle_sentiment_tracking():
    """Enable or disable AI sentiment tracking for a single portfolio or watchlist coin."""
    data = request.get_json() or {}
    table_type = data.get('table_type')
    enabled = bool(data.get('enabled', True))

    if table_type == 'webull':
        coin = _webull_holding_for_current_user(data.get('id'))
    elif table_type == 'portfolio':
        coin_id = data.get('id')
        coin = Coin.query.filter_by(user_id=current_user.id, id=coin_id).first()
    elif table_type == 'watchlist':
        symbol = data.get('symbol')
        coin = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    else:
        return jsonify({"success": False, "error": "Invalid table type"})

    if not coin:
        return jsonify({"success": False, "error": "Coin not found"})

    coin.sentiment_tracking_enabled = enabled
    if not enabled:
        if table_type != 'webull':
            coin.sentiment = 'Not Tracked'
            coin.sentiment_reason = ''
    db.session.commit()
    return jsonify({
        "success": True,
        "sentiment_tracking_enabled": enabled,
        "sentiment": getattr(coin, 'sentiment', None) or ('Hold' if enabled else 'Not Tracked')
    })

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
        if not enabled:
            two_factor_error = _cancellation_2fa_error(data)
            if two_factor_error:
                return jsonify({'success': False, 'error': two_factor_error, 'requires_2fa': True}), 403
        
        user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        vol_hours = int(getattr(user_setting, 'volatility_hours', 24) or 24)
        confirmation_minutes = int(getattr(user_setting, 'automated_trigger_confirmation_minutes', 15) or 15)
        
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
            coin.auto_sell_confirmation_started_at = None
            db.session.commit()
            logger.info(f"Auto-sell ({quote_currency}) enabled for user {current_user.username}: {coin.symbol} at {pct_val}% drop in {vol_hours}h with {confirmation_minutes}m confirmation.")
            return jsonify({
                "success": True,
                "message": f"Auto-sell enabled for {coin.symbol}. It will automatically sell for {quote_currency} only if the price remains down more than {pct_val:.1f}% across the {vol_hours}-hour lookback for {confirmation_minutes} consecutive minute(s).",
                "auto_sell_enabled": True,
                "auto_sell_quote_currency": quote_currency,
                "volatility_pct": pct_val,
                "volatility_hours": vol_hours,
                "automated_trigger_confirmation_minutes": confirmation_minutes
            })
        else:
            coin.auto_sell_enabled = False
            coin.auto_sell_confirmation_started_at = None
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
        if not enabled:
            two_factor_error = _cancellation_2fa_error(data)
            if two_factor_error:
                return jsonify({'success': False, 'error': two_factor_error, 'requires_2fa': True}), 403

        user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
        vol_hours = int(getattr(user_setting, 'volatility_hours', 24) or 24)
        confirmation_minutes = int(getattr(user_setting, 'automated_trigger_confirmation_minutes', 15) or 15)

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
            coin.auto_buy_confirmation_started_at = None
            db.session.commit()

            logger.info(f"Auto-buy ({quote_currency}) enabled for user {current_user.username}: {coin.symbol} (${alloc_amount:.2f}) at +{pct_val}% surge in {vol_hours}h with {confirmation_minutes}m confirmation.")
            return jsonify({
                "success": True,
                "message": f"Auto-buy enabled for {coin.symbol}. It will automatically purchase with ${alloc_amount:.2f} {quote_currency} only if the price remains up more than {pct_val:.1f}% across the {vol_hours}-hour lookback for {confirmation_minutes} consecutive minute(s).",
                "auto_buy_enabled": True,
                "auto_buy_amount": alloc_amount,
                "auto_buy_quote_currency": quote_currency,
                "volatility_pct": pct_val,
                "volatility_hours": vol_hours,
                "automated_trigger_confirmation_minutes": confirmation_minutes
            })
        else:
            coin.auto_buy_enabled = False
            coin.auto_buy_confirmation_started_at = None
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
        msg['Subject'] = f"[Crypto & Securities Dashboard] {topic}"
        
        # Email body
        body = f"""New support message from Crypto & Securities Dashboard:

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
