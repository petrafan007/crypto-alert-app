import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from models import WebullAccountSnapshot, WebullActivity, WebullHistoricalOrder
from services.webull_sync_service import _sync_account_activities, _sync_account_orders


class WebullSyncServiceTests(unittest.TestCase):
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
        WebullHistoricalOrder.query.delete()
        WebullActivity.query.delete()
        WebullAccountSnapshot.query.delete()
        db.session.commit()

    def test_account_activity_sync_is_idempotent_and_checkpoints_environment(self):
        now = datetime(2026, 8, 31, 12, 0, 0)
        snapshot = WebullAccountSnapshot(
            user_id=1,
            account_id='account-1',
            environment='production',
            activity_synced_at=now - timedelta(days=1),
            activity_sync_environment='production',
        )
        db.session.add(snapshot)
        db.session.commit()
        credential = SimpleNamespace(
            webull_app_key='key', webull_app_secret='secret', webull_access_token='token',
        )
        first_payload = [{
            'id': 'activity-1', 'account_id': 'account-1',
            'activity_type': 'TRANSFER', 'activity_sub_type': 'INTERNAL_TRANSFER',
            'currency': 'USD', 'market': 'US', 'net_amount': '5.00',
            'biz_time': '2026-08-31T03:02:41.000Z',
        }]
        with patch('services.webull_sync_service.get_webull_cash_activities', return_value=first_payload):
            _sync_account_activities(
                user_id=1, environment='production', account_id='account-1',
                credential=credential, snapshot=snapshot, now=now,
            )
            db.session.commit()

        self.assertEqual(WebullActivity.query.count(), 1)
        row = WebullActivity.query.one()
        self.assertEqual(row.net_amount, 5.0)
        self.assertEqual(row.activity_sub_type, 'INTERNAL_TRANSFER')
        self.assertEqual(snapshot.activity_sync_environment, 'production')
        self.assertEqual(snapshot.activity_synced_at, now)

        second_payload = [{**first_payload[0], 'net_amount': '7.25'}]
        with patch('services.webull_sync_service.get_webull_cash_activities', return_value=second_payload):
            _sync_account_activities(
                user_id=1, environment='production', account_id='account-1',
                credential=credential, snapshot=snapshot, now=now + timedelta(minutes=1),
            )
            db.session.commit()

        self.assertEqual(WebullActivity.query.count(), 1)
        self.assertEqual(WebullActivity.query.one().net_amount, 7.25)

    def test_historical_order_sync_is_idempotent_and_updates_status(self):
        now = datetime(2026, 8, 31, 12, 0, 0)
        credential = SimpleNamespace(
            webull_app_key='key', webull_app_secret='secret', webull_access_token='token',
        )
        first_payload = [{
            'order_id': 'provider-order-1', 'client_order_id': 'client-order-1',
            'symbol': 'AAPL', 'side': 'BUY', 'order_type': 'LIMIT',
            'total_quantity': '2', 'limit_price': '205.50',
            'filled_quantity': '0', 'status': 'WORKING',
            'create_time': '2026-08-31T04:00:00.000Z',
        }]
        with patch('services.webull_sync_service.get_webull_order_history', return_value=first_payload) as history_mock:
            _sync_account_orders(
                user_id=1, environment='production', account_id='account-1',
                credential=credential, now=now,
            )
            db.session.commit()

        history_mock.assert_called_once_with(
            'key', 'secret', 'production', 'token', page_size=100, account_id='account-1',
        )
        self.assertEqual(WebullHistoricalOrder.query.count(), 1)
        row = WebullHistoricalOrder.query.one()
        self.assertEqual(row.status, 'WORKING')
        self.assertEqual(row.quantity, 2.0)
        self.assertEqual(row.price, 205.5)

        second_payload = [{
            **first_payload[0], 'filled_quantity': '2',
            'average_filled_price': '205.25', 'status': 'FILLED',
            'update_time': '2026-08-31T04:05:00.000Z',
        }]
        with patch('services.webull_sync_service.get_webull_order_history', return_value=second_payload):
            _sync_account_orders(
                user_id=1, environment='production', account_id='account-1',
                credential=credential, now=now + timedelta(minutes=5),
            )
            db.session.commit()

        self.assertEqual(WebullHistoricalOrder.query.count(), 1)
        row = WebullHistoricalOrder.query.one()
        self.assertEqual(row.status, 'FILLED')
        self.assertEqual(row.filled_quantity, 2.0)
        self.assertEqual(row.filled_price, 205.25)


if __name__ == '__main__':
    unittest.main()
