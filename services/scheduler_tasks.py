import time
from datetime import datetime
from flask import current_app
from core.extensions import db
from log import logger
from models import Coin, WatchlistCoin, Notification
from credentials import User, Credential
from services.binance_service import (
    sync_binance_account, binance_rate_limiter, fetch_binance_price
)
from services.notification_service import (
    send_telegram_alert, save_notification_record, send_telegram_message
)
from services.portfolio_service import (
    record_true_portfolio_value, get_comprehensive_crypto_data_for_user
)
from services.credential_service import get_user_credentials

# Cache for alert states
alert_states = {} # {(user_id, symbol, direction, source, threshold): state}

def _normalize_threshold(threshold):
    if threshold is None:
        return None
    try:
        return float(f"{float(threshold):.6f}")
    except:
        return None

def get_last_alert_state(user_id, symbol, direction, source=None, threshold=None):
    key = (user_id, symbol.upper(), direction.lower(), source, threshold)
    return alert_states.get(key)

def set_last_alert_state(user_id, symbol, direction, value, source=None, threshold=None):
    key = (user_id, symbol.upper(), direction.lower(), source, threshold)
    if value is None:
        alert_states.pop(key, None)
    else:
        alert_states[key] = value

def safe_background_iteration(f):
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Background iteration error: {e}")
    return wrapper

class ObjectView(object):
    def __init__(self, d):
        self.__dict__ = d

def update_auto_alert_cache():
    """Helper to update any caches if needed"""
    pass

def background_binance_sync_loop(app):
    """Background job to sync Binance transactions and balances every 5 minutes for all users"""
    logger.info("Starting Binance sync background job")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
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
                        from binance.client import Client
                        client = Client(
                            api_key=user.api_key,
                            api_secret=user.api_secret,
                            testnet=False,
                            tld='us',
                            requests_params={'timeout': 30}
                        )
                        from types import SimpleNamespace
                        cred_obj = SimpleNamespace(api_key=user.api_key, api_secret=user.api_secret)
                        sync_binance_account(user.id, user.username, client, cred_obj)
                    except Exception as e:
                        logger.error(f"Error syncing Binance for user {user.username}: {e}")
                
                update_auto_alert_cache()
            
            iteration()
            time.sleep(300)

def portfolio_alert_loop(app):
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
                            price = coin.current if coin.current and coin.current > 0 else None
                        
                        if price is None or coin.avg_entry is None:
                            continue

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

                        norm_down = _normalize_threshold(down_threshold)
                        last_alert_down = get_last_alert_state(user.id, symbol, "down", "portfolio", norm_down)
                        if down_threshold is not None:
                            if price <= down_threshold:
                                if last_alert_down not in ("saved", "sent"):
                                    save_notification_record(user.id, coin.id, 'coin', symbol, 'down', 'price', down_threshold, price, price)
                                    set_last_alert_state(user.id, symbol, "down", "saved", "portfolio", norm_down)
                                if last_alert_down != "sent":
                                    sent = send_telegram_alert(user.username, symbol, price, "down", down_threshold)
                                    if sent:
                                        set_last_alert_state(user.id, symbol, "down", "sent", "portfolio", norm_down)
                            elif last_alert_down in ("saved", "sent") and price > down_threshold * 1.01:
                                set_last_alert_state(user.id, symbol, "down", None, "portfolio", norm_down)

                        norm_up = _normalize_threshold(up_threshold)
                        last_alert_up = get_last_alert_state(user.id, symbol, "up", "portfolio", norm_up)
                        if up_threshold is not None:
                            if price >= up_threshold:
                                if last_alert_up not in ("saved", "sent"):
                                    save_notification_record(user.id, coin.id, 'coin', symbol, 'up', 'price', up_threshold, price, price)
                                    set_last_alert_state(user.id, symbol, "up", "saved", "portfolio", norm_up)
                                if last_alert_up != "sent":
                                    sent = send_telegram_alert(user.username, symbol, price, "up", up_threshold)
                                    if sent:
                                        set_last_alert_state(user.id, symbol, "up", "sent", "portfolio", norm_up)
                            elif last_alert_up in ("saved", "sent") and price < up_threshold * 0.99:
                                set_last_alert_state(user.id, symbol, "up", None, "portfolio", norm_up)

            iteration()
            time.sleep(120)

def watchlist_alert_loop(app):
    logger.info("=== watchlist_alert_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    watchlist_coins = WatchlistCoin.query.filter_by(user_id=user.id, alert_enabled=True, hidden=False).all()
                    for coin in watchlist_coins:
                        symbol = (coin.symbol or '').upper()
                        price = None
                        
                        if binance_rate_limiter.can_call(symbol):
                            try:
                                price = fetch_binance_price(symbol)
                                if price and price > 0:
                                    binance_rate_limiter.record_call(symbol)
                                    try:
                                        coin.current_price = price
                                        db.session.commit()
                                    except: pass
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
            iteration()
            time.sleep(120)

def check_coin_volatility(user, coin, client, table_type):
    """Check for high volatility in a coin and send Telegram alert"""
    try:
        symbol = coin.symbol.upper()
        volatility_threshold = float(coin.volatility_pct or 0)
        if volatility_threshold <= 0: return

        from binance.client import Client
        ticker = client.get_ticker(symbol=f"{symbol}USDT")
        price_change_pct = float(ticker['priceChangePercent'])

        if abs(price_change_pct) >= volatility_threshold:
            direction = "UP" if price_change_pct > 0 else "DOWN"
            last_alert = get_last_alert_state(user.id, symbol, "volatility", source=table_type, threshold=volatility_threshold)
            if last_alert != "sent":
                msg = f"⚠️ VOLATILITY ALERT: {symbol} is {direction} {abs(price_change_pct):.2f}% in 24h!"
                send_telegram_message(user.username, msg)
                set_last_alert_state(user.id, symbol, "volatility", "sent", source=table_type, threshold=volatility_threshold)
        else:
            set_last_alert_state(user.id, symbol, "volatility", None, source=table_type, threshold=volatility_threshold)
    except Exception as e:
        logger.error(f"Error checking volatility for {coin.symbol}: {e}")

def volatility_alert_loop(app):
    logger.info("=== volatility_alert_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    credentials = get_user_credentials(user.username)
                    if not credentials or not (credentials.api_key or credentials.trading_api_key):
                        continue
                    from binance.client import Client
                    client = Client(credentials.api_key, credentials.api_secret, tld='us')
                    coins = Coin.query.filter(Coin.user_id == user.id, Coin.alert_enabled == True, Coin.volatility_pct > 0).all()
                    for coin in coins: check_coin_volatility(user, coin, client, 'portfolio')
                    watchlist_coins = WatchlistCoin.query.filter(WatchlistCoin.user_id == user.id, WatchlistCoin.alert_enabled == True, WatchlistCoin.volatility_pct > 0).all()
                    for coin in watchlist_coins: check_coin_volatility(user, coin, client, 'watchlist')
            iteration()
            time.sleep(300)

def start_background_jobs(app=None):
    """Initialize and start all background alert and sync loops."""
    import threading
    from log import logger
    
    logger.info("Starting background jobs...")
    
    # 1. Binance Portfolio Sync Loop
    sync_thread = threading.Thread(target=background_binance_sync_loop, args=(app,), daemon=True)
    sync_thread.start()
    
    # 2. Portfolio Price Alert Loop
    portfolio_thread = threading.Thread(target=portfolio_alert_loop, args=(app,), daemon=True)
    portfolio_thread.start()
    
    # 3. Watchlist Price Alert Loop
    watchlist_thread = threading.Thread(target=watchlist_alert_loop, args=(app,), daemon=True)
    watchlist_thread.start()
    
    # 4. Volatility Alert Loop
    volatility_thread = threading.Thread(target=volatility_alert_loop, args=(app,), daemon=True)
    volatility_thread.start()
    
    logger.info("All background threads initiated.")
