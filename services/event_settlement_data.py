"""Public, exact-contract settlement evidence for Webull-listed Kalshi markets.

Docs: https://docs.kalshi.com/api-reference/market/get-market
No account credentials, quote-derived outcomes or broker orders are used.
"""
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests


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
        market = response.json().get('market') or {}
        if (market.get('ticker') != symbol or market.get('market_type') != 'binary'
                or market.get('status') != 'finalized' or market.get('is_provisional')
                or market.get('result') not in ('yes', 'no')):
            return None
        try:
            close = aware(market['close_time'])
            settled = aware(market['settlement_ts'])
            payout = float(market['settlement_value_dollars'])
        except (KeyError, TypeError, ValueError, AttributeError):
            return None
        if (abs((close-aware(cutoff_at)).total_seconds()) > 1
                or settled < close or settled > aware(now)
                or payout != (1.0 if market['result'] == 'yes' else 0.0)):
            return None
        return {'settled_outcome': market['result'].upper(), 'settlement_price': payout,
                'payout_date': settled.isoformat(), 'provider_timestamp': settled.isoformat(),
                'market': market, 'source_url': response.url}
    return None
