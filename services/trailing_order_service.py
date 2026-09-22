import time
import math
from datetime import datetime
from flask import current_app
from core.extensions import db
from core.time_utils import utc_now
from trading_models import TrailingOrder, TradingSettings, TestOrder, RealOrder, AllActivity
from models import Coin
from credentials import Credential
from log import logger

def _get_reference_price(symbol, client=None):
    """
    Get current market price for a symbol using Coin table, Binance client, or public ticker.
    """
    clean_sym = symbol.strip().upper()
    
    # 1. Try Coin table first (fastest, cached by background sync)
    coin = Coin.query.filter_by(symbol=clean_sym).first()
    if coin and coin.current and coin.current > 0:
        return float(coin.current)
    
    # Strip quote to find base coin
    for quote in ['USDT', 'USD', 'BTC', 'ETH', 'BNB']:
        if clean_sym.endswith(quote):
            base = clean_sym[:-len(quote)]
            coin = Coin.query.filter_by(symbol=base).first()
            if coin and coin.current and coin.current > 0:
                return float(coin.current)
            break

    # 2. Try client if provided
    if client:
        try:
            ticker = client.get_symbol_ticker(symbol=clean_sym)
            if ticker and 'price' in ticker:
                return float(ticker['price'])
        except Exception as e:
            logger.warning(f"Failed to fetch ticker from client for {clean_sym}: {e}")

    # 3. Fallback to public Binance.US ticker API
    try:
        import urllib.request
        import json
        url = f"https://api.binance.us/api/v3/ticker/price?symbol={clean_sym}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if 'price' in data:
                return float(data['price'])
    except Exception as e:
        logger.warning(f"Public ticker fetch failed for {clean_sym}: {e}")

    return None


def calculate_trailing_stop_price(side, reference_price, trail_type, trail_value):
    """
    Calculate the dynamic trigger price based on side, reference price (peak/trough),
    and trail type (PERCENT or AMOUNT).
    """
    ref = float(reference_price)
    val = float(trail_value)
    
    if side.upper() == 'SELL':
        # Stop price trails BELOW reference price
        if trail_type.upper() == 'PERCENT':
            return round(ref * (1.0 - (val / 100.0)), 8)
        else:
            return round(max(0.0, ref - val), 8)
    else: # BUY
        # Stop price trails ABOVE reference price
        if trail_type.upper() == 'PERCENT':
            return round(ref * (1.0 + (val / 100.0)), 8)
        else:
            return round(ref + val, 8)


def create_trailing_order(user_id, symbol, side, quantity, trail_type='PERCENT', trail_value=2.0,
                          activation_price=None, execution_type='MARKET', test_mode=False, client=None):
    """
    Validate and persist a new synthetic TrailingOrder.
    """
    clean_symbol = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_trail_type = str(trail_type or 'PERCENT').strip().upper()
    clean_exec_type = str(execution_type or 'MARKET').strip().upper()

    if clean_side not in ('BUY', 'SELL'):
        raise ValueError("Order side must be BUY or SELL.")

    if clean_trail_type not in ('PERCENT', 'AMOUNT'):
        raise ValueError("Trail type must be PERCENT or AMOUNT.")

    try:
        qty = float(quantity)
        if qty <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a positive number.")

    try:
        t_val = float(trail_value)
        if t_val <= 0:
            raise ValueError()
        if clean_trail_type == 'PERCENT' and t_val >= 100.0:
            raise ValueError("Percentage trail must be less than 100%.")
    except (TypeError, ValueError):
        raise ValueError("Trail value must be a positive number.")

    current_price = _get_reference_price(clean_symbol, client=client)
    if not current_price or current_price <= 0:
        raise ValueError(f"Unable to determine current market price for {clean_symbol}.")

    act_price = None
    if activation_price is not None and str(activation_price).strip() != '':
        try:
            act_price = float(activation_price)
            if act_price <= 0:
                act_price = None
        except (TypeError, ValueError):
            act_price = None

    # Determine activation state
    is_activated = True
    highest_price = None
    lowest_price = None

    if clean_side == 'SELL':
        highest_price = current_price
        if act_price and current_price < act_price:
            is_activated = False
        initial_stop = calculate_trailing_stop_price('SELL', highest_price, clean_trail_type, t_val)
    else: # BUY
        lowest_price = current_price
        if act_price and current_price > act_price:
            is_activated = False
        initial_stop = calculate_trailing_stop_price('BUY', lowest_price, clean_trail_type, t_val)

    order = TrailingOrder(
        user_id=user_id,
        symbol=clean_symbol,
        side=clean_side,
        quantity=qty,
        trail_type=clean_trail_type,
        trail_value=t_val,
        activation_price=act_price,
        is_activated=is_activated,
        highest_price=highest_price,
        lowest_price=lowest_price,
        current_stop_price=initial_stop,
        execution_type=clean_exec_type,
        test_mode=bool(test_mode),
        status='ACTIVE',
        created_at=utc_now(aware=False),
        updated_at=utc_now(aware=False)
    )

    db.session.add(order)
    db.session.commit()
    logger.info(f"Created TrailingOrder #{order.id}: {clean_side} {qty} {clean_symbol} (trail={t_val} {clean_trail_type}, stop={initial_stop})")
    return order.to_dict()


def cancel_trailing_order(order_id, user_id):
    """
    Cancel an active trailing order.
    """
    order = TrailingOrder.query.filter_by(id=order_id, user_id=user_id).first()
    if not order:
        raise ValueError("Trailing order not found.")

    if order.status != 'ACTIVE':
        raise ValueError(f"Cannot cancel order in '{order.status}' status.")

    order.status = 'CANCELLED'
    order.updated_at = utc_now(aware=False)
    db.session.commit()
    logger.info(f"Cancelled TrailingOrder #{order.id} for user {user_id}")
    return order.to_dict()


def get_user_trailing_orders(user_id, status=None):
    """
    Fetch all trailing orders for user, optionally filtered by status.
    """
    query = TrailingOrder.query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status.upper())
    orders = query.order_by(TrailingOrder.created_at.desc()).all()
    return [o.to_dict() for o in orders]


def evaluate_single_trailing_order(order, current_price, execute_trigger=True):
    """
    Evaluates an active trailing order against a new price tick.
    Ratchets highest/lowest prices and stop price if price moves in favor.
    Triggers execution if price moves against position and crosses stop price.
    Returns: (updated: bool, triggered: bool)
    """
    if order.status != 'ACTIVE':
        return False, False

    price = float(current_price)
    updated = False
    triggered = False

    # Check activation if pending
    if not order.is_activated and order.activation_price:
        if order.side == 'SELL' and price >= order.activation_price:
            order.is_activated = True
            order.highest_price = max(order.highest_price or price, price)
            order.current_stop_price = calculate_trailing_stop_price('SELL', order.highest_price, order.trail_type, order.trail_value)
            updated = True
            logger.info(f"TrailingOrder #{order.id} ACTIVATED at price ${price:.4f}")
        elif order.side == 'BUY' and price <= order.activation_price:
            order.is_activated = True
            order.lowest_price = min(order.lowest_price or price, price)
            order.current_stop_price = calculate_trailing_stop_price('BUY', order.lowest_price, order.trail_type, order.trail_value)
            updated = True
            logger.info(f"TrailingOrder #{order.id} ACTIVATED at price ${price:.4f}")

    if not order.is_activated:
        return updated, False

    # Dynamic trailing logic
    if order.side == 'SELL':
        # If market reaches new high, ratchet up stop price
        if order.highest_price is None or price > order.highest_price:
            order.highest_price = price
            new_stop = calculate_trailing_stop_price('SELL', price, order.trail_type, order.trail_value)
            # Stop price can only increase, never decrease
            if new_stop > order.current_stop_price:
                order.current_stop_price = new_stop
                updated = True
                logger.info(f"TrailingOrder #{order.id} SELL ratcheted up: high=${order.highest_price:.4f}, stop=${order.current_stop_price:.4f}")

        # Check trigger: price dropped to or below dynamic stop
        if price <= order.current_stop_price:
            triggered = True
            order.status = 'TRIGGERED'
            order.triggered_at = utc_now(aware=False)
            updated = True
            logger.info(f"TrailingOrder #{order.id} SELL TRIGGERED at price ${price:.4f} <= stop ${order.current_stop_price:.4f}")
            if execute_trigger:
                execute_trailing_trigger(order, price)

    else: # BUY
        # If market reaches new low, ratchet down stop price
        if order.lowest_price is None or price < order.lowest_price:
            order.lowest_price = price
            new_stop = calculate_trailing_stop_price('BUY', price, order.trail_type, order.trail_value)
            # Buy trigger can only decrease, never increase
            if new_stop < order.current_stop_price:
                order.current_stop_price = new_stop
                updated = True
                logger.info(f"TrailingOrder #{order.id} BUY ratcheted down: low=${order.lowest_price:.4f}, stop=${order.current_stop_price:.4f}")

        # Check trigger: price bounced up to or above dynamic stop
        if price >= order.current_stop_price:
            triggered = True
            order.status = 'TRIGGERED'
            order.triggered_at = utc_now(aware=False)
            updated = True
            logger.info(f"TrailingOrder #{order.id} BUY TRIGGERED at price ${price:.4f} >= stop ${order.current_stop_price:.4f}")
            if execute_trigger:
                execute_trailing_trigger(order, price)

    if updated:
        order.updated_at = utc_now(aware=False)

    return updated, triggered


def execute_trailing_trigger(order, current_price):
    """
    Submits market order when trailing stop is triggered.
    """
    try:
        if order.test_mode:
            # Create TestOrder record
            test_order = TestOrder(
                user_id=order.user_id,
                symbol=order.symbol,
                side=order.side,
                type=order.execution_type,
                quantity=order.quantity,
                price=current_price,
                status='FILLED',
                created_at=utc_now(aware=False),
                executed_at=utc_now(aware=False)
            )
            db.session.add(test_order)
            order.status = 'FILLED'
            order.executed_order_id = f"test_trail_{int(time.time())}"
            logger.info(f"TrailingOrder #{order.id} filled in TEST mode.")
            return

        # Real trading execution on Binance.US
        from credential_security import decrypt_secret
        from binance.client import Client

        cred = Credential.query.filter_by(user_id=order.user_id).first()
        if not cred or not cred.trading_api_key or not cred.trading_api_secret:
            order.status = 'FAILED'
            order.error_message = "Missing Binance.US trading credentials."
            logger.error(f"TrailingOrder #{order.id} failed: No Binance credentials.")
            return

        api_key = cred.trading_api_key
        api_secret = cred.trading_api_secret

        client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')

        order_params = {
            'symbol': order.symbol,
            'side': order.side,
            'type': order.execution_type,
            'quantity': order.quantity
        }

        logger.info(f"Submitting real order for TrailingOrder #{order.id}: {order_params}")
        resp = client.create_order(**order_params)

        order.executed_order_id = str(resp.get('orderId') or resp.get('clientOrderId') or '')
        order.status = 'FILLED' if resp.get('status') in ('FILLED', 'PARTIALLY_FILLED', 'NEW') else resp.get('status', 'FILLED')
        logger.info(f"TrailingOrder #{order.id} successfully submitted to Binance.US (orderId={order.executed_order_id})")

    except Exception as e:
        logger.error(f"Error executing triggered TrailingOrder #{order.id}: {e}")
        order.status = 'FAILED'
        order.error_message = str(e)


def evaluate_active_trailing_orders():
    """
    Cycle through all ACTIVE trailing orders across users and evaluate against latest prices.
    Called by background scheduler thread.
    """
    try:
        active_orders = TrailingOrder.query.filter_by(status='ACTIVE').all()
        if not active_orders:
            return

        # Group by symbol to minimize price fetches
        symbols = list(set(o.symbol for o in active_orders))
        prices = {}
        for s in symbols:
            p = _get_reference_price(s)
            if p and p > 0:
                prices[s] = p

        modified = False
        for order in active_orders:
            price = prices.get(order.symbol)
            if price:
                updated, _ = evaluate_single_trailing_order(order, price, execute_trigger=True)
                if updated:
                    modified = True

        if modified:
            db.session.commit()

    except Exception as e:
        logger.error(f"Error in evaluate_active_trailing_orders: {e}")
        db.session.rollback()


def trailing_order_worker_loop(app):
    """
    Background worker daemon evaluating active trailing orders every 2 seconds.
    """
    logger.info("Starting trailing_order_worker_loop background thread...")
    while True:
        try:
            with app.app_context():
                evaluate_active_trailing_orders()
        except Exception as e:
            logger.error(f"Unhandled exception in trailing_order_worker_loop: {e}")
        time.sleep(2.0)
