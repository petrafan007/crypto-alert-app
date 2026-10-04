"""Bounded Event model requests and deterministic eligibility checks."""
import json

MAX_BATCH_CONTRACTS = 2
SCOPE_EXCLUSIONS = frozenset({'CONTRACT_EXPIRED', 'MARKET_NOT_OPEN',
                            'TOO_CLOSE_TO_EXPIRATION', 'TOO_FAR_FROM_EXPIRATION'})
PREFLIGHT_GATES = SCOPE_EXCLUSIONS | {'KILL_SWITCH', 'MARKET_STATUS_UNKNOWN',
    'STALE_QUOTE', 'MISSING_QUOTE', 'CROSSED_QUOTE', 'SPREAD_TOO_WIDE', 'INSUFFICIENT_LIQUIDITY'}

def scope_excluded(market, config, now):
    from event_algo import evaluate_market
    return bool(SCOPE_EXCLUSIONS.intersection(evaluate_market(
        {**market, '_model_metadata': {}}, config, now=now)['reason_codes']))


def inference_preflight(market, config, now):
    """Spend no AI request when neither outcome can pass known entry gates.

    Evaluate both extreme probabilities solely to select each possible book.
    These probe values are never saved, returned as forecasts, or traded.
    """
    from event_algo import _market_cutoff, evaluate_market
    from services.event_market_timing import quote_freshness
    if _market_cutoff(market) is None:
        return ['DATA_ERROR']
    blocked = []
    for probability in (1.0, 0.0):
        probe = {**market, 'model_probability_yes': probability, 'model_confidence': 1.0,
                 '_model_metadata': {}}
        reasons = set(PREFLIGHT_GATES.intersection(evaluate_market(probe, config, now=now)['reason_codes']))
        if quote_freshness(market, now)['status'] != 'FRESH':
            reasons.add('STALE_QUOTE')
        if not reasons:
            return []
        blocked.extend(sorted(reasons))
    return list(dict.fromkeys(blocked))


def skip_metadata(reasons):
    return {'status': 'skipped', 'preflight_reasons': reasons,
            'error': 'AI not requested: known entry gates failed (' + ', '.join(reasons) + ')'}


def strict_batch_predictions(text, expected_symbols):
    """Validate the complete response, never rescue fragments from broken JSON."""
    import math
    import re
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        raw = str(text).strip()
        fenced = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', raw, re.IGNORECASE | re.DOTALL)
        payload = json.loads(fenced.group(1) if fenced else raw, object_pairs_hook=unique_keys)
        if not isinstance(payload, dict) or set(payload) != {'predictions'}:
            return {}
        rows = payload['predictions']
        if not isinstance(rows, list) or len(rows) != len(expected_symbols):
            return {}
        predictions = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'contract_symbol', 'probability_yes', 'confidence', 'rationale'}:
                return {}
            symbol = row['contract_symbol']
            if not isinstance(symbol, str) or symbol not in expected_symbols or symbol in predictions:
                return {}
            for field in ('probability_yes', 'confidence'):
                value = row[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    return {}
            if not isinstance(row['rationale'], str) or not row['rationale'].strip():
                return {}
            predictions[symbol] = {key: row[key] for key in ('probability_yes', 'confidence', 'rationale')}
        return predictions if set(predictions) == set(expected_symbols) else {}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {}
