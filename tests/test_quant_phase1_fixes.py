"""Regression tests for the Phase 1 quantitative strategy fixes.

Covers:
  R1 - credit spread entry/exit are priced on the same executable basis
  R2 - the stop is a risk limit and a spread cannot be born in breach
  R3 - the entry gate rejects spreads that cannot pay for themselves
  R4 - the equity exit oscillator is decoupled from the entry oscillator
  R5 - the per-trade risk cap uses the amount at risk, not reserved collateral
"""
import unittest
from datetime import datetime, timedelta

from services.portfolio_strategy_signals import (
    EXIT_RSI_PERIOD,
    equity_signal,
    rsi,
    select_credit_spread,
)
from services.portfolio_execution_math import entry_quantity

SETTINGS = {
    'equities': {'trend_sma_days': 50, 'rsi_period': 2, 'rsi_entry_threshold': 10,
                 'bollinger_std': 2.0},
    'options': {'min_ivr': 40, 'target_delta': 18, 'target_dte': 45,
                'profit_target_pct': 50, 'max_friction_ratio': 0.50,
                'max_break_even_win_rate': 0.80, 'max_loss_ratio': 0.75},
    'crypto': {'entry_channel_periods': 20, 'exit_channel_periods': 10,
               'atr_stop_multiplier': 2.5},
}


def option_leg(symbol, strike, bid, ask, expiration='2026-11-05', kind='PUT',
               delta=-0.30, size=10):
    return {'symbol': symbol, 'strike': strike, 'bid': bid, 'ask': ask,
            'expiration': expiration, 'option_type': kind, 'delta': delta,
            'bid_size': size, 'ask_size': size}


def daily_bars(closes, start=400.0):
    bars = []
    price = start
    for i, close in enumerate(closes):
        open_price = price
        high = max(open_price, close) * 1.002
        low = min(open_price, close) * 0.998
        bars.append({'open': open_price, 'high': high, 'low': low,
                     'close': close, 'volume': 1000.0,
                     'time': 1700000000 + i * 86400})
        price = close
    return bars


class OptionEntryGateTests(unittest.TestCase):
    """R3 - the entry gate must reject spreads that cannot pay for themselves."""

    def test_thin_credit_spread_is_rejected(self):
        # Credit 0.07 on a $1 width: break-even win rate is 96%.
        contracts = [option_leg('QQQ723', 723.0, 13.91, 14.02),
                     option_leg('QQQ722', 722.0, 13.61, 13.73)]
        with self.assertRaises(ValueError):
            select_credit_spread(contracts, 700.0, 80, SETTINGS['options'],
                                 datetime(2026, 10, 1), allow_warmup=True)

    def test_friction_exceeding_credit_is_rejected(self):
        # Round-trip friction 0.40 against a credit of 0.07.
        contracts = [option_leg('QQQ723', 723.0, 13.50, 14.60),
                     option_leg('QQQ722', 722.0, 13.40, 14.03)]
        with self.assertRaises(ValueError):
            select_credit_spread(contracts, 700.0, 80, SETTINGS['options'],
                                 datetime(2026, 10, 1), allow_warmup=True)

    def test_healthy_spread_is_accepted(self):
        # $2 wide, 0.55 credit, 0.22 round-trip friction. This is the
        # geometry of the one historical trade that passed the gate.
        contracts = [option_leg('QQQ740', 740.0, 18.00, 18.11),
                     option_leg('QQQ738', 738.0, 17.34, 17.45)]
        spread = select_credit_spread(contracts, 750.0, 80, SETTINGS['options'],
                                       datetime(2026, 10, 1), allow_warmup=True)
        self.assertAlmostEqual(spread['credit'], 0.55, places=4)
        self.assertAlmostEqual(spread['width'], 2.0, places=4)
        self.assertAlmostEqual(spread['friction'], 0.22, places=4)
        self.assertLess(spread['break_even_win_rate'], 0.85)
        self.assertLessEqual(spread['friction'], 0.50 * spread['credit'])

    def test_break_even_win_rate_is_reported(self):
        contracts = [option_leg('QQQ740', 740.0, 18.00, 18.11),
                     option_leg('QQQ738', 738.0, 17.34, 17.45)]
        spread = select_credit_spread(contracts, 750.0, 80, SETTINGS['options'],
                                       datetime(2026, 10, 1), allow_warmup=True)
        credit, width = spread['credit'], spread['width']
        target = SETTINGS['options']['profit_target_pct'] / 100
        loss = SETTINGS['options']['max_loss_ratio'] * (width - credit)
        expected = loss / (target * credit + loss)
        self.assertAlmostEqual(spread['break_even_win_rate'], expected, places=6)

    def test_entry_mark_is_the_executable_close_cost(self):
        """R1 - entry_mark must equal credit plus round-trip friction."""
        contracts = [option_leg('QQQ740', 740.0, 18.00, 18.11),
                     option_leg('QQQ738', 738.0, 17.34, 17.45)]
        spread = select_credit_spread(contracts, 750.0, 80, SETTINGS['options'],
                                       datetime(2026, 10, 1), allow_warmup=True)
        self.assertAlmostEqual(spread['entry_mark'],
                               spread['credit'] + spread['friction'], places=6)

    def test_a_spread_cannot_be_born_in_breach_of_its_own_stop(self):
        """R2 - the entry mark must sit below the risk-limit stop."""
        contracts = [option_leg('QQQ740', 740.0, 18.00, 18.11),
                     option_leg('QQQ738', 738.0, 17.34, 17.45)]
        spread = select_credit_spread(contracts, 750.0, 80, SETTINGS['options'],
                                       datetime(2026, 10, 1), allow_warmup=True)
        max_loss = spread['width'] - spread['credit']
        stop = spread['credit'] + max_loss * SETTINGS['options']['max_loss_ratio']
        self.assertLess(spread['entry_mark'], stop)

    def test_a_high_credit_narrow_spread_is_rejected_as_born_in_breach(self):
        """R2 - a $0.90 credit on a $1 width cannot carry $0.20 of friction.

        The risk budget is only $0.10 per contract, so the position would
        open above its own stop. The engine rejects such a spread at entry.
        """
        contracts = [option_leg('QQQ740', 740.0, 18.50, 18.60),
                     option_leg('QQQ739', 739.0, 17.50, 17.60)]
        with self.assertRaises(ValueError):
            select_credit_spread(contracts, 750.0, 80, SETTINGS['options'],
                                 datetime(2026, 10, 1), allow_warmup=True)

    def test_a_wide_thin_credit_spread_is_rejected(self):
        """R3 - a 0.18 credit on a $2 width cannot pay for itself."""
        contracts = [option_leg('QQQ740', 740.0, 17.69, 17.88),
                     option_leg('QQQ738', 738.0, 17.33, 17.51)]
        with self.assertRaises(ValueError):
            select_credit_spread(contracts, 750.0, 80, SETTINGS['options'],
                                 datetime(2026, 10, 1), allow_warmup=True)


class EquityExitOscillatorTests(unittest.TestCase):
    """R4 - the exit oscillator must not reuse the entry oscillator period."""

    def test_exit_uses_a_standard_period_oscillator(self):
        self.assertEqual(EXIT_RSI_PERIOD, 14)

    def test_exit_does_not_fire_on_a_two_period_rsi(self):
        # Real AMZN closes from the archived market data. The 2-period RSI
        # reads overbought (79.6) while the 14-period oscillator is neutral
        # (32.5). The legacy exit closed the position on this signal.
        closes = [166.72, 170.4, 167.52, 164.36, 163.25, 162.55, 161.49, 165.36,
                  165.21, 161.21, 162.14, 158.92, 156.3, 151.67, 142.64, 144.54,
                  139.99, 138.87, 139.64, 143.98]
        closes = ([100.0 + i * 0.2 for i in range(60)] + closes)
        bars = daily_bars(closes)
        benchmark = daily_bars([100.0 + i * 0.4 for i in range(len(closes))])
        signal = equity_signal(bars, closes[-1], SETTINGS['equities'], benchmark,
                                rotation_rank=1)
        entry_rsi = rsi(closes, 2)
        exit_rsi = rsi(closes, EXIT_RSI_PERIOD)
        self.assertGreater(entry_rsi, 70,
                           'the 2-period RSI should read overbought here')
        self.assertLess(exit_rsi, 70,
                        'the 14-period RSI should stay neutral here')
        self.assertFalse(signal['exit'],
                         'A saturated 2-period RSI must not close the position.')
        self.assertIn('exit_rsi', signal['checks'])

    def test_exit_still_fires_when_price_breaks_the_trend_average(self):
        closes = [100 + i for i in range(80)]
        bars = daily_bars(closes)
        benchmark = daily_bars([100 + i * 0.5 for i in range(80)])
        average = sum(closes[-50:]) / 50
        signal = equity_signal(bars, average - 5, SETTINGS['equities'], benchmark,
                                rotation_rank=1)
        self.assertTrue(signal['exit'])

    def test_entry_pullback_still_uses_the_configured_period(self):
        closes = [100 + i for i in range(80)]
        bars = daily_bars(closes)
        benchmark = daily_bars([100 + i * 0.5 for i in range(80)])
        signal = equity_signal(bars, closes[-1], SETTINGS['equities'], benchmark,
                                rotation_rank=1)
        self.assertEqual(signal['checks']['rsi'],
                         rsi(closes, SETTINGS['equities']['rsi_period']))

    def test_exit_rsi_is_reported_separately_from_entry_rsi(self):
        closes = ([100.0 + i * 0.2 for i in range(60)] +
                  [166.72, 170.4, 167.52, 164.36, 163.25, 162.55, 161.49,
                   165.36, 165.21, 161.21, 162.14, 158.92, 156.3, 151.67,
                   142.64, 144.54, 139.99, 138.87, 139.64, 143.98])
        bars = daily_bars(closes)
        benchmark = daily_bars([100.0 + i * 0.4 for i in range(len(closes))])
        signal = equity_signal(bars, closes[-1], SETTINGS['equities'], benchmark,
                                rotation_rank=1)
        self.assertEqual(signal['checks']['exit_rsi'],
                         rsi(closes, EXIT_RSI_PERIOD))
        self.assertNotEqual(signal['checks']['exit_rsi'],
                            signal['checks']['rsi'])


class PositionSizingTests(unittest.TestCase):
    """R5 - the loss cap must be applied to the amount actually at risk."""

    def test_risk_per_unit_overrides_the_collateral_fallback(self):
        equity = 48766.24
        # A $1 wide spread with a 0.30 credit: collateral and max loss agree.
        quantity = entry_quantity('options', 0.30, 1000.0, equity, None,
                                  multiplier=100, unit=70.0, risk_per_unit=70.0)
        self.assertGreater(quantity, 0)

    def test_max_loss_basis_allows_a_wider_spread(self):
        equity = 48766.24
        cap = equity * 0.005
        # A $2 wide spread at 0.55 credit: max loss is $145 per contract.
        max_loss = 145.0
        quantity = entry_quantity('options', 0.55, 1000.0, equity, None,
                                  multiplier=100, unit=145.0, risk_per_unit=max_loss)
        self.assertEqual(quantity, int(cap / (max_loss + 2 * 1.30)))

    def test_risk_cap_rejects_an_unfundable_strike_spacing(self):
        equity = 48766.24
        # A $10 wide spread on a high-priced underlying: $900 at risk per
        # contract exceeds the $243.83 per-trade budget.
        quantity = entry_quantity('options', 0.55, 5000.0, equity, None,
                                  multiplier=100, unit=900.0, risk_per_unit=900.0)
        self.assertEqual(quantity, 0)

    def test_stop_based_risk_is_unchanged(self):
        equity = 48766.24
        quantity = entry_quantity('equities', 100.0, 1000.0, equity, 90.0,
                                  multiplier=1, unit=100.0)
        self.assertGreater(quantity, 0)


if __name__ == '__main__':
    unittest.main()
