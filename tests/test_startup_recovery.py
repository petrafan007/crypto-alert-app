import unittest
from flask import Flask
from core.extensions import db
from database import _recover_startup_state
from models import Coin, WatchlistCoin, StakedCoin
from trading_models import AllActivity


class StartupRecoveryTests(unittest.TestCase):
    def test_recovers_both_sentiment_tables_and_preserves_unknown_cost(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        db.init_app(app)
        with app.app_context():
            try:
                for model in (Coin, WatchlistCoin, StakedCoin, AllActivity):
                    model.__table__.create(db.engine)
                db.session.add(Coin(user_id=1, symbol='GRAM', amount=10, avg_entry=0, sentiment='Checking now...'))
                db.session.add(WatchlistCoin(user_id=1, symbol='BTC', sentiment='Checking now...'))
                db.session.add(WatchlistCoin(user_id=1, symbol='ETH', sentiment='Buy', sentiment_reason='Keep existing assessment'))
                db.session.commit()
                with db.engine.begin() as connection:
                    _recover_startup_state(connection)
                db.session.expire_all()
                coin = Coin.query.one()
                watch = WatchlistCoin.query.filter_by(symbol='BTC').one()
                unchanged = WatchlistCoin.query.filter_by(symbol='ETH').one()
                self.assertEqual(coin.sentiment, 'Hold')
                self.assertEqual(watch.sentiment, 'Watch')
                self.assertIsNotNone(coin.sentiment_last_updated)
                self.assertIsNotNone(watch.sentiment_last_updated)
                self.assertEqual(coin.avg_entry, 0)
                self.assertEqual(unchanged.sentiment, 'Buy')
                self.assertEqual(unchanged.sentiment_reason, 'Keep existing assessment')
            finally:
                db.session.remove()
                db.engine.dispose()
