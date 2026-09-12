"""Settlement during entry stops, using an ephemeral database and mocked quotes."""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from core.extensions import db
from credentials import User
from event_algo import event_algo_worker_loop, resolve_event_outcomes
from event_algo_models import (
    EventStrategyConfig, EventMarketSnapshot, EventContractOutcome,
    EventStrategyOrder, EventStrategyDecision,
)
from portfolio_algo_models import PortfolioStrategyPosition, PortfolioStrategyLot, PortfolioEngineState


class PausedEventSettlementTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True)
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        tables = [model.__table__ for model in (
            EventStrategyConfig, EventMarketSnapshot, EventContractOutcome,
            EventStrategyOrder, EventStrategyDecision, PortfolioStrategyPosition,
            PortfolioStrategyLot, PortfolioEngineState, User,
        )]
        db.metadata.create_all(db.engine, tables=tables)
        self.config = EventStrategyConfig(user_id=1, name='Paused test', enabled=False,
                                          mode='PAPER', kill_switch=True, worker_status='KILLED')
        db.session.add(self.config)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def test_killed_config_resolves_and_settles_once_without_crossing_users(self):
        now = datetime.utcnow()
        for user in (1, 2):
            db.session.add(EventMarketSnapshot(user_id=user, config_id=self.config.id,
                run_id=1, contract_symbol='TEST', cutoff_at=now-timedelta(minutes=5)))
            db.session.add(EventStrategyOrder(user_id=user, config_id=self.config.id,
                contract_symbol='TEST', outcome='YES', side='BUY', quantity=2,
                status='SIMULATED_FILLED', filled_quantity=2, filled_price=.4, fee=.03))
        db.session.commit()
        credential = SimpleNamespace(webull_app_key='test', webull_app_secret='test', webull_access_token='test')
        with patch('event_algo._webull_connection_for_user', return_value=(credential, 'test')), \
                patch('services.webull_service.get_webull_event_market', return_value={'settled_outcome': 'YES'}) as quote:
            result = resolve_event_outcomes(1, config=self.config)
            repeat = resolve_event_outcomes(1, config=self.config, force=True)
        self.assertEqual(result['resolved_count'], 1)
        self.assertEqual(repeat['resolved_count'], 0)
        quote.assert_called_once()
        settled = EventStrategyOrder.query.filter_by(user_id=1).one()
        self.assertEqual(settled.status, 'SIMULATED_SETTLED')
        self.assertAlmostEqual(settled.realized_pnl, 1.17)
        self.assertEqual(EventStrategyOrder.query.filter_by(user_id=2).one().status, 'SIMULATED_FILLED')
        self.assertEqual(EventContractOutcome.query.count(), 1)
        self.assertTrue(self.config.kill_switch)
        self.assertFalse(self.config.enabled)

    def test_worker_resolves_stopped_killed_and_master_paused_configs_without_scanning(self):
        # Exercise the actual supervisor query and gating, one iteration each.
        for enabled, killed, master_killed in [(False, False, False), (True, True, False),
                                               (False, True, True), (True, False, True)]:
            with self.subTest(enabled=enabled, killed=killed, master_killed=master_killed):
                self.config = db.session.get(EventStrategyConfig, self.config.id)
                self.config.enabled, self.config.kill_switch = enabled, killed
                db.session.merge(PortfolioEngineState(user_id=1, kill_switch=master_killed))
                db.session.commit()
                stop = Mock()
                stop.is_set.side_effect = [False, True]
                with patch('event_algo.is_event_strategy_admin', return_value=True), \
                        patch('event_algo.resolve_event_outcomes', return_value={'resolved_count': 0}) as resolve, \
                        patch('event_algo.run_event_strategy_scan') as scan, \
                        patch('event_algo.generate_event_strategy_report') as report:
                    event_algo_worker_loop(self.app, stop)
                resolve.assert_called_once()
                scan.assert_not_called()
                report.assert_not_called()
                stop.wait.assert_called_once_with(15)

    def test_resolution_still_rejects_live_mode(self):
        self.config.mode = 'LIVE'
        with patch('event_algo._webull_connection_for_user') as connection:
            self.assertFalse(resolve_event_outcomes(1, config=self.config)['success'])
        connection.assert_not_called()

    def test_empty_paused_config_needs_no_provider_credentials(self):
        with patch('event_algo._webull_connection_for_user') as connection:
            self.assertEqual(resolve_event_outcomes(1, config=self.config)['resolved_count'], 0)
        connection.assert_not_called()

    def test_worker_preserves_account_ownership_gate(self):
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        with patch('event_algo.is_event_strategy_admin', return_value=False), \
                patch('event_algo.resolve_event_outcomes') as resolve:
            event_algo_worker_loop(self.app, stop)
        resolve.assert_not_called()
