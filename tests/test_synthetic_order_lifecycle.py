"""Regression coverage for the real synthetic lifecycle, with isolated paper ledgers.

All venue I/O is mocked. These tests never connect to a broker or the app database.
"""
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch, Mock
from flask import Flask
from core.extensions import db
from credentials import User, Credential, UserSetting
from models import WebullTestAccount, WebullTestPosition, WebullTestOrder
from trading_models import (LadderOrder, LadderRung, TrailingOrder, SyntheticExecution,
                            TestOrder, TestPortfolio, TradingSettings)
from services import synthetic_execution_service as ex
from services import ladder_order_service as ladder
from services import trailing_order_service as trailing


class SyntheticLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SECRET_KEY='synthetic-tests', TESTING=True)
        db.init_app(self.app)
        self.ctx = self.app.app_context(); self.ctx.push()
        tables = [User, Credential, UserSetting, TradingSettings, TestOrder, TestPortfolio,
                  LadderOrder, LadderRung, TrailingOrder, SyntheticExecution,
                  WebullTestAccount, WebullTestPosition, WebullTestOrder]
        for model in tables:
            model.__table__.create(db.engine, checkfirst=True)
        db.session.add(TradingSettings(user_id=1, test_mode_enabled=False, max_order_size_usd=0))
        db.session.add(UserSetting(user_id=1, webull_environment='production', webull_test_mode_enabled=True))
        db.session.add(TestPortfolio(user_id=1, symbol='BTC', quantity=100, avg_entry_price=100, total_cost_basis=10000))
        db.session.add(TestPortfolio(user_id=1, symbol='USD', quantity=100000, total_cost_basis=100000))
        db.session.commit()
        self.rules = {'step': Decimal('0.00001'), 'base': 'BTC', 'quote': 'USD'}
        self.patchers = [patch.object(ex, 'quantity_rules', return_value=self.rules),
                         patch.object(ladder, '_get_reference_price', return_value=100),
                         patch.object(trailing, '_get_reference_price', return_value=100),
                         patch.object(ex, 'binance_client'),
                         patch('services.webull_service.place_webull_order')]
        self.mocks = [p.start() for p in self.patchers]
        self.client = self.mocks[3].return_value
        self.client.get_asset_balance.return_value = {'free': '1000000'}
        self.webull_submit = self.mocks[4]
        self.client.create_order.side_effect = AssertionError('Unexpected live submission')
        self.webull_submit.side_effect = AssertionError('Unexpected live Webull submission')

    def tearDown(self):
        for p in reversed(self.patchers): p.stop()
        db.session.remove(); db.engine.dispose(); self.ctx.pop()

    def create(self, **kwargs):
        args = dict(user_id=1, symbol='BTCUSD', side='SELL', total_quantity=10, test_mode=True,
                    upside_mode='LADDER', downside_mode='NONE')
        args.update(kwargs)
        result = ladder.create_ladder_order(**args)
        return db.session.get(LadderOrder, result['id'])

    def tick(self, parent, price):
        ladder.evaluate_single_ladder_order(parent, price)
        db.session.commit()
        return parent.to_dict()

    def test_every_side_and_mode_combination_stays_within_parent_quantity(self):
        for side in ('BUY', 'SELL'):
            for up in ('SINGLE', 'LADDER', 'TRAILING'):
                for down in ('SINGLE', 'LADDER', 'TRAILING'):
                    with self.subTest(side=side, upside=up, downside=down):
                        parent = self.create(side=side, upside_mode=up, downside_mode=down,
                            upside_target_price=110 if side == 'SELL' else 90,
                            downside_target_price=90 if side == 'SELL' else 110,
                            upside_trail_value=5, downside_trail_value=3)
                        for price in ([104, 108, 120, 90, 80] if side == 'SELL' else [96, 92, 80, 110, 120]):
                            self.tick(parent, price)
                        rows = ex.executions(parent, 'LADDER')
                        self.assertAlmostEqual(sum(r.filled_quantity for r in rows), 10, places=8)
                        self.assertIn(parent.status, {'COMPLETED', 'STOPPED_OUT'})
        self.client.create_order.assert_not_called(); self.webull_submit.assert_not_called()

    def test_tiny_prices_preserve_trigger_distance(self):
        rungs = ladder.calculate_ladder_rungs('SELL', 0.00000012, 100000000)
        self.assertAlmostEqual(rungs[0]['target_price'] / 0.00000012, 1.02)
        self.assertAlmostEqual(trailing.calculate_trailing_stop_price('SELL', 0.00000012, 'PERCENT', 2) / 0.00000012, .98)

    def test_impossible_sell_trail_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'below the price'):
            self.create(upside_mode='TRAILING', upside_trail_type='AMOUNT', upside_trail_value=100)
        with self.assertRaisesRegex(ValueError, 'below the price'):
            trailing.create_trailing_order(1, 'BTCUSD', 'SELL', 10, trail_type='AMOUNT', trail_value=100, test_mode=True)

    def test_legacy_completed_totals_are_explicitly_unverified(self):
        parent = self.create()
        parent.engine_version = None
        parent.status = 'COMPLETED'
        db.session.commit()
        result = parent.to_dict()
        self.assertFalse(result['execution_history_verified'])
        self.assertIsNone(result['filled_quantity'])
        self.assertIsNone(result['remaining_quantity'])

    def test_restart_reconciles_trailing_intent_committed_before_acknowledgement(self):
        result = trailing.create_trailing_order(1, 'BTCUSD', 'SELL', 1, test_mode=False)
        parent = db.session.get(TrailingOrder, result['id'])
        parent.status = 'TRIGGERED'
        db.session.add(SyntheticExecution(user_id=1, parent_kind='TRAILING', parent_id=parent.id,
            leg='TRAILING', quantity=1, client_order_id='restart-intent', filled_quantity=0, status='SUBMITTING'))
        db.session.commit()
        identifier = parent.id
        db.session.remove()
        self.client.get_order.return_value = {'status': 'FILLED', 'executedQty': '1', 'cummulativeQuoteQty': '97', 'orderId': 71}
        trailing.evaluate_active_trailing_orders()
        parent = db.session.get(TrailingOrder, identifier)
        self.assertEqual(parent.status, 'FILLED')
        self.assertEqual(parent.to_dict()['filled_quantity'], 1)
        self.client.create_order.assert_not_called()

    def test_trailing_profit_executes_whole_remainder_after_partial_stop(self):
        parent = self.create(upside_mode='TRAILING', upside_trail_value=5, upside_activation_price=120,
            downside_mode='LADDER', downside_rungs=[{'offset_pct': -5, 'pct_of_total': 30}, {'offset_pct': -15, 'pct_of_total': 70}])
        self.tick(parent, 94)
        self.assertAlmostEqual(parent.to_dict()['filled_quantity'], 3)
        self.tick(parent, 125); self.tick(parent, 118)
        self.assertEqual([r.quantity for r in ex.executions(parent, 'LADDER')], [3, 7])
        self.assertEqual(parent.status, 'COMPLETED')
        self.assertEqual(parent.rungs[1].status, 'CANCELLED')

    def test_cancel_only_does_not_execute(self):
        parent = self.create(downside_mode='SINGLE', downside_target_price=95, stop_loss_action='CANCEL_REMAINING')
        self.tick(parent, 94)
        self.assertEqual(parent.status, 'CANCELLED')
        self.assertEqual(SyntheticExecution.query.count(), 0)
        self.client.create_order.assert_not_called()

    def test_buy_protection_buys_and_paper_never_uses_live_client(self):
        parent = self.create(side='BUY', downside_mode='SINGLE', downside_target_price=105)
        self.tick(parent, 106)
        record = TestOrder.query.one()
        self.assertEqual(record.side, 'BUY'); self.assertEqual(record.quantity, 10)
        self.client.create_order.assert_not_called()

    def test_submitted_then_partial_then_filled_has_truthful_progress(self):
        self.client.create_order.side_effect = None
        self.client.create_order.return_value = {'orderId': 123, 'status': 'NEW', 'executedQty': '0'}
        parent = self.create(test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        self.tick(parent, 111)
        self.assertEqual(parent.status, 'SUBMITTED'); self.assertEqual(parent.to_dict()['filled_quantity'], 0)
        self.tick(parent, 120)
        self.client.create_order.assert_called_once()
        self.client.get_order.return_value = {'orderId': 123, 'status': 'PARTIALLY_FILLED', 'executedQty': '4', 'cummulativeQuoteQty': '444'}
        rows = ex.reconcile_executions(parent, 'LADDER'); ladder._sync_parent(parent, rows)
        self.assertEqual(parent.status, 'SUBMITTED'); self.assertEqual(parent.to_dict()['filled_quantity'], 4)
        self.client.get_order.return_value = {'orderId': 123, 'status': 'FILLED', 'executedQty': '10', 'cummulativeQuoteQty': '1115'}
        rows = ex.reconcile_executions(parent, 'LADDER'); ladder._sync_parent(parent, rows)
        self.assertEqual(parent.status, 'COMPLETED'); self.assertEqual(rows[0].filled_price, 111.5)

    def test_rejection_is_not_completed(self):
        self.client.create_order.side_effect = None
        self.client.create_order.return_value = {'status': 'REJECTED', 'executedQty': '0'}
        parent = self.create(test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        self.tick(parent, 111)
        self.assertEqual(parent.status, 'FAILED'); self.assertEqual(parent.rungs[0].status, 'FAILED')
        self.assertEqual(parent.to_dict()['filled_quantity'], 0)

    def test_ambiguous_submission_survives_reload_and_is_never_retransmitted(self):
        self.client.create_order.side_effect = TimeoutError('lost acknowledgement')
        parent = self.create(test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        self.tick(parent, 111)
        parent_id = parent.id
        db.session.remove(); parent = db.session.get(LadderOrder, parent_id)
        self.assertEqual(ex.executions(parent, 'LADDER')[0].status, 'UNKNOWN')
        self.tick(parent, 111)
        self.client.create_order.assert_called_once()
        self.client.get_order.return_value = {'status': 'FILLED', 'executedQty': '10', 'cummulativeQuoteQty': '1110'}
        rows = ex.reconcile_executions(parent, 'LADDER'); ladder._sync_parent(parent, rows)
        self.assertEqual(parent.status, 'COMPLETED')

    def test_cancellation_reconciles_submitted_order(self):
        self.client.create_order.side_effect = None
        self.client.create_order.return_value = {'status': 'NEW', 'executedQty': '0'}
        self.client.get_order.return_value = {'status': 'PARTIALLY_FILLED', 'executedQty': '2'}
        self.client.cancel_order.return_value = {'status': 'CANCELED', 'executedQty': '2'}
        parent = self.create(test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        self.tick(parent, 111)
        result = ladder.cancel_ladder_order(parent.id, 1)
        self.assertEqual(result['status'], 'CANCELLED'); self.assertEqual(result['filled_quantity'], 2)
        self.client.cancel_order.assert_called_once()
        self.tick(parent, 200); self.client.create_order.assert_called_once()

    def test_standalone_binance_trailing_live_path_and_paper_path(self):
        for paper in (True, False):
            with self.subTest(paper=paper):
                result = trailing.create_trailing_order(1, 'BTCUSD', 'SELL', 1, test_mode=paper)
                parent = db.session.get(TrailingOrder, result['id'])
                self.client.create_order.side_effect = None
                self.client.create_order.return_value = {'status': 'FILLED', 'executedQty': '1', 'cummulativeQuoteQty': '97'}
                trailing.evaluate_single_trailing_order(parent, 97)
                self.assertEqual(parent.status, 'FILLED')
        self.assertEqual(self.client.create_order.call_count, 1)

    def test_webull_paper_uses_its_own_positions_cash_and_ledger(self):
        db.session.add(WebullTestAccount(user_id=1, cash_balance=10000, currency='USD')); db.session.commit()
        parent = self.create(broker='webull', instrument_type='ETF', symbol='SPY', side='BUY',
                             upside_mode='SINGLE', upside_target_price=90)
        self.tick(parent, 89)
        self.assertEqual(parent.status, 'COMPLETED')
        self.assertEqual(WebullTestOrder.query.one().filled_quantity, 10)
        self.assertEqual(WebullTestPosition.query.one().quantity, 10)
        self.assertEqual(WebullTestAccount.query.one().cash_balance, 9110)
        self.assertEqual(TestOrder.query.count(), 0)
        self.webull_submit.assert_not_called()

    def test_paper_ledger_rolls_back_with_execution_failure(self):
        db.session.add(WebullTestAccount(user_id=1, cash_balance=10000, currency='USD')); db.session.commit()
        parent = self.create(broker='webull', instrument_type='EQUITY', symbol='AAPL', side='BUY', upside_mode='SINGLE', upside_target_price=90)
        with patch.object(ex, 'apply_broker_result', side_effect=ValueError('invalid result')):
            self.tick(parent, 89)
        self.assertEqual(parent.status, 'FAILED')
        self.assertEqual(WebullTestAccount.query.one().cash_balance, 10000)
        self.assertEqual(WebullTestOrder.query.count(), 0)
        self.assertEqual(WebullTestPosition.query.count(), 0)
        self.assertEqual(SyntheticExecution.query.count(), 0)

    def test_validation_rejects_nonfinite_allocations_and_wrong_direction(self):
        for bad in (float('nan'), float('inf'), -1, 0):
            with self.subTest(quantity=bad), self.assertRaises(ValueError): self.create(total_quantity=bad)
        for spec in ([{'offset_pct': 5, 'pct_of_total': 150}, {'offset_pct': 10, 'pct_of_total': -50}],
                     [{'offset_pct': -5, 'pct_of_total': 100}]):
            with self.subTest(rungs=spec), self.assertRaises(ValueError): self.create(custom_rungs=spec)
        with self.assertRaises(ValueError): self.create(upside_mode='TRAILING', upside_trail_value=100)
        with self.assertRaises(ValueError): self.create(upside_mode='UNSUPPORTED')

    def test_aggressive_and_custom_are_preserved(self):
        parent = self.create(preset_name='AGGRESSIVE')
        self.assertEqual([r.target_price for r in parent.rungs], [105, 110, 115, 120])
        parent = self.create(custom_rungs=[{'target_price': 111, 'pct_of_total': 60}, {'target_price': 123, 'pct_of_total': 40}])
        self.assertEqual([r.target_price for r in parent.rungs], [111, 123])
        self.assertEqual([r.quantity for r in parent.rungs], [6, 4])

    def test_maximum_order_size_enforced_server_side(self):
        setting = db.session.get(TradingSettings, 1); setting.max_order_size_usd = 100; db.session.commit()
        with self.assertRaisesRegex(ValueError, 'maximum order size'): self.create(test_mode=False)

    def test_account_and_mode_list_filters_and_ownership(self):
        one = self.create()
        self.create(test_mode=False)
        self.assertEqual(len(ladder.get_user_ladder_orders(1, broker='all')), 2)
        self.assertEqual(len(ladder.get_user_ladder_orders(1, test_mode=True)), 1)
        self.assertEqual(ladder.get_user_ladder_orders(2), [])
        with self.assertRaises(ValueError): ladder.cancel_ladder_order(one.id, 2)

    def test_worker_holds_closed_market_and_pauses_legacy_orders(self):
        parent = self.create(broker='webull', instrument_type='ETF', symbol='SPY', side='BUY')
        identifier = parent.id
        with patch.object(ex, 'market_is_open', return_value=False): ladder.evaluate_active_ladder_orders()
        parent = db.session.get(LadderOrder, identifier)
        self.assertEqual(parent.status, 'ACTIVE'); self.assertIn('regular market', parent.monitoring_error)
        parent.engine_version = 1; db.session.commit()
        identifier = parent.id
        ladder.evaluate_active_ladder_orders()
        self.assertEqual(db.session.get(LadderOrder, identifier).status, 'NEEDS_REVIEW')

    def test_webull_quote_is_venue_scoped_and_rejects_stale_crypto(self):
        credential = SimpleNamespace(webull_app_key='key', webull_app_secret='secret', webull_access_token='token')
        with patch.object(ex, 'webull_credentials', return_value=(credential, 'uat')), patch('services.webull_service.get_webull_market_snapshot') as snapshot:
            snapshot.return_value = {'price': 100, 'as_of': datetime.now(timezone.utc).isoformat()}
            self.assertEqual(ex.reference_price('BTCUSD', broker='webull', user_id=1), 100)
            self.assertEqual(snapshot.call_args.args[2], 'uat')
            snapshot.return_value['as_of'] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            with self.assertRaisesRegex(ValueError, 'stale'): ex.reference_price('BTCUSD', broker='webull', user_id=1)

    def test_two_factor_and_mode_are_enforced_for_synthetic_routes(self):
        from routes import portfolio
        settings = db.session.get(TradingSettings, 1); settings.require_2fa = True; settings.totp_secret = 'test'; db.session.commit()
        with self.app.test_request_context(json={'broker': 'binance', 'test_mode': False}), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            _, error = portfolio._synthetic_request_mode({'broker': 'binance', 'test_mode': False})
            self.assertEqual(error[1], 403)
            self.assertTrue(error[0].get_json()['requires_2fa'])
        settings.test_mode_enabled = True; db.session.commit()
        with self.app.test_request_context(), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            _, error = portfolio._synthetic_request_mode({'broker': 'binance', 'test_mode': False})
            self.assertEqual(error[1], 409)

    def test_live_webull_routes_each_supported_instrument_and_waits_for_confirmation(self):
        cred = SimpleNamespace(webull_app_key='key', webull_app_secret='secret', webull_access_token='token')
        self.webull_submit.side_effect = None
        self.webull_submit.return_value = {'success': True, 'order_id': 'WB123'}
        for instrument, symbol in [('CRYPTO', 'BTCUSD'), ('EQUITY', 'AAPL'), ('ETF', 'SPY')]:
            with self.subTest(instrument=instrument), patch.object(ex, 'webull_credentials', return_value=(cred, 'production')), \
                 patch('services.webull_service.get_webull_account_positions', return_value=[{'symbol': symbol, 'quantity': 10}]), \
                 patch('services.webull_service.get_webull_order_detail', return_value={'order_id': 'WB123', 'status': 'FILLED', 'filled_qty': '10', 'filled_price': '111.25'}):
                parent = self.create(broker='webull', instrument_type=instrument, symbol=symbol, test_mode=False, account_id='ACCOUNT', upside_mode='SINGLE', upside_target_price=110)
                self.tick(parent, 111)
                self.assertEqual(parent.status, 'SUBMITTED')
                self.assertEqual(self.webull_submit.call_args.kwargs['instrument_type'], instrument)
                self.assertEqual(self.webull_submit.call_args.kwargs['account_id'], 'ACCOUNT')
                rows = ex.reconcile_executions(parent, 'LADDER'); ladder._sync_parent(parent, rows)
                self.assertEqual(parent.status, 'COMPLETED'); self.assertEqual(rows[0].filled_price, 111.25)
        self.client.create_order.assert_not_called()

    def test_api_contract_preserves_custom_rungs_and_downside(self):
        from routes import portfolio
        payload = {'broker': 'binance', 'test_mode': True, 'symbol': 'BTCUSD', 'side': 'SELL', 'total_quantity': 10,
                   'custom_rungs': [{'target_price': 111, 'percentage_of_total': 25}, {'target_price': 125, 'percentage_of_total': 75}],
                   'upside_mode': 'LADDER', 'downside_mode': 'TRAILING', 'downside_trail_type': 'AMOUNT', 'downside_trail_value': 5,
                   'has_stop_loss': True}
        with self.app.test_request_context(json=payload), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            response = portfolio.api_create_ladder_order.__wrapped__()
            data = response.get_json()
        self.assertTrue(data['success']); order = data['ladder_order']
        self.assertEqual(order['downside_mode'], 'TRAILING'); self.assertEqual(order['downside_trail_type'], 'AMOUNT')
        self.assertEqual([r['target_price'] for r in order['rungs']], [111, 125])
        self.assertEqual([r['quantity'] for r in order['rungs']], [2.5, 7.5])

    def test_live_funding_recheck_cannot_create_a_short(self):
        self.client.get_asset_balance.return_value = {'free': '1'}
        parent = self.create(test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        self.tick(parent, 111)
        self.assertEqual(parent.status, 'FAILED'); self.assertIn('sufficient', parent.monitoring_error)
        self.client.create_order.assert_not_called()

    def test_half_day_session_uses_exchange_close(self):
        parent = self.create(broker='webull', instrument_type='ETF', symbol='SPY')
        with patch.object(ex, 'utc_now', return_value=datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)):
            self.assertFalse(ex.market_is_open(parent))
        with patch.object(ex, 'utc_now', return_value=datetime(2026, 11, 27, 17, 0, tzinfo=timezone.utc)):
            self.assertTrue(ex.market_is_open(parent))

    def test_webull_credentials_are_redacted_in_log_mappings(self):
        import logging
        from core.log_redaction import SecretRedactionFilter
        record = logging.LogRecord('test', 20, '', 1, "params=%s", ({'app_key':'private-key', 'app_secret':'private-secret', 'access_token':'private-token', 'symbol':'AAPL'},), None)
        SecretRedactionFilter().filter(record)
        self.assertNotIn('private-', record.getMessage()); self.assertIn('AAPL', record.getMessage())
