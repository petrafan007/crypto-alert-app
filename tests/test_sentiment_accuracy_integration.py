import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask

from core.extensions import db
from credentials import User, UserSetting
from models import SentimentHistory
from services.sentiment_outcome_service import build_sentiment_accuracy_response


class SentimentAccuracyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
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
        db.session.query(SentimentHistory).delete()
        db.session.query(UserSetting).delete()
        db.session.query(User).delete()
        user = User(username='sentiment-test', pwd_hash='test')
        db.session.add(user)
        db.session.flush()
        self.user_id = user.id
        db.session.add(UserSetting(
            user_id=user.id,
            sentiment_buy_immediately_correct_pct=3,
            sentiment_buy_immediately_wrong_pct=1,
            sentiment_sell_immediately_correct_pct=3,
            sentiment_sell_immediately_wrong_pct=1,
        ))

        start = datetime.now(timezone.utc) - timedelta(hours=5)
        self.records = [
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Buy Immediately', price_at_prediction=100, created_at=start),
            SentimentHistory(user_id=user.id, symbol='ETH', source_type='portfolio', sentiment='Hold', price_at_prediction=200, created_at=start + timedelta(minutes=10)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='watchlist', sentiment='Watch', price_at_prediction=90, created_at=start + timedelta(minutes=20)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Sell Immediately', price_at_prediction=104, created_at=start + timedelta(hours=1)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Hold', price_at_prediction=100, created_at=start + timedelta(hours=2)),
        ]
        db.session.add_all(self.records)
        db.session.commit()

    def test_report_uses_next_same_coin_and_source_check(self):
        report = build_sentiment_accuracy_response(self.user_id, timeframe='all')
        history = {row['id']: row for row in report['history']}

        first = history[self.records[0].id]
        second = history[self.records[3].id]
        latest = history[self.records[4].id]

        self.assertEqual(first['evaluation_price'], 104)
        self.assertEqual(first['outcome_status'], 'correct')
        self.assertEqual(first['price_delta_pct'], 4)
        self.assertEqual(second['evaluation_price'], 100)
        self.assertEqual(second['outcome_status'], 'correct')
        self.assertEqual(latest['outcome_status'], 'tracking')
        self.assertIsNone(latest['evaluation_price'])
        self.assertEqual(first['evaluation_method'], 'next_sentiment_check')


if __name__ == '__main__':
    unittest.main()
