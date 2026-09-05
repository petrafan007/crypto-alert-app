import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from services import provider_resilience as r
from services.ai_service import event_search_queries, validated_search_queries, web_search


class ProviderResilienceTests(unittest.TestCase):
    def setUp(self):
        r._memory.clear()
        r._inflight.clear()

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

    def test_search_failure_returns_zero_sources_and_cools_down(self):
        with patch('services.ai_service.get_user_credentials', return_value=None), patch.object(r.requests, 'get', side_effect=requests.ConnectTimeout('outage')) as get:
            self.assertEqual(web_search('BTC news', username='alice'), [])
            self.assertEqual(web_search('ETH news', username='alice'), [])
        self.assertEqual(get.call_count, 1)

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


if __name__ == '__main__':
    unittest.main()
