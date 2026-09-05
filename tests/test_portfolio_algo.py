"""Quantitative engine regression tests. Integration tests use an isolated PostgreSQL URI."""
import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, g
from flask_login import LoginManager
from core.extensions import db
from portfolio_algo_models import DEFAULT_ALLOCATIONS, DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS
from services import portfolio_engine as e
from services.portfolio_strategy_signals import (
    completed_bars, crypto_signal, equity_signal, futures_signal, fresh_quote,
    in_session, performance, select_credit_spread, rsi,
)


class PortfolioSignalsTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(total_bankroll=50000, module_settings_json='{}', watchlists_json=json.dumps(DEFAULT_QUANT_WATCHLISTS))

    def test_allocation_rejects_nan_negative_unknown_and_rounding(self):
        for value in (float('nan'), float('inf'), -1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                e.validate_config({'allocations': {**DEFAULT_ALLOCATIONS, 'equities': value}}, self.config())
        with self.assertRaises(ValueError):
            e.validate_config({'allocations': {**DEFAULT_ALLOCATIONS, 'extra': 0}}, self.config())
        with self.assertRaises(ValueError):
            e.validate_config({'allocations': {m: 20.006 for m in DEFAULT_ALLOCATIONS}}, self.config())

    def test_settings_merge_and_reject_bad_shapes(self):
        cfg = self.config()
        merged = e.validate_config({'module_settings': {'crypto': {'entry_channel_periods': 30}}}, cfg)
        self.assertEqual(json.loads(merged['module_settings_json'])['crypto']['exit_channel_periods'], 10)
        for payload in ([], {'enabled': 'false'}, {'watchlists': {'crypto': [None]}}, {'module_settings': {'crypto': {'entry_channel_periods': 20.5}}}, {'module_settings': {'futures': {'max_intraday_loss': 251}}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                e.validate_config(payload, cfg)

    def test_holidays_dst_and_early_close(self):
        self.assertFalse(in_session(datetime(2026, 9, 7, 15)))  # Labor Day
        self.assertTrue(in_session(datetime(2026, 9, 4, 13, 30)))
        self.assertFalse(in_session(datetime(2026, 11, 27, 18, 1)))  # 1 pm ET close
        self.assertFalse(in_session(datetime(2026, 1, 5, 14, 29)))
        self.assertTrue(in_session(datetime(2026, 1, 5, 14, 30)))

    def test_forming_bar_and_nonfinite_quote_are_rejected(self):
        now = datetime(2026, 9, 4, 15, tzinfo=timezone.utc)
        row = {'time': now.timestamp(), 'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 10}
        self.assertEqual(completed_bars([row], now, seconds=3600), [])
        for quote in ({'price': float('nan'), 'as_of': now}, {'price': 1, 'as_of': now-timedelta(minutes=3)}, {'price': 1, 'as_of': None}):
            with self.assertRaises(ValueError):
                fresh_quote(quote, now)

    def test_crypto_breakout_uses_prior_channel_and_dominance(self):
        bars = [{'high': 100, 'low': 90, 'close': 95} for _ in range(25)]
        settings = DEFAULT_MODULE_SETTINGS['crypto']
        self.assertTrue(crypto_signal(bars, 101, settings, True)['enter'])
        self.assertFalse(crypto_signal(bars, 101, settings, False)['enter'])
        self.assertTrue(crypto_signal(bars, 89, settings, True)['exit'])
        self.assertEqual(rsi([1, 1, 1]), 50)

    def test_opening_range_requires_complete_minutes(self):
        start = datetime(2026, 9, 4, 13, 30, tzinfo=timezone.utc)
        bars = [{'time': (start+timedelta(minutes=i)).timestamp(), 'high': 100, 'low': 90, 'close': 95, 'volume': 10} for i in range(15)]
        settings = DEFAULT_MODULE_SETTINGS['futures']
        self.assertTrue(futures_signal(bars, 101, settings, start+timedelta(minutes=16))['enter'])
        self.assertEqual(futures_signal(bars, 89, settings, start+timedelta(minutes=16))['side'], 'SHORT')
        with self.assertRaises(ValueError):
            futures_signal(bars[1:], 101, settings, start+timedelta(minutes=16))

    def test_options_requires_ivr_and_defines_loss(self):
        legs = [dict(symbol='S', strike=95, delta=-.18, expiration='2026-10-19', option_type='PUT', bid=1.5, ask=1.6),
                dict(symbol='L', strike=90, delta=-.10, expiration='2026-10-19', option_type='PUT', bid=.4, ask=.5)]
        now = datetime(2026, 9, 4, 15)
        with self.assertRaises(ValueError):
            select_credit_spread(legs, 100, None, DEFAULT_MODULE_SETTINGS['options'], now)
        result = select_credit_spread(legs, 100, 50, DEFAULT_MODULE_SETTINGS['options'], now)
        self.assertEqual(result['credit'], 1)
        self.assertEqual(result['width'], 5)

    def test_performance_does_not_annualize_short_history_or_zero_variance(self):
        now = datetime(2026, 9, 4)
        rows = [{'time': (now+timedelta(days=i)).isoformat()+'Z', 'equity': 50000} for i in range(40)]
        short = performance(rows[:2], 50000, [])
        self.assertIsNone(short['annualized_return_pct'])
        self.assertIsNone(short['win_rate_pct'])
        full = performance(rows, 50000, [10, -5])
        self.assertEqual(full['annualized_return_pct'], 0)
        self.assertIsNone(full['sharpe'])
        self.assertEqual(full['win_rate_pct'], 50)


@unittest.skipUnless(os.environ.get('QUANT_TEST_DATABASE_URI'), 'Set QUANT_TEST_DATABASE_URI to an isolated PostgreSQL database')
class PortfolioLedgerTests(unittest.TestCase):
    user_counter = int.from_bytes(os.urandom(3))

    @classmethod
    def setUpClass(cls):
        from routes.portfolio_algo import portfolio_algo_bp
        import models  # register notification and user tables before creating the test schema
        cls.app = Flask(__name__)
        cls.app.config.update(SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI=os.environ['QUANT_TEST_DATABASE_URI'], TESTING=True)
        db.init_app(cls.app)
        manager = LoginManager(cls.app)
        @manager.user_loader
        def load_user(value):
            return SimpleNamespace(id=int(value), username='admin', is_admin=True, is_authenticated=True, is_active=True, is_anonymous=False)
        @manager.unauthorized_handler
        def unauthorized():
            return {'success': False}, 401
        @cls.app.before_request
        def clear_test_user_cache():
            g.pop('_login_user', None)
        cls.app.register_blueprint(portfolio_algo_bp)
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        type(self).user_counter += 1
        self.user_id = type(self).user_counter
        self.cfg, self.acc, self.state = e.ensure_portfolio(self.user_id)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.user_id)
            session['_fresh'] = True

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.context.pop()

    def entry(self, module='equities', side='LONG', price=100, stop=95, **kwargs):
        return e.enter_lot(self.cfg, self.acc, self.state, module, 'TEST', {'side': side, 'stop': stop, 'enter': True, 'target': .5}, price, datetime.utcnow(), **kwargs)

    def test_round_trip_conserves_cash_and_costs(self):
        lot = self.entry()
        self.assertIsNotNone(lot)
        db.session.flush()
        p = db.session.get(e.Position, lot.position_id)
        self.assertGreater(p.quantity, 0)
        e.balances(self.acc, self.state, self.user_id)
        self.assertAlmostEqual(self.acc.total_equity, 50000-lot.entry_fee)
        e.close_lot(self.acc, lot, 110, 'TEST', datetime.utcnow())
        e.balances(self.acc, self.state, self.user_id)
        self.assertAlmostEqual(self.acc.total_equity, 50000+lot.realized_pnl)
        self.assertEqual(p.quantity, 0)

    def test_credit_spread_reserve_pnl_and_gtc_exit(self):
        lot = e.enter_lot(self.cfg, self.acc, self.state, 'options', 'SPY', {'side': 'SHORT', 'target': .5}, 1,
                          datetime.utcnow(), multiplier=100, margin=100, details={'width': 2})
        self.assertIsNotNone(lot)
        p = db.session.get(e.Position, lot.position_id)
        qty = p.quantity
        self.assertAlmostEqual(self.acc.cash_balance, 50000-qty*101.3)
        e.close_lot(self.acc, lot, .5, 'PROFIT_TARGET', datetime.utcnow())
        self.assertAlmostEqual(lot.realized_pnl, qty*(50-2.6))
        self.assertEqual(e.Order.query.filter_by(user_id=self.user_id, order_type='LIMIT').one().status, 'FILLED')

    def test_no_double_entry_or_overspend_and_user_isolation(self):
        self.assertIsNotNone(self.entry())
        self.assertIsNone(self.entry())
        self.acc.cash_balance = 0
        self.assertIsNone(e.enter_lot(self.cfg, self.acc, self.state, 'crypto', 'BTC', {'side': 'LONG', 'stop': 95}, 100, datetime.utcnow()))
        other_cfg, other_acc, other_state = e.ensure_portfolio(self.user_id+10000)
        self.assertEqual(other_acc.cash_balance, 50000)
        self.assertEqual(e.current_lots(other_cfg.user_id, other_state), [])

    def test_reset_archives_and_fences_inflight_scan(self):
        lot = self.entry()
        db.session.commit()
        self.cfg.enabled = True
        db.session.commit()
        token = e.claim(self.user_id, force=True)
        old_generation = self.state.generation
        e.reset_bankroll(self.user_id, 25000)
        cfg, acc, state = e.locked(self.user_id)
        self.assertEqual(state.generation, old_generation+1)
        self.assertFalse(e.owns(cfg, state, token))
        self.assertEqual(acc.total_equity, 25000)
        self.assertEqual(e.current_lots(self.user_id, state), [])
        self.assertIsNotNone(db.session.get(e.Lot, lot.id))
        self.assertGreater(e.Order.query.filter_by(user_id=self.user_id).count(), 0)

    def test_concurrent_worker_claims_have_one_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        e.control(self.user_id, 'start')
        barrier = Barrier(2)
        def claim_in_context():
            with self.app.app_context():
                try:
                    barrier.wait(timeout=5)
                    return e.claim(self.user_id, True)
                finally:
                    db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim_in_context) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(bool(token) for token in results), 1)

    def test_worker_lease_and_stop(self):
        e.control(self.user_id, 'start')
        token = e.claim(self.user_id, True)
        self.assertTrue(token)
        self.assertIsNone(e.claim(self.user_id, True))
        e.control(self.user_id, 'stop')
        cfg, _, state = e.locked(self.user_id)
        self.assertFalse(e.owns(cfg, state, token))

    def test_circuit_is_persistent_and_notification_is_written_once(self):
        from models import Notification
        self.acc.cash_balance = self.acc.total_equity = 45000
        self.cfg.enabled = True
        self.assertTrue(e.check_circuit(self.cfg, self.acc, self.state))
        db.session.commit()
        self.assertTrue(self.state.kill_switch)
        self.assertFalse(self.cfg.enabled)
        self.assertEqual(Notification.query.filter_by(user_id=self.user_id, category='portfolio_strategy').count(), 1)
        e.check_circuit(self.cfg, self.acc, self.state)
        db.session.commit()
        self.assertEqual(Notification.query.filter_by(user_id=self.user_id, category='portfolio_strategy').count(), 1)
        with self.assertRaises(ValueError):
            e.control(self.user_id, 'start')

    def test_api_auth_validation_reset_confirmation_and_zero_balance(self):
        path = '/api/webull/portfolio-algo/'
        self.assertEqual(self.app.test_client().get(path+'status').status_code, 401)
        with patch('routes.portfolio_algo.is_event_strategy_admin', return_value=False):
            self.assertEqual(self.client.get(path+'status').status_code, 403)
        self.assertEqual(self.client.get(path+'config').status_code, 200)
        for body in ([], {'allocations': {**DEFAULT_ALLOCATIONS, 'equities': float('nan')}}, {'target_annual_return': -1}):
            self.assertEqual(self.client.post(path+'config', json=body).status_code, 400)
        self.assertEqual(self.client.post(path+'reset-bankroll', json={'amount': 25000}).status_code, 400)
        self.assertEqual(self.client.post(path+'reset-bankroll', json={'amount': 25000, 'confirm': True}).status_code, 200)
        self.acc.total_equity = 0
        db.session.commit()
        self.assertEqual(self.client.get(path+'status').json['account']['total_equity'], 0)

    def test_futures_short_multiplier_and_daily_risk_budget(self):
        lot = e.enter_lot(self.cfg, self.acc, self.state, 'futures', 'MNQ', {'side': 'SHORT', 'stop': 110}, 100,
                          datetime.utcnow(), multiplier=2, margin=500)
        self.assertIsNotNone(lot)
        p = db.session.get(e.Position, lot.position_id)
        e.mark_position(p, lot, 90)
        self.assertAlmostEqual(p.unrealized_pnl, (p.average_cost-90)*p.quantity*2)
        self.assertLessEqual((110-p.average_cost)*p.quantity*2+2*lot.entry_fee, 250)

    def test_audit_disabled_reports_unavailable_without_invented_results(self):
        with patch('services.ai_service.is_ai_enabled', return_value=False):
            audit = e.run_audit(self.user_id)
        self.assertEqual(audit['status'], 'UNAVAILABLE')
        self.assertIsNone(audit['provider'])
        self.assertNotIn('0.32', audit['content'])
        self.assertIsNone(audit['evidence']['correlations'][0]['pearson_r'])

    def test_full_crypto_worker_entry_trailing_stop_and_history_failure_exit(self):
        from unittest.mock import MagicMock
        self.cfg.watchlists_json = json.dumps({m: (['BTC'] if m=='crypto' else []) for m in e.MODULES})
        db.session.commit()
        e.control(self.user_id, 'start')
        data = MagicMock()
        data.quote.return_value = 101
        data.bars.return_value = [{'high': 100, 'low': 99, 'close': 99.5} for _ in range(25)]
        data.dominance_ok.return_value = True
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertTrue(result['success'])
        lot = e.current_lots(self.user_id, self.state)[0]
        first_stop = lot.stop_price
        data.quote.return_value = 105
        e.run_scan(self.user_id, True, provider=data)
        self.assertGreater(lot.stop_price, first_stop)
        data.quote.return_value = 95
        data.bars.side_effect = RuntimeError('History unavailable')
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertTrue(result['success'])
        self.assertIsNotNone(lot.closed_at)
        self.assertEqual(e.current_lots(self.user_id, self.state), [])
        self.assertAlmostEqual(self.acc.total_equity, 50000+lot.realized_pnl)

    def test_equity_worker_enters_on_relative_momentum_pullback(self):
        from unittest.mock import MagicMock
        class FixedClock(datetime):
            @classmethod
            def utcnow(cls):
                return cls(2026, 9, 4, 15)
        self.cfg.watchlists_json = json.dumps({m: (['NVDA'] if m=='equities' else []) for m in e.MODULES})
        db.session.commit()
        closes = [100+i*.4 for i in range(198)]+[168, 163]
        bars = [{'high': c+1, 'low': c-1, 'close': c} for c in closes]
        benchmark = [{'high': 101, 'low': 99, 'close': 100} for _ in range(200)]
        data = MagicMock()
        data.quote.return_value = 164
        data.bars.side_effect = lambda symbol, *args, **kwargs: benchmark if symbol=='SPY' else bars
        with patch('services.portfolio_engine.datetime', FixedClock):
            e.control(self.user_id, 'start')
            result = e.run_scan(self.user_id, True, provider=data)
        self.assertTrue(result['success'])
        self.assertEqual(len(e.current_lots(self.user_id, self.state)), 1)
        self.assertEqual(result['modules']['equities']['entries'], 1)

    def test_options_worker_opens_and_fills_persistent_profit_exit(self):
        from unittest.mock import MagicMock
        class FixedClock(datetime):
            @classmethod
            def utcnow(cls):
                return cls(2026, 9, 4, 15)
        self.cfg.watchlists_json = json.dumps({m: (['SPY'] if m=='options' else []) for m in e.MODULES})
        db.session.commit()
        data = MagicMock()
        legs = [dict(symbol='S', strike=95, delta=-.18, expiration='2026-10-19', option_type='PUT', bid=1.5, ask=1.6),
                dict(symbol='L', strike=93, delta=-.10, expiration='2026-10-19', option_type='PUT', bid=.4, ask=.5)]
        data.options.return_value = (100, legs, 50)
        with patch('services.portfolio_engine.datetime', FixedClock):
            e.control(self.user_id, 'start')
            self.assertTrue(e.run_scan(self.user_id, True, provider=data)['success'])
            lot = e.current_lots(self.user_id, self.state)[0]
            data.spread_mark.return_value = .4
            e.run_scan(self.user_id, True, provider=data)
        self.assertIsNotNone(lot.closed_at)
        self.assertGreater(lot.realized_pnl, 0)
        self.assertEqual(e.Order.query.filter_by(user_id=self.user_id, order_type='LIMIT').one().status, 'FILLED')

    def test_futures_worker_uses_contract_metadata_and_closes_on_range_stop(self):
        from unittest.mock import MagicMock
        class FixedClock(datetime):
            @classmethod
            def utcnow(cls):
                return cls(2026, 9, 4, 15)
        self.cfg.watchlists_json = json.dumps({m: (['MES'] if m=='futures' else []) for m in e.MODULES})
        db.session.commit()
        data = MagicMock()
        data.future.return_value = ('MESZ26', 5, 1500)
        data.quote.return_value = 101
        start = datetime(2026, 9, 4, 13, 30, tzinfo=timezone.utc)
        data.bars.return_value = [{'time': (start+timedelta(minutes=i)).timestamp(), 'high': 100, 'low': 95, 'close': 98, 'volume': 10} for i in range(15)]
        with patch('services.portfolio_engine.datetime', FixedClock):
            e.control(self.user_id, 'start')
            self.assertTrue(e.run_scan(self.user_id, True, provider=data)['success'])
            lot = e.current_lots(self.user_id, self.state)[0]
            self.assertEqual(lot.multiplier, 5)
            data.quote.return_value = 90
            e.run_scan(self.user_id, True, provider=data)
        self.assertIsNotNone(lot.closed_at)
        self.assertLess(lot.realized_pnl, 0)

    def test_configuration_change_during_quote_fetch_fences_fill(self):
        from unittest.mock import MagicMock
        self.cfg.watchlists_json = json.dumps({m: (['BTC'] if m=='crypto' else []) for m in e.MODULES})
        db.session.commit()
        e.control(self.user_id, 'start')
        data = MagicMock()
        def quote(*args, **kwargs):
            e.control(self.user_id, 'stop')
            return 101
        data.quote.side_effect = quote
        data.bars.return_value = [{'high': 100, 'low': 99, 'close': 99.5} for _ in range(25)]
        data.dominance_ok.return_value = True
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertFalse(result['success'])
        self.assertEqual(e.current_lots(self.user_id, self.state), [])
        self.assertEqual(self.acc.cash_balance, 50000)

    def test_event_entry_settlement_is_scoped_and_consumed_once(self):
        from event_algo_models import EventStrategyConfig, EventMarketSnapshot, EventStrategyDecision, EventContractOutcome, EventStrategyOrder
        from event_algo import simulate_paper_fills
        now = datetime.utcnow()
        config = EventStrategyConfig(user_id=self.user_id, name='Event Test', enabled=True)
        market = EventMarketSnapshot(user_id=self.user_id, contract_symbol='KXBTC15M-TEST', series_symbol='KXBTC15M',
            received_at=now, cutoff_at=now+timedelta(minutes=10), yes_ask=.4, yes_bid=.39)
        db.session.add_all([config, market])
        db.session.flush()
        market.config_id = config.id
        decision = EventStrategyDecision(user_id=self.user_id, config_id=config.id, snapshot_id=market.id,
            contract_symbol=market.contract_symbol, action='BUY_YES', outcome='YES', eligible=True,
            confidence=.9, probability_yes=.7, probability_no=.3, net_edge=.28, executable_price=.4)
        db.session.add(decision)
        db.session.commit()
        entries = e.event_inputs(self.user_id, self.state, now, ['KXBTC15M'], DEFAULT_MODULE_SETTINGS['events'])
        self.assertEqual(len(entries), 1)
        symbol, price, signal, details, key = entries[0]
        lot = e.enter_lot(self.cfg, self.acc, self.state, 'events', symbol, signal, price, now, details=details, key=key)
        self.assertIsNotNone(lot)
        self.assertIsNone(e.enter_lot(self.cfg, self.acc, self.state, 'events', symbol, signal, price, now, details=details, key=key))
        self.assertEqual(simulate_paper_fills(self.user_id, config=config)['simulated_count'], 0)
        self.assertEqual(EventStrategyOrder.query.filter_by(user_id=self.user_id).count(), 0)
        db.session.add(EventContractOutcome(user_id=self.user_id, contract_symbol=market.contract_symbol, outcome='YES', settlement_status='RESOLVED'))
        db.session.flush()
        mark, reason = e.mark_event(self.user_id, details, now)
        quantity = db.session.get(e.Position, lot.position_id).quantity
        e.close_lot(self.acc, lot, mark, reason, now)
        self.assertAlmostEqual(lot.realized_pnl, quantity*(.6-.015))

    def test_successful_audit_uses_real_ai_signature_and_records_archive(self):
        from credentials import User
        from unittest.mock import MagicMock
        user = User(id=self.user_id, username=f'quant-audit-{self.user_id}', pwd_hash='test')
        db.session.add(user)
        db.session.commit()
        response = SimpleNamespace(text='Measured results need a longer observation window.', provider='test', model='test-model')
        with patch('services.ai_service.is_ai_enabled', return_value=True), patch('services.ai_service.call_ai_with_web_search', return_value=(response, '')) as call:
            result = e.run_audit(self.user_id)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['provider'], 'test')
        self.assertEqual(call.call_args.kwargs['prompt_type'], 'portfolio_audit')
        self.assertEqual(call.call_args.kwargs['username'], user.username)
        self.assertEqual(len(call.call_args.kwargs['messages']), 2)
        self.assertEqual(e.Audit.query.filter_by(user_id=self.user_id).count(), 1)

    def test_scan_provider_failure_is_visible_and_lease_released(self):
        e.control(self.user_id, 'start')
        with patch('services.portfolio_strategy_data.PortfolioMarketData', side_effect=RuntimeError('Credentials unavailable')):
            result = e.run_scan(self.user_id, True)
        self.assertFalse(result['success'])
        self.assertIsNone(self.state.lease_token)
        self.assertEqual(self.cfg.worker_status, 'DEGRADED')


if __name__ == '__main__':
    unittest.main()
