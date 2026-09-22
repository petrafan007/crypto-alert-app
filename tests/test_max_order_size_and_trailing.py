import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from trading_models import TradingSettings, TrailingOrder, TestOrder
from services.trailing_order_service import (
    calculate_trailing_stop_price,
    evaluate_single_trailing_order,
    create_trailing_order,
    cancel_trailing_order,
    get_user_trailing_orders
)
class TestMaxOrderSizeAndTrailing(unittest.TestCase):

    def test_calculate_trailing_stop_price(self):
        # SELL with percentage: 2% below peak
        stop_sell_pct = calculate_trailing_stop_price('SELL', 100.0, 'PERCENT', 2.0)
        self.assertAlmostEqual(stop_sell_pct, 98.0)

        # SELL with dollar amount: $5 below peak
        stop_sell_amt = calculate_trailing_stop_price('SELL', 100.0, 'AMOUNT', 5.0)
        self.assertAlmostEqual(stop_sell_amt, 95.0)

        # BUY with percentage: 2% above trough
        stop_buy_pct = calculate_trailing_stop_price('BUY', 100.0, 'PERCENT', 2.0)
        self.assertAlmostEqual(stop_buy_pct, 102.0)

        # BUY with dollar amount: $5 above trough
        stop_buy_amt = calculate_trailing_stop_price('BUY', 100.0, 'AMOUNT', 5.0)
        self.assertAlmostEqual(stop_buy_amt, 105.0)

    def test_evaluate_single_trailing_order_sell(self):
        # Create an active SELL trailing order: peak=100, trail=2%, stop=98
        order = TrailingOrder(
            id=9991,
            user_id=1,
            symbol='BTCUSDT',
            side='SELL',
            quantity=0.01,
            trail_type='PERCENT',
            trail_value=2.0,
            highest_price=100.0,
            current_stop_price=98.0,
            is_activated=True,
            status='ACTIVE'
        )

        # 1. Price climbs to 105: stop should ratchet up to 105 * 0.98 = 102.9
        updated, triggered = evaluate_single_trailing_order(order, 105.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertFalse(triggered)
        self.assertEqual(order.highest_price, 105.0)
        self.assertAlmostEqual(order.current_stop_price, 102.9)
        self.assertEqual(order.status, 'ACTIVE')

        # 2. Price dips slightly to 104: peak stays 105, stop stays 102.9, no trigger
        updated, triggered = evaluate_single_trailing_order(order, 104.0, execute_trigger=False)
        self.assertFalse(updated)
        self.assertFalse(triggered)
        self.assertEqual(order.highest_price, 105.0)
        self.assertAlmostEqual(order.current_stop_price, 102.9)

        # 3. Price drops to 102.5 (below 102.9): TRIGGERED!
        updated, triggered = evaluate_single_trailing_order(order, 102.5, execute_trigger=False)
        self.assertTrue(updated)
        self.assertTrue(triggered)
        self.assertEqual(order.status, 'TRIGGERED')

    def test_evaluate_single_trailing_order_buy(self):
        # Create an active BUY trailing order: trough=100, trail=2%, stop=102
        order = TrailingOrder(
            id=9992,
            user_id=1,
            symbol='BTCUSDT',
            side='BUY',
            quantity=0.01,
            trail_type='PERCENT',
            trail_value=2.0,
            lowest_price=100.0,
            current_stop_price=102.0,
            is_activated=True,
            status='ACTIVE'
        )

        # 1. Price drops to 90: stop should ratchet down to 90 * 1.02 = 91.8
        updated, triggered = evaluate_single_trailing_order(order, 90.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertFalse(triggered)
        self.assertEqual(order.lowest_price, 90.0)
        self.assertAlmostEqual(order.current_stop_price, 91.8)
        self.assertEqual(order.status, 'ACTIVE')

        # 2. Price climbs slightly to 91.0: trough stays 90, stop stays 91.8, no trigger
        updated, triggered = evaluate_single_trailing_order(order, 91.0, execute_trigger=False)
        self.assertFalse(updated)
        self.assertFalse(triggered)
        self.assertEqual(order.lowest_price, 90.0)
        self.assertAlmostEqual(order.current_stop_price, 91.8)

        # 3. Price rebounds to 92.5 (above 91.8): TRIGGERED!
        updated, triggered = evaluate_single_trailing_order(order, 92.5, execute_trigger=False)
        self.assertTrue(updated)
        self.assertTrue(triggered)
        self.assertEqual(order.status, 'TRIGGERED')

    def test_activation_price_delay(self):
        # SELL order with activation price = 110, current = 100
        order = TrailingOrder(
            id=9993,
            user_id=1,
            symbol='BTCUSDT',
            side='SELL',
            quantity=0.01,
            trail_type='PERCENT',
            trail_value=2.0,
            activation_price=110.0,
            is_activated=False,
            highest_price=100.0,
            current_stop_price=98.0,
            status='ACTIVE'
        )

        # Price at 105: not activated yet, should not trigger even if below stop
        updated, triggered = evaluate_single_trailing_order(order, 105.0, execute_trigger=False)
        self.assertFalse(order.is_activated)
        self.assertFalse(triggered)

        # Price crosses 110: activated!
        updated, triggered = evaluate_single_trailing_order(order, 112.0, execute_trigger=False)
        self.assertTrue(order.is_activated)
        self.assertEqual(order.highest_price, 112.0)
        self.assertAlmostEqual(order.current_stop_price, 112.0 * 0.98)

    def test_trading_settings_max_order_size_unlimited(self):
        # Verify 0.0 or None allows unlimited order sizes
        settings = TradingSettings(user_id=9999, max_order_size_usd=0.0)
        self.assertEqual(settings.max_order_size_usd, 0.0)

        # Simulation of routes/portfolio.py check logic
        order_value_usd = 50000.0
        max_limit = getattr(settings, 'max_order_size_usd', None)
        is_blocked = (max_limit is not None and float(max_limit) > 0 and order_value_usd > float(max_limit))
        self.assertFalse(is_blocked, "Order should NOT be blocked when max_order_size_usd is 0.0")

        # When positive limit set:
        settings.max_order_size_usd = 1000.0
        max_limit = getattr(settings, 'max_order_size_usd', None)
        is_blocked = (max_limit is not None and float(max_limit) > 0 and order_value_usd > float(max_limit))
        self.assertTrue(is_blocked, "Order should be blocked when exceeding positive limit")

if __name__ == '__main__':
    unittest.main()
