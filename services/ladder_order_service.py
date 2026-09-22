"""
Ladder & Synthetic Bracket Order Service
Provides synthetic server-side smart order creation, template configuration,
price monitoring, progressive rung execution, trailing take-profit/stop-loss,
and lifecycle management for both Binance.US (Crypto) and Webull (Equities, ETFs, and Crypto).
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

DOWNSIDE_PRESET_TEMPLATES = {
    'SELL': {
        'Tight': [
            {'offset_pct': -1.5, 'pct_of_total': 33.33},
            {'offset_pct': -3.0, 'pct_of_total': 33.33},
            {'offset_pct': -4.5, 'pct_of_total': 33.34},
        ],
        'Moderate': [
            {'offset_pct': -3.0, 'pct_of_total': 30.0},
            {'offset_pct': -5.0, 'pct_of_total': 30.0},
            {'offset_pct': -8.0, 'pct_of_total': 40.0},
        ]
    },
    'BUY': {
        'Tight': [
            {'offset_pct': 1.5, 'pct_of_total': 33.33},
            {'offset_pct': 3.0, 'pct_of_total': 33.33},
            {'offset_pct': 4.5, 'pct_of_total': 33.34},
        ],
        'Moderate': [
            {'offset_pct': 3.0, 'pct_of_total': 30.0},
            {'offset_pct': 5.0, 'pct_of_total': 30.0},
            {'offset_pct': 8.0, 'pct_of_total': 40.0},
        ]
    }
}


def calculate_ladder_rungs(side, current_price, total_quantity, preset_name='Conservative', custom_rungs=None, rung_type='TAKE_PROFIT'):
    """
    Computes price targets and quantity allocation for each rung of a ladder.
    Returns list of dicts: [{rung_number, target_price, price_offset_pct, quantity, percentage_of_total, estimated_usd, rung_type}]
    """
    ref_price = float(current_price)
    total_qty = float(total_quantity)
    clean_side = side.upper()

    if custom_rungs and len(custom_rungs) > 0:
        specs = custom_rungs
    else:
        if rung_type == 'STOP_LOSS':
            templates = DOWNSIDE_PRESET_TEMPLATES.get(clean_side, {})
            preset = preset_name if preset_name in templates else 'Moderate'
            specs = templates.get(preset, templates.get('Moderate', []))
        else:
            templates = PRESET_TEMPLATES.get(clean_side, {})
            preset = preset_name if preset_name in templates else 'Conservative'
            specs = templates.get(preset, templates.get('Conservative', []))

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
            qty = round(remaining_qty, 8)
            pct_total = round((qty / total_qty) * 100.0, 2) if total_qty > 0 else 0
        else:
            pct_total = float(spec.get('pct_of_total', spec.get('percentage_of_total', 100.0 / max(len(specs), 1))))
            qty = round(total_qty * (pct_total / 100.0), 8)
            remaining_qty -= qty

        estimated_usd = round(qty * target_px, 2)

        calculated_rungs.append({
            'rung_number': rung_num,
            'rung_type': rung_type,
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
                        instrument_type='CRYPTO', trading_session='CORE', test_mode=False, client=None,
                        strategy_type='SYNTHETIC', upside_mode='LADDER', upside_target_price=None,
                        upside_trail_value=None, upside_trail_type='PERCENT', upside_activation_price=None,
                        downside_mode='NONE', downside_target_price=None, downside_trail_value=None,
                        downside_trail_type='PERCENT', downside_activation_price=None,
                        downside_preset='Moderate', downside_rungs=None):
    """
    Validate, calculate, and persist a parent LadderOrder with child LadderRungs.
    Supports Mode A (Single), Mode B (Ladder), Mode C (Trailing) for both Upside and Downside.
    """
    clean_symbol = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_broker = str(broker or 'binance').strip().lower()
    clean_instrument = str(instrument_type or 'CRYPTO').strip().upper()
    clean_session = str(trading_session or 'CORE').strip().upper()
    clean_account_id = str(account_id).strip() if account_id else None

    clean_upside_mode = str(upside_mode or 'LADDER').strip().upper()
    clean_downside_mode = str(downside_mode or 'NONE').strip().upper()

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

    # Resolve legacy stop-loss arguments
    sl_price = None
    if (has_stop_loss or clean_downside_mode == 'SINGLE') and (stop_loss_trigger_price or downside_target_price):
        try:
            sl_price = float(downside_target_price or stop_loss_trigger_price)
            if sl_price <= 0:
                sl_price = None
        except (TypeError, ValueError):
            sl_price = None

    if sl_price and clean_downside_mode == 'NONE':
        clean_downside_mode = 'SINGLE'

    # Build rungs list
    all_rungs_data = []

    # 1. Upside rungs (Take Profit)
    if clean_upside_mode == 'LADDER':
        upside_rungs_data = calculate_ladder_rungs(clean_side, current_price, qty, preset_name=preset_name, custom_rungs=custom_rungs, rung_type='TAKE_PROFIT')
        all_rungs_data.extend(upside_rungs_data)
    elif clean_upside_mode == 'SINGLE':
        tgt_px = float(upside_target_price) if upside_target_price else (current_price * 1.05 if clean_side == 'SELL' else current_price * 0.95)
        offset_pct = round(((tgt_px - current_price) / current_price) * 100.0, 2)
        all_rungs_data.append({
            'rung_number': 1,
            'rung_type': 'TAKE_PROFIT',
            'target_price': tgt_px,
            'price_offset_pct': offset_pct,
            'quantity': qty,
            'percentage_of_total': 100.0,
            'estimated_usd': round(qty * tgt_px, 2),
            'status': 'PENDING'
        })
        upside_target_price = tgt_px
    elif clean_upside_mode == 'TRAILING':
        upside_trail_value = float(upside_trail_value or 2.0)
        upside_trail_type = str(upside_trail_type or 'PERCENT').upper()
        upside_activation_price = float(upside_activation_price) if upside_activation_price else None

    # 2. Downside rungs (Stop Loss)
    if clean_downside_mode == 'LADDER':
        downside_rungs_data = calculate_ladder_rungs(clean_side, current_price, qty, preset_name=downside_preset, custom_rungs=downside_rungs, rung_type='STOP_LOSS')
        # Assign contiguous rung numbers
        start_num = len(all_rungs_data) + 1
        for idx, r in enumerate(downside_rungs_data):
            r['rung_number'] = start_num + idx
            all_rungs_data.append(r)
    elif clean_downside_mode == 'TRAILING':
        downside_trail_value = float(downside_trail_value or 3.0)
        downside_trail_type = str(downside_trail_type or 'PERCENT').upper()
        downside_activation_price = float(downside_activation_price) if downside_activation_price else None

    total_budget = sum(r['estimated_usd'] for r in all_rungs_data if r['rung_type'] == 'TAKE_PROFIT')
    if total_budget <= 0:
        total_budget = round(qty * current_price, 2)

    # Initial watermarks
    up_stop = None
    if clean_upside_mode == 'TRAILING':
        if clean_side == 'SELL':
            up_stop = current_price * (1.0 - (upside_trail_value / 100.0)) if upside_trail_type == 'PERCENT' else max(0.0, current_price - upside_trail_value)
        else:
            up_stop = current_price * (1.0 + (upside_trail_value / 100.0)) if upside_trail_type == 'PERCENT' else current_price + upside_trail_value

    down_stop = None
    if clean_downside_mode == 'TRAILING':
        if clean_side == 'SELL':
            down_stop = current_price * (1.0 - (downside_trail_value / 100.0)) if downside_trail_type == 'PERCENT' else max(0.0, current_price - downside_trail_value)
        else:
            down_stop = current_price * (1.0 + (downside_trail_value / 100.0)) if downside_trail_type == 'PERCENT' else current_price + downside_trail_value

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
        strategy_type=strategy_type or 'SYNTHETIC',
        upside_mode=clean_upside_mode,
        upside_target_price=upside_target_price,
        upside_trail_value=upside_trail_value,
        upside_trail_type=upside_trail_type,
        upside_activation_price=upside_activation_price,
        upside_highest_price=current_price if clean_upside_mode == 'TRAILING' else None,
        upside_current_stop_price=up_stop,
        downside_mode=clean_downside_mode,
        downside_target_price=sl_price,
        downside_trail_value=downside_trail_value,
        downside_trail_type=downside_trail_type,
        downside_activation_price=downside_activation_price,
        downside_lowest_price=current_price if clean_downside_mode == 'TRAILING' else None,
        downside_current_stop_price=down_stop,
        has_stop_loss=bool(clean_downside_mode != 'NONE'),
        stop_loss_trigger_price=sl_price,
        stop_loss_action=stop_loss_action or 'SELL_ALL',
        status='ACTIVE',
        rungs_total=len(all_rungs_data),
        rungs_filled=0,
        test_mode=bool(test_mode),
        trading_session=clean_session,
        created_at=utc_now(aware=False),
        updated_at=utc_now(aware=False)
    )

    db.session.add(ladder)
    db.session.flush()

    for r in all_rungs_data:
        rung = LadderRung(
            ladder_id=ladder.id,
            rung_number=r['rung_number'],
            rung_type=r.get('rung_type', 'TAKE_PROFIT'),
            target_price=r['target_price'],
            price_offset_pct=r.get('price_offset_pct'),
            quantity=r['quantity'],
            percentage_of_total=r.get('percentage_of_total'),
            estimated_usd=r.get('estimated_usd'),
            status='PENDING'
        )
        db.session.add(rung)

    db.session.commit()
    logger.info(f"Created LadderOrder #{ladder.id} [{clean_broker.upper()}]: {clean_side} {qty} {clean_symbol} [Upside: {clean_upside_mode}, Downside: {clean_downside_mode}] across {len(all_rungs_data)} rungs.")
    return ladder.to_dict()


def cancel_ladder_order(ladder_id, user_id):
    """
    Cancels an active ladder order and all its pending rungs.
    """
    ladder = LadderOrder.query.filter_by(id=ladder_id, user_id=user_id).first()
    if not ladder:
        raise ValueError(f"Ladder order #{ladder_id} not found.")

    if ladder.status in ('COMPLETED', 'CANCELLED', 'STOPPED_OUT'):
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
    Evaluates ladder order and its rungs against market price.
    Supports Mode A (Single), Mode B (Ladder), and Mode C (Trailing) for both Upside and Downside.
    Returns (updated, triggered_count).
    """
    if ladder.status not in ('ACTIVE', 'PARTIALLY_FILLED'):
        return False, 0

    price = float(current_price)
    updated = False
    triggered_count = 0
    downside_mode = (ladder.downside_mode or ('SINGLE' if ladder.has_stop_loss else 'NONE')).upper()
    upside_mode = (ladder.upside_mode or 'LADDER').upper()

    # -------------------------------------------------------------
    # 1. DOWNSIDE EVALUATION (Stop-Loss / Protection)
    # -------------------------------------------------------------
    if downside_mode == 'SINGLE':
        sl_price = ladder.downside_target_price or ladder.stop_loss_trigger_price
        if sl_price:
            triggered = (price <= sl_price) if ladder.side == 'SELL' else (price >= sl_price)
            if triggered:
                logger.info(f"LadderOrder #{ladder.id} DOWNSIDE SINGLE STOP TRIGGERED at price ${price:.4f} <= stop ${sl_price:.4f}")
                pending_rungs = [r for r in ladder.rungs if r.status == 'PENDING']
                remaining_qty = sum(r.quantity for r in pending_rungs) if pending_rungs else ladder.total_quantity

                if remaining_qty > 0 and execute_trigger:
                    _execute_stop_loss_market_sell(ladder, remaining_qty, price)

                for r in pending_rungs:
                    r.status = 'CANCELLED'
                    r.error_message = f"Cancelled due to Stop-Loss trigger at ${price:.4f}"

                ladder.status = 'STOPPED_OUT'
                ladder.updated_at = utc_now(aware=False)
                return True, 1

    elif downside_mode == 'TRAILING':
        trail_val = float(ladder.downside_trail_value or 3.0)
        trail_type = ladder.downside_trail_type or 'PERCENT'
        act_px = ladder.downside_activation_price

        if ladder.side == 'SELL':
            # Ratchet peak watermark
            if ladder.downside_lowest_price is None or price > ladder.downside_lowest_price:
                ladder.downside_lowest_price = price
                new_stop = price * (1.0 - (trail_val / 100.0)) if trail_type == 'PERCENT' else max(0.0, price - trail_val)
                if ladder.downside_current_stop_price is None or new_stop > ladder.downside_current_stop_price:
                    ladder.downside_current_stop_price = new_stop
                    updated = True

            is_active = True
            if act_px and ladder.downside_lowest_price and ladder.downside_lowest_price < act_px:
                is_active = False

            if is_active and ladder.downside_current_stop_price and price <= ladder.downside_current_stop_price:
                logger.info(f"LadderOrder #{ladder.id} DOWNSIDE TRAILING STOP TRIGGERED at ${price:.4f} <= dynamic stop ${ladder.downside_current_stop_price:.4f}")
                pending_rungs = [r for r in ladder.rungs if r.status == 'PENDING']
                remaining_qty = sum(r.quantity for r in pending_rungs) if pending_rungs else ladder.total_quantity

                if remaining_qty > 0 and execute_trigger:
                    _execute_stop_loss_market_sell(ladder, remaining_qty, price)

                for r in pending_rungs:
                    r.status = 'CANCELLED'
                    r.error_message = f"Cancelled due to Trailing Stop trigger at ${price:.4f}"

                ladder.status = 'STOPPED_OUT'
                ladder.updated_at = utc_now(aware=False)
                return True, 1

    elif downside_mode == 'LADDER':
        # Check staged downside stop rungs
        stop_rungs = [r for r in ladder.rungs if getattr(r, 'rung_type', None) == 'STOP_LOSS' and r.status == 'PENDING']
        for rung in stop_rungs:
            triggered = (price <= rung.target_price) if ladder.side == 'SELL' else (price >= rung.target_price)
            if triggered:
                rung.status = 'TRIGGERED'
                updated = True
                triggered_count += 1
                logger.info(f"LadderOrder #{ladder.id} STOP Rung #{rung.rung_number} TRIGGERED at price ${price:.4f} (target: ${rung.target_price:.4f})")
                if execute_trigger:
                    execute_ladder_rung_trigger(ladder, rung, price)

    # -------------------------------------------------------------
    # 2. UPSIDE EVALUATION (Take-Profit / Scale-Out)
    # -------------------------------------------------------------
    if upside_mode == 'SINGLE':
        tgt_px = ladder.upside_target_price
        if tgt_px:
            hit = (price >= tgt_px) if ladder.side == 'SELL' else (price <= tgt_px)
            if hit:
                logger.info(f"LadderOrder #{ladder.id} UPSIDE SINGLE TARGET TRIGGERED at price ${price:.4f} >= target ${tgt_px:.4f}")
                pending_rungs = [r for r in ladder.rungs if r.status == 'PENDING']
                remaining_qty = sum(r.quantity for r in pending_rungs) if pending_rungs else ladder.total_quantity
                if remaining_qty > 0 and execute_trigger:
                    single_rung = pending_rungs[0] if pending_rungs else LadderRung(quantity=remaining_qty, rung_number=1)
                    execute_ladder_rung_trigger(ladder, single_rung, price)
                for r in pending_rungs:
                    r.status = 'FILLED'
                ladder.status = 'COMPLETED'
                ladder.rungs_filled = max(ladder.rungs_total, 1)
                ladder.updated_at = utc_now(aware=False)
                return True, 1

    elif upside_mode == 'TRAILING':
        trail_val = float(ladder.upside_trail_value or 2.0)
        trail_type = ladder.upside_trail_type or 'PERCENT'
        act_px = ladder.upside_activation_price

        if ladder.side == 'SELL':
            # Ratchet peak watermark
            if ladder.upside_highest_price is None or price > ladder.upside_highest_price:
                ladder.upside_highest_price = price
                updated = True

            is_active = True
            if act_px and ladder.upside_highest_price < act_px:
                is_active = False

            if is_active and ladder.upside_highest_price:
                stop_px = ladder.upside_highest_price * (1.0 - (trail_val / 100.0)) if trail_type == 'PERCENT' else max(0.0, ladder.upside_highest_price - trail_val)
                ladder.upside_current_stop_price = stop_px

                if price <= stop_px:
                    logger.info(f"LadderOrder #{ladder.id} UPSIDE TRAILING TAKE-PROFIT TRIGGERED at price ${price:.4f} <= peak pullback ${stop_px:.4f}")
                    pending_rungs = [r for r in ladder.rungs if r.status == 'PENDING']
                    remaining_qty = sum(r.quantity for r in pending_rungs) if pending_rungs else ladder.total_quantity
                    if remaining_qty > 0 and execute_trigger:
                        single_rung = pending_rungs[0] if pending_rungs else LadderRung(quantity=remaining_qty, rung_number=1)
                        execute_ladder_rung_trigger(ladder, single_rung, price)
                    for r in pending_rungs:
                        r.status = 'FILLED'
                    ladder.status = 'COMPLETED'
                    ladder.rungs_filled = max(ladder.rungs_total, 1)
                    ladder.updated_at = utc_now(aware=False)
                    return True, 1

    elif upside_mode == 'LADDER':
        # Check staged upside take-profit rungs
        tp_rungs = [r for r in ladder.rungs if getattr(r, 'rung_type', None) in ('TAKE_PROFIT', None) and r.status == 'PENDING']
        for rung in tp_rungs:
            triggered = (price >= rung.target_price) if ladder.side == 'SELL' else (price <= rung.target_price)
            if triggered:
                rung.status = 'TRIGGERED'
                updated = True
                triggered_count += 1
                logger.info(f"LadderOrder #{ladder.id} TAKE-PROFIT Rung #{rung.rung_number} TRIGGERED at price ${price:.4f} (target: ${rung.target_price:.4f})")
                if execute_trigger:
                    execute_ladder_rung_trigger(ladder, rung, price)

    if updated:
        filled_count = sum(1 for r in ladder.rungs if r.status in ('FILLED', 'TRIGGERED'))
        ladder.rungs_filled = filled_count
        if filled_count >= ladder.rungs_total and ladder.rungs_total > 0:
            ladder.status = 'COMPLETED'
        elif filled_count > 0:
            ladder.status = 'PARTIALLY_FILLED'
        ladder.updated_at = utc_now(aware=False)

    return updated, triggered_count


def execute_ladder_rung_trigger(ladder, rung, current_price):
    """
    Submits a market execution for a triggered ladder rung on Binance.US or Webull.
    Supports Equities, ETFs, and Webull Crypto, as well as Binance.US Crypto spot.
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
        logger.error(f"Error during evaluate_active_ladder_orders cycle: {e}")
