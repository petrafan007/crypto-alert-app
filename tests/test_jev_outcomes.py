from datetime import timedelta
import json
from core.extensions import db
from models import PriceHistory
from services.jev_evaluations import create_evaluation, update_evaluation, get_evaluation
from services.jev_outcomes import evaluate_pending_outcomes, calibration, telemetry
from services.jev_contracts import build_sentiment_questions
from tests.jev_helpers import JevTestCase, response_for


class JevOutcomeTests(JevTestCase):
    def evaluation(self):
        state = dict(self.state, decision_time=(self.now-timedelta(hours=25)).isoformat())
        evaluation_id = create_evaluation(1, 'sentiment', state, self.config)
        update_evaluation(evaluation_id, status='success', answers_json=json.dumps(response_for(build_sentiment_questions())['answers']))
        return evaluation_id

    def test_grades_fixed_horizon_and_computes_calibration(self):
        evaluation_id = self.evaluation()
        target = self.now-timedelta(hours=1)
        db.session.add(PriceHistory(symbol='BTC', price=103, timestamp=int(target.timestamp()), exchange='binance'))
        db.session.commit()
        self.assertEqual(evaluate_pending_outcomes(self.now), 1)
        row = get_evaluation(evaluation_id)
        self.assertAlmostEqual(row.outcome_return_pct, 3)
        group = next(iter(calibration([row]).values()))
        self.assertAlmostEqual(group['questions']['bullish']['brier'], .15**2)
        self.assertEqual(evaluate_pending_outcomes(self.now), 0)
        self.assertIsNone(row.max_favorable_excursion_pct)

    def test_missing_or_future_prices_remain_unscored(self):
        evaluation_id = self.evaluation()
        db.session.add(PriceHistory(symbol='BTC', price=103, timestamp=int((self.now+timedelta(hours=1)).timestamp()), exchange='binance'))
        db.session.commit()
        self.assertEqual(evaluate_pending_outcomes(self.now), 0)
        self.assertIsNone(get_evaluation(evaluation_id).outcome_return_pct)

    def test_telemetry_scoped_to_user_and_missing_cost_not_free(self):
        self.evaluation()
        self.assertEqual(telemetry(2)['sample_count'], 0)
        self.assertEqual(telemetry(1)['sample_count'], 1)
        self.assertIsNone(telemetry(1)['reported_cost_usd'])
        self.assertNotIn('synthetic-jev-secret', str(telemetry(1)))


    def test_missing_old_price_does_not_starve_newer_outcomes(self):
        self.evaluation()  # BTC is intentionally missing a price.
        self.state['symbol'] = 'ETH'
        evaluation_id = self.evaluation()
        db.session.add(PriceHistory(symbol='ETH', price=102,
            timestamp=int((self.now-timedelta(hours=1)).timestamp()), exchange='binance'))
        db.session.commit()
        self.assertEqual(evaluate_pending_outcomes(self.now, limit=1), 0)
        self.assertEqual(evaluate_pending_outcomes(self.now, limit=1), 1)
        self.assertAlmostEqual(get_evaluation(evaluation_id).outcome_return_pct, 2)

    def test_quant_uses_same_source_future_observation_not_binance(self):
        from services.jev_quant_overlay import build_quant_state
        from services.jev_contracts import build_crypto_quant_questions
        first = build_quant_state('BTC', 100, {'enter': True}, self.now-timedelta(hours=25))
        evaluation_id = create_evaluation(1, 'quant_crypto', first, self.config)
        update_evaluation(evaluation_id, status='success', answers_json=json.dumps(response_for(build_crypto_quant_questions())['answers']))
        db.session.add(PriceHistory(symbol='BTC', price=900,
            timestamp=int((self.now-timedelta(hours=1)).timestamp()), exchange='binance'))
        db.session.commit()
        self.assertEqual(evaluate_pending_outcomes(self.now), 0)
        later = build_quant_state('BTC', 105, {'enter': False}, self.now-timedelta(hours=1))
        create_evaluation(1, 'quant_crypto', later, self.config)
        self.assertEqual(evaluate_pending_outcomes(self.now), 1)
        self.assertAlmostEqual(get_evaluation(evaluation_id).outcome_return_pct, 5)
