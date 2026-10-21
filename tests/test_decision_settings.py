from types import SimpleNamespace
from unittest.mock import Mock, patch
from credentials import Credential, UserSetting
from core.extensions import db
from routes import system, ai
from services.decision_engine import DecisionError
from services.decision_settings import (
    DEFAULT_ENDPOINT, INCEPTION_DECISIONS_ENDPOINT, INCEPTION_DECISIONS_MODEL,
    SUBQ_ENDPOINT, SUBQ_MODEL, normalize_transport, validate_settings,
)
from tests.decision_helpers import DecisionTestCase


class DecisionSettingsTests(DecisionTestCase):
    def test_openrouter_key_mask_preserves_saved_secret_in_both_settings_apis(self):
        for route in ('/api/settings', '/api/ai/settings'):
            with self.subTest(route=route):
                response, status = self.request('POST', {
                    'openrouter_api_key': 'synthetic-openrouter-key', 'decision_transport': 'inception',
                    'decision_endpoint': INCEPTION_DECISIONS_ENDPOINT, 'decision_model': INCEPTION_DECISIONS_MODEL,
                }, route=route)
                self.assertEqual(status, 200)
                self.assertNotIn('synthetic-openrouter-key', str(response.json))
                credential = Credential.query.filter_by(user_id=1).one()
                self.assertEqual(credential.openrouter_api_key, 'synthetic-openrouter-key')
                response, status = self.request('POST', {
                    'openrouter_api_key': '********', 'decision_enabled': True,
                }, route=route)
                self.assertEqual(status, 200)
                self.assertEqual(credential.openrouter_api_key, 'synthetic-openrouter-key')
                settings = db.session.get(UserSetting, 1)
                self.assertEqual(settings.decision_endpoint, INCEPTION_DECISIONS_ENDPOINT)
                self.assertEqual(settings.decision_model, INCEPTION_DECISIONS_MODEL)

    def test_masks_cannot_overwrite_the_model_secret_even_outside_settings_routes(self):
        credential = Credential.query.filter_by(user_id=1).one()
        credential.openrouter_api_key = 'first-key'; db.session.commit()
        encrypted = credential._openrouter_api_key
        for mask in ('********', '  ********  '):
            credential.openrouter_api_key = mask; db.session.commit(); db.session.expire_all()
            self.assertEqual(credential._openrouter_api_key, encrypted)
            self.assertEqual(credential.openrouter_api_key, 'first-key')

    def test_saved_status_is_confirmed_after_commit_and_survives_later_full_save(self):
        for route in ('/api/settings', '/api/ai/settings'):
            with self.subTest(route=route):
                response, status = self.request('POST', {'openrouter_api_key':'replacement-key'}, route)
                self.assertEqual(status, 200)
                self.assertTrue(response.json['openrouter_api_key_configured'])
                self.assertEqual(response.json['openrouter_api_key'], '********')
                db.session.expire_all()
                self.assertEqual(Credential.query.filter_by(user_id=1).one().openrouter_api_key, 'replacement-key')
                response, status = self.request('POST', {'openrouter_api_key':'********', 'decision_enabled':True}, route)
                self.assertEqual(status, 200)
                db.session.expire_all()
                self.assertEqual(Credential.query.filter_by(user_id=1).one().openrouter_api_key, 'replacement-key')
                response, status = self.request('GET', route=route)
                self.assertTrue(response.json['openrouter_api_key_configured'])
                self.assertNotIn('replacement-key', str(response.json))

    def test_retired_generative_fallback_setting_is_ignored(self):
        # The generative fallback is always allowed now, so the retired
        # 'jev_generative_fallback_enabled' flag is no longer a valid setting
        # and must not be persisted or change any behaviour.
        response, status = self.request('POST', {
            'decision_enabled': True, 'jev_generative_fallback_enabled': True,
        })
        self.assertEqual(status, 200, response.json)
        settings = db.session.get(UserSetting, 1)
        self.assertTrue(settings.decision_enabled)
        self.assertFalse(hasattr(settings, 'decision_generative_fallback_enabled'))

    def test_old_stored_placeholder_is_reported_as_missing_not_configured(self):
        from credential_security import normalize_secret_for_storage
        credential = Credential.query.filter_by(user_id=1).one()
        credential._openrouter_api_key = normalize_secret_for_storage('********')
        db.session.commit()
        reply, status = self.request('GET')
        self.assertEqual(status, 200)
        self.assertFalse(reply.json['openrouter_api_key_configured'])
        self.assertEqual(reply.json['openrouter_api_key'], '')

    def request(self, method, payload=None, route='/api/settings'):
        module, handler = (system, system.api_settings) if route == '/api/settings' else (ai, ai.api_ai_settings)
        with self.app.test_request_context(route, method=method, json=payload), \
             patch.object(module, 'current_user', SimpleNamespace(id=1, username='decision-test', is_authenticated=True)):
            result = handler.__wrapped__()
        return result if isinstance(result, tuple) else (result, 200)

    def test_subq_model_and_endpoint_are_pinned_to_official_decisions_api(self):
        from services.decision_settings import schema_columns
        self.assertIn(('credentials', 'subq_api_key', 'VARCHAR'), schema_columns())
        self.assertIn(('credentials', 'inception_decisions_key', 'VARCHAR'), schema_columns())
        self.assertEqual(validate_settings({
            'decision_transport': 'subq', 'decision_model': SUBQ_MODEL, 'decision_endpoint': SUBQ_ENDPOINT,
        })['decision_model'], SUBQ_MODEL)
        normalized = normalize_transport({
            'decision_transport': 'subq', 'decision_model': 'typesafe-ai/jev', 'decision_endpoint': DEFAULT_ENDPOINT,
        })
        self.assertEqual(normalized['decision_model'], SUBQ_MODEL)
        self.assertEqual(normalized['decision_endpoint'], SUBQ_ENDPOINT)
        for invalid in (
            {'decision_transport': 'subq', 'decision_model': 'other-model'},
            {'decision_transport': 'subq', 'decision_endpoint': 'https://attacker.example/decisions'},
            {'decision_transport': 'unknown'},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_settings(invalid)

    def test_inception_model_and_endpoint_are_pinned_to_the_decisions_api(self):
        self.assertEqual(validate_settings({
            'decision_transport': 'inception', 'decision_model': INCEPTION_DECISIONS_MODEL,
            'decision_endpoint': INCEPTION_DECISIONS_ENDPOINT,
        })['decision_model'], INCEPTION_DECISIONS_MODEL)
        normalized = normalize_transport({
            'decision_transport': 'inception', 'decision_model': 'other-model',
            'decision_endpoint': SUBQ_ENDPOINT,
        })
        self.assertEqual(normalized['decision_model'], INCEPTION_DECISIONS_MODEL)
        self.assertEqual(normalized['decision_endpoint'], INCEPTION_DECISIONS_ENDPOINT)
        with self.assertRaises(ValueError):
            validate_settings({'decision_transport': 'inception', 'decision_model': 'other-model'})

    def test_subq_key_encrypts_masks_and_round_trips_in_both_settings_apis(self):
        for route in ('/api/settings', '/api/ai/settings'):
            with self.subTest(route=route):
                response, status = self.request('POST', {
                    'subq_api_key': 'synthetic-subq-secret', 'decision_transport': 'subq',
                    'decision_model': SUBQ_MODEL, 'decision_endpoint': SUBQ_ENDPOINT,
                }, route=route)
                self.assertEqual(status, 200, response.json)
                self.assertNotIn('synthetic-subq-secret', str(response.json))
                self.assertEqual(response.json['subq_api_key'], '********')
                self.assertTrue(response.json['subq_api_key_configured'])
                credential = Credential.query.filter_by(user_id=1).one()
                self.assertEqual(credential.subq_api_key, 'synthetic-subq-secret')
                self.assertNotEqual(credential._subq_api_key, 'synthetic-subq-secret')

                response, status = self.request('POST', {
                    'subq_api_key': '********', 'decision_enabled': True,
                }, route=route)
                self.assertEqual(status, 200, response.json)
                db.session.expire_all()
                self.assertEqual(credential.subq_api_key, 'synthetic-subq-secret')
                response, status = self.request('GET', route=route)
                self.assertEqual(status, 200)
                self.assertTrue(response.json['subq_api_key_configured'])
                self.assertNotIn('synthetic-subq-secret', str(response.json))

    def test_inception_key_encrypts_masks_and_round_trips_in_both_settings_apis(self):
        for route in ('/api/settings', '/api/ai/settings'):
            with self.subTest(route=route):
                response, status = self.request('POST', {
                    'inception_decisions_key': 'synthetic-inception-secret', 'decision_transport': 'inception',
                    'decision_model': INCEPTION_DECISIONS_MODEL, 'decision_endpoint': INCEPTION_DECISIONS_ENDPOINT,
                }, route=route)
                self.assertEqual(status, 200, response.json)
                self.assertNotIn('synthetic-inception-secret', str(response.json))
                self.assertEqual(response.json['inception_decisions_key'], '********')
                self.assertTrue(response.json['inception_decisions_key_configured'])
                credential = Credential.query.filter_by(user_id=1).one()
                self.assertEqual(credential.inception_decisions_key, 'synthetic-inception-secret')
                self.assertNotEqual(credential._inception_decisions_key, 'synthetic-inception-secret')

    def test_save_load_encrypt_mask_preserve_replace_clear(self):
        reply, status = self.request('POST', {'ai_gateway_key': 'new-key', 'decision_enabled': True, 'decision_sentiment_mode': 'first', 'decision_confidence_threshold': .85})
        self.assertEqual(status, 200, reply.json)
        self.assertEqual(reply.json['ai_gateway_key'], '********')
        self.assertEqual(reply.json['decision_sentiment_mode'], 'first')
        credential = Credential.query.filter_by(user_id=1).one()
        self.assertEqual(credential.ai_gateway_key, 'new-key')
        self.assertNotIn('new-key', credential._ai_gateway_key)
        encrypted = credential._ai_gateway_key
        self.request('POST', {'ai_gateway_key': '********', 'decision_quant_enabled': False})
        self.assertEqual(credential._ai_gateway_key, encrypted)
        reply, status = self.request('GET')
        self.assertEqual(reply.json['ai_gateway_key'], '********')
        self.assertNotIn('new-key', str(reply.json))
        self.request('POST', {'ai_gateway_key': ''})
        self.assertFalse(credential.ai_gateway_key)

    def test_both_apis_reject_invalid_settings_before_key_write(self):
        for route in ('/api/settings', '/api/ai/settings'):
            for invalid in ({'decision_timeout_seconds': 200}, {'decision_confidence_threshold': float('nan')},
                            {'decision_enabled': 'false'},
                            {'decision_endpoint': 'https://unapproved.example/evaluate'}):
                reply, status = self.request('POST', dict(invalid, ai_gateway_key='should-not-save'), route=route)
                self.assertEqual(status, 400, reply.json)
                self.assertEqual(Credential.query.filter_by(user_id=1).one().ai_gateway_key, 'synthetic-decision-secret')

    def test_ai_settings_api_masks_round_trip(self):
        reply, status = self.request('POST', {'ai_gateway_key': '********', 'decision_sentiment_mode': 'first'}, route='/api/ai/settings')
        self.assertEqual(status, 200, reply.json)
        self.assertEqual(Credential.query.filter_by(user_id=1).one().ai_gateway_key, 'synthetic-decision-secret')
        self.assertEqual(db.session.get(UserSetting, 1).decision_sentiment_mode, 'first')

    def test_connection_uses_saved_key_without_exposing_it(self):
        with self.app.test_request_context('/api/decision/test-connection', method='POST', json={'subq_api_key': '********'}), \
             patch.object(ai, 'current_user', SimpleNamespace(id=1)), \
             patch('services.decision_engine.DecisionClient.evaluate', side_effect=DecisionError('auth')) as evaluate:
            reply, status = ai.test_decision_connection.__wrapped__()
        self.assertEqual(status, 400)
        self.assertNotIn('synthetic-subq-secret', str(reply.json))
        evaluate.assert_called_once()

    def test_subq_connection_test_uses_saved_subq_key_and_model(self):
        credential = Credential.query.filter_by(user_id=1).one()
        credential.subq_api_key = 'synthetic-subq-secret'
        db.session.commit()
        payload = {
            'decision_transport': 'subq', 'decision_model': SUBQ_MODEL, 'decision_endpoint': SUBQ_ENDPOINT,
            'subq_api_key': '********',
        }
        with self.app.test_request_context('/api/decision/test-connection', method='POST', json=payload), \
             patch.object(ai, 'current_user', SimpleNamespace(id=1)), \
             patch('services.decision_engine.DecisionClient') as client:
            client.return_value.evaluate.return_value = SimpleNamespace(
                model=SUBQ_MODEL, provider='SubQ', latency_ms=12,
            )
            reply = ai.test_decision_connection.__wrapped__()
        self.assertEqual(reply.status_code, 200)
        response_data = reply.get_json()
        self.assertEqual(response_data['provider'], 'SubQ')
        self.assertEqual(response_data['model'], SUBQ_MODEL)
        self.assertEqual(response_data['message'], 'Decision Engine connection succeeded.')
        self.assertNotIn('synthetic-subq-secret', str(response_data))
        client.assert_called_once_with(
            'synthetic-subq-secret', SUBQ_ENDPOINT, SUBQ_MODEL, 3.0, transport='subq',
        )
        client.return_value.evaluate.assert_called_once()

    def test_inception_connection_test_uses_saved_inception_key_and_model(self):
        credential = Credential.query.filter_by(user_id=1).one()
        credential.inception_decisions_key = 'synthetic-inception-secret'
        db.session.commit()
        payload = {
            'decision_transport': 'inception', 'decision_model': INCEPTION_DECISIONS_MODEL,
            'decision_endpoint': INCEPTION_DECISIONS_ENDPOINT, 'inception_decisions_key': '********',
        }
        with self.app.test_request_context('/api/decision/test-connection', method='POST', json=payload), \
             patch.object(ai, 'current_user', SimpleNamespace(id=1)), \
             patch('services.decision_engine.DecisionClient') as client:
            client.return_value.evaluate.return_value = SimpleNamespace(
                model=INCEPTION_DECISIONS_MODEL, provider='Inception', latency_ms=9,
            )
            reply = ai.test_decision_connection.__wrapped__()
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.get_json()['provider'], 'Inception')
        client.assert_called_once_with(
            'synthetic-inception-secret', INCEPTION_DECISIONS_ENDPOINT, INCEPTION_DECISIONS_MODEL, 3.0,
            transport='inception',
        )

    def test_key_prefix_smart_routing(self):
        for route in ('/api/settings', '/api/ai/settings'):
            with self.subTest(route=route):
                # sk-or- key sent as ai_gateway_key gets routed to openrouter_api_key
                reply, status = self.request('POST', {'ai_gateway_key': 'sk-or-routed-key'}, route=route)
                self.assertEqual(status, 200)
                cred = Credential.query.filter_by(user_id=1).one()
                self.assertEqual(cred.openrouter_api_key, 'sk-or-routed-key')

                # vck_ key sent as openrouter_api_key gets routed to ai_gateway_key
                reply, status = self.request('POST', {'openrouter_api_key': 'vck_routed_vercel_key'}, route=route)
                self.assertEqual(status, 200)
                cred = Credential.query.filter_by(user_id=1).one()
                self.assertEqual(cred.ai_gateway_key, 'vck_routed_vercel_key')

    def test_connection_test_reports_the_missing_key_for_the_selected_provider(self):
        credential = Credential.query.filter_by(user_id=1).one()
        credential.subq_api_key = ''
        db.session.commit()
        with self.app.test_request_context('/api/decision/test-connection', method='POST', json={}), \
             patch.object(ai, 'current_user', SimpleNamespace(id=1)), \
             patch('services.decision_engine.DecisionClient.evaluate', side_effect=DecisionError('missing_key')) as evaluate:
            reply, status = ai.test_decision_connection.__wrapped__()
        self.assertEqual(status, 400)
        self.assertEqual(reply.get_json()['code'], 'missing_key')
        evaluate.assert_called_once()




import os
import uuid
import unittest


@unittest.skipUnless(os.getenv('DECISION_TEST_DATABASE_URI'), 'Requires an isolated PostgreSQL test database')
class DecisionMigrationTests(unittest.TestCase):
    def test_additive_migration_preserves_existing_settings_and_is_repeatable(self):
        from sqlalchemy import create_engine, text
        from services.decision_settings import schema_columns
        engine = create_engine(os.environ['DECISION_TEST_DATABASE_URI'])
        schema = 'decision_migration_' + uuid.uuid4().hex
        try:
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                connection.execute(text('CREATE TABLE credentials (user_id INTEGER, existing_key TEXT)'))
                connection.execute(text('CREATE TABLE user_settings (user_id INTEGER, ai_enabled BOOLEAN)'))
                connection.execute(text("INSERT INTO credentials VALUES (1, 'preserved')"))
                connection.execute(text("INSERT INTO user_settings VALUES (1, TRUE)"))
                for _ in range(2):
                    for table, column, declaration in schema_columns():
                        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {declaration}'))
                self.assertEqual(connection.execute(text('SELECT existing_key FROM credentials')).scalar(), 'preserved')
                row = connection.execute(text('SELECT ai_enabled, decision_enabled, decision_sentiment_mode, decision_quant_enabled FROM user_settings')).one()
                self.assertEqual(tuple(row), (True, False, 'first', False))
        finally:
            engine.dispose()
