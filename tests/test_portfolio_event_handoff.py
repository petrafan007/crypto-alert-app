"""Event execution and risk-pause regression coverage (isolated DB only)."""
import json
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.extensions import db
from event_algo_models import EventContractOutcome, EventMarketSnapshot, EventStrategyConfig, EventStrategyDecision, EventStrategyRun
from services import portfolio_engine as engine
from services import portfolio_event_execution as handoff
from tests.test_portfolio_algo import PortfolioLedgerTests


def quote(symbol='KXBTC15M-TEST', now=None, **changes):
    now = now or datetime.utcnow()
    return {'symbol': symbol, 'series_symbol': 'KXBTC15M', 'yes_ask': .4, 'yes_bid': .39,
            'no_ask': .62, 'no_bid': .60, 'volume': 500, 'open_interest': 100,
            'quote_as_of': now.isoformat() + 'Z', 'cutoff_at': (now + timedelta(minutes=10)).isoformat() + 'Z', **changes}


class EventQuoteValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.utcnow()
        self.decision = SimpleNamespace(created_at=self.now, contract_symbol='KXBTC15M-TEST',
            probability_yes=.8, confidence=.9, outcome='YES')
        self.config = SimpleNamespace(risk_config='{}', signal_config='{}', kill_switch=False)
        self.settings = {'min_confidence': .5, 'min_net_edge': .015}

    def validate(self, market):
        return handoff.validate_entry(self.decision, market, self.config, self.settings, ['KXBTC15M'], self.now)

    def test_fresh_quote_passes_but_stale_missing_and_changed_contract_fail(self):
        self.assertIsNone(self.validate(quote(now=self.now))[0])
        self.assertEqual(self.validate(quote(now=self.now, quote_as_of=(self.now-timedelta(seconds=31)).isoformat()))[0], 'MISSED')
        self.assertEqual(self.validate(quote(now=self.now, quote_as_of=None))[0], 'MISSED')
        self.assertEqual(self.validate(quote(symbol='KXETH15M-OTHER', now=self.now))[0], 'REJECTED')

    def test_handoff_rejects_selected_wide_crossed_or_empty_book(self):
        for changes, reason in [({'yes_bid': .1}, 'SPREAD_TOO_WIDE'),
                                ({'yes_bid': .45}, 'CROSSED_QUOTE'),
                                ({'yes_bid': None}, 'MISSING_QUOTE'),
                                ({'yes_ask_size': 0}, 'INSUFFICIENT_LIQUIDITY')]:
            with self.subTest(changes=changes):
                status, message, _ = self.validate(quote(now=self.now, **changes))
                self.assertEqual(status, 'REJECTED')
                self.assertIn(reason, message)

    def test_crossed_book_is_data_limited_in_readiness(self):
        run = SimpleNamespace(id=1, finished_at=self.now, error_count=0,
                              error_message=None, status='COMPLETED')
        decision = SimpleNamespace(created_at=self.now, eligible=False,
                                   reason_codes='["CROSSED_QUOTE"]')
        with patch.object(handoff, 'EventStrategyRun') as runs, \
                patch.object(handoff, 'EventStrategyDecision') as decisions:
            runs.query.filter_by.return_value.order_by.return_value.first.return_value = run
            decisions.query.filter_by.return_value.all.return_value = [decision]
            status, _ = handoff.readiness(1, SimpleNamespace(id=1, enabled=True), self.now)
        self.assertEqual(status, 'DATA_LIMITED')

    def test_fresh_quote_does_not_inherit_old_depth(self):
        old = {'symbol': 'TEST', 'yes_ask_size': 0, 'no_ask_size': 500}
        credential = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        with patch.object(handoff, 'db') as database, \
                patch('event_algo._webull_connection_for_user', return_value=(credential, 'test')), \
                patch('services.webull_service.get_webull_event_snapshots', return_value={'TEST': {'yes_ask': .4}}):
            database.session.get.return_value = SimpleNamespace(raw_json=json.dumps(old))
            market = handoff.fresh_market(1, SimpleNamespace(snapshot_id=1, contract_symbol='TEST'))
        self.assertNotIn('yes_ask_size', market)
        self.assertNotIn('no_ask_size', market)

    def test_expired_decision_and_cutoff_do_not_get_relaxed(self):
        self.decision.created_at = self.now - timedelta(seconds=121)
        self.assertEqual(self.validate(quote(now=self.now))[0], 'MISSED')
        self.decision.created_at = self.now
        self.assertEqual(self.validate(quote(now=self.now, cutoff_at=(self.now+timedelta(seconds=25)).isoformat()))[0], 'MISSED')

    def test_recompute_edge_including_configured_uncertainty_not_only_old_edge(self):
        status, reason, _ = self.validate(quote(now=self.now, yes_ask=.795, yes_bid=.79))
        self.assertEqual(status, 'REJECTED')
        self.assertIn('EDGE_TOO_SMALL', reason)
        self.config.signal_config = json.dumps({'uncertainty_buffer': .5})
        self.assertEqual(self.validate(quote(now=self.now))[0], 'REJECTED')


@unittest.skipUnless(os.environ.get('QUANT_TEST_DATABASE_URI'), 'Requires isolated PostgreSQL')
class EventHandoffLedgerTests(unittest.TestCase):
    user_counter = int.from_bytes(os.urandom(3))
    setUpClass = classmethod(PortfolioLedgerTests.setUpClass.__func__)
    setUp = PortfolioLedgerTests.setUp
    tearDown = PortfolioLedgerTests.tearDown

    def decision(self, symbol='KXBTC15M-TEST', *, age=0):
        now = datetime.utcnow()
        cfg = EventStrategyConfig.query.filter_by(user_id=self.user_id).first()
        if not cfg:
            cfg = EventStrategyConfig(user_id=self.user_id, name='Test Events', enabled=True)
            db.session.add(cfg)
            db.session.flush()
        run = EventStrategyRun(user_id=self.user_id, config_id=cfg.id, status='COMPLETED',
            started_at=now, finished_at=now, heartbeat_at=now, scanned_count=1, qualified_count=1)
        db.session.add(run)
        db.session.flush()
        snap = EventMarketSnapshot(user_id=self.user_id, config_id=cfg.id, run_id=run.id,
            contract_symbol=symbol, series_symbol='KXBTC15M', received_at=now,
            cutoff_at=now+timedelta(minutes=10), yes_ask=.4, yes_bid=.39, raw_json=json.dumps(quote(symbol)))
        db.session.add(snap)
        db.session.flush()
        decision = EventStrategyDecision(user_id=self.user_id, config_id=cfg.id, run_id=run.id,
            snapshot_id=snap.id, contract_symbol=symbol, action='BUY_YES', outcome='YES', eligible=True,
            probability_yes=.8, probability_no=.2, confidence=.9, net_edge=.3, executable_price=.4,
            created_at=now-timedelta(seconds=age), feature_json=json.dumps({'existing_evidence': 123}))
        db.session.add(decision)
        self.cfg.enabled, self.cfg.worker_status = True, 'RUNNING'
        self.acc.reset_at = now-timedelta(days=1)
        db.session.commit()
        return decision

    def test_fills_immediately_while_slow_scan_owns_lease_and_is_idempotent(self):
        row = self.decision()
        token = engine.claim(self.user_id, force=True)
        self.assertTrue(token)
        loader = MagicMock(side_effect=lambda user, decision: quote(decision.contract_symbol))
        result = handoff.consume_event_decisions(self.user_id, quote_loader=loader)
        self.assertTrue(result['success'])
        self.assertEqual(result['processed'][0]['status'], 'FILLED')
        self.assertEqual(self.state.lease_token, token)
        self.assertEqual(engine.Lot.query.filter_by(user_id=self.user_id).count(), 1)
        evidence = json.loads(db.session.get(EventStrategyDecision, row.id).feature_json)
        self.assertEqual(evidence['existing_evidence'], 123)
        self.assertIn('quote_snapshot_id', evidence['portfolio_execution'])
        self.assertEqual(handoff.consume_event_decisions(self.user_id, quote_loader=loader)['processed'], [])
        loader.assert_called_once()

    def test_every_expired_or_rejected_decision_has_a_persisted_reason(self):
        stale = self.decision('KXBTC15M-STALE', age=121)
        expensive = self.decision('KXBTC15M-EXPENSIVE')
        result = handoff.consume_event_decisions(self.user_id, quote_loader=lambda user, decision: quote(
            decision.contract_symbol, yes_ask=.795, yes_bid=.79))
        statuses = {row['status'] for row in result['processed']}
        self.assertEqual(statuses, {'MISSED', 'REJECTED'})
        for row in (stale, expensive):
            self.assertTrue(handoff.disposition(db.session.get(EventStrategyDecision, row.id), self.state.generation)['reason'])
        self.assertEqual(engine.Lot.query.filter_by(user_id=self.user_id).count(), 0)

    def test_stop_during_quote_io_cannot_fill_or_mutate_stopped_ledger(self):
        self.decision()
        def loader(user, decision):
            self.cfg.enabled, self.cfg.worker_status = False, 'STOPPED'
            self.state.lease_token = self.state.lease_until = None
            db.session.commit()
            return quote(decision.contract_symbol)
        handoff.consume_event_decisions(self.user_id, quote_loader=loader)
        self.assertEqual(engine.Lot.query.filter_by(user_id=self.user_id).count(), 0)
        self.assertEqual(self.acc.cash_balance, 50000)

    def test_another_worker_filling_during_quote_io_cannot_duplicate_contract(self):
        self.decision()
        def loader(user, decision):
            cfg, acc, state = engine.locked(user)
            engine.enter_lot(cfg, acc, state, 'events', decision.contract_symbol,
                {'enter': True}, .4, datetime.utcnow(),
                details={'contract_symbol': decision.contract_symbol, 'outcome': 'YES'},
                key=f'events:{decision.contract_symbol}')
            db.session.commit()
            return quote(decision.contract_symbol)
        result = handoff.consume_event_decisions(self.user_id, quote_loader=loader)
        self.assertEqual(result['processed'][0]['status'], 'REJECTED')
        self.assertEqual(engine.Lot.query.filter_by(user_id=self.user_id).count(), 1)

    def test_scan_cannot_double_settle_lot_closed_in_another_session(self):
        from concurrent.futures import ThreadPoolExecutor
        self.decision()
        handoff.consume_event_decisions(self.user_id, quote_loader=lambda user, decision: quote(decision.contract_symbol))
        lot = engine.Lot.query.filter_by(user_id=self.user_id).one()
        lot_id = lot.id
        self.cfg.module_settings_json = json.dumps({module: {'enabled': False} for module in engine.MODULES})
        db.session.commit()
        def close_in_other_session():
            with self.app.app_context():
                try:
                    cfg, acc, state = engine.locked(self.user_id)
                    current = db.session.get(engine.Lot, lot_id)
                    engine.close_lot(acc, current, 1, 'SETTLEMENT', datetime.utcnow())
                    engine.balances(acc, state, self.user_id)
                    db.session.commit()
                finally:
                    db.session.remove()
        def mark(*args):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(close_in_other_session).result(timeout=10)
            return 1, 'SETTLEMENT'
        with patch.object(engine, 'mark_event', side_effect=mark):
            result = engine.run_scan(self.user_id, force=True)
        self.assertTrue(result['success'])
        self.assertEqual(engine.Order.query.filter_by(user_id=self.user_id, side='SELL').count(), 1)

    def test_scan_reloads_newer_event_mark_under_lock_instead_of_overwriting_it(self):
        from concurrent.futures import ThreadPoolExecutor
        self.decision()
        handoff.consume_event_decisions(self.user_id, quote_loader=lambda user, decision: quote(decision.contract_symbol))
        lot = engine.Lot.query.filter_by(user_id=self.user_id).one()
        lot_id = lot.id
        self.cfg.module_settings_json = json.dumps({module: {'enabled': False} for module in engine.MODULES})
        engine.trigger_pause(self.cfg, self.state, 'Hold new entries, continue marks')
        db.session.commit()
        original_mark = engine.mark_event
        calls = 0
        def newer_mark_in_other_session():
            with self.app.app_context():
                try:
                    cfg, acc, state = engine.locked(self.user_id)
                    current = db.session.get(engine.Lot, lot_id)
                    db.session.add(EventMarketSnapshot(user_id=self.user_id, contract_symbol='KXBTC15M-TEST',
                        received_at=datetime.utcnow(), yes_bid=.55, yes_ask=.56))
                    engine.mark_position(db.session.get(engine.Position, current.position_id), current, .55)
                    engine.balances(acc, state, self.user_id)
                    db.session.commit()
                finally:
                    db.session.remove()
        def mark(*args):
            nonlocal calls
            calls += 1
            answer = original_mark(*args)
            if calls == 1:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(newer_mark_in_other_session).result(timeout=10)
            return answer
        with patch.object(engine, 'mark_event', side_effect=mark):
            result = engine.run_scan(self.user_id, force=True)
        self.assertTrue(result['success'])
        self.assertEqual(calls, 2)
        self.assertEqual(db.session.get(engine.Position, lot.position_id).market_price, .55)
        self.assertIsNone(lot.closed_at)

    def test_reset_generation_during_quote_io_cannot_fill_new_generation(self):
        self.decision()
        def loader(user, decision):
            self.state.generation += 1
            db.session.commit()
            return quote(decision.contract_symbol)
        handoff.consume_event_decisions(self.user_id, quote_loader=loader)
        self.assertEqual(engine.Lot.query.filter_by(user_id=self.user_id).count(), 0)

    def test_kill_during_quote_io_holds_entry_without_clearing_slow_lease(self):
        self.decision()
        token = engine.claim(self.user_id, force=True)
        def loader(user, decision):
            engine.trigger_pause(self.cfg, self.state, 'Test risk pause')
            db.session.commit()
            return quote(decision.contract_symbol)
        result = handoff.consume_event_decisions(self.user_id, quote_loader=loader)
        self.assertEqual(result['processed'][0]['status'], 'HELD')
        self.assertEqual(self.state.lease_token, token)
        self.assertEqual(engine.Lot.query.filter_by(user_id=self.user_id).count(), 0)

    def test_settlements_continue_while_paused_but_explicit_stop_freezes(self):
        self.decision()
        handoff.consume_event_decisions(self.user_id, quote_loader=lambda user, decision: quote(decision.contract_symbol))
        lot = engine.Lot.query.filter_by(user_id=self.user_id).one()
        engine.trigger_pause(self.cfg, self.state, 'Paused entries')
        db.session.add(EventContractOutcome(user_id=self.user_id, contract_symbol='KXBTC15M-TEST',
            outcome='YES', settlement_status='RESOLVED'))
        self.cfg.enabled, self.cfg.worker_status = False, 'STOPPED'
        db.session.commit()
        handoff.consume_event_decisions(self.user_id)
        self.assertIsNone(lot.closed_at)
        self.cfg.worker_status = 'MONITORING_ONLY'
        db.session.commit()
        handoff.consume_event_decisions(self.user_id)
        self.assertIsNotNone(lot.closed_at)
        self.assertEqual(engine.Order.query.filter_by(user_id=self.user_id, side='SELL').count(), 1)
        handoff.consume_event_decisions(self.user_id)
        self.assertEqual(engine.Order.query.filter_by(user_id=self.user_id, side='SELL').count(), 1)

    def test_risk_circuit_manages_all_existing_positions_not_only_first(self):
        settings = engine.settings_for(self.cfg)
        settings = {module: {**values, 'enabled': module == 'crypto'} for module, values in settings.items()}
        self.cfg.module_settings_json = json.dumps(settings)
        lots = []
        for symbol in ('BTC', 'ETH'):
            lots.append(engine.enter_lot(self.cfg, self.acc, self.state, 'crypto', symbol,
                {'enter': True, 'side': 'LONG', 'stop': 95}, 100, datetime.utcnow()))
        self.cfg.enabled, self.cfg.worker_status = True, 'RUNNING'
        self.acc.cash_balance -= 6000
        db.session.commit()
        provider = MagicMock()
        provider.quote.return_value = 90
        provider.bars.side_effect = ValueError('History unavailable')
        result = engine.run_scan(self.user_id, force=True, provider=provider)
        self.assertTrue(result['success'], result)
        self.assertTrue(self.state.kill_switch)
        self.assertTrue(all(lot.closed_at is not None for lot in lots))
        self.assertEqual(engine.Order.query.filter_by(user_id=self.user_id, side='SELL').count(), 2)
        self.assertIsNone(self.state.lease_token)

    def test_readiness_distinguishes_no_data_and_no_signal(self):
        self.assertEqual(handoff.readiness(self.user_id, None, datetime.utcnow())[0], 'DATA_LIMITED')
        row = self.decision()
        cfg = db.session.get(EventStrategyConfig, row.config_id)
        self.assertEqual(handoff.readiness(self.user_id, cfg, datetime.utcnow())[0], 'READY')
        row.eligible, row.reason_codes = False, json.dumps(['EDGE_TOO_SMALL_AFTER_FEES'])
        db.session.commit()
        self.assertEqual(handoff.readiness(self.user_id, cfg, datetime.utcnow())[0], 'NO_SIGNAL')
        row.reason_codes = json.dumps(['MODEL_UNAVAILABLE'])
        db.session.commit()
        self.assertEqual(handoff.readiness(self.user_id, cfg, datetime.utcnow())[0], 'DATA_LIMITED')
        row.reason_codes = json.dumps(['AI_EVALUATION_DEFERRED'])
        db.session.commit()
        status, msg = handoff.readiness(self.user_id, cfg, datetime.utcnow())
        self.assertEqual(status, 'NO_SIGNAL')
        self.assertIn('deferred pending batch cadence', msg)
