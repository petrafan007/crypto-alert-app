"""Exercise the Settings handler with encrypted credentials and no external calls."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from flask import Flask
from credentials import Credential
from routes import system


class TelegramSettingsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('credential_security._get_fernet', return_value=Fernet(Fernet.generate_key())))
        self.cred = Credential(user_id=1, username='test-owner', ai_provider='none')
        self.cred.telegram_token = '123456:old-test-secret'
        self.cred.telegram_chat_id = '100'
        self.model = Mock()
        self.model.query.filter_by.return_value.first.return_value = self.cred
        self.stack.enter_context(patch.object(system, 'Credential', self.model))
        settings = Mock()
        settings.query.filter_by.return_value.first.return_value = SimpleNamespace(webull_environment='production')
        self.stack.enter_context(patch.object(system, 'UserSetting', settings))
        self.database = self.stack.enter_context(patch.object(system, 'db'))
        self.stack.enter_context(patch.object(system, 'current_user', SimpleNamespace(id=1, username='test-owner', is_authenticated=True)))
        self.stack.enter_context(patch.object(system, 'get_user_ai_settings', return_value={}))
        self.stack.enter_context(patch.object(system, 'is_encryption_available', return_value=True))
        self.stack.enter_context(patch.object(system, 'is_persisted_key_available', return_value=True))

    def call(self, method, payload=None):
        with self.app.test_request_context('/api/settings', method=method, json=payload):
            response = system.api_settings.__wrapped__()
            self.assertFalse(isinstance(response, tuple), 'Settings handler returned an error')
            return response.get_json()

    def reload_credential(self):
        reloaded = Credential(user_id=1, username='test-owner', ai_provider='none')
        reloaded._telegram_token = self.cred._telegram_token
        reloaded._telegram_chat_id = self.cred._telegram_chat_id
        self.cred = reloaded
        self.model.query.filter_by.return_value.first.return_value = reloaded

    def test_replacement_is_committed_encrypted_and_returned_on_reload(self):
        self.call('POST', {'telegram_token': ' 123456:new-test-secret\n', 'telegram_chat_id': ' -100123 '})
        self.database.session.commit.assert_called_once()
        self.assertTrue(self.cred._telegram_token.startswith('gAAAA'))
        self.assertNotIn('new-test-secret', self.cred._telegram_token)
        self.reload_credential()
        result = self.call('GET')
        self.assertEqual(result['telegram_token'], '********')
        self.assertEqual(self.cred.telegram_token, '123456:new-test-secret')
        self.assertEqual(result['telegram_chat_id'], '********')
        self.assertEqual(self.cred.telegram_chat_id, '-100123')

    def test_omitted_fields_retain_saved_credentials(self):
        self.call('POST', {'telegram_notifications_enabled': True})
        self.assertEqual(self.cred.telegram_token, '123456:old-test-secret')
        self.assertEqual(self.cred.telegram_chat_id, '100')

    def test_token_only_save_preserves_chat_id(self):
        self.call('POST', {'telegram_token': '123456:new-test-secret'})
        self.assertEqual(self.cred.telegram_token, '123456:new-test-secret')
        self.assertEqual(self.cred.telegram_chat_id, '100')

    def test_round_tripped_masks_preserve_credentials(self):
        result = self.call('GET')
        self.call('POST', {'telegram_token': result['telegram_token'], 'telegram_chat_id': result['telegram_chat_id']})
        self.assertEqual(self.cred.telegram_token, '123456:old-test-secret')
        self.assertEqual(self.cred.telegram_chat_id, '100')

    def test_explicit_blank_clears_credentials(self):
        self.call('POST', {'telegram_token': ' ', 'telegram_chat_id': ''})
        self.assertIsNone(self.cred.telegram_token)
        self.assertIsNone(self.cred.telegram_chat_id)


if __name__ == '__main__':
    unittest.main()
