import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.ai_service import (
    INCEPTION_CHAT_COMPLETIONS_URL,
    call_ollama_chat,
    get_ollama_models,
    is_ollama_admin,
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

    def test_quartan_is_the_fourth_explicit_fallback(self):
        settings = {
            'ai_provider': 'openai',
            'ai_model': 'gpt-5',
            'ai_provider_secondary': 'zai',
            'ai_model_secondary': 'glm-4.5-flash',
            'ai_provider_tertiary': 'inception',
            'ai_model_tertiary': 'mercury-2',
            'ai_provider_quartan': 'ollama',
            'ai_model_quartan': 'gpt-oss:120b-cloud',
            'ai_reasoning_level_quartan': 'high',
        }
        self.assertEqual(
            build_configured_ai_tiers(settings)[-1],
            ('quartan', 'ollama', 'gpt-oss:120b-cloud', 'high'),
        )

    def test_ollama_is_restricted_to_the_permanent_administrator(self):
        with patch.dict(os.environ, {'OLLAMA_ADMIN_USERNAME': 'admin'}):
            self.assertTrue(is_ollama_admin('admin'))
            self.assertTrue(is_ollama_admin(SimpleNamespace(id=1, username='other')))
            self.assertFalse(is_ollama_admin(SimpleNamespace(id=2, username='another-user')))

    def test_ollama_models_are_discovered_and_deduplicated(self):
        response = type('Response', (), {
            'status_code': 200,
            'json': lambda self: {'models': [
                {'name': 'llama3.2:latest'},
                {'name': 'qwen2.5:latest'},
                {'name': 'llama3.2:latest'},
            ]},
        })()
        with patch('services.ai_service.requests.get', return_value=response) as request:
            self.assertEqual(get_ollama_models(), ['llama3.2:latest', 'qwen2.5:latest'])
            request.assert_called_once()

    def test_ollama_chat_requires_nonempty_response(self):
        response = type('Response', (), {
            'status_code': 200,
            'text': '',
            'json': lambda self: {'message': {'content': 'OK'}},
        })()
        with patch('services.ai_service.requests.post', return_value=response):
            self.assertEqual(
                call_ollama_chat('llama3.2:latest', [{'role': 'user', 'content': 'ping'}]),
                'OK',
            )

    def test_ollama_chat_accepts_thinking_response_for_cloud_probe(self):
        response = type('Response', (), {
            'status_code': 200,
            'text': '',
            'json': lambda self: {'message': {'content': '', 'thinking': 'OK'}},
        })()
        with patch('services.ai_service.requests.post', return_value=response) as request:
            self.assertEqual(
                call_ollama_chat(
                    'gpt-oss:120b-cloud',
                    [{'role': 'user', 'content': 'Reply with exactly OK.'}],
                    reasoning_level='high',
                ),
                'OK',
            )
            payload = request.call_args.kwargs['json']
            self.assertEqual(payload['think'], 'high')
            self.assertFalse(payload['stream'])


if __name__ == '__main__':
    unittest.main()
