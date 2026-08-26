import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask

from core.extensions import db
from credentials import User, UserSetting
from models import SentimentHistory
from services.analysis_service import get_user_ai_settings
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
            sentiment_hold_steady_pct=1,
            sentiment_hold_wrong_pct=4,
        ))

        start = datetime.now(timezone.utc) - timedelta(hours=5)
        self.records = [
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Buy Immediately', price_at_prediction=100, created_at=start),
            SentimentHistory(user_id=user.id, symbol='ETH', source_type='portfolio', sentiment='Hold', price_at_prediction=200, created_at=start + timedelta(minutes=10)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='watchlist', sentiment='Watch', price_at_prediction=90, created_at=start + timedelta(minutes=20)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Sell Immediately', price_at_prediction=104, created_at=start + timedelta(hours=1)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Hold', price_at_prediction=100, created_at=start + timedelta(hours=2)),
            SentimentHistory(user_id=user.id, symbol='BTC', source_type='portfolio', sentiment='Consider Buying', price_at_prediction=105, created_at=start + timedelta(hours=3)),
        ]
        db.session.add_all(self.records)
        db.session.commit()

    def test_report_uses_next_same_coin_and_source_check(self):
        report = build_sentiment_accuracy_response(self.user_id, timeframe='all')
        history = {row['id']: row for row in report['history']}

        first = history[self.records[0].id]
        second = history[self.records[3].id]
        hold = history[self.records[4].id]
        latest = history[self.records[5].id]
        expected_eval_time = self.records[3].created_at
        if expected_eval_time.tzinfo is None:
            expected_eval_time = expected_eval_time.replace(tzinfo=timezone.utc)

        self.assertEqual(first['evaluation_price'], 104)
        self.assertEqual(first['evaluated_at'], self.records[3].created_at.isoformat())
        self.assertEqual(first['evaluated_timestamp'], int(expected_eval_time.timestamp()))
        self.assertEqual(first['outcome_status'], 'correct')
        self.assertEqual(first['price_delta_pct'], 4)
        self.assertEqual(second['evaluation_price'], 100)
        self.assertEqual(second['outcome_status'], 'correct')
        self.assertEqual(hold['evaluation_price'], 105)
        self.assertEqual(hold['outcome_status'], 'wrong')
        self.assertEqual(hold['steady_threshold_pct'], 1)
        self.assertEqual(hold['upside_wrong_threshold_pct'], 4)
        self.assertEqual(hold['downside_wrong_threshold_pct'], 4)
        self.assertEqual(latest['outcome_status'], 'tracking')
        self.assertIsNone(latest['evaluation_price'])
        self.assertIsNone(latest['evaluated_timestamp'])
        self.assertEqual(first['evaluation_method'], 'next_sentiment_check')
        self.assertEqual(report['summary']['evaluated_signals'], 3)
        self.assertEqual(report['summary']['bullish_count'], 1)
        self.assertEqual(report['summary']['bearish_count'], 1)
        self.assertEqual(report['summary']['overall_accuracy'], 66.7)
        self.assertEqual(report['summary']['bullish_win_rate'], 100.0)
        self.assertEqual(report['summary']['bearish_win_rate'], 100.0)
        self.assertEqual(report['summary']['correct_count'], 2)
        self.assertEqual(report['summary']['wrong_count'], 1)
        self.assertEqual(report['summary']['bullish_correct_count'], 1)
        self.assertEqual(report['summary']['bullish_wrong_count'], 0)
        self.assertEqual(report['summary']['bearish_correct_count'], 1)
        self.assertEqual(report['summary']['bearish_wrong_count'], 0)
        self.assertEqual(report['model_breakdown'][0]['win_rate'], 66.7)

    def test_zero_directional_rates_are_reported_when_all_decisive_calls_are_wrong(self):
        db.session.query(SentimentHistory).delete(synchronize_session=False)
        db.session.commit()
        db.session.expunge_all()
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        records = [
            SentimentHistory(user_id=self.user_id, symbol='BTC', source_type='portfolio', sentiment='Buy Immediately', price_at_prediction=100, created_at=start),
            SentimentHistory(user_id=self.user_id, symbol='BTC', source_type='portfolio', sentiment='Hold', price_at_prediction=99, created_at=start + timedelta(hours=1)),
            SentimentHistory(user_id=self.user_id, symbol='ETH', source_type='portfolio', sentiment='Sell Immediately', price_at_prediction=100, created_at=start),
            SentimentHistory(user_id=self.user_id, symbol='ETH', source_type='portfolio', sentiment='Hold', price_at_prediction=101, created_at=start + timedelta(hours=1)),
            SentimentHistory(user_id=self.user_id, symbol='SOL', source_type='portfolio', sentiment='Hold', price_at_prediction=100, created_at=start),
            SentimentHistory(user_id=self.user_id, symbol='SOL', source_type='portfolio', sentiment='Hold', price_at_prediction=100.5, created_at=start + timedelta(hours=1)),
        ]
        db.session.add_all(records)
        db.session.commit()

        summary = build_sentiment_accuracy_response(self.user_id, timeframe='all')['summary']
        self.assertEqual(summary['correct_count'], 1)
        self.assertEqual(summary['wrong_count'], 2)
        self.assertEqual(summary['overall_accuracy'], 33.3)
        self.assertEqual(summary['bullish_correct_count'], 0)
        self.assertEqual(summary['bullish_wrong_count'], 1)
        self.assertEqual(summary['bullish_win_rate'], 0.0)
        self.assertEqual(summary['bearish_correct_count'], 0)
        self.assertEqual(summary['bearish_wrong_count'], 1)
        self.assertEqual(summary['bearish_win_rate'], 0.0)

    def test_sentiment_chart_range_is_persisted_with_a_safe_default(self):
        settings = UserSetting.query.filter_by(user_id=self.user_id).first()
        self.assertEqual(get_user_ai_settings('sentiment-test')['sentiment_chart_default_range'], '3d')

        settings.sentiment_chart_default_range = '90d'
        db.session.commit()
        self.assertEqual(get_user_ai_settings('sentiment-test')['sentiment_chart_default_range'], '90d')

        settings.sentiment_chart_default_range = 'invalid'
        db.session.commit()
        self.assertEqual(get_user_ai_settings('sentiment-test')['sentiment_chart_default_range'], '3d')


if __name__ == '__main__':
    unittest.main()
