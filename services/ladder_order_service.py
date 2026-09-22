"""
Ladder & Synthetic Bracket Order Service
Provides synthetic server-side smart order creation, template configuration,
price monitoring, progressive rung execution, trailing take-profit/stop-loss,
and lifecycle management for both Binance.US (Crypto) and Webull (Equities, ETFs, and Crypto).
"""

import time
from decimal import Decimal
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
from services import synthetic_execution_service as execution


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
            preset = str(preset_name).title() if str(preset_name).title() in templates else 'Moderate'
            specs = templates.get(preset, templates.get('Moderate', []))
        else:
            templates = PRESET_TEMPLATES.get(clean_side, {})
            preset = str(preset_name).title() if str(preset_name).title() in templates else 'Conservative'
            specs = templates.get(preset, templates.get('Conservative', []))

    if not specs or len(specs) > 10:
        raise ValueError('Use between 1 and 10 rungs per ladder.')
    allocations = [execution.positive(r.get('pct_of_total', r.get('percentage_of_total')), 'Rung allocation') for r in specs]
    if abs(sum(allocations) - 100) > 0.01:
        raise ValueError('Each ladder must allocate exactly 100% of the shared quantity.')
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
            target_px = float(Decimal(str(ref_price)) * (1 + Decimal(str(offset_pct)) / 100))

        # Determine quantity
        if i == len(specs) - 1:
            qty = round(remaining_qty, 8)
            pct_total = round((qty / total_qty) * 100.0, 2) if total_qty > 0 else 0
        else:
            pct_total = float(spec.get('pct_of_total', spec.get('percentage_of_total', 100.0 / max(len(specs), 1))))
            qty = round(total_qty * (pct_total / 100.0), 8)
            remaining_qty -= qty

        execution.positive(target_px, 'Rung target')
        execution.positive(qty, 'Rung quantity')
        favorable = target_px > ref_price if clean_side == 'SELL' else target_px < ref_price
        if favorable != (rung_type == 'TAKE_PROFIT') or target_px == ref_price:
            raise ValueError('Rung targets must be on the correct side of the current price.')
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
    clean_symbol, clean_side, clean_broker, clean_instrument, clean_session, clean_account_id = execution.validate_identity(
        symbol, side, broker, instrument_type, trading_session, account_id, test_mode)
    symbol, side, broker, instrument_type, trading_session, account_id = (clean_symbol, clean_side, clean_broker, clean_instrument, clean_session, clean_account_id)
    clean_symbol = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_broker = str(broker or 'binance').strip().lower()
    clean_instrument = str(instrument_type or 'CRYPTO').strip().upper()
    clean_session = str(trading_session or 'CORE').strip().upper()
    clean_account_id = str(account_id).strip() if account_id else None

    clean_upside_mode = str(upside_mode or 'LADDER').strip().upper()
    clean_downside_mode = str(downside_mode or 'NONE').strip().upper()

    if clean_upside_mode not in {'SINGLE', 'LADDER', 'TRAILING'} or clean_downside_mode not in {'NONE', 'SINGLE', 'LADDER', 'TRAILING'}:
        raise ValueError('Choose a supported upside and downside mode.')

    if clean_side not in ('BUY', 'SELL'):
        raise ValueError("Order side must be BUY or SELL.")

    try:
        qty = execution.positive(total_quantity, 'Total quantity')
        if qty <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Total quantity must be a positive number.")

    current_price = _get_reference_price(clean_symbol, client=client, broker=clean_broker, instrument_type=clean_instrument, user_id=user_id)
    if not current_price or current_price <= 0:
        raise ValueError(f"Unable to determine current market price for {clean_symbol}.")

    if has_stop_loss and clean_downside_mode == 'NONE':
        clean_downside_mode = 'SINGLE'

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

    if clean_downside_mode == 'SINGLE':
        sl_price = execution.positive(downside_target_price or stop_loss_trigger_price, 'Stop price')
        if (sl_price >= current_price if clean_side == 'SELL' else sl_price <= current_price):
            raise ValueError('The protection stop must be on the adverse side of the current price.')
    if stop_loss_action not in {'SELL_ALL', 'SELL_REMAINDER', 'MARKET_SELL_ALL', 'CANCEL_REMAINING'}:
        raise ValueError('Choose market execution or cancel remaining orders for the stop action.')

    # Build rungs list
    all_rungs_data = []

    # 1. Upside rungs (Take Profit)
    if clean_upside_mode == 'LADDER':
        upside_rungs_data = calculate_ladder_rungs(clean_side, current_price, qty, preset_name=preset_name, custom_rungs=custom_rungs, rung_type='TAKE_PROFIT')
        all_rungs_data.extend(upside_rungs_data)
    elif clean_upside_mode == 'SINGLE':
        tgt_px = execution.positive(upside_target_price, 'Target price')
        if (tgt_px <= current_price if clean_side == 'SELL' else tgt_px >= current_price):
            raise ValueError('The target must be on the favorable side of the current price.')
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
        upside_trail_value, upside_trail_type = execution.trailing_parameters(upside_trail_value, upside_trail_type)
        upside_activation_price = execution.positive(upside_activation_price, 'Activation price', optional=True)

    # 2. Downside rungs (Stop Loss)
    if clean_downside_mode == 'LADDER':
        downside_rungs_data = calculate_ladder_rungs(clean_side, current_price, qty, preset_name=downside_preset, custom_rungs=downside_rungs, rung_type='STOP_LOSS')
        # Assign contiguous rung numbers
        start_num = len(all_rungs_data) + 1
        for idx, r in enumerate(downside_rungs_data):
            r['rung_number'] = start_num + idx
            all_rungs_data.append(r)
    elif clean_downside_mode == 'TRAILING':
        downside_trail_value, downside_trail_type = execution.trailing_parameters(downside_trail_value, downside_trail_type)
        downside_activation_price = execution.positive(downside_activation_price, 'Activation price', optional=True)

    for mode, kind, value, activation in (
        (clean_upside_mode, upside_trail_type, upside_trail_value, upside_activation_price),
        (clean_downside_mode, downside_trail_type, downside_trail_value, downside_activation_price),
    ):
        if mode == 'TRAILING' and clean_side == 'SELL' and kind == 'AMOUNT' and value >= max(current_price, activation or 0):
            raise ValueError('The sell trail amount must be below the price at activation.')

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

    ladder.engine_version = 2
    ladder.environment = execution.environment_for(user_id, clean_broker)
    rules = execution.quantity_rules(ladder)
    normalized = execution.normalize_quantity(qty, rules)
    if abs(normalized - qty) > max(1e-14, qty * 1e-12):
        raise ValueError(f'Total quantity must be a multiple of {rules["step"]}.')
    execution.check_quantity(ladder, qty, current_price, rules)
    execution.check_order_limit(ladder, qty, current_price, rules)
    for kind in ('TAKE_PROFIT', 'STOP_LOSS'):
        group = [r for r in all_rungs_data if r['rung_type'] == kind]
        allocated = 0
        for idx, r in enumerate(group):
            r['quantity'] = execution.normalize_quantity(round(qty - allocated, 8) if idx == len(group) - 1 else r['quantity'], rules)
            execution.check_quantity(ladder, r['quantity'], r['target_price'], rules)
            allocated = round(allocated + r['quantity'], 8)
            r['estimated_usd'] = r['quantity'] * r['target_price']
            r['percentage_of_total'] = 100 * r['quantity'] / qty
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
    return execution.cancel_parent(LadderOrder, 'LADDER', ladder_id, user_id)


def get_user_ladder_orders(user_id, symbol=None, status=None, broker=None, account_id=None, test_mode=None):
    query = LadderOrder.query.filter_by(user_id=user_id)
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
    return [order.to_dict() for order in query.order_by(LadderOrder.created_at.desc()).all()]


def _sync_parent(ladder, rows):
    by_rung = {r.rung_id: r for r in rows if r.rung_id}
    for rung in ladder.rungs:
        row = by_rung.get(rung.id)
        if row:
            rung.status = row.status
            rung.executed_order_id = row.broker_order_id
            rung.executed_price = row.filled_price
            rung.executed_at = row.updated_at if row.status == 'FILLED' else None
            rung.error_message = row.error_message
    ladder.rungs_filled = sum(r.status == 'FILLED' for r in ladder.rungs)
    filled = sum(float(r.filled_quantity or 0) for r in rows)
    pending = any(r.status in execution.OPEN_EXECUTIONS for r in rows)
    if pending:
        ladder.status = 'CANCEL_PENDING' if ladder.cancel_requested else 'SUBMITTED'
    elif filled >= ladder.total_quantity - 1e-10:
        ladder.status = 'STOPPED_OUT' if rows and rows[-1].leg == 'STOP_LOSS' else 'COMPLETED'
    elif ladder.cancel_requested:
        ladder.status = 'CANCELLED'
    elif any(r.status in {'FAILED', 'CANCELLED'} for r in rows):
        ladder.status = 'FAILED'
        ladder.monitoring_error = 'An execution was rejected or cancelled before the strategy finished. Review fills before creating a replacement.'
    elif filled > 0:
        ladder.status = 'PARTIALLY_FILLED'
    if ladder.status in {'COMPLETED', 'STOPPED_OUT', 'CANCELLED', 'FAILED'}:
        for rung in ladder.rungs:
            if rung.status == 'PENDING':
                rung.status = 'CANCELLED'
    return filled, pending


def _trailing_hit(ladder, prefix, price):
    value, kind = execution.trailing_parameters(getattr(ladder, f'{prefix}_trail_value'), getattr(ladder, f'{prefix}_trail_type'))
    watermark_field = 'upside_highest_price' if prefix == 'upside' else 'downside_lowest_price'
    previous = getattr(ladder, watermark_field)
    watermark = price if previous is None else (max(previous, price) if ladder.side == 'SELL' else min(previous, price))
    setattr(ladder, watermark_field, watermark)
    from services.trailing_order_service import calculate_trailing_stop_price
    stop = calculate_trailing_stop_price(ladder.side, watermark, kind, value)
    setattr(ladder, f'{prefix}_current_stop_price', stop)
    hurdle = getattr(ladder, f'{prefix}_activation_price')
    activated = not hurdle or (watermark >= hurdle if ladder.side == 'SELL' else watermark <= hurdle)
    return activated and (price <= stop if ladder.side == 'SELL' else price >= stop)


def evaluate_single_ladder_order(ladder, current_price, execute_trigger=True):
    if ladder.status not in execution.WORKING_PARENTS:
        return False, 0
    price = execution.positive(current_price, 'Current price')
    rows = execution.executions(ladder, 'LADDER')
    filled, pending = _sync_parent(ladder, rows)
    if pending or ladder.cancel_requested or ladder.status not in {'ACTIVE', 'PARTIALLY_FILLED'}:
        return True, 0
    remaining = max(0, ladder.total_quantity - filled)
    downside = ladder.downside_mode or ('SINGLE' if ladder.has_stop_loss else 'NONE')
    # Preserve legacy safety stops whose migration supplied a default NONE mode.
    if downside == 'NONE' and ladder.has_stop_loss and ladder.stop_loss_trigger_price:
        downside = 'SINGLE'
    upside = ladder.upside_mode or 'LADDER'
    updated, count = False, 0
    for prefix, mode, leg in (('downside', downside, 'STOP_LOSS'), ('upside', upside, 'TAKE_PROFIT')):
        candidates = []
        if mode == 'TRAILING':
            hit = _trailing_hit(ladder, prefix, price)
            updated = True
            if hit:
                candidates = [None]
        elif mode == 'SINGLE':
            target = getattr(ladder, f'{prefix}_target_price') or (ladder.stop_loss_trigger_price if prefix == 'downside' else None)
            favorable = (price >= target if ladder.side == 'SELL' else price <= target) if target else False
            hit = bool(target) and (favorable if prefix == 'upside' else (price <= target if ladder.side == 'SELL' else price >= target))
            if hit:
                candidates = [next((r for r in ladder.rungs if (r.rung_type or 'TAKE_PROFIT') == leg and r.status == 'PENDING'), None)]
        elif mode == 'LADDER':
            for rung in ladder.rungs:
                if rung.status != 'PENDING' or (rung.rung_type or 'TAKE_PROFIT') != leg:
                    continue
                hit = (price >= rung.target_price if ladder.side == 'SELL' else price <= rung.target_price) if prefix == 'upside' else (price <= rung.target_price if ladder.side == 'SELL' else price >= rung.target_price)
                if hit:
                    candidates.append(rung)
        for rung in candidates:
            if prefix == 'downside' and mode == 'SINGLE' and ladder.stop_loss_action == 'CANCEL_REMAINING':
                ladder.cancel_requested = True
                _sync_parent(ladder, rows)
                return True, 1
            qty = min(remaining, rung.quantity) if rung is not None and mode == 'LADDER' else remaining
            if qty <= 1e-10:
                break
            updated, count = True, count + 1
            if not execute_trigger:
                if rung is not None:
                    rung.status = 'TRIGGERED'
                continue
            try:
                row = execution.submit_execution(ladder, 'LADDER', qty, price, leg, rung=rung)
                rows.append(row)
            except Exception as exc:
                ladder.status = 'FAILED'
                ladder.monitoring_error = str(exc)
                if rung is not None:
                    rung.status, rung.error_message = 'FAILED', str(exc)
                return True, count
            filled, pending = _sync_parent(ladder, rows)
            remaining = max(0, ladder.total_quantity - filled)
            if pending or ladder.status not in {'ACTIVE', 'PARTIALLY_FILLED'}:
                return True, count
            # A single/trailing branch owns the whole remaining quantity.
            if mode != 'LADDER':
                return True, count
    if updated:
        ladder.updated_at = utc_now(aware=False)
    return updated, count


def execute_ladder_rung_trigger(ladder, rung, current_price):
    """Compatibility entry point; worker evaluation owns the parent lock."""
    rows = execution.executions(ladder, 'LADDER')
    filled, pending = _sync_parent(ladder, rows)
    if pending or any(r.rung_id == rung.id for r in rows if rung.id):
        return
    row = execution.submit_execution(ladder, 'LADDER', min(rung.quantity, max(0, ladder.total_quantity - filled)), current_price,
                                     rung.rung_type or 'TAKE_PROFIT', rung=rung)
    _sync_parent(ladder, rows + [row])


def evaluate_active_ladder_orders():
    ids = [row.id for row in LadderOrder.query.filter(LadderOrder.status.in_(execution.WORKING_PARENTS)).all()]
    db.session.rollback()
    for identifier in ids:
        try:
            with execution.parent_lock('LADDER', identifier) as locked:
                if not locked:
                    continue
                ladder = db.session.get(LadderOrder, identifier, populate_existing=True)
                if ladder.status not in execution.WORKING_PARENTS:
                    continue
                if ladder.engine_version != 2:
                    ladder.status = 'NEEDS_REVIEW'
                    ladder.monitoring_error = 'Created before v3.9.0: cancel and recreate after reviewing broker fills and the saved strategy. Earlier tickets could save different settings.'
                    db.session.commit()
                    continue
                rows = execution.reconcile_executions(ladder, 'LADDER')
                _sync_parent(ladder, rows)
                if ladder.status in {'ACTIVE', 'PARTIALLY_FILLED'} and not ladder.cancel_requested:
                    if execution.market_is_open(ladder):
                        try:
                            price = _get_reference_price(ladder.symbol, broker=ladder.broker, instrument_type=ladder.instrument_type,
                                                         user_id=ladder.user_id, environment=ladder.environment)
                            ladder.last_price, ladder.last_checked_at, ladder.monitoring_error = price, utc_now(aware=False), None
                            evaluate_single_ladder_order(ladder, price)
                        except Exception:
                            ladder.monitoring_error = 'Current venue quote unavailable or stale. Waiting for a fresh quote.'
                    else:
                        ladder.monitoring_error = 'Waiting for regular market hours; stock/ETF market orders execute only during CORE.'
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Synthetic ladder evaluation failed for order %s', identifier)
        finally:
            db.session.remove()


def ladder_order_worker_loop(app):
    while True:
        try:
            with app.app_context():
                evaluate_active_ladder_orders()
        except Exception:
            logger.exception('Synthetic ladder worker cycle failed')
        time.sleep(2.0)
