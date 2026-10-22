import copy
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock, patch
import requests
from services.decision_contracts import build_sentiment_questions
from services.decision_engine import DecisionClient, DecisionError, validate_answers
from services.decision_settings import INCEPTION_DECISIONS_ENDPOINT, INCEPTION_DECISIONS_MODEL, SUBQ_ENDPOINT, SUBQ_MODEL
from tests.decision_helpers import noul_payload, response_for


class DecisionEngineTests(TestCase):
    def setUp(self):
        DecisionClient._failures.clear()
        self.questions = build_sentiment_questions()
        self.payload = noul_payload(self.questions)
        self.client = DecisionClient('never-print-this-key')

    def test_native_boolean_choice_score_and_cost(self):
        with patch('services.decision_engine.requests.post', return_value=Mock(status_code=200, json=lambda: self.payload)) as post:
            result = self.client.evaluate(state={'asset': 'BTC'}, questions=self.questions)
        self.assertEqual(result.answers['direction']['choice'], 'bullish')
        self.assertEqual(result.answers['materiality']['score'], 3)
        self.assertEqual(result.answers['bullish']['probability'], .85)
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertEqual(len(post.call_args.kwargs['json']['questions']), 6)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_rejects_missing_invalid_and_nonfinite_answers(self):
        invalid = []
        item = copy.deepcopy(self.payload); del item['answers']['bullish']; invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['bullish']['noul'] = float('nan'); invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['direction']['choice'] = 'invented'; invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['materiality']['score'] = 5; invalid.append(item)
        item = copy.deepcopy(self.payload); item['answers']['direction']['probabilities']['bullish'] = .4; invalid.append(item)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(DecisionError):
                validate_answers(item, self.questions)

    def test_malformed_json_never_retried(self):
        with patch('services.decision_engine.requests.post', return_value=Mock(status_code=200, json=Mock(side_effect=ValueError('never-print-this-key')))) as post:
            with self.assertRaises(DecisionError) as caught:
                self.client.evaluate(state={}, questions=self.questions)
            self.assertEqual(caught.exception.code, 'invalid_response')
            self.assertNotIn('never-print-this-key', str(caught.exception))
            self.assertEqual(post.call_count, 1)

    def test_rate_limit_retries_once_and_auth_never_retries(self):
        for status, expected in [(429, 2), (401, 1), (403, 1), (400, 1), (302, 1)]:
            DecisionClient._failures.clear()
            with patch('services.decision_engine.requests.post', return_value=Mock(status_code=status, text='never-print-this-key')) as post, patch('services.decision_engine.time.sleep'):
                with self.assertRaises(DecisionError) as caught:
                    self.client.evaluate(state={}, questions=self.questions)
                self.assertEqual(post.call_count, expected)
                self.assertNotIn('never-print-this-key', str(caught.exception))

    def test_timeout_and_circuit_breaker_are_bounded(self):
        with patch('services.decision_engine.requests.post', side_effect=requests.Timeout('never-print-this-key')) as post, patch('services.decision_engine.time.sleep'):
            for _ in range(3):
                with self.assertRaises(DecisionError) as caught:
                    self.client.evaluate(state={}, questions=self.questions)
                self.assertEqual(caught.exception.code, 'timeout')
            with self.assertRaises(DecisionError) as caught:
                self.client.evaluate(state={}, questions=self.questions)
            self.assertEqual(caught.exception.code, 'cooldown')
            self.assertEqual(post.call_count, 6)

    def test_unapproved_destination_rejected_before_network(self):
        # The transport pins the endpoint, and the endpoint allowlist rejects
        # anything that is not an operator-approved HTTPS decisions endpoint.
        from services.decision_settings import validate_endpoint
        with self.assertRaises(ValueError):
            validate_endpoint('http://127.0.0.1/private')
        with self.assertRaises(ValueError):
            validate_endpoint('https://attacker.example/decisions')
        # A client can never be pointed at an unapproved destination.
        client = DecisionClient('saved-key', endpoint='http://127.0.0.1/private', transport='subq')
        self.assertEqual(client.endpoint, SUBQ_ENDPOINT)

    def test_inception_decisions_api_normalizes_noul_and_preserves_confidence(self):
        payload = copy.deepcopy(self.payload)
        payload['model'] = INCEPTION_DECISIONS_MODEL
        payload['usage'] = {'input_tokens': 123, 'output_tokens': 4, 'cost': .00001}
        for key, answer in payload['answers'].items():
            if answer['type'] != 'noul':
                answer['confidence'] = .87
        client = DecisionClient('inception-test-key', transport='inception')
        with patch('services.decision_engine.requests.post', return_value=Mock(status_code=200, json=lambda: payload)) as post:
            result = client.evaluate(state={'asset': 'BTC'}, questions=self.questions)
        self.assertEqual(post.call_args.args[0], INCEPTION_DECISIONS_ENDPOINT)
        request = post.call_args.kwargs['json']
        self.assertNotIn('messages', request)
        self.assertEqual(request['model'], INCEPTION_DECISIONS_MODEL)
        self.assertEqual(request['questions']['bullish']['type'], 'noul')
        self.assertEqual(result.answers['bullish']['probability'], .85)
        self.assertEqual(result.confidence['direction'], .87)
        # The provider-neutral client reports the usage it was given; it never
        # derives a cost the provider did not report.
        self.assertEqual(result.usage['input_tokens'], 123)
        self.assertIsNone(result.estimated_cost_usd)
        self.assertEqual(result.provider, 'Inception')
        self.assertEqual(result.transport, 'inception')

    def test_subq_decisions_api_converts_noul_and_preserves_typed_answers(self):
        payload = {'model': SUBQ_MODEL, 'answers': self.payload['answers'],
                   'usage': {'input_tokens': 123, 'output_tokens': 0}}
        client = DecisionClient('subq-test-key', transport='subq')
        with patch('services.decision_engine.requests.post', return_value=Mock(status_code=200, json=lambda: payload)) as post:
            result = client.evaluate(state={'asset': 'BTC'}, questions=self.questions)

        self.assertEqual(post.call_args.args[0], SUBQ_ENDPOINT)
        request = post.call_args.kwargs['json']
        self.assertEqual(request['model'], SUBQ_MODEL)
        self.assertEqual(request['questions']['bullish']['type'], 'noul')
        self.assertNotIn('providerOptions', request)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer subq-test-key')
        self.assertEqual(result.answers['bullish'], {'type': 'boolean', 'probability': .85})
        self.assertEqual(result.answers['direction']['choice'], 'bullish')
        self.assertEqual(result.confidence['direction'], .95)
        self.assertEqual(result.provider, 'SubQ')
        self.assertEqual(result.transport, 'subq')
        self.assertEqual(result.usage['input_tokens'], 123)
        self.assertIsNone(result.estimated_cost_usd)

    def test_subq_rejects_model_override_before_network_request(self):
        client = DecisionClient('subq-test-key', transport='subq')
        with patch('services.decision_engine.requests.post') as post:
            with self.assertRaisesRegex(ValueError, 'SubQ supports only the subq-snap-1.1 decision model'):
                client.evaluate(state={}, questions=self.questions, model='unsupported-model')
        post.assert_not_called()

    def test_inception_rejects_model_override_before_network_request(self):
        client = DecisionClient('inception-test-key', transport='inception')
        with patch('services.decision_engine.requests.post') as post:
            with self.assertRaisesRegex(ValueError, 'Inception supports only the mercury-decide decision model'):
                client.evaluate(state={}, questions=self.questions, model='unsupported-model')
        post.assert_not_called()

    def test_subq_rejects_malformed_noul_and_missing_confidence(self):
        malformed = copy.deepcopy(self.payload)
        malformed['answers']['bullish'] = {'type': 'boolean', 'probability': .85}
        missing_confidence = copy.deepcopy(self.payload)
        missing_confidence['model'] = SUBQ_MODEL
        for key, answer in missing_confidence['answers'].items():
            if answer['type'] != 'noul':
                del answer['confidence']
        payloads = (malformed, missing_confidence)
        for payload in payloads:
            with self.subTest(payload=payload), patch(
                'services.decision_engine.requests.post',
                return_value=Mock(status_code=200, json=lambda: payload),
            ):
                with self.assertRaises(DecisionError) as caught:
                    DecisionClient('subq-test-key', transport='subq').evaluate(state={}, questions=self.questions)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_request_budget_hook_counts_each_transport_attempt_and_can_stop_retry(self):
        before = Mock(side_effect=[None, ValueError('request budget exhausted')])
        with patch('services.decision_engine.requests.post', return_value=Mock(status_code=429)) as post, \
                patch('services.decision_engine.time.sleep'):
            with self.assertRaisesRegex(ValueError, 'budget exhausted'):
                self.client.evaluate(state={}, questions=self.questions, before_request=before)
        self.assertEqual(before.call_count, 2)
        post.assert_called_once()
