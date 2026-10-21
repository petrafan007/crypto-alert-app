"""Candidate-strategy replay: a candidate rule is compared against the baseline.

The tests build a small deterministic synthetic dataset and run the replay in
an isolated in-memory database. They never touch the live PostgreSQL archive.
"""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from credentials import User
from event_algo_models import EventStrategyConfig
from research_data_models import (ResearchCapture, ResearchCollectionConfig, ResearchCollectionState,
                                  ResearchDataset, ResearchJob)
from services.research_dataset import canonical
from services.research_history import ResearchMarketData
from services.research_replay import (baseline_sources, candidate_fixtures, compare_results,
                                       run_comparison, scenario_run, timeline, validate_candidate)
from portfolio_algo_models import (DEFAULT_ALLOCATIONS, DEFAULT_MODULE_SETTINGS,
                                   DEFAULT_QUANT_WATCHLISTS, PortfolioStrategyConfig)

NOW = datetime(2025, 6, 2, 14, tzinfo=timezone.utc)

# A candidate that refuses every crypto breakout: the baseline would have
# entered, the candidate must not.
FLAT_CRYPTO_CANDIDATE = '''def decide(f):
    c = f["checks"]
    ready = c["price_above_entry_channel"] and c["dominance_gate_passed"] and False
    if ready:
        return {"enter": True, "setup": "NEVER", "reason": "Unreachable."}
    return {"enter": False, "setup": "NEVER", "reason": "Candidate declined every breakout."}
'''

# A candidate that enters on every crypto breakout, including ones the
# dominance gate rejected.
ALWAYS_CRYPTO_CANDIDATE = '''def decide(f):
    c = f["checks"]
    ready = c["price_above_entry_channel"]
    if ready:
        return {"enter": True, "setup": "CANDIDATE_BREAKOUT_V1", "reason": "Candidate entered on a completed-hour breakout."}
    return {"enter": False, "setup": "CANDIDATE_BREAKOUT_V1", "reason": "Price has not exceeded the completed-bar Donchian high."}
'''

SYNTAX_ERROR_CANDIDATE = 'def decide(f):\n    return {"enter": True,,}\n'

WRONG_SHAPE_CANDIDATE = '''def decide(f):
    return "not a decision object"
'''


def row(kind, module, symbol, at=NOW, **fields):
    return {'kind': kind, 'module': module, 'symbol': symbol, 'source': 'TEST', 'currency': 'USD',
            'event_at': at.isoformat(), 'available_at': at.isoformat(), 'timestamp_basis': 'PROVIDER', **fields}


def config(*enabled):
    settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS)
    for key in settings:
        settings[key]['enabled'] = key in enabled
    return {'settings': settings, 'allocations': copy.deepcopy(DEFAULT_ALLOCATIONS),
            'watchlists': copy.deepcopy(DEFAULT_QUANT_WATCHLISTS), 'bankroll': 1000, 'target': 18.5,
            'currency': 'USD', 'event': {'risk': {}, 'signal': {}, 'config_id': None}}


def crypto_data(prices=(105, 108, 109, 95), symbols=('BTCUSD',)):
    """Deterministic hourly history plus four observed quotes."""
    rows = []
    for symbol in symbols:
        for i in range(200):
            t = NOW - timedelta(hours=201 - i)
            rows.append(row('bar', 'crypto', symbol, t,
                            available_at=(t + timedelta(hours=1)).isoformat(),
                            complete_at=(t + timedelta(hours=1)).isoformat(),
                            interval='1h', open=100, high=101, low=99, close=100, volume=100))
        for i, price in enumerate(prices):
            rows.append(row('quote', 'crypto', symbol, NOW + timedelta(minutes=5 * i), price=price,
                            bid=price - .1, ask=price + .1, ask_size=1000, bid_size=1000))
    return canonical(rows, {'origin': 'SYNTHETIC_TEST'})


class CandidateReplayTests(unittest.TestCase):
    """The candidate path never reaches the live database."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True)
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    # (a) The baseline path is unchanged when no candidate is given.
    def test_baseline_path_is_unchanged_without_a_candidate(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        points = timeline(data, NOW, NOW + timedelta(minutes=16))
        with patch.object(ResearchMarketData, 'dominance_ok', return_value=True):
            plain = scenario_run(data, cfg, points, 'baseline', [])
            again = scenario_run(data, cfg, points, 'baseline', [])
        # Without a candidate the replay is byte-for-byte the shipped baseline.
        self.assertEqual(plain, again)
        self.assertEqual(plain['entries'], 1)
        self.assertEqual(plain['closed_trades'], 1)
        self.assertEqual(plain['coverage']['crypto'], 'OBSERVED')
        self.assertEqual(plain['status'], 'COMPUTED')

    def test_baseline_run_reports_the_shipped_rule_checksum(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        points = timeline(data, NOW, NOW + timedelta(minutes=6))
        with patch.object(ResearchMarketData, 'dominance_ok', return_value=True):
            result = scenario_run(data, cfg, points, 'baseline', [])
        self.assertEqual(result['entries'], 1)
        sources = baseline_sources()
        self.assertEqual(len(sources['crypto']), 64)
        self.assertEqual(sources['crypto'],
                         hashlib.sha256((Path(__file__).resolve().parent.parent /
                                         'strategy_service' / 'rules' / 'crypto.py').read_text().encode()).hexdigest())

    # (b) A candidate that changes a decision produces a different result.
    def test_candidate_changes_entries_and_pnl_versus_baseline(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        points = timeline(data, NOW, NOW + timedelta(minutes=16))
        candidate = validate_candidate('crypto', FLAT_CRYPTO_CANDIDATE, cfg['settings'])
        self.assertEqual(len(candidate['sha256']), 64)
        with patch.object(ResearchMarketData, 'dominance_ok', return_value=True):
            baseline = scenario_run(data, cfg, points, 'baseline', [])
            proposed = scenario_run(data, cfg, points, 'baseline', [], candidate=candidate)
        self.assertEqual(baseline['entries'], 1)
        self.assertEqual(proposed['entries'], 0)
        self.assertNotEqual(baseline['ending_equity'], proposed['ending_equity'])

        comparison = compare_results(baseline, proposed, candidate, baseline_sources())
        self.assertEqual(comparison['modules']['crypto']['baseline']['entries'], 1)
        self.assertEqual(comparison['modules']['crypto']['candidate']['entries'], 0)
        self.assertEqual(comparison['modules']['crypto']['delta']['entries'], -1)
        self.assertEqual(comparison['modules']['crypto']['baseline_sha256'], baseline_sources()['crypto'])
        self.assertEqual(comparison['modules']['crypto']['candidate_sha256'], candidate['sha256'])
        # Every other module keeps the shipped baseline rule.
        self.assertEqual(comparison['modules']['equities']['candidate_sha256'],
                         baseline_sources()['equities'])
        self.assertFalse(comparison['modules']['equities']['changed'])
        self.assertEqual(comparison['total']['delta']['entries'], -1)
        # The measures the comparison must expose for every module and total.
        for key in ('entries', 'closed_trades', 'net_pnl', 'max_drawdown_pct', 'win_rate_pct'):
            self.assertIn(key, comparison['modules']['crypto']['baseline'])
            self.assertIn(key, comparison['modules']['crypto']['candidate'])
            self.assertIn(key, comparison['total']['baseline'])
            self.assertIn(key, comparison['total']['candidate'])

    def test_candidate_that_enters_more_often_changes_the_trade_count(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        points = timeline(data, NOW, NOW + timedelta(minutes=16))
        candidate = validate_candidate('crypto', ALWAYS_CRYPTO_CANDIDATE, cfg['settings'])
        with patch.object(ResearchMarketData, 'dominance_ok', return_value=False):
            baseline = scenario_run(data, cfg, points, 'baseline', [])
            proposed = scenario_run(data, cfg, points, 'baseline', [], candidate=candidate)
        # The dominance gate blocks the baseline; the candidate ignores it.
        self.assertEqual(baseline['entries'], 0)
        self.assertEqual(proposed['entries'], 1)

    def test_comparison_run_reports_both_sides_and_the_checksums(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        candidate = validate_candidate('crypto', FLAT_CRYPTO_CANDIDATE, cfg['settings'])
        request = {'start': NOW.isoformat(),
                   'split': (NOW + timedelta(minutes=10)).isoformat(),
                   'end': (NOW + timedelta(minutes=16)).isoformat()}
        with patch.object(ResearchMarketData, 'dominance_ok', return_value=True):
            result = run_comparison(data, cfg, request, candidate)
        self.assertEqual(result['scope'], 'candidate_strategy_comparison')
        self.assertEqual(result['candidate']['sha256'], candidate['sha256'])
        self.assertEqual(result['candidate']['baseline_sha256'], baseline_sources()['crypto'])
        for window in result['windows'].values():
            total = window['comparison']['total']
            self.assertIn('baseline', total)
            self.assertIn('candidate', total)
            self.assertEqual(total['baseline']['entries'], 1)
            self.assertEqual(total['candidate']['entries'], 0)
            self.assertEqual(window['comparison']['modules']['crypto']['delta']['entries'], -1)

    # (c) An invalid candidate is rejected, and the replay reports the rejection.
    def test_invalid_candidates_are_rejected(self):
        for label, source in (('syntax error', SYNTAX_ERROR_CANDIDATE),
                               ('wrong shape', WRONG_SHAPE_CANDIDATE),
                               ('empty', ''),
                               ('not a function', 'x = 1\n')):
            with self.subTest(candidate=label):
                with self.assertRaises(ValueError) as caught:
                    validate_candidate('crypto', source)
                self.assertTrue(str(caught.exception))

    def test_candidate_returning_a_non_boolean_enter_is_rejected(self):
        source = '''def decide(f):
    return {"enter": "yes", "setup": "X", "reason": "Not a boolean."}
'''
        with self.assertRaises(ValueError):
            validate_candidate('crypto', source)

    def test_rejected_candidate_never_reaches_the_replay(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        points = timeline(data, NOW, NOW + timedelta(minutes=6))
        with self.assertRaises(ValueError):
            validate_candidate('crypto', SYNTAX_ERROR_CANDIDATE, cfg['settings'])
        # A candidate that never passed validation cannot be replayed.
        with self.assertRaises(ValueError):
            scenario_run(data, cfg, points, 'baseline', [],
                         candidate={'module': 'crypto', 'source': SYNTAX_ERROR_CANDIDATE,
                                    'sha256': '0' * 64})

    def test_rejected_candidate_is_reported_instead_of_replayed(self):
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        request = {'start': NOW.isoformat(),
                   'split': (NOW + timedelta(minutes=10)).isoformat(),
                   'end': (NOW + timedelta(minutes=16)).isoformat()}
        result = run_comparison(data, cfg, request,
                                {'module': 'crypto', 'source': SYNTAX_ERROR_CANDIDATE,
                                 'sha256': '0' * 64})
        self.assertEqual(result['status'], 'REJECTED')
        self.assertEqual(result['windows'], {})
        self.assertIn('syntax error', result['rejection']['reason'])
        self.assertEqual(result['rejection']['module'], 'crypto')

    def test_candidate_fixtures_use_the_live_feature_shape(self):
        fixtures = candidate_fixtures('crypto')
        self.assertEqual(len(fixtures), 2)
        self.assertIn('checks', fixtures[0])
        self.assertIn('price_above_entry_channel', fixtures[0]['checks'])
        self.assertIn('dominance_gate_passed', fixtures[0]['checks'])
        events = candidate_fixtures('events')
        self.assertEqual(sorted(events[0]), ['eligible', 'fresh_quote', 'risk_allowed'])

    def test_every_strategy_module_accepts_a_valid_candidate(self):
        source = '''def decide(f):
    if f["checks"]:
        return {"enter": False, "setup": "TEST", "reason": "Candidate declined."}
    return {"enter": False, "setup": "TEST", "reason": "Candidate declined."}
'''
        for module in ('crypto', 'equities', 'options'):
            with self.subTest(module=module):
                candidate = validate_candidate(module, source)
                self.assertEqual(candidate['module'], module)
                self.assertEqual(len(candidate['sha256']), 64)
        events = validate_candidate('events', '''def decide(f):
    if f["eligible"] and f["fresh_quote"] and f["risk_allowed"]:
        return {"enter": True, "setup": "TEST", "reason": "Candidate entered."}
    return {"enter": False, "setup": "TEST", "reason": "Candidate declined."}
''')
        self.assertEqual(events['module'], 'events')

    def test_a_candidate_that_cannot_read_live_features_is_rejected(self):
        # The Events rule reads top-level keys, not a checks dict.
        source = '''def decide(f):
    c = f["checks"]
    return {"enter": False, "setup": "TEST", "reason": "Candidate read the wrong shape."}
'''
        with self.assertRaises(ValueError):
            validate_candidate('events', source)

    def test_the_candidate_source_is_the_one_that_actually_ran(self):
        import services.research_replay as replay_module
        data = crypto_data()
        cfg = config('crypto')
        cfg['watchlists']['crypto'] = ['BTC']
        points = timeline(data, NOW, NOW + timedelta(minutes=6))
        candidate = validate_candidate('crypto', FLAT_CRYPTO_CANDIDATE, cfg['settings'])
        real = replay_module.evaluate_local
        seen = []

        def recording(source, features):
            seen.append(source)
            return real(source, features)

        with patch.object(ResearchMarketData, 'dominance_ok', return_value=True), \
                patch.object(replay_module, 'evaluate_local', recording):
            scenario_run(data, cfg, points, 'baseline', [], candidate=candidate)
        self.assertTrue(seen)
        # The candidate source is evaluated for crypto; the shipped crypto
        # rule is never evaluated in its place.
        self.assertIn(FLAT_CRYPTO_CANDIDATE, seen)
        self.assertNotIn((Path(__file__).resolve().parent.parent /
                          'strategy_service' / 'rules' / 'crypto.py').read_text(), seen)


class CandidateComparisonJobTests(unittest.TestCase):
    """The comparison is queued, computed and read back from the job row."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test', TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in (
            User, ResearchCollectionConfig, ResearchCollectionState, ResearchCapture,
            ResearchDataset, ResearchJob, PortfolioStrategyConfig, EventStrategyConfig)])
        db.session.add(User(id=1, username='admin', pwd_hash='test'))
        db.session.add(PortfolioStrategyConfig(user_id=1))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def test_comparison_job_is_persisted_and_readable(self):
        from research_data_models import ResearchJob
        from services.research_dataset import save_dataset
        from services.research_jobs import enqueue, job_dict, process_one
        dataset = save_dataset(1, crypto_data())
        request = {'dataset_id': dataset.id, 'start': NOW.isoformat(),
                   'split': (NOW + timedelta(minutes=10)).isoformat(),
                   'end': (NOW + timedelta(minutes=16)).isoformat(),
                   'candidate': {'module': 'crypto', 'source': FLAT_CRYPTO_CANDIDATE}}
        job = enqueue(1, 'replay_compare', request)
        self.assertEqual(job['kind'], 'replay_compare')
        stored = ResearchJob.query.filter_by(id=job['id']).one()
        candidate = json.loads(stored.request_json)['request']['candidate']
        self.assertEqual(candidate['module'], 'crypto')
        self.assertEqual(len(candidate['sha256']), 64)

        with patch('services.research_replay.run_comparison',
                   return_value={'scope': 'candidate_strategy_comparison', 'status': 'COMPARED',
                                 'candidate': candidate, 'windows': {}}):
            self.assertTrue(process_one())
        stored = db.session.get(ResearchJob, job['id'], populate_existing=True)
        self.assertEqual(stored.status, 'COMPLETED')
        summary = json.loads(stored.summary_json)
        self.assertEqual(summary['scope'], 'candidate_strategy_comparison')
        self.assertEqual(summary['candidate']['sha256'], candidate['sha256'])
        # The stored result is readable without the in-process objects.
        self.assertEqual(job_dict(stored, result=True)['result']['status'], 'COMPARED')

    def test_invalid_candidate_is_never_queued(self):
        from services.research_jobs import enqueue
        request = {'dataset_id': 1, 'start': NOW.isoformat(),
                   'split': (NOW + timedelta(minutes=10)).isoformat(),
                   'end': (NOW + timedelta(minutes=16)).isoformat(),
                   'candidate': {'module': 'crypto', 'source': SYNTAX_ERROR_CANDIDATE}}
        with self.assertRaises(ValueError):
            enqueue(1, 'replay_compare', request)

    def test_existing_job_kinds_still_enqueue(self):
        from services.research_dataset import save_dataset
        from services.research_jobs import enqueue
        dataset = save_dataset(1, crypto_data())
        self.assertEqual(enqueue(1, 'iv_preview', {'dataset_id': dataset.id})['kind'], 'iv_preview')
        self.assertEqual(enqueue(1, 'replay', {'dataset_id': dataset.id, 'start': NOW.isoformat(),
                                               'split': (NOW + timedelta(minutes=10)).isoformat(),
                                               'end': (NOW + timedelta(minutes=16)).isoformat()})['kind'],
                         'replay')
        with self.assertRaises(ValueError):
            enqueue(1, 'not_a_job', {})


if __name__ == '__main__':
    unittest.main()
