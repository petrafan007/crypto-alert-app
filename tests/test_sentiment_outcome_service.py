import unittest
from types import SimpleNamespace

from services.sentiment_outcome_service import (
    CORRECT_THRESHOLD_FIELDS,
    DEFAULT_SENTIMENT_CHART_RANGE,
    HOLD_VARIABLE,
    SENTIMENT_THRESHOLD_FIELDS,
    evaluate_sentiment_outcome,
    get_sentiment_thresholds,
    pair_next_sentiment_checks,
    validate_sentiment_chart_range,
    validate_sentiment_threshold_payload,
    validate_sentiment_window_payload,
)


class SentimentOutcomeTests(unittest.TestCase):
    def grade(self, sentiment, end, correct=5, wrong=0, steady=1, hold_wrong=5):
        return evaluate_sentiment_outcome(
            sentiment,
            'portfolio',
            100,
            end,
            correct,
            wrong,
            steady,
            hold_wrong,
        )

    def test_bullish_zero_wrong_boundary(self):
        self.assertEqual(self.grade('Buy Immediately', 105)['status'], 'correct')
        self.assertEqual(self.grade('Buy Immediately', 100.001)['status'], 'neutral')
        self.assertEqual(self.grade('Consider Buying', 100.01)['status'], 'neutral')
        self.assertEqual(self.grade('Consider Buying', 100)['status'], 'wrong')
        self.assertEqual(self.grade('Consider Buying', 99.99)['status'], 'wrong')

    def test_exact_decimal_boundary_is_not_lost_to_float_rounding(self):
        result = evaluate_sentiment_outcome(
            'Buy Immediately', 'portfolio', 19, 19 * 1.05, 5, 0
        )
        self.assertEqual(result['status'], 'correct')
        self.assertEqual(result['delta_pct'], 5)

    def test_small_price_move_preserves_its_direction(self):
        result = evaluate_sentiment_outcome(
            'Consider Buying', 'portfolio', 100, 99.999, 2.5, 0
        )
        self.assertEqual(result['status'], 'wrong')
        self.assertLess(result['delta_pct'], 0)
        self.assertAlmostEqual(result['delta_pct'], -0.001, places=6)

    def test_bearish_zero_wrong_boundary(self):
        self.assertEqual(self.grade('Sell Immediately', 95)['status'], 'correct')
        self.assertEqual(self.grade('Consider Selling', 99.99)['status'], 'neutral')
        self.assertEqual(self.grade('Consider Selling', 100)['status'], 'wrong')
        self.assertEqual(self.grade('Consider Selling', 100.01)['status'], 'wrong')

    def test_hold_has_steady_neutral_and_wrong_regions(self):
        self.assertEqual(self.grade('Hold', 101, hold_wrong=4)['status'], 'correct')
        self.assertEqual(self.grade('Hold', 99, hold_wrong=4)['status'], 'correct')
        self.assertEqual(self.grade('Hold', 103, hold_wrong=4)['status'], 'neutral')
        self.assertEqual(self.grade('Hold', 97, hold_wrong=4)['status'], 'neutral')
        self.assertEqual(self.grade('Hold', 104, hold_wrong=4)['status'], 'wrong')
        self.assertEqual(self.grade('Hold', 96, hold_wrong=4)['status'], 'wrong')

    def test_hold_can_use_zero_as_steady_range(self):
        self.assertEqual(self.grade('Hold', 100, steady=0)['status'], 'correct')
        self.assertEqual(self.grade('Hold', 100.01, steady=0)['status'], 'neutral')
        self.assertEqual(self.grade('Hold', 95, steady=0)['status'], 'wrong')

    def test_hold_rejects_wrong_boundary_that_overlaps_steady_range(self):
        result = self.grade('Hold', 101, steady=5, hold_wrong=5)
        self.assertEqual(result['status'], 'unscored')

    def test_directional_correct_and_wrong_thresholds_are_independent(self):
        result = self.grade('Buy Immediately', 98, correct=2, wrong=3)
        self.assertEqual(result['status'], 'neutral')
        self.assertEqual(result['neutral_lower_pct'], -3)
        self.assertEqual(result['neutral_upper_pct'], 2)

    def test_legacy_watchlist_labels_use_directional_families(self):
        self.assertEqual(self.grade('Definitely Buy', 105)['status'], 'correct')
        self.assertEqual(self.grade('Watch', 95)['status'], 'correct')
        self.assertEqual(self.grade('Avoid', 101)['status'], 'wrong')

    def test_unknown_or_invalid_signal_is_unscored(self):
        self.assertEqual(self.grade('Maybe', 110)['status'], 'unscored')
        self.assertEqual(
            evaluate_sentiment_outcome('Buy Immediately', 'portfolio', 0, 100)['status'],
            'unscored',
        )

    def test_threshold_payload_accepts_zero_only_where_semantically_valid(self):
        payload = {
            field: ('5.00' if field in CORRECT_THRESHOLD_FIELDS else '0.00')
            for field in SENTIMENT_THRESHOLD_FIELDS
        }
        payload[HOLD_VARIABLE['wrong_field']] = '5.00'
        values, errors = validate_sentiment_threshold_payload(payload, require_all=True)
        self.assertFalse(errors)
        self.assertEqual(values[HOLD_VARIABLE['steady_field']], 0)

        correct_field = next(iter(CORRECT_THRESHOLD_FIELDS))
        payload[correct_field] = '0.00'
        _, errors = validate_sentiment_threshold_payload(payload, require_all=True)
        self.assertIn(correct_field, errors)

    def test_threshold_payload_enforces_precision_and_hold_relationship(self):
        payload = {
            field: ('5.00' if field in CORRECT_THRESHOLD_FIELDS else '1.00')
            for field in SENTIMENT_THRESHOLD_FIELDS
        }
        payload[HOLD_VARIABLE['wrong_field']] = '5.00'
        payload[HOLD_VARIABLE['steady_field']] = '1.234'
        _, errors = validate_sentiment_threshold_payload(payload, require_all=True)
        self.assertIn(HOLD_VARIABLE['steady_field'], errors)

        payload[HOLD_VARIABLE['steady_field']] = '5.00'
        _, errors = validate_sentiment_threshold_payload(payload, require_all=True)
        self.assertIn(HOLD_VARIABLE['wrong_field'], errors)

    def test_threshold_payload_requires_all_ten_fields(self):
        values, errors = validate_sentiment_threshold_payload(
            {SENTIMENT_THRESHOLD_FIELDS[0]: '2.00'}, require_all=True
        )
        self.assertEqual(values[SENTIMENT_THRESHOLD_FIELDS[0]], 2.0)
        self.assertEqual(len(errors), len(SENTIMENT_THRESHOLD_FIELDS) - 1)
        self.assertEqual(len(SENTIMENT_THRESHOLD_FIELDS), 10)

    def test_saved_zero_thresholds_are_not_replaced_by_defaults(self):
        settings = SimpleNamespace(
            sentiment_buy_immediately_correct_pct=5,
            sentiment_buy_immediately_wrong_pct=0,
            sentiment_consider_buying_correct_pct=5,
            sentiment_consider_buying_wrong_pct=0,
            sentiment_consider_selling_correct_pct=5,
            sentiment_consider_selling_wrong_pct=0,
            sentiment_sell_immediately_correct_pct=5,
            sentiment_sell_immediately_wrong_pct=0,
            sentiment_hold_steady_pct=0,
            sentiment_hold_wrong_pct=3,
        )
        thresholds = get_sentiment_thresholds(settings)
        self.assertEqual(thresholds['buy_immediately']['wrong_pct'], 0)
        self.assertEqual(thresholds['sell_immediately']['wrong_pct'], 0)
        self.assertEqual(thresholds['hold']['steady_pct'], 0)
        self.assertEqual(thresholds['hold']['wrong_pct'], 3)

    def test_sentiment_chart_range_validation(self):
        self.assertEqual(DEFAULT_SENTIMENT_CHART_RANGE, '3d')
        self.assertEqual(validate_sentiment_chart_range('90D'), ('90d', None))
        value, error = validate_sentiment_chart_range('2d')
        self.assertIsNone(value)
        self.assertIn('valid Sentiment Chart range', error)

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

    def test_sentiment_windows_require_bounded_whole_hours(self):
        values, errors = validate_sentiment_window_payload({
            'sentiment_history_lookback_hours': '48',
            'watchlist_sentiment_forecast_horizon_hours': 168,
        })
        self.assertFalse(errors)
        self.assertEqual(values['sentiment_history_lookback_hours'], 48)
        self.assertEqual(values['watchlist_sentiment_forecast_horizon_hours'], 168)

        _, errors = validate_sentiment_window_payload({
            'sentiment_history_lookback_hours': 0,
            'sentiment_forecast_horizon_hours': 168.5,
            'watchlist_sentiment_forecast_horizon_hours': 169,
        })
        self.assertEqual(len(errors), 3)


if __name__ == '__main__':
    unittest.main()
