"""Watchlist stock rows report their Webull identity (v4.19.6).

A watchlist entry stored in the generic table as a stock (asset_type
'stock') is a Webull security. The list payloads used to serve it without
any provider fields, so the dashboard classified the row as a Binance row
and a working Webull order for the symbol — native or synthetic — could
never match it: no pending-order highlight and no Cancel/Replace actions,
even with a live synthetic Limit order working (Joseph's ANT order on the
IPO morning). These tests pin the payload identity, the remove-endpoint
fallback that keeps deleting such rows working, and the pending-order
feed half of the match.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager

from core.extensions import db
from models import WatchlistCoin, WebullWatchlistItem
from routes.portfolio import portfolio_bp
from tests import test_synthetic_order_lifecycle as base


class WatchlistStockProviderTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SECRET_KEY='watchlist-stock-provider-test',
            TESTING=True,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        manager = LoginManager(self.app)

        @manager.user_loader
        def load_user(value):
            return SimpleNamespace(id=int(value), is_authenticated=True, username='tester')

        self.app.register_blueprint(portfolio_bp)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = '1'
        self.ctx = self.app.app_context()
        self.ctx.push()
        WatchlistCoin.__table__.create(db.engine)
        WebullWatchlistItem.__table__.create(db.engine)
        db.session.add(WatchlistCoin(symbol='ANT', user_id=1, current_price=83.0,
                                     hidden=False, alert_enabled=False, asset_type='stock'))
        db.session.add(WatchlistCoin(symbol='BTC', user_id=1, current_price=100.0,
                                     hidden=False, alert_enabled=False, asset_type='crypto'))
        db.session.add(WatchlistCoin(symbol='ANT', user_id=2, current_price=83.0,
                                     hidden=False, alert_enabled=False, asset_type='stock'))
        db.session.add(WebullWatchlistItem(user_id=1, symbol='XYZ', instrument_type='EQUITY'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    # -- helpers -----------------------------------------------------------
    def _coin(self, symbol, user_id=1):
        return WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()

    def _list_payload(self):
        with patch('routes.portfolio.get_user_latest_news_cache', return_value={}), \
                patch('routes.market._get_binance_24h_tickers', return_value={}):
            resp = self.client.get('/api/watchlist')
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def _live_payload(self):
        with patch('routes.portfolio.get_user_latest_news_cache', return_value={}), \
                patch('routes.market._get_binance_24h_tickers', return_value={}), \
                patch('routes.portfolio._fetch_stock_price_yf', return_value=83.0), \
                patch('routes.portfolio.fetch_binance_price', return_value=100.0):
            resp = self.client.get('/api/watchlist-live')
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    @staticmethod
    def _row(payload, symbol):
        return next(row for row in payload if row['symbol'] == symbol)

    # -- payload identity ----------------------------------------------------
    def test_stock_row_reports_webull_identity_in_list(self):
        row = self._row(self._list_payload(), 'ANT')
        self.assertEqual(row['source'], 'webull')
        self.assertEqual(row['provider'], 'webull')
        self.assertIs(row['is_external'], True)
        self.assertEqual(row['instrument_type'], 'EQUITY')

    def test_stock_row_reports_webull_identity_in_live_list(self):
        row = self._row(self._live_payload(), 'ANT')
        self.assertEqual(row['source'], 'webull')
        self.assertEqual(row['provider'], 'webull')
        self.assertIs(row['is_external'], True)
        self.assertEqual(row['instrument_type'], 'EQUITY')

    def test_crypto_row_keeps_historical_shape(self):
        for payload in (self._list_payload(), self._live_payload()):
            row = self._row(payload, 'BTC')
            self.assertNotEqual(row.get('provider'), 'webull')
            self.assertFalse(row.get('is_external'))

    # -- remove endpoint -----------------------------------------------------
    def test_remove_generic_stock_row_via_webull_provider(self):
        ant = self._coin('ANT')
        resp = self.client.post('/api/watchlist/remove',
                                json={'symbol': 'ANT', 'provider': 'webull', 'id': ant.id})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])
        self.assertIsNone(self._coin('ANT'))
        self.assertIsNotNone(self._coin('ANT', user_id=2))

    def test_remove_webull_watchlist_item_via_prefixed_id(self):
        item = WebullWatchlistItem.query.filter_by(user_id=1, symbol='XYZ').first()
        resp = self.client.post('/api/watchlist/remove',
                                json={'symbol': 'XYZ', 'provider': 'webull',
                                      'id': f'webull-watchlist-{item.id}',
                                      'instrument_type': 'EQUITY', 'event_outcome': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])
        self.assertIsNone(WebullWatchlistItem.query.filter_by(user_id=1, symbol='XYZ').first())
        self.assertIsNotNone(self._coin('ANT'))

    def test_remove_webull_provider_never_deletes_a_crypto_row(self):
        btc = self._coin('BTC')
        resp = self.client.post('/api/watchlist/remove',
                                json={'symbol': 'BTC', 'provider': 'webull', 'id': btc.id})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self._coin('BTC'))


class WatchlistPendingFeedTests(unittest.TestCase):
    """The other half of the match: the pending-order feed carries the
    working Webull conditional synthetic in the shared pending shape."""
    setUp, tearDown = base.SyntheticLifecycleTests.setUp, base.SyntheticLifecycleTests.tearDown

    def test_working_webull_conditional_appears_in_pending_feed(self):
        from services import synthetic_conditional_service as conditional
        from services.pending_order_serializer import working_synthetic_orders
        self.rules['step'] = 1
        order = conditional.create_conditional(1, dict(
            strategy_type='LIMIT', symbol='ANT', side='BUY', broker='webull',
            instrument_type='EQUITY', account_id='A', trading_session='ALL',
            total_quantity=5, limit_cap_pct=1, test_mode=False,
            legs=[dict(side='BUY', order_type='LIMIT', price=88)]))
        entries = [e for e in working_synthetic_orders(1) if e.get('symbol') == 'ANT']
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['order_id'], f'ladder_{order.id}')
        self.assertEqual(entry['provider'], 'webull')
        self.assertTrue(entry['is_synthetic'])
        self.assertTrue(entry['is_conditional'])

        order.status = 'CANCELLED'
        db.session.commit()
        self.assertEqual([e for e in working_synthetic_orders(1) if e.get('symbol') == 'ANT'], [])


if __name__ == '__main__':
    unittest.main()
