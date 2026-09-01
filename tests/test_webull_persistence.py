import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from credentials import User
from models import BinanceOrder, OrderHistorySyncState, WebullAccountSnapshot, WebullHolding, WebullOrder, WebullWatchlistItem
from trading_models import PortfolioValueHistory
from services.webull_import_service import (
    get_webull_order_rows,
    import_webull_orders,
    import_webull_portfolio_snapshot,
)
from services.order_history_sync_service import get_binance_order_rows, import_binance_orders
from routes.portfolio import get_real_orders_only


class WebullPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        cls.context = cls.app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.context.pop()

    def setUp(self):
        for model in (BinanceOrder, OrderHistorySyncState, WebullOrder, WebullHolding, WebullAccountSnapshot, WebullWatchlistItem):
            db.session.query(model).delete()
        db.session.commit()

    def test_live_order_import_upserts_a_mobile_event_fill(self):
        imported = import_webull_orders(7, [{
            '_webull_account_id': 'cash-account',
            '_webull_account_type': 'CASH',
            'order_id': 'mobile-event-order',
            'symbol': 'KXBTC15M-26SEP011915-15',
            'instrument_type': 'EVENT',
            'event_outcome': 'YES',
            'side': 'SELL',
            'order_type': 'LIMIT',
            'total_quantity': '23',
            'filled_quantity': '23',
            'limit_price': '0.59',
            'average_filled_price': '0.60',
            'status': 'FILLED',
            'create_time': '2026-09-01T23:06:55.642Z',
            'filled_time_at': '2026-09-01T23:06:55.708Z',
        }])

        self.assertEqual(imported, 1)
        rows = get_webull_order_rows(7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 'mobile-event-order')
        self.assertEqual(rows[0]['status'], 'FILLED')
        self.assertEqual(rows[0]['filled_quantity'], 23.0)
        self.assertEqual(rows[0]['filled_price'], 0.60)
        self.assertEqual(rows[0]['event_outcome'], 'YES')

        import_webull_orders(7, [{
            '_webull_account_id': 'cash-account',
            'order_id': 'mobile-event-order',
            'symbol': 'KXBTC15M-26SEP011915-15',
            'filled_quantity': '23',
            'average_filled_price': '0.60',
            'status': 'FILLED',
        }])
        self.assertEqual(WebullOrder.query.filter_by(user_id=7).count(), 1)

    def test_binance_external_order_import_is_durable_and_idempotent(self):
        imported, latest_updated_at, latest_order_id = import_binance_orders(7, [{
            'orderId': 345,
            'clientOrderId': 'mobile-order-345',
            'symbol': 'BTCUSD',
            'side': 'BUY',
            'type': 'LIMIT',
            'origQty': '0.01',
            'executedQty': '0',
            'price': '60000',
            'status': 'NEW',
            'time': 1780000000000,
            'updateTime': 1780000001000,
        }])

        self.assertEqual(imported, 1)
        self.assertEqual(latest_order_id, 345)
        self.assertIsNotNone(latest_updated_at)

        imported, _, _ = import_binance_orders(7, [{
            'orderId': 345,
            'symbol': 'BTCUSD',
            'side': 'BUY',
            'type': 'LIMIT',
            'origQty': '0.01',
            'executedQty': '0.01',
            'price': '60000',
            'cummulativeQuoteQty': '599.5',
            'status': 'FILLED',
            'time': 1780000000000,
            'updateTime': 1780000002000,
        }])

        self.assertEqual(imported, 1)
        self.assertEqual(BinanceOrder.query.filter_by(user_id=7).count(), 1)
        rows = get_binance_order_rows(7)
        self.assertEqual(rows[0]['id'], '345')
        self.assertEqual(rows[0]['status'], 'FILLED')
        self.assertEqual(rows[0]['filled_quantity'], 0.01)
        self.assertEqual(rows[0]['filled_price'], 59950.0)

    def test_webull_history_page_uses_only_the_local_webull_ledger(self):
        import_webull_orders(7, [{
            '_webull_account_id': 'cash-account',
            'order_id': 'event-order-1',
            'symbol': 'KXBTC15M-26SEP011915-15',
            'instrument_type': 'EVENT',
            'side': 'BUY',
            'order_type': 'LIMIT',
            'total_quantity': '3',
            'status': 'FILLED',
            'create_time': '2026-09-01T23:06:55Z',
        }])

        with self.app.test_request_context('/api/trading/real-orders?account_scope=webull&page=1&page_size=50'):
            with patch('routes.portfolio.current_user', SimpleNamespace(id=7)), patch(
                'routes.portfolio.get_binance_order_rows', side_effect=AssertionError('Binance ledger must not be read'),
            ):
                response = get_real_orders_only.__wrapped__()

        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['history_source'], 'database')
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['orders'][0]['source'], 'webull')

    def test_snapshot_refresh_replaces_stale_cash_and_preserves_event_metadata(self):
        preview = [{
            'account_id': 'cash-account',
            'account_type': 'CASH',
            'account_name': 'Individual Cash',
            'balance': {
                'total_asset_currency': 'USD',
                'total_cash_balance': '10.26',
                'total_net_liquidation_value': '170.10',
            },
            'positions': [{
                'symbol': 'KXBTC15M-26SEP011915-15',
                'instrument_type': 'EVENT',
                'event_outcome': 'YES',
                'quantity': '1',
                'last_price': '0.60',
            }, {
                'symbol': 'AAPL',
                'instrument_type': 'EQUITY',
                'quantity': '0.15',
                'last_price': '316.00',
            }],
        }]
        import_webull_portfolio_snapshot(7, preview)

        preview[0]['balance']['total_cash_balance'] = '13.94'
        preview[0]['balance']['total_net_liquidation_value'] = '172.76'
        preview[0]['positions'] = []
        import_webull_portfolio_snapshot(7, preview)

        snapshot = WebullAccountSnapshot.query.filter_by(user_id=7, account_id='cash-account').one()
        cash = WebullHolding.query.filter_by(
            user_id=7, account_id='cash-account', symbol='USD', instrument_type='CASH',
        ).one()
        self.assertEqual(snapshot.total_cash_balance, 13.94)
        self.assertEqual(snapshot.total_net_liquidation_value, 172.76)
        self.assertEqual(cash.current_value, 13.94)
        self.assertEqual(WebullHolding.query.filter_by(user_id=7, instrument_type='EVENT').count(), 0)

    def test_webull_watchlist_keeps_broker_contract_identity_per_user(self):
        item = WebullWatchlistItem(
            user_id=7,
            instrument_id='event-contract-1',
            symbol='KXBTC15M-26SEP011915-15',
            instrument_type='EVENT',
            event_outcome='YES',
            display_name='Bitcoin up in 15 minutes',
            last_price=0.60,
        )
        db.session.add(item)
        db.session.commit()

        stored = WebullWatchlistItem.query.filter_by(user_id=7, symbol=item.symbol).one()
        self.assertEqual(stored.instrument_id, 'event-contract-1')
        self.assertEqual(stored.event_outcome, 'YES')
        self.assertEqual(stored.last_price, 0.60)


if __name__ == '__main__':
    unittest.main()