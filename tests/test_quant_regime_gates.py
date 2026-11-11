"""Regression tests for the v4.14.0 entry-quality regime gates.

A signal may only enter when the broader tape confirms the idea: options need
a 20-session trend outside the noise band, crypto breakouts need a rising
20-hour average and real hourly range, and equity longs need the benchmark
above its own 50-session average. These gates remove purposeless trades
without capping the engine's ability to trade a confirmed setup.
"""
import copy
import unittest
from pathlib import Path

from portfolio_algo_models import DEFAULT_MODULE_SETTINGS
from services.portfolio_strategy_signals import (
    DIRECTION_CONFIRMATION_BAND,
    crypto_signal,
    equity_signal,
    option_regime,
)
from services.research_replay import evaluate_local


def daily(closes):
    return [{'open': value, 'high': value + 1, 'low': value - 1,
             'close': value, 'volume': 100, 'time': float(index * 86400)}
            for index, value in enumerate(closes)]


def hourly(closes, spread=1.0):
    return [{'open': value, 'high': value + spread, 'low': value - spread,
             'close': value, 'volume': 10, 'time': float(index * 3600)}
            for index, value in enumerate(closes)]


EQUITY_SETTINGS = {'trend_sma_days': 50, 'rsi_period': 2,
                   'rsi_entry_threshold': 10, 'bollinger_std': 2}


class OptionsDirectionBandTests(unittest.TestCase):
    def test_a_trend_inside_the_band_is_noise_not_direction(self):
        # 61 bars rising 0.1 per session: the 20-session trend is ~1.9%,
        # inside the 2% confirmation band. No spread direction may be derived.
        history = daily([100 + index * .1 for index in range(61)])
        regime = option_regime(history, 106, .4, rank_252=80)
        self.assertIsNone(regime['option_type'])
        self.assertFalse(regime['enter'])
        self.assertFalse(regime['checks']['trend_clears_confirmation_band'])
        self.assertEqual(regime['checks']['direction_confirmation_band'],
                         DIRECTION_CONFIRMATION_BAND)

    def test_a_confirmed_uptrend_still_sells_put_spreads(self):
        history = daily([80 + index * .2 for index in range(61)])
        regime = option_regime(history, 100, .4, rank_252=50)
        self.assertTrue(regime['checks']['trend_clears_confirmation_band'])
        self.assertEqual(regime['option_type'], 'PUT')
        self.assertTrue(regime['enter'])

    def test_a_confirmed_downtrend_still_sells_call_spreads(self):
        history = daily([120 - index * .3 for index in range(61)])
        regime = option_regime(history, 102, .4, rank_252=50)
        self.assertEqual(regime['option_type'], 'CALL')
        self.assertTrue(regime['enter'])

    def test_high_iv_cannot_manufacture_a_direction(self):
        history = daily([100 + index * .05 for index in range(61)])
        regime = option_regime(history, 103, .9, rank_252=99)
        self.assertIsNone(regime['option_type'])
        self.assertFalse(regime['enter'])


class CryptoRegimeGateTests(unittest.TestCase):
    def setUp(self):
        self.settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS['crypto'])

    def test_a_qualified_breakout_still_enters(self):
        bars = hourly([95] * 25, spread=5)
        signal = crypto_signal(bars, 101, self.settings, True)
        self.assertTrue(signal['enter'])
        self.assertEqual(signal['checks']['trend_sma_20h'], 95)
        self.assertTrue(signal['checks']['price_above_trend_sma'])
        self.assertTrue(signal['checks']['atr_above_noise_floor'])

    def test_a_breakout_against_the_trend_average_is_rejected(self):
        # A short entry channel can break out while the 20-hour average is
        # still far overhead: the prior decline must veto the long.
        settings = {**self.settings, 'entry_channel_periods': 10}
        bars = hourly([130] * 15, spread=1) + hourly([95] * 10, spread=1)
        signal = crypto_signal(bars, 97, settings, True)
        self.assertTrue(signal['checks']['price_above_entry_channel'])
        self.assertFalse(signal['checks']['price_above_trend_sma'])
        self.assertFalse(signal['enter'])

    def test_a_flat_tape_breakout_is_rejected_by_the_noise_floor(self):
        bars = hourly([100] * 25, spread=.05)
        signal = crypto_signal(bars, 100.2, self.settings, True)
        self.assertTrue(signal['checks']['price_above_entry_channel'])
        self.assertTrue(signal['checks']['price_above_trend_sma'])
        self.assertFalse(signal['checks']['atr_above_noise_floor'])
        self.assertFalse(signal['enter'])

    def test_the_exit_is_unchanged_by_the_entry_gates(self):
        bars = hourly([100] * 25, spread=.05)
        signal = crypto_signal(bars, 99, self.settings, True)
        self.assertFalse(signal['enter'])
        self.assertTrue(signal['exit'])

    def test_the_trend_window_raises_the_minimum_history(self):
        settings = {**self.settings, 'entry_channel_periods': 10,
                    'exit_channel_periods': 10}
        with self.assertRaises(ValueError) as caught:
            crypto_signal(hourly([95] * 19), 101, settings, True)
        self.assertIn('Insufficient completed hourly channel history.',
                      str(caught.exception))

    def test_the_shipped_rule_consumes_the_new_gates(self):
        source = Path('strategy_service/rules/crypto.py').read_text(encoding='utf-8')
        base = {'price_above_entry_channel': True, 'dominance_gate_passed': True,
                'price_above_trend_sma': True, 'atr_above_noise_floor': True}
        self.assertTrue(evaluate_local(source, {'checks': base})['enter'])
        for gate in ('price_above_trend_sma', 'atr_above_noise_floor'):
            blocked = {**base, gate: False}
            self.assertFalse(evaluate_local(source, {'checks': blocked})['enter'], gate)


class EquityRegimeGateTests(unittest.TestCase):
    def setUp(self):
        self.leader = daily([100 + index * .5 for index in range(200)])

    def test_rotation_requires_a_bullish_benchmark_regime(self):
        flat = daily([100] * 200)
        signal = equity_signal(self.leader, self.leader[-1]['close'],
                               EQUITY_SETTINGS, flat, rotation_rank=1)
        self.assertFalse(signal['checks']['benchmark_regime_ok'])
        self.assertFalse(signal['checks']['rotation_top_two'])
        self.assertFalse(signal['enter'])

    def test_rotation_enters_when_the_benchmark_confirms(self):
        rising = daily([100 + index * .1 for index in range(200)])
        signal = equity_signal(self.leader, self.leader[-1]['close'],
                               EQUITY_SETTINGS, rising, rotation_rank=1)
        self.assertTrue(signal['checks']['benchmark_regime_ok'])
        self.assertTrue(signal['enter'])
        self.assertEqual(signal['setup'], 'TREND_ROTATION_V1')

    def test_a_bear_regime_blocks_even_strong_relative_momentum(self):
        falling = daily([200 - index * .2 for index in range(200)])
        signal = equity_signal(self.leader, self.leader[-1]['close'],
                               EQUITY_SETTINGS, falling, rotation_rank=1)
        self.assertGreater(signal['checks']['relative_momentum_vs_spy'], 0.1)
        self.assertFalse(signal['enter'])

    def test_the_pullback_setup_also_requires_the_regime(self):
        pullback = daily([100 + index * .3 for index in range(180)] +
                         [200] * 19 + [180])
        flat = daily([100] * 200)
        rising = daily([100 + index * .1 for index in range(200)])
        blocked = equity_signal(pullback, 180, EQUITY_SETTINGS, flat, None)
        self.assertFalse(blocked['checks']['pullback_qualified'])
        self.assertFalse(blocked['enter'])
        admitted = equity_signal(pullback, 180, EQUITY_SETTINGS, rising, None)
        self.assertTrue(admitted['checks']['pullback_qualified'])
        self.assertEqual(admitted['setup'], 'TREND_PULLBACK_V1')

    def test_the_regime_check_is_reported_with_its_average(self):
        rising = daily([100 + index * .1 for index in range(200)])
        signal = equity_signal(self.leader, self.leader[-1]['close'],
                               EQUITY_SETTINGS, rising, rotation_rank=1)
        expected = sum(row['close'] for row in rising[-50:]) / 50
        self.assertAlmostEqual(signal['checks']['benchmark_sma_50'], expected)


if __name__ == '__main__':
    unittest.main()