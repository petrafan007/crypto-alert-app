"""Regression tests for the v4.12.1 cross-symbol contamination fix.

Production evidence (Oct 21, 2026): ETH live-gate evaluations were
recorded carrying BTC's price ($84,783.08) on a 15-bar stub series, and
the outcome evaluator then graded six healthy ETH evaluations from
those rows, printing fake +3,363% returns. These tests pin the guards
that now prevent it: gate evidence integrity (bar floor, price coherence
with the asset's own recent band) and outcome-quote plausibility.
"""
import json
from datetime import timedelta
from unittest.mock import Mock, patch

from core.extensions import db
from models import JevEvaluation
from services import portfolio_engine as engine
from services.decision_contracts import build_crypto_quant_questions
from services.decision_evaluations import create_evaluation, get_evaluation, update_evaluation
from services.decision_outcomes import evaluate_pending_outcomes
from services.decision_quant import build_state, evaluate_entry
from tests.decision_helpers import DecisionTestCase, noul_payload, response_for


def quant_payload(probability):
    questions = build_crypto_quant_questions()
    payload = noul_payload(questions)
    payload['answers']['confirm_entry'] = {'type': 'noul', 'noul': probability}
    return payload


def signal_with(checks, enter=True):
    return {'enter': enter, 'setup': 'DONCHIAN_DOMINANCE_V1', 'checks': checks}


HEALTHY_CHECKS = {'completed_hourly_bars': 150, 'entry_channel_high': 2501.0,
                  'price_above_entry_channel': True, 'dominance_gate_passed': True,
                  'atr_period': 14, 'atr': 21.5}


class QuantGateIntegrityTests(DecisionTestCase):
    def seed_eth_history(self, prices=(2448.0, 2451.0, 2449.0)):
        for index, price in enumerate(prices):
            state = build_state('ETH', price, signal_with(HEALTHY_CHECKS),
                                self.now - timedelta(hours=3 - index))
            create_evaluation(1, 'quant_crypto', state, self.config)

    def test_gate_rejects_an_eth_candidate_priced_like_btc(self):
        self.seed_eth_history()
        before = JevEvaluation.query.filter_by(use_case='quant_crypto').count()
        result = evaluate_entry(1, 'ETH', 84783.08,
                                signal_with({'completed_hourly_bars': 150,
                                             'entry_channel_high': 99000.0,
                                             'price_above_entry_channel': False,
                                             'dominance_gate_passed': False,
                                             'atr_period': 14, 'atr': 4200.0}),
                                self.now, self.config)
        self.assertEqual(result['verdict'], 'ABSTAIN')
        self.assertIn('integrity guard', result['reason'])
        self.assertEqual(JevEvaluation.query.filter_by(use_case='quant_crypto').count(), before)

    def test_gate_rejects_thin_evidence(self):
        result = evaluate_entry(1, 'ETH', 2450.0,
                                signal_with({'completed_hourly_bars': 15,
                                             'entry_channel_high': 2520.0,
                                             'price_above_entry_channel': False,
                                             'dominance_gate_passed': False,
                                             'atr_period': 14, 'atr': 16.6}),
                                self.now, self.config)
        self.assertEqual(result['verdict'], 'ABSTAIN')
        self.assertIn('integrity guard', result['reason'])
        self.assertEqual(JevEvaluation.query.filter_by(use_case='quant_crypto').count(), 0)


class EthEndToEndTests(DecisionTestCase):
    def configure_portfolio(self):
        cfg, acc, state = engine.ensure_portfolio(1)
        values = engine.settings_for(cfg)
        for module in values:
            values[module]['enabled'] = module == 'crypto'
        cfg.module_settings_json = json.dumps(values)
        cfg.watchlists_json = json.dumps({'crypto': ['ETH']})
        cfg.enabled = True
        state.kill_switch = False
        db.session.commit()
        return cfg, acc, state

    def market(self):
        data = Mock()
        data.quote.return_value = 2600.0
        data.bars.return_value = [{'time': (self.now - timedelta(hours=200 - i)).timestamp(),
                                   'high': 2501, 'low': 2499, 'close': 2500, 'volume': 1000}
                                  for i in range(150)]
        data.dominance_ok.return_value = True
        return data

    def test_eth_candidate_records_eth_price_series(self):
        self.configure_portfolio()
        with patch('services.decision_engine.requests.post',
                   return_value=Mock(status_code=200, json=lambda: quant_payload(.95))):
            result = engine.run_scan(1, force=True, provider=self.market())
        self.assertTrue(result['success'], result)
        row = JevEvaluation.query.filter_by(use_case='quant_crypto').one()
        self.assertEqual(row.symbol, 'ETH')
        self.assertEqual(row.entry_price, 2600.0)
        state = json.loads(row.state_json)
        self.assertEqual(state['current_price'], 2600.0)
        self.assertEqual(state['features']['entry_channel_high'], 2501)
        self.assertEqual(state['features']['completed_hourly_bars'], 150)
        self.assertEqual(row.action_taken, 'confirm')


class OutcomeIntegrityTests(DecisionTestCase):
    def graded_candidate(self):
        state = build_state('ETH', 2450.0, signal_with(HEALTHY_CHECKS),
                            self.now - timedelta(hours=25))
        evaluation_id = create_evaluation(1, 'quant_crypto', state, self.config)
        update_evaluation(evaluation_id, status='success',
                          answers_json=json.dumps(response_for(build_crypto_quant_questions())['answers']))
        return evaluation_id

    def later_quote(self, price, when):
        state = build_state('ETH', price, signal_with(HEALTHY_CHECKS, enter=False), when)
        return create_evaluation(1, 'quant_crypto', state, self.config)

    def test_contaminated_quote_is_skipped_for_the_next_plausible_one(self):
        evaluation_id = self.graded_candidate()
        due = self.now - timedelta(hours=1)
        self.later_quote(84783.08, due)                        # BTC's price level: rejected
        self.later_quote(2500.0, due + timedelta(minutes=10))  # ETH's real level: used
        self.assertEqual(evaluate_pending_outcomes(self.now), 1)
        row = get_evaluation(evaluation_id)
        self.assertAlmostEqual(row.outcome_price, 2500.0)
        self.assertAlmostEqual(row.outcome_return_pct, (2500.0 / 2450.0 - 1) * 100)

    def test_contaminated_quote_alone_leaves_the_row_unscored(self):
        evaluation_id = self.graded_candidate()
        self.later_quote(84783.08, self.now - timedelta(hours=1))
        self.assertEqual(evaluate_pending_outcomes(self.now), 0)
        self.assertIsNone(get_evaluation(evaluation_id).outcome_return_pct)
