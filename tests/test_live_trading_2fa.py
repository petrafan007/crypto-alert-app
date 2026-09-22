import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, session

from services.trading_2fa_service import require_live_trading_2fa


class _Query:
    def __init__(self, value):
        self.value = value

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self.value


class LiveTradingTwoFactorTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='live-trading-2fa-tests', TESTING=True)

    def test_live_trading_is_blocked_without_an_enrolled_authenticator(self):
        with self.app.test_request_context(), patch(
            'services.trading_2fa_service.TradingSettings.query',
            _Query(SimpleNamespace(totp_secret=None, require_2fa=False)),
        ):
            error = require_live_trading_2fa(7, {}, 'place this live order')
        self.assertIn('Set up two-factor authentication', error)

    def test_setting_flag_cannot_bypass_a_required_live_code(self):
        settings = SimpleNamespace(totp_secret='secret', require_2fa=False)
        with self.app.test_request_context(), \
                patch('services.trading_2fa_service.TradingSettings.query', _Query(settings)), \
                patch('services.trading_2fa_service.verify_totp_code', return_value=True) as verify:
            self.assertIsNone(require_live_trading_2fa(7, {'two_factor_code': '123456'}))
            verify.assert_called_once_with('secret', '123456')

    def test_verified_session_token_is_single_use(self):
        settings = SimpleNamespace(totp_secret='secret', require_2fa=False)
        with self.app.test_request_context(), patch(
            'services.trading_2fa_service.TradingSettings.query', _Query(settings),
        ):
            session['2fa_verified_once'] = {'user_id': 7, 'timestamp': time.time()}
            self.assertIsNone(require_live_trading_2fa(7, {'twofa_token': 'once'}))
            self.assertIn('fresh six-digit', require_live_trading_2fa(7, {'twofa_token': 'once'}))

    def test_expired_or_other_user_token_is_rejected_and_consumed(self):
        settings = SimpleNamespace(totp_secret='secret', require_2fa=True)
        with self.app.test_request_context(), patch(
            'services.trading_2fa_service.TradingSettings.query', _Query(settings),
        ):
            session['2fa_verified_expired'] = {'user_id': 7, 'timestamp': time.time() - 121}
            session['2fa_verified_other'] = {'user_id': 8, 'timestamp': time.time()}
            self.assertIsNotNone(require_live_trading_2fa(7, {'twofa_token': 'expired'}))
            self.assertIsNotNone(require_live_trading_2fa(7, {'twofa_token': 'other'}))
            self.assertNotIn('2fa_verified_expired', session)
            self.assertNotIn('2fa_verified_other', session)


if __name__ == '__main__':
    unittest.main()
