"""Observe deterministic crypto decisions. This module cannot authorize trades."""
import json
import logging
from services.jev_evaluations import utc, create_evaluation

logger = logging.getLogger(__name__)


def build_quant_state(symbol, price, signal, decision_time, portfolio=None):
    # Copy only authoritative, already-computed features, never recompute bars.
    copied = {k: signal.get(k) for k in ('enter', 'exit', 'reason', 'stop', 'side', 'checks')}
    state = {'symbol': symbol, 'instrument_type': 'CRYPTO', 'market_source': 'webull', 'timeframe': '1h',
             'decision_time': utc(decision_time).isoformat(), 'current_price': float(price),
             'forecast_horizon_hours': 24, 'base_signal': copied,
             'portfolio': portfolio or {}, 'outcome_contract': 'return-v1: downside <=-2%'}
    return json.loads(json.dumps(state, allow_nan=False))


def queue_shadow(user_id, state, settings, baseline):
    if not settings['jev_enabled'] or not settings['jev_quant_shadow_enabled']:
        return None
    try:
        return create_evaluation(user_id, 'quant_crypto', state, settings, base_signal=state['base_signal'],
                                 baseline=baseline)
    except Exception:
        logger.warning('Jev quant shadow observation could not be queued.')
        return None
