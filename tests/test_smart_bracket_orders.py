import unittest
from unittest.mock import Mock, patch
from trading_models import LadderOrder, LadderRung
from services.ladder_order_service import (
    calculate_ladder_rungs,
    evaluate_single_ladder_order,
    create_ladder_order
)

class TestSmartBracketOrders(unittest.TestCase):
    """
    Comprehensive tests for the unified Smart Bracket Order system:
    - Mode A: Single Target / Stop
    - Mode B: Staged Ladder Rungs
    - Mode C: Trailing Stop / Trailing Profit
    """

    def test_dual_ladder_rungs_calculation(self):
        """Test calculation of rungs for both Take Profit and Stop Loss ladders."""
        upside_rungs_input = [
            {'price_offset_pct': 5.0, 'percentage_of_total': 50.0},
            {'price_offset_pct': 10.0, 'percentage_of_total': 50.0}
        ]
        downside_rungs_input = [
            {'price_offset_pct': -3.0, 'percentage_of_total': 40.0},
            {'price_offset_pct': -6.0, 'percentage_of_total': 60.0}
        ]

        tp_rungs = calculate_ladder_rungs(
            side='SELL',
            current_price=100.0,
            total_quantity=2.0,
            custom_rungs=upside_rungs_input,
            rung_type='TAKE_PROFIT'
        )
        self.assertEqual(len(tp_rungs), 2)
        self.assertAlmostEqual(tp_rungs[0]['target_price'], 105.0)
        self.assertEqual(tp_rungs[0]['rung_type'], 'TAKE_PROFIT')
        self.assertAlmostEqual(tp_rungs[1]['target_price'], 110.0)

        sl_rungs = calculate_ladder_rungs(
            side='SELL',
            current_price=100.0,
            total_quantity=2.0,
            custom_rungs=downside_rungs_input,
            rung_type='STOP_LOSS'
        )
        self.assertEqual(len(sl_rungs), 2)
        self.assertAlmostEqual(sl_rungs[0]['target_price'], 97.0)
        self.assertEqual(sl_rungs[0]['rung_type'], 'STOP_LOSS')
        self.assertAlmostEqual(sl_rungs[1]['target_price'], 94.0)

    def test_mode_c_trailing_profit_and_mode_b_stop_ladder(self):
        """
        Verify Mode C (Trailing Profit Up with Activation) + Mode B (Stop Ladder Down):
        - Trailing profit waits for activation hurdle ($120).
        - Stop ladder triggers rungs if price drops to stops.
        """
        sl_rung1 = LadderRung(
            id=10,
            ladder_id=1,
            rung_number=1,
            target_price=95.0,
            price_offset_pct=-5.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING',
            rung_type='STOP_LOSS'
        )
        sl_rung2 = LadderRung(
            id=11,
            ladder_id=1,
            rung_number=2,
            target_price=90.0,
            price_offset_pct=-10.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING',
            rung_type='STOP_LOSS'
        )

        order = LadderOrder(
            id=1,
            user_id=1,
            broker='binance',
            symbol='BTCUSDT',
            side='SELL',
            total_quantity=1.0,
            strategy_type='BRACKET',
            upside_mode='TRAILING',
            upside_trail_value=5.0,
            upside_trail_type='PERCENT',
            upside_activation_price=120.0,
            downside_mode='LADDER',
            status='ACTIVE',
            rungs_total=2,
            rungs_filled=0,
            rungs=[sl_rung1, sl_rung2]
        )

        # 1. Price is at $110 (below $120 activation): Upside highest price updates to 110, but not active yet
        updated, count = evaluate_single_ladder_order(order, 110.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertAlmostEqual(order.upside_highest_price, 110.0)
        self.assertEqual(order.status, 'ACTIVE')

        # 2. Price drops to $94: Hits first stop rung ($95)
        updated, count = evaluate_single_ladder_order(order, 94.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(sl_rung1.status, 'TRIGGERED')
        self.assertEqual(sl_rung2.status, 'PENDING')
        self.assertEqual(order.status, 'ACTIVE')

    def test_mode_b_ladder_up_and_mode_c_trailing_stop_down(self):
        """
        Verify Mode B (Take Profit Ladder Up) + Mode C (Trailing Stop Down):
        - Ladder rungs trigger on upside targets.
        - Trailing stop tracks watermark on downside.
        """
        tp_rung1 = LadderRung(
            id=20,
            ladder_id=2,
            rung_number=1,
            target_price=105.0,
            price_offset_pct=5.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING',
            rung_type='TAKE_PROFIT'
        )
        tp_rung2 = LadderRung(
            id=21,
            ladder_id=2,
            rung_number=2,
            target_price=110.0,
            price_offset_pct=10.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING',
            rung_type='TAKE_PROFIT'
        )

        order = LadderOrder(
            id=2,
            user_id=1,
            broker='binance',
            symbol='BTCUSDT',
            side='SELL',
            total_quantity=1.0,
            strategy_type='BRACKET',
            upside_mode='LADDER',
            downside_mode='TRAILING',
            downside_trail_value=3.0,
            downside_trail_type='PERCENT',
            downside_current_stop_price=97.0,
            status='ACTIVE',
            rungs_total=2,
            rungs_filled=0,
            rungs=[tp_rung1, tp_rung2]
        )

        # 1. Price hits $106: First TP rung triggers
        updated, count = evaluate_single_ladder_order(order, 106.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(tp_rung1.status, 'TRIGGERED')
        self.assertEqual(tp_rung2.status, 'PENDING')
        self.assertEqual(order.status, 'ACTIVE')
        # Downside trailing stop ratchets with peak 106 -> 106 * (1 - 0.03) = 102.82
        self.assertAlmostEqual(order.downside_current_stop_price, 102.82)

    def test_mode_a_single_target_and_single_stop(self):
        """
        Verify Mode A (Single Target Up) + Mode A (Single Stop Down):
        Classic smart bracket order.
        """
        order = LadderOrder(
            id=3,
            user_id=1,
            broker='binance',
            symbol='ETHUSDT',
            side='SELL',
            total_quantity=5.0,
            strategy_type='BRACKET',
            upside_mode='SINGLE',
            upside_target_price=2500.0,
            downside_mode='SINGLE',
            downside_target_price=2100.0,
            status='ACTIVE',
            rungs_total=0,
            rungs_filled=0,
            rungs=[]
        )

        # Price reaches $2510 (Target hit)
        updated, count = evaluate_single_ladder_order(order, 2510.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(order.status, 'ACTIVE')

    def test_mode_a_single_stop_loss_trigger(self):
        """Verify Mode A single stop loss triggers when price breaks below stop."""
        order = LadderOrder(
            id=4,
            user_id=1,
            broker='webull',
            symbol='AAPL',
            instrument_type='EQUITY',
            side='SELL',
            total_quantity=10.0,
            strategy_type='BRACKET',
            upside_mode='SINGLE',
            upside_target_price=240.0,
            downside_mode='SINGLE',
            downside_target_price=210.0,
            status='ACTIVE',
            rungs_total=0,
            rungs_filled=0,
            rungs=[]
        )

        # Price drops to $209 (Stop hit)
        updated, count = evaluate_single_ladder_order(order, 209.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(order.status, 'ACTIVE')

    @patch('services.synthetic_execution_service.submit_execution')
    def test_webull_bracket_execution(self, mock_rung_trigger):
        """Verify Webull equity/crypto execution routing."""
        order = LadderOrder(
            id=5,
            user_id=1,
            broker='webull',
            symbol='TSLA',
            instrument_type='EQUITY',
            side='SELL',
            total_quantity=20.0,
            strategy_type='BRACKET',
            upside_mode='SINGLE',
            upside_target_price=250.0,
            downside_mode='NONE',
            status='ACTIVE',
            rungs_total=0,
            rungs_filled=0,
            rungs=[]
        )

        mock_rung_trigger.return_value = Mock(rung_id=None, quantity=20, filled_quantity=0, status='SUBMITTED')
        updated, count = evaluate_single_ladder_order(order, 252.0, execute_trigger=True)
        self.assertTrue(updated)
        self.assertEqual(order.status, 'SUBMITTED')
        mock_rung_trigger.assert_called_once()

if __name__ == '__main__':
    unittest.main()
