import time
from decimal import Decimal
import math
from datetime import datetime
from flask import current_app
from core.extensions import db
from core.time_utils import utc_now
from trading_models import TrailingOrder, TradingSettings, TestOrder, RealOrder, AllActivity
from models import Coin
from credentials import Credential
from log import logger

from services import synthetic_execution_service as execution


def _get_reference_price(symbol, client=None, broker='binance', instrument_type='CRYPTO', user_id=None, environment=None):
    return execution.reference_price(symbol, client, broker, instrument_type, user_id, environment)


def calculate_trailing_stop_price(side, reference_price, trail_type, trail_value):
    """
    Calculate the dynamic trigger price based on side, reference price (peak/trough),
    and trail type (PERCENT or AMOUNT).
    """
    ref = Decimal(str(reference_price))
    val = Decimal(str(trail_value))
    
    if side.upper() == 'SELL':
        # Stop price trails BELOW reference price
        if trail_type.upper() == 'PERCENT':
            return float(ref * (1 - val / 100))
        else:
            return float(max(0, ref - val))
    else: # BUY
        # Stop price trails ABOVE reference price
        if trail_type.upper() == 'PERCENT':
            return float(ref * (1 + val / 100))
        else:
            return float(ref + val)


def create_trailing_order(user_id, symbol, side, quantity, trail_type='PERCENT', trail_value=2.0,
                          activation_price=None, execution_type='MARKET', test_mode=False, client=None,
                          broker='binance', account_id=None, instrument_type='CRYPTO', trading_session='CORE'):
    """
    Validate and persist a new synthetic TrailingOrder.
    Supports both Binance.US and Webull.
    """
    clean_symbol, clean_side, clean_broker, clean_instrument, clean_session, clean_account_id = execution.validate_identity(
        symbol, side, broker, instrument_type, trading_session, account_id, test_mode)
    symbol, side, broker, instrument_type, trading_session, account_id = (clean_symbol, clean_side, clean_broker, clean_instrument, clean_session, clean_account_id)
    if str(execution_type).upper() != 'MARKET':
        raise ValueError('Synthetic trailing orders execute market orders.')
    clean_symbol = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_trail_type = str(trail_type or 'PERCENT').strip().upper()
    clean_exec_type = str(execution_type or 'MARKET').strip().upper()
    clean_broker = str(broker or 'binance').strip().lower()
    clean_instrument = str(instrument_type or 'CRYPTO').strip().upper()
    clean_session = str(trading_session or 'CORE').strip().upper()
    clean_account_id = str(account_id).strip() if account_id else None

    if clean_side not in ('BUY', 'SELL'):
        raise ValueError("Order side must be BUY or SELL.")

    if clean_trail_type not in ('PERCENT', 'AMOUNT'):
        raise ValueError("Trail type must be PERCENT or AMOUNT.")

    try:
        qty = execution.positive(quantity, 'Quantity')
        if qty <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a positive number.")

    try:
        t_val, clean_trail_type = execution.trailing_parameters(trail_value, clean_trail_type)
        if t_val <= 0:
            raise ValueError()
        if clean_trail_type == 'PERCENT' and t_val >= 100.0:
            raise ValueError("Percentage trail must be less than 100%.")
    except (TypeError, ValueError):
        raise ValueError("Trail value must be a positive number.")

    current_price = _get_reference_price(clean_symbol, client=client, broker=clean_broker, instrument_type=clean_instrument, user_id=user_id)
    if not current_price or current_price <= 0:
        raise ValueError(f"Unable to determine current market price for {clean_symbol}.")

    act_price = execution.positive(activation_price, 'Activation price', optional=True)
    if clean_side == 'SELL' and clean_trail_type == 'AMOUNT' and t_val >= max(current_price, act_price or 0):
        raise ValueError('The sell trail amount must be below the price at activation.')

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
        broker=clean_broker,
        account_id=clean_account_id,
        symbol=clean_symbol,
        instrument_type=clean_instrument,
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
        trading_session=clean_session,
        status='ACTIVE',
        created_at=utc_now(aware=False),
        updated_at=utc_now(aware=False)
    )

    order.engine_version = 2
    order.environment = execution.environment_for(user_id, clean_broker)
    rules = execution.quantity_rules(order)
    if abs(execution.normalize_quantity(qty, rules) - qty) > max(1e-14, qty * 1e-12):
        raise ValueError(f'Quantity must be a multiple of {rules["step"]}.')
    execution.check_quantity(order, qty, current_price, rules)
    execution.check_order_limit(order, qty, current_price, rules)
    db.session.add(order)
    db.session.commit()
    logger.info(f"Created TrailingOrder #{order.id} [{clean_broker.upper()}]: {clean_side} {qty} {clean_symbol} (trail={t_val} {clean_trail_type}, stop={initial_stop})")
    return order.to_dict()


def cancel_trailing_order(order_id, user_id):
    return execution.cancel_parent(TrailingOrder, 'TRAILING', order_id, user_id)


def get_user_trailing_orders(user_id, symbol=None, status=None, broker=None, account_id=None, test_mode=None):
    query = TrailingOrder.query.filter_by(user_id=user_id)
    if broker and broker.lower() != 'all':
        query = query.filter_by(broker=broker.lower())
    if symbol:
        query = query.filter_by(symbol=symbol.strip().upper())
    if status:
        query = query.filter_by(status=status.strip().upper())
    if account_id:
        query = query.filter_by(account_id=account_id)
    if test_mode is not None:
        query = query.filter_by(test_mode=test_mode)
    return [o.to_dict() for o in query.order_by(TrailingOrder.created_at.desc()).all()]


def evaluate_single_trailing_order(order, current_price, execute_trigger=True):
    """
    Evaluates an active trailing order against a new price tick.
    Ratchets highest/lowest prices and stop price if price moves in favor.
    Triggers execution if price moves against position and crosses stop price.
    Returns: (updated: bool, triggered: bool)
    """
    if order.status != 'ACTIVE':
        return False, False

    price = execution.positive(current_price, 'Current price')
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


def _sync_trailing(order, rows):
    if not rows:
        return
    row = rows[-1]
    order.executed_order_id = row.broker_order_id
    order.error_message = row.error_message
    if row.status in execution.OPEN_EXECUTIONS:
        order.status = 'CANCEL_PENDING' if order.cancel_requested else 'SUBMITTED'
    elif row.status == 'FILLED':
        order.status = 'FILLED'
    elif order.cancel_requested:
        order.status = 'CANCELLED'
    else:
        order.status = 'FAILED'
        order.error_message = row.error_message or 'Execution ended before the full quantity filled. Review broker fills.'


def execute_trailing_trigger(order, current_price):
    try:
        rows = execution.executions(order, 'TRAILING')
        if not rows:
            rows = [execution.submit_execution(order, 'TRAILING', order.quantity, current_price, 'TRAILING')]
        _sync_trailing(order, rows)
        return order.status in {'SUBMITTED', 'FILLED'}
    except Exception as exc:
        order.status = 'FAILED'
        order.error_message = str(exc)
        return False


def evaluate_active_trailing_orders():
    ids = [o.id for o in TrailingOrder.query.filter(TrailingOrder.status.in_(execution.WORKING_PARENTS)).all()]
    db.session.rollback()
    for identifier in ids:
        try:
            with execution.parent_lock('TRAILING', identifier) as locked:
                if not locked:
                    continue
                order = db.session.get(TrailingOrder, identifier, populate_existing=True)
                if order.status not in execution.WORKING_PARENTS:
                    continue
                if order.engine_version != 2:
                    order.status = 'NEEDS_REVIEW'
                    order.monitoring_error = 'Created before v3.9.0: review broker fills, then cancel and recreate this order.'
                    db.session.commit()
                    continue
                _sync_trailing(order, execution.reconcile_executions(order, 'TRAILING'))
                if order.status == 'ACTIVE' and not order.cancel_requested:
                    if execution.market_is_open(order):
                        try:
                            price = _get_reference_price(order.symbol, broker=order.broker, instrument_type=order.instrument_type,
                                                         user_id=order.user_id, environment=order.environment)
                            order.last_price, order.last_checked_at, order.monitoring_error = price, utc_now(aware=False), None
                            evaluate_single_trailing_order(order, price)
                        except Exception:
                            order.monitoring_error = 'Current venue quote unavailable or stale. Waiting for a fresh quote.'
                    else:
                        order.monitoring_error = 'Waiting for regular market hours; stock/ETF market orders execute only during CORE.'
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Synthetic trailing evaluation failed for order %s', identifier)
        finally:
            db.session.remove()


def trailing_order_worker_loop(app):
    while True:
        try:
            with app.app_context():
                evaluate_active_trailing_orders()
        except Exception:
            logger.exception('Synthetic trailing worker cycle failed')
        time.sleep(2.0)
