"""Settlement timestamps must identify an instant supported by saved evidence."""
import unittest
from datetime import datetime, timedelta, timezone

from services.event_settlement_timing import settlement_timing


class SettlementTimingTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 9, 13, 15)
        self.observed = self.cutoff + timedelta(minutes=5)

    def test_calendar_date_uses_observation_without_inventing_midnight(self):
        selected, evidence = settlement_timing({'payout_date': '2026-09-13'}, self.cutoff, self.observed)
        self.assertEqual(selected, self.observed)
        self.assertEqual(evidence['basis'], 'OBSERVED_RESOLUTION')
        self.assertEqual(evidence['reason'], 'DATE_ONLY_PAYOUT')
        self.assertEqual(evidence['provider_payout_value'], '2026-09-13')

    def test_precise_provider_times_preserve_their_actual_utc_instant(self):
        expected = self.cutoff + timedelta(minutes=2)
        for value in ('2026-09-13T11:02:00-04:00', '2026-09-13T15:02:00Z',
                      expected.replace(tzinfo=timezone.utc).timestamp(), expected.replace(tzinfo=timezone.utc).timestamp()*1000):
            with self.subTest(value=value):
                selected, evidence = settlement_timing({'payout_date': value}, self.cutoff, self.observed)
                self.assertEqual(selected, expected)
                self.assertEqual(evidence['basis'], 'PROVIDER_PAYOUT_TIMESTAMP')
                self.assertIsNone(evidence['reason'])

    def test_unusable_or_out_of_bounds_times_are_labeled_observations(self):
        for value, reason in ((None, 'MISSING_PAYOUT_TIME'), ('bad', 'INVALID_OR_AMBIGUOUS_PAYOUT_TIME'),
                              ('2026-09-13T15:02:00', 'INVALID_OR_AMBIGUOUS_PAYOUT_TIME'),
                              ('2026-09-13T14:59:00Z', 'PAYOUT_BEFORE_CUTOFF'),
                              ('2026-09-13T15:06:00Z', 'PAYOUT_AFTER_OBSERVATION'),
                              (True, 'INVALID_OR_AMBIGUOUS_PAYOUT_TIME'),
                              (float('nan'), 'INVALID_OR_AMBIGUOUS_PAYOUT_TIME')):
            with self.subTest(value=value):
                selected, evidence = settlement_timing({'payout_date': value}, self.cutoff, self.observed)
                self.assertEqual(selected, self.observed)
                self.assertEqual(evidence['reason'], reason)

    def test_explicit_midnight_is_valid_when_it_falls_in_the_resolution_window(self):
        midnight = datetime(2026, 9, 14)
        selected, evidence = settlement_timing({'payout_date': '2026-09-14T00:00:00Z'},
                                                midnight-timedelta(minutes=5), midnight+timedelta(minutes=5))
        self.assertEqual(selected, midnight)
        self.assertEqual(evidence['basis'], 'PROVIDER_PAYOUT_TIMESTAMP')

    def test_observation_before_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            settlement_timing({}, self.cutoff, self.cutoff-timedelta(seconds=1))
