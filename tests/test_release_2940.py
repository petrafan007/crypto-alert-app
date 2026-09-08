"""Regression coverage for market identity, forecast timing and monetary workflows.

All database state is in-memory and all exchange actions are mocked.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from flask import Flask
from core.extensions import db
from models import Coin, PriceHistory, SentimentHistory, StakingPurchase, WebullTestAccount, WebullTestOrder, WebullTestPosition
from trading_models import RealOrder, StakingOrder
from services import staking_purchase_service as purchases
from services.sentiment_outcome_service import repair_fixed_horizon_timestamps, evaluate_pending_fixed_horizon_sentiments
from services.webull_paper_lifecycle import reconcile_paper_options, day_order_close, expiry_close
from services.price_history_service import get_symbol_performance, get_last_nh_price_and_volume, record_price_history_snapshot
from services import staking_service


class ReleaseRegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_etf_and_crypto_with_same_symbol_never_share_history(self):
        now = int(datetime(2026, 9, 4, 20, tzinfo=timezone.utc).timestamp())
        for offset, equity, crypto in [(86400, 24, 2500), (3600, 23.5, 2450), (0, 23.44, 2400)]:
            db.session.add_all([PriceHistory(symbol='ETH', exchange='equity', timestamp=now-offset, price=equity),
                                PriceHistory(symbol='ETH', exchange='binance', timestamp=now-offset, price=crypto)])
        db.session.commit()
        with patch('services.price_history_service.ensure_price_history'):
            stock = get_symbol_performance('ETH', 23.44, now_timestamp=now, is_traditional=True)
            crypto = get_symbol_performance('ETH', 2400, now_timestamp=now)
            points, context = get_last_nh_price_and_volume('ETH', now_timestamp=now)
        self.assertAlmostEqual(stock['change_1d'], -2.33, places=2)
        self.assertAlmostEqual(crypto['change_1d'], -4, places=2)
        self.assertTrue(all(row['price'] > 2000 for row in points))
        self.assertNotIn('23.44', context)

    def test_snapshot_cadence_is_market_scoped(self):
        db.session.add(PriceHistory(symbol='ETH', exchange='equity', timestamp=1000, price=23))
        db.session.commit()
        self.assertTrue(record_price_history_snapshot('ETH', 2500, now_timestamp=1001))

    def prediction(self, offset=-4):
        created = datetime(2026, 9, 1, 20, tzinfo=timezone.utc)
        row = SentimentHistory(user_id=1, symbol='ETH', sentiment='Hold', source_type='portfolio',
            price_at_prediction=100, created_at=created, forecast_horizon_hours=2, evaluation_method='fixed_horizon',
            target_evaluation_at=(created + timedelta(hours=2+offset)).replace(tzinfo=None),
            outcome_evaluated_at=created, outcome_price=100, outcome_pct=0, outcome_status='correct', grading_config='{}')
        db.session.add(row); db.session.commit()
        return row

    def test_timestamp_repair_is_audited_idempotent_and_waits_for_actual_horizon(self):
        row = self.prediction()
        self.assertEqual(repair_fixed_horizon_timestamps(), 1)
        self.assertEqual(row.target_evaluation_at, datetime(2026, 9, 1, 22))
        self.assertEqual(row.outcome_status, 'tracking')
        self.assertEqual(json.loads(row.grading_config)['_timestamp_repair_v2940']['original_outcome_status'], 'correct')
        self.assertEqual(repair_fixed_horizon_timestamps(), 0)
        resolver = Mock(return_value=(100, datetime(2026, 9, 1, 22, tzinfo=timezone.utc)))
        self.assertEqual(evaluate_pending_fixed_horizon_sentiments(now=datetime(2026, 9, 1, 21, tzinfo=timezone.utc), price_resolver=resolver), 0)
        resolver.assert_not_called()
        self.assertEqual(evaluate_pending_fixed_horizon_sentiments(now=datetime(2026, 9, 1, 22, 1, tzinfo=timezone.utc), price_resolver=resolver), 1)

    def test_grading_rejects_future_or_wrong_time_observations(self):
        row = self.prediction()
        now = datetime(2026, 9, 1, 22, 1, tzinfo=timezone.utc)
        for observed in (now + timedelta(minutes=1), now - timedelta(hours=4)):
            self.assertEqual(evaluate_pending_fixed_horizon_sentiments(now=now, price_resolver=lambda *args: (100, observed)), 0)

    def test_expired_paper_option_settles_once_and_preserves_order_evidence(self):
        db.session.add(WebullTestAccount(user_id=1, cash_balance=1000))
        pos = WebullTestPosition(user_id=1, symbol='AAPL 2026-09-02 $320 CALL', instrument_type='OPTION', side='LONG', quantity=1,
                                cost_price=2.95, last_price=2.5, option_type='CALL', option_strike=320, option_expiration='2026-09-02', underlying_symbol='AAPL', contract_multiplier=100)
        order = WebullTestOrder(user_id=1, order_id='old_buy', symbol=pos.symbol, instrument_type='OPTION', side='BUY', order_type='LIMIT', quantity=1,
                               filled_quantity=1, filled_price=2.95, status='Filled', created_at=datetime(2026, 8, 31, 15))
        db.session.add_all([pos, order]); db.session.commit()
        now = datetime(2026, 9, 7, 15, tzinfo=timezone.utc)
        reconcile_paper_options(1, now=now, close_resolver=lambda *args: 325)
        self.assertEqual(pos.quantity, 0)
        self.assertEqual(WebullTestAccount.query.first().cash_balance, 1500)
        self.assertEqual(order.filled_price, 2.95)
        settlement = WebullTestOrder.query.filter_by(status='Settled').one()
        self.assertEqual(settlement.filled_quantity, 0)
        self.assertEqual(json.loads(settlement.combo_orders)['cash_adjustment'], 500)
        reconcile_paper_options(1, now=now, close_resolver=lambda *args: 325)
        self.assertEqual(WebullTestAccount.query.first().cash_balance, 1500)

    def test_missing_expiry_price_does_not_fabricate_settlement(self):
        db.session.add(WebullTestAccount(user_id=1, cash_balance=1000))
        pos = WebullTestPosition(user_id=1, symbol='AAPL 2026-09-02 $320 CALL', instrument_type='OPTION', side='LONG', quantity=1,
            cost_price=3, option_type='CALL', option_strike=320, option_expiration='2026-09-02')
        db.session.add(pos); db.session.commit()
        reconcile_paper_options(1, now=datetime(2026, 9, 7, tzinfo=timezone.utc), close_resolver=Mock(side_effect=ValueError('missing')))
        self.assertEqual(pos.quantity, 1)
        self.assertEqual(WebullTestAccount.query.first().cash_balance, 1000)

    def test_day_order_expiry_uses_exchange_calendar(self):
        self.assertEqual(day_order_close(datetime(2026, 9, 5, tzinfo=timezone.utc)), datetime(2026, 9, 8, 20, tzinfo=timezone.utc))
        self.assertEqual(expiry_close('2026-09-02'), datetime(2026, 9, 2, 20, tzinfo=timezone.utc))

    def test_working_option_only_fills_when_limit_is_marketable(self):
        db.session.add(WebullTestAccount(user_id=1, cash_balance=1000))
        order = WebullTestOrder(user_id=1, order_id='limit', symbol='AAPL 2026-09-11 $320 CALL', instrument_type='OPTION', side='BUY', order_type='LIMIT',
            time_in_force='GTC', quantity=1, limit_price=3, filled_quantity=0, status='Working', created_at=datetime(2026, 9, 1, 15))
        db.session.add(order); db.session.commit()
        now = datetime(2026, 9, 8, 15, tzinfo=timezone.utc)
        reconcile_paper_options(1, now=now, quote_resolver=lambda *args, **kwargs: 4)
        self.assertEqual(order.status, 'Working')
        reconcile_paper_options(1, now=now, quote_resolver=lambda *args, **kwargs: 2)
        self.assertEqual(order.status, 'Filled')
        self.assertEqual(WebullTestAccount.query.first().cash_balance, 800)
        reconcile_paper_options(1, now=now, quote_resolver=lambda *args, **kwargs: 2)
        self.assertEqual(WebullTestAccount.query.first().cash_balance, 800)

    def purchase_setup(self):
        client = Mock()
        client.get_symbol_info.return_value = {'status': 'TRADING', 'filters': [{'filterType': 'MIN_NOTIONAL', 'minNotional': '5'}]}
        client.get_account.return_value = {'balances': [{'asset': 'USDT', 'free': '100'}]}
        client.get_symbol_ticker.return_value = {'price': '2'}
        client.get_asset_balance.return_value = {'free': '9.9'}
        client.create_order.return_value = {'status': 'FILLED', 'orderId': 123, 'executedQty': '10', 'cummulativeQuoteQty': '20',
            'fills': [{'qty': '10', 'commission': '.1', 'commissionAsset': 'ABC'}]}
        product = {'stakingAsset': 'ABC', 'minStakingLimit': '1', 'maxStakingLimit': '1000', 'apy': .12}
        settings = SimpleNamespace(test_mode_enabled=False, max_order_size_usd=1000)
        data = {'id': str(uuid4()), 'asset': 'ABC', 'quoteAsset': 'USDT', 'quoteAmount': '20', 'stake': True}
        return client, product, settings, data

    def test_purchase_and_stake_replay_never_buys_or_stakes_twice(self):
        client, product, settings, data = self.purchase_setup()
        response = Mock(status_code=200); response.json.return_value = {'success': True, 'data': {'purchaseRecordId': 'stake123'}}
        with patch.object(purchases, 'trading_client', return_value=client), patch.object(purchases, 'staking_catalog', return_value=[product]), patch.object(purchases, 'binance_us_api_call', return_value=response) as stake:
            first = purchases.purchase(1, None, settings, data)
            second = purchases.purchase(1, None, settings, data)
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'stake_accepted')
        self.assertEqual(first['stakeQuantity'], '9.90000000')
        client.create_order.assert_called_once()
        stake.assert_called_once()
        self.assertEqual(RealOrder.query.count(), 1)
        self.assertEqual(StakingOrder.query.count(), 1)
        self.assertLessEqual(len(client.create_order.call_args.kwargs['newClientOrderId']), 36)

    def test_purchase_timeout_stays_unknown_without_resubmission(self):
        client, product, settings, data = self.purchase_setup()
        client.create_order.side_effect = TimeoutError()
        with patch.object(purchases, 'trading_client', return_value=client), patch.object(purchases, 'staking_catalog', return_value=[product]), patch.object(purchases, 'binance_us_api_call') as stake:
            first = purchases.purchase(1, None, settings, data)
            purchases.purchase(1, None, settings, data)
        self.assertEqual(first['status'], 'buy_unknown')
        client.create_order.assert_called_once(); stake.assert_not_called()

    def test_staking_failure_preserves_successful_purchase(self):
        client, product, settings, data = self.purchase_setup()
        response = Mock(status_code=200); response.json.return_value = {'success': False, 'code': 'ERROR'}
        with patch.object(purchases, 'trading_client', return_value=client), patch.object(purchases, 'staking_catalog', return_value=[product]), patch.object(purchases, 'binance_us_api_call', return_value=response):
            result = purchases.purchase(1, None, settings, data)
        self.assertEqual(result['status'], 'bought_not_staked')
        self.assertAlmostEqual(Coin.query.filter_by(symbol='ABC').one().amount, 9.9)
        self.assertEqual(StakingOrder.query.count(), 0)

    def test_below_minimum_and_test_mode_do_not_place_real_order(self):
        client, product, settings, data = self.purchase_setup()
        with patch.object(purchases, 'trading_client', return_value=client), patch.object(purchases, 'staking_catalog', return_value=[product]):
            data['quoteAmount'] = '2'
            with self.assertRaisesRegex(ValueError, 'Minimum purchase'):
                purchases.purchase(1, None, settings, data)
            settings.test_mode_enabled = True
            with self.assertRaisesRegex(ValueError, 'Enable real trading'):
                purchases.purchase(1, None, settings, data)
        client.create_order.assert_not_called()
        self.assertEqual(StakingPurchase.query.count(), 0)

    def test_staking_cache_uses_trading_keys_and_invalidates_after_write(self):
        import requests
        from urllib.parse import urlparse, parse_qs
        cred = SimpleNamespace(api_key='read-key', api_secret='read-secret', trading_api_key='trade-key', trading_api_secret='trade-secret')
        response = requests.Response(); response.status_code = 200
        response._content = b'{"success":true,"data":[]}'
        staking_service.invalidate_staking_cache(cred)
        with patch.object(staking_service.requests, 'request', return_value=response) as network:
            for _ in range(2):
                staking_service.binance_us_api_call(cred, '/sapi/v1/staking/asset', use_trading_keys=True)
            self.assertEqual(network.call_count, 1)
            self.assertEqual(network.call_args.kwargs['headers']['X-MBX-APIKEY'], 'trade-key')
            staking_service.binance_us_api_call(cred, '/sapi/v1/staking/stake', method='POST', use_trading_keys=True, params_dict={'stakingAsset': 'A B'})
            self.assertEqual(parse_qs(urlparse(network.call_args.args[1]).query)['stakingAsset'], ['A B'])
            staking_service.binance_us_api_call(cred, '/sapi/v1/staking/asset', use_trading_keys=True)
            self.assertEqual(network.call_count, 3)

    def test_rates_above_one_are_fractions_and_catalog_errors_are_not_empty_success(self):
        self.assertEqual(staking_service.staking_rate('1.2'), 1.2)
        self.assertEqual(staking_service.staking_rate('12%'), .12)
        response = Mock(status_code=200); response.json.return_value = {'success': False, 'code': 'ERROR'}
        with patch.object(staking_service, 'binance_us_api_call', return_value=response), self.assertRaises(ValueError):
            staking_service.staking_catalog(None)

    def test_purchase_route_requires_configured_2fa_and_scopes_receipts(self):
        from routes import portfolio
        from trading_models import TradingSettings
        db.session.add(TradingSettings(user_id=1, test_mode_enabled=False, require_2fa=True, totp_secret='TESTSECRET'))
        db.session.commit()
        self.app.secret_key = 'fixture-secret'
        with self.app.test_request_context('/api/staking/purchases', method='POST', json={'id': str(uuid4())}), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)), patch.object(purchases, 'purchase') as submit:
            response, code = portfolio.api_staking_purchase.__wrapped__()
            self.assertEqual(code, 403)
            self.assertTrue(response.json['requires_2fa'])
            submit.assert_not_called()
        intent = StakingPurchase(id=str(uuid4()), user_id=2, asset='ABC', quote_asset='USDT', quote_amount='20', stake_requested=True, status='buy_unknown')
        db.session.add(intent); db.session.commit()
        with self.app.test_request_context(), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            response, code = portfolio.api_staking_purchase_receipt.__wrapped__(intent.id)
            self.assertEqual(code, 404)


if __name__ == '__main__':
    unittest.main()
