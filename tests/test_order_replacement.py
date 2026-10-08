"""Unit and integration tests for universal order replacement across synthetic, test, and exchange orders."""
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
from flask import Flask
from core.extensions import db
from credentials import User, Credential, UserSetting
from models import WebullTestAccount, WebullTestPosition, WebullTestOrder
from trading_models import (
    LadderOrder, LadderRung, TrailingOrder, SyntheticExecution,
    TestOrder, TestPortfolio, RealOrder, TradingSettings
)
from services.order_replacement_service import cancel_any_order


class OrderReplacementTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SECRET_KEY='test-key',
            TESTING=True
        )
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()

        tables = [
            User, Credential, UserSetting, TradingSettings, TestOrder, TestPortfolio,
            RealOrder, LadderOrder, LadderRung, TrailingOrder, SyntheticExecution,
            WebullTestAccount, WebullTestPosition, WebullTestOrder
        ]
        for model in tables:
            model.__table__.create(db.engine, checkfirst=True)

        user = User(id=1, username='testuser', pwd_hash='test', email='test@example.com')
        db.session.add(user)
        db.session.add(TradingSettings(user_id=1, test_mode_enabled=True, max_order_size_usd=0))
        db.session.add(UserSetting(user_id=1, webull_environment='production', webull_test_mode_enabled=True))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_cancel_any_order_synthetic_ladder(self):
        """Verify cancel_any_order cancels a synthetic ladder order by ladder_id prefix or raw id."""
        ladder = LadderOrder(
            id=101,
            user_id=1,
            symbol='ETHUSDT',
            side='SELL',
            total_quantity=2.5,
            status='ACTIVE',
            broker='binance',
            test_mode=True
        )
        db.session.add(ladder)
        db.session.commit()

        # Cancel with ladder_101
        res = cancel_any_order('ladder_101', user_id=1)
        self.assertTrue(res['success'])
        self.assertEqual(res['order_type'], 'ladder')

        updated = LadderOrder.query.get(101)
        self.assertEqual(updated.status, 'CANCELLED')

    def test_cancel_any_order_synthetic_trailing(self):
        """Verify cancel_any_order cancels a synthetic trailing stop order."""
        trail = TrailingOrder(
            id=202,
            user_id=1,
            symbol='BTCUSDT',
            side='SELL',
            quantity=0.5,
            trail_type='PERCENT',
            trail_value=2.0,
            current_stop_price=98.0,
            status='ACTIVE',
            broker='binance',
            test_mode=True
        )
        db.session.add(trail)
        db.session.commit()

        res = cancel_any_order('trail_202', user_id=1)
        self.assertTrue(res['success'])
        self.assertEqual(res['order_type'], 'trailing')

        updated = TrailingOrder.query.get(202)
        self.assertEqual(updated.status, 'CANCELLED')

    def test_cancel_any_order_paper_test_order(self):
        """Verify cancel_any_order cancels a paper TestOrder."""
        test_ord = TestOrder(
            id=303,
            user_id=1,
            symbol='ETHUSDT',
            side='BUY',
            type='LIMIT',
            quantity=1.0,
            price=2500.0,
            status='NEW'
        )
        db.session.add(test_ord)
        db.session.commit()

        res = cancel_any_order('303', user_id=1)
        self.assertTrue(res['success'])
        self.assertEqual(res['order_type'], 'test_order')

        updated = TestOrder.query.get(303)
        self.assertEqual(updated.status, 'CANCELED')

    def test_cancel_any_order_real_order(self):
        """Verify cancel_any_order marks RealOrder CANCELED."""
        real_ord = RealOrder(
            id=404,
            user_id=1,
            binance_order_id=55555,
            symbol='SOLUSDT',
            side='BUY',
            type='LIMIT',
            quantity=10.0,
            price=150.0,
            status='NEW'
        )
        db.session.add(real_ord)
        db.session.commit()

        res = cancel_any_order('55555', user_id=1, test_mode=True)
        self.assertTrue(res['success'])

        updated = RealOrder.query.get(404)
        self.assertEqual(updated.status, 'CANCELED')

    def test_cancel_any_order_webull_test_order(self):
        """Verify cancel_any_order cancels Webull simulated test order."""
        with patch('services.webull_paper_trading_service.cancel_webull_test_order') as mock_cancel:
            res = cancel_any_order('webull-7001', user_id=1, test_mode=True)
            self.assertTrue(res['success'])
            self.assertEqual(res['order_type'], 'webull')
            mock_cancel.assert_called_once_with(1, '7001')

    def test_cancel_any_order_unprefixed_ladder_numeric_id(self):
        """Verify numeric ID for an active ladder order resolves to cancelling that ladder order."""
        ladder = LadderOrder(
            id=808,
            user_id=1,
            symbol='ETHUSDT',
            side='SELL',
            total_quantity=1.0,
            status='ACTIVE',
            broker='binance',
            test_mode=True
        )
        db.session.add(ladder)
        db.session.commit()

        res = cancel_any_order('808', user_id=1)
        self.assertTrue(res['success'])
        self.assertEqual(res['order_type'], 'ladder')

        updated = LadderOrder.query.get(808)
        self.assertEqual(updated.status, 'CANCELLED')

    def test_synthetic_locked_funds_calculation(self):
        """Verify get_synthetic_locked_funds sums active synthetic orders for asset and side."""
        from services.synthetic_execution_service import get_synthetic_locked_funds
        ladder = LadderOrder(
            id=901,
            user_id=1,
            symbol='BTCUSDT',
            side='SELL',
            total_quantity=0.00888,
            status='ACTIVE',
            broker='binance',
            test_mode=False
        )
        db.session.add(ladder)
        db.session.commit()

        locked = get_synthetic_locked_funds(1, 'BTCUSDT', 'SELL', broker='binance', test_mode=False)
        self.assertAlmostEqual(locked, 0.00888)

        # Excluding this order (as in a replacement) yields 0
        locked_excluded = get_synthetic_locked_funds(1, 'BTCUSDT', 'SELL', broker='binance', test_mode=False, exclude_order_id='ladder_901')
        self.assertEqual(locked_excluded, 0.0)

    def test_check_synthetic_order_capacity_blocks_when_funds_tied_up(self):
        """Verify check_synthetic_order_capacity raises ValueError when synthetic orders tie up balance."""
        from services.synthetic_execution_service import check_synthetic_order_capacity
        ladder = LadderOrder(
            id=902,
            user_id=1,
            symbol='BTCUSDT',
            side='SELL',
            total_quantity=0.00888,
            status='ACTIVE',
            broker='binance',
            test_mode=False
        )
        db.session.add(ladder)
        db.session.commit()

        mock_client = Mock()
        mock_client.get_account.return_value = {
            'balances': [{'asset': 'BTC', 'free': '0.0089', 'locked': '0.0'}]
        }
        with patch('services.synthetic_execution_service.binance_client', return_value=mock_client):
            with self.assertRaises(ValueError) as ctx:
                check_synthetic_order_capacity(1, 'BTCUSDT', 'SELL', 0.005, broker='binance', test_mode=False)
            self.assertIn('Pending synthetic order ties up all available funds', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
