import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from types import SimpleNamespace
from credentials import Credential
from database import db
from services.credential_views import masked_settings, credential_changes
from services.ai_service import get_ollama_models, call_ollama_chat
import os
from cryptography.fernet import Fernet
import credential_security
from routes.portfolio_algo import test_provider_api


class OllamaCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_key = Fernet.generate_key().decode()
        cls.orig_env_key = os.environ.get("CREDENTIALS_ENCRYPTION_KEY")
        os.environ["CREDENTIALS_ENCRYPTION_KEY"] = cls.test_key
        credential_security._get_fernet.cache_clear()

        cls.app = Flask(__name__)
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(cls.app)
        with cls.app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        if cls.orig_env_key is not None:
            os.environ["CREDENTIALS_ENCRYPTION_KEY"] = cls.orig_env_key
        else:
            os.environ.pop("CREDENTIALS_ENCRYPTION_KEY", None)
        credential_security._get_fernet.cache_clear()

    def test_credential_encryption_and_property_accessors(self):
        with self.app.app_context():
            cred = Credential(user_id=999, username="test_ollama_user")
            cred.ollama_key = "ollama-secret-primary"
            cred.ollama_key_fallback = "ollama-secret-secondary"
            cred.ollama_key_tertiary = "ollama-secret-tertiary"
            cred.ollama_key_quaternary = "ollama-secret-quaternary"

            self.assertEqual(cred.ollama_key, "ollama-secret-primary")
            self.assertEqual(cred.ollama_key_fallback, "ollama-secret-secondary")
            self.assertEqual(cred.ollama_key_secondary, "ollama-secret-secondary")
            self.assertEqual(cred.ollama_key_tertiary, "ollama-secret-tertiary")
            self.assertEqual(cred.ollama_key_quaternary, "ollama-secret-quaternary")

            # Verify encrypted storage in private attribute
            self.assertNotEqual(cred._ollama_key, "ollama-secret-primary")
            self.assertTrue(bool(cred._ollama_key))

    def test_credential_views_masks_and_preserves_ollama_keys(self):
        settings_payload = {
            'ollama_key': 'secret-primary',
            'ollama_key_fallback': 'secret-fallback',
            'ollama_key_tertiary': 'secret-tertiary',
            'ollama_key_quaternary': 'secret-quaternary',
            'ai_provider': 'ollama',
        }
        masked = masked_settings(settings_payload)
        self.assertEqual(masked['ollama_key'], '********')
        self.assertEqual(masked['ollama_key_fallback'], '********')
        self.assertEqual(masked['ollama_key_tertiary'], '********')
        self.assertEqual(masked['ollama_key_quaternary'], '********')
        self.assertEqual(masked['ai_provider'], 'ollama')

        # Round-tripping masked keys should omit them from changes so secrets are not overwritten
        changes = credential_changes(masked)
        self.assertNotIn('ollama_key', changes)
        self.assertNotIn('ollama_key_fallback', changes)
        self.assertNotIn('ollama_key_tertiary', changes)
        self.assertNotIn('ollama_key_quaternary', changes)
        self.assertEqual(changes['ai_provider'], 'ollama')

        # Empty string clears secret
        cleared = credential_changes({'ollama_key': ''})
        self.assertIn('ollama_key', cleared)
        self.assertEqual(cleared['ollama_key'], '')

    @patch('requests.get')
    def test_get_ollama_models_sends_authorization_header_when_api_key_provided(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'models': [{'name': 'gpt-oss:120b-cloud'}]}
        mock_get.return_value = mock_resp

        # With API key
        models = get_ollama_models(api_key='test-ollama-cloud-key')
        self.assertEqual(models, ['gpt-oss:120b-cloud'])
        mock_get.assert_called_with(
            'http://127.0.0.1:11434/api/tags',
            headers={'Authorization': 'Bearer test-ollama-cloud-key'},
            timeout=5
        )

        # Without API key
        mock_get.reset_mock()
        get_ollama_models()
        mock_get.assert_called_with(
            'http://127.0.0.1:11434/api/tags',
            headers={},
            timeout=5
        )

    @patch('requests.post')
    def test_call_ollama_chat_sends_authorization_header(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'message': {'content': 'Hello from Ollama cloud'},
            'done_reason': 'stop'
        }
        mock_post.return_value = mock_resp

        res = call_ollama_chat(
            'gpt-oss:120b-cloud',
            [{'role': 'user', 'content': 'hi'}],
            api_key='account-key-123'
        )
        self.assertEqual(str(res), 'Hello from Ollama cloud')
        mock_post.assert_called_once()
        headers = mock_post.call_args.kwargs['headers']
        self.assertEqual(headers.get('Authorization'), 'Bearer account-key-123')

    @patch('services.ai_service.get_ollama_models')
    def test_test_provider_api_passes_key_and_verifies_model(self, mock_get_models):
        mock_get_models.return_value = ['gpt-oss:120b-cloud', 'qwen2.5:14b']
        with self.app.test_request_context():
            response = test_provider_api('ollama', 'cloud-key-xyz', 'gpt-oss:120b-cloud')
            self.assertTrue(response.json['success'])
            mock_get_models.assert_called_once_with(timeout=10, api_key='cloud-key-xyz')


if __name__ == '__main__':
    unittest.main()
