"""One description of a working order for every pending-order reader.

The cached snapshot and the live pending-order endpoint both build their rows
here, so a strategy, a partial fill or an order group is described the same way
wherever the dashboard reads it. Nothing in this module contacts a broker.
"""
import json

QUOTE_SUFFIXES = ('USDT', 'USDC', 'USD')
# Legs of one broker group that cannot all execute: only one of them can spend cash.
EXCLUSIVE_COMBO_TYPES = {'OCO', 'OTOCO', 'STOP_PROFIT', 'STOP_LOSS'}


def base_asset(symbol):
    """'BTCUSDT' -> 'BTC'. Only a known quote suffix is removed."""
    clean = str(symbol or '').strip().upper()
    return next((clean[:-len(quote)] for quote in QUOTE_SUFFIXES if clean.endswith(quote) and len(clean) > len(quote)), clean)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_number(order, keys, positive=False):
    for key in keys:
        if order.get(key) in (None, ''):
            continue
        value = _number(order.get(key))
        if not positive or value > 0:
            return value
    return 0.0


def _outstanding(details, original):
    """Quantity that can still trade: the original amount less confirmed fills."""
    remaining = details.get('remaining_quantity')
    return _number(original) if remaining is None else max(0.0, _number(remaining))


def _child_order_ids(details):
    """Broker and client ids of this strategy's orders that are still open at the broker."""
    from services.synthetic_execution_service import OPEN_EXECUTIONS
    ids = []
    for execution in details.get('executions') or []:
        if execution.get('status') not in OPEN_EXECUTIONS:
            continue
        ids.extend(str(value) for value in (execution.get('broker_order_id'), execution.get('client_order_id')) if value)
    return ids


def conditional_legs(parent):
    """Return (legs that can act in the current phase, legs waiting on the entry)."""
    legs = (json.loads(parent.conditional_spec) or {}).get('legs') or []
    if parent.conditional_phase == 'ENTRY':
        return legs[:1], legs[1:]
    if parent.conditional_phase == 'EXIT':
        return legs[1:], []
    return legs, []


def leg_reserve_price(leg, cap_pct):
    """The most one share of a conditional leg can cost when it executes.

    Limit and stop-limit legs are submitted at their exact entered limit, so
    they never pay more than it. Only a plain stop is sent with the
    extended-hours cap past its trigger, so only a stop reserves that cap.
    """
    if leg.get('order_type') == 'STOP_LOSS':
        return _number(leg.get('stop_price')) * (1 + _number(cap_pct) / 100)
    return _number(leg.get('price') or leg.get('stop_price'))


def _leg_trigger(leg):
    return _number(leg.get('price') if leg.get('order_type') == 'LIMIT' else leg.get('stop_price'))


def _leg_view(leg):
    return {
        'side': leg.get('side'),
        'order_type': leg.get('order_type'),
        'price': leg.get('price'),
        'stop_price': leg.get('stop_price'),
        'trigger_price': _leg_trigger(leg),
    }


def serialize_trailing(order):
    details = order.to_dict()
    symbol = str(order.symbol or '').upper()
    remaining = _outstanding(details, order.quantity)
    stop = order.current_stop_price
    return {
        'order_id': f'trail_{order.id}',
        'symbol': symbol,
        'asset': base_asset(symbol),
        'provider': order.broker or 'binance',
        'source': order.broker or 'binance',
        'side': order.side,
        'type': 'TRAILING_STOP',
        'price': stop,
        'stop_price': stop,
        'trigger_price': stop,
        'highest_price': order.highest_price,
        'lowest_price': order.lowest_price,
        'quantity': remaining,
        'original_quantity': order.quantity,
        'filled_quantity': details.get('filled_quantity'),
        'pending_quantity': details.get('pending_quantity'),
        'quantity_usdt': remaining * _number(stop),
        'trail_type': order.trail_type,
        'trail_value': order.trail_value,
        'status': order.status,
        'account_id': order.account_id,
        'instrument_type': order.instrument_type or 'CRYPTO',
        'direction': 'drops below' if order.side == 'SELL' else 'rises above',
        'synthetic_details': details,
        'child_order_ids': _child_order_ids(details),
        'is_synthetic': True,
        'is_trailing': True,
        'is_activated': order.is_activated,
    }


def serialize_ladder(order):
    details = order.to_dict()
    symbol = str(order.symbol or '').upper()
    remaining = _outstanding(details, order.total_quantity)
    total = _number(order.total_quantity) or 1.0
    entry = {
        'order_id': f'ladder_{order.id}',
        'symbol': symbol,
        'asset': base_asset(symbol),
        'provider': order.broker or 'binance',
        'source': order.broker or 'binance',
        'side': order.side,
        'type': 'LADDER',
        'quantity': remaining,
        'original_quantity': order.total_quantity,
        'filled_quantity': details.get('filled_quantity'),
        'pending_quantity': details.get('pending_quantity'),
        'synthetic_details': details,
        'child_order_ids': _child_order_ids(details),
        'account_id': order.account_id,
        'instrument_type': order.instrument_type or 'CRYPTO',
        'status': order.status,
        'is_synthetic': True,
        'is_ladder': True,
        'preset_name': order.preset_name,
        'strategy_type': order.strategy_type or 'SYNTHETIC',
        'quote_budget': order.quote_budget,
        'budget_remaining': details.get('budget_remaining'),
    }

    if order.conditional_spec:
        # OCO / OTO / OTOCO / single conditional legs: no rungs and no legacy
        # targets, so the prices come from the legs of the current phase.
        active, waiting = conditional_legs(order)
        limit_leg = next((leg for leg in active if leg.get('order_type') == 'LIMIT'), None)
        stop_leg = next((leg for leg in active if leg.get('order_type') != 'LIMIT'), None)
        shown = limit_leg or stop_leg or {}
        trigger = _leg_trigger(shown)
        # Cash is held for the most expensive branch that could execute
        # (a plain stop includes the extended-hours cap), exactly as the engine checks capacity.
        reserve_price = max((leg_reserve_price(leg, order.limit_cap_pct) for leg in active), default=0.0)
        entry.update({
            'price': trigger,
            'trigger_price': trigger,
            'stop_price': _leg_trigger(stop_leg) if stop_leg and stop_leg is not shown else None,
            'quantity_usdt': remaining * (reserve_price if order.side == 'BUY' else trigger),
            'direction': ('rises to' if order.side == 'SELL' else 'drops to') if shown.get('order_type') == 'LIMIT'
                         else ('drops below' if order.side == 'SELL' else 'rises above'),
            'is_conditional': True,
            'conditional_phase': order.conditional_phase,
            'legs': [_leg_view(leg) for leg in active],
            'waiting_legs': [_leg_view(leg) for leg in waiting],
        })
        return entry

    pending_rungs = [rung for rung in order.rungs if rung.status == 'PENDING']
    next_rung = pending_rungs[0] if pending_rungs else None
    target = next_rung.target_price if next_rung else (order.upside_target_price or order.downside_target_price or 0.0)
    if details.get('budget_remaining') is not None:
        budget = _number(details['budget_remaining'])
    elif order.total_budget_usd:
        budget = _number(order.total_budget_usd) * (remaining / total)
    else:
        budget = remaining * _number(target)
    entry.update({
        'price': target,
        'trigger_price': target,
        'quantity_usdt': budget,
        'direction': 'rises to' if order.side == 'SELL' else 'drops to',
        'rungs_total': order.rungs_total,
        'rungs_filled': order.rungs_filled,
        'next_rung_number': next_rung.rung_number if next_rung else None,
        'next_rung_price': target,
        'next_rung_qty': next_rung.quantity if next_rung else None,
        'upside_mode': order.upside_mode or 'LADDER',
        'downside_mode': order.downside_mode or ('SINGLE' if order.has_stop_loss else 'NONE'),
        'upside_target_price': order.upside_target_price,
        'downside_target_price': order.downside_target_price or order.stop_loss_trigger_price,
        'upside_trail_value': order.upside_trail_value,
        'downside_trail_value': order.downside_trail_value,
        'stop_loss_price': order.stop_loss_trigger_price if order.has_stop_loss else None,
    })
    return entry


def working_synthetic_orders(user_id):
    """Every working live synthetic strategy of a user, in the shared pending-order shape."""
    from trading_models import TrailingOrder, LadderOrder
    from services.synthetic_execution_service import WORKING_PARENTS
    # A parked TRIGGERED_NOT_FILLED synthetic is no longer worked by the
    # engine, but it must stay visible wherever working orders are shown:
    # its stop fired and the user has a position decision to make.
    visible = WORKING_PARENTS + ('TRIGGERED_NOT_FILLED',)
    trailing = TrailingOrder.query.filter(
        TrailingOrder.user_id == user_id, TrailingOrder.status.in_(visible), TrailingOrder.test_mode.is_(False),
    ).order_by(TrailingOrder.id.asc()).all()
    ladders = LadderOrder.query.filter(
        LadderOrder.user_id == user_id, LadderOrder.status.in_(visible), LadderOrder.test_mode.is_(False),
    ).order_by(LadderOrder.id.asc()).all()
    return [serialize_trailing(order) for order in trailing] + [serialize_ladder(order) for order in ladders]


def format_binance_open_order(order):
    """Describe a Binance.US open order by what is still unfilled."""
    symbol = str(order.get('symbol') or '').upper()
    side = str(order.get('side') or '').upper()
    price = _number(order.get('price'))
    stop_price = _number(order.get('stopPrice')) or None
    original = _number(order.get('origQty'))
    filled = _number(order.get('executedQty'))
    quantity = max(0.0, original - filled)
    trigger = stop_price or price
    if side == 'SELL':
        direction = 'drops below' if stop_price else 'rises above'
    else:
        direction = 'rises above' if stop_price else 'drops below'
    list_id = order.get('orderListId', -1)
    grouped = list_id not in (None, -1, '-1')
    return {
        'order_id': order.get('orderId'),
        'client_order_id': order.get('clientOrderId') or None,
        'symbol': symbol,
        'asset': base_asset(symbol),
        'provider': 'binance',
        'source': 'binance',
        'side': side,
        'type': order.get('type', 'LIMIT'),
        'price': price,
        'stop_price': stop_price,
        'quantity': quantity,
        'original_quantity': original,
        'filled_quantity': filled,
        'status': 'ACTIVE' if order.get('status') in ['NEW', 'PARTIALLY_FILLED', 'ACTIVE'] else order.get('status'),
        'time': order.get('time'),
        'is_oco': grouped or bool(order.get('type') == 'STOP_LOSS_LIMIT' and order.get('stopPrice') and order.get('price')),
        'direction': direction,
        'trigger_price': trigger,
        'quantity_usdt': quantity * (trigger or 0.0),
        'orderListId': list_id if list_id is not None else -1,
        'group_id': f'binance-list-{list_id}' if grouped else None,
        'group_role': 'exclusive' if grouped else None,
    }


def webull_group(order):
    """Return (group id, role) for a Webull order that belongs to a combo order.

    Legs that are alternatives to each other (OCO pairs, bracket exits) are
    'exclusive'; an entry or an independently triggered leg is 'independent'.
    """
    combo_type = str(order.get('combo_type') or 'NORMAL').strip().upper()
    group_id = next((str(order.get(key)).strip() for key in ('_webull_group_id', 'client_combo_order_id', 'combo_order_id')
                     if order.get(key) not in (None, '')), '')
    if not group_id or (combo_type == 'NORMAL' and not order.get('_webull_group_id')):
        return None, None
    return f'webull-combo-{group_id}', 'exclusive' if combo_type in EXCLUSIVE_COMBO_TYPES else 'independent'


def format_webull_open_order(order, open_statuses=None):
    """Describe a Webull open order by what is still unfilled, or None if it is not open."""
    if not isinstance(order, dict):
        return None
    symbol = str(order.get('symbol') or order.get('ticker') or '').strip().upper()
    if not symbol:
        return None
    status = str(order.get('status') or order.get('order_status') or '').strip().upper()
    if status and open_statuses is not None and status not in open_statuses:
        return None
    side = str(order.get('side') or '').strip().upper()
    price = _first_number(order, ('limit_price', 'price', 'order_price', 'limitPrice', 'orderPrice'), positive=True)
    stop_price = _number(order.get('stop_price') or order.get('stopPrice'))
    total = _first_number(order, ('total_quantity', 'quantity', 'order_quantity', 'order_qty', 'qty'))
    filled = _first_number(order, ('filled_quantity', 'executed_quantity', 'filled_qty'))
    quantity = max(0.0, total - filled)
    trigger = stop_price or price
    if side == 'SELL':
        direction = 'drops below' if stop_price else 'rises above'
    else:
        direction = 'rises above' if stop_price else 'drops below'
    group_id, group_role = webull_group(order)
    combo_type = str(order.get('combo_type') or 'NORMAL').strip().upper()
    return {
        'order_id': str(order.get('order_id') or order.get('orderId') or order.get('id') or ''),
        'client_order_id': str(order.get('client_order_id') or order.get('clientOrderId') or '').strip() or None,
        'symbol': symbol,
        'asset': symbol,
        'provider': 'webull',
        'source': 'webull',
        'side': side,
        'type': str(order.get('order_type') or order.get('type') or 'LIMIT').strip().upper(),
        'price': price,
        'stop_price': stop_price or None,
        'quantity': quantity,
        'original_quantity': total,
        'filled_quantity': filled,
        'status': status or 'ACTIVE',
        'time': order.get('created_at') or order.get('create_time'),
        'is_oco': group_role == 'exclusive',
        'combo_type': combo_type,
        'group_id': group_id,
        'group_role': group_role,
        'direction': direction,
        'trigger_price': trigger,
        'quantity_usdt': quantity * (trigger or price),
        'account_id': str(order.get('_webull_account_id') or order.get('account_id') or ''),
        'instrument_type': order.get('instrument_type') or '',
    }


def link_synthetic_children(pending_orders):
    """Mark broker orders that were submitted by a synthetic strategy in the same list.

    The link comes from the strategy's execution journal (broker and client
    order ids), never from a resemblance in symbol, size or price. A linked
    broker order and its strategy describe the same shares, so cash is held for
    them once.
    """
    parents = {}
    for order in pending_orders:
        for child_id in order.get('child_order_ids') or []:
            parents[(str(order.get('provider') or 'binance').lower(), str(child_id))] = order.get('order_id')
    if not parents:
        return pending_orders
    for order in pending_orders:
        if order.get('is_synthetic'):
            continue
        provider = str(order.get('provider') or 'binance').lower()
        for own_id in (order.get('order_id'), order.get('client_order_id')):
            parent_id = parents.get((provider, str(own_id))) if own_id not in (None, '') else None
            if parent_id:
                order['synthetic_parent_id'] = parent_id
                break
    return pending_orders
