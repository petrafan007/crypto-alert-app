"""Event risk math and real ledger writes in isolated SQLite/PostgreSQL fixtures."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask
from sqlalchemy.schema import CreateSchema
from core.extensions import db
from event_algo_models import EventStrategyConfig
from portfolio_algo_models import PortfolioEngineLog
from services import portfolio_engine as engine
from services.event_risk_policy import normalize_risk_config, entry_allowance


def lot(ident, closed_at=None, pnl=0, collateral=0, fee=0):
    return SimpleNamespace(id=ident, closed_at=closed_at, realized_pnl=pnl,
                           collateral=collateral, entry_fee=fee)


class EventRiskPolicyTests(unittest.TestCase):
    def test_invalid_saved_limits_fail_closed(self):
        for bad in ('bad', float('nan'), float('inf'), -1, True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_risk_config({'max_daily_loss': bad})
        for bad in ('not json', '[]', [], {'max_open_positions': 1.5},
                    {'min_time_remaining_seconds': 100, 'max_time_remaining_seconds': 50}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_risk_config(bad)
        self.assertEqual(normalize_risk_config({})['max_daily_loss'], 25)

    def test_rolling_hour_and_eastern_day_boundaries(self):
        # DST is active: Eastern midnight is 04:00 UTC, not UTC midnight.
        now = datetime(2026, 9, 12, 4, 30, tzinfo=timezone.utc)
        rows = [lot(1, now-timedelta(minutes=31), -3),
                lot(2, now-timedelta(minutes=5), -2),
                lot(3, now-timedelta(hours=2), 20)]
        result = entry_allowance(normalize_risk_config({}), rows, now)
        self.assertEqual(result['hourly_realized_pnl'], -5)
        self.assertEqual(result['daily_realized_pnl'], -2)
        self.assertEqual(result['realized_drawdown'], 5)
        self.assertEqual(result['remaining_loss_allowance'], 10)

    def test_existing_stakes_and_fees_reserve_loss_budget(self):
        result = entry_allowance(normalize_risk_config({}), [lot(1, collateral=10, fee=.3)], datetime.utcnow())
        self.assertAlmostEqual(result['open_dollars'], 10.3)
        self.assertAlmostEqual(result['reserved_loss'], 10.6)
        self.assertAlmostEqual(result['remaining_loss_allowance'], 4.4)

    def test_zero_caps_block_and_gains_do_not_expand_daily_risk(self):
        now = datetime.utcnow()
        for key in ('max_open_positions', 'max_dollars_per_trade', 'max_open_dollars',
                    'max_contracts_per_trade', 'max_hourly_loss', 'max_daily_loss', 'max_drawdown'):
            with self.subTest(key=key):
                self.assertIsNotNone(entry_allowance(normalize_risk_config({key: 0}), [], now)['reason'])
        result = entry_allowance(normalize_risk_config({}), [lot(1, now-timedelta(minutes=1), 100)], now)
        self.assertEqual(result['remaining_loss_allowance'], 15)

    def test_realized_drawdown_persists_across_daily_rollover(self):
        now = datetime.utcnow()
        rows = [lot(1, now-timedelta(days=3), 20), lot(2, now-timedelta(days=2), -36)]
        result = entry_allowance(normalize_risk_config({}), rows, now)
        self.assertEqual(result['realized_drawdown'], 36)
        self.assertIsNotNone(result['reason'])


class EventRiskLedgerTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_RISK_TEST_DATABASE_URI', 'sqlite://')
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        schema = 'risk_test_' + uuid4().hex
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'options': '-csearch_path=' + schema}}
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in (
            engine.Config, engine.Account, engine.State, engine.Position, engine.Lot,
            engine.Order, PortfolioEngineLog, EventStrategyConfig,
        )])
        self.cfg, self.acc, self.state = engine.ensure_portfolio(1)
        self.cfg.enabled = True
        self.event = EventStrategyConfig(user_id=1, name='Risk test', enabled=True, risk_config='{}')
        db.session.add(self.event)
        db.session.commit()
        self.config_id = self.event.id
        self.now = datetime.utcnow()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def save_limits(self, **limits):
        self.event.risk_config = json.dumps(limits)
        db.session.commit()

    def enter(self, symbol='TEST', depth=None):
        cfg, acc, state = engine.locked(1)
        details = {'event_config_id': self.config_id, 'selected_ask_size': depth}
        rejections = []
        result = engine.enter_lot(cfg, acc, state, 'events', symbol, {'side': 'LONG'}, .4,
                                 self.now, details=details, rejections=rejections)
        db.session.commit()
        return result, details, rejections

    def test_trade_limit_includes_fees_and_archives_applied_policy(self):
        self.save_limits(max_dollars_per_trade=2)
        row, details, _ = self.enter()
        self.assertIsNotNone(row)
        self.assertEqual(db.session.get(engine.Position, row.position_id).quantity, 4)
        self.assertLessEqual(row.collateral + row.entry_fee, 2)
        self.assertEqual(details['event_risk_at_fill']['limits']['max_dollars_per_trade'], 2)
        self.assertEqual(json.loads(row.details_json)['depth_status'], 'UNKNOWN')

    def test_depth_and_saved_contract_count_limit_quantity(self):
        self.save_limits(max_contracts_per_trade=3)
        row, _, _ = self.enter(depth=2.9)
        self.assertEqual(db.session.get(engine.Position, row.position_id).quantity, 2)
        row, _, _ = self.enter('OTHER', depth=100)
        self.assertEqual(db.session.get(engine.Position, row.position_id).quantity, 3)

    def test_zero_depth_or_invalid_policy_cannot_write_orders(self):
        self.assertIsNone(self.enter(depth=0)[0])
        self.event.risk_config = '{"max_daily_loss": "invalid"}'
        db.session.commit()
        self.assertIsNone(self.enter()[0])
        self.assertEqual(engine.Order.query.count(), 0)

    def test_pending_positions_reserve_exposure_and_loss(self):
        self.save_limits(max_dollars_per_trade=10, max_open_dollars=2)
        first, _, _ = self.enter()
        self.assertIsNotNone(first)
        self.assertIsNone(self.enter('SECOND')[0])
        self.assertEqual(engine.Lot.query.count(), 1)

    def test_hourly_losses_block_and_other_generations_do_not(self):
        row, _, _ = self.enter()
        engine.close_lot(self.acc, row, 0, 'SETTLEMENT', self.now)
        db.session.commit()
        self.save_limits(max_hourly_loss=5)
        self.assertIsNone(self.enter('SECOND')[0])
        self.state.generation += 1
        db.session.commit()
        self.assertIsNotNone(self.enter('THIRD')[0])

    def test_saved_position_limit_and_config_changes_are_reloaded(self):
        self.save_limits(max_open_positions=1)
        self.assertIsNotNone(self.enter(depth=1)[0])
        self.assertIsNone(self.enter('SECOND', depth=1)[0])
        self.save_limits(max_open_positions=2)
        self.assertIsNotNone(self.enter('SECOND', depth=1)[0])

    def test_reported_risk_matches_saved_limits_and_ledger(self):
        self.save_limits(max_open_positions=7, max_dollars_per_trade=2)
        self.enter(depth=1)
        status = engine.event_risk_status(1, self.state, self.now)
        self.assertEqual(status['limits']['max_open_positions'], 7)
        self.assertAlmostEqual(status['open_dollars'], .415)
        self.event.risk_config = 'invalid'
        db.session.commit()
        self.assertEqual(engine.event_risk_status(1, self.state, self.now)['status'], 'INVALID')

    @unittest.skipUnless(os.environ.get('QUANT_RISK_TEST_DATABASE_URI', '').startswith('postgresql'),
                         'Requires an isolated PostgreSQL test instance for row-lock verification')
    def test_concurrent_entries_cannot_exceed_saved_exposure(self):
        self.save_limits(max_open_positions=10, max_dollars_per_trade=10, max_open_dollars=2)
        barrier = Barrier(2)
        def attempt(symbol):
            with self.app.app_context():
                try:
                    barrier.wait(timeout=5)
                    return self.enter(symbol)[0] is not None
                finally:
                    db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ['FIRST', 'SECOND']))
        self.assertEqual(sum(results), 1)
        db.session.expire_all()
        self.assertLessEqual(sum(row.collateral + row.entry_fee for row in engine.Lot.query.all()), 2)
