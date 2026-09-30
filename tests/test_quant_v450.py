"""Financial safety regressions for v4.5.0 signals and editable strategy source."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.portfolio_strategy_signals import (
    equity_rotation_scores, equity_signal, option_regime, realized_volatility,
)
from strategy_service import server


def bars(closes):
    return [{'open': value, 'high': value + 1, 'low': value - 1,
             'close': value, 'volume': 100, 'time': float(index * 86400)}
            for index, value in enumerate(closes)]


class Quant450SignalTests(unittest.TestCase):
    def test_trend_rotation_and_pullback_are_independent(self):
        cfg = {'trend_sma_days': 50, 'rsi_period': 2,
               'rsi_entry_threshold': 10, 'bollinger_std': 2}
        benchmark = bars([100] * 200)
        leader = bars([100 + index * .5 for index in range(200)])
        ranks = equity_rotation_scores({'LEAD': leader}, benchmark, cfg)
        self.assertEqual(ranks, {'LEAD': 1})
        decision = equity_signal(leader, leader[-1]['close'], cfg, benchmark, ranks['LEAD'])
        self.assertTrue(decision['enter'])
        self.assertEqual(decision['setup'], 'TREND_ROTATION_V1')
        self.assertFalse(equity_signal(leader, 1, cfg, benchmark, ranks['LEAD'])['checks']['current_price_above_sma'])
        pullback = bars([100 + index * .3 for index in range(180)] + [200] * 19 + [180])
        decision = equity_signal(pullback, 180, cfg, benchmark, None)
        self.assertTrue(decision['checks']['pullback_qualified'])
        self.assertEqual(decision['setup'], 'TREND_PULLBACK_V1')

    def test_option_fallback_is_labeled_separately_from_short_and_annual_history(self):
        history = bars([80 + index * .2 for index in range(61)])
        fallback = option_regime(history, 100, .4)
        self.assertTrue(fallback['enter'])
        self.assertEqual(fallback['basis'], 'CURRENT_IV_VS_REALIZED_VOL')
        self.assertIsNone(fallback['checks']['annual_iv_rank_252'])
        short = option_regime(history, 100, .4, rank_30=60)
        self.assertEqual(short['basis'], 'SHORT_IV_PERCENTILE_30')
        annual = option_regime(history, 100, .4, rank_30=60, rank_252=50)
        self.assertEqual(annual['basis'], 'ANNUAL_IV_RANK_252')
        self.assertGreaterEqual(realized_volatility(history, 20), 0)

    def test_source_validator_rejects_imports_attributes_and_recursion(self):
        for source in ('import os\ndef decide(f): return {"enter": True, "reason": "x"}',
                       'def decide(f): return f.__class__',
                       'def decide(f): return decide(f)'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                server.validate_source(source)

    def test_candidate_validates_activates_and_rolls_back_without_app_release(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, 'ROOT', Path(directory)):
                base = server.handle({'schema': 1, 'op': 'source', 'module': 'crypto'})
                modified = base['source'].replace('c["price_above_entry_channel"] and c["dominance_gate_passed"]',
                                                   'c["price_above_entry_channel"]')
                fixture = {'checks': {'price_above_entry_channel': True, 'dominance_gate_passed': False}}
                proposed = server.handle({'schema': 1, 'op': 'propose', 'module': 'crypto',
                    'parent_sha256': base['sha256'], 'source': modified,
                    'fixtures': [{'features': fixture}]})
                self.assertEqual(proposed['status'], 'VALIDATED')
                with self.assertRaises(ValueError):
                    server.handle({'schema': 1, 'op': 'activate', 'module': 'crypto',
                        'parent_sha256': base['sha256'],
                        'candidate_sha256': proposed['candidate_sha256'],
                        'evidence_sha256': 'test', 'gates': {'mode': 'PAPER_EXPERIMENT',
                            'paper_only': True, 'observation_sessions': 0,
                            'sampled_decisions': 1, 'risk_breaches': 0, 'holdout_fresh': True}})
                active = server.handle({'schema': 1, 'op': 'activate', 'module': 'crypto',
                    'parent_sha256': base['sha256'],
                    'candidate_sha256': proposed['candidate_sha256'],
                    'evidence_sha256': 'test', 'gates': {'mode': 'PAPER_EXPERIMENT',
                        'paper_only': True, 'observation_sessions': 1,
                        'sampled_decisions': 1, 'risk_breaches': 0, 'holdout_fresh': True}})
                self.assertEqual(active['status'], 'ACTIVE')
                rolled = server.handle({'schema': 1, 'op': 'rollback', 'module': 'crypto',
                    'expected_sha256': active['sha256']})
                self.assertEqual(rolled['sha256'], base['sha256'])


if __name__ == '__main__':
    unittest.main()
