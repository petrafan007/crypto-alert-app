import unittest
from datetime import datetime
from pathlib import Path

from flask import Flask

from core.extensions import db, login_manager
from credentials import User
from models import AICopilotSession, AIConversation
from routes.ai import (
    _build_copilot_history_context,
    _extract_copilot_session_title,
    ai_bp,
)
from services.ai_service import log_ai_conversation


class CopilotSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='copilot-session-test',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        login_manager.init_app(cls.app)

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

        cls.app.register_blueprint(ai_bp)
        cls.context = cls.app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.context.pop()

    def setUp(self):
        db.session.rollback()
        db.session.query(AIConversation).delete()
        db.session.query(AICopilotSession).delete()
        db.session.query(User).delete()
        db.session.commit()
        self.user = self._create_user('copilot-owner')
        self.other_user = self._create_user('other-user')
        self.client = self.app.test_client()
        self._login(self.client, self.user)

    def tearDown(self):
        db.session.rollback()
        db.session.close()

    @staticmethod
    def _login(client, user):
        with client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    @staticmethod
    def _conversation(user_id, session_id, sender, body):
        return AIConversation(
            user_id=user_id,
            conversation_id=session_id,
            prompt_type='manual',
            sender=sender,
            body=body,
            date=datetime(2026, 9, 4).date(),
            time='10:00:00',
            created_at=datetime(2026, 9, 4, 10, 0),
        )

    @staticmethod
    def _create_user(username):
        user = User(username=username, email=f'{username}@example.com')
        user.set_password('ValidPassword!234')
        db.session.add(user)
        db.session.commit()
        return user

    def test_new_session_is_user_owned_and_session_messages_are_isolated(self):
        created = self.client.post('/api/ai/copilot-sessions')
        self.assertEqual(created.status_code, 201)
        session_id = created.get_json()['session']['id']

        db.session.add_all([
            self._conversation(self.user.id, session_id, 'user', 'What is BTC doing today?'),
            self._conversation(self.user.id, session_id, 'ai', 'BTC has a fresh market-data summary.'),
        ])
        db.session.commit()

        listing = self.client.get('/api/ai/copilot-sessions').get_json()['sessions']
        self.assertEqual(listing[0]['id'], session_id)
        self.assertEqual(listing[0]['message_count'], 2)

        messages = self.client.get(f'/api/ai/conversations?session_id={session_id}').get_json()
        self.assertEqual(messages['total'], 2)
        self.assertEqual({message['conversation_id'] for message in messages['conversations']}, {session_id})

        other_session = AICopilotSession(id='other-session', user_id=self.other_user.id, title='Other user')
        db.session.add(other_session)
        db.session.commit()
        denied = self.client.get('/api/ai/conversations?session_id=other-session')
        self.assertEqual(denied.status_code, 404)

    def test_cross_session_history_is_opt_in_and_user_scoped(self):
        current = AICopilotSession(id='current-session', user_id=self.user.id, title='Current')
        previous = AICopilotSession(id='previous-session', user_id=self.user.id, title='Previous')
        another_user = AICopilotSession(id='another-user-session', user_id=self.other_user.id, title='Private')
        db.session.add_all([current, previous, another_user])
        db.session.add_all([
            self._conversation(self.user.id, 'current-session', 'user', 'Current BTC question'),
            self._conversation(self.user.id, 'previous-session', 'ai', 'BTC prior-session detail'),
            self._conversation(self.other_user.id, 'another-user-session', 'ai', 'BTC other-user private detail'),
        ])
        db.session.commit()

        label, isolated = _build_copilot_history_context(
            self.user.id, 'current-session', 'BTC question', include_all_sessions=False,
        )
        self.assertEqual(label, 'CURRENT ISOLATED COPILOT SESSION')
        self.assertIn('Current BTC question', isolated)
        self.assertNotIn('prior-session detail', isolated)

        label, historical = _build_copilot_history_context(
            self.user.id, 'current-session', 'BTC question', include_all_sessions=True,
        )
        self.assertIn('EXPLICITLY REQUESTED', label)
        self.assertIn('BTC prior-session detail', historical)
        self.assertNotIn('other-user private detail', historical)

    def test_ai_title_envelope_is_removed_and_messages_persist_the_session_id(self):
        title, response = _extract_copilot_session_title(
            'SESSION_TITLE: Bitcoin Risk Review\n\nThe answer starts here.'
        )
        self.assertEqual(title, 'Bitcoin Risk Review')
        self.assertEqual(response, 'The answer starts here.')

        message_id = log_ai_conversation(
            self.user.id,
            'manual',
            'user',
            'Persist this message in its chat.',
            conversation_id='current-session',
        )
        logged = db.session.get(AIConversation, message_id)
        self.assertEqual(logged.conversation_id, 'current-session')

    def test_frontend_positions_completed_reply_at_the_question_not_message_bottom(self):
        source = Path('frontend/src/components/AICopilotSidebar.jsx').read_text()
        self.assertIn('scrollToResponseStart(userMessage.id)', source)
        self.assertNotIn('scrollToBottom', source)


if __name__ == '__main__':
    unittest.main()
