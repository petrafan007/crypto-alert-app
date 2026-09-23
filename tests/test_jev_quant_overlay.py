import copy
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from core.extensions import db
from credentials import UserSetting
from models import JevEvaluation
from services import portfolio_engine as engine
from services.jev_quant_overlay import build_quant_state, queue_shadow
from services.jev_evaluations import process_pending, process_evaluation, get_evaluation
from services.jev_contracts import build_crypto_quant_questions
from tests.jev_helpers import JevTestCase, response_for


class JevQuantTests(JevTestCase):
    def test_false_entry_and_immutable_snapshot(self):
        signal = {'enter': False, 'exit': False, 'checks': {'atr': 3}, 'stop': 90}
        state = build_quant_state('BTC', 100, signal, self.now)
        signal['checks']['atr'] = 999
        self.assertEqual(state['base_signal']['checks']['atr'], 3)
        evaluation_id = queue_shadow(1, state, self.config, {'baseline_action': 'NO_ENTRY'})
        with patch('services.jev_service.requests.post', return_value=Mock(status_code=200, json=lambda: response_for(build_crypto_quant_questions()))):
            row = process_evaluation(evaluation_id)
        self.assertEqual(row.action_taken, 'shadow')
        self.assertFalse(json.loads(row.state_json)['base_signal']['enter'])
        self.assertEqual(json.loads(row.counterfactual_json)['baseline_action'], 'NO_ENTRY')

    def configure_portfolio(self, user_id, *, shadow, kill=False):
        if user_id != 1:
            db.session.add(UserSetting(user_id=user_id, jev_enabled=True, jev_quant_shadow_enabled=shadow))
        else:
            db.session.get(UserSetting, user_id).jev_quant_shadow_enabled = shadow
        cfg, acc, state = engine.ensure_portfolio(user_id)
        values = engine.settings_for(cfg)
        for module in values:
            values[module]['enabled'] = module == 'crypto'
        cfg.module_settings_json = json.dumps(values)
        cfg.watchlists_json = json.dumps({'crypto': ['BTC']})
        cfg.enabled = True
        state.kill_switch = kill
        db.session.commit()
        return cfg, acc, state

    def market(self):
        data = Mock()
        data.quote.return_value = 110
        data.bars.return_value = [{'time': (self.now-timedelta(hours=200-i)).timestamp(), 'high': 101,
                                  'low': 99, 'close': 100, 'volume': 1000} for i in range(150)]
        data.dominance_ok.return_value = True
        return data

    def test_shadow_and_off_execute_identical_paper_entries_without_network(self):
        accounts = [self.configure_portfolio(1, shadow=True), self.configure_portfolio(2, shadow=False)]
        with patch('services.jev_service.requests.post') as post:
            enabled = engine.run_scan(1, force=True, provider=self.market())
            baseline = engine.run_scan(2, force=True, provider=self.market())
            post.assert_not_called()
        self.assertTrue(enabled['success'], enabled)
        self.assertEqual(enabled['modules']['crypto']['entries'], 1, enabled)
        self.assertEqual(baseline['modules']['crypto']['entries'], 1, baseline)
        actual_lot = engine.current_lots(1, accounts[0][2])[0]
        baseline_lot = engine.current_lots(2, accounts[1][2])[0]
        actual_position = db.session.get(engine.Position, actual_lot.position_id)
        baseline_position = db.session.get(engine.Position, baseline_lot.position_id)
        self.assertEqual(actual_position.quantity, baseline_position.quantity)
        self.assertEqual(actual_lot.collateral, baseline_lot.collateral)
        self.assertEqual(accounts[0][1].cash_balance, accounts[1][1].cash_balance)
        rows = JevEvaluation.query.all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0].counterfactual_json)['baseline_action'], 'ENTER')

    def test_shadow_preserves_kill_switch(self):
        self.configure_portfolio(1, shadow=True, kill=True)
        with patch('services.jev_service.requests.post') as post:
            result = engine.run_scan(1, force=True, provider=self.market())
            post.assert_not_called()
        self.assertEqual(result['modules']['crypto']['entries'], 0)
        self.assertEqual(result['modules']['crypto']['qualified_signals'], 1)

    def test_shadow_storage_failure_cannot_rollback_trade(self):
        self.configure_portfolio(1, shadow=True)
        with patch('services.jev_quant_overlay.create_evaluation', side_effect=RuntimeError('storage failed')):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertEqual(result['modules']['crypto']['entries'], 1)

    def test_worker_releases_transaction_before_http_and_claims_once(self):
        state = build_quant_state('BTC', 100, {'enter': False}, self.now)
        evaluation_id = queue_shadow(1, state, self.config, {})
        from sqlalchemy import event
        transactions = set()
        def began(conn): transactions.add(id(conn))
        def ended(conn): transactions.discard(id(conn))
        event.listen(db.engine, 'begin', began)
        event.listen(db.engine, 'commit', ended)
        event.listen(db.engine, 'rollback', ended)
        def http(*args, **kwargs):
            self.assertFalse(transactions, 'Provider called during an open database transaction')
            return Mock(status_code=200, json=lambda: response_for(build_crypto_quant_questions()))
        try:
            with patch('services.jev_service.requests.post', side_effect=http) as post:
                process_pending()
                process_pending()
                self.assertEqual(post.call_count, 1)
        finally:
            event.remove(db.engine, 'begin', began)
            event.remove(db.engine, 'commit', ended)
            event.remove(db.engine, 'rollback', ended)
        self.assertEqual(get_evaluation(evaluation_id).status, 'success')
