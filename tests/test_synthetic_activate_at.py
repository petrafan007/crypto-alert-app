"""Post-dated activation (activate_at) for synthetic orders.

A synthetic strategy created with a future activate_at stays dormant: the
worker records the scheduled message and never fetches prices, evaluates
triggers, or submits executions until the start time arrives. All venue I/O
is mocked through the shared lifecycle fixtures; nothing here touches a
broker or the app database.
"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from core.extensions import db
from trading_models import LadderOrder, SyntheticExecution, TrailingOrder
from services import synthetic_execution_service as ex
from services import synthetic_conditional_service as conditional
from services import ladder_order_service as ladder
from services import trailing_order_service as trailing
from tests import test_synthetic_order_lifecycle as base


class ParseActivateAtTests(unittest.TestCase):
    def test_none_and_empty_mean_unscheduled(self):
        self.assertIsNone(ex.parse_activate_at(None))
        self.assertIsNone(ex.parse_activate_at(''))
        self.assertIsNone(ex.parse_activate_at('   '))

    def test_offset_iso_converts_to_naive_utc(self):
        self.assertEqual(ex.parse_activate_at('2026-11-19T09:30:00-05:00'),
                         datetime(2026, 11, 19, 14, 30))

    def test_zulu_iso(self):
        self.assertEqual(ex.parse_activate_at('2026-11-19T14:30:00Z'),
                         datetime(2026, 11, 19, 14, 30))

    def test_naive_is_assumed_utc(self):
        self.assertEqual(ex.parse_activate_at('2026-11-19T14:30:00'),
                         datetime(2026, 11, 19, 14, 30))

    def test_aware_datetime_passthrough(self):
        aware = datetime(2026, 11, 19, 9, 30, tzinfo=timezone(timedelta(hours=-5)))
        self.assertEqual(ex.parse_activate_at(aware), datetime(2026, 11, 19, 14, 30))

    def test_garbage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'valid start date and time'):
            ex.parse_activate_at('next thursday-ish')
        with self.assertRaisesRegex(ValueError, 'valid start date and time'):
            ex.parse_activate_at(12345)

    def test_more_than_366_days_out_is_rejected(self):
        far = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
        with self.assertRaisesRegex(ValueError, '366 days'):
            ex.parse_activate_at(far)


class ActivationPendingTests(unittest.TestCase):
    def test_pending_only_while_start_is_in_the_future(self):
        now = datetime(2026, 11, 17, 12, 0)
        self.assertTrue(ex.activation_pending(
            SimpleNamespace(activate_at=datetime(2026, 11, 19, 14, 30)), now=now))
        self.assertFalse(ex.activation_pending(
            SimpleNamespace(activate_at=datetime(2026, 11, 17, 11, 0)), now=now))
        self.assertFalse(ex.activation_pending(SimpleNamespace(activate_at=None), now=now))
        self.assertFalse(ex.activation_pending(SimpleNamespace(), now=now))

    def test_message_shows_the_start_in_eastern_time(self):
        message = ex.activation_message(SimpleNamespace(activate_at=datetime(2026, 11, 19, 14, 30)))
        self.assertIn('Scheduled: monitoring starts', message)
        self.assertIn('Nov 19, 2026', message)
        self.assertIn('9:30 AM', message)
        self.assertIn('EST', message)
        self.assertEqual(ex.activation_message(SimpleNamespace(activate_at=None)), '')


class PostDatedSyntheticTests(base.SyntheticLifecycleTests):
    def conditional(self, **extra):
        data = dict(strategy_type='LIMIT', symbol='ANT', side='BUY', broker='webull',
                    instrument_type='EQUITY', account_id='A', trading_session='CORE',
                    total_quantity=6, test_mode=False,
                    legs=[dict(side='BUY', order_type='LIMIT', price=83.33)])
        data.update(extra)
        return conditional.create_conditional(1, data)

    def test_create_conditional_persists_activate_at(self):
        parent = self.conditional(activate_at='2026-11-19T09:30:00-05:00')
        self.assertEqual(parent.activate_at, datetime(2026, 11, 19, 14, 30))
        self.assertEqual(parent.to_dict()['activate_at'], '2026-11-19T14:30:00')

    def test_create_conditional_without_activate_at_stays_unscheduled(self):
        parent = self.conditional()
        self.assertIsNone(parent.activate_at)
        self.assertIsNone(parent.to_dict()['activate_at'])

    def test_create_ladder_and_trailing_accept_activate_at(self):
        parent = self.create(activate_at='2026-11-19T14:30:00Z')
        self.assertEqual(parent.activate_at, datetime(2026, 11, 19, 14, 30))
        self.assertEqual(parent.to_dict()['activate_at'], '2026-11-19T14:30:00')
        result = trailing.create_trailing_order(
            1, 'BTCUSD', 'SELL', 10, test_mode=True, activate_at='2026-11-19T14:30:00Z')
        order = db.session.get(TrailingOrder, result['id'])
        self.assertEqual(order.activate_at, datetime(2026, 11, 19, 14, 30))
        self.assertEqual(order.to_dict()['activate_at'], '2026-11-19T14:30:00')

    def test_worker_leaves_future_dated_conditional_dormant(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).replace(tzinfo=None).isoformat() + 'Z'
        parent = self.conditional(activate_at=future)
        db.session.commit()
        parent_id = parent.id
        with patch.object(ex, 'market_is_open', return_value=True), \
                patch.object(ex, 'parent_reference_price', return_value=80.0) as price, \
                patch.object(ex, 'submit_execution') as submit:
            ladder.evaluate_active_ladder_orders()
            submit.assert_not_called()
            price.assert_not_called()
        parent = db.session.get(LadderOrder, parent_id)
        self.assertEqual(SyntheticExecution.query.count(), 0)
        self.assertEqual(parent.status, 'ACTIVE')
        self.assertIn('Scheduled: monitoring starts', parent.monitoring_error)

    def test_worker_evaluates_once_the_start_time_has_passed(self):
        parent = self.conditional(activate_at='2020-01-01T00:00:00Z')
        db.session.commit()
        with patch.object(ex, 'market_is_open', return_value=True), \
                patch.object(ex, 'parent_reference_price', return_value=80.0), \
                patch.object(ex, 'submit_execution') as submit:
            ladder.evaluate_active_ladder_orders()
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(submit.call_args.kwargs.get('explicit_limit'), 83.33)
        self.assertEqual(SyntheticExecution.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
