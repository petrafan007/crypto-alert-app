"""Read-only Webull OpenAPI connection and 2FA-token helpers."""

import base64
import hashlib
import hmac
from datetime import datetime, timezone
import json
import time
from urllib.parse import quote
from uuid import uuid4

import requests

from log import logger


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
    """Call Webull's read-only account-list endpoint with a signed request."""
    return _webull_request(
        app_key, app_secret, environment, 'GET', '/openapi/account/list', access_token=access_token
    )


def get_webull_accounts(app_key, app_secret, environment='production', access_token=None):
    """Return the authenticated user's Webull accounts using the established read-only endpoint."""
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
        accounts.append({
            'account_id': str(account_id),
            'account_type': str(account.get('account_type') or account.get('accountType') or account.get('type') or 'Unknown'),
            'account_name': str(account.get('account_name') or account.get('accountName') or account.get('name') or ''),
        })
    return accounts


def _get_webull_account_resource(app_key, app_secret, environment, access_token, account_id, legacy_path, current_path):
    response = _webull_request(
        app_key, app_secret, environment, 'GET', legacy_path,
        query_params={'account_id': account_id}, access_token=access_token,
    )
    if getattr(response, 'status_code', None) == 404:
        response = _webull_request(
            app_key, app_secret, environment, 'GET', current_path,
            query_params={'account_id': account_id}, access_token=access_token,
        )
    return _response_payload(response, 'account resource request')


def get_webull_account_balance(app_key, app_secret, environment, access_token, account_id):
    """Fetch one selected account's balance, without persisting it."""
    payload = _get_webull_account_resource(
        app_key, app_secret, environment, access_token, account_id,
        '/openapi/assets/balance', '/trading/assets/balances/get',
    )
    return payload.get('data', payload) if isinstance(payload, dict) else payload


def get_webull_account_positions(app_key, app_secret, environment, access_token, account_id):
    """Fetch one selected account's open positions, without persisting them."""
    payload = _get_webull_account_resource(
        app_key, app_secret, environment, access_token, account_id,
        '/openapi/assets/positions', '/trading/assets/positions/list',
    )
    positions = payload.get('data', payload) if isinstance(payload, dict) else payload
    if isinstance(positions, dict):
        positions = positions.get('positions') or positions.get('items') or []
    return positions if isinstance(positions, list) else []


def get_webull_portfolio_preview(app_key, app_secret, environment='production', access_token=None):
    """Read selected accounts' balances and positions for preview only; performs no imports or trading."""
    preview = []
    for index, account in enumerate(get_webull_accounts(app_key, app_secret, environment, access_token)):
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


def get_webull_option_contracts(app_key, app_secret, environment='production', access_token=None, *, underlying_symbol):
    """Fetch static contracts for one underlying; no trading endpoint is used."""
    clean_underlying = ''.join(char for char in str(underlying_symbol or '').upper() if char.isalnum())
    if not clean_underlying:
        raise WebullConnectionError('An option underlying symbol is required to resolve a contract.')
    payload = _response_payload(
        _webull_request(
            app_key, app_secret, environment, 'GET', '/trading/instruments/options/contracts/list',
            query_params={'symbol': clean_underlying, 'underlying_symbol': clean_underlying, 'status': 'ACTIVE', 'page_size': 100},
            access_token=access_token,
        ),
        'option-contract lookup',
    )
    return _webull_records(payload)


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


def get_webull_order_history(app_key, app_secret, environment='production', access_token=None, page_size=100):
    """Return recent historical orders for every authenticated Webull account.

    This only uses Webull's historical-order query endpoint. It never queries
    open orders and cannot place, amend, or cancel an order.
    """
    records = []
    safe_page_size = max(1, min(int(page_size or 100), 100))
    for index, account in enumerate(get_webull_accounts(app_key, app_secret, environment, access_token)):
        if index:
            # Production Order History is limited to two requests per two seconds.
            time.sleep(2.05)
        account_id = account['account_id']
        params = {'account_id': account_id, 'page_size': safe_page_size}
        response = _webull_request(
            app_key, app_secret, environment, 'GET', '/trading/orders/historical-orders/list',
            query_params=params, access_token=access_token,
        )
        # Retain the legacy path as a compatibility fallback for older approved
        # Webull applications, just as the account resources do.
        if getattr(response, 'status_code', None) == 404:
            response = _webull_request(
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
                records.append({**order, '_webull_account_id': account_id, '_webull_account_type': account.get('account_type')})
    return records


def get_webull_open_orders(app_key, app_secret, environment='production', access_token=None, page_size=100):
    """Return open orders for every authenticated Webull account, read-only.

    This intentionally uses only order-list APIs.  It is used to present a
    combined order view in the app and never creates, changes, or cancels a
    Webull order.
    """
    records = []
    safe_page_size = max(1, min(int(page_size or 100), 100))
    for index, account in enumerate(get_webull_accounts(app_key, app_secret, environment, access_token)):
        if index:
            time.sleep(2.05)
        account_id = account['account_id']
        params = {'account_id': account_id, 'page_size': safe_page_size}
        response = _webull_request(
            app_key, app_secret, environment, 'GET', '/trading/orders/open-orders/list',
            query_params=params, access_token=access_token,
        )
        if getattr(response, 'status_code', None) == 404:
            response = _webull_request(
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
                    '_webull_account_id': account_id,
                    '_webull_account_type': account.get('account_type'),
                })
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
    limit_price=None, time_in_force='DAY', support_trading_session='CORE',
    client_order_id=None,
):
    """Place a live order on Webull for equities, ETFs, or crypto."""
    if not account_id:
        raise WebullConnectionError('Select a Webull account to place the order.')
    clean_symbol = str(symbol or '').strip().upper()
    if not clean_symbol:
        raise WebullConnectionError('A valid instrument symbol is required.')
    clean_side = str(side or '').strip().upper()
    if clean_side not in {'BUY', 'SELL', 'SHORT'}:
        raise WebullConnectionError('Order side must be BUY or SELL.')
    clean_type = str(order_type or '').strip().upper()
    if clean_type not in {'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'}:
        raise WebullConnectionError('Choose a supported order type: MARKET or LIMIT.')
    clean_instrument = str(instrument_type or 'EQUITY').strip().upper()
    if clean_instrument in {'CRYPTO', 'COIN', 'TOKEN'}:
        clean_instrument = 'CRYPTO'
        if not clean_symbol.endswith('USD'):
            clean_symbol = f'{clean_symbol}USD'
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

    order_payload = {
        'combo_type': 'NORMAL',
        'client_order_id': client_order_id or uuid4().hex,
        'symbol': clean_symbol,
        'instrument_type': clean_instrument,
        'order_type': clean_type,
        'side': clean_side,
        'quantity': str(qty) if clean_instrument == 'CRYPTO' or qty != int(qty) else str(int(qty)),
        'time_in_force': str(time_in_force or 'DAY').upper(),
        'support_trading_session': str(support_trading_session or 'CORE').upper(),
    }
    if clean_type in {'LIMIT', 'STOP_LIMIT'}:
        try:
            px = float(limit_price)
            if px <= 0:
                raise ValueError()
            order_payload['limit_price'] = f'{px:.4f}' if px < 1 else f'{px:.2f}'
        except (TypeError, ValueError):
            raise WebullConnectionError('Limit orders require a valid price greater than 0.')

    request_body = {
        'account_id': str(account_id),
        'orders': [order_payload],
    }

    response = _webull_request(
        app_key, app_secret, environment, 'POST', '/openapi/account/orders/place',
        body=request_body, access_token=access_token,
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        response = _webull_request(
            app_key, app_secret, environment, 'POST', '/trading/orders/stock/place',
            body=request_body, access_token=access_token,
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
        app_key, app_secret, environment, 'POST', '/openapi/account/orders/cancel',
        body=body, access_token=access_token,
    )
    if getattr(response, 'status_code', None) in {404, 405}:
        response = _webull_request(
            app_key, app_secret, environment, 'POST', '/trading/orders/stock/cancel',
            body=body, access_token=access_token,
        )

    payload = _response_payload(response, 'order cancellation')
    return {
        'success': True,
        'order_id': order_id or client_order_id,
        'raw': payload.get('data', payload) if isinstance(payload, dict) else payload,
    }

