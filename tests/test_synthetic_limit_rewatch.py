"""Synthetic Limit re-watch/re-place and guardian (backstop) behaviour.

A plain synthetic Limit whose Webull child is cancelled before filling
returns to watching and places the order again (the IPO-halt case), while a
guardian-linked Limit stands behind an existing native Webull order and
only takes over if that order ends unfilled. All venue I/O is mocked; these
tests never connect to a broker or the app database.
"""
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from core.extensions import db
from core.time_utils import utc_now
from models import WebullOrder
from trading_models import LadderOrder, SyntheticExecution
from services import synthetic_execution_service as ex
from services import synthetic_conditional_service as conditional
from services import ladder_order_service as ladder
from tests import test_synthetic_order_lifecycle as base


class LimitRewatchTests(base.SyntheticLifecycleTests):
    def setUp(self):
        super().setUp()
        WebullOrder.__table__.create(db.engine, checkfirst=True)
        from types import SimpleNamespace
        cred = SimpleNamespace(webull_app_key='key', webull_app_secret='secret',
                               webull_access_token='token')
        self.detail = Mock(return_value={'order_id': 'WB1', 'status': 'NEW', 'filled_qty': '0'})
        self.extra_patchers = [
            patch.object(ex, 'webull_credentials', return_value=(cred, 'production')),
            patch('services.webull_service.get_webull_account_balance',
                  return_value={'available_cash': 100000}),
            patch('services.webull_service.get_webull_order_detail', self.detail),
        ]
        for p in self.extra_patchers:
            p.start()
        self.webull_submit.side_effect = None
        self.webull_submit.return_value = {'success': True, 'order_id': 'WB1', 'status': 'NEW'}

    def tearDown(self):
        for p in reversed(self.extra_patchers):
            p.stop()
        super().tearDown()

    # -- helpers -----------------------------------------------------------
    def conditional(self, **extra):
        data = dict(strategy_type='LIMIT', symbol='ANT', side='BUY', broker='webull',
                    instrument_type='EQUITY', account_id='ACC1', trading_session='CORE',
                    total_quantity=5, test_mode=False,
                    legs=[dict(side='BUY', order_type='LIMIT', price=88)])
        data.update(extra)
        return conditional.create_conditional(1, data)

    def cycle(self, parent, price=83):
        """One worker-style pass: reconcile, sync, then evaluate triggers."""
        rows = ex.reconcile_executions(parent, 'LADDER')
        ladder._sync_parent(parent, rows)
        ladder.evaluate_single_ladder_order(parent, price)
        db.session.commit()

    def age(self, row, seconds):
        row.updated_at = utc_now(aware=False) - timedelta(seconds=seconds)
        db.session.commit()

    def make_native(self, **kw):
        args = dict(user_id=1, account_id='ACC1', provider_order_id='PROV1',
                    client_order_id='native-client-1', symbol='ANT', instrument_type='EQUITY',
                    side='BUY', order_type='LIMIT', quantity=5, filled_quantity=0,
                    price=88, status='SUBMITTED')
        args.update(kw)
        row = WebullOrder(**args)
        db.session.add(row)
        db.session.commit()
        return row

    # -- re-watch / re-place of the synthetic's own child ------------------
    def test_cancelled_child_rewatches_and_replaces(self):
        parent = self.conditional()
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(parent.status, 'SUBMITTED')
        self.assertEqual(len(ex.executions(parent, 'LADDER')), 1)
        # Webull cancels the resting child unfilled (IPO still halted).
        self.detail.return_value = {'order_id': 'WB1', 'status': 'CANCELED', 'filled_qty': '0'}
        self.cycle(parent)
        self.assertEqual(parent.status, 'ACTIVE')
        self.assertEqual(parent.monitoring_error, conditional.REWATCH_MESSAGE)
        # Re-placement is paced, not instant, so a fast-cancelling venue
        # cannot be spammed.
        self.assertEqual(self.webull_submit.call_count, 1)
        self.age(ex.executions(parent, 'LADDER')[0],
                 conditional.REPLACEMENT_MIN_INTERVAL_SECONDS + 1)
        self.detail.return_value = {'order_id': 'WB1', 'status': 'NEW', 'filled_qty': '0'}
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 2)
        self.assertEqual(parent.status, 'SUBMITTED')
        self.assertEqual(len(ex.executions(parent, 'LADDER')), 2)
        # The replacement fills: the parent completes normally.
        self.detail.return_value = {'order_id': 'WB1', 'status': 'FILLED',
                                    'filled_qty': '5', 'filled_price': '87.5'}
        self.cycle(parent)
        self.assertEqual(parent.status, 'COMPLETED')

    def test_no_duplicate_while_child_working(self):
        parent = self.conditional()
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 1)
        for _ in range(3):
            self.cycle(parent)
            ladder.evaluate_single_ladder_order(parent, 83)
            db.session.commit()
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(len(ex.executions(parent, 'LADDER')), 1)
        self.assertEqual(parent.status, 'SUBMITTED')

    def test_partial_fill_stops_and_surfaces(self):
        parent = self.conditional()
        self.cycle(parent)
        self.detail.return_value = {'order_id': 'WB1', 'status': 'CANCELED', 'filled_qty': '2'}
        self.cycle(parent)
        self.assertEqual(parent.status, 'FAILED')
        self.assertEqual(parent.monitoring_error, ex.EXTENDED_TIMEOUT_MESSAGE)
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 1)

    def test_repeated_rejections_stop_after_three(self):
        self.webull_submit.return_value = {'success': False, 'status': 'REJECTED',
                                           'reject_reason': 'Broker said no'}
        parent = self.conditional()
        for _ in range(3):
            self.cycle(parent)
            for row in ex.executions(parent, 'LADDER'):
                self.age(row, conditional.REPLACEMENT_MIN_INTERVAL_SECONDS + 1)
        self.assertEqual(parent.status, 'FAILED')
        self.assertEqual(self.webull_submit.call_count, 3)
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 3)

    def test_timeout_skips_untraded_symbol(self):
        parent = self.conditional()
        self.cycle(parent)
        row = ex.executions(parent, 'LADDER')[0]
        row.created_at = utc_now(aware=False) - timedelta(
            seconds=ex.EXTENDED_LIMIT_TIMEOUT_SECONDS + 60)
        db.session.commit()
        with patch('services.webull_service.get_webull_market_snapshot',
                   return_value={'price': 83, 'has_traded': False, 'as_of': None}), \
                patch('services.webull_service.cancel_webull_order',
                      return_value={'success': True}) as cancel:
            ex.reconcile_executions(parent, 'LADDER')
            cancel.assert_not_called()
            self.assertEqual(row.status, 'SUBMITTED')
        with patch('services.webull_service.get_webull_market_snapshot',
                   return_value={'price': 83, 'has_traded': True, 'as_of': '1763577600000'}), \
                patch('services.webull_service.cancel_webull_order',
                      return_value={'success': True}) as cancel:
            ex.reconcile_executions(parent, 'LADDER')
            cancel.assert_called_once()

    def test_trigger_semantics_unchanged(self):
        parent = self.conditional()
        self.cycle(parent, price=90)
        self.assertEqual(self.webull_submit.call_count, 0)
        self.assertEqual(parent.status, 'ACTIVE')
        self.cycle(parent, price=88)
        self.assertEqual(self.webull_submit.call_count, 1)

    # -- guardian (backstop) mode ------------------------------------------
    def test_guardian_watches_live_native_order(self):
        native = self.make_native()
        parent = self.conditional(guardian_order_ref='PROV1')
        spec = json.loads(parent.conditional_spec)
        self.assertEqual(spec['guardian']['state'], 'WATCHING')
        self.assertEqual(spec['guardian']['webull_order_id'], native.id)
        self.webull_submit.side_effect = AssertionError('backstop placed an order too early')
        self.cycle(parent)
        self.assertEqual(parent.status, 'ACTIVE')
        self.assertIn('Backstop armed', parent.monitoring_error)
        self.assertEqual(SyntheticExecution.query.count(), 0)

    def test_guardian_takeover_after_cancel(self):
        self.make_native()
        parent = self.conditional(guardian_order_ref='PROV1')
        self.webull_submit.side_effect = AssertionError('backstop placed an order too early')
        self.cycle(parent)
        self.assertEqual(SyntheticExecution.query.count(), 0)
        self.webull_submit.side_effect = None
        native = WebullOrder.query.filter_by(provider_order_id='PROV1').first()
        native.status = 'CANCELLED'
        db.session.commit()

        def route(*args, **kwargs):
            if kwargs.get('client_order_id') == 'native-client-1':
                return {'status': 'CANCELED', 'filled_qty': '0'}
            return {'order_id': 'WB1', 'status': 'NEW', 'filled_qty': '0'}
        self.detail.side_effect = route
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 1)
        kwargs = self.webull_submit.call_args.kwargs
        self.assertEqual((kwargs['order_type'], kwargs['limit_price'], kwargs['quantity']),
                         ('LIMIT', 88, 5))
        self.assertEqual(parent.status, 'SUBMITTED')
        spec = json.loads(parent.conditional_spec)
        self.assertEqual(spec['guardian']['state'], 'TAKEN_OVER')
        # Its own child is now the live order: nothing more is placed.
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 1)

    def test_guardian_already_cancelled_at_link(self):
        native = self.make_native(status='CANCELLED',
                                  created_at=datetime(2026, 11, 18, 15, 0))
        parent = self.conditional(guardian_order_ref=str(native.id))
        self.detail.return_value = {'status': 'CANCELED', 'filled_qty': '0'}
        self.cycle(parent)
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(parent.status, 'SUBMITTED')
        spec = json.loads(parent.conditional_spec)
        self.assertEqual(spec['guardian']['state'], 'TAKEN_OVER')

    def test_guardian_native_fill_completes(self):
        self.make_native(status='FILLED', filled_quantity=5, filled_price=87.9)
        parent = self.conditional(guardian_order_ref='PROV1')
        self.webull_submit.side_effect = AssertionError('backstop placed an order')
        self.cycle(parent)
        self.assertEqual(parent.status, 'COMPLETED')
        self.assertEqual(SyntheticExecution.query.count(), 0)

    def test_guardian_native_partial_fill_stops(self):
        self.make_native(status='CANCELLED', filled_quantity=2)
        parent = self.conditional(guardian_order_ref='PROV1')
        self.webull_submit.side_effect = AssertionError('backstop placed an order')
        self.cycle(parent)
        self.assertEqual(parent.status, 'FAILED')
        self.assertIn('partially filled', parent.monitoring_error)
        self.assertEqual(SyntheticExecution.query.count(), 0)
        self.cycle(parent)
        self.assertEqual(parent.status, 'FAILED')

    def test_guardian_live_check_blocks_takeover_when_broker_says_working(self):
        self.make_native(status='CANCELLED')
        parent = self.conditional(guardian_order_ref='PROV1')
        self.detail.return_value = {'status': 'NEW', 'filled_qty': '0'}
        self.webull_submit.side_effect = AssertionError('backstop placed an order')
        self.cycle(parent)
        self.assertEqual(parent.status, 'ACTIVE')
        self.assertEqual(SyntheticExecution.query.count(), 0)
        spec = json.loads(parent.conditional_spec)
        self.assertEqual(spec['guardian']['state'], 'WATCHING')

    def test_guardian_link_validation(self):
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.conditional(guardian_order_ref='NOPE')
        self.make_native(symbol='MSFT')
        with self.assertRaisesRegex(ValueError, 'symbol and side'):
            self.conditional(guardian_order_ref='PROV1')
        self.make_native(provider_order_id='PROV2', client_order_id='native-2', quantity=7)
        with self.assertRaisesRegex(ValueError, 'quantity must match'):
            self.conditional(guardian_order_ref='PROV2')
        self.make_native(provider_order_id='PROV3', client_order_id='native-3', account_id='OTHER')
        with self.assertRaisesRegex(ValueError, 'different account'):
            self.conditional(guardian_order_ref='PROV3')
        with self.assertRaisesRegex(ValueError, 'only available for a synthetic Limit'):
            self.conditional(guardian_order_ref='PROV2', strategy_type='OCO', side='SELL',
                             legs=[dict(side='SELL', order_type='LIMIT', price=110),
                                   dict(side='SELL', order_type='STOP_LOSS', stop_price=90)])
        with self.assertRaisesRegex(ValueError, 'live synthetic'):
            self.conditional(guardian_order_ref='PROV2', test_mode=True)

    def test_guardian_worker_cycle_takeover(self):
        self.make_native(status='CANCELLED')
        parent = self.conditional(guardian_order_ref='PROV1')
        parent_id = parent.id
        self.detail.return_value = {'status': 'CANCELED', 'filled_qty': '0'}
        with patch.object(ex, 'market_is_open', return_value=True), \
                patch.object(ex, 'parent_reference_price', return_value=83):
            ladder.evaluate_active_ladder_orders()
        parent = db.session.get(LadderOrder, parent_id)
        self.assertEqual(self.webull_submit.call_count, 1)
        self.assertEqual(parent.status, 'SUBMITTED')


if __name__ == '__main__':
    unittest.main()
