"""Transactional paper ledger, leased supervisor, portfolio telemetry and CIO audits.

All fills are local ORM records. This module cannot submit brokerage orders.
Provider requests happen outside row locks; ownership is rechecked before each fill.
"""
import copy
import json
import logging
import math
import re
import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from core.extensions import db
from portfolio_algo_models import (
    DEFAULT_ALLOCATIONS, DEFAULT_MASTER_CIO_PROMPT, DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS,
    PortfolioStrategyConfig as Config, PortfolioStrategyAccount as Account,
    PortfolioStrategyPosition as Position, PortfolioStrategyOrder as Order,
    PortfolioEngineState as State, PortfolioStrategyLot as Lot,
    PortfolioEquitySnapshot as Snapshot, PortfolioAudit as Audit,
)
from services.portfolio_strategy_signals import (
    MODULES, TYPES, ET, finite, utc, in_session, session_bounds,
    equity_signal, crypto_signal, futures_signal, select_credit_spread, performance,
)

logger = logging.getLogger(__name__)
CADENCE = 300
LIMITS = {
    'equities': {'trend_sma_days': (50, 300, int), 'rsi_period': (2, 14, int), 'rsi_entry_threshold': (1, 50, float), 'bollinger_std': (1, 3, float)},
    'options': {'min_ivr': (0, 100, float), 'target_delta': (10, 35, float), 'target_dte': (20, 60, int), 'profit_target_pct': (25, 75, float)},
    'crypto': {'entry_channel_periods': (10, 100, int), 'exit_channel_periods': (5, 50, int), 'atr_stop_multiplier': (1.5, 5, float)},
    'futures': {'opening_range_minutes': (5, 60, int), 'max_intraday_loss': (1, 250, float)},
    'events': {'min_confidence': (0.5, 1, float), 'min_net_edge': (0.015, 1, float)},
}


def loads(value, default):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, type(default)) else copy.deepcopy(default)
    except (ValueError, TypeError):
        return copy.deepcopy(default)


def settings_for(cfg):
    settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS)
    for module, values in loads(cfg.module_settings_json, {}).items():
        if module in settings and isinstance(values, dict):
            settings[module].update(values)
    return settings


def validate_config(payload, cfg):
    if not isinstance(payload, dict):
        raise ValueError('Configuration must be a JSON object.')
    result = {}
    if 'mode' in payload and payload['mode'] != 'PAPER':
        raise ValueError('The quantitative engine only supports PAPER mode.')
    if 'enabled' in payload:
        raise ValueError('Use the Start and Stop controls to change execution state.')
    if 'total_bankroll' in payload and finite(payload['total_bankroll'], 'bankroll', 100, 1000000) != cfg.total_bankroll:
        raise ValueError('Change the bankroll through the confirmed reset control.')
    if 'target_annual_return' in payload:
        result['target_annual_return'] = finite(payload['target_annual_return'], 'target annual return', 10, 35)
    if 'allocations' in payload:
        values = payload['allocations']
        if not isinstance(values, dict) or set(values) != set(MODULES):
            raise ValueError('Allocations must specify exactly the five asset modules.')
        weights = {k: round(finite(values[k], k+' weight', 0, 100), 2) for k in MODULES}
        if abs(sum(weights.values())-100) > 0.001:
            raise ValueError('Rounded asset allocations must sum exactly to 100%.')
        result['allocations_json'] = json.dumps(weights)
    if 'watchlists' in payload:
        if not isinstance(payload['watchlists'], dict) or set(payload['watchlists'])-set(MODULES):
            raise ValueError('Unknown watchlist module.')
        lists = loads(cfg.watchlists_json, DEFAULT_QUANT_WATCHLISTS)
        for key, values in payload['watchlists'].items():
            if not isinstance(values, list) or len(values) > 30:
                raise ValueError('Each watchlist must be an array of at most 30 symbols.')
            if any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9.\-]{1,30}', s.strip()) for s in values):
                raise ValueError('Watchlist symbols must be 1–30 letters, digits, dots or hyphens.')
            lists[key] = list(dict.fromkeys(s.strip().upper() for s in values))
            if key == 'futures' and set(lists[key])-{'MES', 'MNQ', 'MGC', 'MCL'}:
                raise ValueError('Supported micro futures roots: MES, MNQ, MGC, MCL.')
        result['watchlists_json'] = json.dumps(lists)
    if 'module_settings' in payload:
        modules = payload['module_settings']
        if not isinstance(modules, dict) or set(modules)-set(MODULES):
            raise ValueError('Unknown strategy module.')
        settings = settings_for(cfg)
        for module, values in modules.items():
            if not isinstance(values, dict) or set(values)-set(DEFAULT_MODULE_SETTINGS[module]):
                raise ValueError(f'Unknown {module} strategy parameter.')
            for key, val in values.items():
                if key in LIMITS[module]:
                    low, high, cast = LIMITS[module][key]
                    number = finite(val, module+'.'+key, low, high)
                    if cast is int and number != int(number):
                        raise ValueError(f'{key} must be an integer.')
                    settings[module][key] = cast(number)
                elif key == 'specialist_prompt':
                    if not isinstance(val, str) or len(val) > 12000:
                        raise ValueError('Specialist prompt must be text of at most 12000 characters.')
                    settings[module][key] = val.strip()
                # Descriptive strategy names/return aspirations are not executable settings.
        if settings['crypto']['exit_channel_periods'] >= settings['crypto']['entry_channel_periods']:
            raise ValueError('Crypto exit channel must be shorter than the entry channel.')
        result['module_settings_json'] = json.dumps(settings)
    if 'master_ai_prompt' in payload:
        prompt = payload['master_ai_prompt']
        if not isinstance(prompt, str) or len(prompt) > 16000:
            raise ValueError('CIO prompt must be text of at most 16000 characters.')
        result['master_ai_prompt'] = prompt.strip() or DEFAULT_MASTER_CIO_PROMPT
    if 'master_ai_config' in payload:
        audit = payload['master_ai_config']
        if not isinstance(audit, dict) or set(audit)-{'cadence'} or audit.get('cadence') not in ('off', 'daily', 'weekly'):
            raise ValueError('Audit cadence must be off, daily or weekly.')
        result['master_ai_config'] = json.dumps(audit)
    return result


def ensure_portfolio(user_id):
    """Initialize once; uniqueness plus retry handles concurrent first visits."""
    for attempt in range(2):
        try:
            cfg = Config.query.filter_by(user_id=user_id, name='Default Multi-Asset Portfolio').first()
            acc = Account.query.filter_by(user_id=user_id).first()
            state = db.session.get(State, user_id)
            if cfg is None:
                cfg = Config(user_id=user_id)
                db.session.add(cfg)
            if acc is None:
                acc = Account(user_id=user_id)
                db.session.add(acc)
            if state is None:
                state = State(user_id=user_id)
                db.session.add(state)
            db.session.commit()
            return cfg, acc, state
        except IntegrityError:
            db.session.rollback()
            if attempt:
                raise


def locked(user_id):
    state = State.query.filter_by(user_id=user_id).populate_existing().with_for_update().one()
    cfg = Config.query.filter_by(user_id=user_id, name='Default Multi-Asset Portfolio').populate_existing().one()
    acc = Account.query.filter_by(user_id=user_id).populate_existing().one()
    return cfg, acc, state


def current_lots(user_id, state, opened_only=True):
    query = Lot.query.filter_by(user_id=user_id, generation=state.generation)
    if opened_only:
        query = query.filter(Lot.closed_at.is_(None))
    return query.order_by(Lot.id).all()


def mark_position(pos, lot, price):
    details = loads(lot.details_json, {})
    if lot.module == 'options':
        price = min(price, details['width'])
    direction = -1 if pos.side == 'SHORT' else 1
    pos.market_price = price
    pos.unrealized_pnl = (price-pos.average_cost)*pos.quantity*lot.multiplier*direction
    pos.market_value = lot.collateral + pos.unrealized_pnl
    pos.updated_at = datetime.utcnow()


def balances(acc, state, user_id):
    lots = current_lots(user_id, state)
    unrealized, reserved = 0.0, 0.0
    for lot in lots:
        pos = db.session.get(Position, lot.position_id)
        unrealized += pos.unrealized_pnl
        reserved += lot.collateral
    acc.total_equity = round(acc.cash_balance + reserved + unrealized, 8)
    return unrealized, reserved


def costs(module, price, quantity):
    if module == 'options':
        return 1.30 * quantity  # two legs, $0.65 each, per side
    if module == 'futures':
        return 1.25 * quantity
    if module == 'events':
        return 0.015 * quantity
    return price * quantity * 0.001  # 10 bps paper commission assumption


def fill_price(module, price, side, closing=False):
    if module in ('options', 'events'):
        return price  # executable bid/ask already used
    buy = (side == 'LONG') != closing
    return price * (1.0005 if buy else 0.9995)  # 5 bps adverse slippage


def close_lot(acc, lot, price, reason, now):
    pos = db.session.get(Position, lot.position_id)
    price = fill_price(lot.module, price, pos.side, closing=True)
    mark_position(pos, lot, price)
    fee = 0 if reason == 'SETTLEMENT' else costs(lot.module, price, pos.quantity)
    gross = pos.unrealized_pnl
    pnl = gross - lot.entry_fee - fee
    acc.cash_balance += lot.collateral + gross - fee
    lot.realized_pnl = pnl
    lot.closed_at = now
    db.session.add(Order(user_id=pos.user_id, module_name=lot.module.upper(), symbol=pos.symbol,
        instrument_type=pos.instrument_type, side='BUY' if pos.side=='SHORT' else 'SELL',
        quantity=pos.quantity, price=price, pnl=pnl, notes=json.dumps({'lot_id': lot.id, 'reason': reason, 'fee': fee}), created_at=now))
    for order in Order.query.filter_by(user_id=pos.user_id, status='OPEN', order_type='LIMIT').all():
        if loads(order.notes, {}).get('lot_id') == lot.id:
            order.status = 'FILLED' if reason == 'PROFIT_TARGET' else 'CANCELLED'
    pos.quantity = 0
    pos.market_value = 0
    pos.unrealized_pnl = 0


def module_budget(cfg, acc, state, module):
    weights = loads(cfg.allocations_json, DEFAULT_ALLOCATIONS)
    reserve = sum(lot.collateral for lot in current_lots(cfg.user_id, state) if lot.module == module)
    # Current equity sets the bucket; available cash still bounds every entry.
    return max(0, max(0, acc.total_equity)*weights[module]/100-reserve)


def enter_lot(cfg, acc, state, module, symbol, signal, price, now, *, multiplier=1, margin=None, details=None, key=None):
    key = key or f'{module}:{symbol}:{utc(now).astimezone(ET).date()}'
    if Lot.query.filter_by(user_id=cfg.user_id, generation=state.generation, signal_key=key).first():
        return None
    if any(lot.module == module and db.session.get(Position, lot.position_id).symbol == symbol for lot in current_lots(cfg.user_id, state)):
        return None
    side = signal.get('side', 'LONG')
    price = fill_price(module, price, side)
    budget = min(module_budget(cfg, acc, state, module), acc.cash_balance)
    # Per-position maximum: 20% of a bucket, and 0.5% portfolio stop risk.
    weight = loads(cfg.allocations_json, DEFAULT_ALLOCATIONS)[module]
    fraction = 1.0 if module == 'futures' else 0.2
    budget = min(budget, max(0, acc.total_equity)*weight/100*fraction)
    unit = margin if margin is not None else price*multiplier
    if unit <= 0 or budget <= 0:
        return None
    quantity = budget / (unit + costs(module, price, 1))
    stop = signal.get('stop')
    risk = abs(price-stop)*multiplier if stop is not None else unit
    if risk > 0:
        quantity = min(quantity, max(0, acc.total_equity)*0.005/(risk+2*costs(module, price, 1)))
    if module == 'futures':
        ceiling = settings_for(cfg)['futures']['max_intraday_loss']
        day_start = utc(now).astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
        day_pnl = sum(l.realized_pnl for l in current_lots(cfg.user_id, state, False) if l.module=='futures' and l.closed_at and utc(l.closed_at)>=day_start)
        open_risk = sum(abs(db.session.get(Position, l.position_id).average_cost-(l.stop_price or 0))*db.session.get(Position, l.position_id).quantity*l.multiplier + 2*l.entry_fee for l in current_lots(cfg.user_id, state) if l.module=='futures')
        quantity = min(quantity, max(0, ceiling+min(day_pnl, 0)-open_risk)/(risk+2*costs(module, price, 1)))
    quantity = math.floor(quantity) if module != 'crypto' else math.floor(quantity*1e6)/1e6
    if quantity <= 0:
        return None
    fee, collateral = costs(module, price, quantity), unit*quantity
    pos = Position(user_id=cfg.user_id, symbol=symbol, instrument_type=TYPES[module], side=side,
                   quantity=quantity, average_cost=price, market_price=price, market_value=collateral, unrealized_pnl=0)
    db.session.add(pos)
    db.session.flush()
    lot = Lot(user_id=cfg.user_id, position_id=pos.id, generation=state.generation, module=module, signal_key=key,
              collateral=collateral, multiplier=multiplier, stop_price=stop, target_price=signal.get('target'),
              entry_fee=fee, opened_at=now, details_json=json.dumps(details or {}))
    db.session.add(lot)
    db.session.flush()
    acc.cash_balance -= collateral+fee
    db.session.add(Order(user_id=cfg.user_id, module_name=module.upper(), symbol=symbol, instrument_type=TYPES[module],
        side='SELL' if side=='SHORT' else 'BUY', quantity=quantity, price=price, created_at=now,
        notes=json.dumps({'lot_id': lot.id, 'fee': fee, 'reason': signal.get('reason'), 'collateral': collateral})))
    if module == 'options':
        db.session.add(Order(user_id=cfg.user_id, module_name='OPTIONS', symbol=symbol, instrument_type='OPTION',
            side='BUY', order_type='LIMIT', quantity=quantity, price=lot.target_price, status='OPEN',
            notes=json.dumps({'lot_id': lot.id, 'time_in_force': 'GTC', 'rule': 'PROFIT_TARGET'}), created_at=now))
    return lot


def check_circuit(cfg, acc, state):
    if acc.total_equity <= acc.initial_balance*0.9:
        if not state.kill_switch:
            snapshot(cfg, acc, state, datetime.utcnow())
        trigger_pause(cfg, state, 'Portfolio drawdown reached 10% of starting bankroll. Positions frozen for review.')
        return True
    return state.kill_switch


def trigger_pause(cfg, state, reason):
    newly = not state.kill_switch
    state.kill_switch = True
    state.pause_reason = reason
    state.lease_token = None
    state.lease_until = None
    cfg.enabled = False
    cfg.worker_status = 'PAUSED'
    if newly:
        # Persist a system notification in the same transaction, with no external send.
        from models import Notification
        now = utc(datetime.utcnow()).astimezone(ET)
        db.session.add(Notification(user_id=cfg.user_id, coin_id=0, message=reason, symbol='QUANT',
            category='portfolio_strategy', table_type='system', date=now.strftime('%m-%d-%Y'),
            time=now.strftime('%I:%M %p %Z'), crossing_price=0, current_price=0, direction='down'))


def snapshot(cfg, acc, state, now):
    unrealized, reserved = balances(acc, state, cfg.user_id)
    lots = current_lots(cfg.user_id, state, False)
    realized = sum(l.realized_pnl for l in lots if l.closed_at)
    module_pnl = {m: sum(l.realized_pnl if l.closed_at else db.session.get(Position, l.position_id).unrealized_pnl-l.entry_fee for l in lots if l.module==m) for m in MODULES}
    db.session.add(Snapshot(user_id=cfg.user_id, generation=state.generation, created_at=now, equity=acc.total_equity,
        cash=acc.cash_balance, unrealized_pnl=unrealized, realized_pnl=realized, modules_json=json.dumps(module_pnl)))


def daily_snapshots(user_id, generation):
    latest = (db.session.query(func.max(Snapshot.id)).filter_by(user_id=user_id, generation=generation)
              .group_by(func.date(Snapshot.created_at)))
    return Snapshot.query.filter(Snapshot.id.in_(latest)).order_by(Snapshot.created_at).all()


def observed_drawdown(user_id, generation):
    window = db.session.query(Snapshot.equity.label('equity'),
        func.max(Snapshot.equity).over(order_by=(Snapshot.created_at, Snapshot.id)).label('peak')).filter_by(
            user_id=user_id, generation=generation).subquery()
    maximum = db.session.query(func.max((window.c.peak-window.c.equity)/func.nullif(window.c.peak, 0))).scalar()
    return float(maximum or 0)*100


def portfolio_status(user_id):
    cfg, acc, state = ensure_portfolio(user_id)
    lots = current_lots(user_id, state, False)
    positions = []
    for lot in lots:
        if lot.closed_at:
            continue
        p = db.session.get(Position, lot.position_id)
        positions.append({'id': p.id, 'module': lot.module, 'symbol': p.symbol, 'side': p.side, 'quantity': p.quantity,
            'average_cost': p.average_cost, 'mark': p.market_price, 'unrealized_pnl': p.unrealized_pnl,
            'collateral': lot.collateral, 'stop': lot.stop_price, 'target': lot.target_price,
            'marked_at': p.updated_at.isoformat()+'Z', 'details': loads(lot.details_json, {})})
    query = Snapshot.query.filter_by(user_id=user_id, generation=state.generation).order_by(Snapshot.created_at)
    daily = daily_snapshots(user_id, state.generation)
    first = query.first()
    metric_rows = ([first] if first else []) + daily
    metrics = performance([{'time': r.created_at.isoformat()+'Z', 'equity': r.equity} for r in metric_rows],
                          acc.initial_balance, [l.realized_pnl for l in lots if l.closed_at])
    metrics['max_drawdown_pct'] = observed_drawdown(user_id, state.generation)
    rows = query.limit(2001).all()
    if len(rows) > 2000:
        rows = daily[-2000:]
    curve = [{'time': row.created_at.isoformat()+'Z', 'equity': row.equity, 'cash': row.cash, 'realized_pnl': row.realized_pnl, 'unrealized_pnl': row.unrealized_pnl} for row in rows]
    allocations = loads(cfg.allocations_json, DEFAULT_ALLOCATIONS)
    drift = []
    for module in MODULES:
        capital = sum(p['collateral']+p['unrealized_pnl'] for p in positions if p['module']==module)
        actual = capital/acc.total_equity*100 if acc.total_equity>0 else 0
        difference = actual-allocations[module]
        drift.append({'module': module, 'target_pct': allocations[module], 'actual_pct': actual, 'drift_pct': difference,
                      'signal': 'TRIM' if difference>3 else 'AVAILABLE_CAPACITY' if difference < -3 else 'WITHIN_BAND',
                      'available_capital': module_budget(cfg, acc, state, module)})
    telemetry = loads(state.telemetry_json, {})
    status = cfg.worker_status
    if cfg.enabled and (not state.heartbeat_at or datetime.utcnow()-state.heartbeat_at > timedelta(minutes=10)):
        status = 'STALLED'
    realized = sum(l.realized_pnl for l in lots if l.closed_at)
    return {'success': True, 'mode': 'PAPER', 'worker_status': status, 'enabled': cfg.enabled,
            'kill_switch': state.kill_switch, 'pause_reason': state.pause_reason,
            'heartbeat_at': state.heartbeat_at.isoformat()+'Z' if state.heartbeat_at else None,
            'generation': state.generation, 'modules': telemetry, 'positions': positions, 'open_positions_count': len(positions),
            'account': {'initial_balance': acc.initial_balance, 'cash_balance': acc.cash_balance, 'total_equity': acc.total_equity,
                        'currency': 'USD', 'realized_pnl': realized, 'unrealized_pnl': sum(p['unrealized_pnl'] for p in positions),
                        'return_pct': (acc.total_equity/acc.initial_balance-1)*100},
            'performance': metrics, 'equity_curve': curve[-2000:], 'allocations': allocations, 'rebalance': drift}


def reset_bankroll(user_id, amount):
    amount = finite(amount, 'bankroll', 100, 1000000)
    ensure_portfolio(user_id)
    cfg, acc, state = locked(user_id)
    # Preserve every historical position, order, snapshot and audit under its generation.
    for pos in Position.query.filter_by(user_id=user_id).filter(~Position.id.in_(db.session.query(Lot.position_id))).all():
        module = next((m for m, instrument in TYPES.items() if instrument == pos.instrument_type), 'equities')
        db.session.add(Lot(user_id=user_id, position_id=pos.id, generation=state.generation,
            module=module, signal_key=f'legacy:{pos.id}', collateral=max(0, pos.market_value),
            details_json='{"archived_legacy": true}'))
    for order in Order.query.filter_by(user_id=user_id, status='OPEN').all():
        order.status = 'CANCELLED'
    state.generation += 1
    state.kill_switch = False
    state.pause_reason = None
    state.lease_token = None
    state.lease_until = None
    state.telemetry_json = '{}'
    state.last_scan_at = state.heartbeat_at = state.last_audit_at = None
    cfg.enabled = False
    cfg.worker_status = 'STOPPED'
    cfg.total_bankroll = amount
    acc.initial_balance = acc.cash_balance = acc.total_equity = amount
    acc.reset_at = datetime.utcnow()
    snapshot(cfg, acc, state, acc.reset_at)
    db.session.commit()
    return {'initial_balance': amount, 'cash_balance': amount, 'total_equity': amount, 'reset_at': acc.reset_at.isoformat()+'Z'}


def control(user_id, action):
    ensure_portfolio(user_id)
    cfg, acc, state = locked(user_id)
    if action == 'start':
        if state.kill_switch:
            raise ValueError('Acknowledge the circuit breaker before starting.')
        if acc.total_equity <= acc.initial_balance*0.9:
            raise ValueError('Bankroll remains below the circuit-breaker floor.')
        # Reject unsafe legacy persisted configuration before scheduling it.
        validate_config({'module_settings': settings_for(cfg), 'allocations': loads(cfg.allocations_json, {})}, cfg)
        legacy = Position.query.filter_by(user_id=user_id).filter(Position.quantity>0, ~Position.id.in_(db.session.query(Lot.position_id))).first()
        if legacy:
            raise ValueError('Unmanaged legacy positions exist. Archive this run with the reset control before starting.')
        cfg.enabled = True
        cfg.worker_status = 'STARTING'
        if not Snapshot.query.filter_by(user_id=user_id, generation=state.generation).first():
            snapshot(cfg, acc, state, datetime.utcnow())
    elif action == 'stop':
        cfg.enabled = False
        cfg.worker_status = 'PAUSED' if state.kill_switch else 'STOPPED'
        state.lease_token = state.lease_until = None
    elif action == 'kill':
        trigger_pause(cfg, state, 'Administrator activated the portfolio kill switch. Positions frozen.')
    elif action == 'acknowledge':
        if acc.total_equity <= acc.initial_balance*0.9:
            raise ValueError('The portfolio remains below its drawdown floor; acknowledge after a confirmed bankroll reset.')
        state.kill_switch = False
        state.pause_reason = None
        cfg.worker_status = 'STOPPED'
    else:
        raise ValueError('Unknown worker action.')
    db.session.commit()


def claim(user_id, force=False):
    cfg, acc, state = locked(user_id)
    now = datetime.utcnow()
    if not cfg.enabled or cfg.mode != 'PAPER' or state.kill_switch:
        db.session.rollback()
        return None
    if state.lease_until and state.lease_until > now:
        db.session.rollback()
        return None
    if not force and state.last_scan_at and now-state.last_scan_at < timedelta(seconds=CADENCE):
        db.session.rollback()
        return None
    token = uuid4().hex
    state.lease_token, state.lease_until = token, now+timedelta(minutes=5)
    state.heartbeat_at = now
    cfg.worker_status = 'RUNNING'
    db.session.commit()
    return token


def owns(cfg, state, token):
    return cfg.enabled and cfg.mode == 'PAPER' and not state.kill_switch and state.lease_token == token and state.lease_until and state.lease_until > datetime.utcnow()


def event_inputs(user_id, state, now, watchlist, settings):
    from event_algo_models import EventStrategyDecision as Decision, EventMarketSnapshot as Market, EventStrategyConfig
    event_cfg = EventStrategyConfig.query.filter_by(user_id=user_id).first()
    if not event_cfg or event_cfg.kill_switch or not event_cfg.enabled:
        return []
    rows = Decision.query.filter_by(user_id=user_id, config_id=event_cfg.id, eligible=True).filter(
        Decision.created_at >= now-timedelta(seconds=120)).order_by(Decision.created_at.desc()).limit(50).all()
    results = []
    for decision in rows:
        market = db.session.get(Market, decision.snapshot_id)
        if not market or market.user_id != user_id or market.received_at < now-timedelta(seconds=120) or not market.cutoff_at or market.cutoff_at <= now+timedelta(seconds=30):
            continue
        if market.series_symbol not in watchlist and not any(decision.contract_symbol.startswith(s+'-') for s in watchlist):
            continue
        if (decision.net_edge or 0)<settings['min_net_edge'] or (decision.confidence or 0)<settings['min_confidence']:
            continue
        side = decision.outcome
        price = market.yes_ask if side=='YES' else market.no_ask
        if side not in ('YES', 'NO') or price is None or not 0 < price < 1:
            continue
        # Recompute edge against the current executable quote and paper fee.
        probability = decision.probability_yes if side=='YES' else decision.probability_no
        if probability is None or probability-price-0.015 < settings['min_net_edge']:
            continue
        results.append((decision.contract_symbol[:64], float(price), {'side': 'LONG', 'enter': True, 'reason': 'Qualified event probability signal'},
                        {'contract_symbol': decision.contract_symbol, 'outcome': side, 'decision_id': decision.id}, f'events:{decision.contract_symbol}'))
    return results


def mark_event(user_id, details, now):
    from event_algo_models import EventContractOutcome, EventMarketSnapshot
    outcome = EventContractOutcome.query.filter_by(user_id=user_id, contract_symbol=details['contract_symbol'], settlement_status='RESOLVED').order_by(EventContractOutcome.updated_at.desc()).first()
    if outcome and outcome.outcome in ('YES', 'NO'):
        return (1.0 if outcome.outcome==details['outcome'] else 0.0), 'SETTLEMENT'
    quote = EventMarketSnapshot.query.filter_by(user_id=user_id, contract_symbol=details['contract_symbol']).order_by(EventMarketSnapshot.received_at.desc()).first()
    if not quote or quote.received_at < now-timedelta(seconds=120):
        raise ValueError('Awaiting fresh event quote or provider-confirmed settlement.')
    price = quote.yes_bid if details['outcome']=='YES' else quote.no_bid
    return finite(price, 'event bid', 0, 1), None


def run_scan(user_id, force=False, provider=None):
    token = claim(user_id, force)
    if not token:
        return {'success': False, 'message': 'Engine stopped, paused, busy, or not due.'}
    report = {m: {'status': 'IDLE', 'messages': [], 'evaluated': 0, 'entries': 0} for m in MODULES}
    try:
        from services.portfolio_strategy_data import PortfolioMarketData
        data = provider or PortfolioMarketData(user_id)
        cfg, acc, state = locked(user_id)
        settings = settings_for(cfg)
        watches = loads(cfg.watchlists_json, DEFAULT_QUANT_WATCHLISTS)
        lot_ids = [l.id for l in current_lots(user_id, state)]
        db.session.commit()
        # Manage existing positions first, including symbols removed from the watchlist.
        for lot_id in lot_ids:
            lot = db.session.get(Lot, lot_id)
            pos = db.session.get(Position, lot.position_id)
            details = loads(lot.details_json, {})
            module, symbol, now = lot.module, pos.symbol, datetime.utcnow()
            try:
                if module in ('equities', 'options', 'futures') and not in_session(now):
                    continue
                reason, signal = None, None
                if module == 'events':
                    price, reason = mark_event(user_id, details, now)
                elif module == 'options':
                    price = data.spread_mark(details, now)
                    if price <= lot.target_price:
                        reason = 'PROFIT_TARGET'
                    elif (utc(details['expiration']).date()-utc(now).astimezone(ET).date()).days <= 7:
                        reason = 'EXPIRY_RISK_EXIT'
                    elif price >= min(details['width'], pos.average_cost*2):
                        reason = 'SPREAD_STOP'
                else:
                    price = data.quote(symbol, TYPES[module], now)
                    if module == 'futures':
                        bounds = session_bounds(utc(now).astimezone(ET).date())
                        if utc(lot.opened_at).astimezone(ET).date() != utc(now).astimezone(ET).date() or utc(now)>=bounds[1]-timedelta(minutes=5):
                            reason = 'SESSION_EXIT'
                    elif module in ('equities', 'crypto'):
                        try:
                            if module == 'equities':
                                bars = data.bars(symbol, 'EQUITY', now, limit=max(settings[module]['trend_sma_days']+10, 260))
                                signal = equity_signal(bars, price, settings[module], data.bars('SPY', 'EQUITY', now))
                            else:
                                bars = data.bars(symbol, 'CRYPTO', now, interval='H1', limit=150)
                                signal = crypto_signal(bars, price, settings[module], True)
                            reason = 'STRATEGY_EXIT' if signal['exit'] else None
                        except Exception as exc:
                            # A history outage must not suppress marking or an existing stop.
                            report[module]['messages'].append(f'{symbol}: indicators unavailable ({str(exc)[:120]})')
                if datetime.utcnow()-now > timedelta(seconds=120):
                    raise ValueError('Market-data collection exceeded the quote freshness window.')
                cfg, acc, state = locked(user_id)
                if not owns(cfg, state, token):
                    db.session.rollback()
                    return {'success': False, 'message': 'Worker ownership changed.'}
                lot = db.session.get(Lot, lot_id)
                pos = db.session.get(Position, lot.position_id)
                old_stop = lot.stop_price
                if old_stop is not None and ((pos.side=='LONG' and price<=old_stop) or (pos.side=='SHORT' and price>=old_stop)):
                    reason = 'STOP_LOSS'
                if module == 'crypto' and signal and not reason:
                    lot.stop_price = max(old_stop or 0, signal['stop'])
                mark_position(pos, lot, price)
                if module == 'futures':
                    bounds = utc(now).astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
                    daily = sum(l.realized_pnl for l in current_lots(user_id, state, False) if l.module=='futures' and l.closed_at and utc(l.closed_at)>=bounds)
                    floating = sum(db.session.get(Position, l.position_id).unrealized_pnl-l.entry_fee for l in current_lots(user_id, state) if l.module=='futures')
                    if daily+floating <= -settings[module]['max_intraday_loss']:
                        reason = 'DAILY_LOSS_LIMIT'
                if reason:
                    close_lot(acc, lot, price, reason, now)
                balances(acc, state, user_id)
                if not check_circuit(cfg, acc, state) and lot.closed_at is None:
                    weights = loads(cfg.allocations_json, DEFAULT_ALLOCATIONS)
                    capital = sum(l.collateral+db.session.get(Position, l.position_id).unrealized_pnl for l in current_lots(user_id, state) if l.module==module)
                    if acc.total_equity>0 and capital/acc.total_equity*100-weights[module]>3:
                        close_lot(acc, lot, price, 'REBALANCE_TRIM', now)
                        balances(acc, state, user_id)
                state.heartbeat_at = datetime.utcnow()
                state.lease_until = datetime.utcnow()+timedelta(minutes=5) if state.lease_token else None
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                report[module]['messages'].append(f'{symbol}: {str(exc)[:200]}')
        for module in MODULES:
            for watch_symbol in watches.get(module, []):
                now = datetime.utcnow()
                cfg, acc, state = locked(user_id)
                if not owns(cfg, state, token):
                    db.session.rollback()
                    return {'success': False, 'message': 'Engine stopped or ownership changed.'}
                state.heartbeat_at, state.lease_until = now, now+timedelta(minutes=5)
                db.session.commit()
                try:
                    if module in ('equities', 'options', 'futures') and not in_session(now):
                        report[module]['status'] = 'MARKET_CLOSED'
                        break
                    symbol, multiplier, margin, details = watch_symbol, 1, None, {}
                    if module == 'events':
                        entries = event_inputs(user_id, state, now, [watch_symbol], settings[module])
                    else:
                        if module == 'options':
                            price, contracts, rank = data.options(symbol, settings[module], now)
                            spread = select_credit_spread(contracts, price, rank, settings[module], now)
                            price, multiplier = spread['credit'], 100
                            margin = (spread['width']-price)*100
                            details = spread
                            signal = {'enter': True, 'side': 'SHORT', 'target': price*(1-settings[module]['profit_target_pct']/100), 'reason': 'Defined-risk credit spread'}
                        elif module == 'futures':
                            symbol, multiplier, margin = data.future(watch_symbol, now)
                            price = data.quote(symbol, 'FUTURES', now)
                            signal = futures_signal(data.bars(symbol, 'FUTURES', now, interval='M1', limit=1200), price, settings[module], now)
                            details = {'root': watch_symbol, 'margin_assumption': margin}
                        elif module == 'crypto':
                            price = data.quote(symbol, 'CRYPTO', now)
                            signal = crypto_signal(data.bars(symbol, 'CRYPTO', now, interval='H1', limit=150), price, settings[module], data.dominance_ok(symbol, now))
                        else:
                            price = data.quote(symbol, 'EQUITY', now)
                            bars = data.bars(symbol, 'EQUITY', now, limit=max(settings[module]['trend_sma_days']+10, 260))
                            signal = equity_signal(bars, price, settings[module], data.bars('SPY', 'EQUITY', now))
                        entries = [(symbol, price, signal, details, None)]
                    if datetime.utcnow()-now > timedelta(seconds=120):
                        raise ValueError('Market-data collection exceeded the quote freshness window.')
                    cfg, acc, state = locked(user_id)
                    if not owns(cfg, state, token):
                        db.session.rollback()
                        return {'success': False, 'message': 'Engine stopped or ownership changed.'}
                    balances(acc, state, user_id)
                    if check_circuit(cfg, acc, state):
                        db.session.commit()
                        break
                    for entry_symbol, price, signal, details, key in entries:
                        if signal['enter']:
                            opened = enter_lot(cfg, acc, state, module, entry_symbol, signal, price, now, multiplier=multiplier, margin=margin, details=details, key=key)
                            report[module]['entries'] += int(opened is not None)
                            balances(acc, state, user_id)
                    report[module]['evaluated'] += 1
                    report[module]['status'] = 'SCANNED'
                    db.session.commit()
                except Exception as exc:
                    db.session.rollback()
                    report[module]['messages'].append(f'{watch_symbol}: {str(exc)[:200]}')
        cfg, acc, state = locked(user_id)
        if state.lease_token == token:
            for module in MODULES:
                if report[module]['messages']:
                    report[module]['status'] = 'DATA_LIMITED'
            state.telemetry_json = json.dumps(report)
            snapshot(cfg, acc, state, datetime.utcnow())
            check_circuit(cfg, acc, state)
            state.last_scan_at = state.heartbeat_at = datetime.utcnow()
            state.lease_token = state.lease_until = None
            if not state.kill_switch:
                cfg.worker_status = 'DEGRADED' if any(r['messages'] for r in report.values()) else 'RUNNING'
            db.session.commit()
        else:
            db.session.rollback()
        return {'success': True, 'modules': report}
    except Exception as exc:
        db.session.rollback()
        cfg, acc, state = locked(user_id)
        if state.lease_token == token:
            state.lease_token = state.lease_until = None
            state.last_scan_at = state.heartbeat_at = datetime.utcnow()
            state.telemetry_json = json.dumps({'error': str(exc)[:300]})
            cfg.worker_status = 'DEGRADED'
            db.session.commit()
        else:
            db.session.rollback()
        logger.warning('Portfolio scan failed for user %s: %s', user_id, exc)
        return {'success': False, 'message': str(exc)[:300]}


def measured_correlations(user_id, generation):
    rows = daily_snapshots(user_id, generation)
    daily = {}
    for row in rows:
        daily[row.created_at.date()] = loads(row.modules_json, {})
    days = sorted(daily)
    changes = {m: [] for m in MODULES}
    for a, b in zip(days, days[1:]):
        if (b-a).days == 1:
            for m in MODULES:
                changes[m].append(daily[b].get(m, 0)-daily[a].get(m, 0))
    pairs = []
    for i, a in enumerate(MODULES):
        for b in MODULES[i+1:]:
            x, y = changes[a], changes[b]
            correlation = None
            if len(x) >= 30:
                mx, my = sum(x)/len(x), sum(y)/len(y)
                denominator = math.sqrt(sum((v-mx)**2 for v in x)*sum((v-my)**2 for v in y))
                if denominator:
                    correlation = sum((u-mx)*(v-my) for u, v in zip(x,y))/denominator
            pairs.append({'a': a, 'b': b, 'pearson_r': correlation, 'daily_samples': len(x)})
    return pairs


def audit_dict(row):
    return {'id': row.id, 'generation': row.generation, 'timestamp': row.created_at.isoformat()+'Z',
            'status': row.status, 'content': row.content, 'provider': row.provider, 'model': row.model,
            'evidence': loads(row.evidence_json, {})}


def audit_due(cfg, state, now):
    cadence = loads(cfg.master_ai_config, {}).get('cadence', 'off')
    if cadence == 'off':
        return False
    day = utc(now).astimezone(ET).date()
    bounds = session_bounds(day)
    if not bounds or utc(now) < bounds[1]:
        return False
    if state.last_audit_at:
        previous = utc(state.last_audit_at).astimezone(ET).date()
        if previous == day or (cadence == 'weekly' and previous.isocalendar()[:2] == day.isocalendar()[:2]):
            return False
    return True


def run_audit(user_id, prompt=None, scheduled=False):
    ensure_portfolio(user_id)
    cfg, acc, state = locked(user_id)
    now = datetime.utcnow()
    if scheduled and not audit_due(cfg, state, now):
        db.session.rollback()
        return None
    pending = Audit.query.filter_by(user_id=user_id, status='PENDING').filter(Audit.created_at>now-timedelta(minutes=15)).first()
    if pending:
        db.session.rollback()
        raise ValueError('A portfolio audit is already running.')
    for stale in Audit.query.filter_by(user_id=user_id, status='PENDING').all():
        stale.status = 'FAILED'
        stale.content = 'Audit interrupted or timed out; no verdict available.'
    row = Audit(user_id=user_id, generation=state.generation, created_at=now)
    state.last_audit_at = now
    db.session.add(row)
    db.session.commit()
    audit_id = row.id
    try:
        evidence = portfolio_status(user_id)
        if evidence['generation'] != row.generation:
            raise ValueError('Paper run changed while the audit was being prepared.')
        evidence.pop('equity_curve', None)
        evidence['correlations'] = measured_correlations(user_id, state.generation)
        evidence['target_annual_return'] = cfg.target_annual_return
        evidence['specialist_mandates'] = {m: s['specialist_prompt'] for m, s in settings_for(cfg).items()}
        evidence['limitations'] = ['Paper simulation with estimated costs; targets are aspirations.',
                                  'Annualized return requires 30 elapsed days; ratios/correlations require 30 daily samples.',
                                  'No simulated stress test has been performed; no numerical forecast is supplied.']
        content = None
        provider = model = None
        status = 'UNAVAILABLE'
        from credentials import User
        from services.ai_service import call_ai_with_web_search, is_ai_enabled
        user = db.session.get(User, user_id)
        if user and is_ai_enabled(user.username):
            response, _ = call_ai_with_web_search(
                username=user.username, user_id=user_id,
                messages=[{'role': 'system', 'content': (prompt or cfg.master_ai_prompt or DEFAULT_MASTER_CIO_PROMPT) +
                          '\nUse only supplied quantitative evidence for numerical claims. Null means unavailable. Never invent correlations, stress results, probabilities of profit or guaranteed returns. Give advisory observations only; do not claim to execute changes.'},
                          {'role': 'user', 'content': json.dumps(evidence)}],
                prompt_type='portfolio_audit', symbol='PORTFOLIO', include_db_context=False)
            content = getattr(response, 'text', None)
            provider, model = getattr(response, 'provider', None), getattr(response, 'model', None)
            if content:
                status = 'SUCCESS'
        if not content:
            content = ('AI audit unavailable. Measured portfolio equity: '
                       f"${evidence['account']['total_equity']:,.2f}. Observed maximum drawdown: "
                       f"{evidence['performance']['max_drawdown_pct']:.2f}%. "
                       'Review the evidence and module diagnostics below. No forecast, correlation estimate or stress-test result has been generated.')
        row = db.session.get(Audit, audit_id)
        row.content, row.status, row.provider, row.model = content, status, provider, model
        row.evidence_json = json.dumps(evidence)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        row = db.session.get(Audit, audit_id)
        row.status = 'FAILED'
        row.content = f'AI audit failed: {str(exc)[:300]}. No quantitative verdict was generated.'
        db.session.commit()
    return audit_dict(row)


def portfolio_worker_loop(app, stop_event=None):
    import threading
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        with app.app_context():
            try:
                from credentials import User
                from event_algo import is_event_strategy_admin
                users = [c.user_id for c in Config.query.filter_by(enabled=True, mode='PAPER').all()]
                for user_id in users:
                    user = db.session.get(User, user_id)
                    if user and is_event_strategy_admin(user):
                        ensure_portfolio(user_id)
                        run_scan(user_id)
            except Exception:
                db.session.rollback()
                logger.exception('Portfolio supervisor iteration failed')
            finally:
                db.session.remove()
        stop_event.wait(15)


def portfolio_audit_loop(app, stop_event=None):
    import threading
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        with app.app_context():
            try:
                from credentials import User
                from event_algo import is_event_strategy_admin
                for cfg in Config.query.filter_by(mode='PAPER').all():
                    user = db.session.get(User, cfg.user_id)
                    if user and is_event_strategy_admin(user):
                        run_audit(cfg.user_id, scheduled=True)
            except Exception:
                db.session.rollback()
                logger.exception('Portfolio audit scheduler iteration failed')
            finally:
                db.session.remove()
        stop_event.wait(60)
