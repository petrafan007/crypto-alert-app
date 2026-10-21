"""The Decision Engine's wire contract for each supported provider.

SubQ and Inception Mercury Decide both express a positive answer as a
``noul`` probability, so both are normalised through the same path. These
checks pin the request and response shapes so a provider change cannot
silently corrupt a decision.
"""
import json
import unittest

from services.decision_engine import DecisionClient, DecisionError, validate_answers
from services.decision_settings import (
    INCEPTION_DECISIONS_ENDPOINT,
    INCEPTION_DECISIONS_MODEL,
    SUBQ_ENDPOINT,
    SUBQ_MODEL,
)

QUESTIONS = {
    'bullish': {'type': 'boolean', 'instructions': 'Is this bullish?'},
    'direction': {'type': 'choice', 'instructions': 'Which direction?',
                  'criteria': {'up': 'up', 'down': 'down'}},
    'materiality': {'type': 'score', 'instructions': 'How material?',
                    'criteria': ['low', 'medium', 'high']},
}

MERCURY_RESPONSE = {
    'model': 'mercury-decide',
    'answers': {
        'bullish': {'type': 'noul', 'noul': 0.82},
        'direction': {'type': 'choice', 'choice': 'up',
                      'probabilities': {'up': 0.71, 'down': 0.29}, 'confidence': 0.64},
        'materiality': {'type': 'score', 'score': 1.0,
                        'legend': {'0': 'low', '1': 'medium', '2': 'high'},
                        'probabilities': {'0': 0.1, '1': 0.7, '2': 0.2}, 'confidence': 0.55},
    },
    'usage': {'input_tokens': 512, 'output_tokens': 1},
}


class ProviderEndpointTests(unittest.TestCase):
    def test_inception_uses_the_documented_decisions_endpoint(self):
        self.assertEqual(INCEPTION_DECISIONS_ENDPOINT,
                         'https://api.inceptionlabs.ai/v1/decisions')
        self.assertEqual(INCEPTION_DECISIONS_MODEL, 'mercury-decide')

    def test_subq_uses_its_documented_endpoint(self):
        self.assertEqual(SUBQ_ENDPOINT, 'https://api.subq.ai/v1/systemone')
        self.assertEqual(SUBQ_MODEL, 'subq-snap-preview')

    def test_each_provider_only_accepts_its_own_model(self):
        inception = DecisionClient('k', INCEPTION_DECISIONS_ENDPOINT, INCEPTION_DECISIONS_MODEL, 3.0, 'inception')
        with self.assertRaises(ValueError):
            inception.evaluate(state={}, questions=QUESTIONS, model='mercury-3')
        subq = DecisionClient('k', SUBQ_ENDPOINT, SUBQ_MODEL, 3.0, 'subq')
        with self.assertRaises(ValueError):
            subq.evaluate(state={}, questions=QUESTIONS, model='mercury-decide')


class WireShapeTests(unittest.TestCase):
    def setUp(self):
        self.client = DecisionClient('k', INCEPTION_DECISIONS_ENDPOINT, INCEPTION_DECISIONS_MODEL, 3.0, 'inception')

    def test_internal_boolean_is_sent_as_noul(self):
        wire = self.client._wire_questions(QUESTIONS)
        self.assertEqual(wire['bullish']['type'], 'noul')
        self.assertEqual(wire['bullish']['instructions'], 'Is this bullish?')

    def test_choice_and_score_questions_are_unchanged(self):
        wire = self.client._wire_questions(QUESTIONS)
        self.assertEqual(wire['direction']['type'], 'choice')
        self.assertEqual(wire['direction']['criteria'], {'up': 'up', 'down': 'down'})
        self.assertEqual(wire['materiality']['type'], 'score')
        self.assertEqual(wire['materiality']['criteria'], ['low', 'medium', 'high'])

    def test_documented_response_is_normalised(self):
        answers, confidence = self.client._normalize(MERCURY_RESPONSE, QUESTIONS)
        self.assertEqual(answers['bullish'], {'type': 'boolean', 'probability': 0.82})
        self.assertEqual(answers['direction']['probabilities']['up'], 0.71)
        self.assertEqual(confidence['direction'], 0.64)
        self.assertEqual(answers['materiality']['score'], 1.0)
        self.assertEqual(answers['materiality']['legend']['1'], 'medium')
        self.assertEqual(confidence['materiality'], 0.55)

    def test_mismatched_score_legend_is_rejected(self):
        payload = json.loads(json.dumps(MERCURY_RESPONSE))
        payload['answers']['materiality']['legend'] = {'0': 'low', '1': 'high', '2': 'medium'}
        with self.assertRaises(DecisionError):
            self.client._normalize(payload, QUESTIONS)

    def test_non_noul_boolean_is_rejected(self):
        payload = json.loads(json.dumps(MERCURY_RESPONSE))
        payload['answers']['bullish'] = {'type': 'boolean', 'probability': 0.5}
        with self.assertRaises(DecisionError):
            self.client._normalize(payload, QUESTIONS)

    def test_probability_distribution_must_sum_to_one(self):
        payload = json.loads(json.dumps(MERCURY_RESPONSE))
        payload['answers']['direction']['probabilities'] = {'up': 0.9, 'down': 0.9}
        with self.assertRaises(DecisionError):
            self.client._normalize(payload, QUESTIONS)

    def test_choice_answer_with_unknown_options_is_rejected(self):
        with self.assertRaises(DecisionError):
            validate_answers({'answers': {'direction': MERCURY_RESPONSE['answers']['direction']}},
                             {'direction': {'type': 'choice', 'criteria': {'up': '', 'sideways': ''}}})


class ActiveQuantGateTests(unittest.TestCase):
    """The Decision Engine must be able to block an entry, and must never
    be able to silence a module by abstaining."""

    def test_block_rejects_and_abstain_does_not(self):
        from services.portfolio_engine import decision_verdict

        class Result(dict):
            pass

        def make(verdict):
            return lambda *args, **kwargs: {'verdict': verdict, 'probability': 0.1,
                                            'reason': 'test', 'evaluation_id': None}

        config = {'decision_enabled': True, 'decision_quant_enabled': True}
        blocked = decision_verdict(1, 'crypto', 'BTC', 100.0, {'enter': True},
                                   None, config, make('BLOCK'))
        self.assertEqual(blocked['verdict'], 'BLOCK')

        abstained = decision_verdict(1, 'crypto', 'BTC', 100.0, {'enter': True},
                                     None, config, make('ABSTAIN'))
        self.assertEqual(abstained['verdict'], 'ABSTAIN')

    def test_a_failing_decision_engine_abstains_rather_than_blocking(self):
        from services.portfolio_engine import decision_verdict

        def boom(*args, **kwargs):
            raise RuntimeError('provider down')

        config = {'decision_enabled': True, 'decision_quant_enabled': True}
        result = decision_verdict(1, 'crypto', 'BTC', 100.0, {'enter': True}, None, config, boom)
        self.assertEqual(result['verdict'], 'ABSTAIN')

    def test_the_gate_never_applies_to_a_non_crypto_module(self):
        from services.portfolio_engine import decision_verdict

        def should_not_run(*args, **kwargs):
            raise AssertionError('the decision engine must not gate a non-crypto module')

        config = {'decision_enabled': True, 'decision_quant_enabled': True}
        self.assertIsNone(decision_verdict(1, 'equities', 'MSFT', 100.0, {'enter': True},
                                           None, config, should_not_run))

    def test_the_gate_is_inert_when_the_decision_engine_is_disabled(self):
        from services.portfolio_engine import decision_verdict

        def should_not_run(*args, **kwargs):
            raise AssertionError('the decision engine must not be consulted when disabled')

        for config in ({'decision_enabled': False, 'decision_quant_enabled': True},
                       {'decision_enabled': True, 'decision_quant_enabled': False}):
            self.assertIsNone(decision_verdict(1, 'crypto', 'BTC', 100.0, {'enter': True},
                                               None, config, should_not_run))


if __name__ == '__main__':
    unittest.main()
