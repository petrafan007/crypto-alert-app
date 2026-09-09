import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from core.extensions import db
from portfolio_algo_models import PortfolioMarketObservation as Observation
from services.portfolio_strategy_data import PortfolioMarketData
from services.portfolio_calibration import summarize_event_calibration


class ObservationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        Observation.__table__.create(db.engine)
        self.data = PortfolioMarketData.__new__(PortfolioMarketData)
        self.data.user_id, self.data.cache = 1, {}
        self.now = datetime(2026, 9, 8, 15)

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def test_unverified_history_is_preserved_but_not_used(self):
        for offset in range(1, 8):
            db.session.add(Observation(user_id=1, series='BTC_DOMINANCE', day=self.now.date()-timedelta(days=offset), value=60))
        db.session.commit()
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'data': {'updated_at': self.now.isoformat()+'Z', 'market_cap_percentage': {'btc': 55}}})
        with patch('requests.get', return_value=response):
            with self.assertRaisesRegex(ValueError, '0/7 verified'):
                self.data.dominance_ok('ETH', self.now)
        self.assertEqual(Observation.query.count(), 8)
        self.assertEqual(Observation.query.filter(Observation.source.is_(None)).count(), 7)
        self.assertTrue(self.data.dominance_ok('BTC', self.now))

    def test_verified_days_must_be_the_preceding_seven(self):
        for offset in (1, 2, 3, 4, 5, 6, 8):
            self.data.observe('BTC_DOMINANCE', 60, self.now-timedelta(days=offset), source='COINGECKO_GLOBAL')
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'data': {'updated_at': self.now.isoformat()+'Z', 'market_cap_percentage': {'btc': 55}}})
        with patch('requests.get', return_value=response):
            with self.assertRaisesRegex(ValueError, '6/7 verified'):
                self.data.dominance_ok('SOL', self.now)
            self.data.observe('BTC_DOMINANCE', 60, self.now-timedelta(days=7), source='COINGECKO_GLOBAL')
            self.assertTrue(self.data.dominance_ok('SOL', self.now))

    def test_observation_is_once_per_day_and_user_scoped(self):
        self.data.observe('IV:SPY', .2, self.now, source='WEBULL_OPTION_QUOTES')
        rows = self.data.observe('IV:SPY', .3, self.now, source='WEBULL_OPTION_QUOTES')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value, .3)
        self.assertEqual(rows[0].source, 'WEBULL_OPTION_QUOTES')
        self.data.user_id = 2
        rows = self.data.observe('IV:SPY', .4, self.now, source='WEBULL_OPTION_QUOTES')
        self.assertEqual(len(rows), 1)
        self.assertEqual(Observation.query.count(), 2)


class CalibrationTests(unittest.TestCase):
    def sample(self, contract='A', probability=.8, result='YES', **kwargs):
        return {'contract': contract, 'probability_yes': probability, 'result': result,
                'predicted_at': '2026-09-08T10:00:00Z', 'cutoff_at': '2026-09-08T10:15:00Z',
                'resolved_at': '2026-09-08T10:16:00Z', 'verified_outcome': True,
                'yes_bid': .45, 'yes_ask': .55, **kwargs}

    def test_scores_dedupe_and_include_no_trade_predictions(self):
        result = summarize_event_calibration([self.sample(), self.sample(predicted_at='2026-09-08T10:10:00Z'), self.sample('B', .2, 'NO', eligible=False)])
        self.assertEqual(result['resolved_contracts'], 2)
        self.assertAlmostEqual(result['brier_score'], .04)
        self.assertAlmostEqual(result['market_brier_score'], .25)
        self.assertAlmostEqual(result['skill_score'], .84)
        self.assertAlmostEqual(result['calibration_error'], .2)
        self.assertEqual(result['exclusions']['repeated_contract_forecast'], 1)

    def test_missing_resolution_and_post_cutoff_are_excluded(self):
        result = summarize_event_calibration([self.sample(verified_outcome=False), self.sample('B', predicted_at='2026-09-08T10:16:00Z')])
        self.assertIsNone(result['brier_score'])
        self.assertEqual(result['resolved_contracts'], 0)

    def test_market_skill_uses_only_matching_observations(self):
        result = summarize_event_calibration([self.sample(), self.sample('B', 0, 'YES', yes_bid=None)])
        self.assertAlmostEqual(result['brier_score'], .52)
        self.assertAlmostEqual(result['skill_score'], .84)
        self.assertEqual(result['market_comparison_contracts'], 1)
