import unittest
import json
import os
from unittest.mock import patch
from datetime import datetime, timedelta
from types import SimpleNamespace

from event_algo import (
    _ai_cooldown_seconds,
    _generate_heuristic_report,
    _parse_audit_report_json,
    evaluate_market,
    is_event_strategy_admin,
    normalize_config_payload,
    update_config,
    parse_event_model_batch_response,
    parse_event_model_response,
    report_to_dict,
    summarize_ai_scan_status,
)
from routes.event_algo import _paper_mode_enabled


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

    def test_strategy_paper_mode_is_independent_of_webull_trading_mode(self):
        self.assertTrue(_paper_mode_enabled())

    def test_event_strategy_admin_is_stable_username_only(self):
        with patch.dict(os.environ, {'EVENT_STRATEGY_ADMIN_USERNAME': 'admin'}):
            self.assertTrue(is_event_strategy_admin(SimpleNamespace(username='admin')))
            self.assertTrue(is_event_strategy_admin('ADMIN'))
            self.assertTrue(is_event_strategy_admin(1))
            self.assertFalse(is_event_strategy_admin(2))
            self.assertTrue(is_event_strategy_admin(SimpleNamespace(id=1, username='other')))
            self.assertFalse(is_event_strategy_admin(SimpleNamespace(id=2, username='another-user')))

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
        self.assertEqual(decision['action'], 'BUY_YES')
        self.assertTrue(decision['eligible'])
        self.assertIn('PAPER_SIGNALS_ONLY', decision['reason_codes'])
        self.assertFalse(decision['execution_allowed'])

    def test_market_cutoff_parsing(self):
        from event_algo import _market_cutoff
        # 15M symbol: 26SEP032245 -> 22:45 Eastern -> 02:45 UTC next day
        cutoff_15m = _market_cutoff({'symbol': 'KXBTC15M-26SEP032245-45'})
        self.assertIsNotNone(cutoff_15m)
        self.assertEqual(cutoff_15m.year, 2026)
        self.assertEqual(cutoff_15m.month, 9)
        self.assertEqual(cutoff_15m.day, 4)
        self.assertEqual(cutoff_15m.hour, 2)
        self.assertEqual(cutoff_15m.minute, 45)

        # Daily symbol: 26SEP0323 -> 23:00 Eastern -> 03:00 UTC next day
        cutoff_d = _market_cutoff({'symbol': 'KXBTCD-26SEP0323-T68899.99'})
        self.assertIsNotNone(cutoff_d)
        self.assertEqual(cutoff_d.year, 2026)
        self.assertEqual(cutoff_d.month, 9)
        self.assertEqual(cutoff_d.day, 4)
        self.assertEqual(cutoff_d.hour, 3)
        self.assertEqual(cutoff_d.minute, 0)

        # Date-only fallback should not be midnight at start of day
        cutoff_date = _market_cutoff({'expected_exp_date': '2026-09-03'})
        self.assertIsNotNone(cutoff_date)
        self.assertNotEqual(cutoff_date.hour, 0)

    def test_extract_settled_outcome_terminal_prices(self):
        from event_algo import extract_settled_outcome
        self.assertEqual(extract_settled_outcome({'status': 'DELISTING', 'tradable_status': 'NT', 'last_price': 0.999}), 'YES')
        self.assertEqual(extract_settled_outcome({'status': 'DELISTING', 'tradable_status': 'NT', 'last_price': 0.001}), 'NO')
        self.assertEqual(extract_settled_outcome({'status': 'SETTLED', 'settlement_price': 1.0}), 'YES')
        self.assertEqual(extract_settled_outcome({'status': 'SETTLED', 'settlement_price': 0.0}), 'NO')
        self.assertEqual(extract_settled_outcome({'settled_outcome': 'YES'}), 'YES')
        self.assertIsNone(extract_settled_outcome({'status': 'LISTING', 'tradable_status': 'OC', 'last_price': 0.55}))

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

    def test_parse_audit_report_json_clean_and_fenced(self):
        clean_json = '{"status": "HEALTHY", "headline": "All systems nominal", "summary": "Running smoothly.", "content_markdown": "### 1. Worker Execution"}'
        parsed = _parse_audit_report_json(clean_json)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['status'], 'HEALTHY')
        self.assertEqual(parsed['headline'], 'All systems nominal')

        fenced_json = '```json\n{"status": "ATTENTION_REQUIRED", "headline": "Warnings found", "summary": "Minor issues.", "content_markdown": "### Report"}\n```'
        parsed_fenced = _parse_audit_report_json(fenced_json)
        self.assertIsNotNone(parsed_fenced)
        self.assertEqual(parsed_fenced['status'], 'ATTENTION_REQUIRED')

    def test_parse_audit_report_json_fallback_markdown(self):
        raw_markdown = "### Event Strategy Engine Audit\n\nThe worker has performed 120 scans across BTC and ETH markets with zero quote drops. Decisions remain disciplined."
        parsed = _parse_audit_report_json(raw_markdown)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['status'], 'HEALTHY')
        self.assertIn('120 scans', parsed['content_markdown'])

    def test_generate_heuristic_report_healthy_vs_attention(self):
        healthy_data = {
            'period_start_iso': '2026-09-04T12:00:00Z',
            'period_end_iso': '2026-09-04T18:00:00Z',
            'worker_status': 'RUNNING',
            'symbols': ['BTC', 'ETH'],
            'durations': ['FIFTEEN_MINUTES', 'HOURLY'],
            'metrics': {
                'scans_count': 360,
                'scanned_contracts': 720,
                'total_logs': 400,
                'info_count': 400,
                'warning_count': 0,
                'error_count': 0,
                'decisions_count': 720,
                'eligible_count': 12,
                'no_trade_count': 708,
                'top_reason_codes': {'NO_EDGE': 600, 'CONFIDENCE_TOO_LOW': 108},
                'ai_evaluations': {'SUCCESS': 24, 'SKIPPED': 696},
            },
            'recent_errors': [],
            'decision_examples': [{
                'contract_symbol': 'KXBTC15M-TEST',
                'action': 'NO_TRADE',
                'probability_yes': 0.52,
                'net_edge': 0.01,
                'confidence': 0.55,
                'reason_codes': ['NO_EDGE'],
            }],
        }
        report_healthy = _generate_heuristic_report(healthy_data)
        self.assertEqual(report_healthy['status'], 'HEALTHY')
        self.assertIn('360 scans', report_healthy['content_markdown'])
        self.assertIn('KXBTC15M-TEST', report_healthy['content_markdown'])

        degraded_data = dict(healthy_data)
        degraded_data['metrics'] = dict(healthy_data['metrics'], error_count=5)
        degraded_data['recent_errors'] = [{'created_at': '2026-09-04T15:00:00Z', 'level': 'ERROR', 'event_type': 'SCAN_ERROR', 'message': 'API rate limit exceeded'}]
        report_degraded = _generate_heuristic_report(degraded_data)
        self.assertEqual(report_degraded['status'], 'DEGRADED')
        self.assertIn('API rate limit exceeded', report_degraded['content_markdown'])

    def test_report_to_dict_serialization(self):
        report_obj = SimpleNamespace(
            id=101,
            user_id=1,
            config_id=5,
            created_at=datetime(2026, 9, 4, 18, 0, 0),
            period_start=datetime(2026, 9, 4, 12, 0, 0),
            period_end=datetime(2026, 9, 4, 18, 0, 0),
            status='HEALTHY',
            headline='All operational tests passed',
            summary='Audit passed with high confidence.',
            content_markdown='### Full Audit',
            metrics_json='{"scans_count": 360, "error_count": 0}',
            model='gpt-4o',
            provider='openai',
            tier='primary',
        )
        d = report_to_dict(report_obj)
        self.assertEqual(d['id'], 101)
        self.assertEqual(d['status'], 'HEALTHY')
        self.assertEqual(d['metrics']['scans_count'], 360)
        self.assertEqual(d['model'], 'gpt-4o')

    def test_parse_audit_report_json_with_raw_ai_structure(self):
        raw_ai_payload = json.dumps({
            "audit_timestamp": "2026-09-04T22:00:00Z",
            "overall_status": "WARN",
            "issues": [
                {
                    "type": "AI_BUDGET_EXHAUSTED",
                    "count": 10,
                    "description": "Hourly AI evaluation budget reached repeatedly."
                },
                {
                    "type": "HIGH_ERROR_RATE",
                    "count": 208,
                    "description": "Error logs exceed info logs."
                }
            ],
            "metrics_summary": {
                "heartbeat_age_seconds": 46.1,
                "scans_count": 304,
                "scanned_contracts": 5706,
                "total_logs": 250,
                "info_count": 218,
                "warning_count": 32,
                "error_count": 208,
                "decisions_count": 100,
                "eligible_count": 0,
                "no_trade_count": 100,
                "top_reason_codes": {"MODEL_UNAVAILABLE": 80, "CONFIDENCE_TOO_LOW": 80},
                "ai_evaluations": {"SUCCESS": 85, "SKIPPED": 375}
            },
            "recommendations": [
                {
                    "action": "Increase_AI_Budget",
                    "details": "Raise hourly AI evaluation quota."
                },
                {
                    "action": "Review_Error_Logs",
                    "details": "Inspect the 208 error entries."
                }
            ],
            "next_steps": [
                "Run a focused error audit on frequent exceptions.",
                "Temporarily increase AI budget by 25%."
            ]
        })
        parsed = _parse_audit_report_json(raw_ai_payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['status'], 'ATTENTION_REQUIRED')
        self.assertNotIn('{ "audit_timestamp"', parsed['content_markdown'])
        self.assertIn('## Event Strategy Engine Operational AI Audit Report', parsed['content_markdown'])
        self.assertIn('Detected Operational Issues & Bottlenecks', parsed['content_markdown'])
        self.assertIn('AI Budget Exhausted', parsed['content_markdown'])
        self.assertIn('(Count: 10)', parsed['content_markdown'])
        self.assertIn('Telemetry & Execution Summary', parsed['content_markdown'])
        self.assertIn('Actionable Recommendations & Tuning', parsed['content_markdown'])
        self.assertIn('1. **Increase AI Budget**: Raise hourly AI evaluation quota.', parsed['content_markdown'])
        self.assertIn('Run a focused error audit on frequent exceptions.', parsed['content_markdown'])

    def test_report_to_dict_defensive_json_conversion(self):
        # Even if a legacy database row stored raw JSON in content_markdown, report_to_dict must convert it
        raw_json = json.dumps({
            "overall_status": "HEALTHY",
            "headline": "Telemetry verified clean.",
            "issues": [],
            "metrics_summary": {"scans_count": 100, "scanned_contracts": 200, "decisions_count": 100, "eligible_count": 5, "no_trade_count": 95, "error_count": 0, "warning_count": 0, "info_count": 100},
            "recommendations": [{"action": "Maintain_Cadence", "details": "Keep current 60-second polling interval."}],
            "next_steps": "Continue 24-hour observation."
        })
        legacy_report = SimpleNamespace(
            id=102,
            user_id=1,
            config_id=5,
            created_at=datetime(2026, 9, 4, 18, 0, 0),
            period_start=datetime(2026, 9, 4, 12, 0, 0),
            period_end=datetime(2026, 9, 4, 18, 0, 0),
            status='HEALTHY',
            headline='AI operational audit completed.',
            summary='',
            content_markdown=raw_json, # Raw JSON in DB!
            metrics_json='{}',
            model='gpt-oss:120b-cloud',
            provider='deepseek',
            tier='primary',
        )
        d = report_to_dict(legacy_report)
        self.assertEqual(d['id'], 102)
        self.assertFalse(d['content_markdown'].strip().startswith('{'))
        self.assertIn('## Event Strategy Engine Operational AI Audit Report', d['content_markdown'])
        self.assertIn('Maintain Cadence', d['content_markdown'])

    def test_skipped_contract_reasons(self):
        # When an evaluation is skipped due to budget, it produces AI_BUDGET_EXHAUSTED instead of MODEL_UNAVAILABLE
        decision_budget = evaluate_market({
            'symbol': 'KXBTC15M-TEST',
            'tradable_status': 'OC',
            'yes_bid': 0.40,
            'yes_ask': 0.42,
            'no_bid': 0.58,
            'no_ask': 0.60,
            'volume': 10,
            '_model_metadata': {'status': 'skipped', 'error': 'AI hourly budget exhausted'},
        }, self.config())
        self.assertEqual(decision_budget['action'], 'NO_TRADE')
        self.assertIn('AI_BUDGET_EXHAUSTED', decision_budget['reason_codes'])
        self.assertNotIn('MODEL_UNAVAILABLE', decision_budget['reason_codes'])
        self.assertNotIn('CONFIDENCE_TOO_LOW', decision_budget['reason_codes'])

        # When skipped due to batch interval
        decision_interval = evaluate_market({
            'symbol': 'KXBTC15M-TEST',
            'tradable_status': 'OC',
            'yes_bid': 0.40,
            'yes_ask': 0.42,
            'no_bid': 0.58,
            'no_ask': 0.60,
            'volume': 10,
            '_model_metadata': {'status': 'skipped', 'error': 'AI batch interval has not elapsed'},
        }, self.config())
        self.assertIn('AI_EVALUATION_DEFERRED', decision_interval['reason_codes'])
        self.assertNotIn('CONFIDENCE_TOO_LOW', decision_interval['reason_codes'])

    def test_batch_response_parsing_symbol_dict(self):
        # Test symbol-keyed dictionary parsing from model
        text = json.dumps({
            "KXBTC15M-TEST-1": {
                "probability_yes": 0.65,
                "confidence": 0.85,
                "rationale": "Bullish momentum in BTC underlying"
            },
            "KXETH15M-TEST-2": {
                "probability_yes": 0.40,
                "confidence": 0.70,
                "rationale": "Bearish trend in ETH"
            }
        })
        parsed = parse_event_model_batch_response(text)
        self.assertEqual(len(parsed), 2)
        self.assertIn("KXBTC15M-TEST-1", parsed)
        self.assertEqual(parsed["KXBTC15M-TEST-1"]["probability_yes"], 0.65)
        self.assertEqual(parsed["KXBTC15M-TEST-1"]["confidence"], 0.85)

    def test_format_action_title(self):
        from event_algo import _format_action_title
        self.assertEqual(_format_action_title("Higherrorrate"), "High Error Rate")
        self.assertEqual(_format_action_title("Increaseai Budget"), "Increase AI Budget")
        self.assertEqual(_format_action_title("Investigatemodeldeployment"), "Investigate Model Deployment")
        self.assertEqual(_format_action_title("Adjustconfidencethreshold"), "Adjust Confidence Threshold")
        self.assertEqual(_format_action_title("Reviewerrorlogs"), "Review Error Logs")
        self.assertEqual(_format_action_title("Liquidity Filtertuning"), "Liquidity Filter Tuning")
        self.assertEqual(_format_action_title("Monitorheartbeat"), "Monitor Heartbeat")
        self.assertEqual(_format_action_title("Noeligibledtrades"), "No Eligible Trades")


if __name__ == '__main__':
    unittest.main()
