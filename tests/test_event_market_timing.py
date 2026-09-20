"""Event quote and underlying observations must retain their actual time basis."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from event_algo import _event_model_context, _get_crypto_spot_quote, _market_features, _market_provider_timestamp, _snapshot_model
from services.event_market_timing import observation_time, quote_freshness, underlying_observation
from services.webull_service import _normalise_event_snapshot, _normalise_event_market, get_webull_event_snapshots
from services import portfolio_event_execution as handoff


class EventMarketTimingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 13, 15, tzinfo=timezone.utc)

    def normalise(self, **fields):
        with patch('services.webull_service.datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now
            return _normalise_event_snapshot({'symbol': 'TEST', 'yes_bid': '.39', 'yes_ask': '.4', **fields})

    def test_old_provider_quote_is_not_refreshed_by_retrieval_or_last_trade(self):
        old = self.now - timedelta(minutes=2)
        market = self.normalise(timestamp=int(old.timestamp()*1000), last_trade_time=self.now.timestamp())
        self.assertEqual(market['quote_as_of'], old.isoformat())
        self.assertEqual(market['quote_retrieved_at'], self.now.isoformat())
        self.assertEqual(market['quote_time_basis'], 'PROVIDER')
        self.assertEqual(_market_provider_timestamp(market), old.replace(tzinfo=None))
        self.assertEqual(quote_freshness(market, self.now)['status'], 'STALE')

    def test_no_quote_timestamp_discloses_retrieval_basis_and_separate_trade_time(self):
        old_trade = self.now - timedelta(days=1)
        market = self.normalise(last_trade_time=int(old_trade.timestamp()*1000))
        timing = quote_freshness(market, self.now)
        self.assertIsNone(market['quote_as_of'])
        self.assertIsNone(_market_provider_timestamp(market))
        self.assertEqual(timing['basis'], 'RETRIEVAL_ONLY')
        self.assertEqual(timing['status'], 'FRESH')
        self.assertEqual(timing['last_trade_at'], old_trade.isoformat())
        self.assertEqual(quote_freshness({'last_trade_time': self.now.timestamp()}, self.now)['status'], 'UNKNOWN')
        self.assertEqual(quote_freshness(market, self.now + timedelta(seconds=31))['status'], 'STALE')

    def test_invalid_and_future_provider_times_cannot_fall_back_to_retrieval(self):
        invalid = self.normalise(timestamp='invalid')
        self.assertEqual(quote_freshness(invalid, self.now)['status'], 'INVALID')
        self.assertEqual(invalid['quote_provider_timestamp_raw'], 'invalid')
        future = self.normalise(timestamp=(self.now + timedelta(seconds=6)).isoformat())
        self.assertEqual(quote_freshness(future, self.now)['status'], 'FUTURE')
        for seconds in (-5, 0, 30):
            market = self.normalise(timestamp=(self.now - timedelta(seconds=seconds)).isoformat())
            self.assertEqual(quote_freshness(market, self.now)['status'], 'FRESH')

    def test_snapshot_cache_keeps_original_receipt_time(self):
        with patch.dict('services.webull_service._WEBULL_EVENT_SNAPSHOT_CACHE', {}, clear=True), \
                patch('services.webull_service._webull_request') as request, \
                patch('services.webull_service._response_payload', return_value=[{'symbol': 'TEST', 'yes_ask': '.4'}]), \
                patch('services.webull_service.datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now
            first = get_webull_event_snapshots('test-key', 'test-secret', symbols=['TEST'])['TEST']
            clock.now.return_value = self.now + timedelta(seconds=4)
            cached = get_webull_event_snapshots('test-key', 'test-secret', symbols=['TEST'])['TEST']
        request.assert_called_once()
        self.assertEqual(first['quote_retrieved_at'], cached['quote_retrieved_at'])
        self.assertEqual(cached['quote_retrieved_at'], self.now.isoformat())

    def test_stale_or_unverifiable_underlying_price_is_not_current_model_input(self):
        for timestamp, status in ((None, 'UNKNOWN'), ('bad', 'INVALID'),
                                  (self.now - timedelta(seconds=31), 'STALE'),
                                  (self.now + timedelta(seconds=6), 'FUTURE')):
            with self.subTest(status=status):
                market = {'underlying_price': 60000, 'underlying_price_as_of': timestamp,
                          'underlying_price_retrieved_at': self.now, 'reference_price': 59000}
                observation = underlying_observation(market, self.now)
                self.assertIsNone(observation['price'])
                self.assertEqual(observation['observed_price'], 60000)
                self.assertEqual(observation['status'], status)
                features = _market_features(market, self.now.replace(tzinfo=None))
                self.assertIsNone(features['underlying_price'])
                self.assertIsNone(features['distance_to_reference'])
        context = _event_model_context({'underlying_price': 60000, 'underlying_price_as_of': '2020-01-01T00:00:00Z'})
        self.assertIsNone(context['underlying']['price'])
        self.assertEqual(context['underlying']['freshness']['status'], 'STALE')

    def test_fresh_underlying_and_snapshot_preserve_separate_timestamps(self):
        observed = self.now - timedelta(seconds=10)
        market = self.normalise(underlying_price=60000, underlying_price_as_of=observed.isoformat(), reference_price=59000)
        features = _market_features(market, self.now.replace(tzinfo=None))
        snapshot = _snapshot_model(1, 1, 1, market, features, self.now.replace(tzinfo=None))
        self.assertEqual(features['underlying_price'], 60000)
        self.assertEqual(features['distance_to_reference'], 1000)
        self.assertEqual(features['underlying_observation']['observed_at'], observed.isoformat())
        self.assertIsNone(snapshot.provider_timestamp)
        self.assertEqual(json.loads(snapshot.feature_json)['quote_freshness']['basis'], 'RETRIEVAL_ONLY')

    def test_cached_spot_observation_keeps_age_and_history_fallback_source(self):
        now = datetime.now(timezone.utc)
        stale = {'price': 99999, 'timestamp': int((now-timedelta(hours=2)).timestamp()*1000)}
        row = SimpleNamespace(price=60000, timestamp=int((now-timedelta(seconds=5)).timestamp()*1000))
        with patch('services.webull_streaming_service.get_latest_streaming_quote', return_value=stale), \
                patch('models.PriceHistory') as history:
            history.query.filter_by.return_value.order_by.return_value.first.return_value = row
            result = _get_crypto_spot_quote('BTC')
        self.assertEqual(result['underlying_price_source'], 'PRICE_HISTORY')
        self.assertEqual(result['underlying_price_as_of'], row.timestamp)
        self.assertEqual(underlying_observation(result, now)['price'], 60000)
        fresh = {'price': 61000, 'timestamp': now.isoformat()}
        with patch('services.webull_streaming_service.get_latest_streaming_quote', return_value=fresh), \
                patch('models.PriceHistory') as history:
            result = _get_crypto_spot_quote('BTC')
            history.query.filter_by.assert_not_called()
        self.assertEqual(result['underlying_price_source'], 'WEBULL_STREAM_CACHE')
        self.assertEqual(result['underlying_price_as_of'], now.isoformat())

    def test_handoff_uses_quote_basis_and_drops_prior_quote_timing(self):
        decision = SimpleNamespace(created_at=self.now.replace(tzinfo=None), contract_symbol='TEST', confidence=.9, probability_yes=.8, outcome='YES')
        config = SimpleNamespace(risk_config='{}', signal_config='{}', kill_switch=False)
        settings = {'min_confidence': .5, 'min_net_edge': .015}
        market = self.normalise(last_trade_time=(self.now-timedelta(days=1)).timestamp())
        market['cutoff_at'] = (self.now+timedelta(minutes=10)).isoformat()
        market['series_symbol'] = 'TEST'
        status, _, assessment = handoff.validate_entry(decision, market, config, settings, ['TEST'], self.now.replace(tzinfo=None))
        self.assertIsNone(status)
        self.assertEqual(assessment['features']['quote_freshness']['basis'], 'RETRIEVAL_ONLY')
        for fields in ({'timestamp': (self.now-timedelta(seconds=31)).isoformat()}, {'timestamp': 'bad'}):
            self.assertEqual(handoff.validate_entry(decision, self.normalise(**fields), config, settings, ['TEST'], self.now.replace(tzinfo=None))[0], 'MISSED')
        credential = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        with patch.object(handoff, 'db') as database, \
                patch('event_algo._webull_connection_for_user', return_value=(credential, 'test')), \
                patch('services.webull_service.get_webull_event_snapshots', return_value={'TEST': {'symbol': 'TEST', 'yes_ask': .4}}):
            database.session.get.return_value = SimpleNamespace(raw_json=json.dumps(market))
            refreshed = handoff.fresh_market(1, SimpleNamespace(snapshot_id=1, contract_symbol='TEST'))
        self.assertEqual(quote_freshness(refreshed, self.now)['status'], 'UNKNOWN')

    def test_timestamp_units_and_invalid_values(self):
        for value in (self.now, self.now.isoformat(), self.now.timestamp(), self.now.timestamp()*1000):
            self.assertEqual(observation_time(value), self.now)
        for value in (None, True, 'invalid', float('inf'), float('nan')):
            self.assertIsNone(observation_time(value))

    def test_underlying_spot_price_cannot_replace_contract_reference(self):
        snapshot = self.normalise(underlying_price=60000)
        self.assertEqual(snapshot['underlying_price'], 60000)
        self.assertNotIn('reference_price', snapshot)
        market = _normalise_event_market({'symbol': 'TEST', 'name': 'Test contract', 'underlying_price': 60000}, {})
        self.assertIsNone(market['reference_price'])
        self.assertEqual(self.normalise(underlying_price=60000, reference_price=59000)['reference_price'], 59000)
