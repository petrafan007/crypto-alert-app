"""Audit ownership and provider queues; PostgreSQL tests use an isolated URI."""
import json
import os
import threading
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from flask import Flask
from sqlalchemy import text
from sqlalchemy.schema import CreateSchema

from core.extensions import db
from portfolio_algo_models import PortfolioAudit as Audit, PortfolioEngineState as State, PortfolioEngineLog as Log
from services import portfolio_audit_lifecycle as lifecycle, provider_resilience as resilience


class AuditExpirationTests(unittest.TestCase):
    def test_total_deadline_is_not_renewed_by_progress_and_invalid_progress_is_not_fresh(self):
        created = datetime(2026, 9, 13, 12)
        row = SimpleNamespace(created_at=created, evidence_json='{}')
        with patch.object(lifecycle, 'max_duration_seconds', return_value=3600), \
                patch('services.ai_service.audit_provider_timeout_seconds', return_value=600):
            self.assertIsNone(lifecycle.expiration_reason(row, created+timedelta(seconds=899)))
            self.assertIn('stopped reporting', lifecycle.expiration_reason(row, created+timedelta(seconds=900)))
            row.evidence_json = json.dumps({'audit_progress_at': (created+timedelta(seconds=3599)).isoformat()})
            self.assertIn('total duration', lifecycle.expiration_reason(row, created+timedelta(hours=1)))
            for progress in ('invalid', '2027-01-01', None, ['bad'], '2026-09-12'):
                row.evidence_json = json.dumps({'audit_progress_at': progress})
                self.assertIn('stopped reporting', lifecycle.expiration_reason(row, created+timedelta(seconds=900)))
            self.assertIn('future', lifecycle.expiration_reason(row, created-timedelta(seconds=1)))

    def test_duration_configuration_is_finite_and_bounded(self):
        for value, expected in (('NaN', 3600), ('inf', 3600), ('bad', 3600), ('1', 900), ('999999', 10800)):
            with patch.dict(os.environ, AI_AUDIT_MAX_DURATION_SECONDS=value):
                self.assertEqual(lifecycle.max_duration_seconds(), expected)

    def test_memory_queue_times_out_cancels_and_preserves_host_vs_user_scope(self):
        held, release = threading.Event(), threading.Event()
        def holder():
            with resilience.serialized_ai_request('queue-test-alice', 'ollama'):
                held.set()
                release.wait(3)
        thread = threading.Thread(target=holder)
        thread.start()
        try:
            self.assertTrue(held.wait(2))
            with self.assertRaises(resilience.AIRequestDeferred):
                with resilience.serialized_ai_request('queue-test-bob', 'ollama', wait_timeout=.01):
                    self.fail('Concurrent host-wide Ollama request')
            with self.assertRaises(resilience.AuditCancelled):
                with resilience.serialized_ai_request('queue-test-bob', 'ollama', request_guard=Mock(
                        side_effect=resilience.AuditCancelled('expired'))):
                    self.fail('Cancelled request admitted')
            with resilience.serialized_ai_request('queue-test-bob', 'gemini', wait_timeout=0):
                pass
        finally:
            release.set()
            thread.join(3)
        with resilience.serialized_ai_request('queue-test-bob', 'ollama', wait_timeout=0):
            pass


class AuditLifecycleDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_AUDIT_TEST_DATABASE_URI', 'sqlite://')
        schema = 'audit_test_'+uuid4().hex
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'options': '-csearch_path='+schema}}
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine, tables=[Audit.__table__, State.__table__, Log.__table__])
        db.session.add_all([State(user_id=1, generation=2), State(user_id=2, generation=1)])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def audit(self, *, user_id=1, generation=2, age=0, evidence='{}'):
        row = Audit(user_id=user_id, generation=generation, created_at=datetime.utcnow()-timedelta(seconds=age),
                    evidence_json=evidence, status='PENDING')
        db.session.add(row)
        db.session.commit()
        return row.id

    def test_active_exclusivity_requires_current_generation_and_deadline(self):
        self.audit(generation=1)
        self.audit(age=7200)
        other = self.audit(user_id=2, generation=1)
        self.assertIsNone(lifecycle.active_audit(1))
        self.assertEqual(lifecycle.active_audit(2).id, other)
        current = self.audit()
        self.assertEqual(lifecycle.active_audit(1).id, current)

    def test_recovery_runs_without_new_audit_requests_and_preserves_evidence_once(self):
        expired = self.audit(age=7200, evidence=json.dumps({'module_audits': {'events': 'Completed evidence'}}))
        old_generation = self.audit(generation=1)
        malformed = self.audit(age=7200, evidence='broken JSON')
        current = self.audit()
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        lifecycle.audit_recovery_loop(self.app, stop)
        db.session.expire_all()
        for audit_id in (expired, old_generation, malformed):
            self.assertEqual(db.session.get(Audit, audit_id).status, 'FAILED')
        self.assertEqual(db.session.get(Audit, current).status, 'PENDING')
        self.assertEqual(json.loads(db.session.get(Audit, expired).evidence_json)['module_audits']['events'], 'Completed evidence')
        self.assertEqual(json.loads(db.session.get(Audit, malformed).evidence_json)['unparsed_prior_evidence'], 'broken JSON')
        self.assertEqual(lifecycle.recover_stale_audits(), [])
        self.assertEqual(Log.query.filter_by(event_type='AUDIT_RECOVERED').count(), 3)
        stop.wait.assert_called_once_with(30)

    def test_read_guard_sees_external_cancellation_and_final_write_is_fenced(self):
        audit_id = self.audit()
        cached = db.session.get(Audit, audit_id)
        db.session.commit()
        lifecycle.check_pending_audit(audit_id)
        with db.engine.begin() as connection:
            connection.execute(Audit.__table__.update().where(Audit.id == audit_id).values(status='FAILED', content='Recovered'))
        with self.assertRaises(resilience.AuditCancelled):
            lifecycle.check_pending_audit(audit_id)
        with self.assertRaises(resilience.AuditCancelled):
            lifecycle.require_pending_audit(audit_id)
        self.assertEqual(db.session.get(Audit, audit_id).content, 'Recovered')

    def test_read_guard_rejects_expired_generation_missing_and_deleted_identity(self):
        for audit_id in (self.audit(age=7200), self.audit(generation=1), self.audit(user_id=3), 999999):
            with self.assertRaises(resilience.AuditCancelled):
                lifecycle.check_pending_audit(audit_id)

    def test_postgres_queue_timeout_does_not_release_another_owner_lock(self):
        if db.engine.dialect.name != 'postgresql':
            self.skipTest('Requires isolated PostgreSQL')
        lock_id = int(resilience.identity('ai-request-slot', 'host:ollama')[:15], 16)
        with db.engine.connect() as holder:
            holder.execute(text('SELECT pg_advisory_lock(:key)'), {'key': lock_id})
            holder.commit()
            try:
                with self.assertRaises(resilience.AIRequestDeferred):
                    with resilience.serialized_ai_request('test', 'ollama', wait_timeout=.02):
                        self.fail('Lock was not exclusive')
                guard = Mock(side_effect=[None, resilience.AuditCancelled('recovered while queued')])
                with self.assertRaises(resilience.AuditCancelled):
                    with resilience.serialized_ai_request('test', 'ollama', request_guard=guard):
                        self.fail('Cancelled request admitted')
            finally:
                self.assertTrue(holder.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': lock_id}).scalar())
                holder.commit()
        with resilience.serialized_ai_request('test', 'ollama', wait_timeout=0):
            pass
        self.assertEqual(db.engine.pool.checkedout(), 0)

    def test_postgres_recovery_skips_locked_rows_and_retries_later(self):
        if db.engine.dialect.name != 'postgresql':
            self.skipTest('Requires isolated PostgreSQL')
        audit_id = self.audit(age=7200)
        db.session.rollback()
        with db.engine.connect() as holder:
            holder.execute(text('SELECT id FROM portfolio_strategy_audits WHERE id=:id FOR UPDATE'), {'id': audit_id})
            self.assertEqual(lifecycle.recover_stale_audits(), [])
            holder.rollback()
        self.assertEqual(lifecycle.recover_stale_audits(), [audit_id])
