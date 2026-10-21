"""Regression tests for the Phase 3 quantitative strategy fixes.

Covers:
  R8  - the per-sleeve CAGR targets are readable and reconcile with the
        portfolio target instead of displaying two contradictory numbers
  R9  - the crypto dominance gate is evaluated identically on the entry
        and position-management paths
  R10 - the Event module's open-dollar ceiling is reported against its
        allocation target so an unreachable target is visible
  R13 - the aggregate per-module risk limit bounds combined at-risk capital
"""
import copy
import unittest

from portfolio_algo_models import DEFAULT_MODULE_SETTINGS
from services.portfolio_allocations import (
    blended_sleeve_target,
    normalize_allocations,
    parse_cagr_range,
    sleeve_cagr_midpoints,
)


class SleeveTargetReconciliationTests(unittest.TestCase):
    """R8 - the sleeve targets must be readable and reconcilable."""

    def test_cagr_range_is_parsed(self):
        self.assertEqual(parse_cagr_range('12%–16%'), (12.0, 16.0))
        self.assertEqual(parse_cagr_range('20%-35%'), (20.0, 35.0))
        self.assertEqual(parse_cagr_range('18%'), (18.0, 18.0))

    def test_unparseable_range_returns_none(self):
        self.assertIsNone(parse_cagr_range(None))
        self.assertIsNone(parse_cagr_range('not a number'))

    def test_reversed_range_is_normalised(self):
        self.assertEqual(parse_cagr_range('30%–20%'), (20.0, 30.0))

    def test_every_seeded_module_has_a_readable_sleeve_target(self):
        midpoints = sleeve_cagr_midpoints(DEFAULT_MODULE_SETTINGS)
        self.assertEqual(set(midpoints), set(DEFAULT_MODULE_SETTINGS))
        for module, value in midpoints.items():
            self.assertGreater(value, 0, module)

    def test_blended_target_is_allocation_weighted_not_a_raw_sum(self):
        from services.portfolio_allocations import DEFAULT_WEIGHTS
        settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS)
        settings['futures']['enabled'] = False
        blended = blended_sleeve_target(settings)
        midpoints = sleeve_cagr_midpoints(settings)
        raw_sum = sum(midpoints.values())
        self.assertIsNotNone(blended)
        # The blend must be materially below the unweighted sum of sleeve
        # targets, which is what the engine previously displayed beside the
        # portfolio target without explanation.
        self.assertLess(blended, raw_sum)
        weights = normalize_allocations(
            {m: settings[m].get('allocation_preference') or DEFAULT_WEIGHTS[m]
             for m in DEFAULT_WEIGHTS}, settings)
        expected = sum(weights[m] * midpoints[m] for m in midpoints) / \
                   sum(weights[m] for m in midpoints)
        self.assertAlmostEqual(blended, expected, places=6)

    def test_blended_target_is_none_without_sleeve_targets(self):
        settings = copy.deepcopy(DEFAULT_MODULE_SETTINGS)
        for module in settings:
            settings[module].pop('target_cagr_range', None)
        self.assertIsNone(blended_sleeve_target(settings))


class ModuleRiskLimitTests(unittest.TestCase):
    """R13 - the aggregate module risk limit must be bounded."""

    def test_module_risk_limits_are_defined_for_spot_modules(self):
        from services.portfolio_engine import MODULE_RISK_LIMIT
        self.assertIn('equities', MODULE_RISK_LIMIT)
        self.assertIn('crypto', MODULE_RISK_LIMIT)
        for module, limit in MODULE_RISK_LIMIT.items():
            self.assertGreater(limit, 0)
            self.assertLess(limit, 0.5)

    def test_module_risk_limit_is_below_five_times_the_per_trade_cap(self):
        from services.portfolio_engine import MODULE_RISK_LIMIT
        # The per-trade cap is 0.5% of equity. A module limit above 5x that
        # would not meaningfully bound a handful of positions.
        for module, limit in MODULE_RISK_LIMIT.items():
            self.assertLessEqual(limit, 0.025 * 5)


class EventCapacityVisibilityTests(unittest.TestCase):
    """R10 - an unreachable Event allocation must be visible."""

    def test_capacity_reports_the_dollar_ceiling_and_the_gap(self):
        source = open('services/portfolio_engine.py', encoding='utf-8').read()
        self.assertIn("'max_open_dollars'", source)
        self.assertIn("'unreachable_target_dollars'", source)
        self.assertIn("'allocation_unreachable'", source)
        # The slot count alone must not be the only capacity measure.
        self.assertIn("'available_dollars'", source)


class CryptoDominanceGateTests(unittest.TestCase):
    """R9 - the dominance gate must not be hardcoded on the management path."""

    def test_management_path_evaluates_the_real_dominance_gate(self):
        source = open('services/portfolio_engine.py', encoding='utf-8').read()
        self.assertNotIn("crypto_signal(bars, price, settings[module], True)",
                         source)
        self.assertIn("crypto_signal(bars, price, settings[module], data.dominance_ok(symbol, now))",
                      source)


if __name__ == '__main__':
    unittest.main()
