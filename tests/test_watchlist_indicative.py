"""Watchlist indicative prices (v4.18.3).

A watchlist row can carry a manually maintained indicative price for a
symbol that has no live quote yet (an IPO in Nasdaq price discovery, e.g.
ANT before its opening cross). The list APIs expose the indicative value
alongside the live price; the dashboard shows it, labelled "Indicative",
only while the live price is absent — a real quote always wins.

These tests use an isolated in-memory SQLite database and mock every
external price source; nothing touches a broker, Yahoo, or the app DB.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager

from core.extensions import db
from models import WatchlistCoin, WebullWatchlistItem
from routes.portfolio import portfolio_bp

ROOT = Path(__file__).resolve().parents[1]


class WatchlistIndicativeTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SECRET_KEY='watchlist-indicative-test',
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
        db.session.add(WatchlistCoin(symbol='ANT', user_id=1, current_price=0.0,
                                     hidden=False, alert_enabled=False, asset_type='stock'))
        db.session.add(WatchlistCoin(symbol='TSLA', user_id=2, current_price=0.0,
                                     hidden=False, alert_enabled=False, asset_type='stock'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    # -- helpers -----------------------------------------------------------
    def _row(self, symbol='ANT', user_id=1):
        return WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()

    def _list_payload(self):
        with patch('routes.portfolio.get_user_latest_news_cache', return_value={}), \
                patch('routes.market._get_binance_24h_tickers', return_value={}):
            resp = self.client.get('/api/watchlist')
        self.assertEqual(resp.status_code, 200)
        return {row['symbol']: row for row in resp.get_json()}

    def _live_payload(self, stock_price):
        with patch('routes.portfolio.get_user_latest_news_cache', return_value={}), \
                patch('routes.market._get_binance_24h_tickers', return_value={}), \
                patch('routes.portfolio._fetch_stock_price_yf', return_value=stock_price), \
                patch('routes.portfolio.fetch_binance_price', return_value=0.0):
            resp = self.client.get('/api/watchlist-live')
        self.assertEqual(resp.status_code, 200)
        return {row['symbol']: row for row in resp.get_json()}

    def _set(self, payload):
        return self.client.post('/api/watchlist/indicative', json=payload)

    # -- setter ------------------------------------------------------------
    def test_set_indicative_price_and_list_exposes_it(self):
        resp = self._set({'symbol': 'ANT', 'indicative_price': 74.25, 'source': 'Nasdaq NOII'})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['indicative_price'], 74.25)
        self.assertEqual(body['indicative_source'], 'Nasdaq NOII')
        self.assertIsNotNone(body['indicative_updated_at'])

        row = self._row()
        self.assertEqual(row.indicative_price, 74.25)
        self.assertEqual(row.indicative_source, 'Nasdaq NOII')
        self.assertIsNotNone(row.indicative_updated_at)

        listed = self._list_payload()['ANT']
        self.assertEqual(listed['indicative_price'], 74.25)
        self.assertEqual(listed['indicative_source'], 'Nasdaq NOII')
        self.assertIsNotNone(listed['indicative_updated_at'])
        self.assertEqual(listed['current_price'], 0.0)

    def test_clear_indicative_price_with_null(self):
        self._set({'symbol': 'ANT', 'indicative_price': 74.25, 'source': 'Nasdaq NOII'})
        resp = self._set({'symbol': 'ANT', 'indicative_price': None})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertIsNone(body['indicative_price'])
        self.assertIsNone(body['indicative_updated_at'])
        self.assertIsNone(body['indicative_source'])

        row = self._row()
        self.assertIsNone(row.indicative_price)
        self.assertIsNone(row.indicative_updated_at)
        self.assertIsNone(row.indicative_source)
        self.assertIsNone(self._list_payload()['ANT']['indicative_price'])

    def test_invalid_indicative_values_are_rejected(self):
        for payload in (
            {'symbol': 'ANT', 'indicative_price': -3},
            {'symbol': 'ANT', 'indicative_price': 0},
            {'symbol': 'ANT', 'indicative_price': 'abc'},
            {'indicative_price': 74.25},
        ):
            with self.subTest(payload=payload):
                resp = self._set(payload)
                self.assertEqual(resp.status_code, 400)
                self.assertFalse(resp.get_json()['success'])
        self.assertIsNone(self._row().indicative_price)

    def test_unknown_symbol_returns_404(self):
        resp = self._set({'symbol': 'NOPE', 'indicative_price': 10})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()['success'])

    def test_cannot_set_another_users_row(self):
        # TSLA belongs to user 2 only; user 1 must not reach it.
        resp = self._set({'symbol': 'TSLA', 'indicative_price': 250})
        self.assertEqual(resp.status_code, 404)
        self.assertIsNone(self._row(symbol='TSLA', user_id=2).indicative_price)

    # -- live list: indicative vs live quote -------------------------------
    def test_live_list_without_quote_keeps_indicative(self):
        self._set({'symbol': 'ANT', 'indicative_price': 74.25, 'source': 'Nasdaq NOII'})
        listed = self._live_payload(stock_price=0.0)['ANT']
        self.assertEqual(listed['current_price'], 0.0)
        self.assertEqual(listed['indicative_price'], 74.25)
        self.assertEqual(listed['indicative_source'], 'Nasdaq NOII')

    def test_live_list_with_quote_reports_live_price(self):
        self._set({'symbol': 'ANT', 'indicative_price': 74.25, 'source': 'Nasdaq NOII'})
        listed = self._live_payload(stock_price=91.5)['ANT']
        # The live quote is present and positive, so the dashboard renders it
        # and ignores the indicative value: live always wins.
        self.assertEqual(listed['current_price'], 91.5)
        self.assertEqual(listed['indicative_price'], 74.25)

    # -- schema / frontend wiring ------------------------------------------
    def test_model_and_migration_cover_indicative_columns(self):
        columns = set(WatchlistCoin.__table__.columns.keys())
        for name in ('indicative_price', 'indicative_updated_at', 'indicative_source'):
            self.assertIn(name, columns)
        database_py = (ROOT / 'database.py').read_text(encoding='utf-8')
        for name in ('indicative_price', 'indicative_updated_at', 'indicative_source'):
            self.assertIn('("watchlist", "%s"' % name, database_py)

    def test_dashboard_renders_indicative_badge_only_without_live_price(self):
        jsx = (ROOT / 'frontend/src/pages/Dashboard.jsx').read_text(encoding='utf-8')
        self.assertIn('item.indicative_price', jsx)
        self.assertIn('Indicative', jsx)
        self.assertIn('!(livePrice > 0) && indicativePrice > 0', jsx)


if __name__ == '__main__':
    unittest.main()
