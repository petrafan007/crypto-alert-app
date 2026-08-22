import time
import os
import json
import threading
from datetime import datetime
from flask import current_app
from core.extensions import db
from log import logger
from models import Coin, WatchlistCoin, Notification
from credentials import User, Credential, UserSetting
from services.binance_service import (
    sync_binance_account, binance_rate_limiter, fetch_binance_price
)
from services.notification_service import (
    send_telegram_alert, save_notification_record, send_telegram_message
)
from services.portfolio_service import (
    record_true_portfolio_value, compute_portfolio_total_value, record_portfolio_history, get_comprehensive_crypto_data_for_user
)
from services.credential_service import get_user_credentials
from services.price_history_service import record_price_history_snapshot

# Persistent alert states store
_alert_state_lock = threading.Lock()
ALERT_STATE_FILE = "alert_state.json"

def _load_alert_states():
    if os.path.exists(ALERT_STATE_FILE):
        try:
            with open(ALERT_STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading alert states: {e}")
            return {}
    return {}

def _save_alert_states(states):
    try:
        with open(ALERT_STATE_FILE, 'w') as f:
            json.dump(states, f)
    except Exception as e:
        logger.error(f"Error saving alert states: {e}")

def _make_alert_key(user_id, symbol, direction, source=None, threshold=None):
    thresh_str = f"{float(threshold):.6f}" if threshold is not None else "None"
    src = source or "portfolio"
    return f"{user_id}:{symbol.upper()}:{direction.lower()}:{src}:{thresh_str}"

def _normalize_threshold(threshold):
    if threshold is None:
        return None
    try:
        return float(f"{float(threshold):.6f}")
    except:
        return None

def get_last_alert_state(user_id, symbol, direction, source=None, threshold=None):
    key = _make_alert_key(user_id, symbol, direction, source, threshold)
    with _alert_state_lock:
        states = _load_alert_states()
        return states.get(key)

def set_last_alert_state(user_id, symbol, direction, value, source=None, threshold=None):
    key = _make_alert_key(user_id, symbol, direction, source, threshold)
    with _alert_state_lock:
        states = _load_alert_states()
        if value is None:
            states.pop(key, None)
        else:
            states[key] = value
        _save_alert_states(states)

def safe_background_iteration(f):
    def wrapper(*args, **kwargs):
        try:
            try:
                db.session.rollback()
            except Exception:
                pass
            res = f(*args, **kwargs)
            try:
                db.session.commit()
            except Exception as commit_err:
                logger.error(f"Background iteration commit error: {commit_err}")
                db.session.rollback()
            return res
        except Exception as e:
            logger.error(f"Background iteration error: {e}")
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            try:
                db.session.remove()
            except Exception:
                pass
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
                    coins = Coin.query.filter(
                        Coin.user_id == user.id,
                        db.or_(Coin.hidden == False, Coin.amount > 0, Coin.force_visible == True)
                    ).all()
                    for coin in coins:
                        symbol = (coin.symbol or '').upper()
                        price = None
                        
                        if binance_rate_limiter.can_call(symbol):
                            try:
                                price = fetch_binance_price(symbol)
                                if price and price > 0:
                                    binance_rate_limiter.record_call(symbol)
                                    coin.current = price
                                    coin.updated_at = datetime.utcnow()
                                    try:
                                        record_price_history_snapshot(symbol, price)
                                    except Exception as history_error:
                                        logger.warning(f"Failed to record price history for {symbol}: {history_error}")
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

                        if not coin.alert_enabled:
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

                    # Compute and record total portfolio value for history chart
                    try:
                        cred_obj = get_user_credentials(user.username)
                        total_val = compute_portfolio_total_value(user.id, username=user.username, cred=cred_obj)
                        if total_val > 0:
                            record_portfolio_history(user.id, round(total_val, 2))
                    except Exception as val_err:
                        logger.error(f"Error computing/recording portfolio total for user {user.username}: {val_err}")
            iteration()
            time.sleep(60)

def watchlist_alert_loop(app):
    logger.info("=== watchlist_alert_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    watchlist_coins = WatchlistCoin.query.filter_by(user_id=user.id, hidden=False).all()
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
                            
                        if price is None or not coin.alert_enabled:
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
            time.sleep(60)

def check_coin_volatility(user, coin, ticker_map, client, volatility_hours, table_type):
    """Check volatility against the configured number of completed hourly candles."""
    try:
        symbol = coin.symbol.upper()
        volatility_threshold = float(coin.volatility_pct or 0)
        if volatility_threshold <= 0: return

        ticker = ticker_map.get(f"{symbol}USDT") or ticker_map.get(f"{symbol}USD") or ticker_map.get(symbol)
        if not ticker or 'lastPrice' not in ticker:
            return

        pair = ticker.get('symbol')
        if not pair:
            return
        klines = client.get_klines(symbol=pair, interval='1h', limit=volatility_hours + 1)
        if len(klines) < 2:
            return

        start_price = float(klines[0][1])
        current_price = float(ticker['lastPrice'])
        if start_price <= 0:
            return
        price_change_pct = ((current_price - start_price) / start_price) * 100

        if abs(price_change_pct) >= volatility_threshold:
            direction = "UP" if price_change_pct > 0 else "DOWN"
            last_alert = get_last_alert_state(user.id, symbol, "volatility", source=table_type, threshold=volatility_threshold)
            if last_alert != "sent":
                msg = f"⚠️ VOLATILITY ALERT: {symbol} is {direction} {abs(price_change_pct):.2f}% in {volatility_hours}h!"
                send_telegram_message(user.username, msg)
                set_last_alert_state(user.id, symbol, "volatility", "sent", source=table_type, threshold=volatility_threshold)
        else:
            set_last_alert_state(user.id, symbol, "volatility", None, source=table_type, threshold=volatility_threshold)
    except Exception as e:
        logger.error(f"Error checking volatility for {coin.symbol}: {e}")

def check_auto_sell_for_coin(user, coin, ticker_map, client):
    """
    Check if an auto-sell enabled coin has dropped more than its threshold in a 1-hour period,
    and execute an automatic market sell for USDT if triggered.
    """
    try:
        if not getattr(coin, 'auto_sell_enabled', False):
            return
        if not coin.amount or float(coin.amount) <= 0:
            return

        symbol = coin.symbol.upper()
        threshold = float(getattr(coin, 'auto_sell_volatility_pct', None) or coin.volatility_pct or 0)
        if threshold <= 0:
            return

        # Target USDT pair, fallback to USD
        pair = f"{symbol}USDT"
        ticker = ticker_map.get(pair)
        if not ticker:
            pair = f"{symbol}USD"
            ticker = ticker_map.get(pair)
        if not ticker or 'lastPrice' not in ticker:
            return

        # Fetch 1-hour klines (interval='1h', limit=2: [0] is previous hour, [1] is current hour)
        klines = client.get_klines(symbol=pair, interval='1h', limit=2)
        if len(klines) < 2:
            return

        start_price = float(klines[0][1])  # Open price of 1h candle (previous hour reference)
        current_price = float(ticker['lastPrice'])
        if start_price <= 0:
            return

        # Calculate price drop percentage (positive when price drops)
        price_drop_pct = ((start_price - current_price) / start_price) * 100

        # If price dropped by more than threshold within 1 hour
        if price_drop_pct >= threshold:
            logger.warning(
                f"🚨 AUTO-SELL TRIGGERED for User {user.username}: {symbol} dropped {price_drop_pct:.2f}% "
                f"(Threshold: {threshold}%) from ${start_price:.4f} to ${current_price:.4f}"
            )
            execute_auto_sell(user, coin, pair, current_price, price_drop_pct, threshold, client)
    except Exception as e:
        logger.error(f"Error checking auto-sell for {getattr(coin, 'symbol', '?')}: {e}", exc_info=True)

def execute_auto_sell(user, coin, pair, current_price, price_drop_pct, threshold, client):
    """Execute automatic market sell for USDT upon volatility drop trigger, cancelling conflicting open orders first."""
    from models import Notification
    from trading_models import AllActivity
    from services.binance_service import get_symbol_filters
    from services.common import format_quantity

    symbol = coin.symbol.upper()
    try:
        # Step 1: Check for and cancel any existing open orders for this coin to unlock balances
        cancelled_orders = []
        try:
            open_orders = []
            try:
                open_orders = client.get_open_orders()
            except Exception as all_ord_err:
                logger.warning(f"Failed to fetch global open orders for {symbol}, checking pair {pair}: {all_ord_err}")
                try:
                    open_orders = client.get_open_orders(symbol=pair)
                except Exception:
                    open_orders = []

            for ord_item in open_orders:
                ord_symbol = ord_item.get('symbol', '')
                # Match orders where base asset matches our coin (e.g., ETHUSDT, ETHUSD, ETHBTC)
                if ord_symbol.startswith(symbol) or ord_symbol == pair:
                    ord_id = ord_item.get('orderId')
                    try:
                        logger.info(f"Auto-Sell pre-check: Cancelling conflicting open order {ord_symbol} #{ord_id} for User {user.username}...")
                        client.cancel_order(symbol=ord_symbol, orderId=ord_id)
                        cancelled_orders.append(f"{ord_symbol} #{ord_id}")

                        # Update local RealOrder record if present
                        try:
                            from trading_models import RealOrder
                            local_order = RealOrder.query.filter_by(user_id=user.id, binance_order_id=int(ord_id)).first()
                            if local_order:
                                local_order.status = 'CANCELED'
                                local_order.canceled_at = datetime.utcnow()
                                local_order.updated_at = datetime.utcnow()
                        except Exception as loc_err:
                            logger.warning(f"Could not update local RealOrder for #{ord_id}: {loc_err}")
                    except Exception as cancel_err:
                        logger.error(f"Failed to cancel open order {ord_symbol} #{ord_id}: {cancel_err}")

            if cancelled_orders:
                logger.info(f"Auto-Sell: Successfully cancelled {len(cancelled_orders)} open order(s) for {symbol}: {', '.join(cancelled_orders)}")
                time.sleep(0.5)  # Brief pause to allow balance unlock to settle on Binance
        except Exception as open_err:
            logger.error(f"Error during open orders check/cancellation for {symbol}: {open_err}")

        # Step 2: Get symbol trading filters
        filters = get_symbol_filters(client, pair)
        if not filters:
            logger.error(f"Failed to get symbol filters for auto-sell pair {pair}")
            return

        # Step 3: Check updated free balance on Binance
        try:
            balance = client.get_asset_balance(asset=symbol)
            free_balance = float(balance.get('free', 0)) if balance else 0.0
        except Exception as bal_err:
            logger.warning(f"Could not fetch asset balance for {symbol}, using coin.amount: {bal_err}")
            free_balance = float(coin.amount or 0)

        sell_qty = min(float(coin.amount or 0), free_balance) if free_balance > 0 else float(coin.amount or 0)
        if sell_qty <= 0:
            logger.warning(f"No available balance to sell for {symbol} after open order cancellation. Disabling auto-sell.")
            coin.auto_sell_enabled = False
            db.session.commit()
            return

        step_size = filters.get('stepSize', 0.00001)
        formatted_qty = format_quantity(sell_qty, step_size)
        min_qty = filters.get('minQty', 0)
        min_notional = filters.get('minNotional', 0)

        if formatted_qty < min_qty or (formatted_qty * current_price) < min_notional:
            logger.warning(f"Auto-sell quantity {formatted_qty} {symbol} is below minQty ({min_qty}) or minNotional ({min_notional}). Disabling auto-sell.")
            coin.auto_sell_enabled = False
            db.session.commit()
            return

        logger.info(f"Placing market sell order on Binance for {formatted_qty} {symbol} ({pair})...")
        order = client.order_market_sell(
            symbol=pair,
            quantity=formatted_qty
        )

        order_id = order.get('orderId', 'unknown')
        executed_qty = float(order.get('executedQty', formatted_qty))
        fills = order.get('fills', [])
        total_commission = 0.0
        avg_price = 0.0
        if fills:
            total_price = sum(float(f['price']) * float(f['qty']) for f in fills)
            total_filled_qty = sum(float(f['qty']) for f in fills)
            avg_price = total_price / total_filled_qty if total_filled_qty > 0 else current_price
            total_commission = sum(float(f['commission']) for f in fills)
        else:
            avg_price = float(order.get('price', current_price) or current_price)

        proceeds = executed_qty * avg_price
        quote_asset = 'USDT' if pair.endswith('USDT') else ('USD' if pair.endswith('USD') else 'USDT')

        cancel_note = f" (Cancelled {len(cancelled_orders)} open order(s): {', '.join(cancelled_orders)})" if cancelled_orders else ""

        # Record activity
        new_activity = AllActivity(
            date=datetime.utcnow(),
            type='SELL',
            asset=symbol,
            amount=-executed_qty,
            proceeds=proceeds,
            fee=total_commission,
            txid=f"auto_sell_{order_id}",
            status=order.get('status', 'FILLED'),
            details=f"⚡ Auto-Sell executed: {price_drop_pct:.2f}% drop in 1h (Threshold: {threshold}%) for {quote_asset}{cancel_note}",
            avg_entry=avg_price,
            user_id=user.id,
            exchange='binance'
        )
        db.session.add(new_activity)

        # Update coin record
        coin.auto_sell_enabled = False
        coin.auto_sell_triggered_at = datetime.utcnow()
        if coin.amount:
            coin.amount = max(0.0, float(coin.amount) - executed_qty)

        # Create in-app notification
        notif = Notification(
            user_id=user.id,
            title=f"🚨 Auto-Sell Executed: {symbol}",
            message=f"Automatically sold {executed_qty} {symbol} for {quote_asset} at ~${avg_price:.4f} after a {price_drop_pct:.2f}% price drop in 1 hour (Threshold: {threshold}%).{cancel_note} Order ID: {order_id}",
            created_at=datetime.utcnow()
        )
        db.session.add(notif)
        db.session.commit()

        # Send Telegram notification
        telegram_msg = (
            f"🚨 <b>AUTO-SELL EXECUTED</b>\n"
            f"Coin: <b>{symbol}</b>\n"
            f"Action: Sold <b>{executed_qty} {symbol}</b> for <b>{quote_asset}</b>\n"
            f"Trigger: Dropped <b>{price_drop_pct:.2f}%</b> in 1h (Threshold: <b>{threshold}%</b>)\n"
            f"Exec Price: ~${avg_price:.4f}\n"
            f"Proceeds: ${proceeds:.2f} {quote_asset}\n"
            f"{f'Cancelled Orders: {len(cancelled_orders)}\n' if cancelled_orders else ''}"
            f"Order ID: {order_id}"
        )
        send_telegram_message(user.username, telegram_msg)
        logger.info(f"Auto-sell for {symbol} completed successfully. Order ID: {order_id}")
    except Exception as exec_err:
        logger.error(f"Failed to execute auto-sell for {symbol} (User {user.username}): {exec_err}", exc_info=True)

def volatility_alert_loop(app):
    logger.info("=== volatility_alert_loop STARTED ===")
    from sqlalchemy import or_
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    user_settings = UserSetting.query.filter_by(user_id=user.id).first()
                    volatility_hours = int(getattr(user_settings, 'volatility_hours', 24) or 24)
                    volatility_hours = max(1, min(volatility_hours, 999))
                    coins = Coin.query.filter(
                        Coin.user_id == user.id,
                        or_(Coin.volatility_pct > 0, Coin.auto_sell_enabled == True)
                    ).all()
                    watchlist_coins = WatchlistCoin.query.filter(WatchlistCoin.user_id == user.id, WatchlistCoin.volatility_pct > 0).all()
                    
                    if not coins and not watchlist_coins:
                        continue

                    credentials = get_user_credentials(user.username)
                    if not credentials or not (credentials.api_key or credentials.trading_api_key):
                        continue

                    from binance.client import Client
                    client = Client(credentials.api_key, credentials.api_secret, tld='us')
                    try:
                        tickers = client.get_ticker()
                        ticker_map = {t['symbol']: t for t in tickers if isinstance(t, dict) and 'symbol' in t}
                    except Exception as tick_err:
                        logger.error(f"Failed to fetch tickers for volatility check (User {user.username}): {tick_err}")
                        continue

                    for coin in coins:
                        if coin.volatility_pct and float(coin.volatility_pct) > 0:
                            check_coin_volatility(user, coin, ticker_map, client, volatility_hours, 'portfolio')
                        if getattr(coin, 'auto_sell_enabled', False):
                            check_auto_sell_for_coin(user, coin, ticker_map, client)
                    for coin in watchlist_coins:
                        check_coin_volatility(user, coin, ticker_map, client, volatility_hours, 'watchlist')
            iteration()
            time.sleep(120)

def prune_old_ai_conversations(app):
    """Clean up AI conversations older than 30 days, keeping maximum 1 month of history."""
    from datetime import datetime, timedelta
    from models import AIConversation
    logger.info("=== Starting AI conversation 30-day retention cleanup ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                cutoff = datetime.utcnow() - timedelta(days=30)
                deleted = AIConversation.query.filter(AIConversation.created_at < cutoff).delete(synchronize_session=False)
                if deleted > 0:
                    db.session.commit()
                    logger.info(f"AI Conversation Retention: Pruned {deleted} conversations older than {cutoff}.")
                else:
                    logger.info(f"AI Conversation Retention: No conversations older than {cutoff} found.")
            iteration()
            # Sleep 24 hours between runs
            time.sleep(86400)

def sentiment_analysis_loop(app):
    """Background loop to periodically run sentiment analysis for enabled users according to their frequency settings."""
    from services.ai_service import run_sentiment_analysis_for_user, run_watchlist_sentiment_analysis_for_user
    logger.info("=== sentiment_analysis_loop STARTED ===")
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                users = User.query.all()
                for user in users:
                    try:
                        run_sentiment_analysis_for_user(user.id, user.username, force=False)
                    except Exception as e:
                        logger.error(f"Error in background portfolio sentiment analysis for {user.username}: {e}")
                    try:
                        run_watchlist_sentiment_analysis_for_user(user.id, user.username, force=False)
                    except Exception as e:
                        logger.error(f"Error in background watchlist sentiment analysis for {user.username}: {e}")
            iteration()
            # Check every 30 minutes
            time.sleep(1800)

_background_tasks_started = False
_background_tasks_lock = threading.Lock()

def start_background_jobs(app=None):
    """Initialize and start all background alert, sync, and retention loops."""
    global _background_tasks_started
    import threading
    from log import logger
    
    with _background_tasks_lock:
        if _background_tasks_started:
            logger.info("Background jobs already started, skipping duplicate initialization.")
            return {}
        _background_tasks_started = True

    if not app:
        from flask import current_app
        app = current_app._get_current_object() if current_app else None
        
    if not app:
        logger.warning("start_background_jobs called without an active app.")
        return {}

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
    
    # 5. AI Conversation 30-day Retention Loop
    retention_thread = threading.Thread(target=prune_old_ai_conversations, args=(app,), daemon=True)
    retention_thread.start()

    # 6. Periodic Sentiment Analysis Loop
    sentiment_thread = threading.Thread(target=sentiment_analysis_loop, args=(app,), daemon=True)
    sentiment_thread.start()
    
    logger.info("All background threads initiated.")
    return {
        "sync": sync_thread,
        "portfolio": portfolio_thread,
        "watchlist": watchlist_thread,
        "volatility": volatility_thread,
        "ai_retention": retention_thread,
        "sentiment": sentiment_thread
    }
