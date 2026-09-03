import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from event_algo import evaluate_market, normalize_config_payload, parse_event_model_response


class EventAlgoTests(unittest.TestCase):
    @staticmethod
    def config(**overrides):
        values = {
            'risk_config': '{"min_volume": 1, "max_spread": 0.15}',
            'signal_config': '{"min_net_edge": 0.03, "min_confidence": 0.55, "fee_per_contract": 0.02, "uncertainty_buffer": 0.01, "signals_only": true}',
            'kill_switch': False,
            'model_version': 'empirical-v1',
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_config_forces_paper_and_signals_only(self):
        config = normalize_config_payload({
            'mode': 'LIVE',
            'enabled': True,
            'symbols': 'btc, eth',
            'durations': ['HOURLY'],
            'signal_config': {'signals_only': False},
        }, user_id=7)
        self.assertEqual(config['mode'], 'PAPER')
        self.assertTrue(config['signal_config']['signals_only'])
        self.assertEqual(config['symbols'], ['BTC', 'ETH'])

    def test_missing_probability_is_explicit_no_trade(self):
        decision = evaluate_market({
            'symbol': 'KXBTC15M-TEST',
            'tradable_status': 'OC',
            'yes_bid': 0.40,
            'yes_ask': 0.42,
            'no_bid': 0.58,
            'no_ask': 0.60,
            'volume': 10,
        }, self.config())
        self.assertEqual(decision['action'], 'NO_TRADE')
        self.assertIn('MODEL_UNAVAILABLE', decision['reason_codes'])
        self.assertFalse(decision['execution_allowed'])

    def test_qualified_signal_is_still_not_executed_in_v277(self):
        now = datetime.utcnow()
        decision = evaluate_market({
            'symbol': 'KXBTC15M-TEST',
            'tradable_status': 'OC',
            'quote_as_of': now.isoformat(),
            'contract_period_end': (now + timedelta(minutes=10)).isoformat(),
            'yes_bid': 0.40,
            'yes_ask': 0.42,
            'no_bid': 0.58,
            'no_ask': 0.60,
            'volume': 10,
            'model_probability_yes': 0.70,
            'model_confidence': 0.90,
        }, self.config())
        self.assertEqual(decision['action'], 'NO_TRADE')
        self.assertIn('PAPER_SIGNALS_ONLY', decision['reason_codes'])
        self.assertFalse(decision['execution_allowed'])

    def test_event_model_response_parses_json_and_percentages(self):
        parsed = parse_event_model_response(
            '```json\n{"probability_yes": 72, "confidence": 0.81, "rationale": "short-term momentum"}\n```'
        )
        self.assertEqual(parsed['probability_yes'], 0.72)
        self.assertEqual(parsed['confidence'], 0.81)
        self.assertEqual(parsed['rationale'], 'short-term momentum')

    def test_event_model_response_rejects_missing_or_invalid_values(self):
        self.assertIsNone(parse_event_model_response('{"probability_yes": 0.7}'))
        self.assertIsNone(parse_event_model_response('{"probability_yes": 1.5, "confidence": 0.8}'))
        self.assertIsNone(parse_event_model_response('not json'))

    def test_provider_error_is_visible_in_decision_reasons(self):
        now = datetime.utcnow()
        decision = evaluate_market({
            'symbol': 'KXBTC15M-ERROR',
            'tradable_status': 'OC',
            'quote_as_of': now.isoformat(),
            'contract_period_end': (now + timedelta(minutes=10)).isoformat(),
            'yes_bid': 0.40,
            'yes_ask': 0.42,
            'no_bid': 0.58,
            'no_ask': 0.60,
            'volume': 10,
            '_model_metadata': {'status': 'error', 'error': 'API Key Not Configured'},
        }, self.config())
        self.assertIn('AI_PROVIDER_ERROR', decision['reason_codes'])
        self.assertNotIn('MODEL_UNAVAILABLE', decision['reason_codes'])


if __name__ == '__main__':
    unittest.main()
