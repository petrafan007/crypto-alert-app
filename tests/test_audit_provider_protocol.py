import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from flask import Flask

from services.ai_provider_protocol import AIProviderHTTPError, call_gemini_chat, gemini_generation_config
from services.ai_service import call_ai_with_web_search, call_ollama_chat, audit_provider_retry_delay_seconds
from services.portfolio_audit_context import AUDIT_END
from services.portfolio_audit_progress import audit_progress


def response(code=200, body=None, headers=None):
    result = Mock(status_code=code, headers=headers or {}, text=json.dumps(body or {}))
    result.json.return_value = body or {}
    return result


class AuditProviderProtocolTests(unittest.TestCase):
    def test_gemini_version_specific_thinking(self):
        self.assertEqual(gemini_generation_config('gemini-3.8-flash', 8192, 'extra high'),
                         {'maxOutputTokens': 8192, 'thinkingConfig': {'thinkingLevel': 'high'}})
        self.assertEqual(gemini_generation_config('gemini-3-pro-preview', 8192, 'medium')['thinkingConfig'], {'thinkingLevel': 'high'})
        self.assertEqual(gemini_generation_config('gemini-2.5-flash', 8192, 'extra high')['thinkingConfig'], {'thinkingBudget': 4096})
        self.assertNotIn('thinkingConfig', gemini_generation_config('gemini-2.0-flash', 100, 'low'))

    def test_gemini_preserves_roles_final_text_and_keeps_key_out_of_url(self):
        result = response(body={'candidates': [{'content': {'parts': [{'thought': True, 'text': 'private reasoning'}, {'text': 'Final answer'}]}, 'finishReason': 'STOP'}]})
        with patch('services.ai_provider_protocol.requests.post', return_value=result) as post:
            answer = call_gemini_chat('secret', 'models/gemini-3.8-flash', [
                {'role': 'system', 'content': 'First instruction'}, {'role': 'system', 'content': 'Second instruction'},
                {'role': 'user', 'content': 'Question'}, {'role': 'assistant', 'content': 'Prior answer'},
            ], 8192, 600, 'high')
        self.assertEqual(str(answer), 'Final answer')
        self.assertEqual(answer.finish_reason, 'STOP')
        self.assertNotIn('secret', post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'secret')
        self.assertEqual(post.call_args.kwargs['timeout'], (10, 600))
        payload = post.call_args.kwargs['json']
        self.assertEqual(len(payload['systemInstruction']['parts']), 2)
        self.assertEqual([c['role'] for c in payload['contents']], ['user', 'model'])

    def test_gemini_400_is_not_resent_with_silently_removed_reasoning(self):
        with patch('services.ai_provider_protocol.requests.post', return_value=response(400, {'error': 'bad input secret'})) as post:
            with self.assertRaises(AIProviderHTTPError) as caught:
                call_gemini_chat('secret', 'gemini-3.8-flash', [], 100, 600)
        post.assert_called_once()
        self.assertEqual(caught.exception.status_code, 400)
        self.assertNotIn('secret', str(caught.exception))

    def test_gemini_empty_candidates_cannot_become_a_json_report(self):
        with patch('services.ai_provider_protocol.requests.post', return_value=response(body={'promptFeedback': {'blockReason': 'SAFETY'}})):
            with self.assertRaisesRegex(ValueError, 'SAFETY'):
                call_gemini_chat('key', 'gemini-3.8-flash', [], 100, 600)

    def run_cascade(self, results, tiers=None):
        tiers = tiers or [('primary', 'gemini', 'gemini-3.8-flash', 'high'),
                          ('secondary', 'ollama', 'nemotron-3-ultra:cloud', 'medium'),
                          ('tertiary', 'ollama', 'lfm2.5:latest', 'medium')]
        events = []
        with ExitStack() as stack:
            stack.enter_context(patch('services.ai_service.get_user_ai_settings', return_value={}))
            stack.enter_context(patch('services.ai_service.get_user_credentials', return_value=SimpleNamespace(gemini_key='global-wrong-key')))
            stack.enter_context(patch('services.ai_service.is_ollama_admin', return_value=True))
            stack.enter_context(patch('services.provider_resilience.check'))
            stack.enter_context(patch('services.provider_resilience.read', return_value=None))
            stack.enter_context(patch('services.provider_resilience.block_failure'))
            post = stack.enter_context(patch('requests.post', side_effect=results))
            answer, _ = call_ai_with_web_search(None, [{'role': 'system', 'content': 'Audit'}, {'role': 'user', 'content': '{}'}],
                prompt_type='portfolio_module_audit', custom_tier_configs=tiers,
                custom_api_keys={('primary', 'gemini'): 'dedicated-secret'}, attempt_observer=lambda **event: events.append(event))
            return answer, post.call_args_list, events

    def test_gemini_timeout_and_503_retry_same_key_then_succeed_without_ollama(self):
        success = response(body={'candidates': [{'content': {'parts': [{'text': 'Complete.\n'+AUDIT_END}]}, 'finishReason': 'STOP'}]})
        answer, calls, events = self.run_cascade([requests.ReadTimeout('timed out'), response(503, {'error': 'busy'}), success])
        self.assertEqual(answer.provider, 'gemini')
        self.assertEqual(len(calls), 3)
        self.assertTrue(all('generativelanguage.googleapis.com' in c.args[0] for c in calls))
        self.assertTrue(all(c.kwargs['headers']['x-goog-api-key'] == 'dedicated-secret' for c in calls))
        self.assertEqual([e['event'] for e in events].count('retrying'), 2)
        self.assertNotIn('dedicated-secret', json.dumps(events))

    def test_ollama_cloud_500_retries_without_loading_local_model(self):
        answer, calls, events = self.run_cascade([
            response(500, {'error': 'upstream unavailable'}),
            response(body={'message': {'content': 'Complete.\n'+AUDIT_END}, 'done_reason': 'stop'}),
        ], [('secondary', 'ollama', 'nemotron-3-ultra:cloud', 'medium'), ('tertiary', 'ollama', 'lfm2.5:latest', 'medium')])
        self.assertEqual(answer.model, 'nemotron-3-ultra:cloud')
        self.assertEqual([c.kwargs['json']['model'] for c in calls], ['nemotron-3-ultra:cloud'] * 2)
        self.assertTrue(any('HTTP 500' in (e['error'] or '') for e in events))

    def test_fallback_only_after_retry_exhaustion_in_configured_order(self):
        answer, calls, events = self.run_cascade([
            response(503, {'error': 'busy'}) for _ in range(3)
        ] + [response(body={'message': {'content': 'Complete.\n'+AUDIT_END}, 'done_reason': 'stop'})])
        self.assertEqual(answer.model, 'nemotron-3-ultra:cloud')
        self.assertEqual(len(calls), 4)
        self.assertEqual([e['model'] for e in events if e['event'] == 'queued'], ['gemini-3.8-flash', 'nemotron-3-ultra:cloud'])
        self.assertIn('HTTP 503', answer.failover_history[0]['error'])

    def test_throttle_retries_but_daily_quota_and_auth_do_not_burst(self):
        success = response(body={'message': {'content': 'Complete.\n'+AUDIT_END}, 'done_reason': 'stop'})
        for code, error in [(401, 'invalid key'), (404, 'model missing'), (429, 'GenerateRequestsPerDayPerProjectPerModel')]:
            with self.subTest(code=code):
                _, calls, _ = self.run_cascade([response(code, {'error': error}), success])
                self.assertEqual(len(calls), 2)
        gemini = response(body={'candidates': [{'content': {'parts': [{'text': 'Complete.\n'+AUDIT_END}]}, 'finishReason': 'STOP'}]})
        answer, calls, _ = self.run_cascade([response(429, {'error': 'per minute rate limit'}, {'Retry-After': '45'}), gemini])
        self.assertEqual(answer.provider, 'gemini')
        self.assertEqual(len(calls), 2)

    def test_backoff_honors_retry_after_and_gemini_retry_info(self):
        app = Flask(__name__)
        with app.app_context(), patch('services.ai_service.random.uniform', return_value=0):
            exc = AIProviderHTTPError('Gemini', response(429, {'error': 'slow down'}, {'Retry-After': '90'}))
            self.assertEqual(audit_provider_retry_delay_seconds(1, exc), 90)
            exc = AIProviderHTTPError('Gemini', response(429, {'error': {'retryDelay': '75s'}}))
            self.assertEqual(audit_provider_retry_delay_seconds(1, exc), 75)
            self.assertEqual(audit_provider_retry_delay_seconds(2), 30)

    def test_ollama_400_retries_only_thinking_compatibility_errors(self):
        for detail, expected_calls in [('invalid messages', 1), ('model does not support thinking', 2)]:
            with patch('requests.post', side_effect=[response(400, {'error': detail}), response(body={'message': {'content': 'OK'}})]) as post:
                if expected_calls == 1:
                    with self.assertRaises(AIProviderHTTPError):
                        call_ollama_chat('nemotron-3-ultra:cloud', [])
                else:
                    self.assertEqual(call_ollama_chat('legacy-model', []), 'OK')
                self.assertEqual(post.call_count, expected_calls)

    def test_progress_uses_only_enabled_modules_and_reserves_master_work(self):
        evidence = {'specialist_mandates': {'equities': '', 'crypto': ''},
                    'module_audits': {'equities': 'Done'}, 'audit_progress': {'stage': 'module', 'current_module': 'crypto'}}
        progress = audit_progress('PENDING', '2026-09-08T12:00:00Z', evidence)
        self.assertEqual(progress['percent'], 45)
        self.assertEqual(progress['modules'], ['equities', 'crypto'])
        evidence['module_audit_errors'] = {'crypto': 'Unavailable'}
        evidence['audit_progress']['stage'] = 'master'
        self.assertEqual(audit_progress('PENDING', None, evidence)['percent'], 85)
        self.assertEqual(audit_progress('FAILED', None, evidence)['percent'], 85)
        self.assertEqual(audit_progress('PARTIAL', None, evidence)['percent'], 100)
