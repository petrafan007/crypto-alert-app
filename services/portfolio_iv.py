"""Versioned ATM IV sampling; old methodologies cannot satisfy warm-up."""
import math
from services.portfolio_strategy_signals import utc, ET, session_bounds


def iv_source(target_dte):
    return f'WEBULL_ATM_PAIR_V1_DTE{int(target_dte)}'


def iv_series(symbol, target_dte):
    return f'IV:ATM_PAIR_V1:D{int(target_dte)}:{symbol}'


def atm_pair(contracts, price):
    pairs = {}
    for row in contracts:
        try:
            value = float(row['implied_volatility'])
            if isinstance(row['implied_volatility'], bool) or not math.isfinite(value) or not 0 < value < 10:
                continue
            pairs.setdefault(row['strike'], {})[row['option_type']] = value
        except (KeyError, TypeError, ValueError):
            continue
    valid = [(strike, pair) for strike, pair in pairs.items() if 'CALL' in pair and 'PUT' in pair]
    if not valid:
        raise ValueError('A quoted call/put pair at the same strike is required for measured ATM IV.')
    strike, pair = min(valid, key=lambda item: (abs(item[0]-price), item[0]))
    return (pair['CALL']+pair['PUT'])/2


def collection_window(now):
    stamp = utc(now)
    bounds = session_bounds(stamp.astimezone(ET).date())
    return bool(bounds and 0 < (bounds[1]-stamp).total_seconds() <= 900)
