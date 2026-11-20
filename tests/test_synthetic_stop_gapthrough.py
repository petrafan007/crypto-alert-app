"""Gap-through stop-limit execution and the per-session stop attempt cap.

A stop-limit whose market has already gapped through its limit can never
fill at that limit (the NVDA ladder_29 incident, Nov 20 2026): it must
execute like a plain stop (market in regular hours) instead. A stop that
keeps failing to fill is parked after a few attempts in a visible
TRIGGERED_NOT_FILLED state instead of churning broker orders all session.
All venue I/O is mocked.
"""
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.extensions import db
from core.time_utils import utc_now
from trading_models import SyntheticExecution
from services import synthetic_execution_service as ex
from services import synthetic_conditional_service as conditional
from tests import test_synthetic_order_lifecycle as base


class StopGapThroughTests(base.SyntheticLifecycleTests):
    def setUp(self):
        super().setUp()
        cred = SimpleNamespace(webull_app_key='key', webull_app_secret='secret',
                               webull_access_token='token')
        self.extra_patchers = [
            patch.object(ex, 'webull_credentials', return_value=(cred, 'production')),
            patch('services.webull_service.get_webull_account_balance',
                  return_value={'available_cash': 100000}),
            patch('services.webull_service.get_webull_account_positions',
                  return_value=[{'symbol': 'NVDA', 'quantity': 10, 'available_quantity': 10},
                                {'symbol': 'SPY', 'quantity': 10, 'available_quantity': 10}]),
            patch('services.webull_service.get_webull_order_detail',
                  return_value={'order_id': 'WB1', 'status': 'NEW', 'filled_qty': '0'}),
        ]
        for p in self.extra_patchers:
            p.start()
        self.webull_submit.side_effect = None
        self.webull_submit.return_value = {'success': True, 'order_id': 'WB1', 'status': 'NEW'}

    def tearDown(self):
        for p in reversed(self.extra_patchers):
            p.stop()
        super().tearDown()

    def stop_parent(self, side='SELL', symbol='NVDA', stop=144.0, limit=143.9, qty=1):
        return conditional.create_conditional(1, dict(
            strategy_type='LIMIT', symbol=symbol, side=side, broker='webull',
            instrument_type='EQUITY', account_id='ACC1', trading_session='CORE',
            total_quantity=qty, test_mode=False,
            legs=[dict(side=side, order_type='STOP_LOSS_LIMIT', price=limit, stop_price=stop)]))

    def submit_kwargs(self):
        return self.webull_submit.call_args.kwargs

    # -- gap-through conversion ---------------------------------------------
    def test_gap_through_sell_stop_limit_submits_market(self):
        parent = self.stop_parent()
        conditional.evaluate(parent, 143.54)  # opened below the 143.90 limit
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(self.submit_kwargs()['order_type'], 'MARKET')
        self.assertNotIn('limit_price', self.submit_kwargs())

    def test_in_band_sell_stop_limit_keeps_its_limit(self):
        parent = self.stop_parent()
        conditional.evaluate(parent, 143.95)  # inside the 144.00/143.90 band
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(self.submit_kwargs()['order_type'], 'LIMIT')
        self.assertEqual(self.submit_kwargs()['limit_price'], 143.9)

    def test_gap_through_buy_stop_limit_submits_market(self):
        parent = self.stop_parent(side='BUY', symbol='SPY', stop=100.0, limit=100.10)
        conditional.evaluate(parent, 100.25)  # already above the 100.10 limit
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(self.submit_kwargs()['order_type'], 'MARKET')

    def test_in_band_buy_stop_limit_keeps_its_limit(self):
        parent = self.stop_parent(side='BUY', symbol='SPY', stop=100.0, limit=100.10)
        conditional.evaluate(parent, 100.05)  # inside the 100.00/100.10 band
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(self.submit_kwargs()['order_type'], 'LIMIT')
        self.assertEqual(self.submit_kwargs()['limit_price'], 100.10)

    def test_untriggered_stop_places_nothing(self):
        parent = self.stop_parent()
        conditional.evaluate(parent, 150.0)  # stop not reached
        self.assertEqual(self.webull_submit.call_count, 0)
        self.assertEqual(parent.status, 'ACTIVE')

    def test_extended_hours_preserves_the_entered_stop_limit(self):
        # Extended hours have no market orders: even gapped through, the
        # exact entered limit stands (the plain-stop cap does not apply to
        # stop-limit legs). Pinned by test_synthetic_recovery as well.
        parent = conditional.create_conditional(1, dict(
            strategy_type='LIMIT', symbol='NVDA', side='SELL', broker='webull',
            instrument_type='EQUITY', account_id='ACC1', trading_session='ALL',
            total_quantity=1, test_mode=False,
            legs=[dict(side='SELL', order_type='STOP_LOSS_LIMIT', price=143.9, stop_price=144.0)]))
        with patch.object(ex, 'session_phase', return_value='EXTENDED'):
            conditional.evaluate(parent, 143.54)
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(self.submit_kwargs()['order_type'], 'LIMIT')
        self.assertEqual(self.submit_kwargs()['limit_price'], 143.9)

    # -- per-session attempt cap ---------------------------------------------
    def add_terminal_attempts(self, parent, count, age_days=0):
        for i in range(count):
            row = SyntheticExecution(
                user_id=1, parent_kind='LADDER', parent_id=parent.id, leg='EXIT_0',
                quantity=1, client_order_id=f'old-attempt-{age_days}-{i}',
                filled_quantity=0, status='CANCELLED', order_type='LIMIT', limit_price=143.9)
            row.created_at = utc_now(aware=False) - timedelta(days=age_days)
            row.updated_at = utc_now(aware=False) - timedelta(seconds=60, days=age_days)
            db.session.add(row)
        db.session.commit()

    def test_stop_replacements_capped_and_parked_visibly(self):
        parent = self.stop_parent()
        self.add_terminal_attempts(parent, conditional.MAX_STOP_ATTEMPTS_PER_SESSION)
        conditional.evaluate(parent, 135.0)  # trigger still true, far through the limit
        self.assertEqual(self.webull_submit.call_count, 0)
        self.assertEqual(parent.status, 'TRIGGERED_NOT_FILLED')
        self.assertEqual(parent.monitoring_error, conditional.TRIGGERED_NOT_FILLED_MESSAGE)
        # Parked is not hidden: it stays in the pending-order feed.
        from services.pending_order_serializer import working_synthetic_orders
        ids = [o['order_id'] for o in working_synthetic_orders(1)]
        self.assertIn(f'ladder_{parent.id}', ids)

    def test_attempts_from_a_previous_session_do_not_count(self):
        parent = self.stop_parent()
        self.add_terminal_attempts(parent, conditional.MAX_STOP_ATTEMPTS_PER_SESSION, age_days=1)
        conditional.evaluate(parent, 135.0)
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(self.submit_kwargs()['order_type'], 'MARKET')
        self.assertEqual(parent.status, 'SUBMITTED')


if __name__ == '__main__':
    unittest.main()
