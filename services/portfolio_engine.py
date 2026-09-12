"""Transactional paper ledger, leased supervisor, portfolio telemetry and CIO audits.

All fills are local ORM records. This module cannot submit brokerage orders.
Provider requests happen outside row locks; ownership is rechecked before each fill.
"""
import copy
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from flask import current_app
from core.extensions import db
from portfolio_algo_models import (
    DEFAULT_ALLOCATIONS, DEFAULT_MASTER_CIO_PROMPT, DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS,
    PortfolioStrategyConfig as Config, PortfolioStrategyAccount as Account,
    PortfolioStrategyPosition as Position, PortfolioStrategyOrder as Order,
    PortfolioEngineState as State, PortfolioStrategyLot as Lot,
    PortfolioEquitySnapshot as Snapshot, PortfolioAudit as Audit,
    PortfolioEngineLog, _record_portfolio_log,
)
from services.portfolio_strategy_signals import (
    MODULES, TYPES, ET, finite, utc, in_session, session_bounds,
    equity_signal, crypto_signal, futures_signal, select_credit_spread, performance,
)

from services.portfolio_allocations import normalize_allocations
from services.portfolio_goal_tracking import build_goal_tracking
from services.portfolio_calibration import event_calibration
from services.portfolio_execution_math import costs, fill_price, entry_quantity, spot_exit
from services.portfolio_audit_progress import audit_progress
from services.portfolio_audit_context import (
    ENGINE_PURPOSE, EVIDENCE_RULES, STRATEGY_RULES, audit_system_prompt, check_drawdown_claim,
)

logger = logging.getLogger(__name__)
CADENCE = 300
DEFAULT_AUDIT_PROMPT_INTERVAL_SECONDS = 15
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


def audit_prompt_interval_seconds():
    if current_app.config.get('TESTING'):
        return 0
    try:
        return max(0, min(120, float(os.getenv(
            'PORTFOLIO_AUDIT_PROMPT_INTERVAL_SECONDS',
            str(DEFAULT_AUDIT_PROMPT_INTERVAL_SECONDS),
        ))))
    except (TypeError, ValueError):
        return DEFAULT_AUDIT_PROMPT_INTERVAL_SECONDS


def wait_for_next_audit_prompt(last_finished_at, interval_seconds):
    if last_finished_at is None or interval_seconds <= 0:
        return
    remaining = interval_seconds - (time.monotonic() - last_finished_at)
    if remaining > 0:
        time.sleep(remaining)


def normalize_module_settings(values):
    """Accept the former prompt name while keeping the current field authoritative."""
    values = copy.deepcopy(values)
    if 'specialist_prompt' in values:
        values.setdefault('auditor_prompt', values.pop('specialist_prompt'))
    return values


def settings_for(cfg):
    settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS)
    for module, values in loads(cfg.module_settings_json, {}).items():
        if module in settings and isinstance(values, dict):
            settings[module].update(normalize_module_settings(values))
    weights = loads(getattr(cfg, 'allocations_json', None), DEFAULT_ALLOCATIONS)
    for module in MODULES:
        settings[module].setdefault('allocation_preference', weights.get(module) or DEFAULT_ALLOCATIONS[module])
    return settings


def allocations_for(cfg):
    return normalize_allocations(loads(cfg.allocations_json, DEFAULT_ALLOCATIONS), settings_for(cfg))


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
            if not isinstance(values, dict):
                raise ValueError(f'{module} strategy settings must be a JSON object.')
            values = normalize_module_settings(values)
            unknown = set(values)-(set(DEFAULT_MODULE_SETTINGS[module]) | {'allocation_preference'})
            if unknown:
                raise ValueError(f'Unknown {module} strategy parameter: {", ".join(sorted(unknown))}.')
            for key, val in values.items():
                if key in LIMITS[module]:
                    low, high, cast = LIMITS[module][key]
                    number = finite(val, module+'.'+key, low, high)
                    if cast is int and number != int(number):
                        raise ValueError(f'{key} must be an integer.')
                    settings[module][key] = cast(number)
                elif key == 'allocation_preference':
                    settings[module][key] = finite(val, module+'.'+key, 0, 100)
                elif key == 'enabled':
                    if type(val) is not bool:
                        raise ValueError('Module enabled must be a boolean.')
                    settings[module][key] = val
                elif key == 'auditor_prompt':
                    if not isinstance(val, str) or len(val) > 12000:
                        raise ValueError('Auditor prompt must be text of at most 12000 characters.')
                    settings[module][key] = val.strip()
                # Descriptive strategy names/return aspirations are not executable settings.
        if settings['crypto']['exit_channel_periods'] >= settings['crypto']['entry_channel_periods']:
            raise ValueError('Crypto exit channel must be shorter than the entry channel.')
        result['module_settings_json'] = json.dumps(settings)
    if 'allocations' in payload or 'allocation_weights' in payload:
        values = payload.get('allocation_weights', payload.get('allocations'))
        if not isinstance(values, dict) or set(values) != set(MODULES):
            raise ValueError('Allocation weights must specify exactly the five asset modules.')
        weights = {k: finite(values[k], k+' weight', 0, 100) for k in MODULES}
        if abs(sum(weights.values())-100) > 0.000001 and sum(weights.values()) != 0:
            raise ValueError('Relative allocation weights must sum to 100%.')
        settings = loads(result.get('module_settings_json'), settings_for(cfg))
        effective = normalize_allocations(weights, settings)
        if 'allocation_weights' in payload and 'allocations' in payload:
            supplied = payload['allocations']
            if not isinstance(supplied, dict) or set(supplied) != set(MODULES):
                raise ValueError('Allocations must specify exactly the five asset modules.')
            if any(abs(finite(supplied[k], k+' allocation', 0, 100)-effective[k]) > 0.000001 for k in MODULES):
                raise ValueError('Allocations must match the enabled modules and relative weights.')
        result['allocations_json'] = json.dumps(weights)
    if 'master_ai_prompt' in payload:
        prompt = payload['master_ai_prompt']
        if not isinstance(prompt, str) or len(prompt) > 16000:
            raise ValueError('CIO prompt must be text of at most 16000 characters.')
        result['master_ai_prompt'] = prompt.strip() or DEFAULT_MASTER_CIO_PROMPT
    if 'master_ai_config' in payload:
        audit = payload['master_ai_config']
        if not isinstance(audit, dict) or set(audit)-{'cadence'} or audit.get('cadence') not in ('off', 'daily', 'weekly'):
            raise ValueError('Audit cadence must be off, daily or weekly.')
        saved = loads(getattr(cfg, 'master_ai_config', None), {})
        result['master_ai_config'] = json.dumps({**saved, **audit})
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


def event_risk_status(user_id, state, now):
    from event_algo_models import EventStrategyConfig
    from services.event_risk_policy import normalize_risk_config, entry_allowance
    event_cfg = EventStrategyConfig.query.filter_by(user_id=user_id).first()
    if event_cfg is None:
        return {'status': 'UNAVAILABLE', 'limits': {}, 'reason': 'No Event configuration is saved.'}
    try:
        allowance = entry_allowance(normalize_risk_config(event_cfg.risk_config),
            [lot for lot in current_lots(user_id, state, False) if lot.module == 'events'], now)
        return {'status': 'CONFIGURED', 'config_id': event_cfg.id, **allowance}
    except ValueError as exc:
        return {'status': 'INVALID', 'limits': {}, 'reason': str(exc)}


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
    if not settings_for(cfg)[module]['enabled']:
        return 0
    weights = allocations_for(cfg)
    reserve = sum(lot.collateral for lot in current_lots(cfg.user_id, state) if lot.module == module)
    # Current equity sets the bucket; available cash still bounds every entry.
    return max(0, max(0, acc.total_equity)*weights[module]/100-reserve)


def enter_lot(cfg, acc, state, module, symbol, signal, price, now, *, multiplier=1, margin=None, details=None, key=None, rejections=None):
    def reject(reason):
        if rejections is not None:
            rejections.append(reason)
        return None
    key = key or f'{module}:{symbol}:{utc(now).astimezone(ET).date()}'
    if Lot.query.filter_by(user_id=cfg.user_id, generation=state.generation, signal_key=key).first():
        return reject('Signal already consumed for this contract or trading day.')
    if any(lot.module == module and db.session.get(Position, lot.position_id).symbol == symbol for lot in current_lots(cfg.user_id, state)):
        return reject('An open position already exists for this symbol.')
    side = signal.get('side', 'LONG')
    price = fill_price(module, price, side)
    budget = min(module_budget(cfg, acc, state, module), acc.cash_balance)
    # Per-position maximum: 20% of a bucket, and 0.5% portfolio stop risk.
    weight = allocations_for(cfg)[module]
    fraction = 1.0 if module == 'futures' else 0.2
    budget = min(budget, max(0, acc.total_equity)*weight/100*fraction)
    max_loss = None
    max_contracts = 50
    if module == 'events':
        from event_algo_models import EventStrategyConfig
        from services.event_risk_policy import normalize_risk_config, entry_allowance
        details = details if details is not None else {}
        event_config_id = details.get('event_config_id')
        event_cfg = (db.session.get(EventStrategyConfig, event_config_id, populate_existing=True)
                     if event_config_id is not None else
                     EventStrategyConfig.query.filter_by(user_id=cfg.user_id).populate_existing().first())
        if not event_cfg or event_cfg.user_id != cfg.user_id or event_cfg.mode != 'PAPER' or not event_cfg.enabled or event_cfg.kill_switch:
            return reject('Saved Event configuration is unavailable or paused.')
        try:
            risk = normalize_risk_config(event_cfg.risk_config)
            allowance = entry_allowance(risk, [l for l in current_lots(cfg.user_id, state, False)
                                              if l.module == 'events'], now)
        except ValueError as exc:
            return reject(str(exc))
        details['event_risk_at_fill'] = allowance
        if allowance['reason']:
            return reject(allowance['reason'])
        budget = min(budget, allowance['entry_budget'])
        max_loss = allowance['remaining_loss_allowance']
        max_contracts = risk['max_contracts_per_trade']
        raw_depth = details.get('selected_ask_size')
        details['depth_status'] = 'UNKNOWN' if raw_depth is None else 'REPORTED'
        if raw_depth is not None:
            try:
                depth = float(raw_depth)
                if not math.isfinite(depth) or depth < 1:
                    return reject('Selected Event ask depth cannot fund one contract.')
                max_contracts = min(max_contracts, math.floor(depth))
            except (TypeError, ValueError):
                return reject('Selected Event ask depth is invalid.')
    unit = margin if margin is not None else price*multiplier
    if unit <= 0 or budget <= 0:
        return reject('Insufficient module budget or available cash.')
    stop = signal.get('stop')
    if module == 'futures':
        ceiling = settings_for(cfg)['futures']['max_intraday_loss']
        day_start = utc(now).astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
        day_pnl = sum(l.realized_pnl for l in current_lots(cfg.user_id, state, False) if l.module=='futures' and l.closed_at and utc(l.closed_at)>=day_start)
        open_risk = sum(abs(db.session.get(Position, l.position_id).average_cost-(l.stop_price or 0))*db.session.get(Position, l.position_id).quantity*l.multiplier + 2*l.entry_fee for l in current_lots(cfg.user_id, state) if l.module=='futures')
        max_loss = max(0, ceiling+min(day_pnl, 0)-open_risk)
    quantity = entry_quantity(module, price, budget, acc.total_equity, stop,
                              multiplier=multiplier, unit=unit, max_loss=max_loss, max_contracts=max_contracts)
    if quantity <= 0:
        return reject('Risk or margin budget cannot fund the minimum trade quantity.')
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
    _record_portfolio_log(cfg.user_id, 'POSITION_OPENED',
                          f'Opened {module} paper position ({symbol}): {quantity:g} at {price:.4f}.',
                          module=module, symbol=symbol, lot_id=lot.id, generation=state.generation)
    return lot


def check_circuit(cfg, acc, state):
    if acc.total_equity <= acc.initial_balance*0.9:
        if not state.kill_switch:
            snapshot(cfg, acc, state, datetime.utcnow())
        trigger_pause(cfg, state, 'Portfolio drawdown reached 10% of starting bankroll. New entries paused for review; continuous 24/7 market monitoring and viability tracking active.')
        return True
    return state.kill_switch


def trigger_pause(cfg, state, reason):
    newly = not state.kill_switch
    state.kill_switch = True
    state.pause_reason = reason
    # A risk pause blocks entries, not the owner's management of existing lots.
    # Explicit Stop and reset still revoke the lease in their own control paths.
    # Maintain cfg.enabled so 24/7 market data gathering and shadow viability tracking continue
    cfg.worker_status = 'MONITORING_ONLY'
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


def compute_sub_accounts(user_id, cfg, acc, state, positions, lots):
    """Compute segregated real-world non-IRA sub-accounts matching Webull architecture.

    Splits total baseline across:
      1. Individual Cash (Equities & Options)
      2. Crypto (Spot)
      3. Events Cash (Event Contracts)
      4. Futures (Micro Futures)
    """
    # Honor active enabled allocation weights dynamically (0% to disabled modules)
    normalized_weights = allocations_for(cfg)

    account_defs = [
        {
            'account_id': 'QUANT_ACC_INDIVIDUAL_CASH',
            'account_id_masked': '••••CASH',
            'account_name': 'Individual Cash',
            'account_label': 'Individual Cash (Equities & Options)',
            'account_type': 'CASH',
            'account_class': 'CASH',
            'modules': ['equities', 'options'],
            'instruments': ['EQUITY', 'OPTION'],
        },
        {
            'account_id': 'QUANT_ACC_CRYPTO',
            'account_id_masked': '••••CRYP',
            'account_name': 'Crypto',
            'account_label': 'Crypto (Spot)',
            'account_type': 'CASH',
            'account_class': 'CRYPTO',
            'modules': ['crypto'],
            'instruments': ['CRYPTO'],
        },
        {
            'account_id': 'QUANT_ACC_EVENTS',
            'account_id_masked': '••••EVNT',
            'account_name': 'Events Cash',
            'account_label': 'Events Cash (Event Contracts)',
            'account_type': 'CASH',
            'account_class': 'EVENT',
            'modules': ['events'],
            'instruments': ['EVENT'],
        },
        {
            'account_id': 'QUANT_ACC_FUTURES',
            'account_id_masked': '••••FUTR',
            'account_name': 'Futures',
            'account_label': 'Futures (Micro Futures)',
            'account_type': 'FUTURES',
            'account_class': 'FUTURES',
            'modules': ['futures'],
            'instruments': ['FUTURES'],
        },
    ]

    closed_lots = [l for l in lots if l.closed_at]
    open_lots = [l for l in lots if not l.closed_at]

    sub_accounts = []
    for ad in account_defs:
        w = sum(normalized_weights.get(m, 0.0) for m in ad['modules'])
        init_bal = round(acc.initial_balance * (w / 100.0), 2)
        acct_closed_lots = [l for l in closed_lots if l.module in ad['modules']]
        acct_open_lots = [l for l in open_lots if l.module in ad['modules']]
        acct_realized = sum(l.realized_pnl for l in acct_closed_lots)
        acct_collateral = sum(l.collateral for l in acct_open_lots)
        acct_positions = [p for p in positions if p.get('module') in ad['modules']]
        acct_unrealized = sum(p.get('unrealized_pnl', 0.0) for p in acct_positions)
        acct_market_val = sum(p.get('market_value', p.get('collateral', 0.0)) for p in acct_positions)
        acct_cash = max(0.0, round(init_bal + acct_realized - acct_collateral, 2))
        acct_equity = round(acct_cash + acct_collateral + acct_unrealized, 2)
        sub_accounts.append({
            'account_id': ad['account_id'],
            'account_id_masked': ad['account_id_masked'],
            'account_name': ad['account_name'],
            'account_label': ad['account_label'],
            'account_type': ad['account_type'],
            'account_class': ad['account_class'],
            'allocation_pct': round(w, 4),
            'initial_balance': init_bal,
            'cash_balance': acct_cash,
            'total_cash_balance': acct_cash,
            'settled_cash': acct_cash,
            'buying_power': acct_cash,
            'total_equity': acct_equity,
            'net_liquidation': acct_equity,
            'total_market_value': acct_market_val,
            'unrealized_profit_loss': acct_unrealized,
            'unrealized_profit_loss_rate': (acct_unrealized / init_bal * 100.0) if init_bal > 0 else 0.0,
            'realized_pnl': acct_realized,
            'modules': ad['modules'],
            'instruments': ad['instruments'],
            'is_paper': True,
            'is_quant': True,
        })
    return sub_accounts


def portfolio_status(user_id):
    cfg, acc, state = ensure_portfolio(user_id)
    lots = current_lots(user_id, state, False)
    positions = []
    for lot in lots:
        if lot.closed_at:
            continue
        p = db.session.get(Position, lot.position_id)
        positions.append({'id': p.id, 'module': lot.module, 'instrument_type': p.instrument_type, 'symbol': p.symbol, 'side': p.side, 'quantity': p.quantity,
            'average_cost': p.average_cost, 'mark': p.market_price, 'unrealized_pnl': p.unrealized_pnl, 'contract_multiplier': lot.multiplier,
            'market_value_usd': lot.collateral+p.unrealized_pnl,
            'collateral': lot.collateral, 'stop': lot.stop_price, 'target': lot.target_price,
            'marked_at': p.updated_at.isoformat()+'Z', 'details': loads(lot.details_json, {})})
        if lot.module == 'events':
            from event_algo_models import EventContractOutcome, EventMarketSnapshot
            outcome = EventContractOutcome.query.filter_by(user_id=user_id, contract_symbol=p.symbol).order_by(EventContractOutcome.updated_at.desc()).first()
            market = EventMarketSnapshot.query.filter_by(user_id=user_id, contract_symbol=p.symbol).order_by(EventMarketSnapshot.received_at.desc()).first()
            cutoff = outcome.cutoff_at if outcome else market.cutoff_at if market else None
            positions[-1]['purchased_outcome'] = positions[-1]['details'].get('outcome')
            positions[-1]['settlement'] = {
                'status': outcome.settlement_status if outcome else 'NOT_DUE' if cutoff and cutoff > datetime.utcnow() else 'UNKNOWN',
                'confirmed_outcome': outcome.outcome if outcome and outcome.settlement_status == 'RESOLVED' else None,
                'last_attempt_at': outcome.observed_at.isoformat()+'Z' if outcome and outcome.observed_at else None,
                'cutoff_at': cutoff.isoformat()+'Z' if cutoff else None,
                'expired': cutoff <= datetime.utcnow() if cutoff else None,
            }
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
    allocations = allocations_for(cfg)
    drift = []
    for module in MODULES:
        capital = sum(p['collateral']+p['unrealized_pnl'] for p in positions if p['module']==module)
        actual = capital/acc.total_equity*100 if acc.total_equity>0 else 0
        difference = actual-allocations[module]
        drift.append({'module': module, 'target_pct': allocations[module], 'actual_pct': actual, 'drift_pct': difference,
                      'signal': 'MANAGING_EXISTING' if not settings_for(cfg)[module]['enabled'] and capital else 'DISABLED' if not settings_for(cfg)[module]['enabled'] else 'TRIM' if difference>3 else 'AVAILABLE_CAPACITY' if difference < -3 else 'WITHIN_BAND',
                      'available_capital': module_budget(cfg, acc, state, module)})
    telemetry = loads(state.telemetry_json, {})
    module_settings = settings_for(cfg)
    for module in MODULES:
        item = telemetry.setdefault(module, {'status': 'IDLE', 'messages': [], 'evaluated': 0, 'entries': 0})
        item['enabled'] = module_settings[module]['enabled']
        if not item['enabled']:
            item['status'] = 'DISABLED'
            item['evaluated'] = item['entries'] = 0
        elif item['status'] in ('DISABLED', 'IDLE'):
            item['status'] = 'AWAITING_SCAN'
        elif item['status'] == 'SCANNED':
            item['status'] = 'READY'
    # Surface warm-up prerequisites even when the session gate prevents a scan.
    from portfolio_algo_models import PortfolioMarketObservation
    watches = loads(cfg.watchlists_json, DEFAULT_QUANT_WATCHLISTS)
    if module_settings['options']['enabled']:
        telemetry['options']['prerequisites'] = []
        for symbol in watches.get('options', []):
            count = PortfolioMarketObservation.query.filter_by(user_id=user_id, series='IV:'+symbol).filter(
                PortfolioMarketObservation.day >= datetime.utcnow().date()-timedelta(days=370),
                PortfolioMarketObservation.day <= datetime.utcnow().date(),
                PortfolioMarketObservation.source == 'WEBULL_OPTION_QUOTES',
                PortfolioMarketObservation.observed_at.isnot(None)).count()
            telemetry['options']['prerequisites'].append({
                'symbol': symbol, 'daily_iv_observations': min(count, 252), 'required': 252,
                'message': f'{symbol}: {min(count, 252)}/252 verified daily IV observations. Unverified legacy rows are retained but excluded. No historical IV import is configured; allocation remains unused until history and executable quotes qualify.',
            })
    event_open = [p for p in positions if p['module'] == 'events']
    risk_status = event_risk_status(user_id, state, datetime.utcnow())
    maximum = risk_status['limits'].get('max_open_positions')
    telemetry['events']['risk_policy'] = risk_status
    telemetry['events']['capacity'] = {'open_positions': len(event_open), 'maximum': maximum,
                                      'available_slots': max(0, maximum-len(event_open)) if maximum is not None else None}
    status = cfg.worker_status
    if cfg.enabled:
        # Starting is not a worker heartbeat: allow the supervisor time to claim work.
        since = cfg.updated_at if status == 'STARTING' else state.heartbeat_at
        if not since or datetime.utcnow()-since > timedelta(minutes=10):
            status = 'STALLED'
    realized = sum(l.realized_pnl for l in lots if l.closed_at)
    sub_accounts = compute_sub_accounts(user_id, cfg, acc, state, positions, lots)
    module_pnl = {m: sum(l.realized_pnl if l.closed_at else db.session.get(Position, l.position_id).unrealized_pnl-l.entry_fee
                         for l in lots if l.module == m) for m in MODULES}
    # Compare recorded valuations, not the browser clock advancing against stale marks.
    valuation_at = max(acc.reset_at, acc.updated_at, daily[-1].created_at if daily else acc.reset_at)
    goal = build_goal_tracking(initial_balance=acc.initial_balance, current_equity=acc.total_equity,
        cash_balance=acc.cash_balance, target_annual_return=cfg.target_annual_return,
        started_at=acc.reset_at, as_of=valuation_at,
        snapshots=[{'time': r.created_at, 'equity': r.equity} for r in metric_rows],
        module_pnl=module_pnl, reserved_capital=sum(p['collateral'] for p in positions))
    metrics['annualized_return_pct'] = goal['annualized_return_pct']
    calibration = event_calibration(user_id, acc.reset_at)
    return {'success': True, 'mode': 'PAPER', 'worker_status': status, 'enabled': cfg.enabled,
            'kill_switch': state.kill_switch, 'pause_reason': state.pause_reason,
            'heartbeat_at': state.heartbeat_at.isoformat()+'Z' if state.heartbeat_at else None,
            'last_scan_at': state.last_scan_at.isoformat()+'Z' if state.last_scan_at else None,
            'scan_interval_seconds': CADENCE,
            'generation': state.generation, 'modules': telemetry, 'positions': positions, 'open_positions_count': len(positions),
            'account': {'initial_balance': acc.initial_balance, 'cash_balance': acc.cash_balance, 'total_equity': acc.total_equity,
                        'currency': 'USD', 'realized_pnl': realized, 'unrealized_pnl': sum(p['unrealized_pnl'] for p in positions),
                        'return_pct': (acc.total_equity/acc.initial_balance-1)*100},
            'sub_accounts': sub_accounts,
            'module_enabled': {m: module_settings[m]['enabled'] for m in MODULES},
            'cash_allocation_pct': 0 if any(module_settings[m]['enabled'] for m in MODULES) else 100,
            'performance': metrics, 'goal_tracking': goal, 'event_calibration': calibration,
            'equity_curve': curve[-2000:], 'allocations': allocations, 'rebalance': drift}


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


def wipe_and_reset_portfolio(user_id, amount):
    """Permanently delete all historical paper data, orders, positions, snapshots, logs and reset bankroll."""
    amount = finite(amount, 'bankroll', 100, 1000000)
    ensure_portfolio(user_id)
    cfg, acc, state = locked(user_id)

    # 1. Permanently delete all quant trading history, orders, lots, positions, snapshots, audits, logs
    Order.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Lot.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Position.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Snapshot.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Audit.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PortfolioEngineLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    # 2. Reset engine state to generation 1
    state.generation = 1
    state.kill_switch = False
    state.pause_reason = None
    state.lease_token = None
    state.lease_until = None
    state.telemetry_json = '{}'
    state.last_scan_at = state.heartbeat_at = state.last_audit_at = None

    # 3. Reset config & account balances
    cfg.enabled = False
    cfg.worker_status = 'STOPPED'
    cfg.total_bankroll = amount
    acc.initial_balance = acc.cash_balance = acc.total_equity = amount
    acc.reset_at = datetime.utcnow()

    # 4. Take clean baseline snapshot
    snapshot(cfg, acc, state, acc.reset_at)
    _record_portfolio_log(user_id, 'ENGINE_WIPED_RESET', f'Quantitative strategy engine cleanly reset with ${amount:,.2f} bankroll. All previous trade data and reports wiped.')
    db.session.commit()
    return {'initial_balance': amount, 'cash_balance': amount, 'total_equity': amount, 'reset_at': acc.reset_at.isoformat()+'Z'}


def control(user_id, action):
    from event_algo import get_or_create_config
    ensure_portfolio(user_id)
    cfg, acc, state = locked(user_id)
    event_cfg = get_or_create_config(user_id)
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
        event_cfg.enabled = True
        event_cfg.kill_switch = False
        event_cfg.worker_status = 'STARTING'
        if not Snapshot.query.filter_by(user_id=user_id, generation=state.generation).first():
            snapshot(cfg, acc, state, datetime.utcnow())
    elif action == 'stop':
        cfg.enabled = False
        cfg.worker_status = 'STOPPED'
        event_cfg.enabled = False
        event_cfg.worker_status = 'STOPPED'
        state.lease_token = state.lease_until = None
    elif action == 'kill':
        trigger_pause(cfg, state, 'Administrator activated the portfolio kill switch. New entries paused; 24/7 monitoring active.')
        event_cfg.enabled = False
        event_cfg.kill_switch = True
        event_cfg.worker_status = 'KILLED'
    elif action == 'acknowledge':
        state.pause_reason = None
        if acc.total_equity <= acc.initial_balance*0.9:
            cfg.worker_status = 'MONITORING_ONLY'
            event_cfg.worker_status = 'MONITORING_ONLY'
        else:
            state.kill_switch = False
            cfg.worker_status = 'RUNNING' if cfg.enabled else 'STOPPED'
            event_cfg.kill_switch = False
            event_cfg.worker_status = 'RUNNING' if event_cfg.enabled else 'STOPPED'
    else:
        raise ValueError('Unknown worker action.')
    db.session.commit()


def monitoring_allowed(cfg, state):
    return cfg.mode == 'PAPER' and (cfg.enabled or (state.kill_switch and cfg.worker_status != 'STOPPED'))


def claim(user_id, force=False):
    cfg, acc, state = locked(user_id)
    now = datetime.utcnow()
    if not monitoring_allowed(cfg, state):
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
    cfg.worker_status = 'MONITORING_ONLY' if state.kill_switch else 'RUNNING'
    db.session.commit()
    return token


def owns(cfg, state, token):
    return monitoring_allowed(cfg, state) and state.lease_token == token and state.lease_until and state.lease_until > datetime.utcnow()


def event_inputs(user_id, state, now, watchlist, settings):
    from event_algo_models import EventStrategyDecision as Decision, EventMarketSnapshot as Market, EventStrategyConfig
    event_cfg = EventStrategyConfig.query.filter_by(user_id=user_id).first()
    if not event_cfg or not event_cfg.enabled:
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


def data_status(message):
    text = str(message).lower()
    if 'market_data_not_subscribed' in text:
        return 'SUBSCRIPTION_REQUIRED'
    if 'observations' in text or 'iv rank' in text or 'ivr' in text:
        return 'WARMING_UP'
    return 'DATA_LIMITED'


def run_scan(user_id, force=False, provider=None):
    token = claim(user_id, force)
    if not token:
        return {'success': False, 'message': 'Engine stopped, paused, busy, or not due.'}
    report = {m: {'status': 'IDLE', 'messages': [], 'evaluated': 0, 'entries': 0,
                  'qualified_signals': 0, 'rejected_entries': [], 'observations': []} for m in MODULES}
    try:
        from services.portfolio_strategy_data import PortfolioMarketData
        data = provider
        cfg, acc, state = locked(user_id)
        settings = settings_for(cfg)
        watches = loads(cfg.watchlists_json, DEFAULT_QUANT_WATCHLISTS)
        lot_ids = [l.id for l in current_lots(user_id, state)]
        db.session.commit()
        def market_data():
            nonlocal data
            if data is None:
                data = PortfolioMarketData(user_id)
            return data
        
        _record_portfolio_log(user_id, 'SCAN_START', 'Starting quantitative portfolio scan.')

        # Manage existing positions first, including symbols removed from the watchlist.
        for lot_id in lot_ids:
            lot = db.session.get(Lot, lot_id)
            if lot.closed_at is not None:
                continue
            pos = db.session.get(Position, lot.position_id)
            details = loads(lot.details_json, {})
            module, symbol, now = lot.module, pos.symbol, datetime.utcnow()
            try:
                if module in ('equities', 'options', 'futures') and not in_session(now):
                    continue
                reason, signal = None, None
                if module != 'events':
                    market_data()
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
                # An independent Event consumer may already have settled the
                # lot while this scan collected data. Refresh under the shared
                # state lock before marking/closing to avoid a double credit.
                lot = db.session.get(Lot, lot_id, populate_existing=True)
                if lot.closed_at is not None:
                    db.session.rollback()
                    continue
                pos = db.session.get(Position, lot.position_id, populate_existing=True)
                if module == 'events':
                    # Event marking reads only durable local quote/outcome
                    # records: repeat it under the shared ledger lock so a
                    # concurrent consumer's newer mark cannot be overwritten.
                    price, reason = mark_event(user_id, loads(lot.details_json, {}), datetime.utcnow())
                old_stop = lot.stop_price
                if module in ('equities', 'crypto'):
                    reason, lot.stop_price = spot_exit(module, price, pos.side, old_stop, signal)
                elif old_stop is not None and ((pos.side=='LONG' and price<=old_stop) or (pos.side=='SHORT' and price>=old_stop)):
                    reason = 'STOP_LOSS'
                mark_position(pos, lot, price)
                if module == 'futures':
                    bounds = utc(now).astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
                    daily = sum(l.realized_pnl for l in current_lots(user_id, state, False) if l.module=='futures' and l.closed_at and utc(l.closed_at)>=bounds)
                    floating = sum(db.session.get(Position, l.position_id).unrealized_pnl-l.entry_fee for l in current_lots(user_id, state) if l.module=='futures')
                    if daily+floating <= -settings[module]['max_intraday_loss']:
                        reason = 'DAILY_LOSS_LIMIT'
                if reason:
                    _record_portfolio_log(user_id, 'POSITION_CLOSED', f"Closing {module} lot {lot_id} ({symbol}) at {price:.4f}. Reason: {reason}")
                    close_lot(acc, lot, price, reason, now)
                balances(acc, state, user_id)
                if not check_circuit(cfg, acc, state) and lot.closed_at is None:
                    weights = allocations_for(cfg)
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
            if module == 'events':
                # Do not delay short-lived decisions behind this scan's provider
                # calls or overwrite telemetry from the independent consumer.
                continue
            if not settings[module]['enabled']:
                report[module]['status'] = 'DISABLED'
                continue
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
                        market_data()
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
                    is_held = check_circuit(cfg, acc, state) or not cfg.enabled or state.kill_switch
                    for entry_symbol, price, signal, details, key in entries:
                        report[module]['observations'].append({
                            'symbol': entry_symbol, 'observed_at': now.isoformat()+'Z', 'price': price,
                            'entry_qualified': bool(signal and signal.get('enter')),
                            'reason': (signal or {}).get('reason'),
                            'signal_checks': (signal or {}).get('checks', {}),
                            'dominance_filter_applies': entry_symbol != 'BTC' if module == 'crypto' else None,
                        })
                        if signal and signal.get('enter'):
                            report[module]['qualified_signals'] += 1
                            if is_held:
                                _record_portfolio_log(user_id, 'TRADE_VIABLE_HELD',
                                                      f"Qualified {module} setup detected on {entry_symbol} at {price:.4f} (viable signal; execution held in 24/7 monitoring mode). Reason: {signal.get('reason', 'Qualified')}")
                                report[module]['messages'].append(f"{entry_symbol}: Viable entry signal detected ({signal.get('reason', 'Qualified')}); execution held.")
                            else:
                                rejections = []
                                opened = enter_lot(cfg, acc, state, module, entry_symbol, signal, price, now, multiplier=multiplier, margin=margin, details=details, key=key, rejections=rejections)
                                if rejections:
                                    report[module]['rejected_entries'].append({'symbol': entry_symbol, 'reason': rejections[0]})
                                    _record_portfolio_log(user_id, 'ENTRY_SKIPPED', f'{entry_symbol}: {rejections[0]}', module=module, symbol=entry_symbol)
                                report[module]['entries'] += int(opened is not None)
                                balances(acc, state, user_id)
                    report[module]['evaluated'] += 1
                    report[module]['status'] = 'READY'
                    db.session.commit()
                except Exception as exc:
                    db.session.rollback()
                    report[module]['messages'].append(f'{watch_symbol}: {str(exc)[:200]}')
        cfg, acc, state = locked(user_id)
        if state.lease_token == token:
            report['events'] = loads(state.telemetry_json, {}).get('events', {
                'status': 'DATA_LIMITED' if settings['events']['enabled'] else 'DISABLED',
                'messages': ['Awaiting the independent Event handoff worker.'],
                'evaluated': 0, 'entries': 0,
            })
            if not settings['events']['enabled']:
                report['events']['status'] = 'DISABLED'
            _record_portfolio_log(user_id, 'SCAN_COMPLETE', 'Quantitative portfolio scan completed.')
            for module in MODULES:
                if module == 'events':
                    continue  # Independent consumer already classified its evidence.
                if report[module]['messages'] and settings[module]['enabled']:
                    err_msgs = [m for m in report[module]['messages'] if 'execution held' not in m]
                    if err_msgs:
                        report[module]['status'] = data_status(' '.join(err_msgs))
            state.telemetry_json = json.dumps(report)
            snapshot(cfg, acc, state, datetime.utcnow())
            check_circuit(cfg, acc, state)
            state.last_scan_at = state.heartbeat_at = datetime.utcnow()
            state.lease_token = state.lease_until = None
            if state.kill_switch:
                cfg.worker_status = 'MONITORING_ONLY'
            else:
                degraded = any(
                    report[m]['status'] in ('DATA_LIMITED', 'SUBSCRIPTION_REQUIRED')
                    for m in MODULES
                    if settings[m]['enabled']
                )
                cfg.worker_status = 'DEGRADED' if degraded else 'RUNNING'
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
    evidence = loads(row.evidence_json, {})
    warnings = []
    if row.status in ('SUCCESS', 'PARTIAL') and evidence.get('audit_context_version') != 3:
        warnings.append('This report predates v2.92.7 audit safeguards. Its AI prose may be incomplete or inaccurate; use the saved ledger evidence for facts or generate a fresh report.')
    return {'id': row.id, 'generation': row.generation, 'timestamp': row.created_at.isoformat()+'Z',
            'status': row.status, 'content': row.content, 'provider': row.provider, 'model': row.model,
            'evidence': evidence, 'validation_warnings': warnings,
            'progress': audit_progress(row.status, row.created_at.isoformat()+'Z', evidence)}


def save_audit_progress(audit_id, evidence, stage=None, module=None, **details):
    now = datetime.utcnow().isoformat()+'Z'
    progress = evidence.setdefault('audit_progress', {})
    if stage is not None:
        progress.update(stage=stage, current_module=module, stage_started_at=now,
                        provider=None, model=None, tier=None, event=None, retry_at=None)
    progress.update(details, updated_at=now)
    evidence['audit_progress_at'] = now
    row = db.session.get(Audit, audit_id)
    row.evidence_json = json.dumps(evidence)
    db.session.commit()


def audit_due(cfg, state, now):
    """Run once per completed daily close or first weekly NYSE close.

    Daily catch-up uses only the latest completed session. Weekly catch-up
    stays within the current Eastern calendar week. Manual requests bypass
    this check in reserve_audit.
    """
    cadence = loads(getattr(cfg, 'master_ai_config', None), {}).get('cadence', 'off')
    if cadence not in ('daily', 'weekly'):
        return False
    now = utc(now)
    today = now.astimezone(ET).date()
    if cadence == 'daily':
        days = (today - timedelta(days=offset) for offset in range(8))
    else:
        monday = today - timedelta(days=today.weekday())
        days = (monday + timedelta(days=offset) for offset in range(7))
    for day in days:
        bounds = session_bounds(day)
        if not bounds:
            continue
        close = utc(bounds[1])
        if close > now:
            if cadence == 'weekly':
                return False
            continue
        return state.last_audit_at is None or utc(state.last_audit_at) < close
    return False


def reserve_audit(user_id, scheduled=False):
    """Reserve one audit under the engine lock before dispatching provider work."""
    ensure_portfolio(user_id)
    cfg, acc, state = locked(user_id)
    now = datetime.utcnow()
    if scheduled and not audit_due(cfg, state, now):
        db.session.rollback()
        return None
    pending = Audit.query.filter_by(user_id=user_id, status='PENDING').all()
    for active in pending:
        progress = loads(active.evidence_json, {}).get('audit_progress_at')
        last_activity = utc(progress or active.created_at)
        from services.ai_service import audit_provider_timeout_seconds
        if utc(now)-last_activity < timedelta(seconds=max(900, audit_provider_timeout_seconds()+180)):
            db.session.rollback()
            raise ValueError('A portfolio audit is already running.')
    for stale in pending:
        stale.status = 'FAILED'
        stale.content = 'Audit interrupted or timed out; no verdict available.'
    row = Audit(user_id=user_id, generation=state.generation, created_at=now,
                content='Audit queued. Collecting portfolio evidence and module assessments.',
                evidence_json=json.dumps({'audit_progress': {'stage': 'queued',
                    'modules': [m for m, s in settings_for(cfg).items() if s['enabled']]}}))
    state.last_audit_at = now
    db.session.add(row)
    db.session.commit()
    return row.id


def audit_ai_kwargs(cfg):
    """Use the AI service's supported cascade, including dedicated keys/reasoning."""
    from credential_security import decrypt_secret
    config = loads(cfg.master_ai_config, {})
    tiers, keys = [], {}
    for name in ('primary', 'secondary', 'tertiary'):
        tier = config.get(name)
        if not isinstance(tier, dict) or not tier.get('provider'):
            continue
        provider = str(tier['provider']).strip().lower()
        tiers.append((name, provider, str(tier.get('model') or '').strip(),
                      str(tier.get('reasoning_level') or 'medium').strip().lower()))
        if tier.get('api_key'):
            keys[(name, provider)] = decrypt_secret(tier['api_key'])
    # Legacy portfolios with no dedicated tiers keep their configured global cascade.
    return {'custom_tier_configs': tiers, 'custom_api_keys': keys} if tiers else {}


def run_audit(user_id, prompt=None, scheduled=False, audit_id=None):
    if audit_id is None:
        audit_id = reserve_audit(user_id, scheduled)
    if audit_id is None:
        return None
    row = db.session.get(Audit, audit_id)
    if row is None or row.user_id != user_id:
        raise ValueError('Audit not found.')
    if row.status != 'PENDING':
        return audit_dict(row)
    cfg, _, state = ensure_portfolio(user_id)
    evidence = {}
    try:
        evidence = portfolio_status(user_id)
        if evidence['generation'] != row.generation:
            raise ValueError('Paper run changed while the audit was being prepared.')
        evidence.pop('equity_curve', None)
        enabled_modules = [m for m, s in settings_for(cfg).items() if s['enabled']]
        save_audit_progress(audit_id, evidence, 'preparing', modules=enabled_modules)
        watches = loads(cfg.watchlists_json, DEFAULT_QUANT_WATCHLISTS)
        evidence['watchlists'] = watches
        evidence['specialist_mandates'] = {m: settings_for(cfg)[m]['auditor_prompt'] for m in enabled_modules}
        evidence['correlations'] = [pair for pair in measured_correlations(user_id, state.generation)
                                    if pair['a'] in enabled_modules and pair['b'] in enabled_modules]
        evidence['enabled_allocations'] = {m: evidence['allocations'][m] for m in enabled_modules}
        evidence['cash_allocation'] = {
            'target_pct': evidence['cash_allocation_pct'],
            'actual_cash': evidence['account']['cash_balance'],
            'actual_cash_pct': (evidence['account']['cash_balance']/evidence['account']['total_equity']*100
                                if evidence['account']['total_equity'] > 0 else None),
        }
        evidence['target_annual_return'] = cfg.target_annual_return
        evidence['audit_schema_version'] = '2.95.0'
        evidence['audit_guidance'] = loads(cfg.master_ai_config, {}).get('audit_guidance')
        evidence['goal_tracking'].pop('curve', None)
        evidence['audit_context_version'] = 3
        evidence['as_of'] = datetime.utcnow().isoformat()+'Z'
        now = datetime.utcnow()
        local = utc(now).astimezone(ET)
        next_open = None
        for offset in range(8):
            bounds = session_bounds(local.date()+timedelta(days=offset))
            if bounds and bounds[0] > utc(now):
                next_open = bounds[0].astimezone(ET).isoformat()
                break
        evidence['exchange_session'] = {'as_of_eastern': local.isoformat(), 'open_now': in_session(now),
                                        'has_session_today': session_bounds(local.date()) is not None,
                                        'next_open_eastern': next_open}
        evidence['engine_purpose'] = ENGINE_PURPOSE
        evidence['risk_controls'] = {
            'portfolio_circuit_implemented': True, 'loss_of_starting_bankroll_pause_pct': 10,
            'new_entries_paused': state.kill_switch, 'pause_reason': state.pause_reason,
            'per_position_bucket_limit_pct': {'futures': 100, 'other_modules': 20}, 'modeled_stop_risk_portfolio_pct': 0.5,
            'event_risk_policy': evidence['modules'].get('events', {}).get('risk_policy'),
            'quote_max_age_seconds': 120,
            'cash_waits_for_qualified_signals': True,
            'correlations_and_ratios_automatically_calculated_after_30_daily_samples': True,
        }
        evidence['evidence_rules'] = EVIDENCE_RULES
        evidence['strategy_rules'] = {m: STRATEGY_RULES[m] for m in enabled_modules}
        evidence['strategy_settings'] = {m: {k: v for k, v in settings_for(cfg)[m].items()
                                              if k not in ('auditor_prompt', 'allocation_preference')} for m in enabled_modules}
        all_lots = current_lots(user_id, state, False)
        evidence['module_trade_results'] = {m: {
            'closed_trades': sum(l.module == m and l.closed_at is not None for l in all_lots),
            'realized_pnl_usd': sum(l.realized_pnl for l in all_lots if l.module == m and l.closed_at is not None),
            'open_positions': sum(p['module'] == m for p in evidence['positions']),
        } for m in MODULES}
        evidence['operational_summary'] = {}
        for module in enabled_modules:
            metrics = evidence['modules'][module]
            if metrics['status'] == 'MARKET_CLOSED':
                explanation = ('The exchange calendar is closed. The session gate skipped new-entry data requests '
                               'and signal evaluation. This is normal waiting, not evidence of missing price history '
                               'or a provider outage. Next open: ' + str(next_open) + '.')
            elif module == 'events':
                explanation = ('Use the independently timestamped Event consumer and upstream decision diagnostics. '
                               'An empty eligible-decision lookup is not evidence that market data or the AI provider succeeded. '
                               'Distinguish upstream no-signal, deferred/failed evaluations, stale/cutoff misses, risk holds and actual fills. '
                               'Report recorded counts only; watchlist size is not contracts evaluated.')
            elif metrics['status'] == 'READY':
                explanation = (f"The scan successfully evaluated {metrics.get('evaluated', 0)} watchlist symbols. "
                               f"{metrics.get('qualified_signals', 'Unknown')} signals qualified and "
                               f"{metrics.get('entries', 0)} entries filled. "
                               'Data collection and required indicator calculations succeeded for evaluated symbols. '
                               'If no signal qualified, cash correctly remains unused. Refer to signal_checks for '
                               'the actual conditions; no missing-history outage is recorded.')
            else:
                explanation = 'Use the recorded module status and diagnostic messages to identify the actual limitation.'
            if module == 'events':
                explanation += (' Event positions with NOT_DUE settlement are unexpired normal holdings. '
                                'Settlement-based exits are implemented; no stop/target price is required for them. '
                                'Only expired unresolved positions are settlement blockers. Capacity: ' +
                                json.dumps(metrics.get('capacity', {})))
            evidence['operational_summary'][module] = explanation
        evidence['verified_facts'] = {
            'maximum_drawdown': f"{evidence['performance']['max_drawdown_pct']:.6f}%",
            'total_equity': f"${evidence['account']['total_equity']:,.2f}",
            'cash': f"${evidence['account']['cash_balance']:,.2f}",
            'total_return': f"{evidence['account']['return_pct']:.6f}%",
            'event_market_value': f"${sum(p['market_value_usd'] for p in evidence['positions'] if p['module'] == 'events'):,.2f}",
            'open_position_counts': {m: sum(p['module'] == m for p in evidence['positions']) for m in MODULES},
        }
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
            ai_kwargs = audit_ai_kwargs(cfg)
            evidence['ai_cascade'] = [
                {'tier': tier, 'provider': provider, 'model': model, 'reasoning_level': reasoning}
                for tier, provider, model, reasoning in ai_kwargs.get('custom_tier_configs', [])
            ]
            prompt_interval = audit_prompt_interval_seconds()
            evidence['ai_prompt_execution'] = {
                'specialists_sequential': True,
                'master_after_all_specialists': True,
                'minimum_interval_seconds': prompt_interval,
            }
            _record_portfolio_log(user_id, 'AUDIT_START', 'Starting autonomous portfolio audit cascade.')
            module_responses, module_errors = {}, {}
            evidence['module_audits'] = module_responses
            evidence['module_audit_errors'] = module_errors
            row.evidence_json = json.dumps(evidence)
            db.session.commit()
            def observe_attempt(**event):
                from services.ai_provider_protocol import safe_provider_error
                if event.get('error'):
                    event['error'] = safe_provider_error(event['error'], ai_kwargs.get('custom_api_keys', {}).values())
                entry = {**event, 'at': datetime.utcnow().isoformat()+'Z',
                         'stage': evidence['audit_progress']['stage'],
                         'module': evidence['audit_progress'].get('current_module')}
                evidence.setdefault('provider_attempts', []).append(entry)
                save_audit_progress(audit_id, evidence, **{'retry_at': None, **event})

            last_prompt_finished_at = None
            for module in enabled_modules:
                wait_for_next_audit_prompt(last_prompt_finished_at, prompt_interval)
                _record_portfolio_log(user_id, 'AUDIT_MODULE', f'Running AI auditor for module: {module}')
                save_audit_progress(audit_id, evidence, 'module', module)
                module_watches = watches.get(module, [])
                recent_obs = evidence['modules'][module].get('observations', [])
                module_evidence = {
                    'module': module,
                    'as_of': evidence['as_of'],
                    'exchange_session': evidence['exchange_session'],
                    'operational_summary': evidence['operational_summary'][module],
                    'trade_results': evidence['module_trade_results'][module],
                    'target_annual_return': cfg.target_annual_return,
                    'net_contribution': next((item for item in evidence['goal_tracking']['module_contributions'] if item['module'] == module), None),
                    'event_calibration': evidence['event_calibration'] if module == 'events' else None,
                    'risk_controls': evidence['risk_controls'],
                    'strategy_rules': STRATEGY_RULES[module],
                    'strategy_settings': evidence['strategy_settings'][module],
                    'allocation': evidence['allocations'][module],
                    'metrics': evidence['modules'][module],
                    'watchlist': module_watches,
                    'watchlist_monitoring': recent_obs,
                    'positions': [p for p in evidence['positions'] if p['module'] == module],
                    'correlations': [c for c in evidence['correlations'] if c['a'] == module or c['b'] == module],
                }
                try:
                    response, _ = call_ai_with_web_search(
                        username=user.username, user_id=user_id,
                        messages=[{'role': 'system', 'content': audit_system_prompt(evidence['specialist_mandates'][module], module, guidance=evidence['audit_guidance'])},
                                  {'role': 'user', 'content': json.dumps(module_evidence)}],
                        prompt_type='portfolio_module_audit', symbol=module.upper(), include_db_context=False,
                        attempt_observer=observe_attempt,
                        **ai_kwargs)
                    text = str(getattr(response, 'text', '') or '').strip()
                    if not text:
                        raise ValueError('AI provider returned an empty module assessment.')
                    module_responses[module] = text
                    evidence.setdefault('module_providers', {})[module] = {
                        'provider': getattr(response, 'provider', None), 'model': getattr(response, 'model', None)}
                    evidence.setdefault('module_audit_inputs', {})[module] = module_evidence
                except Exception as exc:
                    db.session.rollback()
                    module_responses[module] = None
                    module_errors[module] = str(exc)[:300]
                    if getattr(exc, 'partial_text', None):
                        evidence.setdefault('incomplete_module_outputs', {})[module] = exc.partial_text
                    _record_portfolio_log(user_id, 'AUDIT_MODULE_FAILED',
                                          f'{module} assessment unavailable: {module_errors[module]}', level='WARNING')
                row = db.session.get(Audit, audit_id)
                evidence['audit_progress_at'] = datetime.utcnow().isoformat()+'Z'
                row.evidence_json = json.dumps(evidence)
                db.session.commit()
                last_prompt_finished_at = time.monotonic()
                save_audit_progress(audit_id, evidence, event='spacing', provider=None, model=None,
                    retry_at=(datetime.utcnow()+timedelta(seconds=prompt_interval)).isoformat()+'Z')

            wait_for_next_audit_prompt(last_prompt_finished_at, prompt_interval)
            _record_portfolio_log(user_id, 'AUDIT_MASTER', 'Synthesizing module insights via Master CIO.')
            save_audit_progress(audit_id, evidence, 'master')
            response, _ = call_ai_with_web_search(
                username=user.username, user_id=user_id,
                messages=[{'role': 'system', 'content': audit_system_prompt(prompt or cfg.master_ai_prompt or DEFAULT_MASTER_CIO_PROMPT, guidance=evidence['audit_guidance'])},
                          {'role': 'user', 'content': json.dumps({k: v for k, v in evidence.items()
                            if k not in ('module_audit_inputs', 'incomplete_module_outputs', 'provider_attempts', 'audit_progress')})}],
                prompt_type='portfolio_audit', symbol='PORTFOLIO', include_db_context=False,
                attempt_observer=observe_attempt,
                **ai_kwargs)
            save_audit_progress(audit_id, evidence, 'finalizing')
            content = str(getattr(response, 'text', '') or '').strip()
            if not content:
                raise ValueError('AI provider returned an empty portfolio report.')
            check_drawdown_claim(content, evidence)
            provider, model = getattr(response, 'provider', None), getattr(response, 'model', None)
            status = 'PARTIAL' if module_errors else 'SUCCESS'
            _record_portfolio_log(user_id, 'AUDIT_COMPLETE',
                                  'Portfolio audit completed with module limitations.' if module_errors else 'Master CIO audit successfully completed.')
        if not content:
            content = ('AI audit unavailable. Measured portfolio equity: '
                       f"${evidence['account']['total_equity']:,.2f}. Observed maximum drawdown: "
                       f"{evidence['performance']['max_drawdown_pct']:.2f}%. "
                       'Review the evidence and module diagnostics below. No forecast, correlation estimate or stress-test result has been generated.')
        row = db.session.get(Audit, audit_id)
        row.content, row.status, row.provider, row.model = content, status, provider, model
        evidence.setdefault('audit_progress', {})['finished_at'] = datetime.utcnow().isoformat()+'Z'
        row.evidence_json = json.dumps(evidence)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        row = db.session.get(Audit, audit_id)
        row.status = 'FAILED'
        row.content = f'AI audit failed: {str(exc)[:300]}. No quantitative verdict was generated. Preserved evidence and completed module assessments are available below.'
        evidence['audit_error'] = str(exc)[:300]
        evidence.setdefault('audit_progress', {})['finished_at'] = datetime.utcnow().isoformat()+'Z'
        if getattr(exc, 'partial_text', None):
            evidence['incomplete_master_output'] = exc.partial_text
        row.evidence_json = json.dumps(evidence)
        _record_portfolio_log(user_id, 'AUDIT_FAILED', f'Portfolio audit {audit_id} failed: {str(exc)[:300]}', level='ERROR')
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
                users = [c.user_id for c in Config.query.filter_by(mode='PAPER').all()
                         if c.enabled or (db.session.get(State, c.user_id) and db.session.get(State, c.user_id).kill_switch)]
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
