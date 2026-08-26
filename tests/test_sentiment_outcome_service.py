import unittest
from types import SimpleNamespace

from services.sentiment_outcome_service import (
    SENTIMENT_THRESHOLD_FIELDS,
    evaluate_sentiment_outcome,
    pair_next_sentiment_checks,
    validate_sentiment_threshold_payload,
)


class SentimentOutcomeTests(unittest.TestCase):
    def grade(self, sentiment, end, correct=3, wrong=1):
        return evaluate_sentiment_outcome(
            sentiment, 'portfolio', 100, end, correct, wrong
        )

    def test_bullish_correct_neutral_and_wrong_boundaries(self):
        self.assertEqual(self.grade('Buy Immediately', 103)['status'], 'correct')
        self.assertEqual(self.grade('Consider Buying', 99)['status'], 'wrong')
        self.assertEqual(self.grade('Hold', 101)['status'], 'neutral')

    def test_bearish_correct_neutral_and_wrong_boundaries(self):
        self.assertEqual(self.grade('Sell Immediately', 97)['status'], 'correct')
        self.assertEqual(self.grade('Consider Selling', 101)['status'], 'wrong')
        self.assertEqual(self.grade('Sell Immediately', 99)['status'], 'neutral')

    def test_exact_boundaries_are_decisive(self):
        self.assertEqual(self.grade('Hold', 103)['status'], 'correct')
        self.assertEqual(self.grade('Hold', 99)['status'], 'wrong')
        self.assertEqual(self.grade('Consider Selling', 97)['status'], 'correct')
        self.assertEqual(self.grade('Consider Selling', 101)['status'], 'wrong')

    def test_correct_and_wrong_thresholds_are_independent(self):
        result = self.grade('Buy Immediately', 98, correct=2, wrong=3)
        self.assertEqual(result['status'], 'neutral')
        self.assertEqual(result['neutral_lower_pct'], -3)
        self.assertEqual(result['neutral_upper_pct'], 2)

    def test_legacy_watchlist_labels_use_the_five_configured_families(self):
        self.assertEqual(self.grade('Definitely Buy', 103)['status'], 'correct')
        self.assertEqual(self.grade('Watch', 97)['status'], 'correct')
        self.assertEqual(self.grade('Avoid', 101)['status'], 'wrong')

    def test_unknown_or_invalid_signal_is_unscored(self):
        self.assertEqual(self.grade('Maybe', 110)['status'], 'unscored')
        self.assertEqual(
            evaluate_sentiment_outcome('Buy Immediately', 'portfolio', 0, 100)['status'],
            'unscored',
        )

    def test_threshold_payload_requires_positive_two_decimal_values(self):
        valid = {field: '1.25' for field in SENTIMENT_THRESHOLD_FIELDS}
        values, errors = validate_sentiment_threshold_payload(valid, require_all=True)
        self.assertFalse(errors)
        self.assertEqual(values[SENTIMENT_THRESHOLD_FIELDS[0]], 1.25)

        invalid = dict(valid)
        invalid[SENTIMENT_THRESHOLD_FIELDS[0]] = '0'
        invalid[SENTIMENT_THRESHOLD_FIELDS[1]] = '1.234'
        _, errors = validate_sentiment_threshold_payload(invalid, require_all=True)
        self.assertIn(SENTIMENT_THRESHOLD_FIELDS[0], errors)
        self.assertIn(SENTIMENT_THRESHOLD_FIELDS[1], errors)

    def test_threshold_payload_requires_all_ten_fields(self):
        values, errors = validate_sentiment_threshold_payload(
            {SENTIMENT_THRESHOLD_FIELDS[0]: '2.00'}, require_all=True
        )
        self.assertEqual(values[SENTIMENT_THRESHOLD_FIELDS[0]], 2.0)
        self.assertEqual(len(errors), len(SENTIMENT_THRESHOLD_FIELDS) - 1)

    def test_checks_pair_only_with_the_same_coin_and_source(self):
        records = [
            SimpleNamespace(id=1, symbol='BTC', source_type='portfolio'),
            SimpleNamespace(id=2, symbol='ETH', source_type='portfolio'),
            SimpleNamespace(id=3, symbol='BTC', source_type='watchlist'),
            SimpleNamespace(id=4, symbol='BTC', source_type='portfolio'),
            SimpleNamespace(id=5, symbol='ETH', source_type='portfolio'),
            SimpleNamespace(id=6, symbol='BTC', source_type='portfolio'),
        ]
        pairs = pair_next_sentiment_checks(records)
        self.assertEqual(pairs[1].id, 4)
        self.assertEqual(pairs[4].id, 6)
        self.assertEqual(pairs[2].id, 5)
        self.assertNotIn(3, pairs)
        self.assertNotIn(6, pairs)


if __name__ == '__main__':
    unittest.main()
