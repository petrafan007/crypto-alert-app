"""Calibration population selection against isolated SQLite or PostgreSQL."""
import os
import json
import unittest
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Flask
from sqlalchemy.schema import CreateSchema

from core.extensions import db
from event_algo_models import EventContractOutcome as Outcome, EventMarketSnapshot as Market, EventStrategyDecision as Decision
from services.portfolio_calibration import event_calibration


class CalibrationQueryTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        uri = os.environ.get('QUANT_CALIBRATION_TEST_DATABASE_URI', 'sqlite://')
        app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        schema = 'calibration_test_' + uuid4().hex
        if uri.startswith('postgresql'):
            app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'options': '-csearch_path=' + schema}}
        db.init_app(app)
        self.context = app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in (Market, Decision, Outcome)])
        self.start = datetime(2026, 9, 13, 12)
        self.cutoff = self.start + timedelta(hours=1)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def forecast(self, contract, probability=.8, minute=0, user_id=1, **changes):
        market = Market(user_id=user_id, config_id=7, contract_symbol=contract,
                        cutoff_at=self.cutoff, yes_bid=.45, yes_ask=.55)
        db.session.add(market)
        db.session.flush()
        values = dict(user_id=user_id, config_id=7, snapshot_id=market.id,
                      contract_symbol=contract, probability_yes=probability,
                      created_at=self.start + timedelta(minutes=minute), action='NO_TRADE', eligible=False)
        values.update(changes)
        decision = Decision(**values)
        db.session.add(decision)
        db.session.flush()
        return decision, market

    def resolve(self, contract, result='YES', **changes):
        values = dict(user_id=1, config_id=7, contract_symbol=contract, cutoff_at=self.cutoff,
                      outcome=result, settlement_status='RESOLVED', resolved_source='TEST_PROVIDER',
                      settlement_at=self.cutoff + timedelta(minutes=1), updated_at=self.cutoff + timedelta(minutes=2))
        values.update(changes)
        db.session.add(Outcome(**values))
        db.session.flush()

    def calibration(self, limit=2):
        db.session.commit()
        return event_calibration(1, self.start, limit)

    def test_repeated_forecasts_do_not_consume_contract_limit(self):
        for minute in range(5):
            self.forecast('A', .8 if minute == 0 else .1, minute)
        self.forecast('B', .2, 6)
        self.resolve('A')
        self.resolve('B', 'NO')
        result = self.calibration()
        self.assertEqual(result['resolved_contracts'], 2)
        self.assertEqual(result['eligible_resolved_contracts'], 2)
        self.assertEqual(result['forecast_rows_examined'], 6)
        self.assertEqual(result['exclusions']['repeated_contract_forecast'], 4)
        self.assertFalse(result['truncated'])
        self.assertAlmostEqual(result['brier_score'], .04)
        self.assertAlmostEqual(result['skill_score'], .84)

    def test_validation_precedes_ranking_and_sampling(self):
        self.forecast('A', 1.2)
        self.forecast('A', .8, 1)
        _, bad_snapshot = self.forecast('B', .9)
        bad_snapshot.cutoff_at = None
        self.forecast('B', .2, 2)
        self.forecast('C', .1, 60)
        self.forecast('D', .1, 3)
        self.forecast('E', .1, 4)
        self.resolve('A')
        self.resolve('B', 'NO')
        self.resolve('C')
        self.resolve('E', settlement_at=self.start)
        result = self.calibration()
        self.assertEqual(result['resolved_contracts'], 2)
        self.assertAlmostEqual(result['brier_score'], .04)
        self.assertFalse(result['truncated'])
        self.assertEqual(result['exclusions'], {'invalid_or_post_cutoff_forecast': 3,
                                               'no_verified_resolution': 1, 'invalid_resolution_timestamp': 1})

    def test_truncation_and_equal_timestamp_ties_use_distinct_contracts(self):
        self.forecast('A', .8)
        self.forecast('A', .1)
        self.forecast('B', .2)
        self.forecast('C', .9, 1)
        for contract, result in [('A', 'YES'), ('B', 'NO'), ('C', 'YES')]:
            self.resolve(contract, result)
        result = self.calibration()
        self.assertEqual(result['resolved_contracts'], 2)
        self.assertEqual(result['sampled_forecasts'], 2)
        self.assertEqual(result['eligible_resolved_contracts'], 3)
        self.assertEqual(result['contract_limit'], 2)
        self.assertTrue(result['truncated'])
        self.assertAlmostEqual(result['brier_score'], .04)
        self.assertFalse(self.calibration(limit=3)['truncated'])

    def test_duplicate_outcomes_use_latest_valid_record_without_using_sample_slots(self):
        self.forecast('A', .8)
        self.forecast('B', .2, 1)
        self.resolve('A', 'YES', config_id=None)
        self.resolve('A', 'NO')  # Same update time: higher outcome ID breaks the tie.
        self.resolve('A', 'YES', resolved_source='', updated_at=self.cutoff + timedelta(minutes=3))
        self.resolve('B', 'NO')
        result = self.calibration()
        self.assertEqual(result['resolved_contracts'], 2)
        self.assertFalse(result['truncated'])
        self.assertAlmostEqual(result['brier_score'], .34)
        self.assertEqual(result['exclusions'], {'no_verified_resolution': 1, 'repeated_contract_forecast': 1})

    def test_user_run_snapshot_and_outcome_scope(self):
        self.forecast('A', .1, -1)
        self.forecast('A', .8)
        self.forecast('OTHER_USER', .1, user_id=2)
        self.resolve('A')
        self.resolve('OTHER_USER', user_id=2)
        for contract, outcome_changes in [('WRONG_USER', {'user_id': 2}),
                                          ('WRONG_CONFIG', {'config_id': 8}),
                                          ('WRONG_CUTOFF', {'cutoff_at': self.cutoff + timedelta(hours=1)})]:
            self.forecast(contract)
            self.resolve(contract, **outcome_changes)
        _, wrong_user = self.forecast('WRONG_SNAPSHOT_USER')
        wrong_user.user_id = 2
        _, wrong_contract = self.forecast('WRONG_SNAPSHOT_CONTRACT')
        wrong_contract.contract_symbol = 'OTHER_CONTRACT'
        self.resolve('WRONG_SNAPSHOT_USER')
        self.resolve('WRONG_SNAPSHOT_CONTRACT')
        result = self.calibration()
        self.assertEqual(result['resolved_contracts'], 1)
        self.assertEqual(result['forecast_rows_examined'], 4)
        self.assertAlmostEqual(result['brier_score'], .04)
        self.assertEqual(result['exclusions'], {'no_verified_resolution': 3})

    def test_market_comparison_stays_on_the_matched_subset(self):
        self.forecast('A', .8)
        _, unmatched = self.forecast('B', 0, 1)
        unmatched.yes_bid = None
        self.resolve('A')
        self.resolve('B')
        result = self.calibration()
        self.assertEqual(result['market_comparison_contracts'], 1)
        self.assertAlmostEqual(result['brier_score'], .52)
        self.assertAlmostEqual(result['skill_score'], .84)

    def test_empty_and_unresolved_population(self):
        result = self.calibration()
        self.assertEqual(result['status'], 'AWAITING_RESOLVED_FORECASTS')
        self.assertIsNone(result['brier_score'])
        self.assertEqual(result['forecast_rows_examined'], 0)
        self.forecast('A')
        result = self.calibration()
        self.assertEqual(result['resolved_contracts'], 0)
        self.assertFalse(result['truncated'])
        self.assertEqual(result['exclusions'], {'no_verified_resolution': 1})

    def test_invalid_limits_are_rejected(self):
        for limit in (0, -1, True, 1.5, '2'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.calibration(limit)

    def test_breakdowns_use_selected_decision_metadata_not_snapshot_or_later_models(self):
        features = {'model': {'provider': 'archived-provider', 'model': 'archived-model'},
                    'contract_details': {'duration_label': '15-minute'}}
        _, snapshot = self.forecast('A', feature_json=json.dumps(features), model_version='archived-v1')
        snapshot.feature_json = json.dumps({'model': {'model': 'older-snapshot-model'}})
        self.forecast('A', minute=1, feature_json='{"model":{"model":"later-model"}}')
        self.forecast('B', minute=2, feature_json='broken JSON')
        self.resolve('A')
        self.resolve('B')
        result = self.calibration(limit=1)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['breakdowns']['model']['rows'][0]['label'], 'archived-provider / archived-model / archived-v1')
        self.assertEqual(result['breakdowns']['duration']['rows'][0]['label'], '15-minute')
        for dimension in ('model', 'duration', 'period'):
            self.assertEqual(sum(row['resolved_contracts'] for row in result['breakdowns'][dimension]['rows']), 1)
        result = self.calibration(limit=2)
        self.assertEqual(result['breakdowns']['model']['total_groups'], 2)
        self.assertTrue(any(row['label'].startswith('Unknown provider') for row in result['breakdowns']['model']['rows']))
