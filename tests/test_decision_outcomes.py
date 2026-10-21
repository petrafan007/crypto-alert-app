from datetime import timedelta
import json
from core.extensions import db
from models import PriceHistory
from services.decision_evaluations import create_evaluation, update_evaluation, get_evaluation
from services.decision_outcomes import evaluate_pending_outcomes, calibration, telemetry
from services.decision_contracts import build_sentiment_questions
from services.decision_quant import build_state
from tests.decision_helpers import DecisionTestCase, response_for


class DecisionOutcomeTests(DecisionTestCase):
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

    def test_telemetry_scoped_to_user_and_reports_each_provider_model(self):
        evaluation_id = self.evaluation()
        from services.decision_evaluations import update_evaluation
        update_evaluation(evaluation_id, provider='SubQ', model='subq-snap-preview')
        self.assertEqual(telemetry(2)['sample_count'], 0)
        result = telemetry(1)
        self.assertEqual(result['sample_count'], 1)
        self.assertEqual(result['recent'][0]['provider'], 'SubQ')
        self.assertEqual(result['recent'][0]['model'], 'subq-snap-preview')
        self.assertIsNone(result['reported_cost_usd'])
        self.assertNotIn('synthetic-decision-secret', str(result))


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
        from services.decision_contracts import build_crypto_quant_questions
        first = build_state('BTC', 100, {'enter': True}, self.now-timedelta(hours=25))
        evaluation_id = create_evaluation(1, 'quant_crypto', first, self.config)
        update_evaluation(evaluation_id, status='success', answers_json=json.dumps(response_for(build_crypto_quant_questions())['answers']))
        db.session.add(PriceHistory(symbol='BTC', price=900,
            timestamp=int((self.now-timedelta(hours=1)).timestamp()), exchange='binance'))
        db.session.commit()
        self.assertEqual(evaluate_pending_outcomes(self.now), 0)
        later = build_state('BTC', 105, {'enter': False}, self.now-timedelta(hours=1))
        create_evaluation(1, 'quant_crypto', later, self.config)
        self.assertEqual(evaluate_pending_outcomes(self.now), 1)
        self.assertAlmostEqual(get_evaluation(evaluation_id).outcome_return_pct, 5)
