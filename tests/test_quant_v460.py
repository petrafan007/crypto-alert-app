"""Focused v4.6.0 paper reporting and daily strategy adjustment regressions."""
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from credentials import User
from portfolio_algo_models import (
    PortfolioAIReview as Review, PortfolioAudit as Audit, PortfolioEngineState as State,
    PortfolioStrategyAccount as Account,
    PortfolioSignalDecision as Decision, PortfolioStrategyConfig as Config,
    PortfolioStrategyLot as Lot, PortfolioStrategyPosition as Position,
    PortfolioStrategyRevision as Revision,
)
from services import portfolio_engine as engine
from services import portfolio_strategy_review as strategy_review


class Quant460Tests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True)
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in (
            User, Config, Account, State, Position, Lot, Decision, Revision, Review, Audit)])
        db.session.add(User(id=1, username='quant-test', pwd_hash='test'))
        db.session.add(Config(user_id=1, enabled=True, mode='PAPER',
                              master_ai_config=json.dumps({'daily_strategy_requests': 3})))
        db.session.add(State(user_id=1, generation=1))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def decision(self, *, action='ENTER', disposition='REJECTED', reason='Risk amount $35.00'):
        row = Decision(user_id=1, generation=1, module='crypto', symbol='BTC',
                       evaluated_at=datetime.utcnow(), snapshot_sha256='a'*64,
                       strategy_version='baseline', code_sha256='b'*64,
                       setup='DONCHIAN_V1', proposed_action=action,
                       disposition=disposition, reason=reason, checks_json='{}')
        db.session.add(row)
        db.session.commit()
        return row

    def test_portfolio_loss_does_not_halt_but_manual_kill_still_does(self):
        cfg = Config.query.filter_by(user_id=1).one()
        acc = Account(user_id=1, initial_balance=50000, total_equity=44000, cash_balance=44000)
        db.session.add(acc)
        state = db.session.get(State, 1)
        db.session.commit()
        self.assertFalse(engine.check_circuit(cfg, acc, state))
        self.assertFalse(state.kill_switch)
        state.kill_switch = True
        state.pause_reason = 'Administrator activated the portfolio kill switch.'
        db.session.commit()
        self.assertTrue(engine.check_circuit(cfg, acc, state))
        engine.ensure_portfolio(1)
        self.assertTrue(state.kill_switch)

    def test_report_change_detection_ignores_repeated_numeric_noise_but_sees_fill(self):
        self.decision()
        first = engine.scheduled_material_signature(1, 1, datetime.utcnow())
        self.decision(reason='Risk amount $42.50')
        self.assertEqual(first, engine.scheduled_material_signature(1, 1, datetime.utcnow()))
        self.decision(disposition='FILLED', reason='Paper fill')
        self.assertNotEqual(first, engine.scheduled_material_signature(1, 1, datetime.utcnow()))

    def test_scheduled_no_change_and_stale_worker_make_zero_ai_calls(self):
        state = db.session.get(State, 1)
        state.last_scan_at = datetime.utcnow()
        modules = engine.scheduled_material_fingerprints(1, 1)
        signature = engine.scheduled_material_signature(1, 1, datetime.utcnow())
        previous = Audit(user_id=1, generation=1, status='SUCCESS',
                         evidence_json=json.dumps({'material_signature': signature,
                             'material_module_signatures': modules}))
        pending = Audit(user_id=1, generation=1, status='PENDING')
        db.session.add_all([previous, pending])
        db.session.commit()
        with patch.object(engine, 'portfolio_status', side_effect=AssertionError('AI evidence should be skipped')):
            result = engine.run_audit(1, scheduled=True, audit_id=pending.id)
        self.assertEqual(result['status'], 'NO_CHANGE')
        self.assertTrue(result['evidence']['ai_requests_skipped'])
        state.last_scan_at = datetime.utcnow() - timedelta(minutes=16)
        stale = Audit(user_id=1, generation=1, status='PENDING')
        db.session.add(stale)
        db.session.commit()
        with patch.object(engine, 'portfolio_status', side_effect=AssertionError('Stale worker should skip AI')):
            result = engine.run_audit(1, scheduled=True, audit_id=stale.id)
        self.assertEqual(result['status'], 'DATA_STALE')
        self.assertTrue(result['evidence']['ai_requests_skipped'])

    def test_failed_daily_ai_review_retries_same_day_with_saved_ceiling(self):
        payload = {'modules': {}, 'active_sources': {}, 'daily_request_limit': 3}
        def failed(**kwargs):
            kwargs['attempt_observer'](event='started')
            raise RuntimeError('temporary provider failure')
        successful = SimpleNamespace(text='{"module":null,"source":null,"reason":"No revision justified"}',
                                     provider='test', model='test')
        with patch.object(strategy_review, 'assess_active_experiments'), \
             patch.object(strategy_review, 'promote_mature_shadows'), \
             patch.object(strategy_review, 'evidence', return_value=payload), \
             patch('services.ai_service.is_ai_enabled', return_value=True), \
             patch('services.portfolio_engine.audit_ai_kwargs', return_value={}), \
             patch('services.ai_service.call_ai_with_web_search', side_effect=failed) as provider:
            first = strategy_review.review_user(1)
            self.assertEqual(first.status, 'FAILED')
            self.assertEqual(first.request_count, 1)
            first.completed_at = datetime.utcnow() - timedelta(minutes=16)
            db.session.commit()
            def succeed(**kwargs):
                kwargs['attempt_observer'](event='started')
                return successful, None
            provider.side_effect = succeed
            second = strategy_review.review_user(1)
        self.assertEqual(second.status, 'NO_CHANGE')
        self.assertEqual(second.request_count, 2)
        self.assertEqual(Review.query.filter_by(user_id=1).count(), 1)

    def test_bad_paper_experiment_restores_prior_rule_without_halting_engine(self):
        activated = datetime.utcnow() - timedelta(days=1)
        revision = Revision(user_id=1, module='crypto', parent_sha256='a'*64,
                            candidate_sha256='b'*64, source_json='{}', evidence_sha256='c'*64,
                            status='ACTIVE', activated_at=activated,
                            validation_json=json.dumps({'mode': 'PAPER_EXPERIMENT'}))
        db.session.add(revision)
        for index in range(5):
            position = Position(user_id=1, symbol=f'SYMBOL{index}', instrument_type='CRYPTO', quantity=0)
            db.session.add(position)
            db.session.flush()
            db.session.add(Lot(user_id=1, position_id=position.id, generation=1,
                module='crypto', signal_key=f'experiment-{index}', collateral=1,
                realized_pnl=-1, opened_at=activated + timedelta(minutes=1),
                closed_at=activated + timedelta(hours=index+1),
                details_json=json.dumps({'code_sha256': 'b'*64})))
        db.session.commit()
        with patch.object(strategy_review, 'request', return_value={'status': 'ROLLED_BACK'}) as service:
            strategy_review.assess_active_experiments(1)
        self.assertEqual(revision.status, 'ROLLED_BACK')
        service.assert_called_once_with('rollback', module='crypto', expected_sha256='b'*64)
        self.assertFalse(db.session.get(State, 1).kill_switch)

    def test_next_day_paper_candidate_activates_after_forward_decision(self):
        created = datetime.utcnow() - timedelta(days=2)
        revision = Revision(user_id=1, module='crypto', parent_sha256='a'*64,
                            candidate_sha256='b'*64, source_json='{}', evidence_sha256='c'*64,
                            status='SHADOW', created_at=created)
        db.session.add(revision)
        self.decision(action='NO_TRADE', disposition='NO_TRADE', reason='Baseline passed')
        def service(op, **kwargs):
            if op == 'evaluate_candidate':
                return {'enter': True}
            if op == 'activate':
                self.assertEqual(kwargs['gates']['mode'], 'PAPER_EXPERIMENT')
                self.assertEqual(kwargs['gates']['sampled_decisions'], 1)
                return {'status': 'ACTIVE'}
            raise AssertionError(op)
        with patch.object(strategy_review, 'request', side_effect=service):
            strategy_review.promote_mature_shadows(1, Config.query.filter_by(user_id=1).one())
        self.assertEqual(revision.status, 'ACTIVE')
        self.assertIsNotNone(revision.activated_at)
        self.assertEqual(json.loads(revision.validation_json)['new_unobserved_entries'], 1)


if __name__ == '__main__':
    unittest.main()
