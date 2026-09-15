import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from flask import Flask, session

import routes.system as system
from models import WebullScheduledOrder
from services.webull_scheduled_order_service import (
    create_scheduled_fractional_order,
    cancel_scheduled_fractional_order,
    get_user_scheduled_orders,
    process_due_scheduled_orders,
    DEFAULT_PRICE_CEILING_BUFFER,
)
from services.market_calendar_service import (
    get_next_regular_market_open,
    is_regular_market_hours,
    is_trading_day,
)


class _Query:
    def __init__(self, value):
        self.value = value

    def filter_by(self, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        if isinstance(self.value, list):
            return self.value
        return [self.value] if self.value is not None else []

    def first(self):
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value

    def get(self, _id):
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value


class WebullScheduledOrdersTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret'

    def test_market_calendar_next_open_calculation(self):
        """Test calculating the next NYSE 9:30 AM ET market open."""
        # On a Friday at 8:00 PM ET (Saturday 00:00 UTC), next open should be Monday 9:30 AM ET
        friday_night = datetime(2026, 9, 18, 20, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
        target_utc, target_et, target_date_str = get_next_regular_market_open(friday_night)
        self.assertEqual(target_date_str, '2026-09-21')  # Monday
        self.assertEqual(target_et.hour, 9)
        self.assertEqual(target_et.minute, 30)

        # On Monday at 8:00 AM ET, next open should be today Monday at 9:30 AM ET
        monday_pre = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
        target_utc, target_et, target_date_str = get_next_regular_market_open(monday_pre)
        self.assertEqual(target_date_str, '2026-09-21')
        self.assertEqual(target_et.hour, 9)
        self.assertEqual(target_et.minute, 30)

    @patch('services.webull_scheduled_order_service.db.session')
    @patch('services.webull_scheduled_order_service.create_system_notification')
    def test_create_scheduled_fractional_order_defaults_3pct_ceiling(self, mock_notify, mock_db_session):
        """Verify default +3% price ceiling is automatically applied when not specified."""
        order_dict = create_scheduled_fractional_order(
            user_id=1,
            account_id='acc-123',
            symbol='TSLA',
            quantity=0.5,
            reference_price=300.00,
        )
        self.assertEqual(order_dict['symbol'], 'TSLA')
        self.assertEqual(order_dict['quantity'], 0.5)
        self.assertEqual(order_dict['reference_price'], 300.00)
        # 300.00 * 1.03 = 309.00
        self.assertEqual(order_dict['max_price'], 309.00)
        self.assertEqual(order_dict['status'], 'PENDING')
        self.assertTrue(mock_db_session.add.called)
        self.assertTrue(mock_db_session.commit.called)

    @patch('services.webull_scheduled_order_service.db.session')
    def test_create_scheduled_order_validation(self, mock_db_session):
        """Test rejection of invalid quantities and amounts."""
        # Negative quantity
        with self.assertRaises(ValueError):
            create_scheduled_fractional_order(user_id=1, account_id='acc-1', symbol='AAPL', quantity=-1)

        # More than 5 decimals
        with self.assertRaises(ValueError):
            create_scheduled_fractional_order(user_id=1, account_id='acc-1', symbol='AAPL', quantity=0.123456)

        # Cash amount under $5.00
        with self.assertRaises(ValueError):
            create_scheduled_fractional_order(
                user_id=1, account_id='acc-1', symbol='AAPL', entrust_type='AMOUNT', total_cash_amount=4.50
            )

    @patch('services.webull_scheduled_order_service.WebullScheduledOrder.query')
    @patch('services.webull_scheduled_order_service.db.session')
    def test_cancel_scheduled_fractional_order(self, mock_db_session, mock_query):
        """Test canceling a pending scheduled order."""
        fake_order = WebullScheduledOrder(
            id=42, user_id=1, account_id='acc-1', symbol='NVDA', status='PENDING', quantity=0.25
        )
        mock_query.filter_by.return_value.first.return_value = fake_order

        res = cancel_scheduled_fractional_order(user_id=1, order_id=42)
        self.assertEqual(fake_order.status, 'CANCELLED')
        self.assertEqual(res['status'], 'CANCELLED')
        self.assertTrue(mock_db_session.commit.called)

    @patch('services.webull_scheduled_order_service.is_regular_market_hours', return_value=True)
    @patch('services.webull_scheduled_order_service.get_webull_market_snapshot')
    @patch('services.webull_scheduled_order_service.place_webull_order')
    @patch('services.webull_scheduled_order_service.User.query')
    @patch('services.webull_scheduled_order_service.UserSetting.query')
    @patch('services.webull_scheduled_order_service.Credential.query')
    @patch('services.webull_scheduled_order_service.WebullScheduledOrder.query')
    @patch('services.webull_scheduled_order_service.db.session')
    def test_process_due_scheduled_orders_skips_when_ceiling_breached(
        self, mock_db, mock_order_query, mock_cred_query, mock_sett_query, mock_user_query,
        mock_place, mock_snapshot, mock_is_open
    ):
        """If open price exceeds ceiling, order must abort safely as SKIPPED_PRICE_LIMIT."""
        order = WebullScheduledOrder(
            id=10,
            user_id=1,
            account_id='acc-1',
            symbol='TSLA',
            quantity=0.5,
            entrust_type='QTY',
            reference_price=350.00,
            max_price=360.00,  # Ceiling is $360.00
            target_execution_time=datetime.utcnow() - timedelta(seconds=10),
            status='PENDING',
        )
        mock_order_query.filter.return_value.order_by.return_value.all.return_value = [order]
        mock_user_query.get.return_value = SimpleNamespace(id=1, username='testuser', telegram_chat_id=None)
        mock_sett_query.filter_by.return_value.first.return_value = SimpleNamespace(webull_environment='production')
        mock_cred_query.filter_by.return_value.first.return_value = SimpleNamespace(
            webull_app_key='k', webull_app_secret='s', webull_access_token='t',
            webull_token_status='NORMAL', webull_token_environment='production',
        )
        # Snapshot returns price $365.00 (> ceiling $360.00)
        mock_snapshot.return_value = {'symbol': 'TSLA', 'price': 365.00}

        results = process_due_scheduled_orders()
        self.assertEqual(len(results), 1)
        self.assertEqual(order.status, 'SKIPPED_PRICE_LIMIT')
        self.assertIn('exceeded cutoff ceiling', order.execution_error)
        self.assertFalse(mock_place.called)  # Did not buy!

    @patch('services.webull_scheduled_order_service.is_regular_market_hours', return_value=True)
    @patch('services.webull_scheduled_order_service.get_webull_market_snapshot')
    @patch('services.webull_scheduled_order_service.place_webull_order')
    @patch('services.webull_scheduled_order_service.User.query')
    @patch('services.webull_scheduled_order_service.UserSetting.query')
    @patch('services.webull_scheduled_order_service.Credential.query')
    @patch('services.webull_scheduled_order_service.WebullScheduledOrder.query')
    @patch('services.webull_scheduled_order_service.db.session')
    def test_process_due_scheduled_orders_executes_within_ceiling(
        self, mock_db, mock_order_query, mock_cred_query, mock_sett_query, mock_user_query,
        mock_place, mock_snapshot, mock_is_open
    ):
        """If open price is below or equal to ceiling, order executes as a CORE Market order."""
        order = WebullScheduledOrder(
            id=11,
            user_id=1,
            account_id='acc-1',
            symbol='TSLA',
            quantity=0.5,
            entrust_type='QTY',
            reference_price=350.00,
            max_price=360.00,
            target_execution_time=datetime.utcnow() - timedelta(seconds=10),
            status='PENDING',
        )
        mock_order_query.filter.return_value.order_by.return_value.all.return_value = [order]
        mock_user_query.get.return_value = SimpleNamespace(id=1, username='testuser', telegram_chat_id=None)
        mock_sett_query.filter_by.return_value.first.return_value = SimpleNamespace(webull_environment='production')
        mock_cred_query.filter_by.return_value.first.return_value = SimpleNamespace(
            webull_app_key='k', webull_app_secret='s', webull_access_token='t',
            webull_token_status='NORMAL', webull_token_environment='production',
        )
        # Snapshot returns price $355.00 (within ceiling)
        mock_snapshot.return_value = {'symbol': 'TSLA', 'price': 355.00}
        mock_place.return_value = {'order_id': 'wb-fill-999'}

        results = process_due_scheduled_orders()
        self.assertEqual(len(results), 1)
        self.assertEqual(order.status, 'EXECUTED')
        self.assertEqual(order.provider_order_id, 'wb-fill-999')
        self.assertTrue(mock_place.called)
        # Verify it was placed with support_trading_session='CORE'
        _, kwargs = mock_place.call_args
        self.assertEqual(kwargs.get('support_trading_session'), 'CORE')
        self.assertEqual(kwargs.get('order_type'), 'MARKET')

    @patch('services.webull_scheduled_order_service.is_regular_market_hours', return_value=True)
    @patch('services.webull_scheduled_order_service.get_webull_market_snapshot')
    @patch('services.webull_scheduled_order_service.place_webull_order')
    @patch('services.webull_scheduled_order_service.User.query')
    @patch('services.webull_scheduled_order_service.UserSetting.query')
    @patch('services.webull_scheduled_order_service.Credential.query')
    @patch('services.webull_scheduled_order_service.WebullScheduledOrder.query')
    @patch('services.webull_scheduled_order_service.db.session')
    def test_process_due_scheduled_orders_applies_default_3_pct_buffer_when_max_price_omitted(
        self, mock_db, mock_order_query, mock_cred_query, mock_sett_query, mock_user_query,
        mock_place, mock_snapshot, mock_is_open
    ):
        """When max_price is not provided, service defaults to +3% above reference_price ($100 -> $103.00), allowing $100.01 to execute."""
        order = WebullScheduledOrder(
            id=12,
            user_id=1,
            account_id='acc-1',
            symbol='TSLA',
            total_cash_amount=100.00,
            entrust_type='AMOUNT',
            reference_price=100.00,
            max_price=None,  # No explicit max_price, should default to $103.00 (+3%)
            target_execution_time=datetime.utcnow() - timedelta(seconds=10),
            status='PENDING',
        )
        mock_order_query.filter.return_value.order_by.return_value.all.return_value = [order]
        mock_user_query.get.return_value = SimpleNamespace(id=1, username='testuser', telegram_chat_id=None)
        mock_sett_query.filter_by.return_value.first.return_value = SimpleNamespace(webull_environment='production')
        mock_cred_query.filter_by.return_value.first.return_value = SimpleNamespace(
            webull_app_key='k', webull_app_secret='s', webull_access_token='t',
            webull_token_status='NORMAL', webull_token_environment='production',
        )
        # Snapshot returns price $100.01 (minor price increase within +3% buffer ceiling)
        mock_snapshot.return_value = {'symbol': 'TSLA', 'price': 100.01}
        mock_place.return_value = {'order_id': 'wb-fill-10001'}

        results = process_due_scheduled_orders()
        self.assertEqual(len(results), 1)
        self.assertEqual(order.status, 'EXECUTED')
        self.assertEqual(order.provider_order_id, 'wb-fill-10001')
        self.assertTrue(mock_place.called)

    def test_endpoints_2fa_enforcement(self):
        """Verify POST /api/webull/scheduled-orders enforces 2FA when require_2fa is enabled."""
        with self.app.test_request_context(
            '/api/webull/scheduled-orders',
            method='POST',
            json={'account_id': 'acc-1', 'symbol': 'TSLA', 'quantity': 0.5},
        ):
            with patch.object(system, 'current_user', SimpleNamespace(id=1)), \
                 patch.object(system.UserSetting, 'query', _Query(SimpleNamespace())), \
                 patch('trading_models.TradingSettings.query', _Query(SimpleNamespace(require_2fa=True, totp_secret='secret'))), \
                 patch.object(system, '_require_webull_account_access', return_value='acc-1'):
                response, status_code = system.api_webull_create_scheduled_order.__wrapped__()
                self.assertEqual(status_code, 403)
                self.assertTrue(response.json.get('requires_2fa'))


if __name__ == '__main__':
    unittest.main()
