import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask

from core.extensions import db
from credentials import User, UserSetting
from models import ExternalSentimentSignal
from services.external_signal_service import create_external_signal, grade_external_signal


class ExternalSignalServiceTests(unittest.TestCase):
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
        db.session.query(UserSetting).delete()
        db.session.query(User).delete()
        user = User(username='external-signal-test', pwd_hash='test')
        db.session.add(user)
        db.session.flush()
        self.user = user
        db.session.add(UserSetting(
            user_id=user.id,
            sentiment_consider_buying_correct_pct=2.5,
            sentiment_consider_buying_wrong_pct=0,
        ))
        db.session.commit()

    def test_signal_freezes_rules_and_grades_with_connector_price(self):
        created = datetime.now(timezone.utc) - timedelta(hours=2)
        signal = create_external_signal(
            user_id=self.user.id, provider='webull', account_id='account-1',
            symbol='AAPL', instrument_type='STOCK', prompt_family='equity',
            recommendation='Consider Buying', reason='Test', market_context='Test market data',
            entry_price=100, currency='USD', forecast_horizon_hours=1, created_at=created,
        )
        self.assertEqual(signal.outcome_status, 'tracking')
        self.assertEqual(signal.target_evaluation_at, created.replace(tzinfo=None) + timedelta(hours=1))

        settings = UserSetting.query.filter_by(user_id=self.user.id).first()
        settings.sentiment_consider_buying_correct_pct = 50
        db.session.commit()
        grade_external_signal(signal, 103, created + timedelta(hours=1))
        db.session.commit()

        self.assertEqual(signal.outcome_status, 'correct')
        self.assertEqual(signal.outcome_pct, 3)
        self.assertEqual(signal.provider, 'webull')
        self.assertEqual(signal.prompt_family, 'equity')


if __name__ == '__main__':
    unittest.main()
