import unittest

from flask import Flask, g, jsonify

from core.extensions import db, login_manager
from credentials import Credential, OnboardingDefaultProfile, User, UserSetting
from models import AIPrompt
from routes.auth import auth_bp
from services.onboarding_service import seed_new_user_defaults, snapshot_defaults


class OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='onboarding-test',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        login_manager.init_app(cls.app)

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

        cls.app.register_blueprint(auth_bp)

        @cls.app.get('/private')
        def private_page():
            return 'private'

        @cls.app.get('/api/private')
        def private_api():
            return jsonify(success=True)

        cls.context = cls.app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.context.pop()

    def setUp(self):
        g.pop('_login_user', None)
        db.session.remove()
        for model in (AIPrompt, Credential, OnboardingDefaultProfile, UserSetting, User):
            db.session.query(model).delete()
        db.session.commit()

    def create_user(self, username, required=True):
        user = User(username=username, email=f'{username}@example.com')
        user.set_password('ValidPassword!234')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserSetting(
            user_id=user.id,
            onboarding_required=required,
            onboarding_completed=False,
            onboarding_page='exchanges',
        ))
        db.session.commit()
        return user

    def login(self, client, user):
        with client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def test_required_user_is_blocked_from_pages_and_apis(self):
        user = self.create_user('required')
        client = self.app.test_client()
        self.login(client, user)
        page = client.get('/private')
        api = client.get('/api/private')
        self.assertEqual(page.status_code, 302)
        self.assertTrue(page.headers['Location'].endswith('/onboarding'))
        self.assertEqual(api.status_code, 428)
        self.assertTrue(api.get_json()['onboarding_required'])

    def test_registration_creates_required_resumable_onboarding(self):
        response = self.app.test_client().post('/register', json={
            'username': 'newbeta',
            'email': 'newbeta@example.com',
            'password': 'StrongPassword!234',
            'accepted_terms': True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['redirect'], '/onboarding')
        user = User.query.filter_by(username='newbeta').one()
        setting = db.session.get(UserSetting, user.id)
        self.assertTrue(setting.onboarding_required)
        self.assertFalse(setting.onboarding_completed)
        self.assertEqual(setting.onboarding_page, 'security-choice')
        self.assertEqual(setting.webull_environment, 'production')

    def test_existing_user_is_not_forced_into_onboarding(self):
        user = self.create_user('existing', required=False)
        client = self.app.test_client()
        self.login(client, user)
        self.assertEqual(client.get('/private').status_code, 200)

    def test_dashboard_gate_requires_one_verified_selected_exchange(self):
        user = self.create_user('gate')
        setting = db.session.get(UserSetting, user.id)
        setting.onboarding_exchange_choice = 'both'
        db.session.commit()
        client = self.app.test_client()
        self.login(client, user)
        rejected = client.post('/api/onboarding/finish')
        self.assertEqual(rejected.status_code, 400)
        setting.onboarding_binance_verified = True
        db.session.commit()
        accepted = client.post('/api/onboarding/finish')
        self.assertEqual(accepted.status_code, 200)
        db.session.refresh(setting)
        self.assertTrue(setting.onboarding_completed)
        self.assertFalse(setting.onboarding_required)

    def test_default_snapshot_creates_independent_nonsecret_copies(self):
        owner = self.create_user('owner', required=False)
        owner_setting = db.session.get(UserSetting, owner.id)
        owner_setting.max_slippage_pct = 1.25
        owner_setting.tax_cost_basis_method = 'fifo'
        db.session.add(AIPrompt(user_id=owner.id, market_analysis_pre='Owner default prompt'))
        snapshot_defaults(owner.id)
        first = self.create_user('first')
        second = self.create_user('second')
        first_setting, first_prompts = seed_new_user_defaults(first.id, db.session.get(UserSetting, first.id))
        second_setting, second_prompts = seed_new_user_defaults(second.id, db.session.get(UserSetting, second.id))
        db.session.commit()
        self.assertEqual(first_setting.max_slippage_pct, 1.25)
        self.assertEqual(second_prompts.market_analysis_pre, 'Owner default prompt')
        first_setting.max_slippage_pct = 9.0
        first_prompts.market_analysis_pre = 'Changed only for first'
        db.session.commit()
        self.assertEqual(second_setting.max_slippage_pct, 1.25)
        self.assertEqual(second_prompts.market_analysis_pre, 'Owner default prompt')


if __name__ == '__main__':
    unittest.main()
