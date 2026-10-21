"""Prove the Phase 2 evidence-consistency validator blocks the false audit.

Audit id 52 (2026-10-20, provider 'zai') declared the Events module
"effectively frozen" by an exhausted loss allowance and reported "2,480
entries were rejected in the last 24 hours". Its own evidence payload
contradicted both claims. This test replays that exact audit against the
validator and asserts it is now rejected.
"""
import json
import unittest

from services.portfolio_audit_context import (
    IncompleteAuditError,
    check_audit_evidence,
    check_evidence_consistency,
)

FALSE_CLAIM = """
## 3.5 Events Module (Status: NO_SIGNAL / RISK_BLOCKED)
The Events module is effectively frozen. A risk policy logic error is
exhausting the daily loss allowance after only a few hours of operation,
blocking all new entries. Consequently, 2,480 entries were rejected in the
last 24 hours alone.
"""


def evidence_fixture():
    """The evidence payload exactly as audit 52 received it."""
    return {
        'decision_summary_24h': {
            'equities': {'evaluated': 650, 'qualified': 130, 'filled': 1, 'blocked': 129},
            'options': {'evaluated': 325, 'qualified': 238, 'filled': 1, 'blocked': 237},
            'crypto': {'evaluated': 822, 'qualified': 10, 'filled': 1, 'blocked': 9},
            'events': {'evaluated': 0, 'qualified': 0, 'filled': 0, 'blocked': 0},
        },
        'modules': {
            'events': {
                'status': 'NO_SIGNAL',
                'messages': ['Observed Event contracts are closed or outside the saved entry window; '
                             'no AI evaluation required.'],
                'entries_paused': False,
                'risk_policy': {
                    'reason': None,
                    'remaining_loss_allowance': 10.0,
                    'aggregate_loss_limits_enforced': False,
                    'open_positions': 0,
                    'open_dollars': 0,
                },
                'rejected_entries': [
                    {'status': 'REJECTED',
                     'reason': 'Saved Event hourly, daily or drawdown loss allowance is exhausted '
                               'after reserving open risk.',
                     'recorded_at': '2026-09-18T22:10:35.374774Z'},
                ],
            },
            'options': {
                'status': 'MARKET_CLOSED',
                'entries_paused': False,
                'risk_policy': {'reason': None, 'remaining_loss_allowance': 10.0,
                                'aggregate_loss_limits_enforced': False},
            },
        },
    }


class EvidenceConsistencyTests(unittest.TestCase):
    def test_false_frozen_events_claim_is_rejected(self):
        with self.assertRaises(IncompleteAuditError) as caught:
            check_evidence_consistency(FALSE_CLAIM, evidence_fixture())
        self.assertIn('blocked', str(caught.exception).lower())

    def test_a_blocked_claim_is_allowed_when_the_evidence_supports_it(self):
        evidence = evidence_fixture()
        evidence['modules']['events']['risk_policy']['reason'] = \
            'Saved Event open-position limit reached, including pending settlements.'
        evidence['modules']['events']['entries_paused'] = True
        check_evidence_consistency(FALSE_CLAIM, evidence)

    def test_a_blocked_claim_is_allowed_when_the_24h_count_shows_blocks(self):
        evidence = evidence_fixture()
        evidence['decision_summary_24h']['events'] = {
            'evaluated': 900, 'qualified': 0, 'filled': 0, 'blocked': 900}
        check_evidence_consistency(FALSE_CLAIM, evidence)

    def test_unrelated_claims_are_not_rejected(self):
        text = """
## 3.2 Options Module
The Options module is the largest drag, with a 1-in-18 win rate.
The Equities module holds five positions with slight unrealized losses.
"""
        check_evidence_consistency(text, evidence_fixture())

    def test_drawdown_guard_still_works(self):
        evidence = evidence_fixture()
        evidence['performance'] = {'max_drawdown_pct': 4.44}
        with self.assertRaises(IncompleteAuditError):
            check_audit_evidence('Observed max drawdown was 12.0%.', evidence)
        check_audit_evidence('Observed max drawdown was 4.45%.', evidence)

    def test_no_evidence_leaves_the_claim_uncheckable(self):
        check_evidence_consistency(FALSE_CLAIM, {})


if __name__ == '__main__':
    unittest.main()
