"""Regression coverage for incident containment, with synthetic credentials only."""
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from flask import Flask
from flask_login import LoginManager
from routes import auth, system
from core.session_security import require_session_secret
from core.log_redaction import SecretRedactionFilter
from services.credential_views import MASK, SECRET_FIELDS, masked_settings, credential_changes, saved_or_supplied


class CredentialSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test-only-' * 8
        LoginManager(self.app)
        self.app.register_blueprint(auth.auth_bp)
        self.app.register_blueprint(system.system_bp)
        # Avoid unrelated onboarding DB work in an isolated authentication test.
        self.app.before_request_funcs.clear()
        self.user = Mock(id=1, username='synthetic')
        self.user.check_password.return_value = True

    def test_all_secret_response_fields_masked_and_preserved(self):
        source = {k: 'synthetic-private-value' for k in SECRET_FIELDS}
        source['ai_model'] = 'a-model'
        public = masked_settings(source)
        self.assertNotIn('synthetic-private-value', str(public))
        self.assertEqual(credential_changes(public), {'ai_model': 'a-model'})
        self.assertEqual(credential_changes({'telegram_token': ''}), {'telegram_token': ''})
        self.assertEqual(saved_or_supplied(MASK, SimpleNamespace(api_key='saved'), 'api_key'), 'saved')

    def test_all_login_routes_block_missing_second_factor(self):
        from trading_models import TradingSettings
        with self.app.app_context(), patch.object(auth, 'User') as au, patch.object(system, 'User') as su, \
             patch('credentials.User', au), patch.object(TradingSettings, 'query') as settings, \
             patch.object(auth, 'login_user') as login, patch.object(system, 'create_extension_jwt') as jwt:
            au.query.filter_by.return_value.first.return_value = self.user
            su.query.filter_by.return_value.first.return_value = self.user
            settings.filter_by.return_value.first.return_value = SimpleNamespace(totp_secret='test-secret')
            for route in ['/api/login', '/login', '/api/extension/login', '/api/desktop/login']:
                with self.subTest(route=route):
                    client = self.app.test_client()
                    values = {'username': 'synthetic', 'password': 'test-password'}
                    response = client.post(route, **({'data': values} if route == '/login' else {'json': values}))
                    self.assertTrue(response.json.get('requires_2fa'), response.json)
                    self.assertFalse(response.json.get('success', False))
                    with client.session_transaction() as session:
                        self.assertNotIn('_user_id', session)
            login.assert_not_called()
            jwt.assert_not_called()

    def test_second_factor_invalid_exception_and_valid(self):
        from trading_models import TradingSettings
        with self.app.test_request_context(), patch.object(TradingSettings, 'query') as query, patch.object(auth, 'verify_totp_code') as verify:
            query.filter_by.return_value.first.return_value = SimpleNamespace(totp_secret='synthetic')
            verify.return_value = False
            self.assertEqual(auth.login_second_factor_error(self.user, {'code':'123456'})[1], 401)
            verify.side_effect = RuntimeError('synthetic failure')
            self.assertEqual(auth.login_second_factor_error(self.user, {'code':'123456'})[1], 401)
            verify.side_effect = None
            verify.return_value = True
            self.assertIsNone(auth.login_second_factor_error(self.user, {'code':'123456'}))

    def test_legacy_credential_response_has_no_secret(self):
        with self.app.test_request_context(), patch.object(auth, 'current_user', self.user):
            response = auth.api_get_credentials.__wrapped__()
            self.assertEqual(response.json, {'username': 'synthetic'})
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_retired_query_credential_check_never_calls_provider(self):
        with self.app.test_request_context('/api/check-credential?field=telegram_token&value=synthetic'), patch.object(system.requests, 'get') as get:
            self.assertEqual(system.check_credential.__wrapped__()[1], 410)
            get.assert_not_called()

    def test_new_secret_write_fails_closed_without_encryption(self):
        from credential_security import encrypt_secret, EncryptionKeyError
        with patch('credential_security._get_fernet', side_effect=EncryptionKeyError('missing')):
            with self.assertRaises(EncryptionKeyError):
                encrypt_secret('synthetic-private-value')

    def test_session_secret_rejects_missing_and_examples(self):
        for value in [None, '', 'short', 'super-secret-key-change-me', 'your-secret'*8]:
            with self.assertRaises(RuntimeError): require_session_secret(value)
        self.assertEqual(require_session_secret('a7b2c9d4'*8), 'a7b2c9d4'*8)

    def test_log_filter_removes_token_and_query_credentials(self):
        token = '123456789:' + 'x'*35
        record = logging.LogRecord('test', logging.ERROR, '', 1, 'Request failed: %s', ('https://api.telegram.org/bot'+token+'/getMe?apiKey=synthetic-secret',), None)
        SecretRedactionFilter().filter(record)
        self.assertNotIn(token, record.getMessage())
        self.assertNotIn('synthetic-secret', record.getMessage())

if __name__ == '__main__': unittest.main()
