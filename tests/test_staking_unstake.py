import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from datetime import datetime, timedelta

from flask import Flask
from core.extensions import db
from models import StakedCoin
from trading_models import StakingOrder
from services import staking_service
import routes.portfolio as portfolio


class StakingUnstakeTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_build_staking_balance_view_populates_staking_amount_and_links_db(self):
        cred = SimpleNamespace(api_key='key', api_secret='sec', user_id=1)
        record = StakedCoin(
            user_id=1,
            symbol='GRAM',
            amount=68.64,
            status='processing',
            unstaking_period_hours=18,
            staked_at=datetime.utcnow()
        )
        db.session.add(record)
        db.session.commit()
        record_id = record.id

        mock_balance_resp = MagicMock()
        mock_balance_resp.status_code = 200
        mock_balance_resp.json.return_value = {
            'success': True,
            'data': [{'asset': 'GRAM', 'amount': '68.64'}]
        }
        mock_asset_resp = MagicMock(status_code=200)
        mock_asset_resp.json.return_value = {'data': []}
        mock_hist_resp = MagicMock(status_code=200)
        mock_hist_resp.json.return_value = {'data': []}

        with patch.object(staking_service, 'binance_us_api_call', side_effect=[mock_balance_resp, mock_asset_resp, mock_hist_resp]),              patch.object(staking_service, 'fetch_binance_price', return_value=1.5):
            
            result = staking_service.build_staking_balance_view(cred)
            active = result.get('activePositions', [])
            self.assertEqual(len(active), 1)
            pos = active[0]
            self.assertEqual(pos['asset'], 'GRAM')
            self.assertEqual(pos['amount'], 68.64)
            self.assertEqual(pos['stakingAmount'], 68.64)
            self.assertEqual(pos.get('id'), record_id)
            self.assertEqual(pos.get('unstaking_period_hours'), 18)
            
            refreshed = db.session.get(StakedCoin, record_id)
            self.assertEqual(refreshed.status, 'active')


    def test_api_unstake_asset_supports_symbol_lookup(self):
        record = StakedCoin(
            user_id=1,
            symbol='GRAM',
            amount=68.64,
            status='active',
            unstaking_period_hours=18,
            staked_at=datetime.utcnow()
        )
        db.session.add(record)
        db.session.commit()
        record_id = record.id

        cred = SimpleNamespace(api_key='key', api_secret='sec', username='jcavallarojr')
        mock_unstake_resp = MagicMock()
        mock_unstake_resp.status_code = 200
        mock_unstake_resp.json.return_value = {'success': True}

        with self.app.test_request_context('/api/staking/unstake', method='POST', json={'asset': 'GRAM', 'amount': 68.64}), \
             patch('routes.portfolio.current_user', SimpleNamespace(id=1, username='jcavallarojr')), \
             patch('routes.portfolio.TradingSettings.query') as mock_settings, \
             patch('routes.portfolio.get_user_credentials', return_value=cred), \
             patch('routes.portfolio.binance_us_api_call', return_value=mock_unstake_resp), \
             patch('routes.portfolio.trigger_portfolio_snapshot'):
            mock_settings.filter_by.return_value.first.return_value = None
            
            resp = portfolio.api_unstake_asset.__wrapped__()
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('success'))
            
            refreshed = db.session.get(StakedCoin, record_id)
            self.assertEqual(refreshed.status, 'unstaking')

    def test_build_staking_balance_view_auto_reconciles_successful_unstake_from_history(self):
        cred = SimpleNamespace(api_key='key', api_secret='sec', user_id=1)
        record = StakedCoin(
            user_id=1,
            symbol='GRAM',
            amount=68.64,
            status='unstaking',
            unstake_requested_at=datetime.utcnow() - timedelta(days=2),
            unstake_available_at=datetime.utcnow() - timedelta(days=1),
            staked_at=datetime.utcnow() - timedelta(days=10)
        )
        db.session.add(record)
        order = StakingOrder(
            user_id=1,
            symbol='GRAM',
            action='unstake',
            amount=68.64,
            status='PROCESSING',
            created_at=datetime.utcnow() - timedelta(days=2)
        )
        db.session.add(order)
        db.session.commit()
        record_id = record.id
        order_id = order.id

        mock_balance_resp = MagicMock(status_code=200)
        mock_balance_resp.json.return_value = {'success': True, 'data': []}
        mock_asset_resp = MagicMock(status_code=200)
        mock_asset_resp.json.return_value = {'data': []}
        mock_hist_resp = MagicMock(status_code=200)
        mock_hist_resp.json.return_value = {
            'data': [{'asset': 'GRAM', 'amount': '68.64', 'type': 'unstaked', 'status': 'SUCCESS', 'initiatedTime': 1793857579781}]
        }

        with patch.object(staking_service, 'binance_us_api_call', side_effect=[mock_balance_resp, mock_asset_resp, mock_hist_resp]), \
             patch.object(staking_service, 'fetch_binance_price', return_value=1.14):
            result = staking_service.build_staking_balance_view(cred)
            self.assertEqual(len(result.get('pendingPositions', [])), 0)
            self.assertEqual(len(result.get('activePositions', [])), 0)
            self.assertEqual(result.get('summary', {}).get('pendingCount'), 0)
            self.assertEqual(result.get('summary', {}).get('totalUsd'), 0.0)

            refreshed_rec = db.session.get(StakedCoin, record_id)
            self.assertEqual(refreshed_rec.status, 'unstaked')

            refreshed_order = db.session.get(StakingOrder, order_id)
            self.assertEqual(refreshed_order.status, 'COMPLETED')

    def test_build_staking_balance_view_auto_reconciles_expired_unstake(self):
        cred = SimpleNamespace(api_key='key', api_secret='sec', user_id=1)
        record = StakedCoin(
            user_id=1,
            symbol='GRAM',
            amount=68.64,
            status='unstaking',
            unstake_requested_at=datetime.utcnow() - timedelta(days=5),
            unstake_available_at=datetime.utcnow() - timedelta(days=4),
            staked_at=datetime.utcnow() - timedelta(days=15)
        )
        db.session.add(record)
        db.session.commit()
        record_id = record.id

        mock_balance_resp = MagicMock(status_code=200)
        mock_balance_resp.json.return_value = {'success': True, 'data': []}
        mock_asset_resp = MagicMock(status_code=200)
        mock_asset_resp.json.return_value = {'data': []}
        mock_hist_resp = MagicMock(status_code=200)
        mock_hist_resp.json.return_value = {'data': []}

        with patch.object(staking_service, 'binance_us_api_call', side_effect=[mock_balance_resp, mock_asset_resp, mock_hist_resp]), \
             patch.object(staking_service, 'fetch_binance_price', return_value=1.14):
            result = staking_service.build_staking_balance_view(cred)
            self.assertEqual(len(result.get('pendingPositions', [])), 0)
            refreshed_rec = db.session.get(StakedCoin, record_id)
            self.assertEqual(refreshed_rec.status, 'unstaked')

    def test_get_user_staked_balance_map_clears_completed_unstake(self):
        record = StakedCoin(
            user_id=1,
            symbol='GRAM',
            amount=68.64,
            status='unstaking',
            unstake_requested_at=datetime.utcnow() - timedelta(days=5),
            unstake_available_at=datetime.utcnow() - timedelta(days=4),
            staked_at=datetime.utcnow() - timedelta(days=15)
        )
        db.session.add(record)
        db.session.commit()

        s_map = staking_service.get_user_staked_balance_map(1)
        self.assertNotIn('GRAM', s_map)


if __name__ == '__main__':
    unittest.main()
