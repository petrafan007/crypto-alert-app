import unittest
from unittest.mock import Mock, patch

from flask import Flask, g

from core.extensions import db, login_manager
from credentials import User, UserSetting
from models import AssetIconCache, Coin
from routes.auth import auth_bp
from routes.market import market_bp
from services.binance_service import update_coins_from_binance_balances
from services.portfolio_service import reveal_hidden_usd_after_completed_trade


class Version2673RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='v2673-test',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        login_manager.init_app(cls.app)

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

        cls.app.register_blueprint(auth_bp)
        cls.app.register_blueprint(market_bp)
        cls.context = cls.app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.context.pop()

    def setUp(self):
        db.session.remove()
        g.pop('_login_user', None)
        for model in (AssetIconCache, Coin, UserSetting, User):
            db.session.query(model).delete()
        db.session.commit()

        self.user = User(username='regression', email='regression@example.com')
        self.user.set_password('CurrentPassword!234')
        db.session.add(self.user)
        db.session.flush()
        db.session.add(UserSetting(
            user_id=self.user.id,
            onboarding_required=False,
            onboarding_completed=True,
        ))
        db.session.commit()

    def client(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = str(self.user.id)
            session['_fresh'] = True
        return client

    def hidden_usd(self):
        coin = Coin(
            user_id=self.user.id,
            symbol='USD',
            amount=125.0,
            current=1.0,
            avg_entry=1.0,
            hidden=True,
            auto_hidden=False,
            force_visible=False,
        )
        db.session.add(coin)
        db.session.commit()
        return coin

    @patch('services.binance_service.fetch_binance_price', return_value=1.0)
    def test_balance_refresh_preserves_manual_usd_hide(self, _mock_price):
        coin = self.hidden_usd()
        update_coins_from_binance_balances(
            self.user.id,
            [{'asset': 'USD', 'free': '125.00', 'locked': '0'}],
        )
        db.session.refresh(coin)
        self.assertTrue(coin.hidden)
        self.assertFalse(coin.force_visible)

    def test_only_completed_usd_market_trade_reveals_usd(self):
        coin = self.hidden_usd()
        self.assertFalse(reveal_hidden_usd_after_completed_trade(self.user.id, 'HYPEUSDT'))
        self.assertTrue(coin.hidden)
        self.assertTrue(reveal_hidden_usd_after_completed_trade(self.user.id, 'BTCUSD'))
        db.session.commit()
        db.session.refresh(coin)
        self.assertFalse(coin.hidden)
        self.assertTrue(coin.force_visible)

    def test_password_update_requires_current_password_and_signup_strength(self):
        client = self.client()
        wrong = client.post('/api/account/password', json={
            'current_password': 'WrongPassword!234',
            'new_password': 'NewValidPassword!234',
            'confirm_password': 'NewValidPassword!234',
        })
        self.assertEqual(wrong.status_code, 400)

        weak = client.post('/api/account/password', json={
            'current_password': 'CurrentPassword!234',
            'new_password': 'too-weak',
            'confirm_password': 'too-weak',
        })
        self.assertEqual(weak.status_code, 400)

        mismatch = client.post('/api/account/password', json={
            'current_password': 'CurrentPassword!234',
            'new_password': 'NewValidPassword!234',
            'confirm_password': 'AnotherPassword!234',
        })
        self.assertEqual(mismatch.status_code, 400)

        success = client.post('/api/account/password', json={
            'current_password': 'CurrentPassword!234',
            'new_password': 'NewValidPassword!234',
            'confirm_password': 'NewValidPassword!234',
        })
        self.assertEqual(success.status_code, 200)
        db.session.refresh(self.user)
        self.assertTrue(self.user.check_password('NewValidPassword!234'))

    @patch('routes.market.requests.get')
    def test_asset_icon_uses_exact_ranked_coingecko_match(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {'id': 'unrelated', 'symbol': 'NOPE', 'name': 'Nope', 'market_cap_rank': 1, 'image': 'https://example.com/nope.png'},
            {'id': 'lower-rank', 'symbol': 'HYPE', 'name': 'Other Hype', 'market_cap_rank': 900, 'image': 'https://example.com/other.png'},
            {'id': 'hyperliquid', 'symbol': 'hype', 'name': 'Hyperliquid', 'market_cap_rank': 10, 'image': 'https://assets.coingecko.com/hype.png'},
        ]
        mock_get.return_value = response

        result = self.client().post('/api/asset-icons', json={'symbols': ['HYPE', 'NOPE', 'HYPE']})
        self.assertEqual(result.status_code, 200)
        payload = result.get_json()['icons']['HYPE']
        self.assertEqual(payload['asset_id'], 'hyperliquid')
        self.assertEqual(payload['icon_url'], 'https://assets.coingecko.com/hype.png')
        self.assertEqual(payload['provider'], 'CoinGecko')
        self.assertIn('hype,nope', mock_get.call_args.kwargs['params']['symbols'])
        self.assertEqual(mock_get.call_args.kwargs['params']['include_tokens'], 'all')

        # The second request is served from the persistent 30-day cache.
        second = self.client().get('/api/asset-icon/HYPE')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()['asset_id'], 'hyperliquid')
        self.assertEqual(mock_get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
