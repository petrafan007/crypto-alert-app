"""Public, exact-contract settlement evidence for Webull-listed Kalshi markets.

Docs: https://docs.kalshi.com/api-reference/market/get-market
No account credentials, quote-derived outcomes or broker orders are used.
"""
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests


def validated_kalshi_market(symbol, cutoff_at, market, observed_at):
    """Validate saved or fresh exact-contract evidence without making requests."""
    from services.event_market_timing import observation_time

    cutoff, observed = observation_time(cutoff_at), observation_time(observed_at)
    if (not isinstance(market, dict) or cutoff is None or observed is None or cutoff > observed
            or market.get('ticker') != symbol or market.get('market_type') != 'binary'
            or market.get('status') != 'finalized' or market.get('is_provisional')
            or market.get('result') not in ('yes', 'no')):
        return None
    try:
        # Provider timestamps must establish an instant, including a timezone.
        close = datetime.fromisoformat(market['close_time'].replace('Z', '+00:00'))
        settled = datetime.fromisoformat(market['settlement_ts'].replace('Z', '+00:00'))
        value = market['settlement_value_dollars']
        payout = float(value)
        if isinstance(value, bool) or close.tzinfo is None or settled.tzinfo is None:
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if (abs((close-cutoff).total_seconds()) > 1 or settled < close or settled > observed
            or payout != (1.0 if market['result'] == 'yes' else 0.0)):
        return None
    return {'settled_outcome': market['result'].upper(), 'settlement_price': payout,
            'payout_date': settled.astimezone(timezone.utc).isoformat(),
            'provider_timestamp': settled.astimezone(timezone.utc).isoformat(), 'market': market}


def confirmed_kalshi_settlement(symbol, cutoff_at, now=None):
    if not re.fullmatch(r'KX[A-Z0-9]+-\d{2}[A-Z]{3}\d{4}[A-Z0-9.-]*', symbol or '') or not cutoff_at:
        return None
    now = now or datetime.now(timezone.utc)
    def aware(value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if aware(cutoff_at) > aware(now):
        return None
    base = 'https://external-api.kalshi.com/trade-api/v2'
    for path in ('markets', 'historical/markets'):
        response = requests.get(f'{base}/{path}/{quote(symbol, safe="")}', timeout=8)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        evidence = validated_kalshi_market(symbol, cutoff_at, response.json().get('market'), now)
        return {**evidence, 'source_url': response.url} if evidence else None
    return None
