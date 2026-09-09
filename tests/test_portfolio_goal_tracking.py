import unittest
from datetime import datetime, timedelta, timezone

from services.portfolio_goal_tracking import build_goal_tracking
from services.portfolio_audit_context import (
    DEFAULT_AUDIT_GUIDANCE, EVIDENCE_RULES, audit_prompt_policy, audit_system_prompt,
)


class PortfolioGoalTrackingTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def goal(self, days=365, **changes):
        end = self.start+timedelta(days=days)
        kwargs = dict(initial_balance=50000, current_equity=55000, cash_balance=25000,
                      target_annual_return=18.5, started_at=self.start, as_of=end,
                      snapshots=[{'time': self.start, 'equity': 50000}, {'time': end, 'equity': 55000}],
                      module_pnl={'equities': 4000, 'events': 1000}, reserved_capital=29000)
        kwargs.update(changes)
        return build_goal_tracking(**kwargs)

    def test_one_year_target_and_gap_are_code_calculated(self):
        result = self.goal()
        self.assertAlmostEqual(result['target_equity'], 59250)
        self.assertAlmostEqual(result['target_gap_usd'], -4250)
        self.assertAlmostEqual(result['target_gap_pct'], -4250/59250*100)
        self.assertAlmostEqual(result['annualized_return_pct'], 10)
        self.assertAlmostEqual(result['cagr_gap_pct_points'], -8.5)
        self.assertEqual(result['mode'], 'PAPER')

    def test_first_day_comparison_does_not_invent_annualized_evidence(self):
        result = self.goal(days=1, current_equity=50000)
        self.assertGreater(result['target_equity'], 50000)
        self.assertIsNone(result['annualized_return_pct'])
        self.assertIsNone(result['cagr_gap_pct_points'])
        self.assertEqual(result['annualization_status'], 'INSUFFICIENT_HISTORY')
        self.assertIsNone(result['rolling_returns']['30']['return_pct'])

    def test_reset_inception_not_first_snapshot_controls_elapsed_time(self):
        result = self.goal(days=365, snapshots=[{'time': self.start+timedelta(days=364), 'equity': 54000}])
        self.assertAlmostEqual(result['annualized_return_pct'], 10)
        self.assertEqual(result['elapsed_days'], 365)
        self.assertEqual(result['observations']['observed_calendar_days'], 1)
        self.assertEqual(result['observations']['missing_calendar_days'], 365)
        self.assertEqual(result['curve'][0]['equity'], 50000)

    def test_thirty_days_only_enables_descriptive_annualization(self):
        self.assertIsNone(self.goal(days=29.9)['annualized_return_pct'])
        result = self.goal(days=30)
        self.assertIsNotNone(result['annualized_return_pct'])
        self.assertEqual(result['annualization_status'], 'DESCRIPTIVE_ONLY')
        self.assertIn('not statistical validation', result['annualization_note'])

    def test_rolling_returns_use_real_boundary_and_reveal_gaps(self):
        result = self.goal(days=100, snapshots=[
            {'time': self.start+timedelta(days=69.5), 'equity': 52000},
            {'time': self.start+timedelta(days=100), 'equity': 55000},
        ])
        window = result['rolling_returns']['30']
        self.assertAlmostEqual(window['return_pct'], (55000/52000-1)*100)
        self.assertEqual(window['actual_elapsed_days'], 30.5)
        self.assertGreater(window['missing_calendar_days'], 0)
        self.assertIsNone(result['rolling_returns']['90']['return_pct'])

    def test_rolling_never_uses_future_or_stale_anchor(self):
        for anchor in (68.9, 70.1):
            with self.subTest(anchor=anchor):
                result = self.goal(days=100, snapshots=[{'time': self.start+timedelta(days=anchor), 'equity': 52000}])
                self.assertIsNone(result['rolling_returns']['30']['return_pct'])

    def test_module_contributions_reconcile_and_expose_missing_attribution(self):
        result = self.goal(module_pnl={'equities': 4400, 'events': -20})
        self.assertEqual(result['unattributed_pnl_usd'], 620)
        self.assertAlmostEqual(result['module_contributions'][0]['contribution_pct_points'], 8.8)
        self.assertAlmostEqual(result['capital_utilization_pct'], 30000/55000*100)
        self.assertEqual(result['reserved_capital_usd'], 29000)

    def test_snapshot_gaps_and_invalid_values_are_not_filled(self):
        result = self.goal(days=4, snapshots=[
            {'time': self.start, 'equity': 50000},
            {'time': self.start+timedelta(days=3), 'equity': 55000},
            {'time': self.start+timedelta(days=3), 'equity': 55001},
            {'time': 'invalid', 'equity': 9},
            {'time': self.start+timedelta(days=2), 'equity': float('nan')},
            {'time': self.start-timedelta(days=1), 'equity': 80000},
        ])
        coverage = result['observations']
        self.assertEqual(coverage['invalid_snapshot_count'], 2)
        self.assertEqual(coverage['snapshot_count'], 2)
        self.assertEqual(coverage['missing_calendar_days'], 3)
        self.assertEqual(coverage['gap_ranges'][0], {'start': '2025-01-02', 'end': '2025-01-03', 'days': 2})
        self.assertEqual(len(result['curve']), 3)

    def test_stale_asof_cannot_be_misrepresented_as_a_later_return(self):
        result = self.goal(days=10)
        self.assertEqual(result['as_of'], '2025-01-11T00:00:00Z')
        self.assertEqual(result['elapsed_days'], 10)

    def test_utc_timestamps_and_invalid_ledger_inputs(self):
        result = self.goal(started_at='2024-12-31T19:00:00-05:00')
        self.assertEqual(result['started_at'], '2025-01-01T00:00:00Z')
        for changes in ({'initial_balance': 0}, {'current_equity': float('inf')}, {'target_annual_return': -100}, {'as_of': self.start-timedelta(days=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.goal(**changes)

    def test_updated_numeric_target_changes_reference_without_rewriting_results(self):
        result = self.goal(target_annual_return=12)
        self.assertAlmostEqual(result['target_equity'], 56000)
        self.assertAlmostEqual(result['cagr_gap_pct_points'], -2)
        self.assertEqual(result['current_equity'], 55000)

    def test_prompt_guidance_is_editable_visible_and_preserves_custom_mandates(self):
        custom = 'My saved custom legacy target 16.5–21%.'
        prompt = audit_system_prompt(custom, guidance='Prioritize my named experiment.')
        self.assertTrue(prompt.startswith(custom))
        self.assertIn('Prioritize my named experiment.', prompt)
        self.assertNotIn(DEFAULT_AUDIT_GUIDANCE, prompt)
        self.assertIn('authoritative over legacy ranges', prompt)
        policy = audit_prompt_policy()
        self.assertEqual(policy['evidence_rules'], EVIDENCE_RULES)
        self.assertEqual(policy['default_guidance'], DEFAULT_AUDIT_GUIDANCE)
        self.assertIn(policy['module_scope'], audit_system_prompt(custom, 'events'))


if __name__ == '__main__':
    unittest.main()
