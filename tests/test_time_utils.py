import unittest
from datetime import datetime, timezone

from core.time_utils import (
    utc_now,
    utc_from_timestamp,
    ensure_utc_naive,
    ensure_utc_aware,
)


class TimeUtilsTests(unittest.TestCase):
    def test_utc_now_naive_by_default(self):
        now = utc_now()
        self.assertIsNone(now.tzinfo)
        self.assertIsInstance(now, datetime)

    def test_utc_now_aware_when_requested(self):
        now = utc_now(aware=True)
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.tzinfo, timezone.utc)

    def test_utc_from_timestamp_naive_and_aware(self):
        ts = 1700000000.0
        naive = utc_from_timestamp(ts)
        self.assertIsNone(naive.tzinfo)
        self.assertEqual(naive.year, 2023)

        aware = utc_from_timestamp(ts, aware=True)
        self.assertEqual(aware.tzinfo, timezone.utc)
        self.assertEqual(aware.year, 2023)

    def test_ensure_utc_naive_and_aware(self):
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 1, 1, 12, 0, 0)

        converted_naive = ensure_utc_naive(aware)
        self.assertIsNone(converted_naive.tzinfo)
        self.assertEqual(converted_naive, naive)

        converted_aware = ensure_utc_aware(naive)
        self.assertEqual(converted_aware.tzinfo, timezone.utc)
        self.assertEqual(converted_aware, aware)

        self.assertIsNone(ensure_utc_naive(None))
        self.assertIsNone(ensure_utc_aware(None))


if __name__ == '__main__':
    unittest.main()
