"""Legacy fill gates and real concurrent transactions, with no provider I/O."""
import inspect
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4

from flask import Flask
from sqlalchemy import update
from sqlalchemy.schema import CreateSchema

from core.extensions import db
from event_algo import simulate_paper_fills
from event_algo_models import (
    EventMarketSnapshot, EventStrategyConfig, EventStrategyDecision,
    EventStrategyLog, EventStrategyOrder,
)
from portfolio_algo_models import PortfolioStrategyConfig


class LegacyEventFillTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_LEGACY_TEST_DATABASE_URI', 'sqlite://')
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        schema = 'legacy_test_' + uuid4().hex
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                'connect_args': {'options': '-csearch_path=' + schema + ' -cstatement_timeout=10000'}}
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in (
            EventMarketSnapshot, EventStrategyConfig, EventStrategyDecision,
            EventStrategyLog, EventStrategyOrder, PortfolioStrategyConfig,
        )])
        self.config = EventStrategyConfig(user_id=1, name='Legacy', enabled=True)
        db.session.add(self.config)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def decision(self, symbol='TEST', *, config=None, **quote_changes):
        config = config or self.config
        now = datetime.utcnow()
        market = dict(symbol=symbol, cutoff_at=(now+timedelta(minutes=5)).isoformat(),
            quote_retrieved_at=now.isoformat(), quote_time_basis='RETRIEVAL_ONLY',
            yes_bid=.39, yes_ask=.4, no_bid=.59, no_ask=.6)
        market.update(quote_changes)
        snapshot = EventMarketSnapshot(user_id=config.user_id, config_id=config.id,
            contract_symbol=symbol, raw_json=json.dumps(market))
        db.session.add(snapshot)
        db.session.flush()
        decision = EventStrategyDecision(user_id=config.user_id, config_id=config.id,
            snapshot_id=snapshot.id, contract_symbol=symbol, eligible=True, action='BUY_YES',
            outcome='YES', executable_price=.4, probability_yes=.8, confidence=.9, created_at=now)
        db.session.add(decision)
        db.session.commit()
        return decision

    def limits(self, **limits):
        self.config.risk_config = json.dumps(limits)
        db.session.commit()

    def test_valid_fill_and_zero_fee_record_saved_evidence(self):
        self.config.signal_config = '{"fee_per_contract":0}'
        row = self.decision(yes_ask_size=1)
        result = simulate_paper_fills(1, decision_ids=[row.id])
        self.assertTrue(result['success'])
        self.assertEqual(result['simulated_count'], 1)
        order = EventStrategyOrder.query.one()
        self.assertEqual((order.quantity, order.filled_price, order.fee), (1, .4, 0))
        evidence = json.loads(EventStrategyLog.query.one().metadata_json)
        self.assertEqual(evidence['depth_status'], 'REPORTED')
        self.assertEqual(evidence['quote_freshness']['basis'], 'RETRIEVAL_ONLY')
        self.assertEqual(evidence['event_risk_at_fill']['limits']['max_open_positions'], 3)

    def test_empty_and_invalid_selection_never_broaden_to_all_decisions(self):
        self.decision()
        for selection in ([], ['bad'], [True], [1.5], '1', {}, [0], [-1]):
            with self.subTest(selection=selection):
                result = simulate_paper_fills(1, decision_ids=selection)
                self.assertEqual(result['simulated_count'], 0)
                self.assertEqual(result['success'], selection == [])
        self.assertEqual(EventStrategyOrder.query.count(), 0)
        for limit in (True, 1.2, 'bad', None, 0, 101):
            self.assertFalse(simulate_paper_fills(1, limit=limit)['success'])

    def test_non_object_api_body_returns_400(self):
        from routes.event_algo import event_algo_simulate
        for body in ('[]', 'null', 'true', 'bad'):
            with self.app.test_request_context(json=None, data=body, content_type='application/json'):
                response, status = inspect.unwrap(event_algo_simulate)()
                self.assertEqual(status, 400)
                self.assertFalse(response.json['success'])

    def test_stopped_killed_and_live_configs_cannot_fill(self):
        self.decision()
        for enabled, killed, mode in ((False, False, 'PAPER'), (True, True, 'PAPER'), (True, False, 'LIVE')):
            self.config.enabled, self.config.kill_switch, self.config.mode = enabled, killed, mode
            db.session.commit()
            self.assertFalse(simulate_paper_fills(1, config=self.config)['success'])
        self.assertEqual(EventStrategyOrder.query.count(), 0)

    def test_held_fill_preserves_the_scanners_uncommitted_decision(self):
        row = self.decision()
        self.config.enabled = False
        db.session.commit()
        pending = EventStrategyDecision(user_id=1, config_id=self.config.id, snapshot_id=row.snapshot_id,
            contract_symbol='TEST', eligible=True, action='BUY_YES', outcome='YES',
            executable_price=.4, probability_yes=.8, confidence=.9)
        db.session.add(pending)
        db.session.flush()
        self.assertFalse(simulate_paper_fills(1, decision_ids=[pending.id])['success'])
        self.assertEqual(EventStrategyDecision.query.count(), 2)
        self.assertEqual(EventStrategyOrder.query.count(), 0)

    def test_reload_rejects_stop_changed_by_another_connection(self):
        self.decision()
        config_id = self.config.id
        self.assertTrue(self.config.enabled)
        with db.engine.begin() as connection:
            connection.execute(update(EventStrategyConfig).where(EventStrategyConfig.id == config_id).values(enabled=False))
        self.assertFalse(simulate_paper_fills(1, config=self.config)['success'])
        self.assertEqual(EventStrategyOrder.query.count(), 0)

    def test_config_user_and_snapshot_isolation(self):
        others = [EventStrategyConfig(user_id=user, name='Other', enabled=True) for user in (1, 2)]
        db.session.add_all(others)
        db.session.commit()
        rows = [self.decision('OTHER' + str(i), config=config) for i, config in enumerate(others)]
        result = simulate_paper_fills(1, config=self.config, decision_ids=[row.id for row in rows])
        self.assertEqual(result['simulated_count'], 0)
        self.assertFalse(simulate_paper_fills(1, config=others[1])['success'])
        own = self.decision()
        own.snapshot_id = rows[1].snapshot_id
        db.session.commit()
        self.assertEqual(simulate_paper_fills(1, decision_ids=[own.id])['simulated_count'], 0)

    def test_stale_unknown_future_and_expired_quotes_cannot_fill(self):
        now = datetime.utcnow()
        for i, changes in enumerate((
            {'quote_retrieved_at': (now-timedelta(seconds=31)).isoformat()},
            {'quote_retrieved_at': None},
            {'quote_retrieved_at': (now+timedelta(seconds=15)).isoformat()},
            {'quote_time_basis': 'INVALID_PROVIDER'},
            {'cutoff_at': None}, {'cutoff_at': (now-timedelta(seconds=1)).isoformat()},
        )):
            row = self.decision('TEST' + str(i), **changes)
            result = simulate_paper_fills(1, decision_ids=[row.id])
            self.assertEqual(result['simulated_count'], 0)
            self.assertEqual(len(result['skipped']), 1)

    def test_stale_decision_cannot_replay_even_with_recent_quote(self):
        row = self.decision()
        row.created_at -= timedelta(seconds=121)
        db.session.commit()
        self.assertIn('120-second', simulate_paper_fills(1)['skipped'][0]['reason'])

    def test_price_model_depth_and_current_signal_gates(self):
        cases = [({'yes_bid': .1}, None), ({'yes_bid': .5}, None), ({'yes_ask_size': 0}, None),
                 ({}, {'executable_price': .5}), ({}, {'confidence': None}),
                 ({}, {'probability_yes': float('nan')}), ({}, {'executable_price': 1})]
        for i, (quote, changes) in enumerate(cases):
            row = self.decision('TEST' + str(i), **quote)
            for key, value in (changes or {}).items():
                setattr(row, key, value)
            db.session.commit()
            self.assertEqual(simulate_paper_fills(1, decision_ids=[row.id])['simulated_count'], 0)
        self.config.signal_config = '{"min_confidence":0.95}'
        row = self.decision('TIGHTER')
        self.assertEqual(simulate_paper_fills(1, decision_ids=[row.id])['simulated_count'], 0)

    def test_each_saved_risk_cap_blocks_unaffordable_entry(self):
        row = self.decision()
        for key, value in (('max_open_positions', 0), ('max_contracts_per_trade', 0),
                           ('max_dollars_per_trade', .4), ('max_open_dollars', .4),
                           ('max_hourly_loss', .4), ('max_daily_loss', .4), ('max_drawdown', .4),
                           ('max_spread', .001), ('min_volume', 100),
                           ('min_time_remaining_seconds', 400), ('max_time_remaining_seconds', 100)):
            with self.subTest(key=key):
                self.limits(**{key: value})
                result = simulate_paper_fills(1, decision_ids=[row.id])
                self.assertEqual(result['simulated_count'], 0)

    def test_batch_reserves_exposure_and_loss_before_next_fill(self):
        self.limits(max_open_dollars=.82)
        self.decision('ONE')
        self.decision('TWO')
        result = simulate_paper_fills(1)
        self.assertEqual(result['simulated_count'], 1)
        self.assertEqual(len(result['skipped']), 1)
        evidence = json.loads(EventStrategyLog.query.filter_by(event_type='LEGACY_PAPER_FILLED').one().metadata_json)
        self.assertEqual(evidence['depth_status'], 'UNKNOWN')

    def test_duplicate_contract_is_blocked_across_decisions_and_configs(self):
        self.decision()
        self.assertEqual(simulate_paper_fills(1)['simulated_count'], 1)
        other = EventStrategyConfig(user_id=1, name='Second', enabled=True)
        db.session.add(other)
        db.session.commit()
        row = self.decision(config=other)
        self.assertEqual(simulate_paper_fills(1, config=other, decision_ids=[row.id])['simulated_count'], 0)
        self.assertEqual(EventStrategyOrder.query.count(), 1)

    def test_closed_losses_and_pending_orders_reserve_risk_across_configs(self):
        row = self.decision()
        for status, settled, pnl in (('SIMULATED_PENDING', None, 0),
                                    ('SIMULATED_SETTLED', datetime.utcnow(), -1)):
            existing = EventStrategyOrder(user_id=1, config_id=999, mode='PAPER',
                contract_symbol=status, outcome='YES', side='BUY', quantity=1,
                filled_quantity=0 if settled is None else 1, filled_price=.4, fee=.02,
                status=status, settled_at=settled, realized_pnl=pnl)
            db.session.add(existing)
            self.limits(max_daily_loss=.8)
            self.assertEqual(simulate_paper_fills(1, decision_ids=[row.id])['simulated_count'], 0)

    def test_invalid_settings_and_ambiguous_history_fail_closed(self):
        self.decision()
        for value in ('[]', 'bad', '{"fee_per_contract":null}', '{"fee_per_contract":-1}'):
            self.config.signal_config = value
            db.session.commit()
            self.assertFalse(simulate_paper_fills(1)['success'])
        self.config.signal_config = '{}'
        self.config.risk_config = '{"max_daily_loss":null}'
        db.session.commit()
        self.assertFalse(simulate_paper_fills(1)['success'])
        self.limits()
        db.session.add(EventStrategyOrder(user_id=1, config_id=self.config.id, contract_symbol='OLD',
            side='BUY', outcome='YES', quantity=1, filled_price=.4, status='UNKNOWN'))
        db.session.commit()
        self.assertFalse(simulate_paper_fills(1)['success'])
        self.assertEqual(EventStrategyOrder.query.count(), 1)

    def test_existing_quantitative_config_never_creates_legacy_orders(self):
        self.decision()
        db.session.add(PortfolioStrategyConfig(user_id=1))
        db.session.commit()
        self.assertEqual(simulate_paper_fills(1)['simulated_count'], 0)
        self.assertEqual(EventStrategyOrder.query.count(), 0)

    def test_unserializable_evidence_cannot_commit_a_fill_without_its_log(self):
        self.config.signal_config = '{"extra":NaN}'
        self.decision()
        result = simulate_paper_fills(1)
        self.assertFalse(result['success'])
        self.assertEqual(result['simulated_count'], 0)
        self.assertEqual(EventStrategyOrder.query.count(), 0)
        self.assertEqual(EventStrategyLog.query.count(), 0)

    @unittest.skipUnless(os.environ.get('QUANT_LEGACY_TEST_DATABASE_URI', '').startswith('postgresql'),
                         'Requires isolated PostgreSQL row locks')
    def test_concurrent_calls_cannot_duplicate_or_overspend(self):
        self.limits(max_open_dollars=.5)
        ids = [self.decision(symbol).id for symbol in ('ONE', 'TWO')]
        self._race([[ids[0]], [ids[1]]])

    @unittest.skipUnless(os.environ.get('QUANT_LEGACY_TEST_DATABASE_URI', '').startswith('postgresql'),
                         'Requires isolated PostgreSQL row locks')
    def test_concurrent_replay_with_budget_for_two_fills_still_fills_once(self):
        row = self.decision()
        self._race([[row.id], [row.id]])

    def _race(self, selections):
        barrier = Barrier(2)
        def invoke(selection):
            with self.app.app_context():
                barrier.wait(timeout=5)
                return simulate_paper_fills(1, decision_ids=selection)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(invoke, selections))
        self.assertTrue(all(result['success'] for result in results))
        self.assertEqual(EventStrategyOrder.query.count(), 1)
        self.assertLessEqual(sum(row.quantity * row.filled_price + row.fee
                                 for row in EventStrategyOrder.query.all()), .5)


if __name__ == '__main__':
    unittest.main()
