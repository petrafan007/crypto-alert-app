"""Settlement during entry stops, using an ephemeral database and mocked quotes."""
import unittest
import json
import os
from datetime import datetime, timedelta
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from sqlalchemy.schema import CreateSchema
from core.extensions import db
from credentials import User
from event_algo import event_algo_worker_loop, resolve_event_outcomes
from event_algo_models import (
    EventStrategyConfig, EventMarketSnapshot, EventContractOutcome,
    EventStrategyOrder, EventStrategyDecision,
)
from portfolio_algo_models import PortfolioStrategyPosition, PortfolioStrategyLot, PortfolioEngineState
from services.event_settlement_timing import repair_date_only_settlements
from services.event_settlement_repair import collect_legacy_settlement_evidence, repair_verified_legacy_settlements


class PausedEventSettlementTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_SETTLEMENT_TEST_DATABASE_URI', 'sqlite://')
        schema = 'settlement_test_' + uuid4().hex
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'options': '-csearch_path=' + schema}}
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        tables = [model.__table__ for model in (
            EventStrategyConfig, EventMarketSnapshot, EventContractOutcome,
            EventStrategyOrder, EventStrategyDecision, PortfolioStrategyPosition,
            PortfolioStrategyLot, PortfolioEngineState, User,
        )]
        db.metadata.create_all(db.engine, tables=tables)
        self.config = EventStrategyConfig(user_id=1, name='Paused test', enabled=False,
                                          mode='PAPER', kill_switch=True, worker_status='KILLED')
        db.session.add(self.config)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def test_killed_config_resolves_and_settles_once_without_crossing_users(self):
        now = datetime.utcnow()
        for user in (1, 2):
            db.session.add(EventMarketSnapshot(user_id=user, config_id=self.config.id,
                run_id=1, contract_symbol='TEST', cutoff_at=now-timedelta(minutes=5)))
            db.session.add(EventStrategyOrder(user_id=user, config_id=self.config.id,
                contract_symbol='TEST', outcome='YES', side='BUY', quantity=2,
                status='SIMULATED_FILLED', filled_quantity=2, filled_price=.4, fee=.03))
        db.session.commit()
        credential = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        with patch('event_algo._webull_connection_for_user', return_value=(credential, 'test')), \
                patch('services.webull_service.get_webull_event_market', return_value={'settled_outcome': 'YES'}) as quote:
            result = resolve_event_outcomes(1, config=self.config)
            repeat = resolve_event_outcomes(1, config=self.config, force=True)
        self.assertEqual(result['resolved_count'], 1)
        self.assertEqual(repeat['resolved_count'], 0)
        quote.assert_called_once()
        settled = EventStrategyOrder.query.filter_by(user_id=1).one()
        self.assertEqual(settled.status, 'SIMULATED_SETTLED')
        self.assertAlmostEqual(settled.realized_pnl, 1.17)
        self.assertEqual(EventStrategyOrder.query.filter_by(user_id=2).one().status, 'SIMULATED_FILLED')
        self.assertEqual(EventContractOutcome.query.count(), 1)
        self.assertTrue(self.config.kill_switch)
        self.assertFalse(self.config.enabled)

    def test_worker_resolves_stopped_killed_and_master_paused_configs_without_scanning(self):
        # Exercise the actual supervisor query and gating, one iteration each.
        for enabled, killed, master_killed in [(False, False, False), (True, True, False),
                                               (False, True, True), (True, False, True)]:
            with self.subTest(enabled=enabled, killed=killed, master_killed=master_killed):
                self.config = db.session.get(EventStrategyConfig, self.config.id)
                self.config.enabled, self.config.kill_switch = enabled, killed
                db.session.merge(PortfolioEngineState(user_id=1, kill_switch=master_killed))
                db.session.commit()
                stop = Mock()
                stop.is_set.side_effect = [False, True]
                with patch('event_algo.is_event_strategy_admin', return_value=True), \
                        patch('event_algo.resolve_event_outcomes', return_value={'resolved_count': 0}) as resolve, \
                        patch('event_algo.run_event_strategy_scan') as scan, \
                        patch('event_algo.generate_event_strategy_report') as report:
                    event_algo_worker_loop(self.app, stop)
                resolve.assert_called_once()
                scan.assert_not_called()
                report.assert_not_called()
                stop.wait.assert_called_once_with(15)

    def test_resolution_still_rejects_live_mode(self):
        self.config.mode = 'LIVE'
        with patch('event_algo._webull_connection_for_user') as connection:
            self.assertFalse(resolve_event_outcomes(1, config=self.config)['success'])
        connection.assert_not_called()

    def test_empty_paused_config_needs_no_provider_credentials(self):
        with patch('event_algo._webull_connection_for_user') as connection:
            self.assertEqual(resolve_event_outcomes(1, config=self.config)['resolved_count'], 0)
        connection.assert_not_called()

    def test_worker_preserves_account_ownership_gate(self):
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        with patch('event_algo.is_event_strategy_admin', return_value=False), \
                patch('event_algo.resolve_event_outcomes') as resolve:
            event_algo_worker_loop(self.app, stop)
        resolve.assert_not_called()

    def test_new_date_only_resolution_uses_time_after_provider_response(self):
        cutoff = datetime.utcnow()-timedelta(minutes=5)
        db.session.add(EventMarketSnapshot(user_id=1, config_id=self.config.id, contract_symbol='TEST', cutoff_at=cutoff))
        db.session.add(EventStrategyOrder(user_id=1, config_id=self.config.id, contract_symbol='TEST', outcome='YES',
                                         side='BUY', quantity=2, status='SIMULATED_FILLED', filled_quantity=2, filled_price=.4, fee=.03))
        db.session.commit()
        credential = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        response_times = []
        def response(*args, **kwargs):
            response_times.append(datetime.utcnow())
            return {'settled_outcome': 'YES', 'payout_date': cutoff.date().isoformat()}
        with patch('event_algo._webull_connection_for_user', return_value=(credential, 'test')), \
                patch('services.webull_service.get_webull_event_market', side_effect=response):
            result = resolve_event_outcomes(1, config=self.config)
        self.assertEqual(result['resolved_count'], 1)
        outcome = EventContractOutcome.query.one()
        order = EventStrategyOrder.query.one()
        self.assertGreaterEqual(outcome.observed_at, response_times[0])
        self.assertEqual(outcome.settlement_at, outcome.observed_at)
        self.assertEqual(order.settled_at, outcome.observed_at)
        self.assertAlmostEqual(order.realized_pnl, 1.17)
        self.assertEqual(json.loads(outcome.raw_json)['_settlement_timing']['basis'], 'OBSERVED_RESOLUTION')

    def test_historical_repair_is_scoped_reversible_and_idempotent(self):
        old = datetime(2026, 9, 13)
        cutoff, observed = old+timedelta(hours=15), old+timedelta(hours=15, minutes=5)
        for user_id in (1, 2):
            db.session.add(EventContractOutcome(user_id=user_id, config_id=self.config.id, contract_symbol='TEST',
                outcome='YES', settlement_status='RESOLVED', cutoff_at=cutoff, observed_at=observed,
                settlement_at=old, resolved_source='WEBULL_EVENT_MARKET',
                raw_json=json.dumps({'settled_outcome': 'YES', 'payout_date': '2026-09-13', 'original_evidence': 123})))
            db.session.add(EventStrategyOrder(user_id=user_id, config_id=self.config.id, contract_symbol='TEST',
                outcome='YES', side='BUY', quantity=2, status='SIMULATED_SETTLED', settled_at=old,
                filled_quantity=2, filled_price=.4, fee=.03, realized_pnl=1.17))
        db.session.add(EventStrategyOrder(user_id=1, config_id=self.config.id+10, contract_symbol='TEST',
            outcome='YES', side='BUY', quantity=2, status='SIMULATED_SETTLED', settled_at=old, realized_pnl=1.17))
        db.session.commit()
        before = EventContractOutcome.query.filter_by(user_id=1).one().raw_json
        preview = repair_date_only_settlements(user_id=1)
        self.assertEqual((preview['eligible_outcomes'], preview['matching_orders']), (1, 1))
        self.assertEqual(preview['updated_outcomes'], 0)
        self.assertEqual(EventContractOutcome.query.filter_by(user_id=1).one().raw_json, before)
        applied = repair_date_only_settlements(user_id=1, apply=True)
        db.session.commit()
        self.assertEqual((applied['updated_outcomes'], applied['updated_orders']), (1, 1))
        outcome = EventContractOutcome.query.filter_by(user_id=1).one()
        evidence = json.loads(outcome.raw_json)
        self.assertEqual(evidence['original_evidence'], 123)
        self.assertEqual(evidence['_settlement_timing']['repair']['previous_settlement_at'], old.isoformat()+'+00:00')
        order = EventStrategyOrder.query.filter_by(user_id=1, config_id=self.config.id).one()
        self.assertEqual((outcome.settlement_at, order.settled_at), (observed, observed))
        self.assertEqual((order.quantity, order.filled_price, order.fee, order.realized_pnl), (2, .4, .03, 1.17))
        self.assertEqual(EventContractOutcome.query.filter_by(user_id=2).one().settlement_at, old)
        self.assertEqual(EventStrategyOrder.query.filter_by(user_id=1, config_id=self.config.id+10).one().settled_at, old)
        self.assertEqual(repair_date_only_settlements(user_id=1, apply=True)['updated_outcomes'], 0)

    def test_historical_repair_skips_ambiguous_evidence(self):
        old = datetime(2026, 9, 13)
        raw = {'payout_date': '2026-09-13', 'settled_outcome': 'YES'}
        cases = [{'raw_json': 'bad'}, {'raw_json': json.dumps({'payout_date': '2026-09-13T00:00:00Z'})},
                 {'outcome': 'NO'}, {'observed_at': old}, {'resolved_source': None},
                 {'settlement_at': old+timedelta(minutes=1)},
                 {'raw_json': json.dumps({**raw, '_settlement_timing': {'version': 1}})}]
        for index, changes in enumerate(cases):
            values = dict(user_id=1, config_id=self.config.id, contract_symbol=f'TEST-{index}', outcome='YES',
                          settlement_status='RESOLVED', settlement_at=old, cutoff_at=old+timedelta(hours=15),
                          observed_at=old+timedelta(hours=16), resolved_source='WEBULL_EVENT_MARKET', raw_json=json.dumps(raw))
            db.session.add(EventContractOutcome(**{**values, **changes}))
        db.session.commit()
        result = repair_date_only_settlements(apply=True)
        self.assertEqual(result['examined'], len(cases))
        self.assertEqual(result['updated_outcomes'], 0)
        self.assertEqual(sum(result['skipped'].values()), len(cases))

    def test_historical_trade_prices_cannot_certify_resolution_by_repairing_time(self):
        # Archived production records contain near-terminal quotes, not explicit
        # provider payouts. Repair must not make them eligible for calibration.
        old = datetime(2026, 9, 13)
        for index, (outcome, price) in enumerate((('YES', .999), ('NO', .001), ('YES', 1), ('NO', 0))):
            db.session.add(EventContractOutcome(user_id=1, config_id=self.config.id,
                contract_symbol=f'LEGACY-{index}', outcome=outcome, settlement_status='RESOLVED',
                settlement_at=old, cutoff_at=old+timedelta(hours=15), observed_at=old+timedelta(hours=16),
                resolved_source='WEBULL_EVENT_MARKET', raw_json=json.dumps({
                    'payout_date': '2026-09-13', 'status': 'DELISTING', 'tradable_status': 'NT', 'last_price': price})))
        db.session.commit()
        before = [(row.id, row.raw_json, row.settlement_at) for row in EventContractOutcome.query.order_by(EventContractOutcome.id)]
        report = repair_date_only_settlements(apply=True)
        db.session.commit()
        self.assertEqual(report['updated_outcomes'], 0)
        self.assertEqual(report['skipped'], {'unverified_resolution': 4})
        self.assertEqual(before, [(row.id, row.raw_json, row.settlement_at)
                                  for row in EventContractOutcome.query.order_by(EventContractOutcome.id)])

    def legacy_provider_fixture(self, user_id=1, symbol='KXBTC15M-26SEP031500-00'):
        old = datetime(2026, 9, 3)
        cutoff = old+timedelta(hours=19)
        row = EventContractOutcome(user_id=user_id, config_id=self.config.id, contract_symbol=symbol,
            outcome='YES', settlement_status='RESOLVED', cutoff_at=cutoff, settlement_at=old,
            observed_at=cutoff+timedelta(minutes=4), settlement_price=.999, resolved_source='WEBULL_EVENT_MARKET',
            raw_json=json.dumps({'payout_date': old.date().isoformat(), 'last_price': .999, 'status': 'DELISTING'}))
        db.session.add(row)
        provider = {'source_url': 'https://external-api.kalshi.com/trade-api/v2/markets/'+symbol,
            'market': {'ticker': symbol, 'market_type': 'binary', 'status': 'finalized', 'result': 'yes',
                       'close_time': cutoff.isoformat()+'Z', 'settlement_ts': (cutoff+timedelta(minutes=1)).isoformat()+'Z',
                       'settlement_value_dollars': '1.0000'}}
        return row, provider

    def test_provider_repair_previews_archives_and_preserves_money_and_scope(self):
        row, provider = self.legacy_provider_fixture()
        self.legacy_provider_fixture(user_id=2)
        old, symbol, config_id = row.settlement_at, row.contract_symbol, self.config.id
        for user, config, mode in ((1, config_id, 'PAPER'), (2, config_id, 'PAPER'),
                                    (1, config_id+10, 'PAPER'), (1, config_id, 'LIVE')):
            db.session.add(EventStrategyOrder(user_id=user, config_id=config, contract_symbol=symbol,
                mode=mode, outcome='YES', side='BUY', quantity=2, status='SIMULATED_SETTLED', settled_at=old,
                filled_quantity=2, filled_price=.4, fee=.03, realized_pnl=1.17))
        db.session.commit()
        def lookup(*args):
            if hasattr(db.engine.pool, 'checkedout'):
                self.assertEqual(db.engine.pool.checkedout(), 0, 'Provider I/O must not hold a DB connection')
            return provider
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', side_effect=lookup) as fetch:
            plan = collect_legacy_settlement_evidence(1)
        fetch.assert_called_once()
        # JSON round trips must preserve the exact stale-state comparison.
        plan = json.loads(json.dumps(plan))
        preview = repair_verified_legacy_settlements(plan, user_id=1)
        self.assertEqual((preview['eligible_outcomes'], preview['matching_orders'], preview['updated_outcomes']), (1, 1, 0))
        self.assertEqual(EventContractOutcome.query.filter_by(user_id=1).one().settlement_at, old)
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', side_effect=AssertionError('HTTP in apply')):
            applied = repair_verified_legacy_settlements(plan, user_id=1, apply=True)
        db.session.commit()
        self.assertEqual((applied['updated_outcomes'], applied['updated_orders']), (1, 1))
        fixed = EventContractOutcome.query.filter_by(user_id=1).one()
        self.assertEqual(fixed.settlement_at, datetime(2026, 9, 3, 19, 1))
        self.assertEqual((fixed.outcome, fixed.settlement_price, fixed.resolved_source), ('YES', 1, 'KALSHI_FINALIZED_MARKET'))
        archived = json.loads(fixed.raw_json)['_settlement_timing']['repair']
        self.assertEqual(archived['previous_outcome'], plan['records'][0]['before'])
        self.assertEqual(archived['previous_orders'][0]['realized_pnl'], 1.17)
        for order in EventStrategyOrder.query.all():
            self.assertEqual((order.quantity, order.filled_price, order.fee, order.realized_pnl), (2, .4, .03, 1.17))
            expected = fixed.settlement_at if (order.user_id, order.config_id, order.mode) == (1, config_id, 'PAPER') else old
            self.assertEqual(order.settled_at, expected)
        self.assertEqual(EventContractOutcome.query.filter_by(user_id=2).one().settlement_at, old)
        self.assertEqual(repair_verified_legacy_settlements(plan, user_id=1, apply=True)['updated_outcomes'], 0)

    def test_provider_repair_rejects_conflicts_invalid_evidence_and_failed_lookups(self):
        row, provider = self.legacy_provider_fixture()
        db.session.commit()
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', return_value=provider):
            original = collect_legacy_settlement_evidence(1)
        for change, reason in (({'result': 'no', 'settlement_value_dollars': '0'}, 'outcome_conflict'),
                               ({'ticker': 'WRONG'}, 'invalid_provider_evidence'),
                               ({'status': 'determined'}, 'invalid_provider_evidence'),
                               ({'close_time': '2026-09-03T18:00:00Z'}, 'invalid_provider_evidence'),
                               ({'settlement_ts': '2026-09-03'}, 'invalid_provider_evidence')):
            plan = json.loads(json.dumps(original))
            plan['records'][0]['provider']['market'].update(change)
            report = repair_verified_legacy_settlements(plan, user_id=1, apply=True)
            self.assertEqual(report['skipped'], {reason: 1})
            self.assertEqual(report['updated_outcomes'], 0)
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', side_effect=TimeoutError('private request')):
            plan = collect_legacy_settlement_evidence(1)
        self.assertEqual(plan['records'][0]['error'], 'TimeoutError')
        self.assertNotIn('private request', json.dumps(plan))
        self.assertEqual(repair_verified_legacy_settlements(plan, user_id=1)['skipped'], {'provider_unavailable': 1})

    def test_provider_repair_rechecks_changed_rows_and_supports_transaction_rollback(self):
        row, provider = self.legacy_provider_fixture()
        db.session.commit()
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', return_value=provider):
            plan = collect_legacy_settlement_evidence(1)
        self.assertEqual(repair_verified_legacy_settlements(plan, user_id=1, apply=True)['updated_outcomes'], 1)
        db.session.rollback()
        self.assertEqual(EventContractOutcome.query.one().resolved_source, 'WEBULL_EVENT_MARKET')
        EventContractOutcome.query.one().raw_json = '{"changed": true}'
        db.session.commit()
        self.assertEqual(repair_verified_legacy_settlements(plan, user_id=1, apply=True)['skipped'], {'changed_or_missing_outcome': 1})

    def test_provider_repair_enforces_user_scope_and_bounded_cursor(self):
        _, provider = self.legacy_provider_fixture()
        self.legacy_provider_fixture(symbol='KXBTC15M-26SEP031515-15')
        db.session.commit()
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', return_value=provider):
            first = collect_legacy_settlement_evidence(1, limit=1)
            second = collect_legacy_settlement_evidence(1, limit=1, after_id=first['last_id'])
        self.assertTrue(first['truncated'])
        self.assertFalse(second['truncated'])
        self.assertNotEqual(first['records'][0]['before']['id'], second['records'][0]['before']['id'])
        with self.assertRaises(ValueError):
            repair_verified_legacy_settlements(first, user_id=2, apply=True)
        first['records'][0]['before']['user_id'] = 2
        with self.assertRaises(ValueError):
            repair_verified_legacy_settlements(first, user_id=1, apply=True)
        for limit in (0, 1001, True):
            with self.assertRaises(ValueError):
                collect_legacy_settlement_evidence(1, limit=limit)

    def test_provider_verified_repair_restores_pre_cutoff_calibration_sample(self):
        from services.portfolio_calibration import event_calibration
        row, provider = self.legacy_provider_fixture()
        start = row.cutoff_at-timedelta(hours=1)
        market = EventMarketSnapshot(user_id=1, config_id=self.config.id, contract_symbol=row.contract_symbol,
                                      cutoff_at=row.cutoff_at, yes_bid=.45, yes_ask=.55)
        db.session.add(market)
        db.session.flush()
        db.session.add(EventStrategyDecision(user_id=1, config_id=self.config.id, snapshot_id=market.id,
            contract_symbol=row.contract_symbol, created_at=start, probability_yes=.8, action='NO_TRADE', eligible=False))
        db.session.commit()
        self.assertEqual(event_calibration(1, start)['resolved_contracts'], 0)
        db.session.rollback()
        with patch('services.event_settlement_repair.confirmed_kalshi_settlement', return_value=provider):
            plan = collect_legacy_settlement_evidence(1)
        repair_verified_legacy_settlements(plan, user_id=1, apply=True)
        db.session.commit()
        calibration = event_calibration(1, start)
        self.assertEqual(calibration['resolved_contracts'], 1)
        self.assertAlmostEqual(calibration['brier_score'], .04)
