"""Every pending-order reader describes orders through one serializer.

Covers unfilled remainders, conditional strategy legs by phase, broker order
groups, and the journal link between a synthetic strategy and its broker order.
"""
import unittest
from core.extensions import db
from credentials import UserSetting
from models import WebullOrder
from trading_models import SyntheticExecution, TrailingOrder
from services import pending_order_serializer as serializer
from services import synthetic_conditional_service as conditional
from services import synthetic_execution_service as ex
from services.webull_service import _flatten_webull_order_groups
from tests import test_synthetic_order_lifecycle as base


class PendingOrderSerializerTests(unittest.TestCase):
    setUp, tearDown, create = base.SyntheticLifecycleTests.setUp, base.SyntheticLifecycleTests.tearDown, base.SyntheticLifecycleTests.create

    def otoco(self, **extra):
        data = dict(strategy_type='OTOCO', symbol='NVDA', side='BUY', broker='webull', instrument_type='EQUITY', account_id='A',
                    trading_session='ALL', total_quantity=10, limit_cap_pct=1, test_mode=False,
                    legs=[dict(side='BUY', order_type='LIMIT', price=160),
                          dict(side='SELL', order_type='LIMIT', price=175),
                          dict(side='SELL', order_type='STOP_LOSS', stop_price=150)])
        data.update(extra)
        self.rules['step'] = 1
        return conditional.create_conditional(1, data)

    def test_binance_orders_report_the_unfilled_remainder_and_exact_base_asset(self):
        order = serializer.format_binance_open_order({'orderId': 5, 'clientOrderId': 'c5', 'symbol': 'ETHUSDT', 'side': 'BUY', 'type': 'LIMIT',
                                                      'price': '100', 'origQty': '10', 'executedQty': '4', 'status': 'PARTIALLY_FILLED', 'orderListId': -1})
        self.assertEqual((order['quantity'], order['original_quantity'], order['filled_quantity'], order['quantity_usdt']), (6.0, 10.0, 4.0, 600.0))
        self.assertEqual((order['asset'], order['client_order_id'], order['group_id']), ('ETH', 'c5', None))
        self.assertEqual(serializer.format_binance_open_order({'symbol': 'USDTUSD', 'side': 'SELL', 'price': '1', 'origQty': '5'})['asset'], 'USDT')
        grouped = serializer.format_binance_open_order({'symbol': 'BTCUSD', 'side': 'BUY', 'price': '9', 'origQty': '1', 'orderListId': 77})
        self.assertEqual((grouped['group_id'], grouped['group_role'], grouped['is_oco']), ('binance-list-77', 'exclusive', True))

    def test_webull_combo_legs_keep_their_group_and_role(self):
        flat = _flatten_webull_order_groups([
            {'client_combo_order_id': 'combo-1', 'status': 'SUBMITTED', 'items': [
                {'order_id': '1', 'symbol': 'AAPL', 'side': 'BUY', 'combo_type': 'MASTER', 'limit_price': '10', 'total_quantity': '3'},
                {'order_id': '2', 'symbol': 'AAPL', 'side': 'SELL', 'combo_type': 'STOP_PROFIT', 'limit_price': '12', 'total_quantity': '3'},
                {'order_id': '3', 'symbol': 'AAPL', 'side': 'SELL', 'combo_type': 'STOP_LOSS', 'stop_price': '9', 'total_quantity': '3'}]},
            {'client_order_id': 'single', 'status': 'SUBMITTED', 'items': [{'order_id': '4', 'symbol': 'MSFT', 'side': 'BUY', 'limit_price': '5', 'total_quantity': '2', 'filled_quantity': '1'}]},
        ])
        self.assertEqual([order.get('_webull_group_id') for order in flat], ['combo-1', 'combo-1', 'combo-1', None])
        entries = [serializer.format_webull_open_order({**order, '_webull_account_id': 'A'}, {'SUBMITTED'}) for order in flat]
        self.assertEqual([(entry['group_id'], entry['group_role']) for entry in entries],
                         [('webull-combo-combo-1', 'independent'), ('webull-combo-combo-1', 'exclusive'), ('webull-combo-combo-1', 'exclusive'), (None, None)])
        self.assertEqual((entries[3]['quantity'], entries[3]['quantity_usdt'], entries[3]['account_id']), (1.0, 5.0, 'A'))
        self.assertIsNone(serializer.format_webull_open_order({'symbol': 'AAPL', 'status': 'FILLED'}, {'SUBMITTED'}))

    def test_conditional_strategy_reports_the_legs_of_its_phase_and_the_engine_reservation(self):
        parent = self.otoco()
        entry = serializer.serialize_ladder(parent)
        self.assertTrue(entry['is_conditional'] and entry['is_ladder'] and entry['is_synthetic'])
        self.assertEqual((entry['conditional_phase'], entry['price'], entry['trigger_price'], entry['quantity']), ('ENTRY', 160.0, 160.0, 10.0))
        self.assertEqual([leg['side'] for leg in entry['legs']], ['BUY'])
        self.assertEqual([(leg['side'], leg['trigger_price']) for leg in entry['waiting_legs']], [('SELL', 175.0), ('SELL', 150.0)])
        locked = ex.get_synthetic_locked_funds(1, 'NVDA', 'BUY', broker='webull', test_mode=False, account_id='A')
        self.assertAlmostEqual(entry['quantity_usdt'], 10 * 160 * 1.01)
        self.assertAlmostEqual(entry['quantity_usdt'], locked, msg='the dashboard figure equals the engine capacity check')

        # After the entry fills, the exits are the working legs and hold no cash as sells.
        parent.conditional_phase, parent.side, parent.total_quantity = 'EXIT', 'SELL', 6
        db.session.commit()
        exits = serializer.serialize_ladder(parent)
        self.assertEqual((exits['side'], exits['quantity'], exits['price'], exits['stop_price'], exits['waiting_legs']), ('SELL', 6.0, 175.0, 150.0, []))
        self.assertEqual(len(exits['legs']), 2)

    def test_trailing_strategy_reports_the_remainder_after_a_partial_fill(self):
        order = TrailingOrder(user_id=1, broker='binance', symbol='BTCUSD', side='BUY', quantity=10, trail_value=2,
                              current_stop_price=100, status='PARTIALLY_FILLED', test_mode=False, engine_version=2)
        db.session.add(order); db.session.flush()
        db.session.add(SyntheticExecution(user_id=1, parent_kind='TRAILING', parent_id=order.id, leg='TRAILING', client_order_id='syn-fill',
                                          quantity=4, filled_quantity=4, status='FILLED'))
        db.session.commit()
        entry = serializer.serialize_trailing(order)
        self.assertEqual((entry['quantity'], entry['original_quantity'], entry['quantity_usdt'], entry['asset']), (6.0, 10, 600.0, 'BTC'))

    def test_broker_orders_are_linked_to_their_strategy_by_the_journal_only(self):
        parent = self.otoco()
        db.session.add(SyntheticExecution(user_id=1, parent_kind='LADDER', parent_id=parent.id, leg='ENTRY', client_order_id='syn-open',
                                          broker_order_id='900', quantity=10, filled_quantity=0, status='SUBMITTED'))
        db.session.add(SyntheticExecution(user_id=1, parent_kind='LADDER', parent_id=parent.id, leg='ENTRY', client_order_id='syn-done',
                                          broker_order_id='800', quantity=10, filled_quantity=0, status='CANCELLED'))
        db.session.commit()
        strategy = serializer.serialize_ladder(parent)
        self.assertEqual(sorted(strategy['child_order_ids']), ['900', 'syn-open'], 'only orders still open at the broker')
        native = lambda order_id, **extra: {'order_id': order_id, 'provider': 'webull', 'symbol': 'NVDA', 'side': 'BUY', 'account_id': 'A', **extra}
        orders = serializer.link_synthetic_children([
            strategy, native('900'), native('555', client_order_id='syn-open'), native('800'), native('901'),
            {**native('900'), 'provider': 'binance'}])
        self.assertEqual([order.get('synthetic_parent_id') for order in orders], [None, strategy['order_id'], strategy['order_id'], None, None, None])

    def test_cached_and_live_readers_share_the_same_strategy_rows(self):
        from services.portfolio_service import get_fast_pending_orders
        WebullOrder.__table__.create(db.engine, checkfirst=True)
        db.session.get(UserSetting, 1).webull_test_mode_enabled = False
        parent = self.otoco()
        db.session.add(SyntheticExecution(user_id=1, parent_kind='LADDER', parent_id=parent.id, leg='ENTRY', client_order_id='syn-open',
                                          broker_order_id='900', quantity=10, filled_quantity=0, status='SUBMITTED'))
        db.session.add(WebullOrder(user_id=1, account_id='A', symbol='NVDA', side='BUY', status='SUBMITTED', quantity=10, price=160,
                                   provider_order_id='900', client_order_id='syn-open'))
        db.session.commit()
        fast = get_fast_pending_orders(1)
        self.assertEqual([order for order in fast if order.get('is_synthetic')], serializer.working_synthetic_orders(1))
        child = next(order for order in fast if order['order_id'] == '900')
        self.assertEqual(child['synthetic_parent_id'], f'ladder_{parent.id}')
        self.assertEqual((child['quantity'], child['original_quantity']), (10.0, 10.0))


if __name__ == '__main__':
    unittest.main()
