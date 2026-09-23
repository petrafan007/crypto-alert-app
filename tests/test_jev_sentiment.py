import json
from datetime import timedelta
from unittest.mock import Mock, patch
from credentials import UserSetting
from core.extensions import db
from models import JevEvaluation, SentimentHistory
from services.jev_contracts import build_sentiment_questions
from services.jev_service import JevClient
from services.jev_sentiment import build_state, acceptance, mapped_result, run_sentiment
from services.jev_evaluations import create_evaluation, process_evaluation, update_evaluation, get_evaluation
from tests.jev_helpers import JevTestCase, response_for


class JevSentimentTests(JevTestCase):
    def setUp(self):
        super().setUp()
        JevClient._failures.clear()
        self.payload = response_for(build_sentiment_questions())
        self.kwargs = {'user_id': 1, 'username': 'jev-test', 'messages': [], 'symbol': 'BTC'}

    def first_mode(self, fallback=True):
        row = db.session.get(UserSetting, 1)
        row.jev_sentiment_mode = 'first'
        row.jev_generative_fallback_enabled = fallback
        db.session.commit()

    def test_point_in_time_excludes_future_and_unknown_retrieval(self):
        stamp = self.now.isoformat()
        evidence = [{'title': 'valid', 'available_at': stamp},
                    {'title': 'future', 'available_at': stamp, 'published_at': (self.now+timedelta(hours=1)).isoformat()},
                    {'title': 'not yet fetched', 'available_at': (self.now+timedelta(seconds=1)).isoformat()},
                    {'title': 'unknown'}]
        state = build_state(self.state, evidence, self.now)
        self.assertEqual([e['title'] for e in state['evidence']], ['valid'])
        self.assertNotIn('outcome_price', state)

    def test_label_mapping_and_score_conversion(self):
        for direction, expected in [('strong_bullish', 'Buy Immediately'), ('bullish', 'Consider Buying'), ('neutral', 'Hold'), ('bearish', 'Consider Selling'), ('strong_bearish', 'Sell Immediately')]:
            answers = response_for(build_sentiment_questions(), direction)['answers']
            self.assertEqual(mapped_result(answers)[0], expected)
            self.assertIn('4.0/5', mapped_result(answers)[1])
        self.assertEqual(mapped_result(response_for(build_sentiment_questions(), 'bearish')['answers'], True)[0], 'Avoid')
        self.assertEqual(mapped_result(response_for(build_sentiment_questions(), 'neutral')['answers'], True)[0], 'Watch')

    def test_confidence_conflict_and_missing_evidence_abstain(self):
        answers = self.payload['answers']
        self.assertTrue(acceptance(answers, {}, self.config, self.state)[0])
        self.assertFalse(acceptance(answers, {'direction': .3}, self.config, self.state)[0])
        answers['conflicted']['probability'] = .9
        self.assertEqual(acceptance(answers, {}, self.config, self.state)[1], 'JEV_ESCALATED_CONFLICT')
        self.assertFalse(acceptance(answers, {}, self.config, {})[0])

    def test_disabled_or_stablecoin_makes_no_evaluation_call(self):
        original = Mock(return_value=(Mock(), 'original'))
        with patch('services.jev_sentiment.create_evaluation') as create:
            context = dict(self.state, symbol='USDT')
            self.assertEqual(run_sentiment(original, self.kwargs, context)[1], 'original')
            setting = db.session.get(UserSetting, 1); setting.jev_enabled = False; db.session.commit()
            self.assertEqual(run_sentiment(original, self.kwargs, self.state)[1], 'original')
            create.assert_not_called()

    def test_shadow_preserves_response_and_defers_network(self):
        response = Mock(provider='generative', model='test')
        def original(**kwargs):
            kwargs['evidence_observer']([{'title': 'News', 'available_at': self.now.isoformat()}])
            return response, 'original'
        with patch('services.portfolio_audit_lifecycle.active_audit', return_value=None), patch('services.jev_service.requests.post') as post:
            actual, prompt = run_sentiment(original, self.kwargs, self.state)
            self.assertIs(actual, response)
            self.assertEqual(prompt, 'original')
            post.assert_not_called()
        self.assertEqual(get_evaluation(actual.jev_evaluation_id).status, 'pending')

    def test_first_mode_accepted_avoids_generative(self):
        self.first_mode()
        original = Mock()
        with patch('services.portfolio_audit_lifecycle.active_audit', return_value=None), \
             patch('services.ai_service.news_api_search', return_value=[{'title': 'News'}]), \
             patch('services.ai_service.web_search', return_value=[]), \
             patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: self.payload)):
            response, _ = run_sentiment(original, self.kwargs, self.state)
        original.assert_not_called()
        self.assertEqual(json.loads(response.choices[0].message.content)['sentiment'], 'Consider Buying')
        row = get_evaluation(response.jev_evaluation_id)
        self.assertEqual(row.action_taken, 'sentiment')
        self.assertNotIn('synthetic-jev-secret', row.state_json + row.settings_json)

    def test_low_confidence_falls_back_and_disabled_fallback_is_explicit(self):
        self.first_mode()
        self.payload = response_for(build_sentiment_questions(), probability=.4)
        original = Mock(return_value=(Mock(), 'fallback'))
        with patch('services.portfolio_audit_lifecycle.active_audit', return_value=None), \
             patch('services.ai_service.news_api_search', return_value=[{'title': 'News'}]), \
             patch('services.ai_service.web_search', return_value=[]), \
             patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: self.payload)):
            response, prompt = run_sentiment(original, self.kwargs, self.state)
            self.assertEqual(prompt, 'fallback')
            self.assertTrue(get_evaluation(response.jev_evaluation_id).fallback_used)
            self.first_mode(fallback=False)
            with self.assertRaisesRegex(ValueError, 'fallback is disabled'):
                run_sentiment(original, self.kwargs, self.state)

    def test_evaluation_link_to_existing_history(self):
        from services.ai_service import record_sentiment_history
        record = record_sentiment_history(1, 'BTC', 'Hold', 'Reason', 100)
        evaluation_id = create_evaluation(1, 'sentiment', self.state, self.config)
        update_evaluation(evaluation_id, user_id=1, sentiment_history_id=record.id)
        self.assertEqual(get_evaluation(evaluation_id).sentiment_history_id, record.id)
        update_evaluation(evaluation_id, user_id=2, sentiment_history_id=999)
        self.assertEqual(get_evaluation(evaluation_id).sentiment_history_id, record.id)

    def test_full_first_sentiment_works_without_generative_prompts_and_links_history(self):
        from models import Coin
        from services.ai_service import analyze_single_symbol_sentiment
        self.first_mode()
        db.session.get(UserSetting, 1).ai_notifications_enabled = False
        db.session.add(Coin(user_id=1, symbol='BTC', current=100, amount=1))
        db.session.commit()
        with patch('services.portfolio_audit_lifecycle.active_audit', return_value=None), \
             patch('routes.helpers.fetch_crypto_price', return_value=100), \
             patch('services.price_history_service.get_last_nh_price_and_volume', return_value=([], 'Recorded history')), \
             patch('services.ai_service.news_api_search', return_value=[{'title': 'News'}]), \
             patch('services.ai_service.web_search', return_value=[]), \
             patch('services.ai_service._call_generative_with_web_search') as generative, \
             patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: self.payload)):
            label, reason = analyze_single_symbol_sentiment(1, 'jev-test', 'BTC', amount=1, force=True)
        self.assertEqual(label, 'Consider Buying')
        generative.assert_not_called()
        row = JevEvaluation.query.one()
        self.assertIsNotNone(row.sentiment_history_id)
        self.assertEqual(db.session.get(SentimentHistory, row.sentiment_history_id).provider, 'typesafe-ai')

    def test_provider_failure_clears_checking_state(self):
        from models import Coin
        from services.ai_service import analyze_single_symbol_sentiment
        self.first_mode(fallback=False)
        db.session.add(Coin(user_id=1, symbol='BTC', current=100, amount=1))
        db.session.commit()
        with patch('services.portfolio_audit_lifecycle.active_audit', return_value=None), \
             patch('routes.helpers.fetch_crypto_price', return_value=100), \
             patch('services.price_history_service.get_last_nh_price_and_volume', return_value=([], 'Recorded history')), \
             patch('services.ai_service.news_api_search', return_value=[{'title': 'News'}]), \
             patch('services.ai_service.web_search', return_value=[]), \
             patch('services.jev_service.requests.post', return_value=Mock(status_code=401)):
            with self.assertRaisesRegex(ValueError, 'fallback is disabled'):
                analyze_single_symbol_sentiment(1, 'jev-test', 'BTC', force=True)
        self.assertEqual(Coin.query.one().sentiment, 'Error')
        self.assertEqual(JevEvaluation.query.one().error_code, 'auth')


    def test_link_failure_does_not_escape_into_sentiment_result(self):
        from services.jev_evaluations import try_update_evaluation
        with patch('services.jev_evaluations.update_evaluation', side_effect=RuntimeError('storage failed')):
            self.assertFalse(try_update_evaluation(1, user_id=1, sentiment_history_id=2))

    def test_future_market_context_is_excluded(self):
        context = dict(self.state, market_context='future indicators',
                       market_available_at=(self.now+timedelta(seconds=1)).isoformat())
        self.assertNotIn('market_context', build_state(context, [], self.now))
        context['market_available_at'] = self.now.isoformat()
        self.assertEqual(build_state(context, [], self.now)['market_context'], 'future indicators')
