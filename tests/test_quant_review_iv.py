"""Regression tests for the v4.14.0 review loop and IV job reliability fixes.

Covers:
  - the daily strategy AI ceiling defaults to three and accepts one through six
  - review evidence links each decision to the realized P&L of the lot it opened
  - a failed daily IV job gets exactly one bounded retry
  - missed close windows with captured quotes are caught up automatically
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from credentials import User
from research_data_models import ResearchJob, ResearchCapture, ResearchCollectionConfig
from portfolio_algo_models import (
    DEFAULT_ALLOCATIONS, DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS,
    PortfolioSignalDecision, PortfolioStrategyConfig, PortfolioStrategyLot,
    PortfolioStrategyPosition,
)
from event_algo_models import EventStrategyConfig
import services.portfolio_engine as engine
import services.portfolio_strategy_review as review
import services.research_jobs as jobs

WINDOW = {'start': '2026-11-06T20:40:00+00:00', 'end': '2026-11-06T21:00:00+00:00'}


class ReviewBudgetTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(total_bankroll=50000, module_settings_json='{}',
                               allocations_json=json.dumps(DEFAULT_ALLOCATIONS),
                               watchlists_json=json.dumps(DEFAULT_QUANT_WATCHLISTS),
                               master_ai_config='{}')

    def test_the_ceiling_accepts_one_through_six(self):
        for value in (1, 3, 6):
            result = engine.validate_config({'master_ai_config': {'daily_strategy_requests': value}}, self.config())
            self.assertEqual(json.loads(result['master_ai_config'])['daily_strategy_requests'], value)
        for value in (0, 7, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                engine.validate_config({'master_ai_config': {'daily_strategy_requests': value}}, self.config())

    def test_the_default_ceiling_is_three(self):
        self.assertEqual(review.MAX_DAILY_AI_REQUESTS, 3)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test', TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.metadata.create_all(db.engine, tables=[m.__table__ for m in (
            User, ResearchCollectionConfig, ResearchCapture, ResearchJob,
            PortfolioStrategyConfig, PortfolioStrategyPosition, PortfolioStrategyLot,
            PortfolioSignalDecision, EventStrategyConfig)])
        db.session.add(User(id=1, username='admin', pwd_hash='test'))
        self.cfg = PortfolioStrategyConfig(user_id=1)
        db.session.add(self.cfg)
        db.session.add(ResearchCollectionConfig(user_id=1, enabled=True, stored_bytes=0, settings_json='{}'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def capture(self, at):
        db.session.add(ResearchCapture(user_id=1, lane='options', source='WEBULL_PRODUCTION',
            kind='option_quotes', symbol='SPY', started_at=at, received_at=at,
            sha256='0' * 64, compressed_bytes=1, raw_bytes=1, payload_gzip=b'', metadata_json='{}'))
        db.session.commit()

    def iv_job(self, status, request=None, completed_at=None, config=None):
        row = ResearchJob(user_id=1, kind='daily_iv', status=status,
            request_json=json.dumps({'request': request or WINDOW,
                                     'config': config or {'settings': {'options': {'target_dte': DEFAULT_MODULE_SETTINGS['options']['target_dte']}}}}),
            created_at=datetime.utcnow() - timedelta(hours=1), completed_at=completed_at,
            message='Worker interrupted or six-minute deadline exceeded; submit a new job.')
        db.session.add(row)
        db.session.commit()
        return row


class EvidenceLinkageTests(DatabaseTestCase):
    def lot(self, symbol, pnl, closed_at):
        position = PortfolioStrategyPosition(user_id=1, symbol=symbol, instrument_type='CRYPTO')
        db.session.add(position)
        db.session.flush()
        lot = PortfolioStrategyLot(user_id=1, position_id=position.id, generation=1, module='crypto',
            signal_key=f'crypto:{symbol}:test', collateral=100, realized_pnl=pnl,
            opened_at=datetime.utcnow() - timedelta(days=2), closed_at=closed_at)
        db.session.add(lot)
        db.session.commit()
        return lot

    def decision(self, symbol, lot=None):
        row = PortfolioSignalDecision(user_id=1, generation=1, module='crypto', symbol=symbol,
            snapshot_sha256='0' * 64, strategy_version='test', code_sha256='0' * 64,
            proposed_action='ENTER', disposition='FILLED', reason='test', checks_json='{}',
            lot_id=lot.id if lot else None)
        db.session.add(row)
        db.session.commit()
        return row

    def evidence(self):
        with patch.object(review, 'request', return_value={'sha256': '0' * 64, 'source': 'def decide(f): pass'}):
            return review.evidence(1, self.cfg)

    def test_decisions_carry_the_realized_pnl_of_the_lot_they_opened(self):
        closed_at = datetime.utcnow() - timedelta(days=1)
        winner = self.lot('WIN', 12.346, closed_at)
        open_lot = self.lot('OPEN', 0.0, None)
        self.decision('WIN', winner)
        self.decision('OPEN', open_lot)
        self.decision('NOLOT')
        payload = self.evidence()
        rows = {row['symbol']: row for row in payload['recent_decisions']}
        self.assertEqual(rows['WIN']['lot_id'], winner.id)
        self.assertEqual(rows['WIN']['realized_pnl_usd'], 12.35)
        self.assertIsNotNone(rows['WIN']['trade_closed_at'])
        self.assertIsNone(rows['OPEN']['realized_pnl_usd'])
        self.assertIsNone(rows['OPEN']['trade_closed_at'])
        self.assertIsNone(rows['NOLOT']['lot_id'])
        self.assertIsNone(rows['NOLOT']['realized_pnl_usd'])

    def test_daily_request_limit_defaults_and_clamps(self):
        for saved, expected in (('{}', 3), ('{"daily_strategy_requests": 6}', 6),
                                ('{"daily_strategy_requests": 99}', 6)):
            self.cfg.master_ai_config = saved
            db.session.commit()
            self.assertEqual(self.evidence()['daily_request_limit'], expected)


class IvRetryTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        jobs._last_retry_check = 0

    def test_a_failed_iv_job_is_retried_once(self):
        self.capture(datetime(2026, 11, 6, 20, 50))
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(minutes=5))
        jobs.schedule_failed_iv_retries()
        queued = ResearchJob.query.filter_by(status='QUEUED').all()
        self.assertEqual(len(queued), 1)
        self.assertEqual(json.loads(queued[0].request_json)['request'], WINDOW)
        jobs._last_retry_check = 0
        jobs.schedule_failed_iv_retries()
        self.assertEqual(ResearchJob.query.count(), 2)

    def test_a_failed_retry_is_not_retried_again(self):
        self.capture(datetime(2026, 11, 6, 20, 50))
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(minutes=10))
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(minutes=5))
        jobs.schedule_failed_iv_retries()
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)

    def test_missing_captures_block_a_retry(self):
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(minutes=5))
        jobs.schedule_failed_iv_retries()
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)

    def test_a_stale_failure_is_not_retried(self):
        self.capture(datetime(2026, 11, 6, 20, 50))
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(hours=25))
        jobs.schedule_failed_iv_retries()
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)

    def test_a_changed_target_dte_blocks_a_retry(self):
        self.capture(datetime(2026, 11, 6, 20, 50))
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(minutes=5),
                    config={'settings': {'options': {'target_dte': 30}}})
        jobs.schedule_failed_iv_retries()
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)


class IvCatchUpTests(DatabaseTestCase):
    NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

    def test_a_missed_close_window_with_captures_is_queued(self):
        self.capture(datetime(2026, 11, 6, 20, 50))
        jobs._catch_up_missed_iv(self.NOW)
        queued = ResearchJob.query.filter_by(status='QUEUED').all()
        self.assertEqual(len(queued), 1)
        self.assertEqual(json.loads(queued[0].request_json)['request'], WINDOW)

    def test_a_covered_window_is_not_requeued(self):
        self.capture(datetime(2026, 11, 6, 20, 50))
        self.iv_job('COMPLETED', completed_at=datetime(2026, 11, 6, 21, 20))
        jobs._catch_up_missed_iv(self.NOW)
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)

    def test_absent_captures_are_not_an_importable_day(self):
        jobs._catch_up_missed_iv(self.NOW)
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)

    def test_a_failed_job_does_not_block_catch_up_of_its_window(self):
        # The catch-up path skips covered windows regardless of job status;
        # the failed job's own recovery is the retry scheduler's job.
        self.capture(datetime(2026, 11, 6, 20, 50))
        self.iv_job('FAILED', completed_at=datetime.utcnow() - timedelta(minutes=5))
        jobs._catch_up_missed_iv(self.NOW)
        self.assertEqual(ResearchJob.query.filter_by(status='QUEUED').count(), 0)


if __name__ == '__main__':
    unittest.main()