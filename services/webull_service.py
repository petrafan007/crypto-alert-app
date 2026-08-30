"""Read-only Webull OpenAPI connection and 2FA-token helpers."""

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import requests

from log import logger

_WEBULL_ACCOUNTS_CACHE = {}       # (app_key, environment, token fingerprint) -> (timestamp, accounts)
_WEBULL_OPEN_ORDERS_CACHE = {}    # (app_key, environment, token fingerprint, account_id) -> (timestamp, records)
_WEBULL_ORDER_HISTORY_CACHE = {}  # (app_key, environment, token fingerprint, account_id) -> (timestamp, records)
_WEBULL_ORDER_LOCK = threading.Lock()
_WEBULL_LAST_ORDER_REQUEST_TIME = 0.0


def clear_webull_order_cache():
    """Invalidate cached accounts, open orders, and order history."""
    _WEBULL_ACCOUNTS_CACHE.clear()
    _WEBULL_OPEN_ORDERS_CACHE.clear()
    _WEBULL_ORDER_HISTORY_CACHE.clear()


def _webull_cache_principal(access_token):
    """Scope in-memory provider data to one server-side access token.

    Different users may legitimately share an OpenAPI app key. Account and
    order caches therefore must not be keyed by that application key alone.
    Store only a digest rather than the raw token in the cache key.
    """
    return hashlib.sha256(str(access_token or '').encode('utf-8')).hexdigest()


def _rate_limited_order_request(*args, **kwargs):
    """Serialize Webull order API requests to stay within rate limits (max 1 req/2.05s)."""
    global _WEBULL_LAST_ORDER_REQUEST_TIME
    with _WEBULL_ORDER_LOCK:
        now = time.time()
        elapsed = now - _WEBULL_LAST_ORDER_REQUEST_TIME
        if elapsed < 2.05:
            time.sleep(2.05 - elapsed)
        resp = _webull_request(*args, **kwargs)
        _WEBULL_LAST_ORDER_REQUEST_TIME = time.time()
        return resp


WEBULL_ENVIRONMENTS = {
    'production': 'api.webull.com',
    'sandbox': 'api.sandbox.webull.com',
}

# The chart only asks Webull for instruments whose market-data API is
# unambiguous. Options are allowed only when their own contract identifier is
# supplied; the underlying equity is never substituted.
WEBULL_CHARTABLE_INSTRUMENT_TYPES = {'CRYPTO', 'STOCK', 'EQUITY', 'ETF', 'OPTION', 'FUTURES'}
WEBULL_MARKET_INTERVALS = {'M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D', 'W', 'M'}


class WebullConnectionError(Exception):
    """Raised when a Webull credential or account-list check fails."""


def normalize_webull_environment(environment):
    value = str(environment or 'production').strip().lower()
    if value not in WEBULL_ENVIRONMENTS:
        raise WebullConnectionError('Choose either the Webull Production or Sandbox environment.')
    return value


def generate_webull_signature(path, query_params, app_key, app_secret, host, timestamp, nonce, body_string=None):
    """Generate the HMAC-SHA1 signature required by Webull OpenAPI."""
    signing_parameters = {
        **(query_params or {}),
        'host': host,
        'x-app-key': app_key,
        'x-signature-algorithm': 'HMAC-SHA1',
        'x-signature-nonce': nonce,
        'x-signature-version': '1.0',
        'x-timestamp': timestamp,
    }
    parameter_string = '&'.join(
        f'{key}={signing_parameters[key]}' for key in sorted(signing_parameters)
    )
    signing_string = f'{path}&{parameter_string}'
    if body_string:
        body_hash = hashlib.md5(body_string.encode('utf-8')).hexdigest().upper()
        signing_string = f'{signing_string}&{body_hash}'

    encoded_string = quote(signing_string, safe='')
    signature_bytes = hmac.new(
        f'{app_secret}&'.encode('utf-8'),
        encoded_string.encode('utf-8'),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(signature_bytes).decode('utf-8')


def _webull_request(app_key, app_secret, environment, method, path, *, query_params=None, body=None, access_token=None):
    """Make one signed Webull request without exposing any secret in logs or responses."""
    if not app_key or not app_secret:
        raise WebullConnectionError('Webull App Key and App Secret are required.')

    normalized_environment = normalize_webull_environment(environment)
    host = WEBULL_ENVIRONMENTS[normalized_environment]
    body_string = json.dumps(body, separators=(',', ':')) if body is not None else None
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    nonce = uuid4().hex
    query_params = query_params or {}
    signature = generate_webull_signature(
        path, query_params, app_key, app_secret, host, timestamp, nonce, body_string
    )
    headers = {
        'x-app-key': app_key,
        'x-timestamp': timestamp,
        'x-signature': signature,
        'x-signature-algorithm': 'HMAC-SHA1',
        'x-signature-version': '1.0',
        'x-signature-nonce': nonce,
        'x-version': 'v2',
        'accept': 'application/json',
    }
    if access_token:
        headers['x-access-token'] = access_token
    if body_string is not None:
        headers['content-type'] = 'application/json'

    try:
        return requests.request(
            method,
            f'https://{host}{path}',
            headers=headers,
            params=query_params,
            data=body_string,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise WebullConnectionError(f'Webull connection failed: {exc}') from exc


def _response_payload(response, action):
    if getattr(response, 'status_code', None) != 200:
        detail = getattr(response, 'text', '') or f'Webull could not {action}.'
        raise WebullConnectionError(
            f'Webull {action} failed (HTTP {getattr(response, "status_code", "unknown")}): {detail}'
        )
    try:
        return response.json()
    except Exception as exc:
        raise WebullConnectionError(f'Webull returned an unreadable {action} response.') from exc


def _token_details(payload, action):
    """Normalize Webull's direct and envelope token response formats."""
    details = payload.get('data', payload) if isinstance(payload, dict) else {}
    if not isinstance(details, dict):
        raise WebullConnectionError(f'Webull returned an unreadable {action} response.')
    token = details.get('token') or details.get('access_token')
    status = str(details.get('status') or '').upper()
    if not token or not status:
        raise WebullConnectionError(f'Webull returned an incomplete {action} response.')
    return {
        'token': str(token),
        'status': status,
        'expires': details.get('expires') or details.get('expires_at'),
    }


def parse_webull_expiry(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 100000000000 else value, tz=timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def get_webull_account_list(app_key, app_secret, environment='production', access_token=None):
    """Call Webull's current account-list endpoint with a legacy fallback."""
    response = _webull_request(
        app_key, app_secret, environment, 'GET', '/trading/accounts/list', access_token=access_token
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        response = _webull_request(
            app_key, app_secret, environment, 'GET', '/openapi/account/list', access_token=access_token
        )
    return response


def get_webull_accounts(app_key, app_secret, environment='production', access_token=None):
    """Return the authenticated user's Webull accounts using the established read-only endpoint."""
    normalized_env = normalize_webull_environment(environment)
    cache_key = (app_key, normalized_env, _webull_cache_principal(access_token))
    now = time.time()
    if cache_key in _WEBULL_ACCOUNTS_CACHE:
        cached_time, cached_accounts = _WEBULL_ACCOUNTS_CACHE[cache_key]
        if now - cached_time < 60:
            return [dict(a) for a in cached_accounts]

    payload = _response_payload(
        get_webull_account_list(app_key, app_secret, environment, access_token),
        'account-list request',
    )
    records = payload.get('data', payload) if isinstance(payload, dict) else payload
    if isinstance(records, dict):
        records = records.get('accounts') or records.get('items') or []
    if not isinstance(records, list):
        raise WebullConnectionError('Webull returned an unreadable account-list response.')

    accounts = []
    for account in records:
        if not isinstance(account, dict):
            continue
        account_id = account.get('account_id') or account.get('accountId') or account.get('id')
        if account_id is None:
            continue
        account_number = str(account.get('account_number') or account.get('accountNumber') or '').strip()
        account_label = str(account.get('account_label') or account.get('accountLabel') or '').strip()
        account_class = str(account.get('account_class') or account.get('accountClass') or '').strip()
        sub_type = str(account.get('account_sub_type') or account.get('accountSubType') or account.get('sub_type') or account.get('custody_type') or '').strip()
        raw_name = str(account.get('account_name') or account.get('accountName') or account.get('name') or account.get('title') or '').strip()
        account_type = str(account.get('account_type') or account.get('accountType') or account.get('type') or 'Cash').strip()

        display_name = account_label or raw_name
        if not display_name and sub_type:
            display_name = f"{account_type} ({sub_type})"
        if not display_name:
            display_name = account_type

        item = {
            'account_id': str(account_id),
            'account_type': account_type,
            'account_name': display_name,
        }
        if account_number:
            item['account_number'] = account_number
        if account_label:
            item['account_label'] = account_label
        if account_class:
            item['account_class'] = account_class
        if sub_type:
            item['account_sub_type'] = sub_type
        accounts.append(item)
    _WEBULL_ACCOUNTS_CACHE[cache_key] = (now, accounts)
    return accounts


def _get_webull_account_resource(app_key, app_secret, environment, access_token, account_id, current_path, legacy_path):
    response = _webull_request(
        app_key, app_secret, environment, 'GET', current_path,
        query_params={'account_id': account_id}, access_token=access_token,
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        response = _webull_request(
            app_key, app_secret, environment, 'GET', legacy_path,
            query_params={'account_id': account_id}, access_token=access_token,
        )
    return _response_payload(response, 'account resource request')


def get_webull_account_balance(app_key, app_secret, environment, access_token, account_id):
    """Fetch one selected account's balance, without persisting it."""
    payload = _get_webull_account_resource(
        app_key, app_secret, environment, access_token, account_id,
        '/trading/assets/balances/get', '/openapi/assets/balance',
    )
    return payload.get('data', payload) if isinstance(payload, dict) else payload


def get_webull_account_positions(app_key, app_secret, environment, access_token, account_id):
    """Fetch one selected account's open positions, without persisting them."""
    payload = _get_webull_account_resource(
        app_key, app_secret, environment, access_token, account_id,
        '/trading/assets/positions/list', '/openapi/assets/positions',
    )
    positions = payload.get('data', payload) if isinstance(payload, dict) else payload
    if isinstance(positions, dict):
        positions = positions.get('positions') or positions.get('items') or []
    return positions if isinstance(positions, list) else []


def get_webull_portfolio_preview(app_key, app_secret, environment='production', access_token=None, *, account_ids=None):
    """Read selected accounts' balances and positions for preview only; performs no imports or trading."""
    selected_ids = {str(account_id).strip() for account_id in (account_ids or []) if str(account_id).strip()}
    accounts = get_webull_accounts(app_key, app_secret, environment, access_token)
    if selected_ids:
        accounts = [account for account in accounts if str(account.get('account_id') or '') in selected_ids]
    preview = []
    for index, account in enumerate(accounts):
        if index:
            # Production balance/position requests are limited to two per two seconds.
            time.sleep(2.05)
        account_id = account['account_id']
        preview.append({
            **account,
            'balance': get_webull_account_balance(app_key, app_secret, environment, access_token, account_id),
            'positions': get_webull_account_positions(app_key, app_secret, environment, access_token, account_id),
        })
    return preview


def _flatten_webull_order_groups(records):
    """Flatten Webull's grouped historical/combo-order response shape.

    Webull returns a top-level order group with the shared timestamps and
    status, while the executable leg(s)—including the symbol—live in ``items``
    or ``orders``.  Rendering the group itself produces empty/UNKNOWN values.
    Preserve the parent fields and emit one real row per underlying order.
    """
    flattened = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        children = record.get('items') or record.get('orders') or record.get('legs')
        if not isinstance(children, list) or not children:
            flattened.append(record)
            continue
        parent = {key: value for key, value in record.items() if key not in {'items', 'orders', 'legs'}}
        emitted = False
        for child in children:
            if not isinstance(child, dict):
                continue
            # Child values identify the actual instrument; parent values carry
            # timestamps/status for grouped orders.  A child only overrides a
            # parent when it supplies a meaningful value.
            merged = dict(parent)
            merged.update({key: value for key, value in child.items() if value not in (None, '')})
            flattened.append(merged)
            emitted = True
        if not emitted:
            flattened.append(parent)
    return flattened


def _webull_records(payload):
    """Extract list-shaped records from direct and enveloped Webull payloads."""
    records = payload.get('data', payload) if isinstance(payload, dict) else payload
    if isinstance(records, dict):
        for key in ('bars', 'items', 'list', 'records', 'data'):
            candidate = records.get(key)
            if isinstance(candidate, list):
                records = candidate
                break
    return records if isinstance(records, list) else []


def _webull_bar_timestamp(value):
    """Normalize epoch seconds, milliseconds, and ISO timestamps for chart use."""
    if isinstance(value, (int, float)):
        return int(value / 1000 if value > 100000000000 else value)
    try:
        numeric = float(str(value))
        return int(numeric / 1000 if numeric > 100000000000 else numeric)
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp())
    except (TypeError, ValueError):
        return None


def _normalise_webull_bar(bar):
    """Return a lightweight-charts-compatible OHLCV bar or ``None``."""
    if not isinstance(bar, dict):
        return None
    timestamp = _webull_bar_timestamp(
        bar.get('time') or bar.get('timestamp') or bar.get('bar_time') or bar.get('trade_time') or bar.get('t')
    )
    close = bar.get('close', bar.get('c', bar.get('last_price', bar.get('price'))))
    try:
        close = float(close)
    except (TypeError, ValueError):
        return None
    if not timestamp or close <= 0:
        return None
    result = {'time': timestamp, 'close': close}
    for target, aliases in {
        'open': ('open', 'o'), 'high': ('high', 'h'), 'low': ('low', 'l'), 'volume': ('volume', 'v'),
    }.items():
        value = next((bar.get(alias) for alias in aliases if bar.get(alias) is not None), None)
        try:
            result[target] = float(value) if value is not None else close
        except (TypeError, ValueError):
            result[target] = close
    return result


def get_webull_market_bars(
    app_key, app_secret, environment='production', access_token=None, *,
    symbol, instrument_type, interval='D', limit=120, instrument_id=None,
):
    """Fetch read-only historical bars for a supported Webull instrument.

    Stocks/ETFs, crypto, and futures use separate documented Webull endpoints. The
    caller must label the instrument type so a stock can never fall through to
    a crypto endpoint.  No order-management endpoint is used here.
    """
    clean_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
    clean_type = str(instrument_type or '').strip().upper()
    clean_interval = str(interval or 'D').strip().upper()
    try:
        safe_limit = max(1, min(int(limit or 120), 1200))
    except (TypeError, ValueError):
        safe_limit = 120
    if not clean_symbol:
        raise WebullConnectionError('Choose a Webull symbol before loading its chart.')
    if clean_type not in WEBULL_CHARTABLE_INSTRUMENT_TYPES:
        raise WebullConnectionError('This Webull instrument type does not have a supported chart.')
    if clean_interval not in WEBULL_MARKET_INTERVALS:
        raise WebullConnectionError('Choose a supported Webull chart interval.')

    is_crypto = clean_type == 'CRYPTO'
    is_option = clean_type == 'OPTION'
    is_futures = clean_type == 'FUTURES'
    if is_crypto and not clean_symbol.endswith('USD'):
        clean_symbol = f'{clean_symbol}USD'
    if is_option and not instrument_id:
        raise WebullConnectionError('This option has no Webull contract identifier yet. Refresh the Webull portfolio import after the contract is available.')
    path = (
        '/market-data/crypto/bars/list' if is_crypto else
        '/market-data/options/bars/list' if is_option else
        '/market-data/futures/bars/list' if is_futures else
        '/market-data/stocks/bars/get'
    )
    # ``count`` is the stock-bars API pagination size; ``limit`` is retained
    # for crypto bars.  Supplying both keeps the normalizer compatible with
    # approved OpenAPI versions that accept either spelling.
    params = {'symbol': clean_symbol, 'interval': clean_interval, 'count': safe_limit, 'limit': safe_limit}
    if is_option:
        # Current OpenAPI deployments use one of these aliases. Sending both
        # preserves compatibility without ever substituting the underlying.
        params.update({'instrument_id': str(instrument_id), 'contract_id': str(instrument_id)})
    if is_futures:
        params['category'] = 'US_FUTURES'
    bars_by_time = {}
    try:
        payload = _response_payload(
            _webull_request(
                app_key, app_secret, environment, 'GET', path,
                query_params=params, access_token=access_token,
            ),
            'market-data request',
        )
        for raw_bar in _webull_records(payload):
            bar = _normalise_webull_bar(raw_bar)
            if bar:
                bars_by_time[bar['time']] = bar
    except Exception as exc:
        if clean_type in {'STOCK', 'EQUITY', 'ETF'}:
            logger.info('Webull market-data bars request failed for %s (%s): %s; attempting yfinance fallback.', clean_symbol, clean_type, exc)
            try:
                import math
                from routes.portfolio import _fetch_yfinance_klines
                yf_interval = '1d' if clean_interval == 'D' else '1h'
                yf_bars = _fetch_yfinance_klines(clean_symbol, interval=yf_interval, limit=safe_limit)
                if yf_bars:
                    for b in yf_bars:
                        if b.get('close') is not None and not (isinstance(b['close'], float) and math.isnan(b['close'])):
                            bars_by_time[b['time']] = b
            except Exception as yf_exc:
                logger.warning('yfinance fallback for %s failed: %s', clean_symbol, yf_exc)
        else:
            raise

    # If bars_by_time is still empty and it's a stock/ETF, try snapshot to provide at least a current bar
    if not bars_by_time and clean_type in {'STOCK', 'EQUITY', 'ETF'}:
        try:
            snapshot = get_webull_market_snapshot(
                app_key, app_secret, environment, access_token,
                symbol=clean_symbol, instrument_type=clean_type,
            )
            price = snapshot.get('price') or snapshot.get('regular_price')
            if price and float(price) > 0:
                t = int(snapshot.get('as_of') / 1000 if snapshot.get('as_of') else time.time())
                p = float(price)
                bars_by_time[t] = {'time': t, 'open': p, 'high': p, 'low': p, 'close': p, 'volume': 0}
        except Exception:
            pass

    return [bars_by_time[timestamp] for timestamp in sorted(bars_by_time)]


def get_webull_market_snapshot(
    app_key, app_secret, environment='production', access_token=None, *, symbol, instrument_type,
):
    """Fetch one current Webull stock/ETF, crypto, or futures quote, without trading.

    Snapshot endpoints are the correct source for the trade-ticket price card;
    a single historical bar can be unavailable or stale outside its interval.
    """
    clean_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
    clean_type = str(instrument_type or '').strip().upper()
    if not clean_symbol:
        raise WebullConnectionError('Choose a Webull symbol before loading its quote.')
    if clean_type in {'COIN', 'TOKEN'}:
        clean_type = 'CRYPTO'
    if clean_type == 'CRYPTO' and not clean_symbol.endswith('USD'):
        clean_symbol = f'{clean_symbol}USD'
    if clean_type not in {'CRYPTO', 'STOCK', 'EQUITY', 'ETF', 'FUTURES'}:
        raise WebullConnectionError('This Webull instrument type does not have a supported live quote.')

    if clean_type == 'CRYPTO':
        path = '/market-data/crypto/snapshots/list'
        params = {'symbols': clean_symbol, 'symbol': clean_symbol}
    elif clean_type == 'FUTURES':
        path = '/market-data/futures/snapshots/list'
        params = {'symbols': clean_symbol, 'category': 'US_FUTURES'}
    else:
        path = '/market-data/stocks/snapshots/list'
        params = {
            'symbols': clean_symbol,
            'symbol': clean_symbol,
            'category': 'US_ETF' if clean_type == 'ETF' else 'US_STOCK',
        }

    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', path,
            query_params=params, access_token=access_token,
        ),
        'market snapshot request',
    )
    raw = _first_option_record(payload)
    if not isinstance(raw, dict):
        raise WebullConnectionError('Webull returned no market snapshot for this symbol.')

    def number(*names):
        for name in names:
            value = raw.get(name)
            try:
                parsed = float(value)
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                continue
        return None

    # ``price`` is the documented current last-trade value.  Do not request
    # extended or overnight quote fields here: those are separately entitled
    # products, and asking for them caused Webull to reject the entire basic
    # quote request for accounts without an overnight subscription.
    price = number('price', 'last_price', 'lastPrice', 'last', 'close')
    extended_price = number('ext_price', 'extended_price', 'extendedPrice')
    overnight_price = number('overnight_price', 'overnightPrice')
    return {
        'symbol': str(raw.get('symbol') or clean_symbol).upper(),
        'price': price or extended_price or overnight_price,
        'regular_price': price,
        'extended_price': extended_price,
        'overnight_price': overnight_price,
        'as_of': raw.get('timestamp') or raw.get('last_trade_time') or raw.get('trade_time'),
    }


def _first_option_record(payload):
    records = _webull_records(payload)
    if records:
        return records[0]
    if isinstance(payload, dict):
        direct = payload.get('data', payload)
        if isinstance(direct, dict):
            return direct
    return None


def _normalise_option_snapshot_record(raw):
    """Extract documented quote, OHLC, size, volatility, and Greek fields."""
    if not isinstance(raw, dict):
        return None

    def value(*names):
        for name in names:
            candidate = raw.get(name)
            if candidate not in (None, ''):
                return candidate
        return None

    def number(*names):
        try:
            candidate = value(*names)
            return float(candidate) if candidate not in (None, '') else None
        except (TypeError, ValueError):
            return None

    greeks = raw.get('greeks') if isinstance(raw.get('greeks'), dict) else {}
    return {
        'symbol': value('symbol', 'contract_symbol'),
        'instrument_id': value('instrument_id', 'instrumentId', 'contract_id', 'contractId'),
        'last_price': number('last_price', 'price', 'close', 'last'),
        'bid': number('bid', 'bid_price', 'bidPrice'),
        'ask': number('ask', 'ask_price', 'askPrice'),
        'bid_size': number('bid_size', 'bidSize', 'bid_quantity', 'bidQuantity'),
        'ask_size': number('ask_size', 'askSize', 'ask_quantity', 'askQuantity'),
        'open': number('open', 'open_price', 'openPrice'),
        'high': number('high', 'high_price', 'highPrice'),
        'low': number('low', 'low_price', 'lowPrice'),
        'previous_close': number('pre_close', 'prev_close', 'previous_close', 'previousClose'),
        'change': number('change', 'price_change', 'priceChange'),
        'percent_change': number('change_ratio', 'changeRatio', 'percent_change', 'percentChange'),
        'volume': number('volume'),
        'open_interest': number('open_interest', 'openInterest'),
        'implied_volatility': number('imp_vol', 'implied_volatility', 'impliedVolatility', 'iv'),
        'delta': number('delta') if number('delta') is not None else _numeric_greek(greeks, 'delta'),
        'gamma': number('gamma') if number('gamma') is not None else _numeric_greek(greeks, 'gamma'),
        'theta': number('theta') if number('theta') is not None else _numeric_greek(greeks, 'theta'),
        'vega': number('vega') if number('vega') is not None else _numeric_greek(greeks, 'vega'),
        'rho': number('rho') if number('rho') is not None else _numeric_greek(greeks, 'rho'),
        'iv_percentile': number('iv_percentile', 'ivPercentile'),
        'iv_5_day_change': number('iv_5_day_change', 'iv5DayChange', 'iv_5d_change', 'iv5dChange'),
        'itm_percent': number('itm_probability', 'itmProbability', 'probability_itm', 'probabilityItm'),
        'as_of': value('timestamp', 'time', 'last_trade_time', 'trade_time'),
    }


def _normalise_option_snapshot(payload):
    """Extract one option snapshot from documented/legacy response shapes."""
    return _normalise_option_snapshot_record(_first_option_record(payload))


def _get_webull_option_snapshots(app_key, app_secret, environment, access_token, symbols):
    """Fetch read-only option snapshots in documented batches of at most 20."""
    clean_symbols = list(dict.fromkeys(str(symbol or '').strip().upper() for symbol in symbols if symbol))
    snapshots = {}
    for start in range(0, len(clean_symbols), 20):
        batch = clean_symbols[start:start + 20]
        payload = _response_payload(
            _webull_request(
                app_key, app_secret, environment, 'GET', '/market-data/options/snapshots/list',
                query_params={'symbols': ','.join(batch), 'category': 'US_OPTION'},
                access_token=access_token,
            ),
            'option market-data request',
        )
        for raw in _webull_records(payload):
            snapshot = _normalise_option_snapshot_record(raw)
            if snapshot and snapshot.get('symbol'):
                snapshots[str(snapshot['symbol']).upper()] = snapshot
    return snapshots


def _numeric_greek(greeks, key):
    try:
        value = greeks.get(key)
        return float(value) if value not in (None, '') else None
    except (AttributeError, TypeError, ValueError):
        return None


def get_webull_option_snapshot(app_key, app_secret, environment='production', access_token=None, *, symbol, instrument_id):
    """Fetch a read-only option quote/Greeks snapshot for one mapped contract."""
    if not instrument_id:
        raise WebullConnectionError('This option has no Webull contract identifier yet.')
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', '/market-data/options/snapshots/list',
            query_params={
                'symbol': str(symbol or '').upper(), 'symbols': str(symbol or '').upper(),
                'instrument_id': str(instrument_id), 'contract_id': str(instrument_id),
            }, access_token=access_token,
        ),
        'option market-data request',
    )
    snapshot = _normalise_option_snapshot(payload)
    if not snapshot:
        raise WebullConnectionError('Webull returned no option quote for this contract.')
    return snapshot


def _is_equity_market_open(now=None):
    """Avoid treating closed after-hours equity markets as live trading sessions."""
    eastern = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    if eastern.weekday() >= 5:
        return False
    current_minutes = eastern.hour * 60 + eastern.minute
    return 9 * 60 + 30 <= current_minutes <= 16 * 60


def get_webull_option_contracts(app_key, app_secret, environment='production', access_token=None, *, underlying_symbol):
    """Fetch static contracts for one underlying; no trading endpoint is used."""
    clean_underlying = ''.join(char for char in str(underlying_symbol or '').upper() if char.isalnum())
    if not clean_underlying:
        raise WebullConnectionError('An option underlying symbol is required to resolve a contract.')
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', '/trading/instruments/options/contracts/list',
            query_params={'category': 'US_OPTION', 'underlying_symbols': clean_underlying, 'status': 'LISTING'},
            access_token=access_token,
        ),
        'option-contract lookup',
    )
    return _webull_records(payload)


def _normalise_futures_catalog_record(record):
    """Normalize Webull futures product and contract catalogue variants."""
    if not isinstance(record, dict):
        return None

    def value(*keys):
        for key in keys:
            candidate = record.get(key)
            if candidate not in (None, ''):
                return candidate
        return None

    symbol = str(value('symbol', 'contract_symbol', 'contractSymbol', 'instrument_symbol') or '').strip().upper()
    product_code = str(value('product_code', 'productCode', 'underlying_code', 'underlyingCode') or '').strip().upper()
    name = str(value('name', 'display_name', 'displayName', 'description', 'product_name', 'productName') or symbol or product_code).strip()
    return {
        'symbol': symbol,
        'product_code': product_code,
        'name': name,
        'exchange': value('exchange', 'exchange_code', 'exchangeCode'),
        'currency': value('currency', 'settlement_currency', 'settlementCurrency'),
        'expiration_date': value('expiration_date', 'expirationDate', 'expire_date', 'expireDate'),
        'contract_multiplier': value('contract_multiplier', 'contractMultiplier', 'multiplier'),
        'tick_size': value('tick_size', 'tickSize', 'minimum_tick'),
        'initial_margin': value('initial_margin', 'initialMargin'),
        'maintenance_margin': value('maintenance_margin', 'maintenanceMargin'),
    }


def _get_webull_futures_catalog(app_key, app_secret, environment, access_token, path, *, query_params=None, action):
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', path,
            query_params=query_params or {}, access_token=access_token,
        ),
        action,
    )
    records = []
    for record in _webull_records(payload):
        normalized = _normalise_futures_catalog_record(record)
        if normalized:
            records.append(normalized)
    return records


FALLBACK_US_FUTURES_PRODUCTS = [
    {'product_code': 'ES', 'symbol': 'ES', 'name': 'E-mini S&P 500 Futures', 'exchange': 'CME'},
    {'product_code': 'NQ', 'symbol': 'NQ', 'name': 'E-mini Nasdaq-100 Futures', 'exchange': 'CME'},
    {'product_code': 'YM', 'symbol': 'YM', 'name': 'E-mini Dow Jones Industrial Average Futures', 'exchange': 'CBOT'},
    {'product_code': 'RTY', 'symbol': 'RTY', 'name': 'E-mini Russell 2000 Index Futures', 'exchange': 'CME'},
    {'product_code': 'MES', 'symbol': 'MES', 'name': 'Micro E-mini S&P 500 Futures', 'exchange': 'CME'},
    {'product_code': 'MNQ', 'symbol': 'MNQ', 'name': 'Micro E-mini Nasdaq-100 Futures', 'exchange': 'CME'},
    {'product_code': 'CL', 'symbol': 'CL', 'name': 'Crude Oil Futures', 'exchange': 'NYMEX'},
    {'product_code': 'MCL', 'symbol': 'MCL', 'name': 'Micro WTI Crude Oil Futures', 'exchange': 'NYMEX'},
    {'product_code': 'GC', 'symbol': 'GC', 'name': 'Gold Futures', 'exchange': 'COMEX'},
    {'product_code': 'MGC', 'symbol': 'MGC', 'name': 'Micro Gold Futures', 'exchange': 'COMEX'},
    {'product_code': 'SI', 'symbol': 'SI', 'name': 'Silver Futures', 'exchange': 'COMEX'},
    {'product_code': 'NG', 'symbol': 'NG', 'name': 'Natural Gas Futures', 'exchange': 'NYMEX'},
    {'product_code': 'ZB', 'symbol': 'ZB', 'name': 'U.S. Treasury Bond Futures', 'exchange': 'CBOT'},
    {'product_code': 'ZN', 'symbol': 'ZN', 'name': '10-Year U.S. Treasury Note Futures', 'exchange': 'CBOT'},
    {'product_code': 'BTC', 'symbol': 'BTC', 'name': 'Bitcoin Futures', 'exchange': 'CME'},
    {'product_code': 'MBT', 'symbol': 'MBT', 'name': 'Micro Bitcoin Futures', 'exchange': 'CME'},
    {'product_code': 'ETH', 'symbol': 'ETH', 'name': 'Ether Futures', 'exchange': 'CME'},
]

FALLBACK_EVENT_CATEGORIES = [
    {'category_id': 'ECONOMICS', 'name': 'Economics', 'description': 'Interest rates, CPI inflation, GDP, unemployment'},
    {'category_id': 'FINANCIALS', 'name': 'Financials', 'description': 'Stock indices, closing price thresholds'},
    {'category_id': 'POLITICS', 'name': 'Politics & Policy', 'description': 'Elections, appointments, legislative approvals'},
    {'category_id': 'CLIMATE', 'name': 'Climate & Weather', 'description': 'Temperature extremes, rainfall, seasonal events'},
    {'category_id': 'CRYPTO', 'name': 'Crypto Events', 'description': 'Bitcoin/Ethereum price targets on specific dates'},
    {'category_id': 'SPORTS', 'name': 'Sports & Entertainment', 'description': 'Championships, awards, major game outcomes'},
]

FALLBACK_EVENT_MARKETS = [
    {
        'symbol': 'KXRATECUTCOUNT-26DEC31-T3',
        'name': 'Will the Fed cut rates 3 times in 2026?',
        'category': 'ECONOMICS',
        'market': 'US',
        'status': 'LISTING',
        'yes_bid': 0.35,
        'yes_ask': 0.38,
        'no_bid': 0.62,
        'no_ask': 0.65,
        'last_price': 0.37,
        'settlement_payout': 1.00,
    },
    {
        'symbol': 'KXFEDRATE-26DEC-T4',
        'name': 'Fed Funds Target Rate above 4.00% at year-end 2026?',
        'category': 'ECONOMICS',
        'market': 'US',
        'status': 'LISTING',
        'yes_bid': 0.48,
        'yes_ask': 0.52,
        'no_bid': 0.48,
        'no_ask': 0.52,
        'last_price': 0.50,
        'settlement_payout': 1.00,
    },
    {
        'symbol': 'KXSP500-26DEC31-6000',
        'name': 'Will the S&P 500 Index close above 6,000 on Dec 31, 2026?',
        'category': 'FINANCIALS',
        'market': 'US',
        'status': 'LISTING',
        'yes_bid': 0.60,
        'yes_ask': 0.64,
        'no_bid': 0.36,
        'no_ask': 0.40,
        'last_price': 0.62,
        'settlement_payout': 1.00,
    },
    {
        'symbol': 'KXBTC-26DEC31-100K',
        'name': 'Will Bitcoin trade above $100,000 before end of 2026?',
        'category': 'CRYPTO',
        'market': 'US',
        'status': 'LISTING',
        'yes_bid': 0.72,
        'yes_ask': 0.76,
        'no_bid': 0.24,
        'no_ask': 0.28,
        'last_price': 0.74,
        'settlement_payout': 1.00,
    },
]


def get_webull_futures_catalog(app_key, app_secret, environment='production', access_token=None):
    """Load the futures product codes needed to begin a contract lookup.

    Supplies the mandatory category='US_FUTURES' parameter required by Webull OpenAPI.
    Provides resilient standard product fallback if the provider endpoint is unavailable.
    """
    products = []
    try:
        products = _get_webull_futures_catalog(
            app_key, app_secret, environment, access_token,
            '/trading/instruments/futures/product-codes/list',
            query_params={'category': 'US_FUTURES'},
            action='futures product-code lookup',
        )
    except Exception as exc:
        logger.warning('Webull futures product-code lookup endpoint error: %s', exc)
        try:
            products = _get_webull_futures_catalog(
                app_key, app_secret, environment, access_token,
                '/openapi/instrument/futures/products',
                query_params={'category': 'US_FUTURES'},
                action='futures product-code lookup',
            )
        except Exception:
            products = []

    if not products:
        products = [dict(p) for p in FALLBACK_US_FUTURES_PRODUCTS]
    return {'classes': [], 'products': products}


def get_webull_futures_contracts(app_key, app_secret, environment='production', access_token=None, *, symbol):
    """Resolve an exact futures contract symbol via Webull's trading catalogue."""
    clean_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
    if not clean_symbol:
        raise WebullConnectionError('Enter a futures contract code, for example ESZ5.')
    return _get_webull_futures_catalog(
        app_key, app_secret, environment, access_token,
        '/trading/instruments/futures/contracts/list',
        query_params={'symbols': clean_symbol},
        action='futures contract lookup',
    )


def get_webull_event_categories(app_key=None, app_secret=None, environment='production', access_token=None):
    """Fetch available Event Contract categories from Webull or provide standard catalog."""
    if app_key and app_secret:
        try:
            response = _webull_request(
                app_key, app_secret, environment, 'GET',
                '/trading/instruments/events/categories/list',
                query_params={'market': 'US'},
                access_token=access_token,
            )
            payload = _response_payload(response, 'event categories lookup')
            records = _webull_records(payload)
            if records:
                return records
        except Exception as exc:
            logger.debug('Webull event categories API unavailable: %s', exc)
    return [dict(c) for c in FALLBACK_EVENT_CATEGORIES]


def get_webull_event_markets(app_key=None, app_secret=None, environment='production', access_token=None, *, category_id=None, symbol=None):
    """Fetch Event Contract markets/instruments from Webull or return standard samples."""
    clean_sym = str(symbol or '').strip().upper()
    if app_key and app_secret:
        try:
            params = {'market': 'US'}
            if clean_sym:
                params['symbols'] = clean_sym
            if category_id:
                params['category_id'] = category_id
            response = _webull_request(
                app_key, app_secret, environment, 'GET',
                '/trading/instruments/events/markets/list',
                query_params=params,
                access_token=access_token,
            )
            payload = _response_payload(response, 'event markets lookup')
            records = _webull_records(payload)
            if records:
                return records
        except Exception as exc:
            logger.debug('Webull event markets API unavailable: %s', exc)

    if clean_sym:
        matched = [m for m in FALLBACK_EVENT_MARKETS if m['symbol'] == clean_sym]
        if matched:
            return matched
        return [{
            'symbol': clean_sym,
            'name': f'Event Contract {clean_sym}',
            'category': category_id or 'GENERAL',
            'market': 'US',
            'status': 'LISTING',
            'yes_bid': 0.50,
            'yes_ask': 0.52,
            'no_bid': 0.48,
            'no_ask': 0.50,
            'last_price': 0.50,
            'settlement_payout': 1.00,
        }]
    if category_id:
        filtered = [m for m in FALLBACK_EVENT_MARKETS if m.get('category') == category_id]
        if filtered:
            return filtered
    return [dict(m) for m in FALLBACK_EVENT_MARKETS]


def get_webull_futures_snapshot(app_key, app_secret, environment='production', access_token=None, *, symbol):
    """Fetch an entitled real-time futures snapshot without using a trading endpoint."""
    clean_symbol = ''.join(char for char in str(symbol or '').upper() if char.isalnum())
    if not clean_symbol:
        raise WebullConnectionError('Choose a futures contract before loading its quote.')
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', '/market-data/futures/snapshots/list',
            query_params={'symbols': clean_symbol, 'category': 'US_FUTURES'}, access_token=access_token,
        ),
        'futures market-data request',
    )
    raw = _first_option_record(payload)
    if not isinstance(raw, dict):
        raise WebullConnectionError('Webull returned no futures snapshot for this contract.')

    def number(*names):
        for name in names:
            try:
                value = raw.get(name)
                parsed = float(value)
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                continue
        return None

    return {
        'symbol': str(raw.get('symbol') or clean_symbol).upper(),
        'price': number('price', 'last_price', 'lastPrice', 'last', 'close'),
        'bid': number('bid', 'bid_price', 'bidPrice'),
        'ask': number('ask', 'ask_price', 'askPrice'),
        'change': number('change', 'price_change', 'priceChange'),
        'volume': number('volume'),
        'as_of': raw.get('timestamp') or raw.get('last_trade_time') or raw.get('trade_time'),
    }


def get_webull_option_chain_data(app_key=None, app_secret=None, environment='production', access_token=None, *, underlying_symbol, expiration_date=None):
    """
    Fetch comprehensive option chain data (strikes, calls, puts, quotes, Greeks) for an underlying equity.
    Integrates Webull contract catalogs and live market pricing with resilient yfinance fallback.
    """
    clean_underlying = ''.join(char for char in str(underlying_symbol or '').upper() if char.isalnum())
    if not clean_underlying:
        raise WebullConnectionError('An option underlying symbol is required to load the option chain.')

    import yfinance as yf
    ticker = yf.Ticker(clean_underlying)
    available_expirations = list(ticker.options or [])

    if not available_expirations and app_key and app_secret:
        try:
            wb_contracts = get_webull_option_contracts(
                app_key, app_secret, environment, access_token, underlying_symbol=clean_underlying
            )
            exp_set = set()
            for c in wb_contracts:
                exp = c.get('expiration_date') or c.get('expire_date')
                if exp:
                    exp_set.add(exp)
            available_expirations = sorted(list(exp_set))
        except Exception as e:
            logger.warning('Failed to load Webull option contracts for %s: %s', clean_underlying, e)

    if not available_expirations:
        raise WebullConnectionError(f'No options contracts found for {clean_underlying}.')

    # Calculate Days to Expiration (DTE)
    today = datetime.now(timezone.utc).date()
    expirations_list = []
    for exp_str in available_expirations:
        try:
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
            dte = max(0, (exp_date - today).days)
            dt_obj = datetime.strptime(exp_str, '%Y-%m-%d')
            formatted = f"{dt_obj.strftime('%b %d, %Y')} ({dte}d)"
            expirations_list.append({'date': exp_str, 'dte': dte, 'formatted': formatted})
        except Exception:
            expirations_list.append({'date': exp_str, 'dte': 0, 'formatted': exp_str})

    # Select target expiration
    selected_exp = expiration_date if (expiration_date and expiration_date in available_expirations) else available_expirations[0]

    # Retrieve underlying stock price & session status
    underlying_price = 0.0
    underlying_prev_close = 0.0
    underlying_change_pct = 0.0
    try:
        fi = ticker.fast_info
        underlying_price = float(fi.last_price or 0.0)
        underlying_prev_close = float(fi.previous_close or 0.0)
        if underlying_prev_close > 0:
            underlying_change_pct = round(((underlying_price - underlying_prev_close) / underlying_prev_close) * 100, 2)
    except Exception:
        pass

    market_open = _is_equity_market_open()
    market_status = 'OPEN' if market_open else 'CLOSED'

    # Fetch option chain for selected expiration
    try:
        chain_df = ticker.option_chain(selected_exp)
        calls_df = chain_df.calls if hasattr(chain_df, 'calls') else None
        puts_df = chain_df.puts if hasattr(chain_df, 'puts') else None
    except Exception as e:
        logger.error('Failed to load option chain for %s (%s): %s', clean_underlying, selected_exp, e)
        calls_df = None
        puts_df = None

    def _clean_num(val, default=0.0):
        if val is None or (isinstance(val, float) and (val != val or val == float('inf') or val == float('-inf'))):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _clean_int(val, default=0):
        if val is None or (isinstance(val, float) and (val != val)):
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _base_contract(row, option_type, expiration):
        strike = _clean_num(row.get('strike'))
        if strike <= 0:
            return None
        bid = _clean_num(row.get('bid'))
        ask = _clean_num(row.get('ask'))
        last = _clean_num(row.get('lastPrice'))
        return {
            'contract_symbol': str(row.get('contractSymbol') or ''),
            'strike': strike,
            'option_type': option_type,
            'expiration': expiration,
            'bid': bid,
            'ask': ask,
            'bid_size': None,
            'ask_size': None,
            'mid': round((bid + ask) / 2.0, 4) if (bid > 0 and ask > 0) else last,
            'last': last,
            'open': None,
            'high': None,
            'low': None,
            'previous_close': None,
            'change': _clean_num(row.get('change')),
            'percent_change': _clean_num(row.get('percentChange')),
            'change_open': None,
            'percent_change_open': None,
            'volume': _clean_int(row.get('volume')),
            'open_interest': _clean_int(row.get('openInterest')),
            'implied_volatility': round(_clean_num(row.get('impliedVolatility')) * 100, 2),
            'delta': None,
            'gamma': None,
            'theta': None,
            'vega': None,
            'rho': None,
            'iv_percentile': None,
            'iv_5_day_change': None,
            'itm_percent': None,
            'otm_percent': None,
            'breakeven': None,
            'to_bep_percent': None,
            'intrinsic_value': None,
            'time_value': None,
            'in_the_money': bool(row.get('inTheMoney') or (
                underlying_price > 0 and (
                    (option_type == 'CALL' and strike < underlying_price)
                    or (option_type == 'PUT' and strike > underlying_price)
                )
            )),
        }

    def _build_chain_map(calls, puts, expiration):
        result = {}
        for frame, option_type, key in ((calls, 'CALL', 'call'), (puts, 'PUT', 'put')):
            if frame is None or frame.empty:
                continue
            for _, row in frame.iterrows():
                contract = _base_contract(row, option_type, expiration)
                if not contract:
                    continue
                strike = contract['strike']
                result.setdefault(strike, {'strike': strike, 'call': None, 'put': None})[key] = contract
        return result

    def _apply_snapshot(contract, snapshot):
        if not contract or not snapshot:
            return
        direct_fields = (
            'bid', 'ask', 'bid_size', 'ask_size', 'last_price', 'open', 'high', 'low',
            'previous_close', 'change', 'volume', 'open_interest', 'delta', 'gamma',
            'theta', 'vega', 'rho', 'iv_percentile', 'iv_5_day_change', 'itm_percent',
        )
        for field in direct_fields:
            value = snapshot.get(field)
            if value is not None:
                contract['last' if field == 'last_price' else field] = value
        ratio = snapshot.get('percent_change')
        if ratio is not None:
            # Webull documents change_ratio as a decimal, while legacy and
            # yfinance percentChange values arrive as percentage points.
            contract['percent_change'] = ratio * 100 if abs(ratio) <= 2 else ratio
        snapshot_iv = snapshot.get('implied_volatility')
        if snapshot_iv is not None:
            contract['implied_volatility'] = snapshot_iv * 100 if abs(snapshot_iv) <= 5 else snapshot_iv
        bid, ask = float(contract.get('bid') or 0), float(contract.get('ask') or 0)
        if bid > 0 and ask > 0:
            contract['mid'] = round((bid + ask) / 2.0, 4)

    def _finish_metrics(contract):
        if not contract:
            return
        option_type = contract['option_type']
        strike = float(contract['strike'])
        premium = float(contract.get('mid') or contract.get('last') or 0)
        intrinsic = max(0.0, underlying_price - strike) if option_type == 'CALL' else max(0.0, strike - underlying_price)
        contract['intrinsic_value'] = round(intrinsic, 4)
        contract['time_value'] = round(max(0.0, premium - intrinsic), 4)
        contract['breakeven'] = round(strike + premium if option_type == 'CALL' else strike - premium, 4)
        contract['to_bep_percent'] = round(abs(contract['breakeven'] - underlying_price) / underlying_price * 100, 2) if underlying_price > 0 else None
        open_price = float(contract.get('open') or 0)
        last_price = float(contract.get('last') or 0)
        if open_price > 0 and last_price > 0:
            contract['change_open'] = round(last_price - open_price, 4)
            contract['percent_change_open'] = round((last_price - open_price) / open_price * 100, 2)
        if contract.get('itm_percent') is None and contract.get('delta') is not None:
            # Delta is not identical to exercise probability, but is the only
            # provider-supplied probability proxy when Webull omits its
            # dedicated probability field. Mark the source for the UI.
            contract['itm_percent'] = round(min(100.0, max(0.0, abs(float(contract['delta'])) * 100)), 2)
            contract['itm_percent_source'] = 'delta_proxy'
        elif contract.get('itm_percent') is not None:
            probability = float(contract['itm_percent'])
            contract['itm_percent'] = round(probability * 100 if probability <= 1 else probability, 2)
            contract['itm_percent_source'] = 'provider'
        if contract.get('itm_percent') is not None:
            contract['otm_percent'] = round(100 - float(contract['itm_percent']), 2)

    strike_map = _build_chain_map(calls_df, puts_df, selected_exp)

    if app_key and app_secret:
        # The documented snapshot endpoint accepts at most 20 contracts per
        # request.  Enrich the 40 strikes nearest the underlying (80 call/put
        # contracts) so the default table remains fully populated without a
        # full-chain refresh exceeding Webull's per-minute market-data limit.
        nearest_strikes = sorted(
            strike_map,
            key=lambda strike: abs(float(strike) - float(underlying_price or strike)),
        )[:40]
        symbols = [
            contract.get('contract_symbol')
            for strike in nearest_strikes
            for strike_row in (strike_map[strike],)
            for contract in (strike_row.get('call'), strike_row.get('put'))
            if contract and contract.get('contract_symbol')
        ]
        try:
            snapshots = _get_webull_option_snapshots(app_key, app_secret, environment, access_token, symbols)
            for strike_row in strike_map.values():
                for contract in (strike_row.get('call'), strike_row.get('put')):
                    if contract:
                        _apply_snapshot(contract, snapshots.get(str(contract.get('contract_symbol') or '').upper()))
        except Exception as exc:
            logger.warning('Webull option snapshot enrichment unavailable for %s: %s', clean_underlying, exc)

    for strike_row in strike_map.values():
        _finish_metrics(strike_row.get('call'))
        _finish_metrics(strike_row.get('put'))

    next_expiration = None
    next_chain_rows = []
    selected_index = available_expirations.index(selected_exp)
    if selected_index + 1 < len(available_expirations):
        next_expiration = available_expirations[selected_index + 1]
        try:
            next_frame = ticker.option_chain(next_expiration)
            next_map = _build_chain_map(next_frame.calls, next_frame.puts, next_expiration)
            for strike_row in next_map.values():
                _finish_metrics(strike_row.get('call'))
                _finish_metrics(strike_row.get('put'))
            next_chain_rows = [next_map[strike] for strike in sorted(next_map)]
        except Exception as exc:
            logger.warning('Farther option expiration unavailable for %s (%s): %s', clean_underlying, next_expiration, exc)

    sorted_strikes = sorted(strike_map.keys())
    chain_rows = [strike_map[s] for s in sorted_strikes]

    return {
        'success': True,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'fresh_for_seconds': 15 if market_open else 60,
        'underlying_symbol': clean_underlying,
        'underlying_price': underlying_price,
        'underlying_prev_close': underlying_prev_close,
        'underlying_change_pct': underlying_change_pct,
        'market_status': market_status,
        'expirations': expirations_list,
        'selected_expiration': selected_exp,
        'chain': chain_rows,
        'next_expiration': next_expiration,
        'next_chain': next_chain_rows,
    }


def get_webull_stock_movers(app_key, app_secret, environment='production', access_token=None, *, direction='DESC'):
    """Return the documented U.S. stock daily gainers or losers screener."""
    safe_direction = 'ASC' if str(direction).upper() == 'ASC' else 'DESC'
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', '/market-data/screeners/gainers-losers/list',
            query_params={
                'category': 'US_STOCK', 'rank_type': 'D1',
                'sort_by': 'CHANGE_RATIO', 'direction': safe_direction,
            },
            access_token=access_token,
        ),
        'stock-movers request',
    )
    movers = []
    for record in _webull_records(payload):
        if not isinstance(record, dict) or not record.get('symbol'):
            continue
        try:
            # Webull documents change_ratio as a decimal (0.0111 = 1.11%).
            change = float(record.get('change_ratio', record.get('changeRatio', 0)) or 0) * 100
        except (TypeError, ValueError):
            change = 0.0
        try:
            price = float(record.get('price', record.get('close', 0)) or 0)
        except (TypeError, ValueError):
            price = 0.0
        movers.append({
            'symbol': str(record.get('symbol')).upper(), 'name': record.get('name'),
            'price': price, 'change': change, 'currency': record.get('currency') or 'USD',
        })
    return movers


def get_webull_order_history(app_key, app_secret, environment='production', access_token=None, page_size=100, account_id=None):
    """Return recent historical orders for Webull accounts.

    If account_id is provided, fetches only for that specific account.
    Caches results in memory for 15 seconds to prevent rate-limit thrashing.
    """
    normalized_env = normalize_webull_environment(environment)
    safe_account_id = str(account_id or '').strip() or None
    cache_key = (app_key, normalized_env, _webull_cache_principal(access_token), safe_account_id)
    now = time.time()
    if cache_key in _WEBULL_ORDER_HISTORY_CACHE:
        cached_time, cached_records = _WEBULL_ORDER_HISTORY_CACHE[cache_key]
        if now - cached_time < 15:
            return [dict(r) for r in cached_records]

    if safe_account_id:
        # The caller already selected one authorized account. Avoid an
        # additional account-list round trip for every scoped history request.
        target_accounts = [{'account_id': safe_account_id, 'account_type': 'Target'}]
    else:
        target_accounts = get_webull_accounts(app_key, app_secret, environment, access_token)

    records = []
    safe_page_size = max(1, min(int(page_size or 100), 100))
    for account in target_accounts:
        acc_id = account['account_id']
        params = {'account_id': acc_id, 'page_size': safe_page_size}
        response = _rate_limited_order_request(
            app_key, app_secret, environment, 'GET', '/trading/orders/historical-orders/list',
            query_params=params, access_token=access_token,
        )
        if getattr(response, 'status_code', None) == 404:
            response = _rate_limited_order_request(
                app_key, app_secret, environment, 'GET', '/openapi/trade/order/history',
                query_params=params, access_token=access_token,
            )
        payload = _response_payload(response, 'order-history request')
        items = payload.get('data', payload) if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get('orders') or items.get('items') or items.get('list') or []
        if not isinstance(items, list):
            continue
        for order in _flatten_webull_order_groups(items):
            if isinstance(order, dict):
                records.append({**order, '_webull_account_id': acc_id, '_webull_account_type': account.get('account_type')})

    _WEBULL_ORDER_HISTORY_CACHE[cache_key] = (now, records)
    return records


def get_webull_open_orders(app_key, app_secret, environment='production', access_token=None, page_size=100, account_id=None):
    """Return open orders for Webull accounts, read-only.

    If account_id is provided, fetches only for that specific account.
    Caches results in memory for 15 seconds to prevent rate-limit thrashing.
    """
    normalized_env = normalize_webull_environment(environment)
    safe_account_id = str(account_id or '').strip() or None
    cache_key = (app_key, normalized_env, _webull_cache_principal(access_token), safe_account_id)
    now = time.time()
    if cache_key in _WEBULL_OPEN_ORDERS_CACHE:
        cached_time, cached_records = _WEBULL_OPEN_ORDERS_CACHE[cache_key]
        if now - cached_time < 15:
            return [dict(r) for r in cached_records]

    if safe_account_id:
        # Combined Orders now requests accounts independently so each result
        # can render as soon as Webull permits it. Do not add a redundant
        # account-list lookup before that scoped request.
        target_accounts = [{'account_id': safe_account_id, 'account_type': 'Target'}]
    else:
        target_accounts = get_webull_accounts(app_key, app_secret, environment, access_token)

    records = []
    safe_page_size = max(1, min(int(page_size or 100), 100))
    for account in target_accounts:
        acc_id = account['account_id']
        params = {'account_id': acc_id, 'page_size': safe_page_size}
        response = _rate_limited_order_request(
            app_key, app_secret, environment, 'GET', '/trading/orders/open-orders/list',
            query_params=params, access_token=access_token,
        )
        if getattr(response, 'status_code', None) == 404:
            response = _rate_limited_order_request(
                app_key, app_secret, environment, 'GET', '/openapi/trade/order/open',
                query_params=params, access_token=access_token,
            )
        payload = _response_payload(response, 'open-orders request')
        items = payload.get('data', payload) if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get('orders') or items.get('items') or items.get('list') or []
        if not isinstance(items, list):
            continue
        for order in _flatten_webull_order_groups(items):
            if isinstance(order, dict):
                records.append({
                    **order,
                    '_webull_account_id': acc_id,
                    '_webull_account_type': account.get('account_type'),
                })

    _WEBULL_OPEN_ORDERS_CACHE[cache_key] = (now, records)
    return records


def create_webull_access_token(app_key, app_secret, environment='production'):
    """Request a Webull token. Production commonly returns PENDING until app/SMS approval."""
    # Match Webull's official Python SDK first. The newer documentation lists a
    # plural path, but production currently rejects our App-Key signature there
    # before it reaches the token flow. Its SDK uses this OpenAPI path.
    response = _webull_request(app_key, app_secret, environment, 'POST', '/openapi/auth/token/create', body={})
    if getattr(response, 'status_code', None) in {401, 404}:
        response = _webull_request(app_key, app_secret, environment, 'POST', '/auth/tokens/create', body={})
    return _token_details(_response_payload(response, 'token creation'), 'token creation')


def check_webull_access_token(app_key, app_secret, access_token, environment='production'):
    """Return the current status for a previously-created Webull token."""
    if not access_token:
        raise WebullConnectionError('Start Webull verification before checking its status.')
    response = _webull_request(
        app_key, app_secret, environment, 'POST', '/openapi/auth/token/check', body={'token': access_token}
    )
    if getattr(response, 'status_code', None) in {401, 404}:
        response = _webull_request(
            app_key, app_secret, environment, 'POST', '/auth/tokens/check', body={'token': access_token}
        )
    return _token_details(_response_payload(response, 'token status check'), 'token status check')


def test_webull_connection(app_key, app_secret, environment='production', access_token=None):
    """Verify credentials with the read-only account-list endpoint."""
    accounts = get_webull_accounts(app_key, app_secret, environment, access_token)

    account_types = sorted({
        account['account_type'] for account in accounts
    })
    return {
        'environment': normalize_webull_environment(environment),
        'account_count': len(accounts),
        'account_types': account_types,
    }


SUPPORTED_WEBULL_ORDER_TYPES = {
    'MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TRAILING_STOP_LOSS',
    'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN'
}
SUPPORTED_WEBULL_OPTION_STRATEGIES = {
    'SINGLE', 'COVERED_STOCK', 'VERTICAL', 'STRADDLE', 'STRANGLE', 'CALENDAR',
    'BUTTERFLY', 'CONDOR', 'IRON_BUTTERFLY', 'IRON_CONDOR',
    'COLLAR_WITH_STOCK', 'DIAGONAL',
}


def place_webull_order(
    app_key, app_secret, environment='production', access_token=None, *,
    account_id, symbol=None, instrument_type='EQUITY', side=None, order_type=None, quantity=None,
    limit_price=None, stop_price=None, time_in_force='DAY', support_trading_session='CORE',
    client_order_id=None, option_type=None, option_strike=None,
    option_expiration=None, option_underlying_symbol=None, option_strategy='SINGLE', option_legs=None,
    trailing_type=None, trailing_stop_step=None,
    entrust_type='QTY', total_cash_amount=None,
    algo_type=None, algo_start_time=None, algo_end_time=None,
    max_target_percent=None, target_vol_percent=None,
    combo_type='NORMAL', client_combo_order_id=None, combo_orders=None,
    bracket_take_profit_price=None, bracket_stop_loss_price=None, bracket_stop_loss_limit_price=None,
    event_outcome=None,
):
    """Place a live order using Webull's unified order contract.

    Supports standard stock orders, combo orders (OTO/OCO/OTOCO), take-profit/stop-loss brackets,
    trailing stops, algorithmic orders, fractional share trading (QTY or AMOUNT), and Event Contracts (LIMIT, DAY, yes/no).
    Crypto order paths remain strictly isolated and unaffected.
    """
    if not account_id:
        raise WebullConnectionError('Select a Webull account to place the order.')

    # 1. Multi-leg Combo Orders (OTO, OCO, OTOCO, etc.)
    if combo_orders and isinstance(combo_orders, list):
        if len(combo_orders) < 2:
            raise WebullConnectionError('Webull combo orders require at least 2 legs.')
        clean_combo_id = str(client_combo_order_id or uuid4().hex[:24]).strip()
        leg_payloads = []
        for i, leg in enumerate(combo_orders):
            if not isinstance(leg, dict):
                continue
            leg_sym = str(leg.get('symbol') or symbol or '').strip().upper()
            if not leg_sym:
                raise WebullConnectionError(f'Combo leg #{i + 1} requires a valid symbol.')
            leg_side = str(leg.get('side') or '').strip().upper()
            if leg_side not in {'BUY', 'SELL', 'SHORT'}:
                raise WebullConnectionError(f'Combo leg #{i + 1} side must be BUY, SELL, or SHORT.')
            leg_type = str(leg.get('order_type') or leg.get('type') or 'LIMIT').strip().upper()
            leg_type = {'STOP': 'STOP_LOSS', 'STOP_LIMIT': 'STOP_LOSS_LIMIT', 'MOO': 'MARKET_ON_OPEN', 'MOC': 'MARKET_ON_CLOSE', 'LOO': 'LIMIT_ON_OPEN'}.get(leg_type, leg_type)
            if leg_type not in SUPPORTED_WEBULL_ORDER_TYPES:
                raise WebullConnectionError(f'Combo leg #{i + 1} has unsupported order type: {leg_type}')
            leg_combo_type = str(leg.get('combo_type') or combo_type or ('MASTER' if i == 0 else 'OTO')).strip().upper()
            leg_cid = str(leg.get('client_order_id') or uuid4().hex[:24]).strip()

            leg_tif = str(leg.get('time_in_force') or time_in_force or 'DAY').upper()
            if leg_type in {'TRAILING_STOP_LOSS', 'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN'}:
                leg_tif = 'DAY'
            elif leg_tif not in {'DAY', 'GTC'}:
                leg_tif = 'DAY'

            leg_session = str(leg.get('support_trading_session') or support_trading_session or 'CORE').upper()
            if leg_session not in {'CORE', 'ALL', 'NIGHT'}:
                leg_session = 'CORE'

            leg_entrust = str(leg.get('entrust_type') or 'QTY').upper()
            leg_payload = {
                'client_order_id': leg_cid,
                'combo_type': leg_combo_type,
                'symbol': leg_sym,
                'instrument_type': 'EQUITY',
                'market': 'US',
                'order_type': leg_type,
                'side': leg_side,
                'time_in_force': leg_tif,
                'support_trading_session': leg_session,
                'entrust_type': leg_entrust,
            }

            if leg_entrust == 'AMOUNT':
                cash_amt = float(leg.get('total_cash_amount') or 0)
                if cash_amt < 5.0:
                    raise WebullConnectionError(f'Combo leg #{i + 1} cash amount must be at least $5.00.')
                leg_payload['total_cash_amount'] = f'{cash_amt:.2f}'
            else:
                try:
                    lqty = float(leg.get('quantity') or 0)
                    if lqty <= 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    raise WebullConnectionError(f'Combo leg #{i + 1} quantity must be a positive number.')
                leg_payload['quantity'] = str(lqty) if not lqty.is_integer() else str(int(lqty))

            if leg_type in {'LIMIT', 'STOP_LOSS_LIMIT', 'LIMIT_ON_OPEN'}:
                try:
                    lpx = float(leg.get('limit_price') or 0)
                    if lpx <= 0:
                        raise ValueError()
                    leg_payload['limit_price'] = f'{lpx:.4f}' if lpx < 1 else f'{lpx:.2f}'
                except (TypeError, ValueError):
                    raise WebullConnectionError(f'Combo leg #{i + 1} requires a positive limit price.')

            if leg_type in {'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
                try:
                    lspx = float(leg.get('stop_price') or 0)
                    if lspx <= 0:
                        raise ValueError()
                    leg_payload['stop_price'] = f'{lspx:.4f}' if lspx < 1 else f'{lspx:.2f}'
                except (TypeError, ValueError):
                    raise WebullConnectionError(f'Combo leg #{i + 1} requires a positive stop price.')

            leg_payloads.append(leg_payload)

        # Submit combo order
        body = {
            'account_id': str(account_id),
            'client_combo_order_id': clean_combo_id,
            'new_orders': leg_payloads,
        }
        res = _rate_limited_order_request(
            app_key, app_secret, environment, 'POST', '/trading/orders/place',
            body=body, access_token=access_token,
        )
        data = _response_payload(res, 'combo order submission')
        clear_webull_order_cache()
        return {
            'success': True,
            'order_id': clean_combo_id,
            'client_combo_order_id': clean_combo_id,
            'legs_count': len(leg_payloads),
            'raw': data,
        }

    # 2. Standard Single Order (or Master Order with attached bracket)
    clean_symbol = str(symbol or '').strip().upper()
    if not clean_symbol:
        raise WebullConnectionError('A valid instrument symbol is required.')

    clean_instrument = str(instrument_type or 'EQUITY').strip().upper()
    if clean_instrument in {'CRYPTO', 'COIN', 'TOKEN'}:
        clean_instrument = 'CRYPTO'
        if not clean_symbol.endswith('USD'):
            clean_symbol = f'{clean_symbol}USD'
    elif clean_instrument in {'OPTION', 'OPTIONS'}:
        clean_instrument = 'OPTION'
    elif clean_instrument in {'FUTURES', 'FUTURE'}:
        clean_instrument = 'FUTURES'
    elif clean_instrument in {'EVENT', 'EVENTS', 'EVENT_CONTRACT', 'EVENT_CONTRACTS'}:
        clean_instrument = 'EVENT'
    else:
        clean_instrument = 'EQUITY'

    clean_side = str(side or '').strip().upper()
    if clean_instrument == 'CRYPTO':
        if clean_side not in {'BUY', 'SELL'}:
            raise WebullConnectionError('Webull crypto orders support BUY and SELL only.')
    elif clean_instrument in {'OPTION', 'FUTURES', 'EVENT'}:
        if clean_side not in {'BUY', 'SELL'}:
            raise WebullConnectionError(f'Webull {clean_instrument.lower()} orders support BUY and SELL only.')
    else:
        if clean_side not in {'BUY', 'SELL', 'SHORT'}:
            raise WebullConnectionError('Order side must be BUY, SELL, or SHORT.')

    clean_type = str(order_type or '').strip().upper()
    clean_type = {'STOP': 'STOP_LOSS', 'STOP_LIMIT': 'STOP_LOSS_LIMIT', 'MOO': 'MARKET_ON_OPEN', 'MOC': 'MARKET_ON_CLOSE', 'LOO': 'LIMIT_ON_OPEN'}.get(clean_type, clean_type)

    if clean_instrument == 'CRYPTO':
        if clean_type not in {'MARKET', 'LIMIT', 'STOP_LOSS_LIMIT'}:
            raise WebullConnectionError('Webull crypto orders support MARKET, LIMIT, and STOP_LOSS_LIMIT only.')
    elif clean_instrument == 'OPTION':
        if clean_type not in {'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
            raise WebullConnectionError('Webull option orders support LIMIT, STOP_LOSS, and STOP_LOSS_LIMIT only.')
    elif clean_instrument == 'FUTURES':
        if clean_type not in {'MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TRAILING_STOP_LOSS'}:
            raise WebullConnectionError('Webull futures orders support MARKET, LIMIT, STOP_LOSS, STOP_LOSS_LIMIT, and TRAILING_STOP_LOSS.')
    elif clean_instrument == 'EVENT':
        if clean_type != 'LIMIT':
            raise WebullConnectionError('Webull event contract orders support LIMIT orders only.')
    else:
        if clean_type not in SUPPORTED_WEBULL_ORDER_TYPES:
            raise WebullConnectionError(f'Choose a supported stock order type: {", ".join(sorted(SUPPORTED_WEBULL_ORDER_TYPES))}.')

    clean_entrust_type = str(entrust_type or 'QTY').strip().upper()
    qty = 0.0
    if clean_instrument == 'EQUITY' and clean_entrust_type == 'AMOUNT':
        try:
            cash_val = float(total_cash_amount or 0)
            if cash_val < 5.0:
                raise ValueError()
        except (TypeError, ValueError):
            raise WebullConnectionError('Total cash amount must be at least $5.00 for cash fractional orders.')
    else:
        clean_entrust_type = 'QTY'
        try:
            qty = float(quantity)
            if qty <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise WebullConnectionError('Order quantity must be a positive number.')

    clean_client_order_id = str(client_order_id or uuid4().hex[:24]).strip()
    if not clean_client_order_id or len(clean_client_order_id) > 32:
        raise WebullConnectionError('Webull client order IDs must contain between 1 and 32 characters.')

    if clean_instrument == 'OPTION':
        if not qty.is_integer():
            raise WebullConnectionError('Webull option orders require a whole number of contracts.')
        clean_option_type = str(option_type or 'CALL').strip().upper()
        if clean_option_type not in {'CALL', 'PUT'}:
            raise WebullConnectionError('Choose CALL or PUT for the option contract.')
        try:
            clean_option_strike = float(option_strike)
            if clean_option_strike <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise WebullConnectionError('Webull option orders require a positive contract strike price.')
        clean_option_expiration = str(option_expiration or '').strip()
        try:
            datetime.strptime(clean_option_expiration, '%Y-%m-%d')
        except (TypeError, ValueError):
            raise WebullConnectionError('Webull option orders require an expiration date in YYYY-MM-DD format.')
        clean_option_underlying = ''.join(
            char for char in str(option_underlying_symbol or clean_symbol).upper() if char.isalnum()
        )
        if not clean_option_underlying:
            raise WebullConnectionError('Webull option orders require an underlying stock symbol.')
        clean_time_in_force = str(time_in_force or 'DAY').upper()
        if clean_time_in_force not in {'DAY', 'GTC'}:
            raise WebullConnectionError('Webull option orders support DAY or GTC time in force.')
        if clean_side == 'SELL' and clean_time_in_force != 'DAY':
            raise WebullConnectionError('Webull option sell orders support DAY time in force only.')
        clean_option_strategy = str(option_strategy or 'SINGLE').strip().upper()
        if clean_option_strategy not in SUPPORTED_WEBULL_OPTION_STRATEGIES:
            raise WebullConnectionError('Choose an option strategy supported by the documented Webull OpenAPI. Ratio is not currently documented.')
        if clean_option_strategy != 'SINGLE':
            if not isinstance(option_legs, list) or len(option_legs) < 2:
                raise WebullConnectionError('The selected option strategy requires at least two legs.')
            strategy_legs = []
            for index, leg in enumerate(option_legs, start=1):
                if not isinstance(leg, dict):
                    raise WebullConnectionError(f'Option strategy leg #{index} is invalid.')
                leg_instrument = str(leg.get('instrument_type') or 'OPTION').strip().upper()
                if leg_instrument not in {'OPTION', 'EQUITY'}:
                    raise WebullConnectionError(f'Option strategy leg #{index} must be OPTION or EQUITY.')
                leg_side = str(leg.get('side') or '').strip().upper()
                if leg_side not in {'BUY', 'SELL'}:
                    raise WebullConnectionError(f'Option strategy leg #{index} must use BUY or SELL.')
                try:
                    leg_ratio_quantity = float(leg.get('quantity') or 0)
                    if leg_ratio_quantity <= 0 or not leg_ratio_quantity.is_integer():
                        raise ValueError()
                except (TypeError, ValueError):
                    raise WebullConnectionError(f'Option strategy leg #{index} requires a positive whole-number quantity.')
                leg_payload = {
                    'symbol': clean_option_underlying,
                    'side': leg_side,
                    # The browser supplies the leg ratio for one strategy unit.
                    # Scale every leg by the visible order quantity so changing
                    # the ticket from one spread to two cannot submit mismatched
                    # leg quantities (for example, 200 shares + 2 covered calls).
                    'quantity': str(int(leg_ratio_quantity * qty)),
                    'instrument_type': leg_instrument,
                    'market': 'US',
                }
                if leg_instrument == 'OPTION':
                    leg_option_type = str(leg.get('option_type') or '').strip().upper()
                    if leg_option_type not in {'CALL', 'PUT'}:
                        raise WebullConnectionError(f'Option strategy leg #{index} requires CALL or PUT.')
                    try:
                        leg_strike = float(leg.get('strike_price'))
                        if leg_strike <= 0:
                            raise ValueError()
                    except (TypeError, ValueError):
                        raise WebullConnectionError(f'Option strategy leg #{index} requires a positive strike.')
                    leg_expiration = str(leg.get('option_expire_date') or '').strip()
                    try:
                        datetime.strptime(leg_expiration, '%Y-%m-%d')
                    except (TypeError, ValueError):
                        raise WebullConnectionError(f'Option strategy leg #{index} requires an expiration in YYYY-MM-DD format.')
                    leg_payload.update({
                        'strike_price': f'{leg_strike:.4f}'.rstrip('0').rstrip('.'),
                        'option_expire_date': leg_expiration,
                        'option_type': leg_option_type,
                    })
                strategy_legs.append(leg_payload)
        else:
            strategy_legs = [{
                'symbol': clean_option_underlying,
                'side': clean_side,
                'quantity': str(int(qty)),
                'strike_price': f'{clean_option_strike:.4f}'.rstrip('0').rstrip('.'),
                'option_expire_date': clean_option_expiration,
                'instrument_type': 'OPTION',
                'option_type': clean_option_type,
                'market': 'US',
            }]
        order_payload = {
            'combo_type': 'NORMAL',
            'client_order_id': clean_client_order_id,
            'symbol': clean_option_underlying,
            'instrument_type': 'OPTION',
            'market': 'US',
            'order_type': clean_type,
            'side': clean_side,
            'option_strategy': clean_option_strategy,
            'quantity': str(int(qty)),
            'time_in_force': clean_time_in_force,
            'entrust_type': 'QTY',
            'legs': strategy_legs,
        }
    elif clean_instrument == 'FUTURES':
        if not qty.is_integer():
            raise WebullConnectionError('Webull futures orders require a whole number of contracts.')
        clean_time_in_force = str(time_in_force or 'DAY').upper()
        if clean_time_in_force not in {'DAY', 'GTC'}:
            raise WebullConnectionError('Webull futures orders support DAY or GTC time in force.')
        order_payload = {
            'combo_type': 'NORMAL',
            'client_order_id': clean_client_order_id,
            'symbol': clean_symbol,
            'instrument_type': 'FUTURES',
            'market': 'US',
            'order_type': clean_type,
            'side': clean_side,
            'quantity': str(int(qty)),
            'time_in_force': clean_time_in_force,
            'entrust_type': 'QTY',
        }
    elif clean_instrument == 'EVENT':
        if not qty.is_integer() or int(qty) < 1:
            raise WebullConnectionError('Webull event contract orders require a whole number of contracts (at least 1).')
        if int(qty) > 50000:
            raise WebullConnectionError('Maximum quantity for Webull event contracts is 50,000 contracts per order.')
        clean_outcome = str(event_outcome or 'YES').strip().lower()
        if clean_outcome not in {'yes', 'no'}:
            raise WebullConnectionError('Event outcome must be specified as "yes" or "no".')
        try:
            epx = float(limit_price)
            if epx < 0.01 or epx > 0.99:
                raise ValueError()
        except (TypeError, ValueError):
            raise WebullConnectionError('Event contract limit price must be between $0.01 and $0.99 per contract.')
        order_payload = {
            'combo_type': 'NORMAL',
            'client_order_id': clean_client_order_id,
            'symbol': clean_symbol,
            'instrument_type': 'EVENT',
            'market': 'US',
            'order_type': 'LIMIT',
            'limit_price': f'{epx:.2f}',
            'quantity': str(int(qty)),
            'side': clean_side,
            'time_in_force': 'DAY',
            'entrust_type': 'QTY',
            'event_outcome': clean_outcome,
        }
    else:
        # Stock (EQUITY) or Crypto
        clean_session = str(support_trading_session or 'CORE').upper()
        if clean_instrument == 'EQUITY' and clean_session not in {'CORE', 'ALL', 'NIGHT'}:
            raise WebullConnectionError('Choose Regular (CORE), Extended (ALL), or Overnight (NIGHT) trading hours.')

        clean_time_in_force = str(time_in_force or 'DAY').upper()
        if clean_instrument == 'CRYPTO':
            if clean_time_in_force not in {'DAY', 'GTC', 'IOC'}:
                clean_time_in_force = 'DAY'
        else:
            if clean_type in {'TRAILING_STOP_LOSS', 'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN'}:
                clean_time_in_force = 'DAY'
            elif clean_time_in_force not in {'DAY', 'GTC'}:
                clean_time_in_force = 'DAY'

        order_payload = {
            'combo_type': str(combo_type or 'NORMAL').upper(),
            'client_order_id': clean_client_order_id,
            'symbol': clean_symbol,
            'instrument_type': clean_instrument,
            'market': 'US',
            'order_type': clean_type,
            'side': clean_side,
            'time_in_force': clean_time_in_force,
            'support_trading_session': clean_session if clean_instrument == 'EQUITY' else None,
            'entrust_type': clean_entrust_type,
        }

        if clean_entrust_type == 'AMOUNT':
            order_payload['total_cash_amount'] = f'{float(total_cash_amount):.2f}'
        else:
            order_payload['quantity'] = str(qty) if clean_instrument == 'CRYPTO' or not qty.is_integer() else str(int(qty))

        order_payload = {key: value for key, value in order_payload.items() if value is not None}

    # Price validations
    if clean_type in {'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
        try:
            spx = float(stop_price)
            if spx <= 0:
                raise ValueError()
            order_payload['stop_price'] = f'{spx:.4f}' if spx < 1 else f'{spx:.2f}'
        except (TypeError, ValueError):
            raise WebullConnectionError('Stop orders require a valid stop price greater than 0.')

    if clean_type in {'LIMIT', 'STOP_LOSS_LIMIT', 'LIMIT_ON_OPEN'}:
        try:
            px = float(limit_price)
            if px <= 0:
                raise ValueError()
            order_payload['limit_price'] = f'{px:.4f}' if px < 1 else f'{px:.2f}'
        except (TypeError, ValueError):
            raise WebullConnectionError('Limit orders require a valid price greater than 0.')

    if clean_type == 'TRAILING_STOP_LOSS':
        clean_trailing_type = str(trailing_type or 'AMOUNT').strip().upper()
        if clean_trailing_type not in {'AMOUNT', 'PERCENTAGE'}:
            raise WebullConnectionError('Choose AMOUNT or PERCENTAGE for trailing stop.')
        try:
            clean_trailing_step = float(trailing_stop_step)
            if clean_trailing_step <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise WebullConnectionError('Trailing stops require a positive trail amount or percentage.')
        order_payload['trailing_type'] = clean_trailing_type
        order_payload['trailing_stop_step'] = f'{clean_trailing_step:.4f}'.rstrip('0').rstrip('.')
        order_payload['time_in_force'] = 'DAY'

    # Algorithmic Orders (EQUITY only)
    if clean_instrument == 'EQUITY' and algo_type:
        clean_algo_type = str(algo_type).strip().upper()
        if clean_algo_type in {'TWAP', 'VWAP', 'POV'}:
            if clean_type not in {'MARKET', 'LIMIT'}:
                raise WebullConnectionError('Algorithmic orders support MARKET and LIMIT orders only.')
            if clean_session != 'CORE':
                raise WebullConnectionError('Algorithmic orders run only during Regular Trading Hours (CORE).')
            if not algo_start_time or not algo_end_time:
                raise WebullConnectionError('Algorithmic orders require start and end times in HH:mm:ss format (Eastern Time).')
            order_payload['algo_type'] = clean_algo_type
            order_payload['algo_start_time'] = str(algo_start_time).strip()
            order_payload['algo_end_time'] = str(algo_end_time).strip()
            if clean_algo_type in {'TWAP', 'VWAP'}:
                pct = max(1, min(20, int(float(max_target_percent or 10))))
                order_payload['max_target_percent'] = str(pct)
            elif clean_algo_type == 'POV':
                pct = max(1, min(20, int(float(target_vol_percent or 10))))
                order_payload['target_vol_percent'] = str(pct)

    # Check for attached Take-Profit / Stop-Loss bracket
    if clean_instrument == 'EQUITY' and (bracket_take_profit_price or bracket_stop_loss_price):
        order_payload['combo_type'] = 'MASTER'
        bracket_legs = [order_payload]
        clean_combo_id = str(client_combo_order_id or uuid4().hex[:24]).strip()
        opp_side = 'SELL' if clean_side == 'BUY' else 'BUY'

        if bracket_take_profit_price:
            try:
                tp_val = float(bracket_take_profit_price)
                if tp_val <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise WebullConnectionError('Take profit price must be greater than 0.')
            tp_leg = {
                'client_order_id': uuid4().hex[:24],
                'combo_type': 'STOP_PROFIT',
                'symbol': clean_symbol,
                'instrument_type': 'EQUITY',
                'market': 'US',
                'order_type': 'LIMIT',
                'side': opp_side,
                'quantity': order_payload.get('quantity', '1'),
                'limit_price': f'{tp_val:.4f}' if tp_val < 1 else f'{tp_val:.2f}',
                'time_in_force': 'DAY',
                'support_trading_session': clean_session,
                'entrust_type': 'QTY',
            }
            bracket_legs.append(tp_leg)

        if bracket_stop_loss_price:
            try:
                sl_val = float(bracket_stop_loss_price)
                if sl_val <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise WebullConnectionError('Stop loss price must be greater than 0.')
            sl_leg_type = 'STOP_LOSS_LIMIT' if bracket_stop_loss_limit_price else 'STOP_LOSS'
            sl_leg = {
                'client_order_id': uuid4().hex[:24],
                'combo_type': 'STOP_LOSS',
                'symbol': clean_symbol,
                'instrument_type': 'EQUITY',
                'market': 'US',
                'order_type': sl_leg_type,
                'side': opp_side,
                'quantity': order_payload.get('quantity', '1'),
                'stop_price': f'{sl_val:.4f}' if sl_val < 1 else f'{sl_val:.2f}',
                'time_in_force': 'DAY',
                'support_trading_session': clean_session,
                'entrust_type': 'QTY',
            }
            if bracket_stop_loss_limit_price:
                try:
                    sll_val = float(bracket_stop_loss_limit_price)
                    if sll_val <= 0:
                        raise ValueError()
                    sl_leg['limit_price'] = f'{sll_val:.4f}' if sll_val < 1 else f'{sll_val:.2f}'
                except (TypeError, ValueError):
                    raise WebullConnectionError('Stop loss limit price must be greater than 0.')
            bracket_legs.append(sl_leg)

        request_body = {
            'account_id': str(account_id),
            'client_combo_order_id': clean_combo_id,
            'new_orders': bracket_legs,
        }
    else:
        request_body = {
            'account_id': str(account_id),
            'new_orders': [order_payload],
        }
        if order_payload.get('combo_type') and order_payload['combo_type'] != 'NORMAL':
            request_body['client_combo_order_id'] = str(client_combo_order_id or uuid4().hex[:24]).strip()

    response = _webull_request(
        app_key, app_secret, environment, 'POST', '/trading/orders/place',
        body=request_body, access_token=access_token,
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        legacy_request_body = {
            'account_id': str(account_id),
            'orders': request_body['new_orders'],
        }
        if 'client_combo_order_id' in request_body:
            legacy_request_body['client_combo_order_id'] = request_body['client_combo_order_id']
        response = _webull_request(
            app_key, app_secret, environment, 'POST', '/openapi/account/orders/place',
            body=legacy_request_body, access_token=access_token,
        )

    payload = _response_payload(response, 'order placement')
    data = payload.get('data', payload) if isinstance(payload, dict) else payload
    order_id = None
    if isinstance(data, dict):
        order_id = data.get('order_id') or data.get('orderId')
        items = data.get('orders') or data.get('items')
        if not order_id and isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                order_id = first.get('order_id') or first.get('orderId')

    clear_webull_order_cache()
    primary_leg = request_body['new_orders'][0]
    return {
        'success': True,
        'order_id': order_id or request_body.get('client_combo_order_id') or primary_leg['client_order_id'],
        'client_order_id': primary_leg['client_order_id'],
        'client_combo_order_id': request_body.get('client_combo_order_id'),
        'symbol': primary_leg.get('symbol', clean_symbol),
        'side': primary_leg.get('side', clean_side),
        'order_type': primary_leg.get('order_type', clean_type),
        'quantity': primary_leg.get('quantity', qty),
        'legs_count': len(request_body['new_orders']),
        'raw': data,
    }


def cancel_webull_order(
    app_key, app_secret, environment='production', access_token=None, *,
    account_id, client_order_id=None, order_id=None,
):
    """Cancel an open order on Webull."""
    if not account_id:
        raise WebullConnectionError('Account ID is required to cancel a Webull order.')
    if not client_order_id and not order_id:
        raise WebullConnectionError('Either client_order_id or order_id is required.')

    body = {'account_id': str(account_id)}
    if client_order_id:
        body['client_order_id'] = str(client_order_id)
    if order_id:
        body['order_id'] = str(order_id)

    response = _webull_request(
        app_key, app_secret, environment, 'POST', '/trading/orders/cancel',
        body=body, access_token=access_token,
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        response = _webull_request(
            app_key, app_secret, environment, 'POST', '/openapi/account/orders/cancel',
            body=body, access_token=access_token,
        )

    payload = _response_payload(response, 'order cancellation')
    clear_webull_order_cache()
    return {
        'success': True,
        'order_id': order_id or client_order_id,
        'raw': payload.get('data', payload) if isinstance(payload, dict) else payload,
    }
