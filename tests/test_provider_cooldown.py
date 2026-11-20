"""Provider cooldown rejections are a distinct, log-only failure class.

One real Gemini failure opens a 60s cooldown; every later call in that
window is rejected by check() before any attempt. Those rejections must
not each raise a user notification (Nov 20 2026: one BTC timeout became
nine warning popups). check() therefore raises ProviderCooldown, and the
ai_service failure handler skips the toast for it — one notification per
provider per cooldown window. Also pins the Gemini read-timeout bump.
"""
import unittest
from pathlib import Path

import requests
from flask import has_app_context

from services import provider_resilience as pr

ROOT = Path(__file__).resolve().parent.parent


class ProviderCooldownTests(unittest.TestCase):
    def setUp(self):
        # These tests use the in-memory store; they must not run inside an
        # app context (which would switch the store to PostgreSQL).
        self.assertFalse(has_app_context())
        self.key = pr.identity('cooldown-test', 'owner', 'svc', id(self))

    def test_check_raises_cooldown_subclass(self):
        pr.block_failure(self.key, 'owner', 'gemini:gemini-4-hydrogen',
                         requests.Timeout('read timed out'))
        self.assertIsNotNone(pr.read(self.key))
        with self.assertRaises(pr.ProviderCooldown) as caught:
            pr.check(self.key)
        self.assertIsInstance(caught.exception, pr.ProviderUnavailable)
        self.assertTrue(pr.is_cooldown_rejection(caught.exception))
        self.assertFalse(pr.is_cooldown_rejection(pr.ProviderUnavailable('x')))

    def test_block_failure_ignores_cooldown_rejections(self):
        pr.block_failure(self.key, 'owner', 'svc', requests.Timeout('read timed out'))
        before = pr.read(self.key)
        pr.block_failure(self.key, 'owner', 'svc', pr.ProviderCooldown('rejected'))
        after = pr.read(self.key)
        self.assertEqual(before['expires_at'], after['expires_at'])

    def test_claim_notification_fires_once_per_window(self):
        # No cooldown row: nothing to dedupe, notification allowed.
        self.assertTrue(pr.claim_notification(self.key))
        pr.block_failure(self.key, 'owner', 'svc', requests.Timeout('read timed out'))
        self.assertTrue(pr.claim_notification(self.key))
        self.assertFalse(pr.claim_notification(self.key))
        self.assertFalse(pr.claim_notification(self.key))
        # Claiming must not destroy the cooldown itself.
        row = pr.read(self.key)
        self.assertIsNotNone(row)
        self.assertEqual(row['payload']['reason'], 'connection unavailable')

    def test_ai_service_wiring(self):
        source = (ROOT / 'services' / 'ai_service.py').read_text()
        gemini_branch = source.split("elif provider == 'gemini':", 1)[1].split('elif provider', 1)[0]
        self.assertIn('provider_timeout(120)', gemini_branch)
        self.assertNotIn('provider_timeout(45)', gemini_branch)
        self.assertIn('claim_notification(_cooldown_key)', source)


if __name__ == '__main__':
    unittest.main()
