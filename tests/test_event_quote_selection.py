"""Regressions for the Event Contract candidate selection and underlying evidence.

The Event module was rejecting effectively every contract it discovered. Four
separate defects stacked on top of each other, and each one is pinned here:

1. The candidate ranking fell back to the symbol string, which selected the
   lowest strikes of an expiry. Those are the contracts furthest from the
   money, which the provider quotes one-sided, so they cannot be traded.
2. The hourly series encodes its settlement as ``-26OCT21H1400``. Without a
   parse for that form the cutoff fell back to the end of the trading day.
3. The underlying spot price was never supplied in exact-series mode, so the
   Decision Engine had no evidence and returned zero confidence.
4. The underlying price came from the recorded price history, which is
   written on a per-portfolio cadence and is routinely older than the
   freshness bound the Decision Engine requires.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from event_algo import (
    _cutoff_from_symbol,
    _event_series_index,
    _event_series_underlying,
    _get_crypto_spot_quote,
    _get_index_level_quote,
)
from services.event_market_timing import underlying_observation
from services.webull_service import (
    _event_market_strike_proximity_key,
    _event_snapshot_has_executable_book,
    _event_symbol_interval,
    _event_symbol_strike,
)

NOW = datetime(2026, 9, 13, 15, tzinfo=timezone.utc)


class ExecutableBookTests(unittest.TestCase):
    """A contract is tradeable only with a two-sided book."""

    def test_a_two_sided_book_is_executable(self):
        snapshot = {'yes_bid': 0.28, 'yes_ask': 0.29, 'no_bid': 0.71, 'no_ask': 0.72}
        self.assertTrue(_event_snapshot_has_executable_book(snapshot))

    def test_a_one_sided_book_is_not_executable(self):
        """The engine's previous candidates quoted only one side."""
        self.assertFalse(_event_snapshot_has_executable_book(
            {'yes_bid': 0.98, 'yes_ask': None, 'no_bid': None, 'no_ask': 0.02}))

    def test_a_missing_or_empty_book_is_not_executable(self):
        self.assertFalse(_event_snapshot_has_executable_book({}))
        self.assertFalse(_event_snapshot_has_executable_book(None))
        self.assertFalse(_event_snapshot_has_executable_book(
            {'yes_bid': 0.0, 'yes_ask': 0.0, 'no_bid': 0.0, 'no_ask': 0.0}))

    def test_an_out_of_range_price_is_not_executable(self):
        self.assertFalse(_event_snapshot_has_executable_book(
            {'yes_bid': 0.28, 'yes_ask': 1.5, 'no_bid': 0.71, 'no_ask': 0.72}))


class StrikeSelectionTests(unittest.TestCase):
    """The strike ladder must be ranked by distance from the money."""

    def test_the_strike_is_read_from_the_symbol(self):
        self.assertEqual(_event_symbol_strike({'symbol': 'KXBTCD-26OCT2317-T75499.99'}), 75499.99)
        self.assertIsNone(_event_symbol_strike({'symbol': 'KXBTCD-26OCT2317'}))

    def test_the_nearest_strike_sorts_first(self):
        market = {'symbol': 'KXBTCD-26OCT2317-T75499.99'}
        near = _event_market_strike_proximity_key(market, 80000.0)
        far = _event_market_strike_proximity_key({'symbol': 'KXBTCD-26OCT2317-T69499.99'}, 80000.0)
        self.assertLess(near, far)

    def test_a_contract_without_a_reference_price_sorts_last(self):
        """Without a reference price nothing can be ranked, so none displaces."""
        without = _event_market_strike_proximity_key({'symbol': 'KXBTCD-26OCT2317-T75499.99'})
        with_reference = _event_market_strike_proximity_key(
            {'symbol': 'KXBTCD-26OCT2317-T75499.99'}, 80000.0)
        self.assertGreater(without, with_reference)

    def test_a_contract_without_a_strike_sorts_last(self):
        without = _event_market_strike_proximity_key({'symbol': 'KXBTC15M-26OCT211515-15'}, 80000.0)
        self.assertEqual(without[0], 1)


class HourlyCutoffTests(unittest.TestCase):
    """The hourly series encodes an explicit settlement time."""

    def test_the_hourly_symbol_resolves_to_its_own_settlement(self):
        """The cutoff must not drift to the end of the trading day."""
        interval = _event_symbol_interval('KXINXU-26OCT21H1600-T7569.9999')
        self.assertIsNotNone(interval)
        self.assertEqual(interval['minutes'], 60)
        self.assertEqual(interval['end'].hour, 16)
        self.assertEqual(interval['end'].minute, 0)
        self.assertEqual(interval['start'], interval['end'] - timedelta(minutes=60))

    def test_the_hourly_cutoff_is_converted_to_utc(self):
        cutoff = _cutoff_from_symbol('KXINXU-26OCT21H1600-T7569.9999')
        self.assertIsNotNone(cutoff)
        # 16:00 Eastern is 20:00 UTC during daylight saving time.
        self.assertEqual(cutoff, datetime(2026, 10, 21, 20, 0))

    def test_the_daily_symbol_still_resolves_its_cutoff(self):
        cutoff = _cutoff_from_symbol('KXBTCD-26OCT2317-T75499.99')
        self.assertIsNotNone(cutoff)
        self.assertEqual(cutoff, datetime(2026, 10, 23, 21, 0))

    def test_the_fifteen_minute_symbol_still_resolves_its_cutoff(self):
        interval = _event_symbol_interval('KXBTC15M-26OCT211515-15')
        self.assertIsNotNone(interval)
        self.assertEqual(interval['minutes'], 15)


class SeriesUnderlyingTests(unittest.TestCase):
    """Each Event series must resolve to the asset it settles against."""

    def test_a_crypto_series_resolves_to_its_asset(self):
        self.assertEqual(_event_series_underlying('KXBTCD'), 'BTC')
        self.assertEqual(_event_series_underlying('KXBTC15M'), 'BTC')
        self.assertEqual(_event_series_underlying('KXETH15M'), 'ETH')

    def test_an_index_series_resolves_to_its_tracking_etf(self):
        self.assertEqual(_event_series_index('KXINXU'), ('SPY', 10.0))

    def test_an_unknown_series_resolves_to_nothing(self):
        self.assertIsNone(_event_series_underlying('KXUNKNOWN'))
        self.assertIsNone(_event_series_index('KXUNKNOWN'))


class UnderlyingEvidenceTests(unittest.TestCase):
    """The underlying observation must satisfy the Decision Engine's bound."""

    def test_the_provider_snapshot_supplies_a_fresh_underlying(self):
        """The recorded history is minutes old and is rejected as missing."""
        retrieved = datetime.now(timezone.utc)
        with patch('services.webull_service.get_webull_market_snapshot') as snapshot:
            snapshot.return_value = {'symbol': 'BTCUSD', 'price': 84360.14,
                                     'as_of': int(retrieved.timestamp() * 1000)}
            quote = _get_crypto_spot_quote('BTC', user_id=1, connection=('k', 's', 'production', 't'))
        self.assertIsNotNone(quote)
        self.assertEqual(quote['underlying_price'], 84360.14)
        self.assertEqual(quote['underlying_price_source'], 'WEBULL_CRYPTO_SNAPSHOT')
        self.assertEqual(underlying_observation(quote, retrieved)['status'], 'FRESH')

    def test_a_stale_provider_snapshot_is_not_accepted_as_evidence(self):
        retrieved = datetime.now(timezone.utc)
        stale = retrieved - timedelta(seconds=120)
        with patch('services.webull_service.get_webull_market_snapshot') as snapshot:
            snapshot.return_value = {'symbol': 'BTCUSD', 'price': 84360.14,
                                     'as_of': int(stale.timestamp() * 1000)}
            quote = _get_crypto_spot_quote('BTC', user_id=1, connection=('k', 's', 'production', 't'))
        self.assertIsNone(quote)

    def test_the_index_level_is_scaled_to_the_struck_level(self):
        retrieved = datetime.now(timezone.utc)
        with patch('services.webull_service.get_webull_market_snapshot') as snapshot:
            snapshot.return_value = {'symbol': 'SPY', 'price': 771.96,
                                     'as_of': int(retrieved.timestamp() * 1000)}
            quote = _get_index_level_quote('KXINXU', user_id=1, connection=('k', 's', 'production', 't'))
        self.assertIsNotNone(quote)
        self.assertAlmostEqual(quote['underlying_price'], 7719.6, places=4)
        self.assertEqual(underlying_observation(quote, retrieved)['status'], 'FRESH')

    def test_an_unknown_series_has_no_index_quote(self):
        self.assertIsNone(_get_index_level_quote('KXUNKNOWN', user_id=1, connection=('k', 's', 'production', 't')))


if __name__ == '__main__':
    unittest.main()
