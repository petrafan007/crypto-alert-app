"""Synthetic stock/ETF orders that run in Regular + Extended Hours.

Webull accepts only whole-share Limit orders outside Regular Hours, so an
extended-hours execution is a Limit order capped past the trigger price and
cancelled if it does not fill in time. All venue I/O is mocked.
"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from core.extensions import db
from trading_models import LadderOrder
from services import synthetic_execution_service as ex
from services import ladder_order_service as ladder
from services.market_calendar_service import equity_session_phase
from tests import test_synthetic_order_lifecycle as base

# Monday 16 November 2026, a regular trading day (EST, UTC-5).
PRE_MARKET = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)    # 4:30 AM ET
REGULAR = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)       # 10:00 AM ET
AFTER_HOURS = datetime(2026, 11, 16, 22, 0, tzinfo=timezone.utc)   # 5:00 PM ET


class ExtendedHoursSessionTests(unittest.TestCase):
    def test_session_phase_follows_the_exchange_calendar(self):
        cases = [
            (datetime(2026, 11, 16, 8, 30, tzinfo=timezone.utc), None),        # 3:30 AM ET
            (PRE_MARKET, 'EXTENDED'),
            (REGULAR, 'CORE'),
            (AFTER_HOURS, 'EXTENDED'),
            (datetime(2026, 11, 17, 1, 30, tzinfo=timezone.utc), None),        # 8:30 PM ET, overnight
            (datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc), None),        # Saturday
            (datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc), None),        # Thanksgiving
            (datetime(2026, 11, 27, 21, 30, tzinfo=timezone.utc), 'EXTENDED'), # half day, 4:30 PM ET
            (datetime(2026, 11, 27, 22, 30, tzinfo=timezone.utc), None),       # half day, 5:30 PM ET
        ]
        for moment, expected in cases:
            with self.subTest(moment=moment.isoformat()):
                self.assertEqual(equity_session_phase(moment), expected)

    def test_identity_accepts_extended_hours_and_refuses_overnight(self):
        identity = ex.validate_identity('NVDA', 'BUY', 'webull', 'EQUITY', 'ALL', 'ACC1', False)
        self.assertEqual(identity[4], 'ALL')
        with self.assertRaisesRegex(ValueError, 'Overnight is not supported'):
            ex.validate_identity('NVDA', 'BUY', 'webull', 'EQUITY', 'NIGHT', 'ACC1', False)
        self.assertEqual(ex.validate_identity('BTCUSD', 'BUY', 'webull', 'CRYPTO', 'ALL', 'ACC1', False)[4], 'CORE')

    def test_limit_cap_and_capped_limit_price(self):
        self.assertIsNone(ex.limit_cap(2, 'CORE'))
        self.assertEqual(ex.limit_cap(None, 'ALL'), ex.DEFAULT_LIMIT_CAP_PCT)
        self.assertEqual(ex.limit_cap('0.5', 'ALL'), 0.5)
        for bad in (0, 0.05, 6, 'abc'):
            with self.subTest(cap=bad), self.assertRaises(ValueError):
                ex.limit_cap(bad, 'ALL')
        self.assertEqual(ex.extended_limit_price('BUY', 165, 1.0), 166.65)
        self.assertEqual(ex.extended_limit_price('SELL', 160, 1.0), 158.4)


class ExtendedHoursExecutionTests(unittest.TestCase):
    setUp = base.SyntheticLifecycleTests.setUp
    tearDown = base.SyntheticLifecycleTests.tearDown
    create = base.SyntheticLifecycleTests.create
    tick = base.SyntheticLifecycleTests.tick

    def live_two_sided_buy(self, **kwargs):
        args = dict(broker='webull', instrument_type='EQUITY', symbol='NVDA', side='BUY', total_quantity=1,
                    test_mode=False, account_id='ACC1', trading_session='ALL', limit_cap_pct=1.0,
                    upside_mode='SINGLE', upside_target_price=110, downside_mode='SINGLE', downside_target_price=90)
        args.update(kwargs)
        with patch.object(ex, 'webull_buy_cash', return_value=100000):
            return self.create(**args)

    def live_patches(self, now, detail):
        cred = SimpleNamespace(webull_app_key='key', webull_app_secret='secret', webull_access_token='token')
        self.webull_submit.side_effect = None
        self.webull_submit.return_value = {'success': True, 'order_id': 'WB1'}
        return [
            patch.object(ex, 'utc_now', side_effect=lambda aware=False: now if aware else now.replace(tzinfo=None)),
            patch.object(ex, 'webull_credentials', return_value=(cred, 'production')),
            patch('services.webull_service.get_webull_account_balance', return_value={'available_cash': 100000}),
            patch('services.webull_service.get_webull_order_detail', return_value=detail),
        ]

    def test_fractional_quantity_is_refused_for_extended_hours(self):
        with self.assertRaisesRegex(ValueError, 'whole shares'):
            self.live_two_sided_buy(total_quantity=1.5)

    def test_extended_hours_trigger_sends_a_capped_whole_share_limit(self):
        parent = self.live_two_sided_buy()
        self.assertEqual(parent.limit_cap_pct, 1.0)
        patches = self.live_patches(AFTER_HOURS, {'order_id': 'WB1', 'status': 'FILLED', 'filled_qty': '1', 'filled_price': '90.4'})
        for p in patches:
            p.start()
        try:
            self.tick(parent, 90)
            kwargs = self.webull_submit.call_args.kwargs
            self.assertEqual((kwargs['order_type'], kwargs['limit_price'], kwargs['quantity'],
                              kwargs['support_trading_session'], kwargs['time_in_force']),
                             ('LIMIT', 90.9, 1, 'ALL', 'DAY'))
            self.assertEqual(parent.status, 'SUBMITTED')
            # The other side cannot fire while the first execution is working.
            self.tick(parent, 115)
            self.assertEqual(self.webull_submit.call_count, 1)
            rows = ex.reconcile_executions(parent, 'LADDER')
            ladder._sync_parent(parent, rows)
            self.assertEqual(parent.status, 'COMPLETED')
            self.assertEqual(rows[0].order_type, 'LIMIT')
        finally:
            for p in reversed(patches):
                p.stop()

    def test_regular_hours_trigger_still_sends_a_market_order(self):
        parent = self.live_two_sided_buy()
        patches = self.live_patches(REGULAR, {'order_id': 'WB1', 'status': 'NEW'})
        for p in patches:
            p.start()
        try:
            self.tick(parent, 111)
            kwargs = self.webull_submit.call_args.kwargs
            self.assertEqual((kwargs['order_type'], kwargs['support_trading_session']), ('MARKET', 'CORE'))
        finally:
            for p in reversed(patches):
                p.stop()

    def test_unfilled_extended_hours_limit_is_cancelled_after_the_timeout(self):
        parent = self.live_two_sided_buy()
        patches = self.live_patches(PRE_MARKET, {'order_id': 'WB1', 'status': 'NEW'})
        for p in patches:
            p.start()
        try:
            self.tick(parent, 90)
            row = ex.executions(parent, 'LADDER')[0]
            row.created_at = PRE_MARKET.replace(tzinfo=None) - timedelta(seconds=ex.EXTENDED_LIMIT_TIMEOUT_SECONDS + 1)
            db.session.commit()
            with patch('services.webull_service.cancel_webull_order', return_value={'success': True}) as cancel:
                ex.reconcile_executions(parent, 'LADDER')
            cancel.assert_called_once()
            with patch('services.webull_service.get_webull_order_detail',
                       return_value={'order_id': 'WB1', 'status': 'CANCELED', 'filled_qty': '0'}):
                rows = ex.reconcile_executions(parent, 'LADDER')
            ladder._sync_parent(parent, rows)
            self.assertEqual(parent.status, 'FAILED')
            self.assertEqual(parent.monitoring_error, ex.EXTENDED_TIMEOUT_MESSAGE)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_extended_hours_parent_waits_outside_its_hours(self):
        parent = self.live_two_sided_buy()
        with patch.object(ex, 'utc_now', return_value=PRE_MARKET):
            self.assertTrue(ex.market_is_open(parent))
        overnight = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)
        with patch.object(ex, 'utc_now', return_value=overnight):
            self.assertFalse(ex.market_is_open(parent))
        self.assertIn('4:00 AM - 8:00 PM ET', ex.waiting_message(parent))

    def test_extended_hours_price_comes_from_yahoo(self):
        with patch.object(ex, 'utc_now', return_value=AFTER_HOURS), \
                patch('services.extended_hours_quote_service.get_extended_hours_price',
                      return_value=(161.01, AFTER_HOURS)) as yahoo:
            price = ex.reference_price('NVDA', broker='webull', instrument_type='EQUITY', user_id=1, trading_session='ALL')
        self.assertEqual(price, 161.01)
        yahoo.assert_called_once_with('NVDA')


if __name__ == '__main__':
    unittest.main()
