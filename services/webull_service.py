"""Read-only Webull OpenAPI connection helpers."""

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

import requests

from log import logger


WEBULL_ENVIRONMENTS = {
    'production': 'api.webull.com',
    'sandbox': 'api.sandbox.webull.com',
}


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


def get_webull_account_list(app_key, app_secret, environment='production'):
    """Call Webull's read-only account-list endpoint with a signed request."""
    if not app_key or not app_secret:
        raise WebullConnectionError('Webull App Key and App Secret are required.')

    normalized_environment = normalize_webull_environment(environment)
    host = WEBULL_ENVIRONMENTS[normalized_environment]
    path = '/openapi/account/list'
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    nonce = uuid4().hex
    signature = generate_webull_signature(
        path, {}, app_key, app_secret, host, timestamp, nonce
    )
    headers = {
        'x-app-key': app_key,
        'x-timestamp': timestamp,
        'x-signature': signature,
        'x-signature-algorithm': 'HMAC-SHA1',
        'x-signature-version': '1.0',
        'x-signature-nonce': nonce,
        'x-version': 'v2',
    }
    try:
        return requests.get(f'https://{host}{path}', headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise WebullConnectionError(f'Webull connection failed: {exc}') from exc


def test_webull_connection(app_key, app_secret, environment='production'):
    """Verify credentials with the read-only account-list endpoint."""
    response = get_webull_account_list(app_key, app_secret, environment)

    status_code = getattr(response, 'status_code', None)
    if status_code != 200:
        detail = getattr(response, 'text', '') or 'Webull did not accept these credentials.'
        raise WebullConnectionError(f'Webull connection failed (HTTP {status_code}): {detail}')

    try:
        payload = response.json()
    except Exception as exc:
        raise WebullConnectionError('Webull returned an unreadable account-list response.') from exc

    accounts = payload.get('data', []) if isinstance(payload, dict) else payload
    if not isinstance(accounts, list):
        accounts = []

    account_types = sorted({
        str(account.get('account_type') or account.get('type') or 'Unknown')
        for account in accounts
        if isinstance(account, dict)
    })
    return {
        'environment': normalize_webull_environment(environment),
        'account_count': len(accounts),
        'account_types': account_types,
    }
