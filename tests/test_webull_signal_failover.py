import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask

from core.extensions import db
from credentials import User, UserSetting, Credential
from models import ExternalSentimentSignal, WebullHolding
from services.webull_signal_service import create_webull_signal


class WebullSignalFailoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
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
        db.session.query(ExternalSentimentSignal).delete()
        db.session.query(WebullHolding).delete()
        db.session.query(UserSetting).delete()
        db.session.query(User).delete()
        user = User(username='webull-failover-user', pwd_hash='test')
        db.session.add(user)
        db.session.flush()
        self.user = user
        db.session.add(UserSetting(user_id=user.id))
        holding = WebullHolding(
            user_id=user.id,
            account_id='acc-1',
            symbol='AAPL',
            instrument_type='STOCK',
            quantity=10,
            current_value=2500,
            cost_price=200,
            last_price=250,
        )
        db.session.add(holding)
        db.session.commit()
        self.holding = holding

    @patch('services.webull_signal_service.is_ai_enabled', return_value=True)
    @patch('services.webull_signal_service._credentials_for_user')
    @patch('services.webull_signal_service.get_webull_market_bars', return_value=[])
    @patch('services.webull_signal_service.get_webull_market_snapshot', return_value={'price': 250.0})
    @patch('services.webull_signal_service.build_webull_market_snapshot')
    @patch('services.webull_signal_service.call_ai_with_web_search')
    def test_create_webull_signal_serializes_failover_history(self, mock_call_ai, mock_snapshot, mock_get_snap, mock_bars, mock_creds, *args):
        mock_creds.return_value = (
            SimpleNamespace(webull_app_key='k', webull_app_secret='s', webull_access_token='t'),
            UserSetting.query.filter_by(user_id=self.user.id).first(),
            'production'
        )
        mock_snapshot.return_value = {
            'context': 'AAPL snapshot test',
            'last_price': 250.0,
            'summary': {'last_price': 250.0},
        }
        
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"sentiment": "Consider Buying", "reason": "Solid earnings"})
                    )
                )
            ],
            provider='zai',
            model='glm-4.7-flash',
            tier='secondary',
            search_status='completed',
            failover_history=[
                {'tier': 'primary', 'provider': 'gemini', 'error': '429 rate limit'},
                {'tier': 'secondary', 'provider': 'zai', 'status': 'success'}
            ]
        )
        mock_call_ai.return_value = (fake_response, None)

        signal, market = create_webull_signal(self.user, self.holding, origin='manual')
        self.assertIsNotNone(signal)
        self.assertEqual(signal.recommendation, 'Consider Buying')
        self.assertEqual(signal.ai_provider, 'zai')
        self.assertIsNotNone(signal.failover_history)
        history = json.loads(signal.failover_history)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['error'], '429 rate limit')


if __name__ == '__main__':
    unittest.main()
