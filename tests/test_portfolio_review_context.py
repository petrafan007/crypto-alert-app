import unittest
from types import SimpleNamespace

from services.portfolio_review_context import format_portfolio_review_holdings


class PortfolioReviewContextTests(unittest.TestCase):
    def test_formats_binance_and_every_webull_asset_class_including_cash(self):
        binance = [SimpleNamespace(symbol='btc', amount=0.5, current_price=60_000, initial_price=0)]
        webull = [
            {
                'symbol': 'USD', 'instrument_type': 'CASH', 'account_label': 'Individual Cash ••••AFZ7',
                'amount': 100.24, 'current_price': 1, 'current_value': 100.24,
            },
            {
                'symbol': 'AAPL', 'instrument_type': 'EQUITY', 'account_label': 'Individual Cash ••••AFZ7',
                'amount': 0.14929, 'current_price': 315.57, 'current_value': 47.11,
                'cost_basis': 46.65, 'webull_unrealized_pnl': 0.46,
            },
            {
                'symbol': 'EVT-YES', 'instrument_type': 'EVENT', 'account_label': 'Events',
                'amount': 20, 'current_price': 0.26, 'current_value': 5.20,
                'cost_basis': 5.0, 'webull_unrealized_pnl': 0.20,
            },
        ]

        result = format_portfolio_review_holdings(binance, webull)

        self.assertIn('Binance.US | BTC | CRYPTO', result)
        self.assertIn('Webull | Individual Cash ••••AFZ7 | USD | CASH', result)
        self.assertIn('Webull | Individual Cash ••••AFZ7 | AAPL | EQUITY', result)
        self.assertIn('Webull | Events | EVT-YES | EVENT', result)
        self.assertIn('unrealized_pnl=$0.46', result)


if __name__ == '__main__':
    unittest.main()
