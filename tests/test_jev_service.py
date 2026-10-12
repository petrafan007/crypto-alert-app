import copy
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock, patch
import requests
from services.jev_contracts import build_sentiment_questions
from services.jev_service import JevClient, JevError, validate_answers
from tests.jev_helpers import response_for


class JevServiceTests(TestCase):
    def setUp(self):
        JevClient._failures.clear()
        self.questions = build_sentiment_questions()
        self.payload = response_for(self.questions)
        self.client = JevClient('never-print-this-key')

    def test_native_boolean_choice_score_and_cost(self):
        with patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: self.payload)) as post:
            result = self.client.evaluate(state={'asset': 'BTC'}, questions=self.questions)
        self.assertEqual(result.answers['direction']['choice'], 'bullish')
        self.assertEqual(result.answers['materiality']['score'], 3)
        self.assertEqual(result.answers['bullish']['probability'], .85)
        self.assertEqual(result.estimated_cost_usd, Decimal('0.000001'))
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertEqual(len(post.call_args.kwargs['json']['questions']), 6)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_rejects_missing_invalid_and_nonfinite_answers(self):
        invalid = []
        item = copy.deepcopy(self.payload); del item['answers']['bullish']; invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['bullish']['probability'] = float('nan'); invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['direction']['choice'] = 'invented'; invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['materiality']['score'] = 5; invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['direction']['probabilities']['bullish'] = .4; invalid.append(item)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(JevError):
                validate_answers(item, self.questions)

    def test_malformed_json_never_retried(self):
        with patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=Mock(side_effect=ValueError('never-print-this-key')))) as post:
            with self.assertRaises(JevError) as caught:
                self.client.evaluate(state={}, questions=self.questions)
            self.assertEqual(caught.exception.code, 'invalid_response')
            self.assertNotIn('never-print-this-key', str(caught.exception))
            self.assertEqual(post.call_count, 1)

    def test_rate_limit_retries_once_and_auth_never_retries(self):
        for status, expected in [(429, 2), (401, 1), (403, 1), (400, 1), (302, 1)]:
            JevClient._failures.clear()
            with patch('services.jev_service.requests.post', return_value=Mock(status_code=status, text='never-print-this-key')) as post, patch('services.jev_service.time.sleep'):
                with self.assertRaises(JevError) as caught:
                    self.client.evaluate(state={}, questions=self.questions)
                self.assertEqual(post.call_count, expected)
                self.assertNotIn('never-print-this-key', str(caught.exception))

    def test_timeout_and_circuit_breaker_are_bounded(self):
        with patch('services.jev_service.requests.post', side_effect=requests.Timeout('never-print-this-key')) as post, patch('services.jev_service.time.sleep'):
            for _ in range(3):
                with self.assertRaises(JevError) as caught:
                    self.client.evaluate(state={}, questions=self.questions)
                self.assertEqual(caught.exception.code, 'timeout')
            with self.assertRaises(JevError) as caught:
                self.client.evaluate(state={}, questions=self.questions)
            self.assertEqual(caught.exception.code, 'cooldown')
            self.assertEqual(post.call_count, 6)

    def test_unapproved_destination_rejected_before_network(self):
        with self.assertRaises(ValueError):
            JevClient('saved-key', endpoint='http://127.0.0.1/private')

    def test_openrouter_native_decisions_normalizes_noul_and_preserves_confidence_cost(self):
        payload = copy.deepcopy(self.payload)
        payload['model'] = 'typesafe/jev-1.13-20260917'
        payload['usage'] = {'input_tokens': 123, 'output_tokens': 4, 'cost': .00001}
        for key, answer in payload['answers'].items():
            if answer['type'] == 'boolean':
                payload['answers'][key] = {'type': 'noul', 'noul': answer['probability']}
            else:
                answer['confidence'] = .87
        client = JevClient('openrouter-test-key', transport='openrouter')
        with patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: payload)) as post:
            result = client.evaluate(state={'asset': 'BTC'}, questions=self.questions)
        self.assertEqual(post.call_args.args[0], 'https://openrouter.ai/api/alpha/decisions')
        request = post.call_args.kwargs['json']
        self.assertNotIn('messages', request)
        self.assertEqual(request['model'], 'typesafe/jev-1.13')
        self.assertEqual(request['questions']['bullish']['type'], 'noul')
        self.assertEqual(result.answers['bullish']['probability'], .85)
        self.assertEqual(result.confidence['direction'], .87)
        self.assertEqual(result.estimated_cost_usd, Decimal('0.00001'))

    def test_subq_decisions_api_converts_noul_and_preserves_typed_answers(self):
        answers = {}
        for key, answer in self.payload['answers'].items():
            question = self.questions[key]
            if question['type'] == 'boolean':
                answers[key] = {'type': 'noul', 'noul': answer['probability']}
            else:
                answers[key] = {**answer, 'confidence': .91}
                if question['type'] == 'score':
                    answers[key]['legend'] = {str(index): str(level)
                                              for index, level in enumerate(question['criteria'])}
        payload = {'model': 'subq-snap-preview', 'answers': answers,
                   'usage': {'input_tokens': 123, 'output_tokens': 0}}
        client = JevClient('subq-test-key', transport='subq')
        with patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: payload)) as post:
            result = client.evaluate(state={'asset': 'BTC'}, questions=self.questions)

        self.assertEqual(post.call_args.args[0], 'https://api.subq.ai/v1/systemone')
        request = post.call_args.kwargs['json']
        self.assertEqual(request['model'], 'subq-snap-preview')
        self.assertEqual(request['questions']['bullish']['type'], 'noul')
        self.assertNotIn('providerOptions', request)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer subq-test-key')
        self.assertEqual(result.answers['bullish'], {'type': 'boolean', 'probability': .85})
        self.assertEqual(result.answers['direction']['choice'], 'bullish')
        self.assertEqual(result.confidence['direction'], .91)
        self.assertEqual(result.provider, 'SubQ')
        self.assertEqual(result.transport, 'subq')
        self.assertEqual(result.usage['input_tokens'], 123)
        self.assertIsNone(result.estimated_cost_usd)

    def test_subq_rejects_model_override_before_network_request(self):
        client = JevClient('subq-test-key', transport='subq')
        with patch('services.jev_service.requests.post') as post:
            with self.assertRaisesRegex(ValueError, 'configured decision model'):
                client.evaluate(state={}, questions=self.questions, model='unsupported-model')
        post.assert_not_called()

    def test_subq_rejects_malformed_noul_and_missing_confidence(self):
        malformed = copy.deepcopy(self.payload)
        malformed['model'] = 'subq-snap-preview'
        malformed['answers']['bullish'] = {'type': 'boolean', 'probability': .85}
        missing_confidence = copy.deepcopy(self.payload)
        missing_confidence['model'] = 'subq-snap-preview'
        for key, answer in missing_confidence['answers'].items():
            if self.questions[key]['type'] == 'boolean':
                missing_confidence['answers'][key] = {'type': 'noul', 'noul': answer['probability']}
        payloads = (malformed, missing_confidence)
        for payload in payloads:
            with self.subTest(payload=payload), patch(
                'services.jev_service.requests.post',
                return_value=Mock(status_code=200, json=lambda: payload),
            ):
                with self.assertRaises(JevError) as caught:
                    JevClient('subq-test-key', transport='subq').evaluate(state={}, questions=self.questions)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_request_budget_hook_counts_each_transport_attempt_and_can_stop_retry(self):
        before = Mock(side_effect=[None, ValueError('request budget exhausted')])
        with patch('services.jev_service.requests.post', return_value=Mock(status_code=429)) as post, \
                patch('services.jev_service.time.sleep'):
            with self.assertRaisesRegex(ValueError, 'budget exhausted'):
                self.client.evaluate(state={}, questions=self.questions, before_request=before)
        self.assertEqual(before.call_count, 2)
        post.assert_called_once()
