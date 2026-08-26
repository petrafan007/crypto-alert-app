import unittest

from services.sentiment_outcome_service import evaluate_sentiment_outcome


class SentimentOutcomeTests(unittest.TestCase):
    def grade(self, sentiment, source, end, threshold=5):
        return evaluate_sentiment_outcome(sentiment, source, 100, end, threshold)['status']

    def test_bullish_direction_and_neutral_band(self):
        self.assertEqual(self.grade('Consider Buying', 'portfolio', 106), 'correct')
        self.assertEqual(self.grade('Buy Immediately', 'portfolio', 94), 'wrong')
        self.assertEqual(self.grade('Definitely Buy', 'watchlist', 104.99), 'neutral')

    def test_bearish_direction(self):
        self.assertEqual(self.grade('Consider Selling', 'portfolio', 94), 'correct')
        self.assertEqual(self.grade('Avoid', 'watchlist', 106), 'wrong')

    def test_hold_and_watch_have_source_aware_meaning(self):
        self.assertEqual(self.grade('Hold', 'portfolio', 106), 'correct')
        self.assertEqual(self.grade('Hold', 'portfolio', 94), 'wrong')
        self.assertEqual(self.grade('Watch', 'watchlist', 94), 'correct')
        self.assertEqual(self.grade('Watch', 'watchlist', 106), 'wrong')

    def test_threshold_boundary_is_decisive(self):
        self.assertEqual(self.grade('Buy', 'portfolio', 105), 'correct')
        self.assertEqual(self.grade('Sell', 'portfolio', 95), 'correct')

    def test_unknown_or_invalid_signal_is_unscored(self):
        self.assertEqual(self.grade('Maybe', 'portfolio', 110), 'unscored')
        self.assertEqual(evaluate_sentiment_outcome('Buy', 'portfolio', 0, 100)['status'], 'unscored')


if __name__ == '__main__':
    unittest.main()
