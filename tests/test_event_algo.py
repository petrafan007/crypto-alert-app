import unittest
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from event_algo import (
    _ai_cooldown_seconds,
    evaluate_market,
    is_event_strategy_admin,
    normalize_config_payload,
    update_config,
    parse_event_model_batch_response,
    parse_event_model_response,
    summarize_ai_scan_status,
)


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
        self.assertEqual(config['durations'], ['HOURLY'])

    def test_explicit_duration_selection_is_preserved_including_empty(self):
        selected = normalize_config_payload({'durations': ['DAILY']}, user_id=7)
        self.assertEqual(selected['durations'], ['DAILY'])

        cleared = normalize_config_payload({'durations': []}, user_id=7)
        self.assertEqual(cleared['durations'], [])

    def test_update_config_persists_selected_duration(self):
        config = SimpleNamespace(user_id=7)
        update_config(config, {'durations': ['MONTHLY']})
        self.assertEqual(json.loads(config.durations), ['MONTHLY'])

    def test_event_strategy_admin_is_stable_username_only(self):
        self.assertTrue(is_event_strategy_admin(SimpleNamespace(username='jcavallarojr')))
        self.assertTrue(is_event_strategy_admin('JCAVALLARojr'))
        self.assertFalse(is_event_strategy_admin(SimpleNamespace(username='another-user')))
        self.assertFalse(is_event_strategy_admin(SimpleNamespace(username='jcavallarojr-admin')))

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

    def test_batch_response_is_strict_and_symbol_keyed(self):
        parsed = parse_event_model_batch_response(
            '{"predictions":[{"contract_symbol":"kxbtc-1","probability_yes":0.72,"confidence":0.8},'
            '{"contract_symbol":"KXETH-2","probability_no":0.25,"confidence":75}]}'
        )
        self.assertEqual(parsed['KXBTC-1']['probability_yes'], 0.72)
        self.assertEqual(parsed['KXETH-2']['probability_yes'], 0.75)
        self.assertNotIn('UNKNOWN', parsed)

    def test_frequency_settings_are_bounded_and_duration_aware(self):
        config = normalize_config_payload({
            'signal_config': {
                'snapshot_interval_seconds': 1,
                'ai_batch_interval_seconds': 999999,
                'ai_batch_size': 999,
                'max_ai_calls_per_hour': 0,
                'ai_cache_ttl_seconds': 2,
                'ai_context_refresh_hours': 999,
                'ai_retry_backoff_seconds': 1,
                'ai_cooldown_by_duration': {'FIFTEEN_MINUTES': 31, 'HOURLY': 7200},
            },
        }, user_id=7)
        signal = config['signal_config']
        self.assertEqual(signal['snapshot_interval_seconds'], 30)
        self.assertEqual(signal['ai_batch_interval_seconds'], 86400)
        self.assertEqual(signal['ai_batch_size'], 20)
        self.assertEqual(signal['max_ai_calls_per_hour'], 1)
        self.assertEqual(signal['ai_cache_ttl_seconds'], 30)
        self.assertEqual(signal['ai_context_refresh_hours'], 168)
        self.assertEqual(signal['ai_retry_backoff_seconds'], 30)
        self.assertEqual(_ai_cooldown_seconds(signal, 'FIFTEEN_MINUTES'), 31)
        self.assertEqual(_ai_cooldown_seconds(signal, 'HOURLY'), 7200)

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

    def test_scheduled_ai_skip_is_not_reported_as_provider_outage(self):
        status = summarize_ai_scan_status({
            'KXBTC15M-TEST': {
                '_model_metadata': {
                    'status': 'skipped',
                    'error': 'AI batch interval has not elapsed',
                },
            },
        })
        self.assertEqual(status['event_type'], 'AI_EVALUATION_DEFERRED')
        self.assertFalse(status['notify'])
        self.assertIn('deferred', status['message'])

    def test_actual_ai_failure_remains_visible_as_provider_outage(self):
        status = summarize_ai_scan_status({
            'KXBTC15M-ERROR': {
                '_model_metadata': {
                    'status': 'error',
                    'error': 'Tertiary provider timed out',
                },
            },
        })
        self.assertEqual(status['event_type'], 'AI_UNAVAILABLE')
        self.assertTrue(status['notify'])
        self.assertIn('Tertiary provider timed out', status['message'])


if __name__ == '__main__':
    unittest.main()
