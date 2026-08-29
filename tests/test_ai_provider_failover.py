import unittest

from services.ai_service import (
    INCEPTION_CHAT_COMPLETIONS_URL,
    _notify_ai_attempt,
    build_configured_ai_tiers,
)


class AIProviderFailoverTests(unittest.TestCase):
    def test_failover_chain_contains_only_explicitly_configured_tiers(self):
        settings = {
            'ai_provider': 'gemini',
            'ai_model': 'gemini-3.7-flash',
            'ai_provider_secondary': 'zai',
            'ai_model_secondary': 'glm-4.7-flash',
            'ai_provider_tertiary': 'inception',
            'ai_model_tertiary': 'mercury-2',
        }

        self.assertEqual(
            build_configured_ai_tiers(settings),
            [
                ('primary', 'gemini', 'gemini-3.7-flash', 'medium'),
                ('secondary', 'zai', 'glm-4.7-flash', 'medium'),
                ('tertiary', 'inception', 'mercury-2', 'medium'),
            ],
        )

    def test_unconfigured_tier_is_not_filled_from_any_other_provider(self):
        settings = {
            'ai_provider': ' GEMINI ',
            'ai_model': 'gemini-3.7-flash',
            # An unused OpenAI key is deliberately not an input to this function.
            'ai_provider_secondary': '',
            'ai_provider_tertiary': 'inception',
            'ai_model_tertiary': 'mercury-2',
        }

        self.assertEqual(
            build_configured_ai_tiers(settings),
            [
                ('primary', 'gemini', 'gemini-3.7-flash', 'medium'),
                ('tertiary', 'inception', 'mercury-2', 'medium'),
            ],
        )

    def test_attempt_observer_receives_exact_failure_metadata(self):
        events = []
        _notify_ai_attempt(
            lambda **event: events.append(event),
            'failed',
            tier='tertiary',
            provider='inception',
            model='mercury-2',
            error='provider returned 429',
        )

        self.assertEqual(
            events,
            [{
                'event': 'failed',
                'tier': 'tertiary',
                'provider': 'inception',
                'model': 'mercury-2',
                'error': 'provider returned 429',
            }],
        )

    def test_inception_uses_the_labs_api_endpoint(self):
        self.assertEqual(
            INCEPTION_CHAT_COMPLETIONS_URL,
            'https://api.inceptionlabs.ai/v1/chat/completions',
        )


if __name__ == '__main__':
    unittest.main()
