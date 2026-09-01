import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes import portfolio


class TradingKlinesTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_missing_binance_credentials_falls_back_without_unbound_credential(self):
        credential_model = Mock()
        credential_model.query.filter.return_value.first.return_value = None
        fallback_bars = [{
            "time": 1788220800,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 25.0,
        }]

        with self.app.test_request_context("/api/trading/klines/AAPL?interval=1d&limit=2"), \
                patch.object(portfolio, "Credential", credential_model), \
                patch.object(portfolio, "_KLINES_CACHE", {}), \
                patch.object(portfolio, "_fetch_yfinance_klines", return_value=fallback_bars):
            response = portfolio.get_trading_klines("AAPL")

        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["source"], "yfinance")
        self.assertEqual(payload["klines"], fallback_bars)


if __name__ == "__main__":
    unittest.main()
