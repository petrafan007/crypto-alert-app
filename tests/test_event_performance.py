"""Evidence, sample and accounting regressions for legacy Event performance."""
import inspect
import json
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from flask import Flask
from sqlalchemy.schema import CreateSchema

from core.extensions import db
from event_algo import event_strategy_performance
from event_algo_models import (
    EventContractOutcome as Outcome, EventStrategyConfig as Config,
    EventStrategyDecision as Decision, EventStrategyOrder as Order,
)


class EventPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_PERFORMANCE_TEST_DATABASE_URI', 'sqlite://')
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        schema = 'performance_test_' + uuid4().hex
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'options': '-csearch_path=' + schema}}
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in (Outcome, Config, Decision, Order)])
        self.config = Config(user_id=1, name='Report')
        db.session.add(self.config)
        db.session.commit()
        self.now = datetime.utcnow()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def order(self, symbol='TEST', **changes):
        values = dict(user_id=1, config_id=self.config.id, contract_symbol=symbol, mode='PAPER',
            status='SIMULATED_SETTLED', side='BUY', outcome='YES', quantity=1, filled_quantity=1,
            filled_price=.4, limit_price=.4, fee=.02, submitted_at=self.now-timedelta(hours=2),
            settled_at=self.now-timedelta(hours=1))
        values.update(changes)
        row = Order(**values)
        db.session.add(row)
        db.session.flush()
        return row

    def resolve(self, order, outcome='YES', **changes):
        values = dict(user_id=order.user_id, config_id=order.config_id, contract_symbol=order.contract_symbol,
            outcome=outcome, settlement_status='RESOLVED', resolved_source='TEST_PROVIDER',
            cutoff_at=self.now-timedelta(minutes=90), settlement_at=order.settled_at,
            observed_at=self.now-timedelta(minutes=5), raw_json=json.dumps({'settled_outcome': outcome}))
        values.update(changes)
        row = Outcome(**values)
        db.session.add(row)
        db.session.flush()
        return row

    def report(self, **kwargs):
        db.session.commit()
        return event_strategy_performance(1, **kwargs)

    def test_empty_is_unavailable_instead_of_zero_profit(self):
        result = self.report()
        self.assertEqual(result['status'], 'EMPTY')
        self.assertEqual(result['trades'], 0)
        for key in ('net_pnl', 'fees', 'max_drawdown', 'profit_factor', 'expectancy'):
            self.assertIsNone(result[key])

    def test_default_zero_pnl_reconstructed_without_mutating_history(self):
        row = self.order()
        self.resolve(row)
        result = self.report()
        self.assertEqual(result['trades'], 1)
        self.assertEqual(result['net_pnl'], .58)
        self.assertEqual(result['stored_pnl_discrepancies'], 1)
        self.assertEqual(db.session.get(Order, row.id).realized_pnl, 0)
        self.assertFalse(db.session.dirty)
        self.assertAlmostEqual(result['gross_pnl'] - result['fees'], result['net_pnl'])

    def test_zero_and_null_price_are_never_replaced_by_a_limit(self):
        for i, price in enumerate((None, 0, 1, float('inf'), float('nan'))):
            self.resolve(self.order('TEST'+str(i), filled_price=price))
        result = self.report()
        self.assertEqual(result['exclusions']['invalid_fill_values'], 5)
        self.assertEqual(result['trades'], 0)
        self.assertIsNone(result['net_pnl'])

    def test_status_and_filled_quantity_determine_pending_not_outcome_presence(self):
        self.resolve(self.order('CANCELLED', status='CANCELLED'))
        self.resolve(self.order('UNFILLED', filled_quantity=0))
        pending = self.order('PENDING', status='SIMULATED_FILLED', settled_at=None)
        self.resolve(pending, settlement_at=self.now-timedelta(hours=1))
        self.order('UNRESOLVED', status='SIMULATED_PENDING', settled_at=None)
        self.order('MISSING')
        result = self.report()
        self.assertEqual(result['pending'], 2)
        self.assertEqual(result['trades'], 0)
        self.assertEqual(result['excluded'], 3)
        self.assertEqual(result['exclusions']['missing_settlement_evidence'], 1)
        self.assertEqual(result['sample']['examined_orders'], result['trades']+result['pending']+result['excluded'])

    def test_partial_fills_use_actual_quantity_and_zero_fee(self):
        self.resolve(self.order(quantity=5, filled_quantity=2, fee=0))
        result = self.report()
        self.assertEqual(result['net_pnl'], 1.2)
        self.assertEqual(result['fees'], 0)

    def test_winning_outcome_can_lose_money_after_fees(self):
        self.resolve(self.order('LOSS', filled_price=.99))
        self.resolve(self.order('FLAT', filled_price=.98))
        self.resolve(self.order('PROFIT', filled_price=.97))
        result = self.report()
        self.assertEqual((result['wins'], result['losses'], result['breakeven']), (1, 1, 1))
        self.assertEqual(result['outcome_wins'], 3)
        self.assertEqual(result['net_pnl'], 0)
        self.assertEqual(result['profit_factor'], 1)

    def test_sample_uses_newest_entries_and_discloses_omitted_records(self):
        for index, price in enumerate((.1, .2, .3)):
            self.resolve(self.order(str(index), filled_price=price,
                                   submitted_at=self.now-timedelta(hours=2)+timedelta(seconds=index)))
        result = self.report(limit=2)
        self.assertEqual(result['net_pnl'], 1.46)
        self.assertEqual(result['sample']['total_orders'], 3)
        self.assertEqual(result['sample']['omitted_orders'], 1)
        self.assertTrue(result['sample']['truncated'])

    def test_same_submission_timestamp_uses_id_as_stable_sample_tiebreaker(self):
        self.resolve(self.order('FIRST', filled_price=.1))
        self.resolve(self.order('SECOND', filled_price=.9))
        self.assertEqual(self.report(limit=1)['net_pnl'], .08)

    def test_drawdown_follows_settlement_sequence(self):
        # Entry sequence is loss, loss, win; settlement sequence loss, win, loss.
        for index, (result, offset) in enumerate((('NO', 0), ('NO', 2), ('YES', 1))):
            order = self.order(str(index), filled_price=.5, fee=0,
                submitted_at=self.now-timedelta(hours=2)+timedelta(seconds=index),
                settled_at=self.now-timedelta(hours=1)+timedelta(minutes=offset))
            self.resolve(order, result)
        report = self.report()
        self.assertEqual(report['net_pnl'], -.5)
        self.assertEqual(report['max_drawdown'], .5)

    def test_user_configuration_outcome_and_mode_isolation(self):
        own = self.order('OWN')
        self.resolve(own)
        other = Config(user_id=1, name='Second')
        foreign = Config(user_id=2, name='Foreign')
        db.session.add_all([other, foreign])
        db.session.flush()
        self.resolve(self.order('OTHER', config_id=other.id))
        self.resolve(self.order('FOREIGN', user_id=2, config_id=foreign.id))
        self.resolve(self.order('LIVE', mode='LIVE'))
        self.resolve(self.order('BAD_SCOPE'), config_id=other.id)
        self.assertEqual(self.report()['trades'], 2)
        self.assertEqual(self.report(config=self.config)['trades'], 1)
        with self.assertRaises(ValueError):
            self.report(config=foreign)

    def test_conflicting_and_duplicate_outcomes_never_duplicate_a_trade(self):
        good = self.order('GOOD')
        self.resolve(good)
        self.resolve(good)
        bad = self.order('BAD')
        self.resolve(bad)
        self.resolve(bad, 'NO')
        result = self.report()
        self.assertEqual(result['trades'], 1)
        self.assertEqual(result['exclusions']['conflicting_settlement_evidence'], 1)

    def test_missing_false_or_mismatched_proof_and_invalid_chronology_are_excluded(self):
        changes = [dict(raw_json='{}'), dict(raw_json='[]'), dict(raw_json='bad'),
                   dict(raw_json='{"settled_outcome":"NO"}'), dict(resolved_source=None),
                   dict(raw_json='{"status":"SETTLED","settlement_price":false}'),
                   dict(observed_at=self.now+timedelta(seconds=30)),
                   dict(cutoff_at=self.now-timedelta(hours=3)),
                   dict(settlement_at=self.now-timedelta(minutes=59)),
                   dict(config_id=None)]
        for index, change in enumerate(changes):
            self.resolve(self.order(str(index)), **change)
        result = self.report()
        self.assertEqual(result['excluded'], len(changes))
        self.assertEqual(result['trades'], 0)

    def test_malformed_or_foreign_duration_metadata_stays_unknown(self):
        for index, value in enumerate(('[]', '{"contract_details":[]}', '{"contract_details":{"duration_label":17}}', 'bad')):
            decision = Decision(user_id=1, config_id=self.config.id, contract_symbol=str(index),
                                action='BUY_YES', feature_json=value)
            db.session.add(decision)
            db.session.flush()
            self.resolve(self.order(str(index), decision_id=decision.id))
        foreign = Decision(user_id=2, config_id=self.config.id, contract_symbol='FOREIGN', action='BUY_YES',
                           feature_json='{"contract_details":{"duration_label":"daily"}}')
        db.session.add(foreign)
        db.session.flush()
        self.resolve(self.order('FOREIGN', decision_id=foreign.id))
        result = self.report()
        self.assertEqual(result['by_duration'], [{'duration': 'Unknown duration', 'trades': 5,
                                                'wins': 5, 'losses': 0, 'breakeven': 0, 'net_pnl': 2.9}])

    def test_invalid_values_and_status_times_are_counted_as_exclusions(self):
        changes = [dict(filled_quantity=-1), dict(filled_quantity=2), dict(quantity=1.5), dict(fee=-.1),
                   dict(side='SELL'), dict(outcome='UNKNOWN'), dict(settled_at=None),
                   dict(settled_at=self.now-timedelta(hours=3)), dict(submitted_at=self.now+timedelta(minutes=1)),
                   dict(status='SIMULATED_FILLED')]
        for index, change in enumerate(changes):
            self.resolve(self.order(str(index), **change))
        result = self.report()
        self.assertEqual(result['excluded'], len(changes))
        self.assertEqual(result['trades'], 0)

    def test_api_configuration_selection_and_non_disclosure(self):
        from routes.event_algo import event_algo_performance
        foreign = Config(user_id=2, name='Foreign')
        db.session.add(foreign)
        db.session.commit()
        self.resolve(self.order())
        db.session.commit()
        for config_id, status in ((str(self.config.id), 200), (str(foreign.id), 404), ('0', 400), ('bad', 400)):
            with self.app.test_request_context('/api/webull/event-algo/performance?config_id='+config_id), \
                    patch('routes.event_algo.current_user', SimpleNamespace(id=1)):
                response = inspect.unwrap(event_algo_performance)()
                response, code = response if isinstance(response, tuple) else (response, response.status_code)
                self.assertEqual(code, status)
                if status == 200:
                    self.assertEqual(response.json['scope']['config_id'], self.config.id)


if __name__ == '__main__':
    unittest.main()
