import unittest

from datetime import datetime, timezone

from services.webull_paper_rules import (
    canonical_paper_instrument_type,
    grouped_reserved_quantity,
    paper_order_fills_immediately,
    paper_order_type_label,
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

    def test_options_do_not_fill_outside_regular_market_hours(self):
        saturday = datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc)
        monday_open = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
        self.assertFalse(paper_order_fills_immediately('LIMIT', 'OPTION', saturday))
        self.assertTrue(paper_order_fills_immediately('LIMIT', 'OPTION', monday_open))

    def test_paper_order_type_caption_is_human_readable(self):
        self.assertEqual(paper_order_type_label('STOP_LOSS_LIMIT'), 'Stop Loss Limit')

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

    def test_event_limit_order_below_ask_sits_as_working_order(self):
        from unittest.mock import patch, MagicMock
        from services.webull_paper_trading_service import execute_webull_test_order

        account_mock = MagicMock(cash_balance=100.0, user_id=1)
        quote = {
            'symbol': 'KXBTC-TEST',
            'yes_ask': 0.47,
            'yes_bid': 0.45,
            'no_ask': 0.55,
            'no_bid': 0.53,
            'status': 'active',
        }
        order_data = {
            'symbol': 'KXBTC-TEST',
            'side': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 10,
            'limit_price': 0.10,
            'instrument_type': 'EVENT',
            'event_outcome': 'yes',
            '_event_market_rules': {
                'max_quantity': 100,
                'fractionable': False,
                'price_ranges': [{'start': 0.01, 'end': 0.99, 'step': 0.01}],
            },
            '_event_market': quote,
        }

        with patch('services.webull_paper_trading_service.db.session'), \
             patch('services.webull_paper_trading_service._lock_webull_test_account', return_value=account_mock), \
             patch('services.webull_paper_trading_service.fetch_live_price', return_value=0.47), \
             patch('services.webull_paper_trading_service._reserved_cash_amount', return_value=0.0), \
             patch('services.webull_paper_trading_service._reserved_short_margin', return_value=0.0), \
             patch('services.webull_paper_trading_service._current_short_margin', return_value=0.0), \
             patch('services.webull_paper_trading_service._find_or_merge_position', return_value=None):

            result = execute_webull_test_order(1, order_data)

            self.assertTrue(result['success'])
            self.assertEqual(result['status'], 'Working')
            self.assertIn('working', result['message'].lower())

    def test_event_limit_order_at_or_above_ask_fills_with_price_improvement(self):
        from unittest.mock import patch, MagicMock
        from services.webull_paper_trading_service import execute_webull_test_order

        account_mock = MagicMock(cash_balance=100.0, user_id=1)
        quote = {
            'symbol': 'KXBTC-TEST',
            'yes_ask': 0.47,
            'yes_bid': 0.45,
            'no_ask': 0.55,
            'no_bid': 0.53,
            'status': 'active',
        }
        order_data = {
            'symbol': 'KXBTC-TEST',
            'side': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 10,
            'limit_price': 0.50,
            'instrument_type': 'EVENT',
            'event_outcome': 'yes',
            '_event_market_rules': {
                'max_quantity': 100,
                'fractionable': False,
                'price_ranges': [{'start': 0.01, 'end': 0.99, 'step': 0.01}],
            },
            '_event_market': quote,
        }

        with patch('services.webull_paper_trading_service.db.session'), \
             patch('services.webull_paper_trading_service._lock_webull_test_account', return_value=account_mock), \
             patch('services.webull_paper_trading_service.fetch_live_price', return_value=0.47), \
             patch('services.webull_paper_trading_service._reserved_cash_amount', return_value=0.0), \
             patch('services.webull_paper_trading_service._reserved_short_margin', return_value=0.0), \
             patch('services.webull_paper_trading_service._current_short_margin', return_value=0.0), \
             patch('services.webull_paper_trading_service._find_or_merge_position', return_value=None):

            result = execute_webull_test_order(1, order_data)

            self.assertTrue(result['success'])
            self.assertEqual(result['status'], 'Filled')
            self.assertAlmostEqual(float(result['filled_price']), 0.47)
            self.assertIn('executed', result['message'].lower())


if __name__ == '__main__':
    unittest.main()
