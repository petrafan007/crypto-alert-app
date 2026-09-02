import unittest

from routes.portfolio import _build_tax_transactions


class TaxReportCalculationTests(unittest.TestCase):
    def test_fifo_mixed_sale_splits_short_and_long_term_gain(self):
        transactions, fifo_lots = _build_tax_transactions([
            {
                'id': 1,
                'date': '2024-01-01T12:00:00',
                'type': 'BUY',
                'asset': 'BTC',
                'amount': 1.0,
                'cost_basis': 100.0,
                'fee': 0.0,
                'price_sold_at': 100.0,
            },
            {
                'id': 2,
                'date': '2025-06-01T12:00:00',
                'type': 'BUY',
                'asset': 'BTC',
                'amount': 1.0,
                'cost_basis': 200.0,
                'fee': 0.0,
                'price_sold_at': 200.0,
            },
            {
                'id': 3,
                'date': '2025-07-01T12:00:00',
                'type': 'SELL',
                'asset': 'BTC',
                'amount': -1.5,
                'proceeds': 450.0,
                'cost_basis': 0.0,
                'fee': 0.0,
                'price_sold_at': 300.0,
            },
        ])

        sale = transactions[-1]
        self.assertEqual(sale['gain_loss_type'], 'mixed')
        self.assertAlmostEqual(sale['gain_loss'], 250.0)
        self.assertAlmostEqual(sale['long_term_gain_loss'], 200.0)
        self.assertAlmostEqual(sale['short_term_gain_loss'], 50.0)
        self.assertEqual(sale['holding_days'], None)
        self.assertAlmostEqual(fifo_lots['BTC'][0]['amount'], 0.5)
        self.assertAlmostEqual(fifo_lots['BTC'][0]['cost'], 100.0)

    def test_exact_365_day_holding_is_long_term(self):
        transactions, _ = _build_tax_transactions([
            {
                'id': 1,
                'date': '2024-01-01T12:00:00',
                'type': 'BUY',
                'asset': 'ETH',
                'amount': 1.0,
                'cost_basis': 100.0,
                'price_sold_at': 100.0,
            },
            {
                'id': 2,
                'date': '2024-12-31T12:00:00',
                'type': 'SELL',
                'asset': 'ETH',
                'amount': -1.0,
                'proceeds': 150.0,
                'price_sold_at': 150.0,
            },
        ])

        sale = transactions[-1]
        self.assertEqual(sale['gain_loss_type'], 'long_term')
        self.assertEqual(sale['holding_days'], 365)
        self.assertAlmostEqual(sale['long_term_gain_loss'], 50.0)
        self.assertAlmostEqual(sale['short_term_gain_loss'], 0.0)


if __name__ == '__main__':
    unittest.main()
