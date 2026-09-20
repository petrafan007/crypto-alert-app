import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from services import provider_resilience as r
from services.ai_service import event_search_queries, validated_search_queries, web_search


def search_response(code=200, body='', headers=None):
    response = Mock(status_code=code, text=body, content=body.encode(), headers=headers or {})
    response.json.side_effect = ValueError('Not JSON')
    return response


class ProviderResilienceTests(unittest.TestCase):
    def setUp(self):
        r._memory.clear()
        r._inflight.clear()
        r._request_locks.clear()

    def test_429_stops_subsequent_requests_and_exposes_owner_scoped_status(self):
        response = Mock(status_code=429, headers={'Retry-After': '120'})
        response.json.return_value = {'code': 'rateLimited'}
        with patch.object(r.requests, 'get', return_value=response) as get:
            for _ in range(2):
                with self.assertRaises(r.ProviderUnavailable):
                    r.checked_get('NewsAPI', 'alice', 'private-key', 'https://example.test')
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(r.health('alice')), 1)
        self.assertEqual(r.health('bob'), [])
        self.assertNotIn('private-key', str(r._memory))

    def test_daily_quota_waits_for_pacific_reset_not_short_retry_hint(self):
        now = datetime(2026, 9, 5, 16, tzinfo=timezone.utc)
        response = SimpleNamespace(headers={'Retry-After': '3'})
        seconds = r.retry_seconds(response, 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', now)
        self.assertEqual(seconds, 15*3600)
        self.assertEqual(r.retry_seconds(response, 'temporary throttle', now), 3)

    def test_cache_deduplicates_concurrent_requests_and_isolates_accounts(self):
        entered, release = threading.Event(), threading.Event()
        result = [{'url': 'https://example.test', 'title': 'Actual article'}]
        def fetch():
            entered.set()
            self.assertTrue(release.wait(2))
            return result
        output = []
        worker = threading.Thread(target=lambda: output.append(r.cached_search('alice', 'news', ['BTC'], fetch)))
        worker.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(r.cached_search('alice', 'news', ['BTC'], lambda: self.fail('duplicate request')), [])
        release.set()
        worker.join(2)
        self.assertEqual(output, [result])
        self.assertEqual(r.cached_search('alice', 'news', ['BTC'], lambda: self.fail('cache missed')), result)
        self.assertEqual(r.cached_search('bob', 'news', ['BTC'], lambda: []), [])

    def test_ollama_requests_are_serialized_across_accounts(self):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first_request():
            with r.serialized_ai_request('alice', 'ollama'):
                first_entered.set()
                self.assertTrue(release_first.wait(2))

        def second_request():
            with r.serialized_ai_request('bob', 'ollama'):
                second_entered.set()

        first = threading.Thread(target=first_request)
        second = threading.Thread(target=second_request)
        first.start()
        self.assertTrue(first_entered.wait(2))
        second.start()
        self.assertFalse(second_entered.wait(.1))
        release_first.set()
        first.join(2)
        second.join(2)
        self.assertTrue(second_entered.is_set())

    def test_search_failure_returns_zero_sources_and_cools_down(self):
        with patch('services.ai_service.get_user_credentials', return_value=None), \
                patch.object(r.requests, 'get', side_effect=requests.ConnectTimeout('outage')) as get, \
                patch.object(r.requests, 'post', side_effect=requests.ConnectTimeout('outage')) as post:
            self.assertEqual(web_search('BTC news', username='alice'), [])
            self.assertEqual(web_search('ETH news', username='alice'), [])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual({row['service'] for row in r.health('alice')}, {'DuckDuckGo', 'Google News RSS'})

    def test_post_throttle_is_shared_with_get_and_recovers_after_expiry(self):
        response = search_response(429, 'private response body', {'Retry-After': '120'})
        with patch.object(r.requests, 'post', return_value=response) as post, \
                patch.object(r.requests, 'get', return_value=search_response()) as get:
            with self.assertRaises(r.ProviderUnavailable):
                r.checked_post('DuckDuckGo', 'alice', '', 'https://example.test', unavailable_cooldown=60)
            with self.assertRaises(r.ProviderUnavailable):
                r.checked_get('DuckDuckGo', 'alice', '', 'https://example.test/other')
            get.assert_not_called()
            key = r.identity('provider', 'alice', 'DuckDuckGo', '')
            self.assertGreater((r.read(key)['expires_at']-datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds(), 110)
            self.assertNotIn('private response body', str(r._memory))
            r.checked_get('DuckDuckGo', 'bob', '', 'https://example.test/other')
            r._memory[key]['expires_at'] = datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1)
            r.checked_get('DuckDuckGo', 'alice', '', 'https://example.test/other')
        self.assertEqual((post.call_count, get.call_count), (1, 2))

    def test_search_challenge_cools_down_duckduckgo_but_google_results_still_work(self):
        rss = '<rss><channel><item><title>Actual article</title><link>https://example.test/news</link><description>Evidence</description><source>Publisher</source></item></channel></rss>'
        with patch('services.ai_service.get_user_credentials', return_value=None), \
                patch.object(r.requests, 'post', return_value=search_response(202, 'challenge')) as post, \
                patch.object(r.requests, 'get', return_value=search_response(body=rss)) as get:
            first = web_search('BTC news', username='alice')
            second = web_search('ETH news', username='alice')
            self.assertEqual((first[0]['title'], second[0]['source']), ('Actual article', 'Google News'))
            self.assertEqual(web_search('BTC news', username='alice'), first)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all('news.google.com/rss/' in call.args[0] for call in get.call_args_list))
        self.assertEqual([row['service'] for row in r.health('alice')], ['DuckDuckGo'])

    def test_empty_lite_page_can_fall_back_to_html_without_false_cooldown(self):
        html = '<div class="result"><a class="result__a" href="https://example.test/news">Actual article</a><div class="result__snippet">Evidence</div></div>'
        with patch('services.ai_service.get_user_credentials', return_value=None), \
                patch.object(r.requests, 'post', return_value=search_response(body='<html></html>')) as post, \
                patch.object(r.requests, 'get', return_value=search_response(body=html)) as get:
            result = web_search('BTC news', username='alice')
        self.assertEqual(result[0]['source'], 'DuckDuckGo')
        self.assertEqual((post.call_count, get.call_count), (1, 1))
        self.assertEqual(r.health('alice'), [])

    def test_event_queries_use_underlyings_and_reject_model_prose(self):
        queries = event_search_queries('EVENT_BATCH contracts KXBTC15M and KXETHD')
        self.assertEqual(len(queries), 2)
        self.assertIn('BTC', queries[0])
        self.assertIn('ETH', queries[1])
        self.assertNotIn('EVENT_BATCH', ' '.join(queries))
        self.assertEqual(validated_search_queries('We need to provide BTC estimates\nThe user wants BTC advice', 'BTC'), ['BTC latest market news today'])

    def test_optional_telegram_skips_network_for_disabled_or_unconfigured_accounts(self):
        from services.notification_service import send_telegram_message
        with patch('credentials.User') as user, patch('credentials.UserSetting') as settings, patch('services.notification_service.get_user_credentials') as credentials, patch('services.notification_service.requests.post') as post:
            user.query.filter_by.return_value.first.return_value = SimpleNamespace(id=1)
            settings.query.filter_by.return_value.first.return_value = SimpleNamespace(telegram_notifications_enabled=False)
            self.assertFalse(send_telegram_message('alice', 'message'))
            credentials.assert_not_called()
            settings.query.filter_by.return_value.first.return_value = None
            credentials.return_value = SimpleNamespace(telegram_token=None, telegram_chat_id=None)
            self.assertFalse(send_telegram_message('alice', 'message'))
            post.assert_not_called()

    def test_telegram_delivery_identifies_account_without_logging_token_or_message(self):
        from services.notification_service import send_telegram_message
        with patch('credentials.User') as user, patch('credentials.UserSetting') as settings, \
             patch('services.notification_service.get_user_credentials') as credentials, \
             patch('services.notification_service.requests.post') as post, \
             patch('services.notification_service.logger') as logger:
            user.query.filter_by.return_value.first.return_value = SimpleNamespace(id=1)
            settings.query.filter_by.return_value.first.return_value = SimpleNamespace(telegram_notifications_enabled=True)
            credentials.return_value = SimpleNamespace(id=12, telegram_token='secret-token', telegram_chat_id='private-chat')
            for code in (200, 401):
                post.return_value.status_code = code
                post.return_value.text = 'secret-token'
                self.assertEqual(send_telegram_message('alice', 'private message'), code == 200)
            post.side_effect = ConnectionError('https://api.telegram.org/botsecret-token/sendMessage')
            self.assertFalse(send_telegram_message('alice', 'private message'))
            output = str(logger.mock_calls)
            self.assertIn('alice', output)
            self.assertIn('401', output)
            self.assertNotIn('secret-token', output)
            self.assertNotIn('private-chat', output)
            self.assertNotIn('private message', output)


if __name__ == '__main__':
    unittest.main()
