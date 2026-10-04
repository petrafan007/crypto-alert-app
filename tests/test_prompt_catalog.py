"""Saved UI instructions reach evaluations; users cannot alter response contracts."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.extensions import db
from credentials import UserSetting
from routes import ai
from services.prompt_catalog import default_prompt, prompt_for, save_overrides, validate_overrides
from services.jev_contracts import build_sentiment_questions
from services.jev_event import build_questions, forecast_identity_for
from services.jev_evaluations import create_evaluation, get_evaluation
from services.jev_service import JevClient, JevError
from tests.jev_helpers import JevTestCase


class PromptCatalogTests(JevTestCase):
    def test_engine_modal_endpoint_persists_contract_instructions(self):
        from routes import portfolio_algo
        questions = default_prompt('jev.contract_probability')
        questions['outcome']['instructions'] = 'Saved modal question for contracts[{index}] ({symbol}).'
        with self.app.test_request_context('/api/webull/portfolio-algo/ai-config', method='POST',
                json={'prompt_overrides': {'jev.contract_probability': questions}}), \
                patch.object(portfolio_algo, 'current_user', SimpleNamespace(id=1, is_admin=True)):
            response = portfolio_algo.portfolio_algo_ai_config.__wrapped__()
        self.assertTrue(response.json['success'])
        db.session.expire_all()
        self.assertEqual(prompt_for(1, 'jev.contract_probability'), questions)
        self.assertEqual(response.json['ai_config']['event_evaluator'], 'jev')

    def test_legacy_event_mandate_is_visible_and_editor_changes_take_effect(self):
        row = db.session.get(UserSetting, 1)
        row.event_strategy_audit_prompt = 'Preserved Event mandate'; db.session.commit()
        response, status = self.request()
        self.assertEqual(response.json['prompts']['audit.event_system']['value'], 'Preserved Event mandate')
        self.request('POST', {'audit.event_system': 'Updated Event mandate'})
        self.assertEqual(prompt_for(1, 'audit.event_system'), 'Updated Event mandate')
        self.assertEqual(row.event_strategy_audit_prompt, 'Preserved Event mandate')

    def request(self, method='GET', payload=None, user_id=1):
        with self.app.test_request_context('/api/ai/prompt-catalog', method=method, json=payload), \
                patch.object(ai, 'current_user', SimpleNamespace(id=user_id, username='jev-test', is_admin=(user_id == 1))):
            result = ai.ai_prompt_catalog.__wrapped__()
        return result if isinstance(result, tuple) else (result, 200)

    def test_authenticated_round_trip_and_user_isolation(self):
        questions = default_prompt('jev.watchlist_sentiment')
        questions['direction']['instructions'] = 'Use the saved watchlist evidence and horizon.'
        response, status = self.request('POST', {'jev.watchlist_sentiment': questions})
        self.assertEqual(status, 200)
        self.assertEqual(response.json['prompts']['jev.watchlist_sentiment']['value'], questions)
        self.assertEqual(build_sentiment_questions(1, True), questions)
        self.assertNotEqual(build_sentiment_questions(2, True), questions)
        self.assertNotEqual(build_sentiment_questions(1, False), questions)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_contract_edits_reach_request_and_invalidate_cached_forecast(self):
        before = forecast_identity_for(1)
        questions = default_prompt('jev.contract_probability')
        questions['outcome']['instructions'] = 'Use exact cutoff for contracts[{index}] ({symbol}); supplied evidence only.'
        response, status = self.request('POST', {'jev.contract_probability': questions})
        self.assertEqual(status, 200)
        actual = build_questions([{'symbol':'ONE'}, {'symbol':'TWO'}], 1)
        self.assertIn('contracts[1] (TWO)', actual['c1_outcome']['instructions'])
        self.assertIn('Use exact cutoff', actual['c0_outcome']['instructions'])
        self.assertNotEqual(before, forecast_identity_for(1))

    def test_invalid_contract_edits_are_rejected_without_overwriting_saved_prompts(self):
        original = db.session.get(UserSetting, 1).ai_prompt_overrides
        for change in ('label', 'type', 'missing_binding', 'empty'):
            questions = default_prompt('jev.contract_probability')
            if change == 'label': questions['outcome']['criteria']['BUY'] = 'Buy now'
            elif change == 'type': questions['outcome']['type'] = 'boolean'
            elif change == 'missing_binding': questions['outcome']['instructions'] = 'Unbound forecast'
            else: questions['outcome']['instructions'] = ''
            with self.subTest(change=change):
                response, status = self.request('POST', {'jev.contract_probability': questions})
                self.assertEqual(status, 400)
                self.assertEqual(db.session.get(UserSetting, 1).ai_prompt_overrides, original)

    def test_non_admin_cannot_change_quantitative_prompts(self):
        _, status = self.request('POST', {'jev.contract_probability': default_prompt('jev.contract_probability')}, user_id=2)
        self.assertEqual(status, 403)

    def test_queued_evaluation_freezes_edited_questions(self):
        row = db.session.get(UserSetting, 1)
        first = default_prompt('jev.sentiment')
        first['direction']['instructions'] = 'First saved instruction'
        save_overrides(row, {'jev.sentiment': first}); db.session.commit()
        evaluation_id = create_evaluation(1, 'sentiment', self.state, self.config)
        second = copy.deepcopy(first); second['direction']['instructions'] = 'Second saved instruction'
        save_overrides(row, {'jev.sentiment': second}); db.session.commit()
        snapshot = json.loads(get_evaluation(evaluation_id).settings_json)
        self.assertEqual(snapshot['questions'], first)
        self.assertEqual(build_sentiment_questions(1), second)

    def test_mask_placeholder_never_reaches_provider(self):
        with patch('services.jev_service.requests.post') as post:
            with self.assertRaises(JevError) as error:
                JevClient('********', transport='openrouter').evaluate(state={}, questions=default_prompt('jev.connection_test'))
        self.assertEqual(error.exception.code, 'missing_key')
        post.assert_not_called()

    def test_sentiment_without_context_cannot_enter_generative_workflow(self):
        from services.ai_service import call_ai_with_web_search
        with patch('services.ai_service._call_generative_with_web_search') as generative:
            for kind in ('sentiment_analysis', 'watchlist_sentiment_analysis', 'webull_equity_analysis', 'webull_event_contract_batch_analysis'):
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    call_ai_with_web_search(user_id=1, prompt_type=kind)
            generative.assert_not_called()
