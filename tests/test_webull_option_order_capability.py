import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routes.system import (
    _live_webull_option_order_capability,
    _webull_position_matches_option_contract,
)


class WebullOptionOrderCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.contract = {
            'underlying_symbol': 'NVDA',
            'option_type': 'CALL',
            'option_strike': 200,
            'option_expiration': '2026-08-31',
        }
        self.position = {
            'instrument_type': 'OPTION',
            'quantity': '2',
            'option': {
                'underlying_symbol': 'NVDA',
                'option_type': 'CALL',
                'strike_price': '200.00',
                'option_expire_date': '2026-08-31T00:00:00Z',
            },
        }

    def test_contract_match_requires_every_contract_identity_field(self):
        self.assertTrue(_webull_position_matches_option_contract(self.position, **self.contract))

        for field, invalid_value in {
            'underlying_symbol': 'AMD',
            'option_type': 'PUT',
            'option_strike': 205,
            'option_expiration': '2026-09-07',
        }.items():
            requested = {**self.contract, field: invalid_value}
            self.assertFalse(_webull_position_matches_option_contract(self.position, **requested))

    @patch('routes.system.get_webull_portfolio_preview')
    def test_live_capability_uses_current_cash_and_only_exact_contracts(self, mock_preview):
        wrong_contract = {
            **self.position,
            'quantity': '9',
            'option': {**self.position['option'], 'option_type': 'PUT'},
        }
        mock_preview.return_value = [{
            'account_id': 'acct-1',
            'balance': {'total_cash_balance': '425.50'},
            'positions': [self.position, wrong_contract],
        }]
        credential = SimpleNamespace(
            webull_app_key='key', webull_app_secret='secret', webull_access_token='token',
        )

        cash, contracts = _live_webull_option_order_capability(
            credential, 'production', 'acct-1', **self.contract,
        )

        self.assertEqual(cash, 425.50)
        self.assertEqual(contracts, 2)
        mock_preview.assert_called_once()


if __name__ == '__main__':
    unittest.main()
