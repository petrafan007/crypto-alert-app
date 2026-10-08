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

    def test_synthetic_ladder_pending_orders_formatting(self):
        """Verify active LadderOrder converts to dictionary and formats into pending_orders payload."""
        from services.synthetic_execution_service import WORKING_PARENTS
        ladder = LadderOrder(
            id=903,
            user_id=1,
            symbol='BTCUSDT',
            side='SELL',
            total_quantity=0.01331,
            status='PARTIALLY_FILLED',
            broker='binance',
            test_mode=False,
            engine_version=2
        )
        db.session.add(ladder)
        db.session.flush()

        rung1 = LadderRung(
            ladder_id=ladder.id,
            rung_number=1,
            rung_type='TAKE_PROFIT',
            target_price=87337.16,
            quantity=0.00332,
            status='PENDING'
        )
        db.session.add(rung1)
        db.session.commit()

        active_ladders = LadderOrder.query.filter(
            LadderOrder.user_id == 1,
            LadderOrder.status.in_(WORKING_PARENTS),
            LadderOrder.test_mode.is_(False)
        ).all()

        pending_orders = []
        for lo in active_ladders:
            sym = lo.symbol.upper()
            base_asset = next((sym[:-len(q)] for q in ('USDT', 'USDC', 'USD') if sym.endswith(q)), sym)
            details = lo.to_dict()
            pending_rungs = [r for r in lo.rungs if r.status == 'PENDING']
            next_rung = pending_rungs[0] if pending_rungs else None
            target_px = next_rung.target_price if next_rung else (lo.upside_target_price or lo.downside_target_price or 0.0)
            rem_qty = float((details.get('remaining_quantity') if details.get('remaining_quantity') is not None else lo.total_quantity) or 0.0)
            tot_qty = float(lo.total_quantity or 1.0)
            if lo.total_budget_usd:
                rem_budget = float(lo.total_budget_usd) * (rem_qty / tot_qty)
            else:
                rem_budget = rem_qty * target_px
            pending_orders.append({
                'order_id': f"ladder_{lo.id}",
                'symbol': sym,
                'asset': base_asset,
                'provider': lo.broker or 'binance',
                'source': lo.broker or 'binance',
                'side': lo.side,
                'type': 'LADDER',
                'price': target_px,
                'trigger_price': target_px,
                'quantity': details.get('remaining_quantity') if details.get('remaining_quantity') is not None else lo.total_quantity,
                'synthetic_details': details,
                'account_id': lo.account_id,
                'quantity_usdt': rem_budget,
                'status': lo.status,
                'direction': 'rises to' if lo.side == 'SELL' else 'drops to',
                'is_ladder': True,
                'rungs_total': lo.rungs_total,
                'rungs_filled': lo.rungs_filled,
                'next_rung_number': next_rung.rung_number if next_rung else None,
                'next_rung_price': target_px,
                'next_rung_qty': next_rung.quantity if next_rung else None,
            })

        self.assertEqual(len(pending_orders), 1)
        item = pending_orders[0]
        self.assertEqual(item['order_id'], 'ladder_903')
        self.assertEqual(item['symbol'], 'BTCUSDT')
        self.assertEqual(item['asset'], 'BTC')
        self.assertEqual(item['status'], 'PARTIALLY_FILLED')
        self.assertIn('synthetic_details', item)
        self.assertEqual(item['synthetic_details']['id'], 903)


if __name__ == '__main__':
    unittest.main()
