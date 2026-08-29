import unittest

from services.webull_paper_rules import (
    canonical_paper_instrument_type,
    grouped_reserved_quantity,
    paper_order_fills_immediately,
    paper_position_valuation,
    paper_reservation_group,
)


class WebullPaperTradingRulesTests(unittest.TestCase):
    def test_known_etf_retains_etf_identity(self):
        self.assertEqual(canonical_paper_instrument_type('SPY', 'EQUITY'), 'ETF')
        self.assertEqual(canonical_paper_instrument_type('QQQ', 'ETF'), 'ETF')
        self.assertEqual(canonical_paper_instrument_type('TSLA', 'EQUITY'), 'EQUITY')

    def test_conditional_and_auction_orders_are_working_at_placement(self):
        for order_type in (
            'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TRAILING_STOP_LOSS',
            'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN',
        ):
            with self.subTest(order_type=order_type):
                self.assertFalse(paper_order_fills_immediately(order_type))
        self.assertTrue(paper_order_fills_immediately('MARKET'))
        self.assertTrue(paper_order_fills_immediately('LIMIT'))

    def test_short_position_is_a_negative_liability_with_inverse_pnl(self):
        valuation = paper_position_valuation('SHORT', 2, 100, 90)
        self.assertEqual(valuation['market_value'], -180)
        self.assertEqual(valuation['cost_basis'], 200)
        self.assertEqual(valuation['unrealized_pnl'], 20)

        losing_valuation = paper_position_valuation('SHORT', 2, 100, 110)
        self.assertEqual(losing_valuation['market_value'], -220)
        self.assertEqual(losing_valuation['unrealized_pnl'], -20)

    def test_bracket_and_combo_siblings_reserve_only_the_largest_leg(self):
        orders = [
            {'order_id': 'SIM_ABC_TP', 'side': 'SELL', 'status': 'Working', 'quantity': 10},
            {'order_id': 'SIM_ABC_SL', 'side': 'SELL', 'status': 'Working', 'quantity': 10},
            {'order_id': 'SIM_COMBO_X_LEG1', 'side': 'SELL', 'status': 'Working', 'quantity': 5},
            {'order_id': 'SIM_COMBO_X_LEG2', 'side': 'SELL', 'status': 'Working', 'quantity': 7},
            {'order_id': 'SIM_OTHER', 'side': 'SELL', 'status': 'Working', 'quantity': 2},
            {'order_id': 'SIM_FILLED', 'side': 'SELL', 'status': 'Filled', 'quantity': 100},
        ]
        self.assertEqual(paper_reservation_group('SIM_ABC_TP'), 'SIM_ABC')
        self.assertEqual(paper_reservation_group('SIM_COMBO_X_LEG2'), 'SIM_COMBO_X')
        self.assertEqual(grouped_reserved_quantity(orders), 19)

    def test_partial_fill_reserves_only_outstanding_quantity(self):
        orders = [
            {
                'order_id': 'SIM_ONE', 'side': 'SELL_TO_CLOSE', 'status': 'Partially Filled',
                'quantity': 10, 'filled_quantity': 4,
            },
        ]
        self.assertEqual(grouped_reserved_quantity(orders), 6)


if __name__ == '__main__':
    unittest.main()
