"""Comprehensive tests for the Part 1 QSE Engine Redesign (v4.19.16).

Verifies all seven approved fixes:
  1. Composite equities/ETF watchlist regime (healthy / pullback / falling_hard)
     weighted toward index ETFs (SPY, QQQ, IWM, SMH); SPY alone cannot freeze
     the book when broader watchlist breadth is healthy.
  2. Strict per-module watchlist gating while keeping watchlists_json as plain
     per-module symbol arrays.
  3. Per-symbol market-state classifier (bottoming / still_falling / topping /
     still_rising / neutral) driving dip entries and top exits.
  4. Continuous crypto sell-side evaluation (trend break, top rollover,
     collapse detection vs. bottoming hold).
  5. Options filter transparency logging every rejection stage and reason
     without loosening $2.60 minimum credit or 0.75 friction cap.
  6. Unified three-layer decision stack (quantitative + AI news/direction
     summary -> decision models) across modules while preserving Mercury
     (`inception`) alongside `subq` and `gemini`.
  7. Pullback 0.5x state-based position sizing while preserving base caps.
"""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from portfolio_algo_models import DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS
from services.decision_settings import TRANSPORTS, INCEPTION_DECISIONS_MODEL, SUBQ_MODEL, GEMINI_DECISIONS_MODEL
from services.decision_quant import build_state, evaluate_entry
from services.portfolio_strategy_signals import (
    classify_market_state,
    compute_crypto_regime,
    compute_watchlist_regime,
    crypto_signal,
    equity_rotation_scores,
    equity_signal,
    select_credit_spread,
)
from strategy_service.server import evaluate_local
from tests.decision_helpers import DecisionTestCase, noul_payload


def make_daily(closes, *, spread=1.0, volumes=None):
    out = []
    for i, c in enumerate(closes):
        vol = volumes[i] if volumes is not None else 1000.0
        o = closes[i - 1] if i > 0 else c
        hi = max(o, c) + spread
        lo = max(0.01, min(o, c) - spread)
        out.append({'open': o, 'high': hi, 'low': lo, 'close': c, 'volume': vol, 'time': float(1700000000 + i * 86400)})
    return out


def make_hourly(closes, *, spread=1.0, volumes=None):
    out = []
    for i, c in enumerate(closes):
        vol = volumes[i] if volumes is not None else 500.0
        o = closes[i - 1] if i > 0 else c
        hi = max(o, c) + spread
        lo = max(0.01, min(o, c) - spread)
        out.append({'open': o, 'high': hi, 'low': lo, 'close': c, 'volume': vol, 'time': float(1700000000 + i * 3600)})
    return out


EQUITY_SETTINGS = copy.deepcopy(DEFAULT_MODULE_SETTINGS['equities'])
EQUITY_SETTINGS['trend_sma_days'] = 50
CRYPTO_SETTINGS = copy.deepcopy(DEFAULT_MODULE_SETTINGS['crypto'])


class CompositeRegimeAndWatchlistTests(unittest.TestCase):
    def test_spy_alone_below_50sma_does_not_freeze_healthy_watchlist(self):
        falling_spy = make_daily([200 - i * 0.3 for i in range(120)])
        rising = make_daily([100 + i * 0.4 for i in range(120)])
        watchlist = ['SPY', 'QQQ', 'IWM', 'SMH', 'XLK', 'NVDA', 'AAPL', 'MSFT', 'AMZN', 'TSLA']
        stronger_nvda = make_daily([100 + i * 0.6 for i in range(120)])
        histories = {sym: (falling_spy if sym == 'SPY' else stronger_nvda if sym == 'NVDA' else rising) for sym in watchlist}

        regime = compute_watchlist_regime(histories, watchlist)
        self.assertEqual(regime['state'], 'healthy')
        self.assertTrue(regime['regime_ok'])
        self.assertEqual(regime['size_multiplier'], 1.0)
        self.assertEqual(regime['above_sma50_count'], 9)

        ranks = equity_rotation_scores(histories, falling_spy, EQUITY_SETTINGS,
                                       watchlist=watchlist, composite_regime=regime)
        self.assertIn('NVDA', ranks)
        sig = equity_signal(stronger_nvda, stronger_nvda[-1]['close'], EQUITY_SETTINGS, falling_spy,
                            ranks['NVDA'], composite_regime=regime)
        self.assertTrue(sig['enter'])
        self.assertEqual(sig['checks']['composite_regime_state'], 'healthy')
        self.assertEqual(sig['size_multiplier'], 1.0)

    def test_pullback_regime_scales_sizing_to_half_and_restricts_to_strongest(self):
        rising = make_daily([100 + i * 0.3 for i in range(120)])
        falling = make_daily([200 - i * 0.3 for i in range(120)])
        watchlist = ['SPY', 'QQQ', 'IWM', 'SMH', 'NVDA', 'AAPL']
        # SPY + NVDA + AAPL above 50-SMA (weight 4.5 / 11.0 = 40.9% -> pullback)
        histories = {
            'SPY': rising, 'NVDA': rising, 'AAPL': rising,
            'QQQ': falling, 'IWM': falling, 'SMH': falling,
        }
        regime = compute_watchlist_regime(histories, watchlist)
        self.assertEqual(regime['state'], 'pullback')
        self.assertTrue(regime['regime_ok'])
        self.assertEqual(regime['size_multiplier'], 0.5)

        sig_rank1 = equity_signal(rising, rising[-1]['close'], EQUITY_SETTINGS, rising, 1, composite_regime=regime)
        sig_rank2 = equity_signal(rising, rising[-1]['close'], EQUITY_SETTINGS, rising, 2, composite_regime=regime)
        self.assertTrue(sig_rank1['enter'])
        self.assertEqual(sig_rank1['size_multiplier'], 0.5)
        self.assertFalse(sig_rank2['checks']['rotation_top_two'])

    def test_falling_hard_regime_blocks_new_longs(self):
        falling = make_daily([200 - i * 0.4 for i in range(120)])
        rising = make_daily([100 + i * 0.4 for i in range(120)])
        watchlist = ['SPY', 'QQQ', 'IWM', 'SMH', 'NVDA', 'AAPL']
        histories = {sym: (rising if sym == 'AAPL' else falling) for sym in watchlist}
        regime = compute_watchlist_regime(histories, watchlist)
        self.assertEqual(regime['state'], 'falling_hard')
        self.assertFalse(regime['regime_ok'])
        self.assertEqual(regime['size_multiplier'], 0.0)
        sig = equity_signal(rising, rising[-1]['close'], EQUITY_SETTINGS, falling, 1, composite_regime=regime)
        self.assertFalse(sig['enter'])

    def test_rotation_ignores_symbols_outside_configured_watchlist(self):
        rising = make_daily([100 + i * 0.5 for i in range(120)])
        histories = {'AAPL': rising, 'ROGUE': rising}
        regime = compute_watchlist_regime(histories, ['AAPL'])
        ranks = equity_rotation_scores(histories, rising, EQUITY_SETTINGS,
                                       watchlist=['AAPL'], composite_regime=regime)
        self.assertEqual(list(ranks.keys()), ['AAPL'])

    def test_default_watchlists_remain_plain_symbol_arrays(self):
        for mod, items in DEFAULT_QUANT_WATCHLISTS.items():
            self.assertIsInstance(items, list, mod)
            self.assertTrue(all(isinstance(s, str) for s in items), mod)


class MarketStateClassifierTests(unittest.TestCase):
    def test_bottoming_base_with_turn_volume_is_classified_bottoming(self):
        # Peak at 120, orderly selloff to 102 with climax, then tight base around 102-104 and turn higher to 105.5
        closes = (
            [115 + i * 0.25 for i in range(20)]
            + [118, 115, 111, 107, 103, 102.5, 102.2, 102.6, 102.8, 103.0, 103.2, 103.5, 104.2]
        )
        vols = [1000] * 20 + [1200, 1400, 1800, 2200, 2500, 900, 700, 650, 650, 700, 800, 1200, 1600]
        bars = make_daily(closes, spread=0.6, volumes=vols)
        ms = classify_market_state(bars, 105.0)
        self.assertEqual(ms['state'], 'bottoming')
        self.assertGreaterEqual(ms['confidence'], 0.55)
        self.assertFalse(ms['collapse'])

    def test_falling_knife_crash_is_classified_still_falling_with_collapse(self):
        closes = [120.0] * 25 + [117, 114, 110, 105, 100, 95, 89, 83]
        vols = [1000] * 25 + [1100, 1300, 1600, 1900, 2200, 2600, 3000, 3500]
        bars = make_daily(closes, spread=3.0, volumes=vols)
        ms = classify_market_state(bars, 81.0)
        self.assertEqual(ms['state'], 'still_falling')
        self.assertTrue(ms['collapse'])

    def test_overextended_parabolic_rollover_is_classified_topping(self):
        closes = [100.0] * 20 + [102, 105, 109, 114, 119, 125, 131, 136, 134]
        vols = [1000] * 20 + [1100, 1200, 1300, 1500, 1600, 1800, 2000, 2200, 2600]
        bars = make_daily(closes, spread=1.0, volumes=vols)
        ms = classify_market_state(bars, 133.0)
        self.assertEqual(ms['state'], 'topping')
        self.assertTrue(ms['rollover'])

    def test_crypto_continuous_sell_evaluation_triggers_collapse_and_top_exits(self):
        crash_closes = [100.0] * 25 + [97, 94, 90, 86, 82, 78]
        crash_vols = [500] * 25 + [700, 900, 1200, 1500, 1800, 2200]
        crash_bars = make_hourly(crash_closes, spread=2.5, volumes=crash_vols)
        sig_crash = crypto_signal(crash_bars, 76.0, CRYPTO_SETTINGS, True)
        self.assertFalse(sig_crash['enter'])
        self.assertTrue(sig_crash['exit'])
        self.assertEqual(sig_crash['exit_reason'], 'CRYPTO_COLLAPSE_EXIT')
        self.assertTrue(sig_crash['checks']['sell_evaluation']['collapse_exit'])

        top_closes = [100.0] * 20 + [103, 107, 112, 118, 124, 130, 136, 134]
        top_vols = [500] * 20 + [600, 700, 800, 900, 1000, 1200, 1400, 1900]
        top_bars = make_hourly(top_closes, spread=1.0, volumes=top_vols)
        sig_top = crypto_signal(top_bars, 133.0, CRYPTO_SETTINGS, True)
        self.assertFalse(sig_top['enter'])
        self.assertTrue(sig_top['exit'])
        self.assertEqual(sig_top['exit_reason'], 'CRYPTO_TOP_EXIT')

    def test_crypto_confirmed_bottom_enables_dip_entry_and_rule_accepts_it(self):
        closes = (
            [115 + i * 0.2 for i in range(20)]
            + [116, 113, 109, 105, 101, 101.0, 101.2, 101.4, 101.6, 101.9, 102.2, 102.6, 103.3]
        )
        vols = [500] * 20 + [700, 900, 1200, 1400, 1600, 450, 380, 350, 360, 400, 500, 750, 950]
        bars = make_hourly(closes, spread=0.8, volumes=vols)
        sig = crypto_signal(bars, 104.0, CRYPTO_SETTINGS, True)
        self.assertTrue(sig['checks']['dip_entry_qualified'])
        self.assertTrue(sig['enter'])
        self.assertEqual(sig['setup'], 'CRYPTO_BOTTOM_DIP_V1')
        source = Path('strategy_service/rules/crypto.py').read_text(encoding='utf-8')
        rule_decision = evaluate_local(source, {'checks': sig['checks']})
        self.assertTrue(rule_decision['enter'])
        self.assertEqual(rule_decision['setup'], 'CRYPTO_BOTTOM_DIP_V1')


class OptionsFilterTransparencyTests(unittest.TestCase):
    def test_select_credit_spread_logs_exact_rejection_filters_without_loosening_rules(self):
        settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS['options'])
        now = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
        contracts = [
            # Rejected by short_delta (> 0.25)
            {'symbol': 'P1', 'strike': 99.0, 'bid': 2.0, 'ask': 2.1, 'expiration': '2026-11-15', 'option_type': 'PUT', 'delta': -0.40, 'bid_size': 10, 'ask_size': 10},
            # Valid short leg, paired with long leg that yields $0.02 credit ($2 <= $2.60 min_credit_2_60)
            {'symbol': 'P2', 'strike': 95.0, 'bid': 0.52, 'ask': 0.54, 'expiration': '2026-11-15', 'option_type': 'PUT', 'delta': -0.18, 'bid_size': 10, 'ask_size': 10},
            {'symbol': 'P3', 'strike': 94.0, 'bid': 0.48, 'ask': 0.50, 'expiration': '2026-11-15', 'option_type': 'PUT', 'delta': -0.14, 'bid_size': 10, 'ask_size': 10},
        ]
        diagnostics = {}
        with self.assertRaises(ValueError) as ctx:
            select_credit_spread(contracts, 100.0, 60, settings, now,
                                 allow_warmup=True, preferred_kind='PUT', diagnostics=diagnostics)
        self.assertIn('filters:', str(ctx.exception))
        self.assertGreaterEqual(diagnostics['rejections']['short_delta'], 1)
        self.assertGreaterEqual(diagnostics['rejections']['min_credit_2_60'], 1)
        self.assertGreater(len(diagnostics['rejection_samples']), 0)


class CombinedDecisionStackAndMercuryTests(DecisionTestCase):
    def test_mercury_transport_preserved_alongside_subq_and_gemini(self):
        self.assertIn('subq', TRANSPORTS)
        self.assertIn('inception', TRANSPORTS)
        self.assertIn('gemini', TRANSPORTS)
        self.assertEqual(SUBQ_MODEL, 'subq-snap-1.2')
        self.assertEqual(INCEPTION_DECISIONS_MODEL, 'mercury-decide')
        self.assertEqual(GEMINI_DECISIONS_MODEL, 'gemini-decision-1')

    def test_combined_decision_passes_both_quant_and_news_summary_for_equities(self):
        from models import JevEvaluation
        from services.decision_contracts import build_crypto_quant_questions
        from services.portfolio_engine import combined_decision_verdict

        questions = build_crypto_quant_questions()
        payload = noul_payload(questions)
        payload['answers']['confirm_entry'] = {'type': 'noul', 'noul': 0.91}

        news_summary = {
            'symbol': 'NVDA', 'module': 'equities', 'direction_bias': 'bullish',
            'catalyst_risk': 'low', 'summary': 'Strong AI data-center demand reported.',
            'headline_count': 2, 'headlines': ['NVDA beats estimates'], 'source': 'ai_news_summary',
        }
        signal = {
            'enter': True, 'setup': 'MARKET_STATE_BOTTOM_V1',
            'checks': {'completed_daily_bars': 120, 'market_state': 'bottoming',
                       'composite_regime_state': 'healthy'},
        }
        with patch('services.decision_engine.requests.post',
                   return_value=Mock(status_code=200, json=lambda: payload)):
            verdict = combined_decision_verdict(
                1, 'equities', 'NVDA', 140.0, signal, self.now,
                self.config, evaluate_entry, news_summary=news_summary,
            )
        self.assertEqual(verdict['verdict'], 'CONFIRM')
        row = JevEvaluation.query.filter_by(use_case='quant_equities', symbol='NVDA').one()
        state = json.loads(row.state_json)
        self.assertEqual(state['module'], 'equities')
        self.assertEqual(state['instrument_type'], 'EQUITY')
        self.assertEqual(state['features']['market_state'], 'bottoming')
        self.assertEqual(state['news_direction_summary']['direction_bias'], 'bullish')

    def test_pullback_size_multiplier_halves_entered_position_size(self):
        from services import portfolio_engine as engine
        cfg, acc, state = engine.ensure_portfolio(1)
        base_sig = {'enter': True, 'side': 'LONG', 'stop': 80.0, 'size_multiplier': 1.0, 'reason': 'healthy'}
        half_sig = {'enter': True, 'side': 'LONG', 'stop': 80.0, 'size_multiplier': 0.5, 'reason': 'pullback'}
        lot_full = engine.enter_lot(cfg, acc, state, 'equities', 'NVDA', base_sig, 100.0, self.now)
        lot_half = engine.enter_lot(cfg, acc, state, 'equities', 'AAPL', half_sig, 100.0, self.now)
        self.assertIsNotNone(lot_full)
        self.assertIsNotNone(lot_half)
        self.assertLess(lot_half.collateral, lot_full.collateral * 0.6)


if __name__ == '__main__':
    unittest.main()
