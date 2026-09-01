import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, session

import routes.system as system


class _Query:
    def __init__(self, value):
        self.value = value

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self.value


class WebullOrderTwoFactorTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret'
        self.setting = SimpleNamespace(webull_test_mode_enabled=False, webull_environment='production')
        self.credential = SimpleNamespace(
            webull_app_key='app-key',
            webull_app_secret='app-secret',
            webull_access_token='access-token',
            webull_token_status='NORMAL',
            webull_token_environment='production',
        )
        self.trading_settings = SimpleNamespace(require_2fa=True, totp_secret='secret')
        self.order = {
            'account_id': 'account-1',
            'symbol': 'KXBTC15M-26SEP011030-30',
            'instrument_type': 'EVENT',
            'side': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 1,
            'limit_price': 0.35,
            'time_in_force': 'DAY',
            'event_outcome': 'yes',
            'twofa_token': 'verified-token',
        }

    def _submit_with_verified_token(self, order, *extra_patches):
        token = order['twofa_token']
        with self.app.test_request_context('/api/webull/orders/place', method='POST', json=order):
            session[f'2fa_verified_{token}'] = {'user_id': 1, 'timestamp': time.time()}
            with patch.object(system, 'current_user', SimpleNamespace(id=1)), \
                 patch.object(system.UserSetting, 'query', _Query(self.setting)), \
                 patch.object(system.Credential, 'query', _Query(self.credential)), \
                 patch('trading_models.TradingSettings.query', _Query(self.trading_settings)), \
                 patch.object(system, '_require_webull_account_access', return_value='account-1'), \
                 patch.object(system, '_require_webull_instrument_account_match', side_effect=lambda _setting, _account, instrument: instrument), \
                 patch.object(system, 'place_webull_order', return_value={'order_id': 'webull-order-1'}) as place_order:
                for patcher in extra_patches:
                    patcher.start()
                try:
                    response = system.api_webull_place_order.__wrapped__()
                finally:
                    for patcher in reversed(extra_patches):
                        patcher.stop()

            if isinstance(response, tuple):
                response, status_code = response
            else:
                status_code = response.status_code
            self.assertEqual(status_code, 200, response.get_json())
            self.assertTrue(response.get_json()['success'])
            self.assertNotIn(f'2fa_verified_{token}', session)
            return place_order

    def test_verified_token_event_order_reaches_webull_submission(self):
        event_market = {'symbol': self.order['symbol'], 'rules': {'settlement': '1.00'}}
        place_order = self._submit_with_verified_token(
            self.order, patch.object(system, '_preflight_webull_event_order', return_value=event_market),
        )
        self.assertEqual(place_order.call_args.kwargs['event_market'], event_market)
        self.assertEqual(place_order.call_args.kwargs['event_outcome'], 'yes')

    def test_verified_token_option_order_reaches_webull_submission(self):
        order = {
            'account_id': 'account-1', 'symbol': 'SPY', 'instrument_type': 'OPTION',
            'side': 'BUY', 'order_type': 'LIMIT', 'quantity': 1, 'limit_price': 4.20,
            'time_in_force': 'DAY', 'option_type': 'PUT', 'option_strike': 745,
            'option_expiration': '2026-09-25', 'option_underlying_symbol': 'SPY',
            'option_strategy': 'SINGLE', 'twofa_token': 'option-token',
        }
        place_order = self._submit_with_verified_token(
            order, patch.object(system, '_live_webull_option_order_capability', return_value=(1_000, 0)),
        )
        self.assertEqual(place_order.call_args.kwargs['instrument_type'], 'OPTION')
        self.assertEqual(place_order.call_args.kwargs['option_type'], 'PUT')
        self.assertEqual(place_order.call_args.kwargs['option_strike'], 745)
        self.assertEqual(place_order.call_args.kwargs['option_expiration'], '2026-09-25')

    def test_option_provider_rejection_is_visible_after_verified_token(self):
        order = {
            'account_id': 'account-1', 'symbol': 'SPY', 'instrument_type': 'OPTION',
            'side': 'BUY', 'order_type': 'LIMIT', 'quantity': 1, 'limit_price': 4.20,
            'time_in_force': 'DAY', 'option_type': 'PUT', 'option_strike': 745,
            'option_expiration': '2026-09-25', 'option_underlying_symbol': 'SPY',
            'option_strategy': 'SINGLE', 'twofa_token': 'rejected-option-token',
        }
        with self.app.test_request_context('/api/webull/orders/place', method='POST', json=order):
            session['2fa_verified_rejected-option-token'] = {'user_id': 1, 'timestamp': time.time()}
            with patch.object(system, 'current_user', SimpleNamespace(id=1)), \
                 patch.object(system.UserSetting, 'query', _Query(self.setting)), \
                 patch.object(system.Credential, 'query', _Query(self.credential)), \
                 patch('trading_models.TradingSettings.query', _Query(self.trading_settings)), \
                 patch.object(system, '_require_webull_account_access', return_value='account-1'), \
                 patch.object(system, '_require_webull_instrument_account_match', return_value='OPTION'), \
                 patch.object(system, '_live_webull_option_order_capability', return_value=(1_000, 0)), \
                 patch.object(system, 'place_webull_order', side_effect=system.WebullConnectionError('Provider rejected this order.')) as place_order:
                response, status_code = system.api_webull_place_order.__wrapped__()

            self.assertEqual(status_code, 400)
            self.assertEqual(response.get_json(), {
                'success': False,
                'message': 'Provider rejected this order.',
            })
            self.assertEqual(place_order.call_count, 1)
            self.assertNotIn('2fa_verified_rejected-option-token', session)

    def test_verified_token_futures_order_reaches_webull_submission(self):
        order = {
            'account_id': 'account-1', 'symbol': 'ESZ5', 'instrument_type': 'FUTURES',
            'side': 'BUY', 'order_type': 'LIMIT', 'quantity': 1, 'limit_price': 6500,
            'time_in_force': 'DAY', 'twofa_token': 'futures-token',
        }
        place_order = self._submit_with_verified_token(
            order, patch.object(system, 'get_webull_futures_contracts', return_value=[{'symbol': 'ESZ5'}]),
        )
        self.assertEqual(place_order.call_args.kwargs['instrument_type'], 'FUTURES')
        self.assertEqual(place_order.call_args.kwargs['symbol'], 'ESZ5')
        self.assertEqual(place_order.call_args.kwargs['limit_price'], 6500)


if __name__ == '__main__':
    unittest.main()