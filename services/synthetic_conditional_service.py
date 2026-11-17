"""App-managed stock/ETF conditional legs, journaled before transmission.

OTO children activate only after the entry has a confirmed terminal state. A
partially filled, cancelled entry activates exits for the confirmed shares only.
"""
import json
from core.extensions import db
from trading_models import LadderOrder
from services import synthetic_execution_service as ex


def validate_legs(kind, legs, quantity):
    counts = {'OCO': 2, 'OTO': 2, 'OTOCO': 3, 'LIMIT': 1, 'STOP': 1}
    if kind not in counts or not isinstance(legs, list) or len(legs) != counts[kind]:
        raise ValueError('Choose LIMIT, STOP, OCO, OTO or OTOCO with the required legs.')
    clean = []
    for i, leg in enumerate(legs):
        side = str(leg.get('side', '')).upper()
        order_type = str(leg.get('order_type', '')).upper()
        if side not in {'BUY', 'SELL'} or order_type not in {'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
            raise ValueError(f'Leg {i + 1}: choose Buy/Sell and Limit, Stop or Stop Limit.')
        if float(leg.get('quantity', quantity)) != quantity:
            raise ValueError('All conditional legs must use the same shared quantity.')
        clean.append(dict(side=side, order_type=order_type,
                          price=ex.positive(leg.get('price'), 'Limit price') if order_type != 'STOP_LOSS' else None,
                          stop_price=ex.positive(leg.get('stop_price', leg.get('stopPrice')), 'Stop price') if order_type != 'LIMIT' else None))
    linked = clean if kind == 'OCO' else clean[1:] if kind == 'OTOCO' else []
    if linked:
        if linked[0]['side'] != linked[1]['side'] or linked[0] == linked[1]:
            raise ValueError('OCO legs must have the same side and different triggers.')
        if {x['order_type'] == 'LIMIT' for x in linked} != {True, False}:
            raise ValueError('Use one Limit leg and one Stop or Stop Limit leg for OCO.')
        limit = next(x['price'] for x in linked if x['order_type'] == 'LIMIT')
        stop = next(x['stop_price'] for x in linked if x['order_type'] != 'LIMIT')
        if (linked[0]['side'] == 'BUY' and limit >= stop) or (linked[0]['side'] == 'SELL' and limit <= stop):
            raise ValueError('The OCO limit and stop must define separate dip/profit and breakout/protection triggers.')
    if kind in {'OTO', 'OTOCO'} and any(x['side'] == clean[0]['side'] for x in clean[1:]):
        raise ValueError('OTO children must reverse the entry side. Short entries are not supported.')
    return clean


def create_conditional(user_id, data, commit=True):
    kind = str(data.get('strategy_type', 'OCO')).upper()
    qty = ex.positive(data.get('total_quantity'), 'Quantity')
    symbol, side, broker, instrument, session, account = ex.validate_identity(
        data.get('symbol'), data.get('side'), data.get('broker', 'webull'), data.get('instrument_type', 'EQUITY'),
        data.get('trading_session', 'ALL'), data.get('account_id'), bool(data.get('test_mode')))
    if broker != 'webull' or instrument not in {'EQUITY', 'ETF'}:
        raise ValueError('Synthetic conditional legs support Webull stocks and ETFs.')
    ex.require_whole_shares(qty, session, instrument)
    legs = validate_legs(kind, data.get('legs'), qty)
    if legs[0]['side'] != side:
        raise ValueError('Order side must match the first leg.')
    parent = LadderOrder(user_id=user_id, broker=broker, account_id=account, symbol=symbol, side=side,
                         instrument_type=instrument, total_quantity=qty, strategy_type=kind,
                         conditional_spec=json.dumps({'legs': legs, 'requested_quantity': qty}),
                         conditional_phase='ENTRY' if kind in {'OTO', 'OTOCO'} else 'SINGLE',
                         upside_mode='NONE', downside_mode='NONE', trading_session=session,
                         limit_cap_pct=ex.limit_cap(data.get('limit_cap_pct'), session), test_mode=bool(data.get('test_mode')),
                         activate_at=ex.parse_activate_at(data.get('activate_at')),
                         status='ACTIVE', engine_version=2, environment=ex.environment_for(user_id, broker))
    rules = ex.quantity_rules(parent)
    if ex.normalize_quantity(qty, rules) != qty:
        raise ValueError('Quantity does not match the broker share increment.')
    db.session.add(parent)
    db.session.flush()
    if commit:
        db.session.commit()
    return parent


def phase_rows(parent, rows):
    if parent.conditional_phase == 'ENTRY':
        return [r for r in rows if r.leg == 'ENTRY']
    if parent.conditional_phase == 'EXIT':
        return [r for r in rows if r.leg != 'ENTRY']
    return rows


def sync(parent, rows):
    relevant = phase_rows(parent, rows)
    if any(r.status in ex.OPEN_EXECUTIONS for r in rows):
        parent.status = 'CANCEL_PENDING' if parent.cancel_requested else 'SUBMITTED'
        return
    filled = sum(r.filled_quantity or 0 for r in relevant)
    if parent.cancel_requested:
        parent.status = 'CANCELLED'
    elif parent.conditional_phase == 'ENTRY' and relevant and filled > 0:
        # Final broker confirmation is required before sizing/arming any exits.
        spec = json.loads(parent.conditional_spec)
        spec['entry_filled_quantity'] = filled
        spec['entry_remainder_cancelled'] = max(0, parent.total_quantity - filled)
        parent.conditional_spec = json.dumps(spec)
        parent.conditional_phase = 'EXIT'
        parent.total_quantity = filled
        parent.side = spec['legs'][1]['side']
        parent.status = 'ACTIVE'
        parent.monitoring_error = None
    elif filled >= parent.total_quantity - 1e-10:
        parent.status = 'COMPLETED'
    elif relevant:
        parent.status = 'FAILED'
        parent.monitoring_error = relevant[-1].error_message or 'Execution ended before the requested quantity filled.'


def evaluate(parent, price):
    spec = json.loads(parent.conditional_spec)
    legs = spec['legs']
    if parent.conditional_phase == 'ENTRY':
        candidates = [(0, legs[0])]
    elif parent.conditional_phase == 'EXIT':
        candidates = list(enumerate(legs[1:], 1))
    else:
        candidates = list(enumerate(legs))
    for index, leg in candidates:
        target = leg['price'] if leg['order_type'] == 'LIMIT' else leg['stop_price']
        upward = (leg['side'] == 'SELL') if leg['order_type'] == 'LIMIT' else (leg['side'] == 'BUY')
        if not (price >= target if upward else price <= target):
            continue
        # Exact entered limits are preserved. Plain stops use the configured cap
        # in extended hours, and market execution in regular hours.
        limit = leg['price'] if leg['order_type'] != 'STOP_LOSS' else None
        try:
            ex.submit_execution(parent, 'LADDER', parent.total_quantity, price,
                                'ENTRY' if parent.conditional_phase == 'ENTRY' else f'EXIT_{index}',
                                explicit_limit=limit, trigger_price=target)
            sync(parent, ex.executions(parent, 'LADDER'))
        except Exception as exc:
            parent.status, parent.monitoring_error = 'FAILED', str(exc)
        return
