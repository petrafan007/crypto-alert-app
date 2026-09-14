"""Fallback cooldowns shared by independent app connections on isolated PostgreSQL."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from flask import Flask
from sqlalchemy.schema import CreateSchema

from core.extensions import db
from services import provider_resilience as resilience
from services.ai_service import web_search
from tests.test_provider_resilience import search_response


@unittest.skipUnless(os.environ.get('QUANT_SEARCH_TEST_DATABASE_URI'), 'Requires isolated PostgreSQL')
class SearchCooldownDatabaseTests(unittest.TestCase):
    def setUp(self):
        schema = 'search_test_'+uuid4().hex
        self.apps = [Flask('search-worker'), Flask('search-web')]
        for app in self.apps:
            app.config.update(SQLALCHEMY_DATABASE_URI=os.environ['QUANT_SEARCH_TEST_DATABASE_URI'], TESTING=True,
                SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'options': '-csearch_path='+schema}})
            db.init_app(app)
        with self.apps[0].app_context():
            with db.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
            resilience.ProviderState.__table__.create(db.engine)

    def tearDown(self):
        for app in self.apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_worker_cooldown_blocks_web_requests_for_same_user_but_not_other_users(self):
        with patch('services.ai_service.get_user_credentials', return_value=None), \
                patch.object(resilience.requests, 'post', return_value=search_response(503)) as post, \
                patch.object(resilience.requests, 'get', return_value=search_response(429, headers={'Retry-After': '120'})) as get:
            with self.apps[0].app_context():
                worker_engine = db.engine
                self.assertEqual(web_search('BTC news', username='alice'), [])
            with self.apps[1].app_context():
                self.assertIsNot(db.engine, worker_engine)
                self.assertEqual(web_search('ETH news', username='alice'), [])
                self.assertEqual((post.call_count, get.call_count), (1, 1))
                self.assertEqual({item['service'] for item in resilience.health('alice')}, {'DuckDuckGo', 'Google News RSS'})
                self.assertEqual(web_search('ETH news', username='bob'), [])
                self.assertEqual((post.call_count, get.call_count), (2, 2))
                self.assertEqual(db.engine.pool.checkedout(), 0)
