import unittest
from unittest.mock import Mock, patch
from trading_models import TrailingOrder, LadderOrder, LadderRung
from services.ladder_order_service import (
    calculate_ladder_rungs,
    evaluate_single_ladder_order
)
from services.trailing_order_service import (
    calculate_trailing_stop_price,
    evaluate_single_trailing_order
)

class TestLadderAndWebullSynthetic(unittest.TestCase):

    def test_calculate_ladder_rungs_conservative_sell(self):
        # 3 rungs: +2%, +4%, +6% on 1.0 BTC at $100
        rungs_input = [
            {'price_offset_pct': 2.0, 'percentage_of_total': 33.33},
            {'price_offset_pct': 4.0, 'percentage_of_total': 33.33},
            {'price_offset_pct': 6.0, 'percentage_of_total': 33.34}
        ]
        rungs = calculate_ladder_rungs(
            side='SELL',
            current_price=100.0,
            total_quantity=1.0,
            custom_rungs=rungs_input
        )
        self.assertEqual(len(rungs), 3)
        self.assertAlmostEqual(rungs[0]['target_price'], 102.0)
        self.assertAlmostEqual(rungs[1]['target_price'], 104.0)
        self.assertAlmostEqual(rungs[2]['target_price'], 106.0)

        total_qty = sum(r['quantity'] for r in rungs)
        self.assertAlmostEqual(total_qty, 1.0, places=4)

    def test_calculate_ladder_rungs_aggressive_buy(self):
        # 4 rungs: -5%, -10%, -15%, -20% on 100 shares at $200
        rungs_input = [
            {'price_offset_pct': -5.0, 'percentage_of_total': 25.0},
            {'price_offset_pct': -10.0, 'percentage_of_total': 25.0},
            {'price_offset_pct': -15.0, 'percentage_of_total': 25.0},
            {'price_offset_pct': -20.0, 'percentage_of_total': 25.0}
        ]
        rungs = calculate_ladder_rungs(
            side='BUY',
            current_price=200.0,
            total_quantity=100.0,
            custom_rungs=rungs_input
        )
        self.assertEqual(len(rungs), 4)
        self.assertAlmostEqual(rungs[0]['target_price'], 190.0)
        self.assertAlmostEqual(rungs[1]['target_price'], 180.0)
        self.assertAlmostEqual(rungs[2]['target_price'], 170.0)
        self.assertAlmostEqual(rungs[3]['target_price'], 160.0)

        for r in rungs:
            self.assertAlmostEqual(r['quantity'], 25.0)

    def test_evaluate_single_ladder_order_sell_progression(self):
        # Setup LadderOrder with 2 rungs: target $105 and target $110
        rung1 = LadderRung(
            id=101,
            ladder_id=1,
            rung_number=1,
            target_price=105.0,
            price_offset_pct=5.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING'
        )
        rung2 = LadderRung(
            id=102,
            ladder_id=1,
            rung_number=2,
            target_price=110.0,
            price_offset_pct=10.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING'
        )
        order = LadderOrder(
            id=1,
            user_id=1,
            broker='binance',
            symbol='BTCUSDT',
            side='SELL',
            total_quantity=1.0,
            status='ACTIVE',
            rungs_total=2,
            rungs_filled=0,
            rungs=[rung1, rung2],
            has_stop_loss=False
        )

        # 1. Price is $102 (below both targets): No trigger
        updated, count = evaluate_single_ladder_order(order, 102.0, execute_trigger=False)
        self.assertFalse(updated)
        self.assertEqual(count, 0)
        self.assertEqual(order.status, 'ACTIVE')
        self.assertEqual(rung1.status, 'PENDING')
        self.assertEqual(rung2.status, 'PENDING')

        # 2. Price climbs to $106: Rung 1 triggers, Rung 2 pending
        updated, count = evaluate_single_ladder_order(order, 106.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(count, 1)
        self.assertEqual(rung1.status, 'TRIGGERED')
        self.assertEqual(order.status, 'ACTIVE')

        # 3. Price climbs to $112: Rung 2 triggers, both rungs triggered -> COMPLETED
        updated, count = evaluate_single_ladder_order(order, 112.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(count, 1)
        self.assertEqual(rung2.status, 'TRIGGERED')
        self.assertEqual(order.status, 'ACTIVE')
        self.assertEqual(order.rungs_filled, 0)

    def test_evaluate_single_ladder_order_downside_stop_loss(self):
        # Setup Sell Ladder with stop loss safety net at $92
        rung1 = LadderRung(
            id=201,
            ladder_id=2,
            rung_number=1,
            target_price=105.0,
            price_offset_pct=5.0,
            quantity=0.5,
            percentage_of_total=50.0,
            status='PENDING'
        )
        order = LadderOrder(
            id=2,
            user_id=1,
            broker='webull',
            symbol='AAPL',
            side='SELL',
            total_quantity=0.5,
            status='ACTIVE',
            rungs_total=1,
            rungs_filled=0,
            rungs=[rung1],
            has_stop_loss=True,
            stop_loss_trigger_price=92.0,
            stop_loss_action='CANCEL_REMAINING'
        )

        # Price crashes to $90 (below stop loss $92)
        updated, count = evaluate_single_ladder_order(order, 90.0, execute_trigger=False)
        self.assertTrue(updated)
        self.assertEqual(count, 1)
        self.assertEqual(order.status, 'CANCELLED')
        self.assertEqual(rung1.status, 'CANCELLED')

    @patch('services.synthetic_execution_service.submit_execution')
    def test_webull_trailing_order_execution(self, mock_webull_place):
        from flask import Flask
        from services.trailing_order_service import execute_trailing_trigger
        
        test_app = Flask('test_synthetic')
        with test_app.app_context(), \
             patch('credentials.Credential.query') as mock_cred_query, \
             patch('credentials.UserSetting.query') as mock_setting_query:
            
            mock_cred = Mock(webull_app_key='app_k', webull_app_secret='app_s', webull_access_token='tok_123')
            mock_cred_query.filter_by.return_value.first.return_value = mock_cred

            mock_setting = Mock(webull_environment='production', webull_default_account_id='12345678')
            mock_setting_query.filter_by.return_value.first.return_value = mock_setting

            mock_webull_place.return_value = Mock(rung_id=None, status='SUBMITTED', broker_order_id='WB_999', error_message=None)

            order = TrailingOrder(
                id=555,
                user_id=1,
                broker='webull',
                account_id='12345678',
                symbol='TSLA',
                instrument_type='EQUITY',
                trading_session='CORE',
                side='SELL',
                quantity=10.0,
                status='ACTIVE'
            )

            success = execute_trailing_trigger(order, current_price=250.0)
            self.assertTrue(success)
            mock_webull_place.assert_called_once()
            self.assertEqual(mock_webull_place.call_args.args[0].broker, 'webull')
            self.assertEqual(order.status, 'SUBMITTED')

    @patch('services.synthetic_execution_service.submit_execution')
    def test_webull_ladder_rung_execution(self, mock_webull_place):
        from flask import Flask
        from services.ladder_order_service import execute_ladder_rung_trigger

        test_app = Flask('test_synthetic')
        with test_app.app_context(), \
             patch('credentials.Credential.query') as mock_cred_query, \
             patch('credentials.UserSetting.query') as mock_setting_query:

            mock_cred = Mock(webull_app_key='app_k', webull_app_secret='app_s', webull_access_token='tok_123')
            mock_cred_query.filter_by.return_value.first.return_value = mock_cred

            mock_setting = Mock(webull_environment='production', webull_default_account_id='12345678')
            mock_setting_query.filter_by.return_value.first.return_value = mock_setting

            mock_webull_place.return_value = Mock(rung_id=301, status='SUBMITTED', broker_order_id='WB_888', error_message=None, filled_quantity=0, filled_price=None)

            rung = LadderRung(
                id=301,
                ladder_id=3,
                rung_number=1,
                target_price=500.0,
                quantity=5.0,
                status='PENDING'
            )
            order = LadderOrder(
                id=3,
                user_id=1,
                broker='webull',
                account_id='12345678',
                symbol='SPY',
                instrument_type='EQUITY',
                trading_session='CORE',
                side='SELL',
                total_quantity=5.0,
                status='ACTIVE',
                rungs_total=1,
                rungs_filled=0,
                rungs=[rung]
            )

            execute_ladder_rung_trigger(order, rung, current_price=500.0)
            self.assertEqual(rung.status, 'SUBMITTED')
            self.assertEqual(rung.executed_order_id, 'WB_888')
            mock_webull_place.assert_called_once()
            self.assertEqual(mock_webull_place.call_args.args[0].broker, 'webull')
            self.assertEqual(mock_webull_place.call_args.args[2], 5.0)

if __name__ == '__main__':
    unittest.main()
