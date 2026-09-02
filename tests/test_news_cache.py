import unittest
from datetime import datetime

from flask import Flask

from core.extensions import db
from models import AIConversation, Coin
from routes.helpers import get_user_latest_news_cache


class NewsCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
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
        db.session.query(AIConversation).delete()
        db.session.query(Coin).delete()
        db.session.commit()

    def test_news_cache_resolves_symbol_from_coin_id(self):
        coin = Coin(user_id=7, symbol='BTC')
        db.session.add(coin)
        db.session.flush()
        db.session.add_all([
            AIConversation(
                user_id=7,
                date=datetime(2026, 9, 1).date(),
                time='10:00 AM',
                prompt_type='coin_analysis',
                sender='ai',
                body='Older analysis',
                coin_id=coin.id,
                created_at=datetime(2026, 9, 1, 10, 0),
            ),
            AIConversation(
                user_id=7,
                date=datetime(2026, 9, 2).date(),
                time='10:00 AM',
                prompt_type='coin_analysis',
                sender='ai',
                body='Latest analysis',
                coin_id=coin.id,
                created_at=datetime(2026, 9, 2, 10, 0),
            ),
        ])
        db.session.commit()

        cache = get_user_latest_news_cache(7)

        self.assertEqual(cache[coin.id]['text'], 'Latest analysis')
        self.assertEqual(cache['BTC']['text'], 'Latest analysis')


if __name__ == '__main__':
    unittest.main()