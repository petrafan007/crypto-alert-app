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
        return SimpleNamespace(total_bankroll=50000, module_settings_json='{}', allocations_json=json.dumps(DEFAULT_ALLOCATIONS), watchlists_json=json.dumps(DEFAULT_QUANT_WATCHLISTS))

    def test_allocation_rejects_nan_negative_unknown_and_rounding(self):
        for value in (float('nan'), float('inf'), -1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                e.validate_config({'allocations': {**DEFAULT_ALLOCATIONS, 'equities': value}}, self.config())
        with self.assertRaises(ValueError):
            e.validate_config({'allocations': {**DEFAULT_ALLOCATIONS, 'extra': 0}}, self.config())
        with self.assertRaises(ValueError):
            e.validate_config({'allocations': {m: 20.006 for m in DEFAULT_ALLOCATIONS}}, self.config())

    def test_dedicated_ai_config_rejects_removed_ollama_models(self):
        from routes.portfolio_algo import validate_master_ai_config
        config = {
            'primary': {'provider': 'gemini', 'model': 'gemini-3.8-flash'},
            'secondary': {'provider': 'ollama', 'model': 'nemotron-3-ultra:cloud'},
            'tertiary': {'provider': 'ollama', 'model': 'lfm2-cpu:latest'},
        }
        available = ['gemma4:26b', 'nemotron-3-ultra:cloud']
        with patch('services.ai_service.get_ollama_models', return_value=available), \
             self.assertRaisesRegex(ValueError, "lfm2-cpu:latest.*not available"):
            validate_master_ai_config(config)
        config['tertiary']['model'] = 'gemma4:26b'
        with patch('services.ai_service.get_ollama_models', return_value=available):
            self.assertIsNone(validate_master_ai_config(config))

    def test_connection_checks_do_not_run_ai_inference(self):
        from routes.portfolio_algo import test_provider_api
        app = Flask(__name__)
        gemini_response = SimpleNamespace(
            status_code=200,
            json=lambda: {'name': 'models/gemini-3.8-flash'},
        )
        with app.test_request_context(), \
             patch('requests.get', return_value=gemini_response) as get_request, \
             patch('requests.post') as post_request:
            response = test_provider_api('gemini', 'secret', 'gemini-3.8-flash')
            self.assertTrue(response.json['success'])
            get_request.assert_called_once()
            post_request.assert_not_called()

        with app.test_request_context(), \
             patch('services.ai_service.get_ollama_models', return_value=['lfm2.5:latest']) as get_models, \
             patch('services.ai_service.call_ollama_chat') as chat_request:
            response = test_provider_api('ollama', '', 'lfm2.5:latest')
            self.assertTrue(response.json['success'])
            get_models.assert_called_once_with(timeout=10)
            chat_request.assert_not_called()

    def test_enabled_targets_cover_every_combination(self):
        for mask in range(32):
            cfg = self.config()
            cfg.module_settings_json = json.dumps({m: {'enabled': bool(mask & (1 << i))} for i, m in enumerate(e.MODULES)})
            effective = e.allocations_for(cfg)
            self.assertEqual(round(sum(effective.values()), 2), 100 if mask else 0)
            for i, module in enumerate(e.MODULES):
                if not mask & (1 << i):
                    self.assertEqual(effective[module], 0)

    def test_effective_targets_and_preferences_are_validated_together(self):
        cfg = self.config()
        weights = {**DEFAULT_ALLOCATIONS, 'equities': 54, 'options': 36, 'crypto': 0, 'events': 0}
        payload = {'allocation_weights': weights,
                   'allocations': {'equities': 60, 'options': 40, 'crypto': 0, 'futures': 0, 'events': 0}}
        self.assertEqual(json.loads(e.validate_config(payload, cfg)['allocations_json']), weights)
        for change in ({'allocations': DEFAULT_ALLOCATIONS},
                       {'allocation_weights': {**weights, 'futures': float('nan')}},
                       {'module_settings': {'options': {'allocation_preference': -1}}},
                       {'module_settings': {'options': {'allocation_preference': True}}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                e.validate_config({**payload, **change}, cfg)

    def test_settings_merge_and_reject_bad_shapes(self):
        cfg = self.config()
        merged = e.validate_config({'module_settings': {'crypto': {'entry_channel_periods': 30}}}, cfg)
        self.assertEqual(json.loads(merged['module_settings_json'])['crypto']['exit_channel_periods'], 10)
        for payload in ([], {'enabled': 'false'}, {'watchlists': {'crypto': [None]}}, {'module_settings': {'crypto': {'entry_channel_periods': 20.5}}}, {'module_settings': {'futures': {'max_intraday_loss': 251}}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                e.validate_config(payload, cfg)

    def test_legacy_specialist_prompts_are_read_without_mutating_saved_settings(self):
        cfg = self.config()
        saved = {module: {'specialist_prompt': f'Custom {module} audit'} for module in e.MODULES}
        cfg.module_settings_json = json.dumps(saved)
        settings = e.settings_for(cfg)
        for module in e.MODULES:
            self.assertEqual(settings[module]['auditor_prompt'], saved[module]['specialist_prompt'])
            self.assertNotIn('specialist_prompt', settings[module])
        self.assertEqual(json.loads(cfg.module_settings_json), saved)
        e.validate_config({'module_settings': settings, 'allocations': DEFAULT_ALLOCATIONS}, cfg)

    def test_legacy_prompt_payloads_are_normalized_and_validated(self):
        for module in e.MODULES:
            cfg = self.config()
            with self.subTest(module=module):
                result = e.validate_config({'module_settings': {module: {'specialist_prompt': ' Custom audit '}}}, cfg)
                settings = json.loads(result['module_settings_json'])[module]
                self.assertEqual(settings['auditor_prompt'], 'Custom audit')
                self.assertNotIn('specialist_prompt', settings)
            for invalid in (None, 42, 'x' * 12001):
                with self.subTest(module=module, invalid_type=type(invalid).__name__), self.assertRaisesRegex(ValueError, 'Auditor prompt'):
                    e.validate_config({'module_settings': {module: {'specialist_prompt': invalid}}}, cfg)

    def test_current_prompt_takes_precedence_over_legacy_alias(self):
        for prompt in ('Current prompt', ''):
            cfg = self.config()
            values = {'specialist_prompt': 'Old prompt', 'auditor_prompt': prompt}
            cfg.module_settings_json = json.dumps({'equities': values})
            self.assertEqual(e.settings_for(cfg)['equities']['auditor_prompt'], prompt)
            result = e.validate_config({'module_settings': {'equities': values}}, cfg)
            self.assertEqual(json.loads(result['module_settings_json'])['equities']['auditor_prompt'], prompt)

    def test_unknown_strategy_parameters_still_identify_the_offending_key(self):
        cfg = self.config()
        cfg.module_settings_json = json.dumps({'equities': {'rsi_typo': 5}})
        with self.assertRaisesRegex(ValueError, 'equities strategy parameter: rsi_typo'):
            e.validate_config({'module_settings': e.settings_for(cfg)}, cfg)

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
        checks = crypto_signal(bars, 101, settings, False)['checks']
        self.assertEqual(checks['completed_hourly_bars'], 25)
        self.assertTrue(checks['price_above_entry_channel'])
        self.assertFalse(checks['dominance_gate_passed'])
        self.assertEqual(checks['atr_period'], 14)
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
        from services.provider_resilience import ProviderState
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
        settings = e.settings_for(self.cfg)
        settings['futures']['enabled'] = True  # Explicit opt-in for legacy futures lifecycle tests.
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
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

    def test_positions_endpoint_preserves_futures_collateral_and_multiplier(self):
        lot = self.entry(module='futures', multiplier=5, margin=1000)
        self.assertIsNotNone(lot)
        db.session.commit()
        response = self.client.get('/api/webull/portfolio-algo/positions')
        self.assertEqual(response.status_code, 200)
        row = response.json['positions'][0]
        self.assertEqual(row['contract_multiplier'], 5)
        self.assertEqual(row['market_value'], lot.collateral)
        self.assertEqual(row['cost_basis'], lot.collateral)

    def test_start_and_save_with_legacy_specialist_prompts(self):
        settings = e.settings_for(self.cfg)
        for module, values in settings.items():
            values.pop('auditor_prompt')
            values['specialist_prompt'] = f'Preserved {module} prompt'
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()

        response = self.client.post('/api/webull/portfolio-algo/control', json={'action': 'start'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(self.cfg.enabled)
        self.assertEqual(self.cfg.worker_status, 'STARTING')
        self.assertEqual(self.client.post('/api/webull/portfolio-algo/control', json={'action': 'stop'}).status_code, 200)

        loaded = self.client.get('/api/webull/portfolio-algo/config').json['config']
        for module in e.MODULES:
            self.assertEqual(loaded['module_settings'][module]['auditor_prompt'], f'Preserved {module} prompt')
            self.assertNotIn('specialist_prompt', loaded['module_settings'][module])
        # A browser opened before upgrading can still submit the old field names.
        response = self.client.post('/api/webull/portfolio-algo/config', json={'module_settings': settings})
        self.assertEqual(response.status_code, 200, response.json)
        saved = json.loads(self.cfg.module_settings_json)
        for module in e.MODULES:
            self.assertEqual(saved[module]['auditor_prompt'], f'Preserved {module} prompt')
            self.assertNotIn('specialist_prompt', saved[module])

    def test_disabled_modules_make_no_entry_data_calls_or_fills(self):
        from unittest.mock import MagicMock
        settings = e.settings_for(self.cfg)
        for module in settings:
            settings[module]['enabled'] = False
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
        e.control(self.user_id, 'start')
        data = MagicMock()
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertTrue(result['success'])
        self.assertFalse(data.mock_calls)
        self.assertEqual(e.current_lots(self.user_id, self.state), [])
        self.assertEqual({v['status'] for v in result['modules'].values()}, {'DISABLED'})
        from portfolio_algo_models import PortfolioEngineLog
        log_types = {row.event_type for row in PortfolioEngineLog.query.filter_by(user_id=self.user_id).all()}
        self.assertIn('SCAN_COMPLETE', log_types)
        self.assertIsNone(self.entry())
        status = e.portfolio_status(self.user_id)
        self.assertEqual(status['cash_allocation_pct'], 100)
        self.assertEqual(status['account']['cash_balance'], 50000)

    def test_disabled_module_still_closes_existing_position_at_stop(self):
        from unittest.mock import MagicMock
        lot = self.entry(module='crypto', price=100, stop=95)
        db.session.commit()
        settings = e.settings_for(self.cfg)
        for module in settings:
            settings[module]['enabled'] = False
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
        data = MagicMock()
        data.quote.return_value = 90
        data.bars.side_effect = ValueError('history unavailable')
        e.control(self.user_id, 'start')
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertTrue(result['success'])
        self.assertIsNotNone(lot.closed_at)
        self.assertEqual(result['modules']['crypto']['entries'], 0)
        self.assertEqual(data.quote.call_count, 1)

    def test_module_toggle_api_preserves_weights_and_rejects_strings(self):
        response = self.client.post('/api/webull/portfolio-algo/config', json={'module_settings': {'futures': {'enabled': False}}})
        self.assertEqual(response.status_code, 200)
        cfg = response.json['config']
        self.assertFalse(cfg['module_settings']['futures']['enabled'])
        self.assertEqual(cfg['allocations'], {'equities': 38.89, 'options': 27.78, 'crypto': 22.22, 'futures': 0, 'events': 11.11})
        self.assertEqual(cfg['allocation_weights']['futures'], 10)
        self.assertEqual(self.client.post('/api/webull/portfolio-algo/config', json={'module_settings': {'futures': {'enabled': True}}}).json['config']['allocations'], DEFAULT_ALLOCATIONS)
        self.assertTrue(cfg['watchlists']['futures'])
        self.assertEqual(self.client.post('/api/webull/portfolio-algo/config', json={'module_settings': {'crypto': {'enabled': 'false'}}}).status_code, 400)

    def test_dynamic_targets_save_reload_budget_and_cash_without_fills(self):
        weights = {'equities': 42, 'options': 18, 'crypto': 20, 'futures': 10, 'events': 10}
        settings = {m: {'enabled': m in ('equities', 'options'), 'allocation_preference': weights[m]} for m in e.MODULES}
        payload = {'allocation_weights': weights, 'module_settings': settings,
                   'allocations': {'equities': 70, 'options': 30, 'crypto': 0, 'futures': 0, 'events': 0}}
        response = self.client.post('/api/webull/portfolio-algo/config', json=payload)
        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        cfg = self.client.get('/api/webull/portfolio-algo/config').json['config']
        self.assertEqual(cfg['allocation_weights'], weights)
        self.assertEqual(cfg['allocations'], payload['allocations'])
        self.assertEqual(cfg['module_settings']['options']['allocation_preference'], 18)
        self.assertEqual(e.module_budget(self.cfg, self.acc, self.state, 'equities'), 35000)
        self.assertEqual(e.module_budget(self.cfg, self.acc, self.state, 'options'), 15000)
        self.assertEqual(e.module_budget(self.cfg, self.acc, self.state, 'crypto'), 0)
        self.assertEqual(self.acc.cash_balance, 50000)
        self.assertEqual(e.current_lots(self.user_id, self.state), [])
        self.assertFalse(self.cfg.enabled)
        settings = {m: {'enabled': False} for m in e.MODULES}
        response = self.client.post('/api/webull/portfolio-algo/config', json={'module_settings': settings})
        self.assertEqual(response.json['config']['cash_allocation_pct'], 100)
        self.assertEqual(sum(response.json['config']['allocations'].values()), 0)
        cfg = self.client.post('/api/webull/portfolio-algo/config', json={'module_settings': {'equities': {'enabled': True}}}).json['config']
        self.assertEqual(cfg['allocations']['equities'], 100)
        self.assertEqual(cfg['allocation_weights'], weights)

    def test_saved_zero_target_keeps_position_until_a_fresh_rebalance_scan(self):
        from unittest.mock import MagicMock
        lot = self.entry(module='crypto', price=100, stop=95)
        db.session.commit()
        initial_orders = e.Order.query.filter_by(user_id=self.user_id).count()
        response = self.client.post('/api/webull/portfolio-algo/config', json={
            'module_settings': {m: {'enabled': False} for m in e.MODULES},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['config']['cash_allocation_pct'], 100)
        self.assertIsNone(lot.closed_at)
        self.assertEqual(e.Order.query.filter_by(user_id=self.user_id).count(), initial_orders)
        self.assertFalse(self.cfg.enabled)
        data = MagicMock()
        data.quote.side_effect = ValueError('fresh quote unavailable')
        e.control(self.user_id, 'start')
        self.assertTrue(e.run_scan(self.user_id, True, provider=data)['success'])
        self.assertIsNone(lot.closed_at)
        data.quote.side_effect = None
        data.quote.return_value = 100
        data.bars.side_effect = ValueError('history unavailable')
        self.assertTrue(e.run_scan(self.user_id, True, provider=data)['success'])
        self.assertIsNotNone(lot.closed_at)
        last_order = e.Order.query.filter_by(user_id=self.user_id).order_by(e.Order.id.desc()).first()
        self.assertEqual(json.loads(last_order.notes)['reason'], 'REBALANCE_TRIM')
        self.assertEqual(e.portfolio_status(self.user_id)['positions'], [])

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
        self.assertEqual(self.cfg.worker_status, 'MONITORING_ONLY')
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

    def test_ai_config_rejects_removed_ollama_model_and_saves_available_models(self):
        path = '/api/webull/portfolio-algo/ai-config'
        payload = {'ai_config': {
            'primary': {'provider': 'gemini', 'model': 'gemini-3.8-flash', 'reasoning_level': 'high'},
            'secondary': {'provider': 'ollama', 'model': 'nemotron-3-ultra:cloud'},
            'tertiary': {'provider': 'ollama', 'model': 'lfm2-cpu:latest'},
        }}
        available = ['gemma4:26b', 'nemotron-3-ultra:cloud']
        with patch('services.ai_service.get_ollama_models', return_value=available):
            rejected = self.client.post(path, json=payload)
        self.assertEqual(rejected.status_code, 400, rejected.json)
        self.assertIn('not available', rejected.json['message'])
        self.assertEqual(json.loads(self.cfg.master_ai_config), {})

        payload['ai_config']['tertiary']['model'] = 'gemma4:26b'
        with patch('services.ai_service.get_ollama_models', return_value=available):
            saved = self.client.post(path, json=payload)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['ai_config']['tertiary']['model'], 'gemma4:26b')
        persisted = json.loads(self.cfg.master_ai_config)
        self.assertEqual(persisted['secondary']['model'], 'nemotron-3-ultra:cloud')
        self.assertEqual(persisted['tertiary']['model'], 'gemma4:26b')

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

    def test_settlement_retries_prioritize_held_contracts_and_deduplicate_before_limit(self):
        from event_algo_models import EventStrategyConfig, EventMarketSnapshot, EventContractOutcome
        from event_algo import resolve_event_outcomes
        cfg = EventStrategyConfig(user_id=self.user_id, name='Retry test', enabled=True)
        db.session.add(cfg)
        now = datetime.utcnow()
        symbols = ['KXBTCD-HELD', 'KXBTC15M-NEW', 'KXETH15M-NEW']
        for index, symbol in enumerate(symbols):
            for _ in range(35 if index else 1):
                db.session.add(EventMarketSnapshot(user_id=self.user_id, contract_symbol=symbol,
                    cutoff_at=now-timedelta(hours=10 if not index else 1), received_at=now))
        # Another user's snapshot is never resolved by this worker.
        db.session.add(EventMarketSnapshot(user_id=self.user_id+1000000, contract_symbol='OTHER', cutoff_at=now-timedelta(hours=1)))
        held = e.enter_lot(self.cfg, self.acc, self.state, 'events', symbols[0], {'enter': True}, .4, now,
                          details={'contract_symbol': symbols[0], 'outcome': 'NO'})
        db.session.commit()
        cred = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        with patch('event_algo._webull_connection_for_user', return_value=(cred, 'production')), \
             patch('services.webull_service.get_webull_event_market', return_value={'status': 'DELISTING'}) as get:
            result = resolve_event_outcomes(self.user_id, config=cfg, limit=1)
            self.assertEqual(get.call_args.kwargs['symbol'], symbols[0])
            self.assertTrue(get.call_args.kwargs['force'])
            self.assertEqual(result['pending_count'], 1)
            get.reset_mock()
            # Pending cooldown is filtered before LIMIT; duplicate snapshots do
            # not crowd out the second distinct contract.
            result = resolve_event_outcomes(self.user_id, config=cfg, limit=2)
            self.assertEqual({c.kwargs['symbol'] for c in get.call_args_list}, set(symbols[1:]))
            self.assertEqual(result['pending_count'], 2)
            pending = EventContractOutcome.query.filter_by(user_id=self.user_id, contract_symbol=symbols[0]).one()
            pending.observed_at = now-timedelta(minutes=5)
            db.session.commit()
            get.return_value = {'settled_outcome': 'NO'}
            result = resolve_event_outcomes(self.user_id, config=cfg, limit=1)
            self.assertEqual(result['resolved_count'], 1)
        mark, reason = e.mark_event(self.user_id, {'contract_symbol': symbols[0], 'outcome': 'NO'}, now)
        self.assertEqual((mark, reason), (1.0, 'SETTLEMENT'))
        e.close_lot(self.acc, held, mark, reason, now)
        self.assertEqual(e.current_lots(self.user_id, self.state), [])

    def test_delisted_event_uses_verified_exchange_settlement_and_records_provenance(self):
        from event_algo_models import EventStrategyConfig, EventMarketSnapshot, EventContractOutcome
        from event_algo import resolve_event_outcomes
        cfg = EventStrategyConfig(user_id=self.user_id, name='Fallback test', enabled=True)
        symbol = 'KXBTCD-26SEP0622-T75899.99'
        db.session.add_all([cfg, EventMarketSnapshot(user_id=self.user_id, contract_symbol=symbol,
            cutoff_at=datetime(2026, 9, 7, 2), received_at=datetime(2026, 9, 7, 1, 59))])
        db.session.commit()
        cred = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        fallback = {'settled_outcome': 'YES', 'settlement_price': 1.0,
                    'payout_date': '2026-09-07T02:02:45Z', 'market': {'ticker': symbol, 'result': 'yes'}}
        with patch('event_algo._webull_connection_for_user', return_value=(cred, 'production')), \
             patch('services.webull_service.get_webull_event_market', side_effect=ValueError('Market removed')), \
             patch('services.event_settlement_data.confirmed_kalshi_settlement', return_value=fallback):
            result = resolve_event_outcomes(self.user_id, config=cfg)
        self.assertEqual(result['resolved_count'], 1)
        row = EventContractOutcome.query.filter_by(user_id=self.user_id, contract_symbol=symbol).one()
        self.assertEqual(row.resolved_source, 'KALSHI_FINALIZED_MARKET')
        self.assertEqual(row.outcome, 'YES')
        self.assertIn('Market removed', json.loads(row.raw_json)['webull_evidence']['error'])

    def test_event_capacity_rejection_does_not_emit_a_fill_log(self):
        from portfolio_algo_models import PortfolioEngineLog
        for index in range(3):
            e.enter_lot(self.cfg, self.acc, self.state, 'events', f'EVENT-{index}', {'enter': True}, .01, datetime.utcnow())
        rejected = []
        lot = e.enter_lot(self.cfg, self.acc, self.state, 'events', 'EVENT-4', {'enter': True}, .01, datetime.utcnow(), rejections=rejected)
        self.assertIsNone(lot)
        self.assertIn('capacity full', rejected[0])
        db.session.commit()
        self.assertEqual(PortfolioEngineLog.query.filter_by(user_id=self.user_id, event_type='POSITION_OPENED').count(), 3)
        status = e.portfolio_status(self.user_id)
        self.assertEqual(status['modules']['events']['capacity']['available_slots'], 0)
        self.assertEqual(status['modules']['options']['prerequisites'][0]['daily_iv_observations'], 0)

    def test_successful_audit_uses_real_ai_signature_and_records_archive(self):
        from credentials import User
        from unittest.mock import MagicMock
        user = User(id=self.user_id, username=f'quant-audit-{self.user_id}', pwd_hash='test')
        db.session.add(user)
        db.session.commit()
        response = SimpleNamespace(text='Measured results need a longer observation window.', provider='test', model='test-model')
        with patch('services.ai_service.is_ai_enabled', return_value=True), patch('services.ai_service.call_ai_with_web_search', autospec=True, return_value=(response, '')) as call:
            result = e.run_audit(self.user_id)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['provider'], 'test')
        self.assertEqual(call.call_args.kwargs['prompt_type'], 'portfolio_audit')
        self.assertEqual(call.call_args.kwargs['username'], user.username)
        self.assertEqual(len(call.call_args.kwargs['messages']), 2)
        self.assertEqual(e.Audit.query.filter_by(user_id=self.user_id).count(), 1)
        from portfolio_algo_models import PortfolioEngineLog
        log_types = {row.event_type for row in PortfolioEngineLog.query.filter_by(user_id=self.user_id).all()}
        self.assertTrue({'AUDIT_START', 'AUDIT_MODULE', 'AUDIT_MASTER', 'AUDIT_COMPLETE'} <= log_types)

    def audit_user(self):
        from credentials import User
        db.session.add(User(id=self.user_id, username=f'audit-{self.user_id}', pwd_hash='test'))
        db.session.commit()

    def test_audit_with_positions_in_every_module_and_dedicated_ai_tiers(self):
        self.audit_user()
        for module in e.MODULES:
            lot = self.entry(module=module, price=.5 if module == 'events' else 100,
                             margin=100 if module in ('options', 'futures') else None,
                             details={'width': 2} if module == 'options' else {})
            self.assertIsNotNone(lot)
        self.cfg.master_ai_config = json.dumps({
            'primary': {'provider': 'ollama', 'model': 'local-auditor', 'reasoning_level': 'high'},
            'secondary': {'provider': 'inception', 'model': 'mercury-2', 'api_key': 'encrypted-test'},
        })
        db.session.commit()
        response = SimpleNamespace(text='Saved evidence reviewed.', provider='test', model='test-model')
        with patch('credential_security.decrypt_secret', return_value='dedicated-test-key'), \
             patch('services.ai_service.is_ai_enabled', return_value=True), \
             patch('services.ai_service.call_ai_with_web_search', autospec=True, return_value=(response, '')) as call:
            result = e.run_audit(self.user_id)
        self.assertEqual(result['status'], 'SUCCESS', result['content'])
        self.assertEqual(call.call_count, 6)
        for request in call.call_args_list[:-1]:
            payload = json.loads(request.kwargs['messages'][1]['content'])
            self.assertEqual(len(payload['positions']), 1)
            self.assertEqual(payload['positions'][0]['module'], payload['module'])
            self.assertEqual(request.kwargs['custom_tier_configs'][0], ('primary', 'ollama', 'local-auditor', 'high'))
            self.assertEqual(request.kwargs['custom_api_keys'][('secondary', 'inception')], 'dedicated-test-key')
        self.assertNotIn('dedicated-test-key', json.dumps(result))
        self.assertEqual(result['evidence']['open_positions_count'], 5)
        self.assertEqual(result['evidence']['ai_cascade'], [
            {'tier': 'primary', 'provider': 'ollama', 'model': 'local-auditor', 'reasoning_level': 'high'},
            {'tier': 'secondary', 'provider': 'inception', 'model': 'mercury-2', 'reasoning_level': 'medium'},
        ])
        master_input = json.loads(call.call_args.kwargs['messages'][1]['content'])
        self.assertNotIn('module_audits', master_input)
        self.assertEqual(master_input['module_trade_results']['crypto']['open_positions'], 1)
        self.assertIn('as_of_eastern', master_input['exchange_session'])
        self.assertNotIn('allocation_preference', master_input['strategy_settings']['equities'])

    def test_module_failure_produces_partial_report_with_saved_diagnostics(self):
        self.audit_user()
        response = SimpleNamespace(text='Portfolio assessment with a missing module.', provider='test', model='test')
        def answer(**kwargs):
            if kwargs['symbol'] == 'CRYPTO':
                raise RuntimeError('Provider quota exhausted')
            return response, ''
        with patch('services.ai_service.is_ai_enabled', return_value=True), \
             patch('services.ai_service.call_ai_with_web_search', autospec=True, side_effect=answer):
            result = e.run_audit(self.user_id)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertIn('quota exhausted', result['evidence']['module_audit_errors']['crypto'])
        self.assertIsNone(result['evidence']['module_audits']['crypto'])
        self.assertTrue(result['evidence']['module_audits']['events'])

    def test_master_failure_preserves_evidence_and_completed_module_reports(self):
        self.audit_user()
        self.entry()
        db.session.commit()
        response = SimpleNamespace(text='Module assessment', provider='test', model='test')
        def answer(**kwargs):
            if kwargs['prompt_type'] == 'portfolio_audit':
                raise RuntimeError('All configured providers unavailable')
            return response, ''
        with patch('services.ai_service.is_ai_enabled', return_value=True), \
             patch('services.ai_service.call_ai_with_web_search', autospec=True, side_effect=answer):
            result = e.run_audit(self.user_id)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['evidence']['open_positions_count'], 1)
        self.assertEqual(len(result['evidence']['module_audits']), 5)
        self.assertIn('All configured providers unavailable', result['content'])
        archived = self.client.get('/api/webull/portfolio-algo/audits').json['audits'][0]
        self.assertEqual(archived['content'], result['content'])
        self.assertTrue(archived['timestamp'])

    def test_empty_master_response_is_not_a_success(self):
        self.audit_user()
        response = SimpleNamespace(text='   ', provider='test', model='test')
        with patch('services.ai_service.is_ai_enabled', return_value=True), \
             patch('services.ai_service.call_ai_with_web_search', autospec=True, return_value=(response, '')):
            result = e.run_audit(self.user_id)
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('empty portfolio report', result['content'])

    def test_manual_audit_queues_once_and_survives_separate_history_requests(self):
        path = '/api/webull/portfolio-algo/master-audit'
        with patch('routes.portfolio_algo.threading.Thread') as thread:
            response = self.client.post(path, json={})
            self.assertEqual(response.status_code, 202, response.json)
            self.assertEqual(response.json['audit']['status'], 'PENDING')
            self.assertEqual(self.client.post(path, json={}).status_code, 400)
            self.assertEqual(thread.call_count, 1)
            thread.return_value.start.assert_called_once()
        pending = self.client.get('/api/webull/portfolio-algo/audits').json['audits'][0]
        self.assertEqual(pending['id'], response.json['audit']['id'])
        with patch('services.ai_service.is_ai_enabled', return_value=False):
            thread.call_args.kwargs['target']()
        completed = self.client.get('/api/webull/portfolio-algo/audits').json['audits'][0]
        self.assertEqual(completed['status'], 'UNAVAILABLE')
        self.assertTrue(completed['content'])

    def test_start_has_grace_period_but_missing_worker_eventually_stalls(self):
        self.state.heartbeat_at = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
        e.control(self.user_id, 'start')
        self.assertEqual(e.portfolio_status(self.user_id)['worker_status'], 'STARTING')
        self.cfg.updated_at = datetime.utcnow() - timedelta(minutes=11)
        db.session.commit()
        self.assertEqual(e.portfolio_status(self.user_id)['worker_status'], 'STALLED')
        self.assertTrue(e.claim(self.user_id, force=True))
        self.assertEqual(e.portfolio_status(self.user_id)['worker_status'], 'RUNNING')

    def test_scan_provider_failure_is_visible_and_lease_released(self):
        e.control(self.user_id, 'start')
        with patch('services.portfolio_strategy_data.PortfolioMarketData', side_effect=RuntimeError('Credentials unavailable')):
            result = e.run_scan(self.user_id, True)
        self.assertTrue(result['success'])
        self.assertEqual(result['modules']['crypto']['status'], 'DATA_LIMITED')
        self.assertIn('Credentials unavailable', str(result['modules']['crypto']['messages']))
        self.assertIsNone(self.state.lease_token)
        self.assertEqual(self.cfg.worker_status, 'DEGRADED')

    def test_scan_warming_up_status_does_not_degrade_worker(self):
        from unittest.mock import MagicMock
        e.control(self.user_id, 'start')
        data = MagicMock()
        data.quote.side_effect = ValueError('Awaiting 7 daily observations for baseline')
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertTrue(result['success'])
        self.assertEqual(result['modules']['crypto']['status'], 'WARMING_UP')
        self.assertEqual(self.cfg.worker_status, 'RUNNING')


    def test_disabled_position_keeps_last_mark_when_quote_unavailable(self):
        from unittest.mock import MagicMock
        lot = self.entry(module='crypto', price=100, stop=95)
        pos = db.session.get(e.Position, lot.position_id)
        old_mark, old_time = pos.market_price, pos.updated_at
        cfg_before = json.loads(self.cfg.watchlists_json)
        settings = e.settings_for(self.cfg)
        for module in settings:
            settings[module]['enabled'] = False
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
        data = MagicMock()
        data.quote.side_effect = ValueError('MARKET_DATA_NOT_SUBSCRIBED')
        e.control(self.user_id, 'start')
        result = e.run_scan(self.user_id, True, provider=data)
        self.assertIsNone(lot.closed_at)
        self.assertEqual((pos.market_price, pos.updated_at), (old_mark, old_time))
        self.assertEqual(result['modules']['crypto']['status'], 'DISABLED')
        self.assertIn('MARKET_DATA_NOT_SUBSCRIBED', str(result['modules']['crypto']['messages']))
        self.assertEqual(json.loads(self.cfg.watchlists_json), cfg_before)
        self.assertEqual(e.portfolio_status(self.user_id)['open_positions_count'], 1)
        data.bars.assert_not_called()

    def test_reenable_preserves_settings_history_and_clears_disabled_status(self):
        lot = self.entry()
        e.close_lot(self.acc, lot, 105, 'TEST_EXIT', datetime.utcnow())
        before = (self.cfg.watchlists_json, self.cfg.allocations_json, self.acc.cash_balance)
        count = e.Order.query.filter_by(user_id=self.user_id).count()
        path = '/api/webull/portfolio-algo/config'
        self.assertEqual(self.client.post(path, json={'module_settings': {'equities': {'enabled': False, 'rsi_period': 3}}}).status_code, 200)
        self.state.telemetry_json = json.dumps({'equities': {'status': 'DISABLED', 'messages': [], 'evaluated': 0, 'entries': 0}})
        db.session.commit()
        self.assertEqual(self.client.post(path, json={'module_settings': {'equities': {'enabled': True}}}).status_code, 200)
        self.assertEqual((self.cfg.watchlists_json, self.cfg.allocations_json, self.acc.cash_balance), before)
        self.assertEqual(e.settings_for(self.cfg)['equities']['rsi_period'], 3)
        self.assertEqual(e.Order.query.filter_by(user_id=self.user_id).count(), count)
        self.assertEqual(e.portfolio_status(self.user_id)['modules']['equities']['status'], 'AWAITING_SCAN')

    def test_data_access_disabled_modules_never_construct_provider(self):
        settings = e.settings_for(self.cfg)
        for module in settings:
            settings[module]['enabled'] = False
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
        with patch('services.portfolio_readiness.PortfolioMarketData') as provider:
            response = self.client.post('/api/webull/portfolio-algo/data-check')
        self.assertEqual(response.status_code, 200)
        self.assertEqual({r['status'] for r in response.json['modules'].values()}, {'DISABLED'})
        provider.assert_not_called()

    def test_disabled_event_collector_cannot_start_manual_scan(self):
        from event_algo import run_event_strategy_scan
        self.cfg.module_settings_json = json.dumps(e.settings_for(self.cfg) | {'events': {'enabled': False}})
        db.session.commit()
        with patch('event_algo._webull_connection_for_user') as connection:
            result = run_event_strategy_scan(self.user_id, force=True)
        self.assertFalse(result['success'])
        self.assertIn('disabled', result['message'])
        connection.assert_not_called()

    def test_event_only_position_management_does_not_require_market_adapter(self):
        settings = e.settings_for(self.cfg)
        for module in settings:
            settings[module]['enabled'] = False
        lot = self.entry(module='events', price=.4, stop=None, details={'symbol': 'EVENT'})
        self.assertIsNotNone(lot)
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
        e.control(self.user_id, 'start')
        with patch('services.portfolio_strategy_data.PortfolioMarketData', side_effect=AssertionError('Unneeded provider')), patch.object(e, 'mark_event', return_value=(1, 'SETTLED')):
            result = e.run_scan(self.user_id, True)
        self.assertTrue(result['success'])
        self.assertIsNotNone(lot.closed_at)

    def test_audit_excludes_disabled_correlations_but_keeps_cash_and_exposure(self):
        settings = e.settings_for(self.cfg)
        for module in settings:
            settings[module]['enabled'] = module == 'crypto'
        self.cfg.module_settings_json = json.dumps(settings)
        db.session.commit()
        with patch('services.ai_service.is_ai_enabled', return_value=False):
            result = e.run_audit(self.user_id)
        evidence = result['evidence']
        self.assertEqual(evidence['correlations'], [])
        self.assertEqual(evidence['enabled_allocations'], {'crypto': 100})
        self.assertEqual(set(evidence['specialist_mandates']), {'crypto'})
        self.assertEqual(evidence['cash_allocation']['target_pct'], 0)
        self.assertEqual(evidence['cash_allocation']['actual_cash'], 50000)

    def test_readiness_statuses_distinguish_subscription_warmup_and_ready(self):
        from unittest.mock import MagicMock
        self.cfg.watchlists_json = json.dumps({m: (['BTC'] if m == 'crypto' else []) for m in e.MODULES})
        db.session.commit()
        e.control(self.user_id, 'start')
        data = MagicMock()
        for message, status in [('MARKET_DATA_NOT_SUBSCRIBED', 'SUBSCRIPTION_REQUIRED'),
                                ('Requires seven daily observations', 'WARMING_UP')]:
            data.quote.side_effect = ValueError(message)
            self.assertEqual(e.run_scan(self.user_id, True, data)['modules']['crypto']['status'], status)
        data.quote.side_effect = None
        data.quote.return_value = 95
        data.bars.return_value = [{'high': 100, 'low': 90, 'close': 95} for _ in range(25)]
        data.dominance_ok.return_value = True
        self.assertEqual(e.run_scan(self.user_id, True, data)['modules']['crypto']['status'], 'READY')

    def test_scheduler_refuses_duplicate_owner_without_starting_jobs(self):
        from runtime import WORKER_LOCK, run_worker
        from sqlalchemy import text
        with db.engine.connect() as connection:
            connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': WORKER_LOCK})
            try:
                with patch('services.scheduler_tasks.start_background_jobs') as start:
                    with self.assertRaisesRegex(RuntimeError, 'Another background scheduler'):
                        run_worker(self.app)
                start.assert_not_called()
            finally:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': WORKER_LOCK})

    def test_scheduler_writes_heartbeat_and_releases_ownership(self):
        from runtime import WORKER_LOCK, run_worker
        from services import provider_resilience as resilience
        from unittest.mock import Mock
        from sqlalchemy import text
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = True
        job = Mock()
        job.is_alive.return_value = True
        with patch('services.scheduler_tasks.start_background_jobs', return_value={'test-job': job}):
            run_worker(self.app, stop)
        self.assertEqual(resilience.read(resilience.identity('scheduler-heartbeat'))['payload']['threads'],
                         [{'name': 'test-job', 'alive': True}])
        with db.engine.connect() as connection:
            self.assertTrue(connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': WORKER_LOCK}).scalar())
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': WORKER_LOCK})


if __name__ == '__main__':
    unittest.main()
