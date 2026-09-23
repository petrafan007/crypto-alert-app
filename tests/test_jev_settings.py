from types import SimpleNamespace
from unittest.mock import Mock, patch
from credentials import Credential, UserSetting
from core.extensions import db
from routes import system, ai
from services.jev_service import JevError
from services.jev_settings import validate_settings
from tests.jev_helpers import JevTestCase


class JevSettingsTests(JevTestCase):
    def request(self, method, payload=None, route='/api/settings'):
        module, handler = (system, system.api_settings) if route == '/api/settings' else (ai, ai.api_ai_settings)
        with self.app.test_request_context(route, method=method, json=payload), \
             patch.object(module, 'current_user', SimpleNamespace(id=1, username='jev-test', is_authenticated=True)):
            result = handler.__wrapped__()
        return result if isinstance(result, tuple) else (result, 200)

    def test_save_load_encrypt_mask_preserve_replace_clear(self):
        reply, status = self.request('POST', {'ai_gateway_key': 'new-key', 'jev_enabled': True, 'jev_sentiment_mode': 'first', 'jev_confidence_threshold': .85})
        self.assertEqual(status, 200, reply.json)
        self.assertEqual(reply.json['ai_gateway_key'], '********')
        self.assertEqual(reply.json['jev_sentiment_mode'], 'first')
        credential = Credential.query.filter_by(user_id=1).one()
        self.assertEqual(credential.ai_gateway_key, 'new-key')
        self.assertNotIn('new-key', credential._ai_gateway_key)
        encrypted = credential._ai_gateway_key
        self.request('POST', {'ai_gateway_key': '********', 'jev_quant_shadow_enabled': False})
        self.assertEqual(credential._ai_gateway_key, encrypted)
        reply, status = self.request('GET')
        self.assertEqual(reply.json['ai_gateway_key'], '********')
        self.assertNotIn('new-key', str(reply.json))
        self.request('POST', {'ai_gateway_key': ''})
        self.assertFalse(credential.ai_gateway_key)

    def test_both_apis_reject_invalid_settings_before_key_write(self):
        for route in ('/api/settings', '/api/ai/settings'):
            for invalid in ({'jev_timeout_seconds': 200}, {'jev_confidence_threshold': float('nan')},
                            {'jev_quant_paper_gate_enabled': True}, {'jev_enabled': 'false'},
                            {'jev_endpoint': 'https://unapproved.example/evaluate'}):
                reply, status = self.request('POST', dict(invalid, ai_gateway_key='should-not-save'), route=route)
                self.assertEqual(status, 400, reply.json)
                self.assertEqual(Credential.query.filter_by(user_id=1).one().ai_gateway_key, 'synthetic-jev-secret')

    def test_ai_settings_api_masks_round_trip(self):
        reply, status = self.request('POST', {'ai_gateway_key': '********', 'jev_sentiment_mode': 'first'}, route='/api/ai/settings')
        self.assertEqual(status, 200, reply.json)
        self.assertEqual(Credential.query.filter_by(user_id=1).one().ai_gateway_key, 'synthetic-jev-secret')
        self.assertEqual(db.session.get(UserSetting, 1).jev_sentiment_mode, 'first')

    def test_connection_uses_saved_key_without_exposing_it(self):
        with self.app.test_request_context('/api/jev/test-connection', method='POST', json={'ai_gateway_key': '********'}), \
             patch.object(ai, 'current_user', SimpleNamespace(id=1)), \
             patch('services.jev_service.JevClient.evaluate', side_effect=JevError('auth')) as evaluate:
            reply, status = ai.test_jev_connection.__wrapped__()
        self.assertEqual(status, 400)
        self.assertNotIn('synthetic-jev-secret', str(reply.json))
        evaluate.assert_called_once()


import os
import uuid
import unittest


@unittest.skipUnless(os.getenv('JEV_TEST_DATABASE_URI'), 'Requires an isolated PostgreSQL test database')
class JevMigrationTests(unittest.TestCase):
    def test_additive_migration_preserves_existing_settings_and_is_repeatable(self):
        from sqlalchemy import create_engine, text
        from services.jev_settings import schema_columns
        engine = create_engine(os.environ['JEV_TEST_DATABASE_URI'])
        schema = 'jev_migration_' + uuid.uuid4().hex
        try:
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                connection.execute(text('CREATE TABLE credentials (user_id INTEGER, existing_key TEXT)'))
                connection.execute(text('CREATE TABLE user_settings (user_id INTEGER, ai_enabled BOOLEAN)'))
                connection.execute(text("INSERT INTO credentials VALUES (1, 'preserved')"))
                connection.execute(text('INSERT INTO user_settings VALUES (1, TRUE)'))
                for _ in range(2):
                    for table, column, declaration in schema_columns():
                        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {declaration}'))
                self.assertEqual(connection.execute(text('SELECT existing_key FROM credentials')).scalar(), 'preserved')
                row = connection.execute(text('SELECT ai_enabled, jev_enabled, jev_sentiment_mode, jev_quant_shadow_enabled FROM user_settings')).one()
                self.assertEqual(tuple(row), (True, False, 'off', False))
        finally:
            engine.dispose()
