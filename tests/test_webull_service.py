import unittest
from unittest.mock import Mock, patch

from services.webull_service import (
    WebullConnectionError,
    normalize_webull_environment,
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
        client = Mock()
        client.account_v2.get_account_list.return_value = response

        with patch('services.webull_service.create_webull_trade_client', return_value=client):
            result = check_webull_connection('app-key', 'app-secret', 'sandbox')

        self.assertEqual(result, {
            'environment': 'sandbox',
            'account_count': 2,
            'account_types': ['OPTION', 'STOCK'],
        })

    def test_non_success_response_is_not_treated_as_connected(self):
        response = Mock(status_code=401, text='Unauthorized')
        client = Mock()
        client.account_v2.get_account_list.return_value = response

        with patch('services.webull_service.create_webull_trade_client', return_value=client):
            with self.assertRaisesRegex(WebullConnectionError, 'HTTP 401'):
                check_webull_connection('app-key', 'app-secret')
