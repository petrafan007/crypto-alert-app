"""App-managed stock/ETF conditional legs, journaled before transmission.

OTO children activate only after the entry has a confirmed terminal state. A
partially filled, cancelled entry activates exits for the confirmed shares only.
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from core.extensions import db
from core.time_utils import utc_now
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
    guardian = resolve_guardian(user_id, data, kind=kind, legs=legs, symbol=symbol, side=side,
                                account=account, quantity=qty)
    spec = {'legs': legs, 'requested_quantity': qty}
    if guardian is not None:
        spec['guardian'] = guardian
    parent = LadderOrder(user_id=user_id, broker=broker, account_id=account, symbol=symbol, side=side,
                         instrument_type=instrument, total_quantity=qty, strategy_type=kind,
                         conditional_spec=json.dumps(spec),
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
    elif (parent.strategy_type == 'LIMIT' and parent.conditional_phase == 'SINGLE' and relevant
          and filled <= 0 and all(r.status in {'CANCELLED', 'FAILED'} for r in relevant)
          and sum(1 for r in rows if r.status == 'FAILED' and not (r.filled_quantity or 0)) < MAX_REPLACEMENT_REJECTIONS):
        # A plain synthetic Limit whose child was cancelled (or rejected)
        # before filling has not finished: return to watching so the next
        # cycle places the order again. This is what lets a Limit order
        # survive an IPO halt, where Webull cancels resting orders before
        # the symbol has ever traded. Partial fills keep the FAILED path.
        parent.status = 'ACTIVE'
        parent.monitoring_error = REWATCH_MESSAGE
    elif relevant:
        parent.status = 'FAILED'
        parent.monitoring_error = relevant[-1].error_message or 'Execution ended before the requested quantity filled.'


def evaluate(parent, price):
    spec = json.loads(parent.conditional_spec)
    if parent.strategy_type == 'LIMIT' and parent.conditional_phase == 'SINGLE':
        attempts = [r for r in ex.executions(parent, 'LADDER')
                    if r.status in {'CANCELLED', 'FAILED'} and not (r.filled_quantity or 0)]
        if attempts and attempts[-1].updated_at is not None and (
                utc_now(aware=False) - attempts[-1].updated_at).total_seconds() < REPLACEMENT_MIN_INTERVAL_SECONDS:
            return
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
        leg_name = 'ENTRY' if parent.conditional_phase == 'ENTRY' else f'EXIT_{index}'
        if leg['order_type'] in {'STOP_LOSS', 'STOP_LOSS_LIMIT'} and _stop_attempts_exhausted(parent, leg_name):
            # The stop already triggered and failed to fill repeatedly this
            # session. Park it in a visible state instead of placing broker
            # orders forever; the user can cancel or replace it.
            parent.status = 'TRIGGERED_NOT_FILLED'
            parent.monitoring_error = TRIGGERED_NOT_FILLED_MESSAGE
            return
        # Exact entered limits are preserved. Plain stops use the configured cap
        # in extended hours, and market execution in regular hours. A stop-limit
        # whose price has already gapped through its limit can never fill at
        # that limit, so in regular hours it executes like a plain stop
        # instead: the protection the user asked for is the exit, not the band
        # between stop and limit. Extended hours have no market orders, so
        # there the entered limit still stands (and the attempt cap above
        # parks the stop visibly if it keeps not filling).
        limit = leg['price'] if leg['order_type'] != 'STOP_LOSS' else None
        if (leg['order_type'] == 'STOP_LOSS_LIMIT' and _through_limit(leg, price)
                and ex.session_phase(parent) != 'EXTENDED'):
            limit = None
        try:
            ex.submit_execution(parent, 'LADDER', parent.total_quantity, price,
                                leg_name,
                                explicit_limit=limit, trigger_price=target)
            sync(parent, ex.executions(parent, 'LADDER'))
        except Exception as exc:
            parent.status, parent.monitoring_error = 'FAILED', str(exc)
        return


# ---------------------------------------------------------------------------
# Guardian (backstop) mode for a plain synthetic Limit, plus the re-watch
# behaviour that lets a synthetic Limit survive broker cancellations.
#
# A Limit synthetic may link an existing native Webull order. While that
# order is working, the synthetic places nothing. If it ends cancelled or
# rejected with no fill, the synthetic takes over and places the order from
# its own leg spec; if it fills, the synthetic completes having placed
# nothing; a partial fill stops the synthetic for review.
# ---------------------------------------------------------------------------
GUARDIAN_LIVE_STATES = {'SUBMITTED', 'WORKING', 'PENDING', 'NEW', 'ACCEPTED', 'QUEUED',
                        'PENDING_NEW', 'PARTIALLY_FILLED'}
GUARDIAN_DEAD_STATES = {'CANCELLED', 'CANCELED', 'REJECTED', 'FAILED', 'EXPIRED'}
REWATCH_MESSAGE = ('The Webull order was cancelled before it filled; '
                   'watching to place it again.')
REPLACEMENT_MIN_INTERVAL_SECONDS = 30
MAX_REPLACEMENT_REJECTIONS = 3
MAX_STOP_ATTEMPTS_PER_SESSION = 3
TRIGGERED_NOT_FILLED_MESSAGE = ('Stop triggered, but the order did not fill after '
                                f'{MAX_STOP_ATTEMPTS_PER_SESSION} attempts this session, so it is parked '
                                'instead of placing more orders. Review the position and cancel or '
                                'replace this synthetic if you still want the execution.')


def _through_limit(leg, price):
    """True when the market is already past a stop-limit leg's limit price."""
    limit = leg.get('price')
    if limit is None:
        return False
    return price < limit if leg['side'] == 'SELL' else price > limit


def _session_start_utc():
    """Naive UTC instant of the current Eastern session day's start."""
    start = datetime.now(ZoneInfo('America/New_York')).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def _stop_attempts_exhausted(parent, leg_name):
    """Whether this stop leg already used up its submissions for the session."""
    start = _session_start_utc()
    attempts = [r for r in ex.executions(parent, 'LADDER')
                if r.leg == leg_name and r.status in {'CANCELLED', 'FAILED'}
                and not (r.filled_quantity or 0)
                and r.created_at is not None and r.created_at >= start]
    return len(attempts) >= MAX_STOP_ATTEMPTS_PER_SESSION


def resolve_guardian(user_id, data, *, kind, legs, symbol, side, account, quantity):
    """Validate an optional backstop link to an existing native Webull order.

    Returns the guardian dict stored in the conditional spec, or None when
    the create request carries no link reference. The reference may be the
    dashboard's numeric webull_orders id or the Webull provider order id.
    """
    ref = data.get('guardian_order_ref') or data.get('guardian_order_id') or data.get('guardian_provider_order_id')
    if ref is None or (isinstance(ref, str) and not ref.strip()):
        return None
    if kind != 'LIMIT' or legs[0]['order_type'] != 'LIMIT':
        raise ValueError('A backstop link is only available for a synthetic Limit order.')
    if data.get('test_mode'):
        raise ValueError('A backstop link requires a live synthetic order.')
    from models import WebullOrder
    ref = str(ref).strip()
    row = None
    if ref.isdigit():
        row = WebullOrder.query.filter_by(id=int(ref), user_id=user_id).first()
    if row is None:
        matches = WebullOrder.query.filter_by(user_id=user_id, provider_order_id=ref).all()
        row = next((m for m in matches if m.account_id == account),
                   matches[0] if len(matches) == 1 else None)
        if row is None and matches:
            raise ValueError('The linked Webull order belongs to a different account.')
    if row is None:
        raise ValueError('The linked Webull order was not found.')
    if row.account_id != account:
        raise ValueError('The linked Webull order belongs to a different account.')
    if str(row.symbol or '').upper() != symbol or str(row.side or '').upper() != side:
        raise ValueError('The linked Webull order must match the synthetic order symbol and side.')
    if float(row.quantity or 0) != float(quantity):
        raise ValueError('The linked Webull order quantity must match the synthetic order quantity.')
    return {'webull_order_id': row.id, 'provider_order_id': row.provider_order_id,
            'client_order_id': row.client_order_id, 'state': 'WATCHING',
            'linked_status': row.status, 'linked_at': utc_now(aware=False).isoformat()}


def _guardian_link(parent):
    try:
        spec = json.loads(parent.conditional_spec or '')
    except (TypeError, ValueError):
        return {}, None
    if not isinstance(spec, dict):
        return {}, None
    link = spec.get('guardian')
    return spec, link if isinstance(link, dict) else None


def _classify_linked(status, filled, quantity):
    status = str(status or '').upper()
    filled = float(filled or 0)
    quantity = float(quantity or 0)
    if filled > 0 and quantity > 0 and filled < quantity - 1e-10:
        return 'PARTIAL'
    if status == 'FILLED' or (quantity > 0 and filled >= quantity - 1e-10):
        return 'FILLED'
    if status in GUARDIAN_DEAD_STATES and filled <= 0:
        return 'DEAD'
    if status in GUARDIAN_LIVE_STATES:
        return 'LIVE'
    return 'UNKNOWN'


def _linked_live_state(parent, link):
    """Fresh broker state for the linked order, or None when unverifiable."""
    client_id = link.get('client_order_id')
    if not client_id:
        return None
    try:
        from services.webull_service import get_webull_order_detail
        cred, env = ex.webull_credentials(parent)
        detail = get_webull_order_detail(cred.webull_app_key, cred.webull_app_secret, env,
                                         cred.webull_access_token, account_id=parent.account_id,
                                         client_order_id=client_id)
    except Exception:
        return None
    raw = detail.get('raw', detail) if isinstance(detail, dict) else {}
    if isinstance(raw, dict):
        raw = raw.get('data', raw)
    if isinstance(raw, dict) and isinstance(raw.get('orders') or raw.get('items'), list):
        items = raw.get('orders') or raw.get('items')
        raw = next((item for item in items
                    if str(item.get('client_order_id') or item.get('clientOrderId')) == client_id),
                   items[0] if len(items) == 1 else {})
    if not isinstance(raw, dict) or not raw:
        return None
    status = str(raw.get('status') or raw.get('order_status') or '').upper().replace(' ', '_')
    status = {'NEW': 'SUBMITTED', 'WORKING': 'SUBMITTED', 'ACCEPTED': 'SUBMITTED', 'PENDING': 'SUBMITTED',
              'PARTIAL_FILLED': 'PARTIALLY_FILLED', 'PARTIALLYFILLED': 'PARTIALLY_FILLED',
              'CANCELED': 'CANCELLED', 'REJECTED': 'FAILED', 'EXPIRED': 'CANCELLED',
              'FINAL_FILLED': 'FILLED'}.get(status, status)
    filled = next((raw[k] for k in ('filled_quantity', 'filled_qty', 'filledSize', 'filled_size', 'executedQty')
                   if raw.get(k) is not None), None)
    return status, (float(filled) if filled is not None else None)


def _guardian_finish(parent, spec, link, state, status, message):
    link['state'] = state
    parent.conditional_spec = json.dumps(spec)
    parent.status = status
    parent.monitoring_error = message
    return False


def guardian_gate(parent):
    """Decide whether a backstopped Limit synthetic may evaluate triggers.

    Returns True when evaluation may proceed: no link, the link was already
    taken over, or the linked order just ended unfilled and this synthetic
    now takes over. Returns False when the cycle must place nothing: the
    linked order is still working, its state cannot be verified, or the
    gate just moved the parent to its terminal state.
    """
    spec, link = _guardian_link(parent)
    if not link or link.get('state') != 'WATCHING':
        return True
    from models import WebullOrder
    row = WebullOrder.query.filter_by(id=link.get('webull_order_id'), user_id=parent.user_id).first()
    if row is None:
        parent.monitoring_error = ('Backstop: the linked Webull order is no longer visible, '
                                   'so nothing will be placed until it can be verified.')
        return False
    quantity = float(row.quantity or parent.total_quantity or 0)
    filled = float(row.filled_quantity or 0)
    outcome = _classify_linked(row.status, filled, quantity)
    if outcome == 'DEAD':
        # The local mirror can lag a just-reported fill; confirm with the
        # broker before taking over so two orders are never live at once.
        live = _linked_live_state(parent, link)
        if live is not None:
            live_status, live_filled = live
            if live_filled is not None:
                filled = live_filled
            outcome = _classify_linked(live_status, filled, quantity)
            if outcome == 'UNKNOWN':
                parent.monitoring_error = ('Backstop: the linked Webull order state could not be '
                                           'verified; nothing will be placed this cycle.')
                return False
    if outcome == 'LIVE':
        parent.monitoring_error = (f"Backstop armed: Webull order {link.get('provider_order_id')} "
                                   'is still working; nothing will be placed unless it ends unfilled.')
        return False
    if outcome == 'FILLED':
        return _guardian_finish(parent, spec, link, 'DONE', 'COMPLETED', None)
    if outcome == 'PARTIAL':
        return _guardian_finish(parent, spec, link, 'STOPPED', 'FAILED',
                                f'Backstop stopped: the linked Webull order partially filled '
                                f'({filled:g} of {quantity:g} shares) and the rest did not fill. '
                                'Nothing was placed; review the fill before creating a new order.')
    if outcome == 'DEAD':
        link['state'] = 'TAKEN_OVER'
        link['takeover_at'] = utc_now(aware=False).isoformat()
        parent.conditional_spec = json.dumps(spec)
        parent.monitoring_error = ('Backstop: the linked Webull order ended cancelled with no fill; '
                                   'this synthetic is placing the order from its own settings now.')
        return True
    parent.monitoring_error = ('Backstop: the linked Webull order state could not be '
                               'verified; nothing will be placed this cycle.')
    return False
