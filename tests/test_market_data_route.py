import unittest
from unittest.mock import patch

from flask import Flask

import routes.market as market


class PublicCryptoMarketDataRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_public_crypto_quote_does_not_require_trading_credentials(self):
        with self.app.app_context(), \
             patch.object(market, 'fetch_crypto_price', return_value=77_388.30) as fetch_price:
            response = market.api_market_data.__wrapped__('BTCUSD')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            'price': 77_388.30,
            'symbol': 'BTC',
            'source': 'binance_us',
        })
        fetch_price.assert_called_once_with('BTC')

    def test_public_crypto_quote_reports_an_unavailable_symbol(self):
        with self.app.app_context(), \
             patch.object(market, 'fetch_crypto_price', return_value=None):
            response, status_code = market.api_market_data.__wrapped__('UNKNOWNUSD')

        self.assertEqual(status_code, 502)
        self.assertEqual(response.get_json()['error'], 'No public Binance.US price is available for UNKNOWN.')


if __name__ == '__main__':
    unittest.main()