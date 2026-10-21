"""Regression tests for the options module's capacity limits.

A credit spread's maximum loss is fixed by its width, not by its price, so
a flat loss cap sized a $1 ladder to one contract and a $5 ladder to zero.
These tests pin the behaviour that makes every listed spread fundable while
the module's aggregate exposure stays bounded.
"""
import unittest

from services.portfolio_execution_math import entry_quantity
from services.portfolio_engine import (
    MAX_POSITIONS_PER_MODULE,
    MODULE_RISK_LIMIT,
    TRADE_RISK_CAP,
)

EQUITY = 49967.40
BUCKET = EQUITY * 0.24962727272727268
PER_POSITION = BUCKET * 0.2
FEE = 1.30


class OptionsFundabilityTests(unittest.TestCase):
    """Every strike ladder the provider offers must be fundable."""

    def _quantity(self, width, credit, cap_pct):
        max_loss = (width - credit) * 100
        return entry_quantity('options', credit, PER_POSITION, EQUITY, None,
                              multiplier=100, unit=max_loss, risk_per_unit=max_loss,
                              risk_cap_pct=cap_pct)

    def test_a_one_dollar_ladder_is_fundable(self):
        self.assertGreaterEqual(self._quantity(1.0, 0.30, TRADE_RISK_CAP['options']), 1)

    def test_a_two_dollar_ladder_is_fundable(self):
        self.assertGreaterEqual(self._quantity(2.0, 0.60, TRADE_RISK_CAP['options']), 1)

    def test_a_five_dollar_ladder_is_fundable(self):
        """NVDA and TSLA are quoted on a $5 ladder. They must not be unfundable."""
        self.assertGreaterEqual(self._quantity(5.0, 1.50, TRADE_RISK_CAP['options']), 1)

    def test_a_ten_dollar_ladder_is_fundable(self):
        self.assertGreaterEqual(self._quantity(10.0, 3.00, TRADE_RISK_CAP['options']), 1)

    def test_the_old_flat_cap_could_not_fund_a_five_dollar_ladder(self):
        """Guards the regression this change exists to fix."""
        self.assertEqual(self._quantity(5.0, 1.50, 0.005), 0)

    def test_the_position_budget_is_not_the_binding_constraint(self):
        """The per-position budget allows far more contracts than the risk cap."""
        max_loss = (2.0 - 0.60) * 100
        by_budget = int(PER_POSITION / (max_loss + FEE))
        by_risk = self._quantity(2.0, 0.60, TRADE_RISK_CAP['options'])
        self.assertLess(by_risk, by_budget)

    def test_risk_cap_defaults_to_half_a_percent_for_spot_modules(self):
        for module in ('equities', 'crypto', 'futures', 'events'):
            self.assertEqual(TRADE_RISK_CAP[module], 0.005, module)

    def test_the_options_risk_cap_is_within_the_module_aggregate_limit(self):
        """A single trade can never exceed the module's aggregate budget."""
        self.assertLessEqual(TRADE_RISK_CAP['options'], MODULE_RISK_LIMIT['options'])

    def test_the_module_aggregate_limit_bounds_every_concurrent_position(self):
        """Even at the maximum position count, aggregate risk stays bounded."""
        cap = TRADE_RISK_CAP['options']
        positions = MAX_POSITIONS_PER_MODULE['options']
        self.assertLessEqual(cap * positions, MODULE_RISK_LIMIT['options'])

    def test_spot_sizing_is_unchanged(self):
        """The spot path keeps its original budget-and-risk sizing."""
        quantity = entry_quantity('equities', 100.0, 1000.0, EQUITY, 90.0,
                                  multiplier=1, unit=100.0)
        # The budget binds before the risk cap for a $1,000 spot position.
        self.assertEqual(quantity, int(1000.0 / (100.0 + 0.10)))

    def test_a_position_with_no_stop_still_uses_the_collateral(self):
        quantity = entry_quantity('equities', 100.0, 1000.0, EQUITY, None,
                                  multiplier=1, unit=100.0)
        self.assertGreater(quantity, 0)


class ModulePositionLimitTests(unittest.TestCase):
    def test_every_module_has_a_position_limit(self):
        for module in ('equities', 'options', 'crypto', 'futures', 'events'):
            self.assertIn(module, MAX_POSITIONS_PER_MODULE)
            self.assertGreater(MAX_POSITIONS_PER_MODULE[module], 0)

    def test_the_options_module_can_hold_several_positions(self):
        """A defined-risk spread book needs more than one position."""
        self.assertGreater(MAX_POSITIONS_PER_MODULE['options'], 1)


if __name__ == '__main__':
    unittest.main()
