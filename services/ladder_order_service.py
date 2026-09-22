"""
Ladder Order Service
Provides synthetic server-side ladder order creation, template configuration,
price monitoring, progressive rung execution, and lifecycle management for
both Binance.US (Crypto) and Webull (Equities, ETFs, and Crypto).
"""

import time
import math
from datetime import datetime
from flask import current_app
from core.extensions import db
from core.time_utils import utc_now
from trading_models import LadderOrder, LadderRung, TestOrder, RealOrder, AllActivity
from models import Coin
from credentials import Credential, UserSetting
from log import logger
from services.trailing_order_service import _get_reference_price


PRESET_TEMPLATES = {
    'SELL': {
        'Conservative': [
            {'offset_pct': 2.0, 'pct_of_total': 33.33},
            {'offset_pct': 4.0, 'pct_of_total': 33.33},
            {'offset_pct': 6.0, 'pct_of_total': 33.34},
        ],
        'Aggressive': [
            {'offset_pct': 5.0, 'pct_of_total': 25.0},
            {'offset_pct': 10.0, 'pct_of_total': 25.0},
            {'offset_pct': 15.0, 'pct_of_total': 25.0},
            {'offset_pct': 20.0, 'pct_of_total': 25.0},
        ]
    },
    'BUY': {
        'Conservative': [
            {'offset_pct': -2.0, 'pct_of_total': 33.33},
            {'offset_pct': -4.0, 'pct_of_total': 33.33},
            {'offset_pct': -6.0, 'pct_of_total': 33.34},
        ],
        'Aggressive': [
            {'offset_pct': -5.0, 'pct_of_total': 25.0},
            {'offset_pct': -10.0, 'pct_of_total': 25.0},
            {'offset_pct': -15.0, 'pct_of_total': 25.0},
            {'offset_pct': -20.0, 'pct_of_total': 25.0},
        ]
    }
}


def calculate_ladder_rungs(side, current_price, total_quantity, preset_name='Conservative', custom_rungs=None):
    """
    Computes price targets and quantity allocation for each rung of a ladder.
    Returns list of dicts: [{rung_number, target_price, price_offset_pct, quantity, percentage_of_total, estimated_usd}]
    """
    ref_price = float(current_price)
    total_qty = float(total_quantity)
    clean_side = side.upper()

    if custom_rungs and len(custom_rungs) > 0:
        specs = custom_rungs
    else:
        preset = preset_name if preset_name in PRESET_TEMPLATES.get(clean_side, {}) else 'Conservative'
        specs = PRESET_TEMPLATES[clean_side][preset]

    calculated_rungs = []
    remaining_qty = total_qty

    for i, spec in enumerate(specs):
        rung_num = i + 1
        
        # Determine target price
        if 'target_price' in spec and spec['target_price'] and float(spec['target_price']) > 0:
            target_px = float(spec['target_price'])
            offset_pct = round(((target_px - ref_price) / ref_price) * 100.0, 2)
        else:
            offset_pct = float(spec.get('offset_pct', spec.get('price_offset_pct', 0.0)))
            target_px = round(ref_price * (1.0 + (offset_pct / 100.0)), 6)

        # Determine quantity
        if i == len(specs) - 1:
            # Final rung absorbs any rounding discrepancy
            qty = round(remaining_qty, 8)
            pct_total = round((qty / total_qty) * 100.0, 2)
        else:
            pct_total = float(spec.get('pct_of_total', spec.get('percentage_of_total', 100.0 / len(specs))))
            qty = round(total_qty * (pct_total / 100.0), 8)
            remaining_qty -= qty

        estimated_usd = round(qty * target_px, 2)

        calculated_rungs.append({
            'rung_number': rung_num,
            'target_price': target_px,
            'price_offset_pct': offset_pct,
            'quantity': qty,
            'percentage_of_total': pct_total,
            'estimated_usd': estimated_usd,
            'status': 'PENDING'
        })

    return calculated_rungs


def create_ladder_order(user_id, symbol, side, total_quantity, preset_name='Conservative',
                        custom_rungs=None, has_stop_loss=False, stop_loss_trigger_price=None,
                        stop_loss_action='SELL_ALL', broker='binance', account_id=None,
                        instrument_type='CRYPTO', trading_session='CORE', test_mode=False, client=None):
    """
    Validate, calculate, and persist a parent LadderOrder with child LadderRungs.
    """
    clean_symbol = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_broker = str(broker or 'binance').strip().lower()
    clean_instrument = str(instrument_type or 'CRYPTO').strip().upper()
    clean_session = str(trading_session or 'CORE').strip().upper()
    clean_account_id = str(account_id).strip() if account_id else None

    if clean_side not in ('BUY', 'SELL'):
        raise ValueError("Order side must be BUY or SELL.")

    try:
        qty = float(total_quantity)
        if qty <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Total quantity must be a positive number.")

    current_price = _get_reference_price(clean_symbol, client=client, broker=clean_broker, instrument_type=clean_instrument, user_id=user_id)
    if not current_price or current_price <= 0:
        raise ValueError(f"Unable to determine current market price for {clean_symbol}.")

    sl_price = None
    if has_stop_loss and stop_loss_trigger_price:
        try:
            sl_price = float(stop_loss_trigger_price)
            if sl_price <= 0:
                sl_price = None
        except (TypeError, ValueError):
            sl_price = None

    rungs_data = calculate_ladder_rungs(clean_side, current_price, qty, preset_name=preset_name, custom_rungs=custom_rungs)
    if not rungs_data or len(rungs_data) == 0:
        raise ValueError("Ladder must contain at least one valid rung.")

    total_budget = sum(r['estimated_usd'] for r in rungs_data)

    ladder = LadderOrder(
        user_id=user_id,
        broker=clean_broker,
        account_id=clean_account_id,
        symbol=clean_symbol,
        instrument_type=clean_instrument,
        side=clean_side,
        total_quantity=qty,
        total_budget_usd=total_budget,
        preset_name=preset_name or 'Custom',
        has_stop_loss=bool(has_stop_loss and sl_price),
        stop_loss_trigger_price=sl_price,
        stop_loss_action=stop_loss_action or 'SELL_ALL',
        status='ACTIVE',
        rungs_total=len(rungs_data),
        rungs_filled=0,
        test_mode=bool(test_mode),
        trading_session=clean_session,
        created_at=utc_now(aware=False),
        updated_at=utc_now(aware=False)
    )

    db.session.add(ladder)
    db.session.flush() # Flush to obtain ladder.id

    for r in rungs_data:
        rung = LadderRung(
            ladder_id=ladder.id,
            rung_number=r['rung_number'],
            target_price=r['target_price'],
            price_offset_pct=r.get('price_offset_pct'),
            quantity=r['quantity'],
            percentage_of_total=r.get('percentage_of_total'),
            estimated_usd=r.get('estimated_usd'),
            status='PENDING'
        )
        db.session.add(rung)

    db.session.commit()
    logger.info(f"Created LadderOrder #{ladder.id} [{clean_broker.upper()}]: {clean_side} {qty} {clean_symbol} across {len(rungs_data)} rungs.")
    return ladder.to_dict()


def cancel_ladder_order(ladder_id, user_id):
    """
    Cancels an active ladder order and all its pending rungs.
    """
    ladder = LadderOrder.query.filter_by(id=ladder_id, user_id=user_id).first()
    if not ladder:
        raise ValueError(f"Ladder order #{ladder_id} not found.")

    if ladder.status in ('COMPLETED', 'CANCELLED'):
        raise ValueError(f"Ladder order #{ladder_id} is already in state {ladder.status}.")

    for rung in ladder.rungs:
        if rung.status == 'PENDING':
            rung.status = 'CANCELLED'

    ladder.status = 'CANCELLED'
    ladder.updated_at = utc_now(aware=False)
    db.session.commit()
    logger.info(f"Cancelled LadderOrder #{ladder_id} for user {user_id}")
    return ladder.to_dict()


def get_user_ladder_orders(user_id, symbol=None, status=None, broker=None):
    """
    Fetch all ladder orders for a user with child rungs.
    """
    query = LadderOrder.query.filter_by(user_id=user_id)
    if broker:
        query = query.filter_by(broker=broker.lower())
    if symbol:
        query = query.filter_by(symbol=symbol.strip().upper())
    if status:
        query = query.filter_by(status=status.strip().upper())

    ladders = query.order_by(LadderOrder.created_at.desc()).all()
    return [l.to_dict() for l in ladders]


def evaluate_single_ladder_order(ladder, current_price, execute_trigger=True):
    """
    Evaluates ladder rungs against market price.
    Returns (updated, triggered_count).
    """
    if ladder.status not in ('ACTIVE', 'PARTIALLY_FILLED'):
        return False, 0

    price = float(current_price)
    updated = False
    triggered_count = 0

    # 1. Check Downside Stop-Loss if enabled
    if ladder.has_stop_loss and ladder.stop_loss_trigger_price:
        if ladder.side == 'SELL' and price <= ladder.stop_loss_trigger_price:
            logger.info(f"LadderOrder #{ladder.id} STOP-LOSS TRIGGERED at price ${price:.4f} <= stop ${ladder.stop_loss_trigger_price:.4f}")
            # Calculate remaining unfilled quantity
            pending_rungs = [r for r in ladder.rungs if r.status == 'PENDING']
            remaining_qty = sum(r.quantity for r in pending_rungs)
            
            if remaining_qty > 0 and execute_trigger:
                _execute_stop_loss_market_sell(ladder, remaining_qty, price)

            for r in pending_rungs:
                r.status = 'CANCELLED'
                r.error_message = f"Cancelled due to Stop-Loss trigger at ${price:.4f}"

            ladder.status = 'STOPPED_OUT'
            ladder.updated_at = utc_now(aware=False)
            return True, 1

    # 2. Check each pending rung
    for rung in ladder.rungs:
        if rung.status != 'PENDING':
            continue

        rung_triggered = False
        if ladder.side == 'SELL':
            # Profit-taking ladder: price climbed to or above target
            if price >= rung.target_price:
                rung_triggered = True
        else: # BUY
            # Scale-in ladder: price dipped to or below target
            if price <= rung.target_price:
                rung_triggered = True

        if rung_triggered:
            rung.status = 'TRIGGERED'
            updated = True
            triggered_count += 1
            logger.info(f"LadderOrder #{ladder.id} Rung #{rung.rung_number} TRIGGERED at price ${price:.4f} (target: ${rung.target_price:.4f})")
            
            if execute_trigger:
                execute_ladder_rung_trigger(ladder, rung, price)

    if updated:
        # Re-tally filled/triggered rungs
        filled_count = sum(1 for r in ladder.rungs if r.status in ('FILLED', 'TRIGGERED'))
        ladder.rungs_filled = filled_count
        if filled_count >= ladder.rungs_total:
            ladder.status = 'COMPLETED'
        elif filled_count > 0:
            ladder.status = 'PARTIALLY_FILLED'
        ladder.updated_at = utc_now(aware=False)

    return updated, triggered_count


def execute_ladder_rung_trigger(ladder, rung, current_price):
    """
    Submits a market execution for a triggered ladder rung.
    """
    try:
        if ladder.test_mode:
            test_order = TestOrder(
                user_id=ladder.user_id,
                symbol=ladder.symbol,
                side=ladder.side,
                type='MARKET',
                quantity=rung.quantity,
                price=current_price,
                status='FILLED',
                created_at=utc_now(aware=False),
                executed_at=utc_now(aware=False)
            )
            db.session.add(test_order)
            rung.status = 'FILLED'
            rung.executed_price = current_price
            rung.executed_at = utc_now(aware=False)
            rung.executed_order_id = f"test_ladder_{ladder.id}_{rung.rung_number}_{int(time.time())}"
            ladder.rungs_filled = sum(1 for r in ladder.rungs if r.status == 'FILLED')
            if ladder.rungs_filled >= ladder.rungs_total:
                ladder.status = 'COMPLETED'
            elif ladder.rungs_filled > 0:
                ladder.status = 'PARTIALLY_FILLED'
            logger.info(f"LadderOrder #{ladder.id} Rung #{rung.rung_number} filled in TEST mode.")
            return

        clean_broker = (ladder.broker or 'binance').lower()

        # Webull execution (Equities, ETFs, Crypto)
        if clean_broker == 'webull':
            from services.webull_service import place_webull_order
            cred = Credential.query.filter_by(user_id=ladder.user_id).first()
            if not cred or not cred.webull_app_key or not cred.webull_app_secret:
                rung.status = 'FAILED'
                rung.error_message = "Missing Webull trading credentials."
                return

            setting = UserSetting.query.filter_by(user_id=ladder.user_id).first()
            environment = getattr(setting, 'webull_environment', 'production') if setting else 'production'

            account_id = ladder.account_id
            if not account_id and setting and setting.webull_default_account_id:
                account_id = setting.webull_default_account_id

            webull_params = {
                'app_key': cred.webull_app_key,
                'app_secret': cred.webull_app_secret,
                'environment': environment,
                'access_token': cred.webull_access_token,
                'account_id': account_id,
                'symbol': ladder.symbol,
                'instrument_type': ladder.instrument_type or 'EQUITY',
                'side': ladder.side,
                'order_type': 'MARKET',
                'quantity': rung.quantity,
                'support_trading_session': ladder.trading_session or 'CORE'
            }
            logger.info(f"Submitting Webull rung order for LadderOrder #{ladder.id}: {webull_params}")
            resp = place_webull_order(**webull_params)
            rung.executed_order_id = str(resp.get('order_id') or resp.get('client_order_id') or '')
            rung.executed_price = current_price
            rung.executed_at = utc_now(aware=False)
            rung.status = 'FILLED'
            ladder.rungs_filled = sum(1 for r in ladder.rungs if r.status == 'FILLED')
            if ladder.rungs_filled >= ladder.rungs_total:
                ladder.status = 'COMPLETED'
            elif ladder.rungs_filled > 0:
                ladder.status = 'PARTIALLY_FILLED'
            logger.info(f"LadderOrder #{ladder.id} Rung #{rung.rung_number} successfully executed on Webull.")
            return

        # Binance.US execution
        from binance.client import Client
        cred = Credential.query.filter_by(user_id=ladder.user_id).first()
        if not cred or not cred.trading_api_key or not cred.trading_api_secret:
            rung.status = 'FAILED'
            rung.error_message = "Missing Binance.US trading credentials."
            return

        client = Client(api_key=cred.trading_api_key, api_secret=cred.trading_api_secret, testnet=False, tld='us')
        order_params = {
            'symbol': ladder.symbol,
            'side': ladder.side,
            'type': 'MARKET',
            'quantity': rung.quantity
        }
        logger.info(f"Submitting Binance.US rung order for LadderOrder #{ladder.id}: {order_params}")
        resp = client.create_order(**order_params)
        rung.executed_order_id = str(resp.get('orderId') or resp.get('clientOrderId') or '')
        rung.executed_price = current_price
        rung.executed_at = utc_now(aware=False)
        rung.status = 'FILLED' if resp.get('status') in ('FILLED', 'PARTIALLY_FILLED', 'NEW') else resp.get('status', 'FILLED')
        ladder.rungs_filled = sum(1 for r in ladder.rungs if r.status == 'FILLED')
        if ladder.rungs_filled >= ladder.rungs_total:
            ladder.status = 'COMPLETED'
        elif ladder.rungs_filled > 0:
            ladder.status = 'PARTIALLY_FILLED'
        logger.info(f"LadderOrder #{ladder.id} Rung #{rung.rung_number} successfully executed on Binance.US.")

    except Exception as e:
        logger.error(f"Error executing LadderOrder #{ladder.id} Rung #{rung.rung_number}: {e}")
        rung.status = 'FAILED'
        rung.error_message = str(e)


def _execute_stop_loss_market_sell(ladder, quantity, current_price):
    """
    Submits an emergency market sell for remaining ladder quantity when stop-loss is breached.
    """
    try:
        clean_broker = (ladder.broker or 'binance').lower()
        if clean_broker == 'webull':
            from services.webull_service import place_webull_order
            cred = Credential.query.filter_by(user_id=ladder.user_id).first()
            if cred and cred.webull_app_key and cred.webull_app_secret:
                setting = UserSetting.query.filter_by(user_id=ladder.user_id).first()
                environment = getattr(setting, 'webull_environment', 'production') if setting else 'production'
                account_id = ladder.account_id or (getattr(setting, 'webull_default_account_id', None) if setting else None)
                place_webull_order(
                    cred.webull_app_key, cred.webull_app_secret, environment, cred.webull_access_token,
                    account_id=account_id, symbol=ladder.symbol, instrument_type=ladder.instrument_type or 'EQUITY',
                    side='SELL', order_type='MARKET', quantity=quantity, support_trading_session=ladder.trading_session or 'CORE'
                )
        else:
            from binance.client import Client
            cred = Credential.query.filter_by(user_id=ladder.user_id).first()
            if cred and cred.trading_api_key and cred.trading_api_secret:
                client = Client(api_key=cred.trading_api_key, api_secret=cred.trading_api_secret, testnet=False, tld='us')
                client.create_order(symbol=ladder.symbol, side='SELL', type='MARKET', quantity=quantity)
    except Exception as e:
        logger.error(f"Error executing ladder stop loss for #{ladder.id}: {e}")


def evaluate_active_ladder_orders():
    """
    Cycle through all ACTIVE or PARTIALLY_FILLED ladder orders and evaluate against market prices.
    Called by background scheduler thread.
    """
    try:
        active_ladders = LadderOrder.query.filter(LadderOrder.status.in_(['ACTIVE', 'PARTIALLY_FILLED'])).all()
        if not active_ladders:
            return

        modified = False
        for ladder in active_ladders:
            price = _get_reference_price(ladder.symbol, broker=ladder.broker, instrument_type=ladder.instrument_type, user_id=ladder.user_id)
            if price and price > 0:
                updated, _ = evaluate_single_ladder_order(ladder, price, execute_trigger=True)
                if updated:
                    modified = True

        if modified:
            db.session.commit()

    except Exception as e:
        logger.error(f"Error in evaluate_active_ladder_orders: {e}")


def ladder_order_worker_loop(app):
    """
    Supervised daemon thread running continuous evaluation for ladder orders.
    """
    logger.info("Starting background ladder orders monitoring loop...")
    with app.app_context():
        while True:
            try:
                evaluate_active_ladder_orders()
            except Exception as e:
                logger.error(f"Error in ladder_order_worker_loop: {e}")
            time.sleep(2.5)
