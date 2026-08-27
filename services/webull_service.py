"""Read-only Webull OpenAPI connection helpers."""

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


def create_webull_trade_client(app_key, app_secret, environment='production'):
    """Create an official Webull Trading API client without placing any orders."""
    if not app_key or not app_secret:
        raise WebullConnectionError('Webull App Key and App Secret are required.')

    try:
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
    except ImportError as exc:
        raise WebullConnectionError('The Webull SDK is not installed on this server.') from exc

    normalized_environment = normalize_webull_environment(environment)
    api_client = ApiClient(app_key, app_secret, 'us')
    api_client.add_endpoint('us', WEBULL_ENVIRONMENTS[normalized_environment])
    return TradeClient(api_client)


def test_webull_connection(app_key, app_secret, environment='production'):
    """Verify credentials with the read-only account-list endpoint."""
    client = create_webull_trade_client(app_key, app_secret, environment)
    try:
        response = client.account_v2.get_account_list()
    except Exception as exc:
        logger.warning('Webull account-list connection check failed: %s', exc)
        raise WebullConnectionError(f'Webull connection failed: {exc}') from exc

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
