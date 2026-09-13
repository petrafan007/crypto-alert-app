"""Refresh must not queue on a paper account while providers are contacted."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from flask import Flask
from sqlalchemy.schema import CreateSchema
from core.extensions import db
from models import WebullTestAccount, WebullTestOrder, WebullTestPosition
from services import webull_paper_lifecycle as lifecycle
from services.webull_paper_trading_service import _lock_webull_test_account


class PaperRefreshTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_RISK_TEST_DATABASE_URI', 'sqlite://')
        schema = 'refresh_test_' + uuid4().hex
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'options': '-csearch_path=' + schema}}
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine, tables=[m.__table__ for m in
            (WebullTestAccount, WebullTestOrder, WebullTestPosition)])
        db.session.add(WebullTestAccount(user_id=1, cash_balance=100))
        self.order = WebullTestOrder(user_id=1, order_id='test', symbol='KXBTC-TEST YES',
            instrument_type='EVENT', side='BUY', order_type='LIMIT', quantity=2,
            limit_price=.5, status='Working', time_in_force='GTC')
        db.session.add(self.order)
        db.session.commit()
        self.order_id = self.order.id
        self.now = datetime(2026, 9, 12, 20, tzinfo=timezone.utc)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        lifecycle._RECONCILE_EVENTS_LAST_RUN.clear()

    def test_fetch_precedes_lock_and_concurrent_cancel_is_reloaded(self):
        def quote(*args, **kwargs):
            # A separate request can acquire the account during provider work.
            with self.app.app_context():
                try:
                    self.assertIsNotNone(_lock_webull_test_account(1, wait=False))
                    db.session.get(WebullTestOrder, self.order_id).status = 'Cancelled'
                    db.session.commit()
                finally:
                    db.session.remove()
            return {'yes_ask': .4, 'yes_bid': .39}
        with patch('services.webull_paper_trading_service.fetch_event_market_quote', side_effect=quote):
            lifecycle.reconcile_paper_events(1, now=self.now, force=True)
        self.assertEqual(db.session.get(WebullTestOrder, self.order_id).status, 'Cancelled')
        self.assertEqual(WebullTestAccount.query.one().cash_balance, 100)
        self.assertEqual(WebullTestPosition.query.count(), 0)

    def test_overlapping_forced_refresh_is_coalesced_and_fill_still_works(self):
        def quote(*args, **kwargs):
            lifecycle.reconcile_paper_events(1, now=self.now, force=True)
            return {'yes_ask': .4, 'yes_bid': .39}
        with patch('services.webull_paper_trading_service.fetch_event_market_quote', side_effect=quote) as fetch:
            lifecycle.reconcile_paper_events(1, now=self.now, force=True)
        fetch.assert_called_once()
        self.assertEqual(WebullTestOrder.query.one().status, 'Filled')
        self.assertAlmostEqual(WebullTestAccount.query.one().cash_balance, 99.16)
        self.assertEqual(WebullTestPosition.query.one().quantity, 2)

    @unittest.skipUnless(os.environ.get('QUANT_RISK_TEST_DATABASE_URI', '').startswith('postgresql'),
                         'Requires isolated PostgreSQL for row-lock semantics')
    def test_busy_account_is_skipped_without_waiting(self):
        _lock_webull_test_account(1)
        with self.app.app_context():
            try:
                with patch('services.webull_paper_trading_service.fetch_event_market_quote',
                           return_value={'yes_ask': .4, 'yes_bid': .39}):
                    lifecycle.reconcile_paper_events(1, now=self.now, force=True)
                self.assertEqual(WebullTestOrder.query.one().status, 'Working')
            finally:
                db.session.remove()
        db.session.rollback()
