"""Isolated Decision Engine fixtures: no paid requests and no application database access."""
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
from services.decision_settings import DEFAULTS
# Imported so its tables are registered before the test schema is created.
import portfolio_algo_models  # noqa: F401


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
    return {'model': 'subq-snap-preview', 'answers': answers, 'usage': {'inputTokens': 20, 'outputTokens': 10},
            'providerMetadata': {'gateway': {'cost': '0.000001'}, 'typesafe': {'confidence': {}}}}


def noul_payload(questions, model='subq-snap-preview', direction='bullish', probability=.9):
    """Convert the internal answer contract into the provider wire format."""
    answers = {}
    for key, answer in response_for(questions, direction, probability)['answers'].items():
        question = questions[key]
        if question['type'] == 'boolean':
            answers[key] = {'type': 'noul', 'noul': answer['probability']}
        else:
            answers[key] = {**answer, 'confidence': .95}
            if question['type'] == 'score':
                answers[key]['legend'] = {str(index): str(level)
                                          for index, level in enumerate(question['criteria'])}
    return {'model': model, 'answers': answers, 'usage': {'inputTokens': 20, 'outputTokens': 10}}


class DecisionTestCase(TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='isolated-test', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        postgres_uri = os.getenv('DECISION_TEST_DATABASE_URI')
        if postgres_uri:
            schema = 'decision_test_' + uuid.uuid4().hex
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
        db.session.add(User(id=1, username='decision-test', pwd_hash='unused'))
        db.session.add(User(id=2, username='other', pwd_hash='unused'))
        self.config = dict(DEFAULTS, decision_enabled=True, decision_sentiment_mode='first',
                           decision_quant_enabled=True)
        db.session.add(UserSetting(user_id=1, ai_enabled=True, **self.config))
        db.session.add(Credential(user_id=1, username='decision-test', ai_gateway_key='synthetic-decision-secret',
                                  subq_api_key='synthetic-subq-secret'))
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
