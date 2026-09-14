"""Guarded compatibility fills for users without a quantitative bankroll.

No provider requests occur here. A recent saved snapshot is a disclosed paper
execution assumption. The caller commits the fills and their evidence together.
"""
import json
import math
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from core.extensions import db
from event_algo_models import (
    EventMarketSnapshot, EventStrategyConfig, EventStrategyDecision,
    EventStrategyLog, EventStrategyOrder,
)
from portfolio_algo_models import PortfolioStrategyConfig
from services.event_market_timing import quote_freshness
from services.event_risk_policy import entry_allowance, normalize_risk_config


def _object(value):
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('Saved Event evidence/settings must be JSON objects.')
    return result


def _number(value, *, minimum=0, maximum=math.inf):
    if isinstance(value, bool):
        raise ValueError('Event numeric values cannot be booleans.')
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError('Event numeric value is invalid or outside its allowed range.')
    return number


def _integer(value):
    # Do not truncate floats or interpret a string as a sequence of decision IDs.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('Expected a positive whole number.')
    result = int(value)
    if result < 1:
        raise ValueError('Expected a positive whole number.')
    return result


def _risk_history(orders):
    rows = []
    for order in orders:
        if order.status in ('CANCELLED', 'REJECTED') and order.filled_quantity == 0:
            continue
        if order.side != 'BUY' or order.outcome not in ('YES', 'NO'):
            raise ValueError('Legacy Event risk history has an unsupported side/outcome.')
        closed = order.status == 'SIMULATED_SETTLED'
        if not closed and order.status not in ('SIMULATED_FILLED', 'SIMULATED_PENDING'):
            raise ValueError('Legacy Event risk history has an unsupported order status.')
        if closed != (order.settled_at is not None):
            raise ValueError('Legacy Event risk history has inconsistent settlement evidence.')
        quantity = _number(order.quantity, minimum=1)
        filled = _number(order.filled_quantity)
        price = _number(order.filled_price if order.filled_price is not None else order.limit_price,
                        minimum=0.000001, maximum=0.999999)
        fee = _number(order.fee)
        if filled > quantity or (order.status != 'SIMULATED_PENDING' and filled != quantity):
            raise ValueError('Legacy Event risk history has inconsistent fill quantities.')
        if closed:
            _number(order.realized_pnl, minimum=-math.inf)
        rows.append(SimpleNamespace(id=order.id, closed_at=order.settled_at,
            realized_pnl=order.realized_pnl, collateral=quantity * price, entry_fee=fee))
    return rows


def _assess(decision, config, signal, now):
    from event_algo import _market_cutoff, evaluate_market
    age = (now - decision.created_at).total_seconds()
    if not -5 <= age <= 120:
        raise ValueError('Decision exceeded its 120-second freshness window.')
    if decision.outcome not in ('YES', 'NO') or decision.action != 'BUY_' + decision.outcome:
        raise ValueError('Decision is not a valid buy signal.')
    _number(decision.probability_yes, maximum=1)
    _number(decision.confidence, maximum=1)
    snapshot = EventMarketSnapshot.query.filter_by(id=decision.snapshot_id,
        user_id=decision.user_id, config_id=config.id, contract_symbol=decision.contract_symbol).first()
    if snapshot is None:
        raise ValueError('Decision has no matching saved snapshot.')
    market = _object(snapshot.raw_json)
    if market.get('symbol') != decision.contract_symbol:
        raise ValueError('Saved quote does not match the exact decision contract.')
    timing = quote_freshness(market, now)
    if timing['status'] != 'FRESH':
        raise ValueError('Saved quote freshness is ' + timing['status'] + '; scan again for a quote within 30 seconds.')
    cutoff = _market_cutoff(market)
    if cutoff is None or cutoff <= now:
        raise ValueError('Contract cutoff is missing or expired.')
    assessment = evaluate_market({**market, 'model_probability_yes': decision.probability_yes,
                                  'model_confidence': decision.confidence}, config, now=now)
    if not assessment['eligible']:
        raise ValueError('Saved quote failed current Event gates: ' + ', '.join(assessment['reason_codes']))
    if assessment['outcome'] != decision.outcome:
        raise ValueError('Current Event gates changed the selected outcome; await a new decision.')
    price = _number(decision.executable_price, minimum=0.000001, maximum=0.999999)
    if abs(price - assessment['executable_price']) > 1e-9:
        raise ValueError('Decision price does not match its saved executable quote.')
    depth = market.get(decision.outcome.lower() + '_ask_size')
    if depth is not None:
        _number(depth, minimum=1)
    return price, {'snapshot_id': snapshot.id, 'quote_freshness': timing,
                   'depth_status': 'UNKNOWN' if depth is None else 'REPORTED',
                   'selected_ask_size': depth, 'signal_config': signal,
                   'net_edge_at_fill': assessment['net_edge']}


def simulate_legacy_fills(user_id, *, config=None, decision_ids=None, limit=25):
    """Caller owns the transaction, including releasing locks on rejections."""
    result = {'success': True, 'mode': 'PAPER', 'simulated_count': 0, 'orders': [], 'skipped': []}
    try:
        limit = _integer(limit)
        if limit > 100:
            raise ValueError('Simulation limit cannot exceed 100.')
        if decision_ids is not None:
            if not isinstance(decision_ids, (list, tuple)) or len(decision_ids) > 100:
                raise ValueError('decision_ids must be a list of at most 100 positive whole numbers.')
            decision_ids = [_integer(value) for value in decision_ids]
        if config is not None and config.user_id != user_id:
            raise ValueError('Event configuration does not belong to this user.')
        # Keep the active bankroll path completely separate from this ledger.
        if PortfolioStrategyConfig.query.filter_by(user_id=user_id).first() is not None:
            return {**result, 'message': 'Qualified signals are consumed by the capital-constrained quantitative ledger.'}
        config_id = config.id if config is not None else None
        # Lock every existing configuration in a stable order: exposure and
        # duplicate contracts are shared by all legacy configurations per user.
        with db.session.no_autoflush:
            configs = (EventStrategyConfig.query.filter_by(user_id=user_id)
                       .order_by(EventStrategyConfig.id).populate_existing().with_for_update().all())
        config = next((row for row in configs if config_id is None or row.id == config_id), None)
        if config is None or config.mode != 'PAPER' or not config.enabled or config.kill_switch:
            raise ValueError('Saved Event configuration is unavailable, stopped or killed.')
        if PortfolioStrategyConfig.query.filter_by(user_id=user_id).first() is not None:
            return {**result, 'message': 'Qualified signals are consumed by the capital-constrained quantitative ledger.'}
        risk = normalize_risk_config(config.risk_config)
        signal = _object(config.signal_config)
        from event_algo import DEFAULT_SIGNAL_CONFIG
        signal = {**DEFAULT_SIGNAL_CONFIG, **signal}
        for key in ('fee_per_contract', 'min_net_edge', 'min_confidence', 'uncertainty_buffer'):
            _number(signal[key], maximum=1)
        fee = float(signal['fee_per_contract'])  # An explicit zero stays zero.
        orders = (EventStrategyOrder.query.filter_by(user_id=user_id, mode='PAPER')
                  .order_by(EventStrategyOrder.id).populate_existing().with_for_update().all())
        history = _risk_history(orders)
        consumed = {order.contract_symbol for order in orders}
        query = EventStrategyDecision.query.filter_by(user_id=user_id, config_id=config.id, eligible=True)
        if decision_ids is not None:
            query = query.filter(EventStrategyDecision.id.in_(decision_ids))
        decisions = query.order_by(EventStrategyDecision.created_at.desc(), EventStrategyDecision.id.desc()).limit(limit).all()
        for decision in decisions:
            evidence = {'decision_id': decision.id, 'contract_symbol': decision.contract_symbol}
            try:
                if decision.contract_symbol in consumed:
                    raise ValueError('Contract already consumed by the legacy paper ledger.')
                now = datetime.utcnow()  # Waiting for the lock cannot refresh a quote.
                price, details = _assess(decision, config, signal, now)
                evidence.update(details)
                allowance = entry_allowance(risk, history, now)
                evidence['event_risk_at_fill'] = allowance
                if allowance['reason']:
                    raise ValueError(allowance['reason'])
                if price + fee > allowance['entry_budget'] + 1e-9 or price + 2 * fee > allowance['remaining_loss_allowance'] + 1e-9:
                    raise ValueError('Saved Event dollar/loss allowance cannot fund one contract including fees.')
                order = EventStrategyOrder(user_id=user_id, config_id=config.id, decision_id=decision.id,
                    mode='PAPER', broker='WEBULL', client_order_id='paper-' + uuid4().hex,
                    contract_symbol=decision.contract_symbol, outcome=decision.outcome, side='BUY',
                    quantity=1, limit_price=price, status='SIMULATED_FILLED', filled_quantity=1,
                    filled_price=price, fee=fee, submitted_at=now)
                db.session.add(order)
                db.session.flush()
                evidence.update(status='FILLED', order_id=order.id, price=price, quantity=1, fee=fee)
                result['orders'].append({'id': order.id, 'contract_symbol': order.contract_symbol,
                    'outcome': order.outcome, 'price': price, 'status': order.status})
                consumed.add(order.contract_symbol)
                history.extend(_risk_history([order]))
            except (TypeError, ValueError, OverflowError) as exc:
                evidence.update(status='REJECTED', reason=str(exc))
                result['skipped'].append({'decision_id': decision.id, 'reason': str(exc)})
            db.session.add(EventStrategyLog(user_id=user_id, config_id=config.id, run_id=decision.run_id,
                event_type='LEGACY_PAPER_' + evidence['status'], level='INFO',
                message=evidence.get('reason', 'One contract simulated with saved Event risk limits.'),
                metadata_json=json.dumps(evidence, allow_nan=False)))
        result['simulated_count'] = len(result['orders'])
        result['message'] = f"Simulated {result['simulated_count']} legacy paper fill(s); skipped {len(result['skipped'])}."
        return result
    except (TypeError, ValueError, OverflowError) as exc:
        # The public wrapper rolls the whole transaction back on failure.
        return {**result, 'success': False, 'simulated_count': 0, 'orders': [], 'message': str(exc)}
