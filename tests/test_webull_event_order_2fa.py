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


class WebullEventOrderTwoFactorTests(unittest.TestCase):
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

    def test_verified_token_event_order_reaches_webull_submission(self):
        event_market = {'symbol': self.order['symbol'], 'rules': {'settlement': '1.00'}}
        with self.app.test_request_context('/api/webull/orders/place', method='POST', json=self.order):
            session['2fa_verified_verified-token'] = {'user_id': 1, 'timestamp': time.time()}
            self.assertIn('2fa_verified_verified-token', session)
            with patch.object(system, 'current_user', SimpleNamespace(id=1)), \
                 patch.object(system.UserSetting, 'query', _Query(self.setting)), \
                 patch.object(system.Credential, 'query', _Query(self.credential)), \
                 patch('trading_models.TradingSettings.query', _Query(self.trading_settings)), \
                 patch.object(system, '_preflight_webull_event_order', return_value=event_market), \
                 patch.object(system, '_require_webull_account_access', return_value='account-1'), \
                 patch.object(system, '_require_webull_instrument_account_match', return_value='EVENT'), \
                 patch.object(system, 'place_webull_order', return_value={'order_id': 'webull-event-1'}) as place_order:
                response = system.api_webull_place_order.__wrapped__()

            if isinstance(response, tuple):
                response, status_code = response
            else:
                status_code = response.status_code
            self.assertEqual(status_code, 200, response.get_json())
            self.assertTrue(response.get_json()['success'])
            self.assertNotIn('2fa_verified_verified-token', session)
            self.assertEqual(place_order.call_args.kwargs['event_market'], event_market)
            self.assertEqual(place_order.call_args.kwargs['event_outcome'], 'yes')


if __name__ == '__main__':
    unittest.main()