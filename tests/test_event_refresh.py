"""Event scan evidence must survive slow inference without becoming falsely fresh."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from services.event_market_timing import normalise_quote_times, quote_freshness
from services.event_quote_refresh import expire_prediction, refresh_markets, replace_quote


class EventRefreshTests(unittest.TestCase):
    def market(self, symbol='TEST'):
        return {'symbol': symbol, 'yes_ask': .4, 'yes_ask_size': 100,
                'quote_as_of': datetime.utcnow().isoformat(),
                'cutoff_at': (datetime.utcnow()+timedelta(minutes=15)).isoformat()}

    def test_refresh_requests_exact_contracts_and_does_not_keep_omitted_depth(self):
        market = self.market()
        with patch('services.webull_service.get_webull_event_snapshots', return_value={
                'TEST': {'symbol': 'TEST', 'yes_ask': .45}}) as fetch:
            self.assertEqual(refresh_markets([market], ('key', 'secret', 'test', 'token')), [])
        fetch.assert_called_once_with('key', 'secret', 'test', 'token', symbols=['TEST'], force=True)
        self.assertEqual(market['yes_ask'], .45)
        self.assertNotIn('yes_ask_size', market)
        self.assertEqual(quote_freshness(market)['status'], 'UNKNOWN')

    def test_missing_wrong_and_failed_quotes_clear_old_executable_evidence(self):
        for response in ({}, {'TEST': {'symbol': 'WRONG', 'yes_ask': .2}}, OSError('offline')):
            with self.subTest(response=response):
                market = self.market()
                kwargs = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
                with patch('services.webull_service.get_webull_event_snapshots', **kwargs):
                    self.assertTrue(refresh_markets([market], ('key', 'secret')))
                self.assertNotIn('yes_ask', market)
                self.assertNotIn('quote_as_of', market)

    def test_expired_and_closed_contracts_are_not_requested(self):
        expired, closed = self.market(), self.market('CLOSED')
        expired['cutoff_at'] = (datetime.utcnow()-timedelta(seconds=1)).isoformat()
        closed['tradable_status'] = 'CO'
        with patch('services.webull_service.get_webull_event_snapshots') as fetch:
            self.assertEqual(refresh_markets([expired, closed], ('key', 'secret')), [])
        fetch.assert_not_called()

    def test_cancellation_is_not_swallowed_as_provider_failure(self):
        with patch('services.webull_service.get_webull_event_snapshots') as fetch:
            with self.assertRaisesRegex(RuntimeError, 'Stopped'):
                refresh_markets([self.market()], ('key', 'secret'),
                                lambda: (_ for _ in ()).throw(RuntimeError('Stopped')))
        fetch.assert_not_called()

    def test_quote_time_preserves_provider_age_over_receipt_time(self):
        now = datetime.utcnow()
        fields = normalise_quote_times({'quote_time': (now-timedelta(minutes=2)).isoformat()}, now)
        self.assertEqual(fields['quote_timestamp_source'], 'quote_time')
        self.assertEqual(quote_freshness(fields, now)['status'], 'STALE')

    def test_repricing_never_extends_forecast_ttl(self):
        now = datetime.utcnow()
        for status in ('cached', 'success'):
            for seconds, valid in ((10, True), (300, True), (301, False), (-6, False)):
                with self.subTest(status=status, seconds=seconds):
                    market = self.market()
                    market.update(model_probability_yes=.8, model_confidence=.9,
                        _model_metadata={'status': status, 'generated_at': (now-timedelta(seconds=seconds)).isoformat()})
                    replace_quote(market, {'symbol': 'TEST', 'yes_ask': .45, 'quote_as_of': now.isoformat()})
                    expire_prediction(market, now, 300)
                    self.assertEqual('model_probability_yes' in market, valid)
                    self.assertEqual(quote_freshness(market, now)['status'], 'FRESH')
