"""Read-only Webull OpenAPI connection and 2FA-token helpers."""

import base64
import hashlib
import hmac
from datetime import datetime, timezone
import json
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


def _webull_request(app_key, app_secret, environment, method, path, *, body=None, access_token=None):
    """Make one signed Webull request without exposing any secret in logs or responses."""
    if not app_key or not app_secret:
        raise WebullConnectionError('Webull App Key and App Secret are required.')

    normalized_environment = normalize_webull_environment(environment)
    host = WEBULL_ENVIRONMENTS[normalized_environment]
    body_string = json.dumps(body, separators=(',', ':')) if body is not None else None
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    nonce = uuid4().hex
    signature = generate_webull_signature(
        path, {}, app_key, app_secret, host, timestamp, nonce, body_string
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


def create_webull_access_token(app_key, app_secret, environment='production'):
    """Request a Webull token. Production commonly returns PENDING until app/SMS approval."""
    # The current public API documents the plural endpoint. The official SDK still
    # uses the legacy OpenAPI endpoint, so only fall back when the documented path
    # is not available; never create a second token after a substantive response.
    response = _webull_request(app_key, app_secret, environment, 'POST', '/auth/tokens/create', body={})
    if getattr(response, 'status_code', None) == 404:
        response = _webull_request(app_key, app_secret, environment, 'POST', '/openapi/auth/token/create', body={})
    return _token_details(_response_payload(response, 'token creation'), 'token creation')


def check_webull_access_token(app_key, app_secret, access_token, environment='production'):
    """Return the current status for a previously-created Webull token."""
    if not access_token:
        raise WebullConnectionError('Start Webull verification before checking its status.')
    response = _webull_request(
        app_key, app_secret, environment, 'POST', '/auth/tokens/check', body={'token': access_token}
    )
    if getattr(response, 'status_code', None) == 404:
        response = _webull_request(
            app_key, app_secret, environment, 'POST', '/openapi/auth/token/check', body={'token': access_token}
        )
    return _token_details(_response_payload(response, 'token status check'), 'token status check')


def test_webull_connection(app_key, app_secret, environment='production', access_token=None):
    """Verify credentials with the read-only account-list endpoint."""
    response = get_webull_account_list(app_key, app_secret, environment, access_token)

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
