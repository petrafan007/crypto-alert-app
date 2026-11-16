"""Regression tests for the v4.17.0 QA fixes."""
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db


class TaxEngineTests(unittest.TestCase):
    def build(self, txs, method='FIFO', wash=False):
        from services.tax_engine import build_tax_transactions
        return build_tax_transactions(txs, method, wash_sales=wash)

    def test_anniversary_day_after_purchase_time_is_still_short_term(self):
        rows, _ = self.build([
            {'id': 1, 'date': datetime(2024, 1, 15, 10), 'type': 'BUY', 'asset': 'BTC', 'amount': 1, 'cost_basis': 100},
            {'id': 2, 'date': datetime(2025, 1, 15, 23), 'type': 'SELL', 'asset': 'BTC', 'amount': -1, 'proceeds': 150},
        ])
        self.assertEqual(rows[1]['gain_loss_type'], 'short_term')

    def test_hifo_sells_highest_cost_lot_first(self):
        rows, lots = self.build([
            {'id': 1, 'date': datetime(2025, 1, 1), 'type': 'BUY', 'asset': 'ETH', 'amount': 1, 'cost_basis': 100},
            {'id': 2, 'date': datetime(2025, 2, 1), 'type': 'BUY', 'asset': 'ETH', 'amount': 1, 'cost_basis': 300},
            {'id': 3, 'date': datetime(2025, 3, 1), 'type': 'SELL', 'asset': 'ETH', 'amount': -1, 'proceeds': 200},
        ], method='HIFO')
        self.assertAlmostEqual(rows[2]['gain_loss'], -100)
        self.assertAlmostEqual(lots['BINANCE:ETH'][0]['cost'], 100)

    def test_specific_lot_selection_overrides_method(self):
        rows, _ = self.build([
            {'id': 1, 'date': datetime(2025, 1, 1), 'type': 'BUY', 'asset': 'ETH', 'amount': 1, 'cost_basis': 100},
            {'id': 2, 'date': datetime(2025, 2, 1), 'type': 'BUY', 'asset': 'ETH', 'amount': 1, 'cost_basis': 300},
            {'id': 3, 'date': datetime(2025, 3, 1), 'type': 'SELL', 'asset': 'ETH', 'amount': -1, 'proceeds': 200,
             'lot_selection': ['2']},
        ])
        self.assertAlmostEqual(rows[2]['gain_loss'], -100)

    def test_outbound_transfer_removes_lots_and_inbound_without_basis_is_flagged(self):
        rows, lots = self.build([
            {'id': 1, 'date': datetime(2025, 1, 1), 'type': 'BUY', 'asset': 'SOL', 'amount': 2, 'cost_basis': 200},
            {'id': 2, 'date': datetime(2025, 1, 2), 'type': 'TRANSFER', 'asset': 'SOL', 'amount': -1},
            {'id': 3, 'date': datetime(2025, 1, 3), 'type': 'RECEIVE', 'asset': 'SOL', 'amount': 1},
        ])
        self.assertAlmostEqual(sum(l['amount'] for l in lots['BINANCE:SOL']), 2)
        self.assertTrue(rows[2]['needs_review'])

    def test_staking_reward_is_income_and_starts_a_lot(self):
        rows, lots = self.build([
            {'id': 's1', 'date': datetime(2025, 1, 1), 'type': 'STAKING', 'asset': 'ETH', 'amount': 0.1, 'usd_value': 300},
        ])
        self.assertAlmostEqual(rows[0]['income'], 300)
        self.assertAlmostEqual(lots['BINANCE:ETH'][0]['cost'], 300)

    def test_sale_beyond_purchases_is_flagged_not_silent(self):
        rows, _ = self.build([
            {'id': 1, 'date': datetime(2025, 1, 1), 'type': 'SELL', 'asset': 'XRP', 'amount': -5, 'proceeds': 10},
        ])
        self.assertAlmostEqual(rows[0]['missing_basis_quantity'], 5)
        self.assertTrue(rows[0]['needs_review'])

    def test_wash_sale_disallows_loss_and_adjusts_replacement_basis(self):
        key = {'_asset_key': 'webull:a:USD:EQUITY:AAPL', '_security_key': 'EQUITY:AAPL', 'asset': 'AAPL'}
        rows, lots = self.build([
            {'id': 1, 'date': datetime(2025, 1, 1), 'type': 'BUY', 'amount': 10, 'cost_basis': 1000, **key},
            {'id': 2, 'date': datetime(2025, 2, 1), 'type': 'SELL', 'amount': -10, 'proceeds': 800, **key},
            {'id': 3, 'date': datetime(2025, 2, 10), 'type': 'BUY', 'amount': 10, 'cost_basis': 850, **key},
        ], wash=True)
        sale = rows[1]
        self.assertAlmostEqual(sale['wash_sale_disallowed'], 200)
        self.assertEqual(sale['adjustment_code'], 'W')
        self.assertAlmostEqual(sale['gain_loss'], 0)
        self.assertAlmostEqual(lots['WEBULL:A:USD:EQUITY:AAPL'][0]['cost'], 1050)

    def test_form_8949_splits_parts(self):
        from services.tax_engine import form_8949_rows, schedule_d_totals
        rows, _ = self.build([
            {'id': 1, 'date': datetime(2023, 1, 1), 'type': 'BUY', 'asset': 'BTC', 'amount': 1, 'cost_basis': 100},
            {'id': 2, 'date': datetime(2025, 1, 1), 'type': 'BUY', 'asset': 'BTC', 'amount': 1, 'cost_basis': 200},
            {'id': 3, 'date': datetime(2025, 6, 1), 'type': 'SELL', 'asset': 'BTC', 'amount': -1, 'proceeds': 300},
            {'id': 4, 'date': datetime(2025, 7, 1), 'type': 'SELL', 'asset': 'BTC', 'amount': -1, 'proceeds': 300},
        ])
        totals = schedule_d_totals(form_8949_rows(rows, 2025))
        self.assertEqual(totals['II']['gain_loss'], 200.0)
        self.assertEqual(totals['I']['gain_loss'], 100.0)


class PaperMatchingRulesTests(unittest.TestCase):
    def test_marketable_limit_fills_at_market_and_resting_limit_waits(self):
        from services.binance_paper_matching import immediate_fill_price
        self.assertEqual(immediate_fill_price('LIMIT', 'BUY', 110, None, 100), 100)
        self.assertIsNone(immediate_fill_price('LIMIT', 'BUY', 90, None, 100))
        self.assertIsNone(immediate_fill_price('LIMIT', 'SELL', 110, None, 100))

    def test_stops_wait_for_trigger_and_immediate_triggers_are_rejected(self):
        from services.binance_paper_matching import immediate_fill_price, validate_new_order, PaperOrderRejected
        self.assertIsNone(immediate_fill_price('STOP_LOSS_LIMIT', 'SELL', 94, 95, 100))
        self.assertEqual(immediate_fill_price('STOP_LOSS_LIMIT', 'SELL', 94, 95, 95), 95)
        with self.assertRaises(PaperOrderRejected):
            validate_new_order('STOP_LOSS_LIMIT', 'SELL', 94, 95, 90)
        with self.assertRaises(PaperOrderRejected):
            validate_new_order('LIMIT_MAKER', 'BUY', 101, None, 100)


class AutoSellMatchingTests(unittest.TestCase):
    def test_base_asset_is_exact(self):
        from services.scheduler_tasks import base_asset_of
        self.assertEqual(base_asset_of('AVAXUSDT'), 'AVAX')
        self.assertEqual(base_asset_of('ETHFIUSD'), 'ETHFI')
        self.assertEqual(base_asset_of('ETHBTC'), 'ETH')
        self.assertNotEqual(base_asset_of('AVAXUSDT'), 'AVA')


class SettingsWriterTests(unittest.TestCase):
    def test_toast_toggle_wins_over_stale_browser_key(self):
        from services.user_settings_writer import normalize_aliases
        data = normalize_aliases({'toast_notifications_enabled': False, 'browser_notifications_enabled': True})
        self.assertIs(data['browser_notifications_enabled'], False)

    def test_invalid_values_are_reported_and_max_tokens_saves(self):
        from services import user_settings_writer as writer
        self.assertIn('ai_max_tokens', writer.validate({'ai_max_tokens': 99999}))
        self.assertIn('volatility_hours', writer.validate({'volatility_hours': 'abc'}))
        self.assertIn('tax_cost_basis_method', writer.validate({'tax_cost_basis_method': 'avg'}))
        target = SimpleNamespace()
        writer.apply(target, {'ai_max_tokens': '3000', 'browser_notifications_enabled': False})
        self.assertEqual(target.ai_max_tokens, 3000)
        self.assertIs(target.browser_notifications_enabled, False)


class DbBackedTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SECRET_KEY='test', TESTING=True)
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        from trading_models import TradingSettings, TestOrder, RealOrder, LadderOrder, LadderRung, TrailingOrder, SyntheticExecution, SyntheticRecovery
        from models import CredentialHealth, Notification
        from credentials import User, Credential, UserSetting
        for model in (TradingSettings, TestOrder, RealOrder, LadderOrder, LadderRung, TrailingOrder, SyntheticExecution,
                      SyntheticRecovery, CredentialHealth, Notification, User, Credential, UserSetting):
            model.__table__.create(db.engine, checkfirst=True)

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_totp_code_works_once(self):
        import pyotp
        from trading_models import TradingSettings
        from services.totp_service import consume_totp_code
        secret = pyotp.random_base32()
        settings = TradingSettings(user_id=5, totp_secret=secret)
        db.session.add(settings)
        db.session.commit()
        code = pyotp.TOTP(secret).now()
        self.assertTrue(consume_totp_code(settings, code))
        self.assertFalse(consume_totp_code(settings, code))

    def test_repeated_auth_failures_pause_and_new_keys_resume(self):
        from services import credential_health as health

        class AuthError(Exception):
            code = -2015
        with patch.object(health, '_notify_paused') as notify:
            for _ in range(3):
                health.record_failure(9, 'binance', AuthError('Invalid API-key, IP, or permissions for action.'))
            self.assertTrue(health.is_paused(9, 'binance'))
            notify.assert_called_once()
            health.record_failure(9, 'binance', TimeoutError('read timed out'))
        health.resume(9, 'binance')
        self.assertFalse(health.is_paused(9, 'binance'))

    def test_unknown_or_finished_orders_are_never_reported_as_replaced(self):
        from trading_models import TestOrder
        from services.order_replacement_service import cancel_any_order
        db.session.add(TestOrder(id=50, user_id=1, symbol='ETHUSDT', side='BUY', type='LIMIT', quantity=1, price=1, status='FILLED'))
        db.session.commit()
        self.assertFalse(cancel_any_order('50', 1, symbol='ETHUSDT', test_mode=True)['success'])
        self.assertFalse(cancel_any_order('no-such-order', 1)['success'])
        self.assertFalse(cancel_any_order('51', 1, test_mode=True)['success'])

    def test_failed_live_binance_cancel_is_not_success(self):
        from services import order_replacement_service as svc

        class Client:
            def get_order(self, **kwargs):
                return {'status': 'NEW', 'executedQty': '0', 'symbol': 'BTCUSDT'}

            def cancel_order(self, **kwargs):
                raise RuntimeError('exchange refused')
        with patch.object(svc, '_binance_client_for', return_value=Client()):
            result = svc.cancel_any_order('123456789', 1, symbol='BTCUSDT', test_mode=False)
        self.assertFalse(result['success'])
        self.assertIn('exchange refused', result['error'])


if __name__ == '__main__':
    unittest.main()
