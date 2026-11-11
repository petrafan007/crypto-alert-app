"""Regression tests for the walk-forward isotonic recalibration layer.

The PAV fit must be deterministic, monotone and guarded by a minimum sample
count; the stored map must only reshape predictions published after the fit,
and every calibrated market must archive the map version and raw probability.
"""
import json
import os
import random
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from services.event_recalibration import (
    MIN_CALIBRATION_SAMPLES,
    apply_isotonic,
    calibrate_market,
    fit_isotonic,
    map_version,
    maybe_refit_calibration,
)


class IsotonicFitTests(unittest.TestCase):
    SAMPLES = [(.1, 0), (.2, 0), (.3, 1), (.4, 0), (.5, 1),
               (.6, 1), (.7, 0), (.8, 1), (.9, 1)]

    def test_pav_pools_adjacent_violators(self):
        blocks = fit_isotonic(self.SAMPLES)
        values = [block['value'] for block in blocks]
        self.assertEqual(values, sorted(values))
        pooled = next(block for block in blocks if block['lower'] == .3)
        self.assertEqual(pooled['upper'], .4)
        self.assertEqual(pooled['value'], .5)
        self.assertEqual(pooled['count'], 2)
        wide = next(block for block in blocks if block['lower'] == .5)
        self.assertEqual(wide['upper'], .7)
        self.assertAlmostEqual(wide['value'], 2 / 3)

    def test_application_is_monotone(self):
        blocks = fit_isotonic(self.SAMPLES)
        grid = [index / 100 for index in range(101)]
        applied = [apply_isotonic(blocks, point) for point in grid]
        self.assertEqual(applied, sorted(applied))

    def test_gaps_and_tails_use_the_nearest_block(self):
        blocks = fit_isotonic(self.SAMPLES)
        self.assertEqual(apply_isotonic(blocks, .35), .5)
        self.assertAlmostEqual(apply_isotonic(blocks, .55), 2 / 3)
        self.assertEqual(apply_isotonic(blocks, .05), 0.0)
        self.assertEqual(apply_isotonic(blocks, .95), 1.0)
        # .25 is equidistant from the .2 block and the .3-.4 block; the tie
        # resolves deterministically to the earlier block.
        self.assertEqual(apply_isotonic(blocks, .25), 0.0)

    def test_fit_is_deterministic_under_input_order(self):
        shuffled = list(self.SAMPLES)
        random.Random(42).shuffle(shuffled)
        self.assertEqual(fit_isotonic(shuffled), fit_isotonic(self.SAMPLES))
        self.assertEqual(map_version(fit_isotonic(shuffled), len(shuffled)),
                         map_version(fit_isotonic(self.SAMPLES), len(self.SAMPLES)))

    def test_empty_map_is_identity(self):
        self.assertEqual(apply_isotonic([], .42), .42)


class RefitGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 2, 15, 0, 0)
        self.config = SimpleNamespace(calibration_json='{}', created_at=self.now - timedelta(days=30))

    def refresh(self, samples):
        with patch('services.portfolio_calibration.calibration_samples', return_value=samples) as query:
            result = maybe_refit_calibration(1, self.config, self.now)
        return result, query

    def test_below_the_minimum_no_map_is_fit(self):
        samples = [(i / 100, i % 2) for i in range(MIN_CALIBRATION_SAMPLES - 1)]
        result, _ = self.refresh(samples)
        self.assertEqual(result['status'], 'AWAITING_SAMPLES')
        self.assertNotIn('blocks', result)
        self.assertEqual(json.loads(self.config.calibration_json)['sample_count'], len(samples))

    def test_single_class_samples_do_not_fit(self):
        result, _ = self.refresh([(.5, 1)] * MIN_CALIBRATION_SAMPLES)
        self.assertEqual(result['status'], 'AWAITING_SAMPLES')

    def test_enough_mixed_samples_fit_a_versioned_map(self):
        samples = [(.2 + (i % 5) * .15, i % 2) for i in range(MIN_CALIBRATION_SAMPLES)]
        result, _ = self.refresh(samples)
        self.assertEqual(result['status'], 'FITTED')
        self.assertEqual(result['sample_count'], MIN_CALIBRATION_SAMPLES)
        self.assertEqual(result['version'], map_version(result['blocks'], len(samples)))
        values = [block['value'] for block in result['blocks']]
        self.assertEqual(values, sorted(values))

    def test_a_fresh_map_is_not_refit(self):
        self.config.calibration_json = json.dumps(
            {'status': 'FITTED', 'fitted_at': (self.now - timedelta(hours=1)).isoformat(), 'blocks': []})
        with patch('services.portfolio_calibration.calibration_samples',
                   side_effect=AssertionError('must not query samples for a fresh map')):
            maybe_refit_calibration(1, self.config, self.now)

    def test_an_awaiting_check_is_throttled(self):
        self.config.calibration_json = json.dumps(
            {'status': 'AWAITING_SAMPLES', 'checked_at': (self.now - timedelta(minutes=30)).isoformat()})
        with patch('services.portfolio_calibration.calibration_samples',
                   side_effect=AssertionError('must not requery within the recheck interval')):
            maybe_refit_calibration(1, self.config, self.now)

    def test_an_old_map_is_refit(self):
        self.config.calibration_json = json.dumps(
            {'status': 'FITTED', 'fitted_at': (self.now - timedelta(hours=7)).isoformat(), 'blocks': []})
        samples = [(.2 + (i % 5) * .15, i % 2) for i in range(MIN_CALIBRATION_SAMPLES)]
        result, query = self.refresh(samples)
        query.assert_called_once()
        self.assertEqual(result['status'], 'FITTED')


class CalibrateMarketTests(unittest.TestCase):
    def setUp(self):
        self.blocks = fit_isotonic([(.2, 0), (.4, 0), (.6, 1), (.8, 1)])
        self.config = SimpleNamespace(calibration_json=json.dumps(
            {'status': 'FITTED', 'version': 'testversion1', 'fitted_at': '2026-11-02T14:00:00',
             'sample_count': 4, 'blocks': self.blocks}))

    def test_the_stamp_archives_version_and_raw_probability(self):
        market = {'model_probability_yes': .65, '_model_metadata': {'status': 'success', 'provider': 'test'}}
        calibrate_market(market, self.config)
        stamp = market['_model_metadata']['calibration']
        self.assertEqual(stamp['version'], 'testversion1')
        self.assertEqual(stamp['raw_probability_yes'], .65)
        self.assertEqual(market['model_probability_yes'], apply_isotonic(self.blocks, .65))
        self.assertEqual(market['_model_metadata']['provider'], 'test')

    def test_recalibration_is_idempotent(self):
        market = {'model_probability_yes': .65, '_model_metadata': {'status': 'success'}}
        calibrate_market(market, self.config)
        first = dict(market['_model_metadata']['calibration'])
        calibrate_market(market, self.config)
        self.assertEqual(market['_model_metadata']['calibration'], first)
        self.assertEqual(market['model_probability_yes'], first['calibrated_probability_yes'])

    def test_without_a_map_the_raw_probability_passes_through(self):
        config = SimpleNamespace(calibration_json='{}')
        market = {'model_probability_yes': .65, '_model_metadata': {'status': 'success'}}
        calibrate_market(market, config)
        self.assertEqual(market['model_probability_yes'], .65)
        self.assertNotIn('calibration', market['_model_metadata'])

    def test_a_market_without_a_prediction_is_untouched(self):
        market = {'_model_metadata': {'status': 'unavailable'}}
        calibrate_market(market, self.config)
        self.assertNotIn('model_probability_yes', market)
        self.assertNotIn('calibration', market['_model_metadata'])


class CalibrationSampleQueryTests(unittest.TestCase):
    """The fit sample comes from verified history through the shared query."""

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from core.extensions import db
        import event_algo_models  # register the event tables
        cls.app = Flask(__name__)
        cls.app.config.update(SECRET_KEY='test-only', TESTING=True,
                              SQLALCHEMY_DATABASE_URI=os.environ['QUANT_TEST_DATABASE_URI'])
        db.init_app(cls.app)
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        from core.extensions import db
        self.context = self.app.app_context()
        self.context.push()
        self.db = db
        self.user_id = int.from_bytes(os.urandom(3), 'big') + 1000000
        self.now = datetime.utcnow()
        from event_algo_models import EventStrategyConfig
        self.config = EventStrategyConfig(user_id=self.user_id, name='Calibration Test',
                                          created_at=self.now - timedelta(days=30))
        db.session.add(self.config)
        db.session.commit()

    def tearDown(self):
        self.db.session.rollback()
        self.db.session.remove()
        self.context.pop()

    def resolved_contract(self, symbol, probability, outcome, *, hours_ago=100,
                          predicted_before_cutoff=True, resolve=True):
        from event_algo_models import EventMarketSnapshot, EventStrategyDecision, EventContractOutcome
        cutoff = self.now - timedelta(hours=hours_ago)
        snapshot = EventMarketSnapshot(user_id=self.user_id, config_id=self.config.id,
                                       contract_symbol=symbol, cutoff_at=cutoff,
                                       yes_bid=.4, yes_ask=.42)
        self.db.session.add(snapshot)
        self.db.session.flush()
        decision = EventStrategyDecision(
            user_id=self.user_id, config_id=self.config.id, snapshot_id=snapshot.id,
            contract_symbol=symbol, action='NO_TRADE', probability_yes=probability,
            created_at=cutoff - timedelta(minutes=10) if predicted_before_cutoff else cutoff + timedelta(minutes=1))
        self.db.session.add(decision)
        if resolve:
            self.db.session.add(EventContractOutcome(
                user_id=self.user_id, config_id=self.config.id, contract_symbol=symbol,
                cutoff_at=cutoff, outcome=outcome, settlement_status='RESOLVED',
                resolved_source='TEST', settlement_at=cutoff + timedelta(minutes=5)))
        self.db.session.commit()

    def test_samples_select_the_earliest_valid_forecast_per_resolved_contract(self):
        from services.portfolio_calibration import calibration_samples
        self.resolved_contract('KXTEST-A', .7, 'YES')
        self.resolved_contract('KXTEST-B', .3, 'NO')
        self.resolved_contract('KXTEST-UNRESOLVED', .5, 'YES', resolve=False)
        self.resolved_contract('KXTEST-POSTCUTOFF', .5, 'YES', predicted_before_cutoff=False)
        # A repeated later forecast for KXTEST-A must not replace the earliest.
        self.resolved_contract('KXTEST-A', .9, 'YES', hours_ago=99)
        samples = dict(calibration_samples(self.user_id, self.config.created_at))
        self.assertEqual(samples, {.7: 1, .3: 0})

    def test_refit_fits_from_verified_history_and_shapes_new_predictions(self):
        from services.event_recalibration import calibration_summary
        for index in range(60):
            self.resolved_contract(f'KXTEST-{index:03d}', .2 + (index % 5) * .15,
                                   'YES' if index % 5 >= 2 else 'NO', hours_ago=100 + index)
        result = maybe_refit_calibration(self.user_id, self.config, self.now)
        self.assertEqual(result['status'], 'FITTED')
        self.assertEqual(result['sample_count'], 60)
        self.assertEqual(calibration_summary(self.config)['version'], result['version'])
        market = {'model_probability_yes': .5, '_model_metadata': {'status': 'success'}}
        calibrate_market(market, self.config)
        stamp = market['_model_metadata']['calibration']
        self.assertEqual(stamp['version'], result['version'])
        self.assertEqual(stamp['raw_probability_yes'], .5)
        self.assertNotEqual(market['model_probability_yes'], .5)


if __name__ == '__main__':
    unittest.main()