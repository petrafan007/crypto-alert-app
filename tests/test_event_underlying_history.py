import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routes.system import _event_underlying_history_points, _get_event_underlying_history


class EventUnderlyingHistoryTests(unittest.TestCase):
    def test_normalizes_valid_minute_bars_and_deduplicates_timestamps(self):
        points = _event_underlying_history_points([
            {'time': 1_000, 'close': '100.25'},
            {'time': 1_000, 'close': '101.25'},
            {'time': 1_060, 'close': '102.50'},
            {'time': 1_120, 'close': 'not-a-price'},
        ])

        self.assertEqual(points, [
            {'timestamp': 1_000, 'price': 101.25},
            {'timestamp': 1_060, 'price': 102.50},
        ])

    def test_uses_public_crypto_history_for_crypto_event_underlyings(self):
        expected = [{'timestamp': 1_000 + index * 60, 'price': 100 + index} for index in range(16)]
        with patch('routes.system._get_public_crypto_minute_history', return_value=(expected, 'binance_us')) as history:
            points, source = _get_event_underlying_history(None, 'production', 'BTCUSD', 'CRYPTO')

        self.assertEqual(points, expected)
        self.assertEqual(source, 'binance_us')
        history.assert_called_once_with('BTCUSD')

    def test_uses_webull_m1_bars_for_financial_event_underlyings(self):
        credential = SimpleNamespace(
            webull_app_key='app-key',
            webull_app_secret='app-secret',
            webull_access_token='access-token',
        )
        bars = [{'time': 1_000 + index * 60, 'close': 100 + index} for index in range(16)]
        with patch('routes.system.get_webull_market_bars', return_value=bars) as market_bars:
            points, source = _get_event_underlying_history(credential, 'production', 'SPY', 'EQUITY')

        self.assertEqual(source, 'webull')
        self.assertEqual(points[0], {'timestamp': 1_000, 'price': 100.0})
        self.assertEqual(len(points), 16)
        self.assertEqual(market_bars.call_args.kwargs['interval'], 'M1')
        self.assertEqual(market_bars.call_args.kwargs['limit'], 20)


if __name__ == '__main__':
    unittest.main()