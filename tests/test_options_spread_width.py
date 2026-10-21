"""Regression tests for the options spread selection and its fundability.

A credit spread's maximum loss is fixed by its width, not by its price, so a
wide spread reserves far more capital per contract than a narrow one. The
engine must prefer the narrowest spread that still meets its duration and
delta targets, because a spread whose risk at the stop exceeds the per-trade
loss cap cannot be funded at all.

The evidence that motivated this is the live provider. NVDA and TSLA are
quoted on a $5 strike ladder, and the widest qualifying spread on NVDA
reserved $1,075 per contract against a $749 per-trade risk cap, so the
module could never open a position. The narrowest qualifying spread
reserves $335.

The quotes below are the live NVDA 2026-11-27 CALL ladder.
"""
import unittest
from datetime import datetime, timezone

from services.portfolio_execution_math import entry_quantity
from services.portfolio_strategy_signals import select_credit_spread

EQUITY = 49959.93
WEIGHT = 27.74
PER_POSITION = EQUITY * WEIGHT / 100 * 0.2
NOW = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)

SETTINGS = {
    'min_ivr': 40, 'target_delta': 18, 'target_dte': 45, 'profit_target_pct': 50,
    'max_friction_ratio': 0.50, 'max_break_even_win_rate': 0.80, 'max_loss_ratio': 0.75,
}

# strike, bid, ask, delta - the live NVDA 2026-11-27 CALL ladder
NVDA_CALL_LADDER = [
    (230.0, 7.10, 7.30, 0.4165),
    (235.0, 5.30, 5.45, 0.3423),
    (240.0, 3.85, 4.00, 0.2736),
    (245.0, 2.72, 2.85, 0.2126),
    (250.0, 1.89, 1.98, 0.1607),
    (255.0, 1.27, 1.39, 0.1186),
]


def ladder(rows, option_type='CALL', expiration='2026-11-27', size=10):
    return [{'symbol': f'{strike:.0f}', 'strike': strike, 'option_type': option_type,
             'expiration': expiration, 'bid': bid, 'ask': ask, 'delta': delta,
             'bid_size': size, 'ask_size': size}
            for strike, bid, ask, delta in rows]


class SpreadWidthSelectionTests(unittest.TestCase):
    """The narrowest qualifying spread must be selected."""

    def _select(self, contracts, price=220.0, kind='CALL'):
        return select_credit_spread(contracts, price, 50, SETTINGS, NOW,
                                    allow_warmup=True, preferred_kind=kind)

    def test_the_narrowest_qualifying_spread_is_preferred(self):
        """A wide spread reserves far more capital per contract."""
        spread = self._select(ladder(NVDA_CALL_LADDER))
        self.assertEqual(spread['width'], 5.0)
        self.assertEqual(spread['short']['strike'], 230.0)
        self.assertEqual(spread['long']['strike'], 235.0)

    def test_a_wide_spread_is_not_selected_when_a_narrow_one_qualifies(self):
        """The $15-wide spread reserved $1,075 per contract on NVDA."""
        wide = [(245.0, 12.60, 12.80, 0.30), (230.0, 7.10, 7.30, 0.4165)]
        spread = self._select(ladder(NVDA_CALL_LADDER + wide))
        self.assertEqual(spread['width'], 5.0)

    def test_the_selected_spread_is_fundable_at_the_per_trade_cap(self):
        """The whole point: a selected spread must be able to open a position."""
        spread = self._select(ladder(NVDA_CALL_LADDER))
        max_loss = spread['width'] - spread['credit']
        stop = spread['credit'] + max_loss * SETTINGS['max_loss_ratio']
        quantity = entry_quantity(
            'options', spread['credit'], PER_POSITION, EQUITY, stop, multiplier=100,
            unit=max_loss * 100, risk_per_unit=(stop - spread['credit']) * 100,
            risk_cap_pct=0.015)
        self.assertGreaterEqual(quantity, 1)

    def test_the_widest_spread_would_not_have_been_fundable(self):
        """Guards the regression this change exists to fix."""
        width, credit = 15.0, 4.25
        max_loss = width - credit
        stop = credit + max_loss * SETTINGS['max_loss_ratio']
        quantity = entry_quantity(
            'options', credit, PER_POSITION, EQUITY, stop, multiplier=100,
            unit=max_loss * 100, risk_per_unit=(stop - credit) * 100,
            risk_cap_pct=0.015)
        self.assertEqual(quantity, 0)

    def test_the_selected_spread_meets_the_break_even_ceiling(self):
        """Narrowing the spread must not bypass the profitability gate."""
        spread = self._select(ladder(NVDA_CALL_LADDER))
        max_loss = spread['width'] - spread['credit']
        win = SETTINGS['profit_target_pct'] / 100 * spread['credit']
        loss = SETTINGS['max_loss_ratio'] * max_loss
        self.assertLessEqual(loss / (win + loss), SETTINGS['max_break_even_win_rate'])

    def test_a_spread_whose_friction_exceeds_its_credit_is_rejected(self):
        """A spread that cannot pay for its own execution is never taken."""
        # The long leg is quoted far above its bid, so the round-trip cost
        # exceeds the credit the spread receives.
        rows = [(230.0, 7.10, 7.30, 0.4165), (235.0, 0.05, 5.45, 0.3423)]
        with self.assertRaises(ValueError):
            self._select(ladder(rows))

    def test_a_spread_whose_break_even_is_too_high_is_rejected(self):
        """The profitability gate still applies to every candidate."""
        rows = [(250.0, 1.89, 1.98, 0.1607), (255.0, 1.27, 1.39, 0.1186)]
        with self.assertRaises(ValueError):
            self._select(ladder(rows))


if __name__ == '__main__':
    unittest.main()
