import unittest
from datetime import datetime, timedelta, timezone

from services.scheduler_tasks import (
    DEFAULT_AUTOMATED_TRIGGER_CONFIRMATION_MINUTES,
    evaluate_automated_trigger_confirmation,
    normalize_automated_trigger_confirmation_minutes,
)


class AutomatedTriggerConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 26, 12, 0, 0)

    def test_default_and_bounds_are_safe(self):
        self.assertEqual(
            normalize_automated_trigger_confirmation_minutes(None),
            DEFAULT_AUTOMATED_TRIGGER_CONFIRMATION_MINUTES,
        )
        self.assertEqual(normalize_automated_trigger_confirmation_minutes(0), 1)
        self.assertEqual(normalize_automated_trigger_confirmation_minutes(5000), 1440)

    def test_first_qualifying_check_starts_confirmation(self):
        started_at, confirmed, action = evaluate_automated_trigger_confirmation(
            None, True, self.now, 15
        )
        self.assertEqual(started_at, self.now)
        self.assertFalse(confirmed)
        self.assertEqual(action, 'started')

    def test_trigger_waits_for_entire_confirmation_window(self):
        started_at = self.now - timedelta(minutes=14, seconds=59)
        _, confirmed, action = evaluate_automated_trigger_confirmation(
            started_at, True, self.now, 15
        )
        self.assertFalse(confirmed)
        self.assertEqual(action, 'pending')

        _, confirmed, action = evaluate_automated_trigger_confirmation(
            self.now - timedelta(minutes=15), True, self.now, 15
        )
        self.assertTrue(confirmed)
        self.assertEqual(action, 'confirmed')

    def test_recovery_resets_the_timer(self):
        started_at, confirmed, action = evaluate_automated_trigger_confirmation(
            self.now - timedelta(minutes=12), False, self.now, 15
        )
        self.assertIsNone(started_at)
        self.assertFalse(confirmed)
        self.assertEqual(action, 'reset')

    def test_timezone_aware_stored_timestamp_is_supported(self):
        started_at = (self.now - timedelta(minutes=15)).replace(tzinfo=timezone.utc)
        returned_start, confirmed, action = evaluate_automated_trigger_confirmation(
            started_at, True, self.now, 15
        )
        self.assertEqual(returned_start, self.now - timedelta(minutes=15))
        self.assertTrue(confirmed)
        self.assertEqual(action, 'confirmed')
