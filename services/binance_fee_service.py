"""Binance.US fee estimates from signed US endpoints, never guessed live rates.

The public paper schedule and BNB discount were verified against
https://www.binance.us/fees and the US BNB-fee help page on 2026-09-22.
Synthetic triggers submit MARKET orders, so every executed leg is a taker.
"""
from copy import deepcopy
import math
import time
from core.time_utils import utc_now

_cache = {}


def _rate(value):
    value = float(value)
    if not math.isfinite(value) or value < 0 or value >= 1:
        raise ValueError('Invalid commission rate from Binance.US.')
    return value


def paper_rates(symbol):
    taker = .0001 if symbol == 'BNBUSD' else .0002
    return {'symbol': symbol, 'makerRate': 0, 'takerRate': taker,
            'rates': {side: {'maker': 0, 'taker': taker, 'standardTaker': taker, 'otherTaker': 0} for side in ('BUY', 'SELL')},
            'source': 'Published Binance.US standard schedule for paper simulation (2026-09-22)',
            'source_url': 'https://www.binance.us/fees', 'paper': True,
            'bnb': {'enabled': False, 'discountFraction': .05}, 'as_of': utc_now(aware=True).isoformat()}


def get_fee_quote(user_id, symbol, *, paper=False, client=None):
    symbol = str(symbol).upper()
    if not symbol.isalnum() or len(symbol) > 20:
        raise ValueError('Invalid Binance.US symbol.')
    if paper:
        result = paper_rates(symbol)
    else:
        key = (user_id, symbol)
        cached = _cache.get(key)
        if client is None and cached and time.monotonic() - cached[0] < 60:
            return deepcopy(cached[1])
        from services.synthetic_execution_service import binance_client
        client = client or binance_client(user_id)
        try:
            raw = client._get('account/commission', signed=True, version=3, data={'symbol': symbol})
            if raw.get('symbol') != symbol:
                raise ValueError('Commission symbol mismatch.')
            standard = raw['standardCommission']
            extra = [raw.get('taxCommission', {}), raw.get('specialCommission', {})]
            rates = {}
            for side, field in (('BUY', 'buyer'), ('SELL', 'seller')):
                standard_taker = _rate(standard['taker']) + _rate(standard.get(field, 0))
                other_taker = sum(_rate(item.get('taker', 0)) + _rate(item.get(field, 0)) for item in extra)
                rates[side] = {'taker': standard_taker + other_taker,
                    'maker': _rate(standard['maker']) + _rate(standard.get(field, 0)) + sum(_rate(item.get('maker', 0)) + _rate(item.get(field, 0)) for item in extra),
                    'standardTaker': standard_taker, 'otherTaker': other_taker}
            discount = raw.get('discount', {})
            bnb_enabled = discount.get('enabledForAccount') is True and discount.get('enabledForSymbol') is True and discount.get('discountAsset') == 'BNB'
            source = 'Binance.US account commission API'
        except Exception:
            # python-binance's get_trade_fee uses the Binance.com path; use the US path.
            data = client._request_margin_api('get', 'asset/query/trading-fee', signed=True, data={'symbol': symbol})
            raw = next((row for row in data if row.get('symbol') == symbol), None)
            if raw is None:
                raise ValueError('Binance.US did not return fees for this symbol.')
            maker, taker = _rate(raw['makerCommission']), _rate(raw['takerCommission'])
            rates = {side: {'maker': maker, 'taker': taker, 'standardTaker': taker, 'otherTaker': 0} for side in ('BUY', 'SELL')}
            bnb_enabled = None
            source = 'Binance.US symbol trading-fee API; BNB setting unavailable'
        result = {'symbol': symbol, 'makerRate': rates['SELL']['maker'], 'takerRate': rates['SELL']['taker'], 'rates': rates,
                  'source': source, 'source_url': 'https://docs.binance.us/#get-account-commission-rates-user_data',
                  'paper': False, 'as_of': utc_now(aware=True).isoformat(),
                  # US help explicitly documents 5% OFF. Old API examples mention 25%;
                  # do not import Binance.com discount semantics or example values.
                  'bnb': {'enabled': bnb_enabled, 'discountFraction': .05}}
        if len(_cache) > 512:
            _cache.clear()
        _cache[key] = (time.monotonic(), deepcopy(result))
    return result
