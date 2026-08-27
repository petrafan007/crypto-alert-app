import unittest
from unittest.mock import Mock, patch

from services.webull_service import (
    WebullConnectionError,
    check_webull_access_token,
    create_webull_access_token,
    generate_webull_signature,
    get_webull_accounts,
    get_webull_portfolio_preview,
    normalize_webull_environment,
    parse_webull_expiry,
    test_webull_connection as check_webull_connection,
)


class WebullServiceTests(unittest.TestCase):
    def test_environment_normalization_accepts_only_supported_values(self):
        self.assertEqual(normalize_webull_environment('Production'), 'production')
        self.assertEqual(normalize_webull_environment('sandbox'), 'sandbox')
        with self.assertRaises(WebullConnectionError):
            normalize_webull_environment('staging')

    def test_account_list_connection_check_returns_non_sensitive_summary(self):
        response = Mock(status_code=200)
        response.json.return_value = [
            {'account_id': '111111', 'account_type': 'STOCK'},
            {'account_id': '222222', 'account_type': 'OPTION'},
        ]
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            result = check_webull_connection('app-key', 'app-secret', 'sandbox')

        self.assertEqual(result, {
            'environment': 'sandbox',
            'account_count': 2,
            'account_types': ['OPTION', 'STOCK'],
        })

    def test_account_discovery_accepts_enveloped_webull_account_lists(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'accounts': [{'accountId': '12345678', 'accountType': 'OPTION', 'accountName': 'Options'}]}
        }
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            accounts = get_webull_accounts('app-key', 'app-secret', access_token='private-token')

        self.assertEqual(accounts, [{
            'account_id': '12345678', 'account_type': 'OPTION', 'account_name': 'Options'
        }])

    def test_non_success_response_is_not_treated_as_connected(self):
        response = Mock(status_code=401, text='Unauthorized')
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            with self.assertRaisesRegex(WebullConnectionError, 'HTTP 401'):
                check_webull_connection('app-key', 'app-secret')

    def test_create_token_normalizes_pending_response_without_exposing_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'token': 'private-token', 'status': 'PENDING', 'expires': '2026-08-27T12:00:00Z'
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = create_webull_access_token('app-key', 'app-secret', 'production')

        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(result['token'], 'private-token')
        self.assertEqual(request_mock.call_args.args[4], '/openapi/auth/token/create')

    def test_check_token_posts_the_saved_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'token': 'private-token', 'status': 'NORMAL', 'expires': 1787832000}
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = check_webull_access_token('app-key', 'app-secret', 'private-token', 'sandbox')

        self.assertEqual(result['status'], 'NORMAL')
        self.assertEqual(request_mock.call_args.kwargs['body'], {'token': 'private-token'})
        self.assertIsNotNone(parse_webull_expiry(result['expires']))

    def test_token_creation_retries_the_documented_path_after_sdk_path_auth_failure(self):
        rejected = Mock(status_code=401, text='Unauthorized')
        accepted = Mock(status_code=200)
        accepted.json.return_value = {
            'token': 'private-token', 'status': 'PENDING', 'expires': '2026-08-27T12:00:00Z'
        }
        with patch('services.webull_service._webull_request', side_effect=[rejected, accepted]) as request_mock:
            result = create_webull_access_token('app-key', 'app-secret')

        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(request_mock.call_args_list[1].args[4], '/auth/tokens/create')

    def test_expiry_parser_accepts_webull_epoch_milliseconds(self):
        parsed = parse_webull_expiry(1787832000000)
        self.assertEqual(parsed.year, 2026)

    def test_portfolio_preview_uses_all_discovered_accounts_without_importing(self):
        accounts = [{'account_id': '1234', 'account_type': 'STOCK', 'account_name': 'Individual'}]
        with patch('services.webull_service.get_webull_accounts', return_value=accounts), \
             patch('services.webull_service.get_webull_account_balance', return_value={'total_cash_balance': '10'}), \
             patch('services.webull_service.get_webull_account_positions', return_value=[{'symbol': 'AAPL'}]):
            preview = get_webull_portfolio_preview('app-key', 'app-secret', access_token='private-token')

        self.assertEqual(preview, [{
            'account_id': '1234', 'account_type': 'STOCK', 'account_name': 'Individual',
            'balance': {'total_cash_balance': '10'}, 'positions': [{'symbol': 'AAPL'}],
        }])

    def test_signature_matches_webulls_documented_example(self):
        signature = generate_webull_signature(
            '/trade/place_order',
            {'a1': 'webull', 'a2': '123', 'a3': 'xxx', 'q1': 'yyy'},
            '776da210ab4a452795d74e726ebd74b6',
            '0f50a2e853334a9aae1a783bee120c1f',
            'api.webull.com',
            '2022-01-04T03:55:31Z',
            '48ef5afed43d4d91ae514aaeafbc29ba',
            '{"k1":123,"k2":"this is the api request body","k3":true,"k4":{"foo":[1,2]}}',
        )
        self.assertEqual(signature, 'kvlS6opdZDhEBo5jq40nHYXaLvM=')
