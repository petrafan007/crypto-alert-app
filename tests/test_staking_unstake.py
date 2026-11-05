import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from datetime import datetime

from flask import Flask
from core.extensions import db
from models import StakedCoin
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


if __name__ == '__main__':
    unittest.main()
