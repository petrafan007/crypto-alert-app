import copy
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from event_algo import _predict_event_markets_batch, _event_market_fingerprint
from services.decision_event import build_questions, evaluator_for, predict
from services.decision_engine import DecisionError
from services.decision_settings import DEFAULTS, INCEPTION_DECISIONS_MODEL, SUBQ_MODEL


class DecisionEventTests(TestCase):
    def setUp(self):
        self.market = {'symbol': 'TEST', 'yes_bid': .39, 'yes_ask': .4, 'no_bid': .59, 'no_ask': .6,
            'quote_as_of': datetime.utcnow().isoformat(), 'tradable_status': 'OC',
            'cutoff_at': (datetime.utcnow() + timedelta(minutes=10)).isoformat()}
        self.config = SimpleNamespace(id=9, user_id=1, enabled=True, kill_switch=False,
                                      signal_config='{}', risk_config='{}')
        self.settings = SimpleNamespace(**{**DEFAULTS, 'decision_enabled': True, 'decision_transport': 'inception'})
        self.result = SimpleNamespace(
            answers={
                'c0_outcome': {'type': 'choice', 'choice': 'YES', 'probabilities': {'YES': .85, 'NO': .15}},
                'c0_evidence': {'type': 'choice', 'choice': 'usable', 'probabilities': {'usable': .9, 'missing': .05, 'conflicted': .05}},
            }, confidence={'c0_outcome': .9}, model=INCEPTION_DECISIONS_MODEL,
            provider='Inception', transport='inception',
            latency_ms=45, usage={'input_tokens': 150}, estimated_cost_usd=Decimal('0.000001'))

    def run_prediction(self, result=None, error=None):
        order = []
        with patch('services.decision_event.db') as database, \
                patch('services.decision_event.Credential') as credentials, \
                patch('services.decision_event.DecisionClient') as client, \
                patch('services.event_runtime.reserve_provider_call', side_effect=lambda _: order.append('reserve')) as reserve:
            database.session.get.return_value = self.settings
            database.session.commit.side_effect = lambda: order.append('commit')
            credentials.query.filter_by.return_value.first.return_value = SimpleNamespace(
                openrouter_api_key='openrouter-test', ai_gateway_key='vercel-test',
                subq_api_key='subq-test', inception_decisions_key='inception-test')
            def evaluate(**kwargs):
                kwargs['before_request']()
                order.append('request')
                if error:
                    raise error
                return result or self.result
            client.return_value.evaluate.side_effect = evaluate
            actual = predict(1, [self.market], self.config, lambda: order.append('guard'))
            args = client.call_args_list[0] if client.call_args_list else None
        return actual['TEST'], args, order, reserve.call_count

    def test_native_prediction_reuses_saved_decision_key_and_records_usage(self):
        result, args, order, calls = self.run_prediction()
        self.assertEqual(args.args[0], 'inception-test')
        self.assertEqual(args.args[1], 'https://api.inceptionlabs.ai/v1/decisions')
        self.assertEqual(args.args[2], INCEPTION_DECISIONS_MODEL)
        self.assertEqual(order, ['commit', 'guard', 'reserve', 'request', 'guard'])
        self.assertEqual(calls, 1)
        self.assertEqual(result['model_probability_yes'], .85)
        self.assertEqual(result['model_confidence'], .9)
        self.assertEqual(result['metadata']['estimated_cost_usd'], '0.000001')
        self.assertFalse(result['metadata']['generative_fallback'])

    def test_subq_provider_uses_its_saved_key_and_pinned_model_for_event_decisions(self):
        self.settings.decision_transport = 'subq'
        result, args, _, _ = self.run_prediction()
        self.assertEqual(args.args[0], 'subq-test')
        self.assertEqual(args.args[1], 'https://api.subq.ai/v1/systemone')
        self.assertEqual(args.args[2], SUBQ_MODEL)
        self.assertEqual(args.kwargs['transport'], 'subq')
        # The transport that answered is recorded, so a decision is attributable.
        self.assertEqual(result['metadata']['transport'], 'inception')

    def test_missing_low_confidence_or_weak_evidence_never_authorizes_entry(self):
        for field in ('missing_confidence', 'low_confidence', 'missing_evidence', 'low_evidence_probability'):
            value = copy.deepcopy(self.result)
            if field == 'missing_confidence':
                value.confidence = {}
            elif field == 'low_confidence':
                value.confidence['c0_outcome'] = .7
            elif field == 'missing_evidence':
                value.answers['c0_evidence']['choice'] = 'missing'
            else:
                value.answers['c0_evidence']['probabilities']['usable'] = .7
            with self.subTest(field=field):
                result, _, _, _ = self.run_prediction(value)
                self.assertEqual(result['model_confidence'], 0)
                self.assertTrue(result['metadata']['abstained'])

    def test_decision_failure_is_redacted_and_never_escalates_to_generative_ai(self):
        with patch('services.ai_service.call_ai_with_web_search') as generative:
            result, _, _, _ = self.run_prediction(error=DecisionError('auth'))
        self.assertEqual(result['metadata']['status'], 'error')
        self.assertEqual(result['metadata']['error_code'], 'auth')
        self.assertNotIn('inception-test', str(result))
        generative.assert_not_called()

    def test_disabled_decision_engine_makes_no_request_and_no_fallback(self):
        self.settings.decision_enabled = False
        result, args, order, calls = self.run_prediction()
        self.assertIsNone(args)
        self.assertEqual(calls, 0)
        self.assertEqual(order, ['commit'])
        self.assertEqual(result['metadata']['deferral_reason'], 'DECISION_DISABLED')

    def test_oversized_batch_rejected_before_query_or_transport(self):
        with patch('services.decision_event.db') as database:
            with self.assertRaises(ValueError):
                predict(1, [self.market] * 3, self.config, Mock())
        database.session.get.assert_not_called()

    def test_questions_bind_each_contract_exactly(self):
        questions = build_questions([self.market, {**self.market, 'symbol': 'OTHER'}])
        self.assertEqual(len(questions), 4)
        self.assertIn('contracts[1] (OTHER)', questions['c1_outcome']['instructions'])
        self.assertEqual(set(questions['c0_outcome']['criteria']), {'YES', 'NO'})

    def test_batch_decision_mode_never_calls_the_configured_cascade(self):
        with patch('event_algo.User') as users, \
                patch('services.analysis_service.is_ai_enabled', return_value=True), \
                patch('services.decision_event.evaluator_for', return_value='decision'), \
                patch('services.decision_event.predict', return_value={'TEST': {'metadata': {'tier': 'decision'}}}) as decision, \
                patch('services.event_runtime.event_request_guard', return_value=Mock()), \
                patch('services.ai_service.call_ai_with_web_search') as generative:
            users.query.filter_by.return_value.first.return_value = SimpleNamespace(username='admin')
            result = _predict_event_markets_batch(1, [self.market], config=self.config)
        self.assertEqual(result['TEST']['metadata']['tier'], 'decision')
        decision.assert_called_once()
        generative.assert_not_called()

    def test_closed_contract_never_calls_the_decision_engine(self):
        with patch('event_algo.User') as users, \
                patch('services.analysis_service.is_ai_enabled', return_value=True), \
                patch('services.decision_event.evaluator_for', return_value='decision'), \
                patch('services.decision_event.predict') as decision:
            users.query.filter_by.return_value.first.return_value = SimpleNamespace(username='admin')
            result = _predict_event_markets_batch(1, [{**self.market, 'tradable_status': 'CO'}], config=self.config)
        decision.assert_not_called()
        self.assertEqual(result['TEST']['metadata']['status'], 'skipped')

    def test_switching_evaluator_invalidates_forecast_cache_without_deleting_history(self):
        original = _event_market_fingerprint({**self.market, '_event_forecast_identity': ['generative']})
        changed = _event_market_fingerprint({**self.market, '_event_forecast_identity': ['decision']})
        self.assertNotEqual(original, changed)

    def test_legacy_cascade_setting_cannot_route_contract_probabilities_to_llms(self):
        # The evaluator is fixed: contract probabilities always go to the
        # Decision Engine, so a saved generative cascade cannot be consulted.
        self.assertEqual(evaluator_for(1), 'decision')
        with patch('services.ai_service.call_ai_with_web_search') as generative:
            result, _, _, _ = self.run_prediction()
        self.assertEqual(result['metadata']['status'], 'success')
        generative.assert_not_called()
