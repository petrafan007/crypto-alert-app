"""Isolated regression tests: no broker traffic or production database mutations."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from decimal import Decimal
import test_synthetic_order_lifecycle as lifecycle
from core.extensions import db
from trading_models import TradingSettings, TestPortfolio, TestOrder, LadderOrder
from services import binance_fee_service as fees
from services.binance_paper_service import fund_account, account_summary, apply_fill


class FeeTests(unittest.TestCase):
    def tearDown(self):
        fees._cache.clear()

    def test_account_rates_include_side_and_tax_and_preserve_zero(self):
        client = Mock()
        client._get.return_value = {'symbol': 'BTCUSD',
            'standardCommission': {'maker': '0', 'taker': '.0002', 'buyer': '0', 'seller': '.0001'},
            'taxCommission': {'taker': '.00001'},
            'discount': {'enabledForAccount': True, 'enabledForSymbol': True, 'discountAsset': 'BNB', 'discount': '.25'}}
        result = fees.get_fee_quote(1, 'BTCUSD', client=client)
        self.assertEqual(result['rates']['BUY']['maker'], 0)
        self.assertAlmostEqual(result['rates']['SELL']['taker'], .00031)
        self.assertAlmostEqual(result['rates']['BUY']['taker'], .00021)
        self.assertAlmostEqual(result['rates']['SELL']['otherTaker'], .00001)
        self.assertTrue(result['bnb']['enabled'])
        self.assertEqual(result['bnb']['discountFraction'], .05)  # US policy, not old/global examples
        client._get.assert_called_once_with('account/commission', signed=True, version=3, data={'symbol': 'BTCUSD'})
        client._request_margin_api.assert_not_called()

    def test_fallback_uses_us_endpoint_and_no_assumed_rate_on_failure(self):
        client = Mock(); client._get.side_effect = RuntimeError('not supported')
        client._request_margin_api.return_value = [{'symbol': 'BTCUSD', 'makerCommission': '0', 'takerCommission': '0'}]
        result = fees.get_fee_quote(1, 'BTCUSD', client=client)
        self.assertEqual(result['takerRate'], 0)
        client._request_margin_api.assert_called_once_with('get', 'asset/query/trading-fee', signed=True, data={'symbol': 'BTCUSD'})
        for data in ([], [{'symbol': 'OTHER', 'makerCommission': '0', 'takerCommission': '.01'}], [{'symbol': 'BTCUSD', 'makerCommission': '0', 'takerCommission': 'NaN'}]):
            client._request_margin_api.return_value = data
            with self.assertRaises(ValueError): fees.get_fee_quote(1, 'BTCUSD', client=client)
        client._request_margin_api.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError): fees.get_fee_quote(1, 'BTCUSD', client=client)

    def test_pinned_sdk_constructs_without_eager_network_and_uses_us_api(self):
        from services.synthetic_execution_service import binance_client
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network')):
            client = binance_client(public=True)
            self.assertIn('binance.us', client.API_URL)
            self.assertEqual(client._requests_params['timeout'], 10)
            self.assertEqual(client._create_api_uri('account/commission', signed=True), 'https://api.binance.us/api/v3/account/commission')
            client.close_connection()

    def test_published_paper_schedule_does_not_access_credentials(self):
        with patch('services.synthetic_execution_service.binance_client', side_effect=AssertionError('No live API')):
            self.assertEqual(fees.get_fee_quote(1, 'BTCUSD', paper=True)['takerRate'], .0002)
            self.assertEqual(fees.get_fee_quote(1, 'BNBUSD', paper=True)['takerRate'], .0001)
            self.assertFalse(fees.get_fee_quote(1, 'BNBUSDT', paper=True)['bnb']['enabled'])


class PaperFundingTests(unittest.TestCase):
    setUp = lifecycle.SyntheticLifecycleTests.setUp
    tearDown = lifecycle.SyntheticLifecycleTests.tearDown
    create = lifecycle.SyntheticLifecycleTests.create
    tick = lifecycle.SyntheticLifecycleTests.tick

    def enable(self):
        db.session.get(TradingSettings, 1).test_mode_enabled = True
        db.session.commit()

    def test_deposit_currencies_validation_and_live_mode_guard(self):
        with self.assertRaisesRegex(ValueError, 'Enable'): fund_account(1, 100)
        self.enable()
        for bad in (0, -1, 'NaN', 'Infinity', 1.001, 1000000001, None):
            with self.subTest(amount=bad), self.assertRaises(ValueError): fund_account(1, bad)
        with self.assertRaises(ValueError): fund_account(1, 100, 'BTC')
        fund_account(1, '1000.01', 'USD'); fund_account(1, 5000, 'USDT')
        self.assertEqual(account_summary(1)['balances'], {'USD': 101000.01, 'USDT': 5000})
        self.assertEqual(account_summary(2)['balances'], {'USD': 0, 'USDT': 0})

    def test_reset_requires_confirmation_and_preserves_other_accounts_and_history(self):
        self.enable()
        paper = self.create(); live = self.create(test_mode=False)
        other = self.create(user_id=2)
        db.session.add(TestPortfolio(user_id=2, symbol='USD', quantity=1234)); db.session.commit()
        with self.assertRaisesRegex(ValueError, 'Confirm'): fund_account(1, 0, reset=True)
        self.assertEqual(account_summary(1)['balances']['USD'], 100000)
        fund_account(1, 0, reset=True, confirmed=True)
        self.assertEqual(account_summary(1)['balances'], {'USD': 0, 'USDT': 0})
        self.assertEqual(account_summary(1)['holdings_count'], 0)
        self.assertEqual(account_summary(2)['balances']['USD'], 1234)
        self.assertEqual(paper.status, 'CANCELLED'); self.assertTrue(all(r.status == 'CANCELLED' for r in paper.rungs))
        self.assertEqual(live.status, 'ACTIVE'); self.assertEqual(other.status, 'ACTIVE')
        self.assertEqual(LadderOrder.query.count(), 3)
        self.assertEqual(TestPortfolio.query.filter_by(user_id=1).count(), 2)
        self.tick(paper, 1000)
        self.assertEqual(TestOrder.query.count(), 0)

    def test_buy_sell_ledger_deducts_received_asset_fees_and_rejects_overdraft(self):
        buy_fee = apply_fill(1, 'BTC', 'USD', 'BUY', 2, 100, .0002); db.session.commit()
        asset = TestPortfolio.query.filter_by(user_id=1, symbol='BTC').one()
        cash = TestPortfolio.query.filter_by(user_id=1, symbol='USD').one()
        self.assertAlmostEqual(asset.quantity, 101.9996); self.assertEqual(cash.quantity, 99800)
        self.assertAlmostEqual(buy_fee, .04)
        sell_fee = apply_fill(1, 'BTC', 'USD', 'SELL', 2, 110, .0002); db.session.commit()
        self.assertAlmostEqual(asset.quantity, 99.9996); self.assertAlmostEqual(cash.quantity, 100019.956)
        self.assertAlmostEqual(sell_fee, .044); self.assertEqual(cash.total_cost_basis, cash.quantity)
        with self.assertRaisesRegex(ValueError, 'Insufficient'): apply_fill(1, 'BTC', 'USD', 'SELL', 200, 100, .0002)
        with self.assertRaisesRegex(ValueError, 'Insufficient'): apply_fill(1, 'BTC', 'USD', 'BUY', 2000, 100, .0002)
        for bad in (float('nan'), float('inf'), -1, 0):
            with self.assertRaises(ValueError): apply_fill(1, 'BTC', 'USD', 'BUY', 1, bad, .0002)

    def test_every_synthetic_child_charges_taker_fee(self):
        parent = self.create()
        self.tick(parent, 120)
        orders = TestOrder.query.all()
        self.assertEqual(len(orders), 3)
        self.assertEqual(parent.status, 'COMPLETED')
        cash = TestPortfolio.query.filter_by(user_id=1, symbol='USD').one()
        self.assertAlmostEqual(cash.quantity, 100000 + 10 * 120 * .9998)
        self.assertTrue(all('0.02%' in o.notes for o in orders))
        self.client.create_order.assert_not_called()

    def test_native_paper_buy_spends_fake_funds_without_signed_exchange_calls(self):
        from routes import portfolio
        self.enable()
        self.client.get_symbol_ticker.return_value = {'price': '100'}
        filters = {'stepSize': .00001, 'minQty': .00001, 'maxQty': 1000, 'tickSize': .01, 'minPrice': .01, 'maxPrice': 1e9, 'minNotional': 1}
        with self.app.test_request_context(json={'symbol': 'BTCUSD', 'side': 'BUY', 'type': 'MARKET', 'quantity': '2'}), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)), patch.object(portfolio, 'get_symbol_filters', return_value=filters):
            response = portfolio.place_test_order.__wrapped__()
            self.assertFalse(isinstance(response, tuple), response)
            self.assertTrue(response.get_json()['success'])
        self.assertAlmostEqual(TestPortfolio.query.filter_by(symbol='BTC').one().quantity, 101.9996)
        self.assertEqual(TestPortfolio.query.filter_by(symbol='USD').one().quantity, 99800)
        self.client.create_test_order.assert_not_called(); self.client.create_order.assert_not_called()

    def test_routes_are_authenticated_and_user_scoped(self):
        from routes import portfolio
        self.enable()
        self.app.register_blueprint(portfolio.portfolio_bp)
        # Login wrapper is retained; route logic is exercised in an isolated request context.
        with self.app.test_request_context(json={'amount': 100, 'currency': 'USDT'}), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            result = portfolio.deposit_binance_paper_money.__wrapped__().get_json()
            self.assertEqual(result['balances']['USDT'], 100)
        with self.app.test_request_context(json={'amount': 0, 'reset': True}), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            response, status = portfolio.deposit_binance_paper_money.__wrapped__()
            self.assertEqual(status, 400); self.assertIn('Confirm', response.get_json()['error'])
        with self.app.test_request_context(), patch.object(portfolio, 'current_user', SimpleNamespace(id=2)):
            self.assertEqual(portfolio.get_binance_paper_account.__wrapped__().get_json()['balances']['USDT'], 0)
