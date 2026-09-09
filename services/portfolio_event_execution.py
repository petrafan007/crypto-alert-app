"""Timely, paper-only Event handoff independent of slow portfolio scans.

Provider reads occur outside transactions. Every ledger mutation uses the same
State row lock as the supervisor and rechecks generation and controls. The main
scan's lease is deliberately untouched; no Event operation submits a broker order.
"""
import json
import logging
import threading
from datetime import datetime, timedelta

from core.extensions import db
from event_algo_models import EventMarketSnapshot, EventStrategyConfig, EventStrategyDecision, EventStrategyRun
from services import portfolio_engine as engine

logger = logging.getLogger(__name__)
_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()
DECISION_TTL_SECONDS = 120


def disposition(decision, generation):
    value = engine.loads(decision.feature_json, {}).get('portfolio_execution', {})
    return value if value.get('generation') == generation else {}


def record_disposition(decision, generation, status, reason, now, **details):
    features = engine.loads(decision.feature_json, {})
    result = {'generation': generation, 'status': status, 'reason': reason,
              'recorded_at': now.isoformat() + 'Z', **details}
    features['portfolio_execution'] = result
    decision.feature_json = json.dumps(features)
    engine._record_portfolio_log(decision.user_id, 'EVENT_HANDOFF_' + status,
        f'{decision.contract_symbol}: {reason}', module='events',
        decision_id=decision.id, generation=generation, disposition=result)
    return result


def fresh_market(user_id, decision):
    """Fetch only this contract's current quote; never refetch a broad catalog."""
    from event_algo import _webull_connection_for_user
    from services.webull_service import get_webull_event_snapshots
    snapshot = db.session.get(EventMarketSnapshot, decision.snapshot_id)
    market = engine.loads(snapshot.raw_json, {}) if snapshot else {}
    credential, environment = _webull_connection_for_user(user_id)
    app_key, app_secret, access_token = credential.webull_app_key, credential.webull_app_secret, credential.webull_access_token
    symbol = decision.contract_symbol
    db.session.commit()  # Release read transaction before provider I/O.
    quote = get_webull_event_snapshots(app_key, app_secret, environment, access_token,
                                      symbols=[symbol], force=True).get(symbol)
    if not quote:
        raise ValueError('Provider returned no fresh executable Event quote.')
    # Do not retain old executable fields if the new quote omits them.
    for field in ('yes_bid', 'yes_ask', 'no_bid', 'no_ask', 'quote_as_of', 'timestamp',
                  'last_trade_time', 'trade_time', 'updated_at'):
        market.pop(field, None)
    market.update(quote)
    market['symbol'] = symbol
    return market


def validate_entry(decision, market, event_cfg, settings, watchlist, now):
    """Reapply original decision gates against the new quote, without new AI."""
    from event_algo import _market_cutoff, _market_provider_timestamp, evaluate_market
    age = (now - decision.created_at).total_seconds()
    if age < -5 or age > DECISION_TTL_SECONDS:
        return 'MISSED', 'Decision exceeded its 120-second freshness window.', None
    if not market or market.get('symbol') != decision.contract_symbol:
        return 'REJECTED', 'Fresh quote did not match the exact decision contract.', None
    provider_time = _market_provider_timestamp(market)
    if not provider_time or not -5 <= (now - provider_time).total_seconds() <= 30:
        return 'MISSED', 'Fresh quote has no usable as-of timestamp or is older than 30 seconds.', None
    cutoff = _market_cutoff(market)
    if not cutoff or cutoff <= now + timedelta(seconds=30):
        return 'MISSED', 'Contract entered the cutoff exclusion window.', None
    if market.get('series_symbol') not in watchlist and not any(
            decision.contract_symbol.startswith(symbol + '-') for symbol in watchlist):
        return 'REJECTED', 'Contract is not in the enabled Event watchlist.', None
    if (decision.confidence or 0) < settings['min_confidence']:
        return 'REJECTED', 'Decision confidence is below the portfolio threshold.', None
    refreshed = {**market, 'model_probability_yes': decision.probability_yes,
                 'model_confidence': decision.confidence}
    assessment = evaluate_market(refreshed, event_cfg, now=now)
    if not assessment['eligible']:
        return 'REJECTED', 'Fresh quote failed Event gates: ' + ', '.join(assessment['reason_codes']), assessment
    if assessment['outcome'] != decision.outcome:
        return 'REJECTED', 'Fresh quote changed the qualified outcome; await a new decision.', assessment
    # evaluate_market includes configured fee, spread and uncertainty. Also
    # reserve at least the ledger's actual paper commission if configured lower.
    from event_algo import DEFAULT_SIGNAL_CONFIG
    signal_cfg = engine.loads(event_cfg.signal_config, DEFAULT_SIGNAL_CONFIG)
    fee_gap = max(0, engine.costs('events', assessment['executable_price'], 1)
                  - float(signal_cfg.get('fee_per_contract', DEFAULT_SIGNAL_CONFIG['fee_per_contract'])))
    if assessment['net_edge'] - fee_gap < settings['min_net_edge']:
        return 'REJECTED', 'Fresh executable quote no longer meets net edge after all costs.', assessment
    return None, None, assessment


def readiness(user_id, event_cfg, now):
    """A successful empty lookup does not certify functioning market/model data."""
    if not event_cfg or not event_cfg.enabled:
        return 'DATA_LIMITED', 'Event decision producer is not running.'
    run = EventStrategyRun.query.filter_by(user_id=user_id, config_id=event_cfg.id).order_by(EventStrategyRun.started_at.desc()).first()
    if not run or not run.finished_at or (now - run.finished_at).total_seconds() > 600:
        return 'DATA_LIMITED', 'No recently completed Event producer scan.'
    if run.error_count or run.error_message or run.status not in ('COMPLETED', 'DEGRADED'):
        return 'DATA_LIMITED', 'Event producer reports upstream errors or an incomplete scan.'
    decisions = EventStrategyDecision.query.filter_by(user_id=user_id, run_id=run.id).all()
    recent = [row for row in decisions if (now - row.created_at).total_seconds() <= DECISION_TTL_SECONDS]
    if not recent:
        return 'DATA_LIMITED', 'No fresh Event decisions; waiting for market/model observations.'
    unavailable = {'AI_PROVIDER_ERROR', 'AI_RESPONSE_INVALID', 'AI_BUDGET_EXHAUSTED',
                   'MODEL_UNAVAILABLE', 'STALE_QUOTE', 'MISSING_QUOTE'}
    if any(unavailable.intersection(engine.loads(row.reason_codes, [])) for row in recent):
        return 'DATA_LIMITED', 'Latest Event scan contains unavailable model or quote evidence.'
    if any(row.eligible for row in recent):
        return 'READY', 'Fresh eligible Event decisions evaluated.'
    if all('AI_EVALUATION_DEFERRED' in engine.loads(row.reason_codes, []) for row in recent):
        return 'NO_SIGNAL', 'Fresh contract quotes evaluated; AI evaluation is deferred pending batch cadence.'
    return 'NO_SIGNAL', 'Fresh markets and model decisions evaluated; no entry met the saved gates.'


def consume_event_decisions(user_id, *, decision_ids=None, quote_loader=None):
    """Process eligible decisions immediately; at most one active call per process."""
    with _ACTIVE_LOCK:
        if user_id in _ACTIVE:
            return {'success': False, 'message': 'Event handoff already active; periodic consumer will retry.'}
        _ACTIVE.add(user_id)
    try:
        return _consume(user_id, decision_ids=decision_ids, quote_loader=quote_loader or fresh_market)
    except Exception:
        db.session.rollback()
        logger.exception('Portfolio Event handoff failed for user %s', user_id)
        return {'success': False, 'message': 'Event handoff failed; see worker logs.'}
    finally:
        _ACTIVE.discard(user_id)


def _consume(user_id, *, decision_ids, quote_loader):
    if not db.session.get(engine.State, user_id):
        return {'success': False, 'message': 'No quantitative portfolio configured.'}
    cfg, acc, state = engine.locked(user_id)
    if not engine.monitoring_allowed(cfg, state):
        db.session.rollback()
        return {'success': False, 'message': 'Portfolio stopped; ledger unchanged.'}
    generation, reset_at = state.generation, acc.reset_at
    query = EventStrategyDecision.query.filter_by(user_id=user_id, eligible=True).filter(
        EventStrategyDecision.created_at >= reset_at)
    if decision_ids is not None:
        query = query.filter(EventStrategyDecision.id.in_(decision_ids))
    ids = [row.id for row in query.order_by(EventStrategyDecision.created_at.desc()).limit(500).all()
           if not disposition(row, generation)]
    db.session.commit()
    processed = []
    for decision_id in ids:
        cfg, acc, state = engine.locked(user_id)
        if state.generation != generation or not engine.monitoring_allowed(cfg, state):
            db.session.rollback()
            break
        decision = db.session.get(EventStrategyDecision, decision_id)
        if not decision or disposition(decision, generation):
            db.session.rollback()
            continue
        now = datetime.utcnow()
        settings = engine.settings_for(cfg)['events']
        event_cfg = db.session.get(EventStrategyConfig, decision.config_id)
        engine.balances(acc, state, user_id)
        held = engine.check_circuit(cfg, acc, state) or not cfg.enabled or not settings['enabled'] or not event_cfg or not event_cfg.enabled or event_cfg.kill_switch or event_cfg.mode != 'PAPER'
        existing = engine.Lot.query.filter_by(user_id=user_id, generation=generation,
            signal_key=f'events:{decision.contract_symbol}').first()
        if held or existing or (now - decision.created_at).total_seconds() > DECISION_TTL_SECONDS:
            status, reason = ('HELD', 'New Event entries are paused or disabled.') if held else (
                ('REJECTED', 'Contract already consumed by the paper ledger.') if existing else
                ('MISSED', 'Decision exceeded its 120-second freshness window.'))
            processed.append(record_disposition(decision, generation, status, reason, now))
            db.session.commit()
            continue
        db.session.commit()
        quote_started = datetime.utcnow()
        try:
            market = quote_loader(user_id, decision)
            quote_error = None
        except Exception as exc:
            market, quote_error = None, str(exc)[:300]
            db.session.rollback()
        cfg, acc, state = engine.locked(user_id)
        if state.generation != generation or not engine.monitoring_allowed(cfg, state):
            db.session.rollback()
            break
        decision = db.session.get(EventStrategyDecision, decision_id, populate_existing=True)
        if not decision or disposition(decision, generation):
            db.session.rollback()
            continue
        now = datetime.utcnow()
        event_cfg = db.session.get(EventStrategyConfig, decision.config_id, populate_existing=True)
        settings = engine.settings_for(cfg)['events']
        engine.balances(acc, state, user_id)
        held = engine.check_circuit(cfg, acc, state) or not cfg.enabled or not settings['enabled'] or not event_cfg or not event_cfg.enabled or event_cfg.kill_switch or event_cfg.mode != 'PAPER'
        assessment = None
        if held:
            status, reason = 'HELD', 'Controls changed during quote refresh; entry held.'
        elif quote_error:
            status, reason = 'REJECTED', 'Fresh provider quote unavailable: ' + quote_error
        elif (now - quote_started).total_seconds() > DECISION_TTL_SECONDS:
            status, reason = 'MISSED', 'Quote collection exceeded the 120-second freshness window.'
        else:
            watches = engine.loads(cfg.watchlists_json, engine.DEFAULT_QUANT_WATCHLISTS)['events']
            status, reason, assessment = validate_entry(decision, market, event_cfg, settings, watches, now)
        details = {'decision_id': decision.id, 'contract_symbol': decision.contract_symbol, 'outcome': decision.outcome}
        if status is None:
            from event_algo import _snapshot_model, _market_features
            # Preserve the exact fresh quote used for the fill and subsequent
            # marking; retaining only the stale producer snapshot is misleading.
            quote_row = _snapshot_model(user_id, event_cfg.id, decision.run_id, market, _market_features(market, now), now)
            db.session.add(quote_row)
            db.session.flush()
            price = assessment['executable_price']
            details.update({'quote_snapshot_id': quote_row.id, 'quote_refreshed_at': now.isoformat() + 'Z', 'net_edge_at_fill': assessment['net_edge']})
            rejections = []
            lot = engine.enter_lot(cfg, acc, state, 'events', decision.contract_symbol[:64],
                {'enter': True, 'side': 'LONG', 'reason': 'Freshly revalidated Event probability signal'}, price, now,
                details=details, key=f'events:{decision.contract_symbol}', rejections=rejections)
            if lot:
                status, reason = 'FILLED', 'Qualified decision filled after fresh executable quote revalidation.'
                details.update({'lot_id': lot.id, 'fill_price': price})
            else:
                status, reason = 'REJECTED', rejections[0] if rejections else 'Paper ledger rejected the entry.'
        processed.append(record_disposition(decision, generation, status, reason, now, **details))
        engine.balances(acc, state, user_id)
        db.session.commit()
    # Manage existing Event risk even if its entry module is disabled/paused.
    cfg, acc, state = engine.locked(user_id)
    if state.generation != generation or not engine.monitoring_allowed(cfg, state):
        db.session.rollback()
        return {'success': False, 'message': 'Portfolio ownership/reset state changed.'}
    now = datetime.utcnow()
    messages = []
    ledger_changed = False
    for lot in engine.current_lots(user_id, state):
        if lot.module != 'events':
            continue
        try:
            price, reason = engine.mark_event(user_id, engine.loads(lot.details_json, {}), now)
            position = db.session.get(engine.Position, lot.position_id)
            ledger_changed = ledger_changed or position.market_price != price or bool(reason)
            engine.mark_position(position, lot, price)
            if reason:
                engine.close_lot(acc, lot, price, reason, now)
        except ValueError as exc:
            messages.append(f'Lot {lot.id}: {exc}')
    engine.balances(acc, state, user_id)
    engine.check_circuit(cfg, acc, state)
    event_cfg = EventStrategyConfig.query.filter_by(user_id=user_id).first()
    status, message = readiness(user_id, event_cfg, now)
    if not engine.settings_for(cfg)['events']['enabled']:
        status, message = 'DISABLED', 'Event entries disabled; existing risk continues to be managed.'
    telemetry = engine.loads(state.telemetry_json, {})
    previous = telemetry.get('events', {})
    history = (previous.get('handoff_dispositions', []) + processed)[-50:]
    counts = previous.get('handoff_counts', {})
    for item in processed:
        counts[item['status']] = counts.get(item['status'], 0) + 1
    telemetry['events'] = {**previous, 'status': status, 'messages': [message] + messages,
        'consumer_heartbeat_at': now.isoformat() + 'Z', 'execution_path': 'INDEPENDENT_EVENT_HANDOFF',
        'last_handoff_at': now.isoformat() + 'Z' if processed else previous.get('last_handoff_at'),
        'evaluated': len(processed) if processed else previous.get('evaluated', 0),
        'entries': sum(row['status'] == 'FILLED' for row in processed) if processed else previous.get('entries', 0),
        'handoff_dispositions': history, 'handoff_counts': counts,
        'entries_paused': bool(state.kill_switch or not cfg.enabled or not engine.settings_for(cfg)['events']['enabled']),
        'qualified_signals': len(processed) if processed else previous.get('qualified_signals', 0),
        'rejected_entries': [row for row in history if row['status'] != 'FILLED']}
    state.telemetry_json = json.dumps(telemetry)
    if processed or ledger_changed:
        engine.snapshot(cfg, acc, state, now)
    db.session.commit()
    return {'success': True, 'processed': processed, 'status': status}


def portfolio_event_worker_loop(app, stop_event=None):
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        with app.app_context():
            try:
                from credentials import User
                from event_algo import is_event_strategy_admin
                users = [cfg.user_id for cfg in engine.Config.query.filter_by(mode='PAPER').all()]
                for user_id in users:
                    if is_event_strategy_admin(db.session.get(User, user_id)):
                        consume_event_decisions(user_id)
            except Exception:
                db.session.rollback()
                logger.exception('Independent Event supervisor iteration failed')
            finally:
                db.session.remove()
        stop_event.wait(15)
