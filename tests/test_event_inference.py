"""No model credits for excluded markets; bounded complete model output."""
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from event_algo import _predict_event_markets_batch, evaluate_market
from services.event_inference import inference_preflight, strict_batch_predictions


class EventInferenceTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('services.jev_event.evaluator_for', return_value='generative')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = datetime.utcnow()
        self.config = SimpleNamespace(id=1, enabled=True, kill_switch=False, risk_config='{}', signal_config='{}')
        self.market = {'symbol': 'TEST', 'yes_bid': .39, 'yes_ask': .4, 'no_bid': .59, 'no_ask': .6,
                       'quote_as_of': self.now.isoformat(), 'tradable_status': 'OC',
                       'cutoff_at': (self.now+timedelta(minutes=10)).isoformat()}

    def test_scope_and_known_execution_gates_exclude_before_inference(self):
        for fields, reason in [
            ({'cutoff_at': (self.now+timedelta(days=2)).isoformat()}, 'TOO_FAR_FROM_EXPIRATION'),
            ({'cutoff_at': (self.now+timedelta(seconds=10)).isoformat()}, 'TOO_CLOSE_TO_EXPIRATION'),
            ({'cutoff_at': (self.now-timedelta(seconds=1)).isoformat()}, 'CONTRACT_EXPIRED'),
            ({'cutoff_at': None}, 'DATA_ERROR'),
            ({'tradable_status': 'CO'}, 'MARKET_NOT_OPEN'),
            ({'tradable_status': 'NT'}, 'MARKET_STATUS_UNKNOWN'),
            ({'quote_as_of': (self.now-timedelta(seconds=31)).isoformat()}, 'STALE_QUOTE'),
            ({'yes_bid': None, 'no_bid': None}, 'MISSING_QUOTE'),
            ({'yes_bid': .5, 'no_bid': .7}, 'CROSSED_QUOTE'),
            ({'yes_bid': .1, 'no_bid': .1}, 'SPREAD_TOO_WIDE'),
            ({'yes_ask_size': 0, 'no_ask_size': 0}, 'INSUFFICIENT_LIQUIDITY')]:
            with self.subTest(reason=reason):
                self.assertIn(reason, inference_preflight({**self.market, **fields}, self.config, self.now))
        self.config.kill_switch = True
        self.assertIn('KILL_SWITCH', inference_preflight(self.market, self.config, self.now))

    def test_one_usable_book_is_enough_and_probes_never_mutate_the_market(self):
        market = {**self.market, 'no_bid': None, 'no_ask': None}
        before = dict(market)
        self.assertEqual(inference_preflight(market, self.config, self.now), [])
        self.assertEqual(market, before)
        self.config.risk_config = '{"min_volume": 100}'
        self.assertIn('INSUFFICIENT_LIQUIDITY', inference_preflight(market, self.config, self.now))

    def test_excluded_contracts_never_call_ai_and_remain_auditable(self):
        market = {**self.market, 'cutoff_at': (self.now+timedelta(days=2)).isoformat()}
        with patch('event_algo.User') as users, \
             patch('services.analysis_service.is_ai_enabled', return_value=True), \
             patch('services.ai_service.call_ai_with_web_search') as ai:
            users.query.filter_by.return_value.first.return_value = SimpleNamespace(username='admin')
            result = _predict_event_markets_batch(1, [market], config=self.config)['TEST']
        ai.assert_not_called()
        market['_model_metadata'] = result['metadata']
        decision = evaluate_market(market, self.config, now=self.now)
        self.assertIn('TOO_FAR_FROM_EXPIRATION', decision['reason_codes'])
        self.assertIn('AI_NOT_REQUIRED', decision['reason_codes'])
        self.assertNotIn('MODEL_UNAVAILABLE', decision['reason_codes'])
        self.assertFalse(decision['eligible'])

    def test_batch_output_requires_all_exact_symbols_and_complete_valid_values(self):
        rows = [{'contract_symbol': s, 'probability_yes': .5, 'confidence': .0,
                 'rationale': 'Missing observations.'} for s in ('A', 'B')]
        valid = json.dumps({'predictions': rows})
        self.assertEqual(set(strict_batch_predictions(valid, ['A', 'B'])), {'A', 'B'})
        self.assertEqual(set(strict_batch_predictions('```json\n'+valid+'\n```', ['A', 'B'])), {'A', 'B'})
        self.assertEqual(strict_batch_predictions(valid[:-2], ['A', 'B']), {})
        self.assertEqual(strict_batch_predictions(valid.replace('observations.', r'S\&P.'), ['A', 'B']), {})
        for changed in ([rows[0]], [rows[0], rows[0]], [rows[0], {**rows[1], 'contract_symbol': 'WRONG'}]):
            self.assertEqual(strict_batch_predictions(json.dumps({'predictions': changed}), ['A', 'B']), {})
        for value in (True, '0.5', 50, -1, float('nan'), float('inf'), None):
            self.assertEqual(strict_batch_predictions(json.dumps({'predictions': [rows[0], {**rows[1], 'probability_yes': value}]}), ['A', 'B']), {})
        duplicate = valid.replace('"confidence": 0.0', '"confidence": 0.0, "confidence": 0.9')
        self.assertEqual(strict_batch_predictions(duplicate, ['A', 'B']), {})

    def test_contract_questions_use_typed_outcomes_and_explicit_evidence(self):
        from services.jev_event import build_questions
        questions = build_questions([self.market])
        self.assertEqual(questions['c0_outcome']['type'], 'choice')
        self.assertEqual(set(questions['c0_outcome']['criteria']), {'YES', 'NO'})
        self.assertIn('contracts[0] (TEST)', questions['c0_outcome']['instructions'])
        self.assertIn('Missing, stale', questions['c0_evidence']['instructions'])

    def test_zero_confidence_placeholder_never_enters_even_with_zero_threshold(self):
        self.config.signal_config = '{"min_confidence": 0}'
        result = evaluate_market({**self.market, 'model_probability_yes': .8,
                                  'model_confidence': 0}, self.config, now=self.now)
        self.assertFalse(result['eligible'])
        self.assertIn('CONFIDENCE_TOO_LOW', result['reason_codes'])

    def test_prediction_batches_are_small_and_use_jev_only(self):
        batches = []
        def respond(user_id, markets, config, guard):
            guard()
            batches.append([m['symbol'] for m in markets])
            return {m['symbol']: {'model_probability_yes': .5, 'model_confidence': 0,
                'metadata': {'status': 'success', 'tier': 'jev'}} for m in markets}
        markets = [{**self.market, 'symbol': symbol} for symbol in ('A', 'B', 'C')]
        with patch('event_algo.User') as users, \
             patch('services.analysis_service.is_ai_enabled', return_value=True), \
             patch('services.event_runtime.event_request_guard', return_value=lambda: None), \
             patch('services.jev_event.predict', side_effect=respond), \
             patch('services.ai_service.call_ai_with_web_search') as generative:
            users.query.filter_by.return_value.first.return_value = SimpleNamespace(username='admin')
            result = _predict_event_markets_batch(1, markets, config=self.config)
        self.assertEqual(batches, [['A', 'B'], ['C']])
        self.assertTrue(all(row['model_confidence'] == 0 for row in result.values()))
        generative.assert_not_called()

    def test_entry_window_is_rechecked_before_a_queued_provider_attempt(self):
        market = dict(self.market)
        def queue_wait(user_id, markets, config, guard):
            market['cutoff_at'] = (self.now-timedelta(seconds=1)).isoformat()
            guard()
            self.fail('An expired contract reached the provider')
        with patch('event_algo.User') as users, \
             patch('services.analysis_service.is_ai_enabled', return_value=True), \
             patch('services.event_runtime.event_request_guard', return_value=lambda: None), \
             patch('services.jev_event.predict', side_effect=queue_wait):
            users.query.filter_by.return_value.first.return_value = SimpleNamespace(username='admin')
            result = _predict_event_markets_batch(1, [market], config=self.config)['TEST']
        self.assertEqual(result['metadata']['deferral_reason'], 'ENTRY_WINDOW_CHANGED')
        self.assertNotIn('model_probability_yes', result)
