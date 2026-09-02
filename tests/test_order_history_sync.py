import unittest

from flask import Flask

from core.extensions import db
from credentials import User
from models import BinanceOrder, Coin, OrderHistorySyncState
from services.order_history_sync_service import _binance_symbols
from trading_models import RealOrder


class BinanceOrderHistorySymbolTests(unittest.TestCase):
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
        for model in (BinanceOrder, Coin, OrderHistorySyncState, RealOrder, User):
            db.session.query(model).delete()
        db.session.commit()

    def test_order_history_sync_keeps_only_live_tradable_spot_pairs(self):
        db.session.add_all([
            Coin(user_id=7, symbol='BTC'),
            Coin(user_id=7, symbol='ONG'),
            RealOrder(user_id=7, symbol='ETHUSD', side='BUY', type='LIMIT', quantity=1.0),
        ])
        db.session.commit()

        symbols = _binance_symbols(7, {
            'symbols': [
                {'symbol': 'BTCUSDT', 'status': 'TRADING', 'isSpotTradingAllowed': True},
                {'symbol': 'ETHUSD', 'status': 'TRADING', 'isSpotTradingAllowed': True},
                {'symbol': 'ONGUSDT', 'status': 'BREAK', 'isSpotTradingAllowed': True},
                {'symbol': 'BTCUSD', 'status': 'TRADING', 'isSpotTradingAllowed': False},
            ],
        })

        self.assertEqual(symbols, ['BTCUSDT', 'ETHUSD'])


if __name__ == '__main__':
    unittest.main()