import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from services.portfolio_audit_context import (
    AUDIT_END, CompletionText, IncompleteAuditError, complete_audit_text,
    check_drawdown_claim, audit_system_prompt,
)


class AuditContextTests(unittest.TestCase):
    def test_settlement_fallback_rejects_unconfirmed_or_mismatched_results(self):
        from datetime import datetime, timezone
        from services.event_settlement_data import confirmed_kalshi_settlement
        symbol = 'KXBTCD-26SEP0622-T75899.99'
        cutoff = datetime(2026, 9, 7, 2, tzinfo=timezone.utc)
        now = datetime(2026, 9, 7, 3, tzinfo=timezone.utc)
        market = {'ticker': symbol, 'market_type': 'binary', 'status': 'finalized', 'result': 'yes',
                  'close_time': '2026-09-07T02:00:00Z', 'settlement_ts': '2026-09-07T02:02:45Z',
                  'settlement_value_dollars': '1.0000'}
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None, url='https://example.test')
        with patch('services.event_settlement_data.requests.get', return_value=response) as get:
            response.json = lambda: {'market': market}
            self.assertEqual(confirmed_kalshi_settlement(symbol, cutoff, now)['settled_outcome'], 'YES')
            for change in ({'ticker': 'WRONG'}, {'result': 'scalar'}, {'status': 'determined'},
                           {'is_provisional': True}, {'settlement_value_dollars': '0.0'},
                           {'close_time': '2026-09-07T01:00:00Z'}, {'settlement_ts': None},
                           {'settlement_ts': '2026-09-08T02:00:00Z'}, {'market_type': 'scalar'}):
                response.json = lambda change=change: {'market': {**market, **change}}
                with self.subTest(change=change):
                    self.assertIsNone(confirmed_kalshi_settlement(symbol, cutoff, now))
            get.reset_mock()
            self.assertIsNone(confirmed_kalshi_settlement('OTHER', cutoff, now))
            self.assertIsNone(confirmed_kalshi_settlement(symbol, cutoff, cutoff.replace(hour=1)))
            get.assert_not_called()

    def test_rejects_incomplete_filtered_or_thinking_only_outputs(self):
        for value in ('Partial table |', AUDIT_END, '```\nunfinished\n'+AUDIT_END,
                      CompletionText('Text\n'+AUDIT_END, 'length'),
                      CompletionText('Text\n'+AUDIT_END, 'MAX_TOKENS'),
                      CompletionText('Text\n'+AUDIT_END, 'safety'),
                      CompletionText('Text\n'+AUDIT_END, 'stop', final_answer=False)):
            with self.subTest(value=value), self.assertRaises(IncompleteAuditError):
                complete_audit_text(value)
        self.assertEqual(complete_audit_text(CompletionText('Complete.\n'+AUDIT_END, 'stop')), 'Complete.')

    def test_drawdown_percentage_is_not_scaled_twice(self):
        evidence = {'performance': {'max_drawdown_pct': .115836}}
        check_drawdown_claim('| Maximum drawdown | 0.12% |', evidence)
        with self.assertRaises(IncompleteAuditError):
            check_drawdown_claim('| Max drawdown | 11.58% |', evidence)

    def test_custom_prompts_retain_engine_purpose_and_evidence_semantics(self):
        prompt = audit_system_prompt('My custom instructions', 'events')
        self.assertTrue(prompt.startswith('My custom instructions'))
        for term in ('PAPER', 'maximum strategy budgets', 'side BOUGHT', 'not a buy signal', 'ALREADY percentages'):
            self.assertIn(term, prompt)

    def call_audit(self, responses, prompt_type='portfolio_module_audit', tiers=None):
        from services.ai_service import call_ai_with_web_search
        with ExitStack() as stack:
            stack.enter_context(patch('services.ai_service.get_user_ai_settings', return_value={
                'ai_provider': 'ollama', 'ai_model': 'test', 'ai_max_tokens': 100,
                'copilot_chat_post': 'WRONG COPILOT PROMPT'}))
            stack.enter_context(patch('services.ai_service.get_user_credentials', return_value=SimpleNamespace()))
            stack.enter_context(patch('services.ai_service.is_ollama_admin', return_value=True))
            stack.enter_context(patch('services.provider_resilience.check'))
            stack.enter_context(patch('services.provider_resilience.block_failure'))
            search = stack.enter_context(patch('services.ai_service.web_search', side_effect=AssertionError('No audit web search')))
            prompts = stack.enter_context(patch('services.ai_service.get_user_ai_prompts', side_effect=AssertionError('No Copilot prompts')))
            provider = stack.enter_context(patch('services.ai_service.call_ollama_chat', side_effect=responses))
            response, _ = call_ai_with_web_search(username=None, user_id=1, messages=[
                {'role': 'system', 'content': 'PAPER SPECIALIST'}, {'role': 'user', 'content': '{"positions": []}'}],
                prompt_type=prompt_type, custom_tier_configs=tiers)
            search.assert_not_called()
            prompts.assert_not_called()
            return response, provider.call_args_list

    def test_specialists_keep_system_prompt_and_retry_with_larger_budget(self):
        response, calls = self.call_audit([CompletionText('cut off', 'length'), 'Finished.\n'+AUDIT_END])
        self.assertEqual(response.text, 'Finished.')
        self.assertEqual([c.kwargs['max_tokens'] for c in calls], [8192, 16384])
        self.assertEqual(calls[0].args[1][1]['content'], '{"positions": []}')
        self.assertTrue(calls[0].args[1][0]['content'].startswith('PAPER SPECIALIST'))
        self.assertEqual(calls[0].kwargs['timeout'], 600)

    def test_master_uses_larger_budget_and_fails_over_after_incomplete_retry(self):
        response, calls = self.call_audit(['cut', 'cut again', 'Complete.\n'+AUDIT_END],
            'portfolio_audit', [('primary', 'ollama', 'first', 'high'), ('secondary', 'ollama', 'second', 'high')])
        self.assertEqual(response.model, 'second')
        self.assertEqual([c.kwargs['max_tokens'] for c in calls], [16384, 32768, 16384])

    def test_exhausted_incomplete_outputs_raise_instead_of_succeeding(self):
        with self.assertRaises(IncompleteAuditError) as caught:
            self.call_audit(['partial one', 'partial two'])
        self.assertEqual(caught.exception.partial_text, 'partial two')

    def test_event_normalizers_preserve_explicit_resolution_end_to_end(self):
        from services.webull_service import _normalise_event_market, _normalise_event_snapshot
        from event_algo import extract_settled_outcome
        for resolution in ({'settled_outcome': 'NO'}, {'resolution': {'winning_outcome': 'YES'}},
                           {'settlement_price': 0}):
            raw = {'symbol': 'KXBTCD-TEST', 'name': 'Test', 'status': 'SETTLED', **resolution}
            market = _normalise_event_market(raw, {})
            market.update(_normalise_event_snapshot(raw))
            self.assertEqual(extract_settled_outcome(market), 'YES' if 'resolution' in resolution else 'NO')
