"""Backend & safety-invariant tests for Global Mode, Paper & QSE Adapters,
isolated Paper Watchlist, mode-scoped Hide/Unhide, and mode-scoped Orders.
"""
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask, g
from flask_login import LoginManager

from core.extensions import db
from credentials import User, UserSetting
from models import Coin, PaperWatchlistItem, WatchlistCoin, WebullTestAccount, WebullTestOrder, WebullTestPosition
from portfolio_algo_models import (
    PortfolioEngineState,
    PortfolioStrategyAccount,
    PortfolioStrategyConfig,
    PortfolioStrategyLot,
    PortfolioStrategyOrder,
    PortfolioStrategyPosition,
)
from routes.auth import auth_bp
from routes.dashboard_modes import dashboard_modes_bp
from routes.portfolio import portfolio_bp
from routes.portfolio_algo import portfolio_algo_bp
from routes.system import system_bp
from trading_models import TestOrder, TestPortfolio, TradingSettings


class GlobalModeAndDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SECRET_KEY'] = 'test-global-mode-secret'
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(cls.app)
        lm = LoginManager()
        lm.init_app(cls.app)

        @lm.user_loader
        def load_user(uid):
            return db.session.get(User, int(uid))

        @lm.unauthorized_handler
        def unauth():
            return {'error': 'Authentication required'}, 401

        @cls.app.before_request
        def clear_login_cache():
            g.pop('_login_user', None)

        cls.app.register_blueprint(auth_bp)
        cls.app.register_blueprint(dashboard_modes_bp)
        cls.app.register_blueprint(portfolio_bp)
        cls.app.register_blueprint(portfolio_algo_bp)
        cls.app.register_blueprint(system_bp)
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.admin = User(id=1, username='admin_user', pwd_hash='x')
        self.regular = User(id=2, username='regular_user', pwd_hash='x')
        db.session.add_all([self.admin, self.regular])
        db.session.add_all([
            UserSetting(user_id=1, global_trading_mode='real', webull_test_mode_enabled=False),
            UserSetting(user_id=2, global_trading_mode='real', webull_test_mode_enabled=False),
            TradingSettings(user_id=1, test_mode_enabled=False),
            TradingSettings(user_id=2, test_mode_enabled=False),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.ctx.pop()

    def _client_for(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        return client

    def test_global_mode_persistence_sync_and_admin_gate(self):
        admin_c = self._client_for(1)
        reg_c = self._client_for(2)

        # Default is real
        r = admin_c.get('/api/global-mode')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['mode'], 'real')

        # Switch to paper syncs both broker flags
        r = admin_c.post('/api/global-mode', json={'mode': 'paper'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['mode'], 'paper')
        self.assertTrue(r.get_json()['webull_test_mode_enabled'])
        self.assertTrue(r.get_json()['binance_test_mode_enabled'])
        self.assertTrue(UserSetting.query.filter_by(user_id=1).first().webull_test_mode_enabled)
        self.assertTrue(TradingSettings.query.filter_by(user_id=1).first().test_mode_enabled)

        # /api/session reflects persisted global_trading_mode
        sess_r = admin_c.get('/api/session')
        self.assertEqual(sess_r.get_json()['global_trading_mode'], 'paper')
        self.assertEqual(sess_r.get_json()['user']['global_trading_mode'], 'paper')

        # Admin can switch to qse; broker test flags reset to False (QSE is read-only)
        r = admin_c.post('/api/global-mode', json={'mode': 'qse'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['mode'], 'qse')
        self.assertFalse(UserSetting.query.filter_by(user_id=1).first().webull_test_mode_enabled)
        self.assertFalse(TradingSettings.query.filter_by(user_id=1).first().test_mode_enabled)

        # Non-admin rejected with 403 on qse, allowed on paper
        self.assertEqual(reg_c.post('/api/global-mode', json={'mode': 'qse'}).status_code, 403)
        self.assertEqual(reg_c.post('/api/global-mode', json={'mode': 'paper'}).status_code, 200)
        self.assertEqual(reg_c.post('/api/global-mode', json={'mode': 'bogus'}).status_code, 400)

    def test_paper_portfolio_merges_ledgers_and_handles_partial_failure(self):
        admin_c = self._client_for(1)
        db.session.add(WebullTestAccount(user_id=1, cash_balance=10000.0))
        db.session.add(WebullTestPosition(
            user_id=1, symbol='AAPL', instrument_type='EQUITY', side='LONG',
            quantity=10.0, cost_price=150.0, last_price=165.0, market_value=1650.0, unrealized_pnl=150.0,
        ))
        db.session.add(TestPortfolio(user_id=1, symbol='USD', quantity=500.0, avg_entry_price=1.0, total_cost_basis=500.0))
        db.session.add(TestPortfolio(user_id=1, symbol='USDT', quantity=250.0, avg_entry_price=1.0, total_cost_basis=250.0))
        db.session.add(TestPortfolio(user_id=1, symbol='BTC', quantity=0.5, avg_entry_price=60000.0, total_cost_basis=30000.0))
        db.session.add(TestOrder(user_id=1, symbol='BTCUSDT', side='BUY', type='LIMIT', quantity=0.1, price=55000.0, status='NEW'))
        db.session.commit()

        with patch('services.webull_paper_trading_service.fetch_live_price', return_value=165.0), \
             patch('services.binance_service.fetch_binance_price', return_value=70000.0):
            r = admin_c.get('/api/dashboard/paper-portfolio')
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body['pending_mode'], 'paper')
        self.assertTrue(body['sources']['webull_test']['complete'])
        self.assertTrue(body['sources']['binance_paper']['complete'])
        by_sym = {row['symbol']: row for row in body['portfolio']}
        self.assertIn('AAPL', by_sym)
        self.assertIn('BTC', by_sym)
        self.assertEqual(by_sym['AAPL']['avg_entry'], 150.0)
        self.assertEqual(by_sym['AAPL']['cost_basis'], 1500.0)
        self.assertEqual(by_sym['AAPL']['source'], 'webull_test')
        self.assertEqual(by_sym['BTC']['source'], 'binance_paper')
        self.assertEqual(by_sym['BTC']['current_value'], 35000.0)
        # Binance paper total = holdings (35000) + USD (500) + USDT (250) = 35750
        self.assertEqual(body['account_totals']['binance'], 35750.0)
        self.assertEqual(body['account_totals']['webull'], 11650.0)
        self.assertEqual(body['account_totals']['all'], 47400.0)
        self.assertEqual(len(body['pending_orders']), 1)
        self.assertTrue(all(o['is_paper'] for o in body['pending_orders']))

        # S10: partial failure reports complete=False for failing ledger while returning the other
        with patch('services.webull_paper_trading_service.get_webull_test_account_summary', side_effect=RuntimeError('boom')), \
             patch('services.binance_service.fetch_binance_price', return_value=70000.0):
            r2 = admin_c.get('/api/dashboard/paper-portfolio')
        self.assertEqual(r2.status_code, 200)
        b2 = r2.get_json()
        self.assertFalse(b2['sources']['webull_test']['complete'])
        self.assertTrue(b2['sources']['binance_paper']['complete'])
        self.assertEqual([row['symbol'] for row in b2['portfolio']], ['BTC'])

    def test_paper_watchlist_crud_scoping_and_strict_isolation(self):
        admin_c = self._client_for(1)
        reg_c = self._client_for(2)

        # Starts empty
        self.assertEqual(admin_c.get('/api/dashboard/paper-watchlist').get_json(), [])

        # Add + idempotent re-add
        r1 = admin_c.post('/api/dashboard/paper-watchlist/add', json={'provider': 'webull', 'symbol': 'NVDA', 'instrument_type': 'EQUITY'})
        self.assertEqual(r1.status_code, 201)
        item_id = r1.get_json()['item']['id']
        r2 = admin_c.post('/api/dashboard/paper-watchlist/add', json={'provider': 'webull', 'symbol': 'nvda', 'instrument_type': 'EQUITY'})
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.get_json()['created'])

        # User 2 cannot read or remove User 1's row
        self.assertEqual(reg_c.get('/api/dashboard/paper-watchlist').get_json(), [])
        self.assertEqual(reg_c.post('/api/dashboard/paper-watchlist/remove', json={'id': item_id}).status_code, 404)

        # S5: Real watchlist is completely disjoint from paper watchlist
        db.session.add(WatchlistCoin(user_id=1, symbol='ETH', asset_type='crypto'))
        db.session.commit()
        real_wl = admin_c.get('/api/watchlist').get_json()
        paper_wl = admin_c.get('/api/dashboard/paper-watchlist').get_json()
        self.assertEqual([r['symbol'] for r in real_wl], ['ETH'])
        self.assertEqual([r['symbol'] for r in paper_wl], ['NVDA'])

        # S6: No alert/sentiment/auto-trade service references PaperWatchlistItem
        for path in Path('services').glob('*.py'):
            src = path.read_text(encoding='utf-8')
            self.assertNotIn('PaperWatchlistItem', src, f'{path} must not touch PaperWatchlistItem')
            self.assertNotIn('paper_watchlist_items', src, f'{path} must not touch paper_watchlist_items')

        # Remove succeeds for owner
        self.assertEqual(admin_c.post('/api/dashboard/paper-watchlist/remove', json={'id': item_id}).status_code, 200)
        self.assertEqual(admin_c.get('/api/dashboard/paper-watchlist').get_json(), [])

    def test_qse_endpoints_admin_only_get_only_pure_read_and_honest_prices(self):
        admin_c = self._client_for(1)
        reg_c = self._client_for(2)

        # Seed QSE account, state, position, lot, and open order
        db.session.add(PortfolioStrategyConfig(user_id=1))
        db.session.add(PortfolioStrategyAccount(user_id=1, initial_balance=50000.0, cash_balance=48000.0, total_equity=50200.0))
        db.session.add(PortfolioEngineState(user_id=1, generation=1))
        pos = PortfolioStrategyPosition(user_id=1, symbol='SPY', instrument_type='EQUITY', side='LONG',
                                        quantity=5.0, average_cost=400.0, market_price=440.0, market_value=2200.0, unrealized_pnl=200.0)
        db.session.add(pos)
        db.session.flush()
        db.session.add(PortfolioStrategyLot(user_id=1, position_id=pos.id, generation=1, module='equities',
                                            signal_key='equities:SPY:2026-11-20', collateral=2000.0, multiplier=1.0))
        db.session.add(PortfolioStrategyOrder(user_id=1, module_name='EQUITIES', symbol='SPY', instrument_type='EQUITY',
                                              side='BUY', order_type='LIMIT', quantity=2.0, price=435.0, status='OPEN'))
        db.session.commit()

        # S7: Non-admin gets 403; non-GET gets 405
        for ep in ('/api/dashboard/qse-portfolio', '/api/dashboard/qse-watchlist'):
            self.assertEqual(reg_c.get(ep).status_code, 403)
            self.assertEqual(admin_c.post(ep, json={}).status_code, 405)
            self.assertEqual(admin_c.put(ep, json={}).status_code, 405)
            self.assertEqual(admin_c.delete(ep).status_code, 405)

        # S8: QSE portfolio pure read model
        r = admin_c.get('/api/dashboard/qse-portfolio')
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body['read_only'])
        self.assertEqual(body['account_totals']['all'], 50200.0)
        self.assertEqual(body['account_totals']['binance'], 0.0)
        self.assertEqual(body['pending_mode'], 'quant')
        self.assertEqual(body['portfolio'][0]['id'], f'QUANT_POS_{pos.id}')
        self.assertEqual(body['portfolio'][0]['module'], 'equities')
        self.assertEqual(len(body['pending_orders']), 1)

        # S13: QSE watchlist futures & events emit null price and price_state='none'
        with patch('routes.dashboard_modes._fetch_live_paper_price', return_value=123.45):
            wr = admin_c.get('/api/dashboard/qse-watchlist')
        self.assertEqual(wr.status_code, 200)
        wbody = wr.get_json()
        self.assertEqual(wbody['module_order'], ['equities', 'options', 'crypto', 'futures', 'events'])
        for row in wbody['rows']:
            if row['module'] in ('futures', 'events'):
                self.assertIsNone(row['current_price'])
                self.assertEqual(row['price_state'], 'none')
            else:
                self.assertEqual(row['price_state'], 'live')

    def test_mode_scoped_hide_unhide_and_orders(self):
        admin_c = self._client_for(1)
        real_coin = Coin(user_id=1, symbol='ADA', amount=10.0, hidden=False)
        paper_tp = TestPortfolio(user_id=1, symbol='SOL', quantity=5.0, avg_entry_price=100.0, total_cost_basis=500.0, hidden=False)
        paper_wb = WebullTestPosition(user_id=1, symbol='MSFT', instrument_type='EQUITY', side='LONG', quantity=2.0, cost_price=400.0, hidden=False)
        db.session.add_all([real_coin, paper_tp, paper_wb])
        db.session.commit()

        # Hide paper assets does not touch real assets
        self.assertEqual(admin_c.post('/api/hide-coin', json={'id': f'binance-paper-{paper_tp.id}', 'hidden': True, 'mode': 'paper'}).status_code, 200)
        self.assertEqual(admin_c.post('/api/hide-coin', json={'id': f'paper_pos_{paper_wb.id}', 'hidden': True, 'mode': 'paper'}).status_code, 200)

        hidden_paper = admin_c.get('/api/hidden-coins?mode=paper').get_json()
        self.assertEqual({h['symbol'] for h in hidden_paper}, {'SOL', 'MSFT'})
        self.assertEqual(admin_c.get('/api/hidden-coins?mode=real').get_json(), [])
        self.assertEqual(admin_c.get('/api/hidden-coins?mode=qse').get_json(), [])
        self.assertEqual(admin_c.post('/api/hide-coin', json={'id': 'x', 'mode': 'qse'}).status_code, 403)
        self.assertEqual(admin_c.post('/api/unhide-all', json={'coin_ids': ['x'], 'mode': 'qse'}).status_code, 403)

        # Unhide paper assets
        self.assertEqual(admin_c.post('/api/unhide-all', json={
            'coin_ids': [f'binance-paper-{paper_tp.id}', f'paper_pos_{paper_wb.id}'],
            'mode': 'paper',
        }).status_code, 200)
        self.assertEqual(admin_c.get('/api/hidden-coins?mode=paper').get_json(), [])

        # Mode-scoped orders API
        db.session.add(TestOrder(user_id=1, symbol='ETHUSDT', side='BUY', type='LIMIT', quantity=1.0, price=2000.0, status='NEW'))
        db.session.add(PortfolioStrategyOrder(user_id=1, module_name='EQUITIES', symbol='QQQ', instrument_type='EQUITY',
                                              side='BUY', order_type='MARKET', quantity=3.0, price=450.0, status='FILLED'))
        db.session.commit()
        p_ord = admin_c.get('/api/dashboard/orders?mode=paper').get_json()
        self.assertTrue(p_ord['success'])
        self.assertEqual(len(p_ord['open_orders']), 1)
        self.assertEqual(p_ord['open_orders'][0]['source'], 'binance')

        q_ord = admin_c.get('/api/dashboard/orders?mode=qse').get_json()
        self.assertTrue(q_ord['success'])
        self.assertTrue(q_ord['read_only'])
        self.assertEqual(len(q_ord['history_orders']), 1)
        self.assertEqual(q_ord['history_orders'][0]['source'], 'webull')
        self.assertEqual(self._client_for(2).get('/api/dashboard/orders?mode=qse').status_code, 403)

    def test_scoped_order_mismatch_and_qse_placement_blocks(self):
        admin_c = self._client_for(1)
        # S4: scope/endpoint mismatch and malformed scope -> 400 with zero orders created
        r1 = admin_c.post('/api/trading/test-order', json={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quantity': 0.1, 'scope': 'real'})
        self.assertEqual(r1.status_code, 400)
        r2 = admin_c.post('/api/trading/test-order', json={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quantity': 0.1, 'scope': 'invalid'})
        self.assertEqual(r2.status_code, 400)
        r3 = admin_c.post('/api/trading/place-order', json={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quantity': 0.1, 'scope': 'paper'})
        self.assertEqual(r3.status_code, 400)
        r4 = admin_c.post('/api/webull/orders/place', json={'symbol': 'AAPL', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 1, 'scope': 'bad'})
        self.assertEqual(r4.status_code, 400)
        self.assertEqual(TestOrder.query.count(), 0)
        self.assertEqual(WebullTestOrder.query.count(), 0)

        # QSE mode blocks manual order placement on both brokers
        admin_c.post('/api/global-mode', json={'mode': 'qse'})
        self.assertEqual(admin_c.post('/api/webull/orders/place', json={'symbol': 'AAPL', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 1}).status_code, 403)
        self.assertEqual(admin_c.post('/api/trading/place-order', json={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quantity': 0.1}).status_code, 403)
        self.assertEqual(admin_c.post('/api/trading/test-order', json={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quantity': 0.1}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
