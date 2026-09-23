"""Isolated Jev fixtures: no paid requests and no application database access."""
from datetime import datetime, timezone
import os
import uuid
from sqlalchemy import create_engine, text
from unittest import TestCase
from unittest.mock import patch
from cryptography.fernet import Fernet
from flask import Flask
from core.extensions import db
from credentials import Credential, User, UserSetting
from services.jev_settings import DEFAULTS


def response_for(questions, direction='bullish', probability=.9):
    answers = {}
    for key, question in questions.items():
        kind = question['type']
        if kind == 'boolean':
            answers[key] = {'type': kind, 'probability': .85 if key in ('bullish', 'confirm_entry') else .1}
        elif kind == 'choice':
            choices = list(question['criteria'])
            selected = direction if key == 'direction' else choices[0]
            answers[key] = {'type': kind, 'choice': selected,
                'probabilities': {c: probability if c == selected else (1-probability)/(len(choices)-1) for c in choices}}
        else:
            answers[key] = {'type': kind, 'score': 3.0,
                           'probabilities': {str(i): float(i == 3) for i in range(len(question['criteria']))}}
    return {'model': 'typesafe-ai/jev', 'answers': answers, 'usage': {'inputTokens': 20, 'outputTokens': 10},
            'providerMetadata': {'gateway': {'cost': '0.000001'}, 'typesafe': {'confidence': {}}}}


class JevTestCase(TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='isolated-test', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        postgres_uri = os.getenv('JEV_TEST_DATABASE_URI')
        if postgres_uri:
            schema = 'jev_test_' + uuid.uuid4().hex
            bootstrap = create_engine(postgres_uri)
            with bootstrap.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            bootstrap.dispose()
            self.app.config.update(SQLALCHEMY_DATABASE_URI=postgres_uri,
                SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'options': f'-csearch_path={schema}'}})
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.encryption = patch('credential_security._get_fernet', return_value=Fernet(Fernet.generate_key()))
        self.encryption.start()
        db.session.add(User(id=1, username='jev-test', pwd_hash='unused'))
        db.session.add(User(id=2, username='other', pwd_hash='unused'))
        self.config = dict(DEFAULTS, jev_enabled=True, jev_sentiment_mode='shadow', jev_quant_shadow_enabled=True)
        db.session.add(UserSetting(user_id=1, ai_enabled=True, **self.config))
        db.session.add(Credential(user_id=1, username='jev-test', ai_gateway_key='synthetic-jev-secret'))
        db.session.commit()
        self.now = datetime.now(timezone.utc)
        self.state = {'symbol': 'BTC', 'instrument_type': 'CRYPTO', 'current_price': 100,
                      'forecast_horizon_hours': 24, 'decision_time': self.now.isoformat(),
                      'evidence': [{'title': 'Test news', 'available_at': self.now.isoformat()}]}

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.encryption.stop()
        self.context.pop()
