"""Regression tests for the Event entry quality gates.

Two floors keep the Event module from trading without thought or purpose:

1. The net edge must survive the ledger's actual paper commission, even when
   the saved signal config reserves a smaller fee (fee-aware edge floor).
2. The model probability must diverge from the midpoint of the executable
   book being bought. A forecast that merely echoes the market midpoint has
   no informational edge; the apparent gross edge is just the spread.
"""
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from event_algo import DEFAULT_SIGNAL_CONFIG, evaluate_market, normalize_config_payload
from services import portfolio_event_execution as handoff


def market(now=None, **changes):
    now = now or datetime.utcnow()
    return {'symbol': 'KXBTC15M-TEST', 'series_symbol': 'KXBTC15M',
            'tradable_status': 'OC', 'yes_bid': .49, 'yes_ask': .50,
            'no_bid': .49, 'no_ask': .50, 'volume': 500, 'open_interest': 100,
            'quote_as_of': now.isoformat() + 'Z',
            'cutoff_at': (now + timedelta(minutes=10)).isoformat() + 'Z', **changes}


def config(signal=None):
    return SimpleNamespace(risk_config='{}', kill_switch=False,
                           signal_config=json.dumps(signal or {}))


class ModelDivergenceGateTests(unittest.TestCase):
    """The model must disagree with the market midpoint, not echo it."""

    def setUp(self):
        self.now = datetime.utcnow()
        # Fees and uncertainty are zeroed so the net-edge floor alone would
        # admit a forecast sitting almost on top of the midpoint. The
        # divergence gate is the independent backstop under test.
        self.signal = {'fee_per_contract': 0, 'uncertainty_buffer': 0, 'min_net_edge': .01}

    def evaluate(self, probability, signal=None, **changes):
        return evaluate_market({**market(self.now, **changes),
                                'model_probability_yes': probability,
                                'model_confidence': .9},
                               config(signal if signal is not None else self.signal), now=self.now)

    def test_the_shipped_default_is_three_points(self):
        self.assertEqual(DEFAULT_SIGNAL_CONFIG['min_model_divergence'], 0.03)

    def test_the_setting_is_normalized_and_clamped(self):
        normalized = normalize_config_payload(
            {'signal_config': {'min_model_divergence': 0.05}}, user_id=7)
        self.assertEqual(normalized['signal_config']['min_model_divergence'], 0.05)
        clamped = normalize_config_payload(
            {'signal_config': {'min_model_divergence': 5}}, user_id=7)
        self.assertEqual(clamped['signal_config']['min_model_divergence'], 1.0)

    def test_a_forecast_echoing_the_midpoint_is_rejected(self):
        # Midpoint .495; probability .515 clears the .01 net-edge floor
        # (gross .015 less half-spread .005) but diverges only .02.
        decision = self.evaluate(.515)
        self.assertFalse(decision['eligible'])
        self.assertIn('MODEL_TOO_CLOSE_TO_MARKET', decision['reason_codes'])
        self.assertNotIn('EDGE_TOO_SMALL_AFTER_FEES', decision['reason_codes'])
        self.assertEqual(decision['model_divergence'], .02)

    def test_a_genuinely_divergent_forecast_is_admitted(self):
        decision = self.evaluate(.53)
        self.assertTrue(decision['eligible'], decision['reason_codes'])
        self.assertEqual(decision['outcome'], 'YES')
        self.assertEqual(decision['model_divergence'], .035)

    def test_the_no_side_is_gated_on_its_own_book(self):
        # probability_no .515 against the NO midpoint .495 diverges .02.
        decision = self.evaluate(.485)
        self.assertEqual(decision['outcome'], 'NO')
        self.assertFalse(decision['eligible'])
        self.assertIn('MODEL_TOO_CLOSE_TO_MARKET', decision['reason_codes'])

    def test_the_gate_is_configurable(self):
        decision = self.evaluate(.515, signal={**self.signal, 'min_model_divergence': .01})
        self.assertTrue(decision['eligible'], decision['reason_codes'])

    def test_the_default_fees_already_imply_a_divergence_floor(self):
        # With the shipped fee, uncertainty and edge floors, any admitted
        # YES forecast diverges by at least .04 plus the full spread, so the
        # .03 gate never silently tightens the default behavior.
        decision = evaluate_market({**market(self.now, yes_bid=.39, yes_ask=.42),
                                    'model_probability_yes': .48, 'model_confidence': .9},
                                   config(), now=self.now)
        self.assertTrue(decision['eligible'], decision['reason_codes'])
        self.assertGreaterEqual(decision['model_divergence'], .04)


class FeeAwareEdgeFloorTests(unittest.TestCase):
    """The handoff must reserve the ledger's real commission, not just the
    fee saved in the signal config."""

    def setUp(self):
        self.now = datetime.utcnow()
        self.decision = SimpleNamespace(user_id=1, created_at=self.now,
                                        contract_symbol='KXBTC15M-TEST',
                                        probability_yes=.43, confidence=.9, outcome='YES')
        self.settings = {'min_confidence': .5, 'min_net_edge': .015}
        self.service_patch = patch('services.strategy_client.evaluate', return_value={
            'enter': True, 'setup': 'EVENT_EDGE_V1', 'strategy_version': 'test',
            'code_sha256': 'a' * 64, 'reason': 'Qualified.'})
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

    def validate(self, signal=None, probability=None):
        if probability is not None:
            self.decision.probability_yes = probability
        quote = market(self.now, yes_bid=.39, yes_ask=.40, no_bid=.60, no_ask=.62)
        return handoff.validate_entry(self.decision, quote,
                                      config(signal), self.settings, ['KXBTC15M'], self.now)

    def test_a_zero_configured_fee_still_reserves_the_ledger_commission(self):
        # Gross edge .03 survives the zero-fee signal math (.015 net) but not
        # the ledger's .015 commission: .015 - .015 = 0 < .015.
        status, message, _ = self.validate(signal={'fee_per_contract': 0, 'min_net_edge': .01})
        self.assertEqual(status, 'REJECTED')
        self.assertIn('net edge after all costs', message)

    def test_the_same_quote_passes_when_the_edge_covers_the_commission(self):
        status, _, assessment = self.validate(signal={'fee_per_contract': 0, 'min_net_edge': .01},
                                              probability=.8)
        self.assertIsNone(status)
        self.assertGreaterEqual(assessment['net_edge'], self.settings['min_net_edge'])

    def test_the_configured_fee_is_not_double_counted(self):
        # The default signal fee already equals the ledger commission, so no
        # extra gap is reserved and the strong edge passes untouched.
        status, _, _ = self.validate(probability=.8)
        self.assertIsNone(status)


if __name__ == '__main__':
    unittest.main()