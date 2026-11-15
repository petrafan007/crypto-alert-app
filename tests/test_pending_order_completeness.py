"""Pending-order and portfolio readers must say which sources answered in full.

A source that failed is reported as incomplete, never as an empty account, so
the dashboard can keep its last confirmed rows for that source only.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from core.extensions import db
from credentials import UserSetting
from models import Coin, WatchlistCoin, WebullOrder
from tests import test_synthetic_order_lifecycle as base


class PendingOrderCompletenessTests(unittest.TestCase):
    setUp, tearDown, create = base.SyntheticLifecycleTests.setUp, base.SyntheticLifecycleTests.tearDown, base.SyntheticLifecycleTests.create

    def live(self):
        for model in (Coin, WatchlistCoin, WebullOrder):
            model.__table__.create(db.engine, checkfirst=True)
        db.session.get(UserSetting, 1).webull_test_mode_enabled = False
        db.session.commit()

    def read(self, creds):
        from routes import portfolio
        stub = SimpleNamespace(query=SimpleNamespace(filter_by=lambda **_: SimpleNamespace(first=lambda: creds)))
        with self.app.test_request_context(), patch.object(portfolio, 'current_user', SimpleNamespace(id=1, username='tester')), \
                patch.object(portfolio, 'Credential', stub), patch.object(portfolio, 'decrypt_secret', side_effect=lambda value: value):
            response = portfolio.api_pending_orders.__wrapped__()
        return response.get_json()

    @staticmethod
    def scopes(data):
        return {scope['key']: scope['complete'] for scope in data['scopes']}

    def test_failed_sources_are_incomplete_and_working_sources_are_complete(self):
        self.live()
        self.create(broker='webull', instrument_type='EQUITY', symbol='NVDA', side='BUY', total_quantity=1, account_id='A',
                    trading_session='ALL', test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        creds = SimpleNamespace(api_key='k', api_secret='s', webull_token_status='NORMAL', webull_token_environment='production',
                                webull_access_token='t', webull_app_key='k', webull_app_secret='s')

        def open_orders(*_args, account_id=None, **_kwargs):
            if account_id == 'B':
                raise RuntimeError('rate limited')
            return [{'order_id': '77', 'symbol': 'AAPL', 'side': 'BUY', 'status': 'SUBMITTED', 'limit_price': '10',
                     'total_quantity': '3', 'filled_quantity': '1', '_webull_account_id': 'A'}]

        with patch('binance.client.Client', side_effect=RuntimeError('exchange offline')), \
                patch('services.webull_import_service._webull_import_account_ids', return_value=['A', 'B']), \
                patch('services.webull_service.get_webull_open_orders', side_effect=open_orders):
            data = self.read(creds)

        self.assertEqual(self.scopes(data), {'binance': False, 'synthetic': True, 'webull:A': True, 'webull:B': False})
        self.assertFalse(data['complete'])
        self.assertEqual(data['mode'], 'production:live')
        self.assertTrue(all(scope.get('reason') for scope in data['scopes'] if not scope['complete']))
        ids = {order['order_id'] for order in data['pending_orders']}
        self.assertEqual(ids, {'77', next(i for i in ids if str(i).startswith('ladder_'))})
        native = next(order for order in data['pending_orders'] if order['order_id'] == '77')
        self.assertEqual((native['account_id'], native['quantity']), ('A', 2.0))

    def test_an_answering_source_with_no_orders_is_complete_and_empty(self):
        self.live()
        creds = SimpleNamespace(api_key='k', api_secret='s', webull_token_status='NORMAL', webull_token_environment='production',
                                webull_access_token='t', webull_app_key='k', webull_app_secret='s')
        with patch('binance.client.Client') as client, \
                patch('services.webull_import_service._webull_import_account_ids', return_value=['A']), \
                patch('services.webull_service.get_webull_open_orders', return_value=[]):
            client.return_value.get_open_orders.return_value = []
            data = self.read(creds)
        self.assertEqual(data['pending_orders'], [])
        self.assertEqual(self.scopes(data), {'binance': True, 'synthetic': True, 'webull:A': True})
        self.assertTrue(data['complete'])

    def test_a_webull_session_that_cannot_read_orders_is_incomplete_not_empty(self):
        self.live()
        creds = SimpleNamespace(api_key=None, api_secret=None, webull_token_status='PENDING', webull_token_environment='production',
                                webull_access_token='t', webull_app_key='k', webull_app_secret='s')
        data = self.read(creds)
        self.assertEqual(self.scopes(data), {'synthetic': True, 'webull:*': False})

    def test_paper_mode_is_reported_and_the_fast_reader_hides_live_webull_orders(self):
        from services.portfolio_service import get_fast_pending_orders, get_pending_order_mode
        self.live()
        db.session.add(WebullOrder(user_id=1, account_id='A', symbol='AAPL', side='BUY', status='SUBMITTED', quantity=1, price=10,
                                   provider_order_id='55'))
        db.session.commit()
        self.assertEqual(get_pending_order_mode(1), 'production:live')
        self.assertEqual([order['order_id'] for order in get_fast_pending_orders(1) if order['provider'] == 'webull'], ['55'])
        db.session.get(UserSetting, 1).webull_test_mode_enabled = True
        db.session.commit()
        self.assertEqual(get_pending_order_mode(1), 'production:paper')
        self.assertEqual([order for order in get_fast_pending_orders(1) if order['provider'] == 'webull'], [])


if __name__ == '__main__':
    unittest.main()
