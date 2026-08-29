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
WEBULL_CHARTABLE_INSTRUMENT_TYPES = {'CRYPTO', 'STOCK', 'EQUITY', 'ETF', 'OPTION'}
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

    Stocks/ETFs and crypto use separate documented Webull endpoints.  The
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
    if is_crypto and not clean_symbol.endswith('USD'):
        clean_symbol = f'{clean_symbol}USD'
    if is_option and not instrument_id:
        raise WebullConnectionError('This option has no Webull contract identifier yet. Refresh the Webull portfolio import after the contract is available.')
    path = (
        '/market-data/crypto/bars/list' if is_crypto else
        '/market-data/options/bars/list' if is_option else
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
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', path,
            query_params=params, access_token=access_token,
        ),
        'market-data request',
    )
    bars_by_time = {}
    for raw_bar in _webull_records(payload):
        bar = _normalise_webull_bar(raw_bar)
        if bar:
            bars_by_time[bar['time']] = bar
    return [bars_by_time[timestamp] for timestamp in sorted(bars_by_time)]


def get_webull_market_snapshot(
    app_key, app_secret, environment='production', access_token=None, *, symbol, instrument_type,
):
    """Fetch one current Webull stock/ETF or crypto quote, without trading.

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
    if clean_type not in {'CRYPTO', 'STOCK', 'EQUITY', 'ETF'}:
        raise WebullConnectionError('This Webull instrument type does not have a supported live quote.')

    if clean_type == 'CRYPTO':
        path = '/market-data/crypto/snapshots/list'
        params = {'symbols': clean_symbol, 'symbol': clean_symbol}
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


def _normalise_option_snapshot(payload):
    """Extract quote and Greeks from documented/legacy option snapshot shapes."""
    raw = _first_option_record(payload)
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
        'volume': number('volume'),
        'open_interest': number('open_interest', 'openInterest'),
        'implied_volatility': number('implied_volatility', 'impliedVolatility', 'iv'),
        'delta': number('delta') if number('delta') is not None else _numeric_greek(greeks, 'delta'),
        'gamma': number('gamma') if number('gamma') is not None else _numeric_greek(greeks, 'gamma'),
        'theta': number('theta') if number('theta') is not None else _numeric_greek(greeks, 'theta'),
        'vega': number('vega') if number('vega') is not None else _numeric_greek(greeks, 'vega'),
        'rho': number('rho') if number('rho') is not None else _numeric_greek(greeks, 'rho'),
        'as_of': value('timestamp', 'time', 'last_trade_time', 'trade_time'),
    }


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

    strike_map = {}

    if calls_df is not None and not calls_df.empty:
        for _, row in calls_df.iterrows():
            strike = _clean_num(row.get('strike'))
            if strike <= 0:
                continue
            if strike not in strike_map:
                strike_map[strike] = {'strike': strike, 'call': None, 'put': None}
            bid = _clean_num(row.get('bid'))
            ask = _clean_num(row.get('ask'))
            mid = round((bid + ask) / 2.0, 2) if (bid > 0 and ask > 0) else _clean_num(row.get('lastPrice'))
            strike_map[strike]['call'] = {
                'contract_symbol': str(row.get('contractSymbol') or ''),
                'strike': strike,
                'option_type': 'CALL',
                'expiration': selected_exp,
                'bid': bid,
                'ask': ask,
                'mid': mid,
                'last': _clean_num(row.get('lastPrice')),
                'change': _clean_num(row.get('change')),
                'percent_change': _clean_num(row.get('percentChange')),
                'volume': _clean_int(row.get('volume')),
                'open_interest': _clean_int(row.get('openInterest')),
                'implied_volatility': round(_clean_num(row.get('impliedVolatility')) * 100, 1),
                'in_the_money': bool(row.get('inTheMoney') or (underlying_price > 0 and strike < underlying_price)),
            }

    if puts_df is not None and not puts_df.empty:
        for _, row in puts_df.iterrows():
            strike = _clean_num(row.get('strike'))
            if strike <= 0:
                continue
            if strike not in strike_map:
                strike_map[strike] = {'strike': strike, 'call': None, 'put': None}
            bid = _clean_num(row.get('bid'))
            ask = _clean_num(row.get('ask'))
            mid = round((bid + ask) / 2.0, 2) if (bid > 0 and ask > 0) else _clean_num(row.get('lastPrice'))
            strike_map[strike]['put'] = {
                'contract_symbol': str(row.get('contractSymbol') or ''),
                'strike': strike,
                'option_type': 'PUT',
                'expiration': selected_exp,
                'bid': bid,
                'ask': ask,
                'mid': mid,
                'last': _clean_num(row.get('lastPrice')),
                'change': _clean_num(row.get('change')),
                'percent_change': _clean_num(row.get('percentChange')),
                'volume': _clean_int(row.get('volume')),
                'open_interest': _clean_int(row.get('openInterest')),
                'implied_volatility': round(_clean_num(row.get('impliedVolatility')) * 100, 1),
                'in_the_money': bool(row.get('inTheMoney') or (underlying_price > 0 and strike > underlying_price)),
            }

    sorted_strikes = sorted(strike_map.keys())
    chain_rows = [strike_map[s] for s in sorted_strikes]

    return {
        'success': True,
        'underlying_symbol': clean_underlying,
        'underlying_price': underlying_price,
        'underlying_prev_close': underlying_prev_close,
        'underlying_change_pct': underlying_change_pct,
        'market_status': market_status,
        'expirations': expirations_list,
        'selected_expiration': selected_exp,
        'chain': chain_rows,
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


def place_webull_order(
    app_key, app_secret, environment='production', access_token=None, *,
    account_id, symbol, instrument_type, side, order_type, quantity,
    limit_price=None, stop_price=None, time_in_force='DAY', support_trading_session='CORE',
    client_order_id=None, option_type=None, option_strike=None,
    option_expiration=None, option_underlying_symbol=None,
):
    """Place a live order using Webull's current unified order contract.

    The current API expects ``new_orders`` at ``/trading/orders/place``.  A
    narrowly scoped legacy fallback remains only for installations whose
    OpenAPI deployment does not expose that endpoint.  Options must carry the
    exact single-leg contract terms; sending only an option type is never a
    valid substitute for a strike and expiration.
    """
    if not account_id:
        raise WebullConnectionError('Select a Webull account to place the order.')
    clean_symbol = str(symbol or '').strip().upper()
    if not clean_symbol:
        raise WebullConnectionError('A valid instrument symbol is required.')
    clean_side = str(side or '').strip().upper()
    if clean_side not in {'BUY', 'SELL', 'SHORT'}:
        raise WebullConnectionError('Order side must be BUY or SELL.')
    clean_type = str(order_type or '').strip().upper()
    clean_type = {'STOP': 'STOP_LOSS', 'STOP_LIMIT': 'STOP_LOSS_LIMIT'}.get(clean_type, clean_type)
    if clean_type not in {'MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
        raise WebullConnectionError('Choose a supported order type: MARKET, LIMIT, STOP_LOSS, or STOP_LOSS_LIMIT.')
    clean_instrument = str(instrument_type or 'EQUITY').strip().upper()
    if clean_instrument in {'CRYPTO', 'COIN', 'TOKEN'}:
        clean_instrument = 'CRYPTO'
        if not clean_symbol.endswith('USD'):
            clean_symbol = f'{clean_symbol}USD'
    elif clean_instrument in {'OPTION', 'OPTIONS'}:
        clean_instrument = 'OPTION'
    elif clean_instrument in {'ETF', 'STOCK', 'SECURITY', 'EQUITY'}:
        clean_instrument = 'EQUITY'
    else:
        clean_instrument = 'EQUITY'

    try:
        qty = float(quantity)
        if qty <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise WebullConnectionError('Order quantity must be a positive number.')

    clean_client_order_id = str(client_order_id or uuid4().hex).strip()
    if not clean_client_order_id or len(clean_client_order_id) > 32:
        raise WebullConnectionError('Webull client order IDs must contain between 1 and 32 characters.')

    if clean_instrument == 'OPTION':
        if clean_side not in {'BUY', 'SELL'}:
            raise WebullConnectionError('Webull option orders support BUY and SELL only.')
        if clean_type not in {'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
            raise WebullConnectionError('Webull option orders support LIMIT, STOP_LOSS, and STOP_LOSS_LIMIT only.')
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
        order_payload = {
            'combo_type': 'NORMAL',
            'client_order_id': clean_client_order_id,
            'symbol': clean_option_underlying,
            'instrument_type': 'OPTION',
            'market': 'US',
            'order_type': clean_type,
            'side': clean_side,
            'option_strategy': 'SINGLE',
            'quantity': str(int(qty)),
            'time_in_force': clean_time_in_force,
            'entrust_type': 'QTY',
            'legs': [{
                'symbol': clean_option_underlying,
                'side': clean_side,
                'quantity': str(int(qty)),
                'strike_price': f'{clean_option_strike:.4f}'.rstrip('0').rstrip('.'),
                'option_expire_date': clean_option_expiration,
                'instrument_type': 'OPTION',
                'option_type': clean_option_type,
                'market': 'US',
            }],
        }
    else:
        clean_session = str(support_trading_session or 'CORE').upper()
        if clean_instrument == 'EQUITY' and clean_session not in {'CORE', 'ALL', 'NIGHT'}:
            raise WebullConnectionError('Choose Regular, Including Extended, or Overnight trading hours.')
        clean_time_in_force = str(time_in_force or 'DAY').upper()
        allowed_time_in_force = {'DAY', 'GTC'} if clean_instrument == 'EQUITY' else {'DAY', 'GTC', 'IOC'}
        if clean_time_in_force not in allowed_time_in_force:
            raise WebullConnectionError(
                'Webull crypto orders support DAY, GTC, or IOC time in force.'
                if clean_instrument == 'CRYPTO' else 'Webull stock and ETF orders support DAY or GTC time in force.'
            )
        if clean_instrument == 'EQUITY' and not qty.is_integer():
            if clean_session != 'CORE':
                raise WebullConnectionError('Fractional stock and ETF orders are available only during Regular Hours. Extended and Overnight sessions require whole shares.')
            if clean_type != 'MARKET':
                raise WebullConnectionError('Webull supports fractional stock and ETF orders as Market orders during Regular Hours.')
            if qty > 1:
                raise WebullConnectionError('A Webull fractional stock or ETF order must be greater than zero and no more than one share.')
        order_payload = {
            'combo_type': 'NORMAL',
            'client_order_id': clean_client_order_id,
            'symbol': clean_symbol,
            'instrument_type': clean_instrument,
            'market': 'US',
            'order_type': clean_type,
            'side': clean_side,
            'quantity': str(qty) if clean_instrument == 'CRYPTO' or qty != int(qty) else str(int(qty)),
            'time_in_force': clean_time_in_force,
            'support_trading_session': clean_session if clean_instrument == 'EQUITY' else None,
            'entrust_type': 'QTY',
        }
        order_payload = {key: value for key, value in order_payload.items() if value is not None}
    if clean_type in {'STOP_LOSS', 'STOP_LOSS_LIMIT'}:
        try:
            spx = float(stop_price)
            if spx <= 0:
                raise ValueError()
            order_payload['stop_price'] = f'{spx:.4f}' if spx < 1 else f'{spx:.2f}'
        except (TypeError, ValueError):
            raise WebullConnectionError('Stop orders require a valid stop price greater than 0.')

    if clean_type in {'LIMIT', 'STOP_LOSS_LIMIT'}:
        try:
            px = float(limit_price)
            if px <= 0:
                raise ValueError()
            order_payload['limit_price'] = f'{px:.4f}' if px < 1 else f'{px:.2f}'
        except (TypeError, ValueError):
            raise WebullConnectionError('Limit orders require a valid price greater than 0.')

    request_body = {
        'account_id': str(account_id),
        'new_orders': [order_payload],
    }

    response = _webull_request(
        app_key, app_secret, environment, 'POST', '/trading/orders/place',
        body=request_body, access_token=access_token,
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        legacy_request_body = {
            'account_id': str(account_id),
            'orders': [order_payload],
        }
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
    return {
        'success': True,
        'order_id': order_id or order_payload['client_order_id'],
        'client_order_id': order_payload['client_order_id'],
        'symbol': clean_symbol,
        'side': clean_side,
        'order_type': clean_type,
        'quantity': qty,
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
