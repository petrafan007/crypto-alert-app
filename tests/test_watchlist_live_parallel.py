"""Watchlist-live parallel price fetching (v4.19.2).

/api/watchlist-live used to fetch each watchlist symbol's price serially,
so the endpoint (and the dashboard's first watchlist paint, which waited
on it) took seconds on multi-symbol watchlists. The fetches now run
concurrently. These tests pin the contract that must not change: the
payload matches the serial version's (same rows, same watchlist order,
same fields), fresh prices are persisted on the rows, and one symbol's
failing fetch neither breaks the request nor loses the other symbols'
fresh prices — the failing row keeps its stored price.

Isolated in-memory SQLite; every external price source is mocked.
"""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager

from core.extensions import db
from models import WatchlistCoin, WebullWatchlistItem
from routes.portfolio import portfolio_bp

PRICES = {'BTC': 91000.5, 'ETH': 3400.25, 'XRP': 2.35, 'SOL': 210.75}
STORED = {'BTC': 90000.0, 'ETH': 3300.0, 'XRP': 2.0, 'SOL': 200.0}


class WatchlistLiveParallelTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SECRET_KEY='watchlist-live-parallel-test',
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
        for symbol in ('BTC', 'ETH', 'SOL', 'XRP'):
            db.session.add(WatchlistCoin(symbol=symbol, user_id=1,
                                         current_price=STORED[symbol],
                                         hidden=False, alert_enabled=False,
                                         asset_type='crypto'))
        db.session.add(WatchlistCoin(symbol='ANT', user_id=1, current_price=83.0,
                                     hidden=False, alert_enabled=False,
                                     asset_type='stock'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def _live(self, binance_side_effect, stock_price=95.25):
        with patch('routes.portfolio.get_user_latest_news_cache', return_value={}), \
                patch('routes.market._get_binance_24h_tickers', return_value={}), \
                patch('routes.portfolio._fetch_stock_price_yf', return_value=stock_price), \
                patch('routes.portfolio.fetch_binance_price', side_effect=binance_side_effect):
            resp = self.client.get('/api/watchlist-live')
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def test_parallel_fetch_returns_full_payload_in_watchlist_order(self):
        # Later symbols answer first: completion order must not leak into
        # the response, which stays in watchlist (symbol) order.
        delays = {'BTC': 0.12, 'ETH': 0.08, 'SOL': 0.04, 'XRP': 0.0}

        def fetch(symbol):
            time.sleep(delays[symbol])
            return PRICES[symbol]

        rows = self._live(fetch)
        self.assertEqual([r['symbol'] for r in rows],
                         ['ANT', 'BTC', 'ETH', 'SOL', 'XRP'])
        by_symbol = {r['symbol']: r for r in rows}
        for symbol, price in PRICES.items():
            self.assertEqual(by_symbol[symbol]['current_price'], price)
        self.assertEqual(by_symbol['ANT']['current_price'], 95.25)
        # Fresh prices are persisted on the rows, as the serial version did.
        for symbol, price in PRICES.items():
            row = WatchlistCoin.query.filter_by(user_id=1, symbol=symbol).first()
            self.assertEqual(row.current_price, price)

    def test_prices_are_fetched_concurrently(self):
        threads = set()
        lock = threading.Lock()

        def fetch(symbol):
            with lock:
                threads.add(threading.get_ident())
            time.sleep(0.05)
            return PRICES[symbol]

        self._live(fetch)
        self.assertGreaterEqual(len(threads), 2)

    def test_one_failing_symbol_keeps_stored_price_and_others_still_update(self):
        def fetch(symbol):
            if symbol == 'ETH':
                raise RuntimeError('binance down')
            return PRICES[symbol]

        rows = self._live(fetch)
        by_symbol = {r['symbol']: r for r in rows}
        self.assertEqual(by_symbol['ETH']['current_price'], STORED['ETH'])
        for symbol in ('BTC', 'SOL', 'XRP'):
            self.assertEqual(by_symbol[symbol]['current_price'], PRICES[symbol])
        eth = WatchlistCoin.query.filter_by(user_id=1, symbol='ETH').first()
        self.assertEqual(eth.current_price, STORED['ETH'])


if __name__ == '__main__':
    unittest.main()
