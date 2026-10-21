import json
from datetime import timedelta
from unittest.mock import Mock, patch
from core.extensions import db
from credentials import UserSetting
from models import JevEvaluation
from services import portfolio_engine as engine
from services.decision_contracts import build_crypto_quant_questions
from services.decision_evaluations import process_pending, process_evaluation, get_evaluation
from tests.decision_helpers import DecisionTestCase, noul_payload, response_for


class DecisionQuantTests(DecisionTestCase):
    def quant_payload(self, probability):
        """A crypto-quant provider payload whose entry answer is `probability`."""
        questions = build_crypto_quant_questions()
        payload = noul_payload(questions)
        payload['answers']['confirm_entry'] = {'type': 'noul', 'noul': probability}
        return payload

    def configure_portfolio(self, user_id, *, enabled, kill=False):
        if user_id != 1:
            db.session.add(UserSetting(user_id=user_id, decision_enabled=True, decision_quant_enabled=enabled))
        else:
            row = db.session.get(UserSetting, user_id)
            row.decision_enabled = True
            row.decision_quant_enabled = enabled
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

    def test_confirm_allows_the_entry_and_records_the_verdict(self):
        self.configure_portfolio(1, enabled=True)
        with patch('services.decision_engine.requests.post',
                   return_value=Mock(status_code=200, json=lambda: self.quant_payload(.95))):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertTrue(result['success'], result)
        self.assertEqual(result['modules']['crypto']['entries'], 1, result)
        row = JevEvaluation.query.filter_by(use_case='quant_crypto').one()
        self.assertEqual(row.action_taken, 'confirm')
        self.assertEqual(row.result_state, 'CONFIRM')
        self.assertEqual(row.status, 'success')

    def test_block_rejects_the_entry_and_records_the_reason(self):
        self.configure_portfolio(1, enabled=True)
        with patch('services.decision_engine.requests.post',
                   return_value=Mock(status_code=200, json=lambda: self.quant_payload(.05))):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertTrue(result['success'], result)
        self.assertEqual(result['modules']['crypto']['entries'], 0, result)
        self.assertEqual(result['modules']['crypto']['qualified_signals'], 1, result)
        rejected = result['modules']['crypto']['rejected_entries']
        self.assertEqual(len(rejected), 1)
        self.assertIn('rejected the setup', rejected[0]['reason'])
        row = JevEvaluation.query.filter_by(use_case='quant_crypto').one()
        self.assertEqual(row.action_taken, 'block')
        self.assertEqual(row.result_state, 'BLOCK')

    def test_abstain_never_blocks_the_entry(self):
        # An undecided engine must not be able to silence a module: the
        # deterministic signal alone decides the entry.
        self.configure_portfolio(1, enabled=True)
        with patch('services.decision_engine.requests.post',
                   return_value=Mock(status_code=200, json=lambda: self.quant_payload(.5))):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertTrue(result['success'], result)
        self.assertEqual(result['modules']['crypto']['entries'], 1, result)
        row = JevEvaluation.query.filter_by(use_case='quant_crypto').one()
        self.assertEqual(row.result_state, 'ABSTAIN')

    def test_disabled_decision_engine_leaves_the_entry_untouched(self):
        self.configure_portfolio(1, enabled=False)
        with patch('services.decision_engine.requests.post') as post:
            result = engine.run_scan(1, force=True, provider=self.market())
            post.assert_not_called()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['modules']['crypto']['entries'], 1, result)
        self.assertEqual(JevEvaluation.query.filter_by(use_case='quant_crypto').count(), 0)

    def test_provider_failure_cannot_suppress_a_deterministic_entry(self):
        # A decision outage must never block a paper entry.
        self.configure_portfolio(1, enabled=True)
        with patch('services.decision_engine.requests.post', return_value=Mock(status_code=401)):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertTrue(result['success'], result)
        self.assertEqual(result['modules']['crypto']['entries'], 1, result)
        row = JevEvaluation.query.filter_by(use_case='quant_crypto').one()
        self.assertEqual(row.status, 'error')

    def test_an_exception_in_the_decision_call_cannot_suppress_an_entry(self):
        self.configure_portfolio(1, enabled=True)
        with patch('services.decision_quant.evaluate_entry', side_effect=RuntimeError('provider exploded')):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertTrue(result['success'], result)
        self.assertEqual(result['modules']['crypto']['entries'], 1, result)

    def test_decision_engine_preserves_kill_switch(self):
        self.configure_portfolio(1, enabled=True, kill=True)
        with patch('services.decision_engine.requests.post') as post:
            result = engine.run_scan(1, force=True, provider=self.market())
            post.assert_not_called()
        self.assertEqual(result['modules']['crypto']['entries'], 0)
        self.assertEqual(result['modules']['crypto']['qualified_signals'], 1)

    def test_decision_engine_is_not_consulted_for_other_modules(self):
        # Only the crypto module is gated; the other modules keep their own rules.
        self.configure_portfolio(1, enabled=True)
        values = engine.settings_for(engine.Config.query.filter_by(user_id=1, name='Default Multi-Asset Portfolio').one())
        for module in values:
            values[module]['enabled'] = module in ('crypto', 'equities')
        cfg = engine.Config.query.filter_by(user_id=1, name='Default Multi-Asset Portfolio').one()
        cfg.module_settings_json = json.dumps(values)
        cfg.watchlists_json = json.dumps({'crypto': ['BTC'], 'equities': ['AAPL']})
        db.session.commit()
        with patch('services.decision_engine.requests.post',
                   return_value=Mock(status_code=200, json=lambda: self.quant_payload(.95))) as post:
            engine.run_scan(1, force=True, provider=self.market())
        symbols = {row.symbol for row in JevEvaluation.query.filter_by(use_case='quant_crypto').all()}
        self.assertEqual(symbols, {'BTC'})

    def test_worker_releases_transaction_before_http_and_claims_once(self):
        from services.decision_evaluations import create_evaluation
        state = {'symbol': 'BTC', 'instrument_type': 'CRYPTO', 'market_source': 'webull',
                 'current_price': 100, 'forecast_horizon_hours': 24, 'decision_time': self.now.isoformat(),
                 'outcome_contract': 'return-v1: downside <=-2%'}
        evaluation_id = create_evaluation(1, 'quant_crypto', state, self.config)
        from sqlalchemy import event
        transactions = set()
        def began(conn): transactions.add(id(conn))
        def ended(conn): transactions.discard(id(conn))
        event.listen(db.engine, 'begin', began)
        event.listen(db.engine, 'commit', ended)
        event.listen(db.engine, 'rollback', ended)
        def http(*args, **kwargs):
            self.assertFalse(transactions, 'Provider called during an open database transaction')
            return Mock(status_code=200, json=lambda: self.quant_payload(.95))
        try:
            with patch('services.decision_engine.requests.post', side_effect=http) as post:
                process_pending()
                process_pending()
                self.assertEqual(post.call_count, 1)
        finally:
            event.remove(db.engine, 'begin', began)
            event.remove(db.engine, 'commit', ended)
            event.remove(db.engine, 'rollback', ended)
        self.assertEqual(get_evaluation(evaluation_id).status, 'success')
