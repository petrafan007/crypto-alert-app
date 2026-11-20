"""Tests for the Muse-placed orders channel (v4.19.15).

Covers the spoken-PIN lifecycle, the TOTP-gated Settings endpoints, the
agent API (draft → confirm / replace / cancel), environment resolution
(real vs paper accounts), paper routing, the account switchboard, the
lockout, and the audit trail. Every broker is mocked — no live order can
be placed from these tests.
"""

import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault('CREDENTIALS_ENCRYPTION_KEY', Fernet.generate_key().decode())

import pyotp
from flask import Flask

import credential_security
from claude_agent_models import ClaudeAgentConfig, ClaudeOrderAudit, ClaudeOrderDraft
from core.extensions import db, login_manager
from credentials import Credential, User, UserSetting
from models import WebullOrder, WebullTestOrder
from routes.claude_agent import claude_agent_bp
from services import claude_agent_service as agent
from trading_models import (
    LadderOrder, LadderRung, RealOrder, SyntheticExecution, SyntheticRecovery,
    TestOrder, TestPortfolio, TradingSettings, TrailingOrder,
)

FAKE_PIN = '135790'
OTHER_PIN = '246802'


class _Query:
    def __init__(self, value):
        self.value = value

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self.value


EXCHANGE_INFO = {
    'symbols': [{
        'symbol': 'BTCUSDT', 'status': 'TRADING',
        'baseAssetPrecision': 8, 'quotePrecision': 8,
        'filters': [
            {'filterType': 'LOT_SIZE', 'minQty': '0.00001000',
             'maxQty': '9000.00000000', 'stepSize': '0.00001000'},
            {'filterType': 'PRICE_FILTER', 'minPrice': '0.01000000',
             'maxPrice': '1000000.00000000', 'tickSize': '0.01000000'},
            {'filterType': 'MIN_NOTIONAL', 'minNotional': '10.00000000'},
        ],
    }],
}


class FakeBinanceClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_exchange_info(self):
        return EXCHANGE_INFO

    def get_symbol_ticker(self, symbol=None):
        return {'symbol': symbol or 'BTCUSDT', 'price': '50000.00'}

    def create_order(self, **params):
        return {
            'orderId': 424242, 'clientOrderId': 'fake-client-1',
            'status': 'NEW', 'executedQty': '0.00000000',
            'cummulativeQuoteQty': '0.00000000', 'fills': [],
            'timeInForce': 'GTC',
        }


def _webull_setting(test_mode=False):
    return SimpleNamespace(webull_test_mode_enabled=test_mode,
                           webull_environment='production')


def _webull_credential():
    return SimpleNamespace(
        webull_app_key='fake-app-key', webull_app_secret='fake-app-secret',
        webull_access_token='fake-access-token', webull_token_status='NORMAL',
        webull_token_environment='production',
        trading_api_key='fake-trading-key', trading_api_secret='fake-trading-secret')


class ClaudeAgentTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        credential_security._get_fernet.cache_clear()
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='claude-agent-test',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        login_manager.init_app(cls.app)

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

        cls.app.register_blueprint(claude_agent_bp)
        cls.context = cls.app.app_context()
        cls.context.push()
        tables = [
            User.__table__, TradingSettings.__table__,
            ClaudeAgentConfig.__table__, ClaudeOrderDraft.__table__,
            ClaudeOrderAudit.__table__, LadderOrder.__table__,
            LadderRung.__table__, SyntheticExecution.__table__,
            SyntheticRecovery.__table__,
            TrailingOrder.__table__, RealOrder.__table__,
            TestOrder.__table__, TestPortfolio.__table__,
            WebullOrder.__table__, WebullTestOrder.__table__,
        ]
        db.metadata.create_all(bind=db.engine, tables=tables)

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        cls.context.pop()

    def setUp(self):
        db.session.rollback()
        for model in (ClaudeOrderAudit, ClaudeOrderDraft, ClaudeAgentConfig,
                      TradingSettings, SyntheticRecovery, SyntheticExecution,
                      LadderRung, LadderOrder,
                      TrailingOrder, RealOrder,
                      TestOrder, TestPortfolio, WebullOrder, WebullTestOrder, User):
            db.session.query(model).delete()
        db.session.commit()
        self.user = User(username='pin-owner', pwd_hash='not-a-real-hash')
        db.session.add(self.user)
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)

    # -- helpers -----------------------------------------------------------
    def _enable_with_pin(self, pin=FAKE_PIN):
        config = agent.get_or_create_config(self.user.id)
        config.enabled = True
        db.session.commit()
        agent.set_pin(config, pin)
        return agent.generate_agent_key(config)

    def _headers(self, key):
        return {'X-Claude-Agent-Key': key}

    def _totp_settings(self):
        secret = pyotp.random_base32()
        row = TradingSettings(user_id=self.user.id, totp_secret=secret,
                              test_mode_enabled=True)
        db.session.add(row)
        db.session.commit()
        return secret

    def _reset_totp_consumption(self):
        row = TradingSettings.query.filter_by(user_id=self.user.id).first()
        if row:
            row.totp_last_used_step = None
            db.session.commit()

    def _draft(self, key, kind, spec):
        return self.client.post('/api/claude-agent/drafts',
                                json={'kind': kind, 'spec': spec},
                                headers=self._headers(key))

    def _confirm(self, key, draft_id, pin):
        return self.client.post(f'/api/claude-agent/drafts/{draft_id}/confirm',
                                json={'pin': pin}, headers=self._headers(key))


class PinLifecycleTests(ClaudeAgentTestBase):
    def test_set_pin_validates_format(self):
        config = agent.get_or_create_config(self.user.id)
        with self.assertRaises(agent.ClaudeAgentError):
            agent.set_pin(config, '12345')
        with self.assertRaises(agent.ClaudeAgentError):
            agent.set_pin(config, 'abcdef')
        agent.set_pin(config, FAKE_PIN)
        self.assertTrue(agent.pin_is_active(config))

    def test_verify_success_and_failure_accounting(self):
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        self.assertFalse(agent.verify_pin(config, OTHER_PIN))
        self.assertEqual(config.failed_attempts, 1)
        self.assertTrue(agent.verify_pin(config, FAKE_PIN))
        self.assertEqual(config.failed_attempts, 0)

    def test_expired_pin_never_verifies(self):
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        config.pin_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        self.assertFalse(agent.pin_is_active(config))
        self.assertFalse(agent.verify_pin(config, FAKE_PIN))

    def test_auto_generate_on_expiry(self):
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        config.pin_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        self.assertTrue(agent.refresh_pin_lifecycle(config))
        self.assertTrue(agent.pin_is_active(config))
        self.assertGreater(config.pin_expires_at, datetime.utcnow())
        from credential_security import decrypt_secret
        self.assertNotEqual(decrypt_secret(config.pin_encrypted), FAKE_PIN)

    def test_no_auto_generate_when_toggle_off(self):
        config = agent.get_or_create_config(self.user.id)
        config.auto_generate_enabled = False
        agent.set_pin(config, FAKE_PIN)
        config.pin_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        self.assertFalse(agent.refresh_pin_lifecycle(config))
        self.assertFalse(agent.pin_is_active(config))

    def test_regenerate_changes_pin(self):
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        agent.generate_new_pin(config)
        from credential_security import decrypt_secret
        self.assertNotEqual(decrypt_secret(config.pin_encrypted), FAKE_PIN)
        self.assertTrue(agent.pin_is_active(config))


class SettingsEndpointTests(ClaudeAgentTestBase):
    def test_pin_set_requires_totp(self):
        self._totp_settings()
        response = self.client.post('/api/claude-agent/pin', json={'pin': FAKE_PIN})
        self.assertEqual(response.status_code, 403)
        config = agent.get_or_create_config(self.user.id)
        self.assertFalse(config.pin_encrypted)

    def test_pin_set_with_totp(self):
        secret = self._totp_settings()
        code = pyotp.TOTP(secret).now()
        response = self.client.post(
            '/api/claude-agent/pin',
            json={'pin': FAKE_PIN, 'two_factor_code': code})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['config']['pin_set'])

    def test_reveal_refused_without_totp_and_allowed_with_it(self):
        secret = self._totp_settings()
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        refused = self.client.post('/api/claude-agent/pin/reveal', json={})
        self.assertEqual(refused.status_code, 403)
        self.assertNotIn(FAKE_PIN, refused.get_data(as_text=True))
        self._reset_totp_consumption()
        code = pyotp.TOTP(secret).now()
        allowed = self.client.post(
            '/api/claude-agent/pin/reveal', json={'two_factor_code': code})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual(allowed.get_json()['pin'], FAKE_PIN)

    def test_enable_requires_totp(self):
        secret = self._totp_settings()
        refused = self.client.put('/api/claude-agent/config', json={'enabled': True})
        self.assertEqual(refused.status_code, 403)
        code = pyotp.TOTP(secret).now()
        allowed = self.client.put(
            '/api/claude-agent/config',
            json={'enabled': True, 'two_factor_code': code})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertTrue(allowed.get_json()['config']['enabled'])

    def test_config_status_never_leaks_pin(self):
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        response = self.client.get('/api/claude-agent/config')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(FAKE_PIN, response.get_data(as_text=True))
        self.assertTrue(response.get_json()['config']['pin_set'])


class AgentApiTests(ClaudeAgentTestBase):
    def test_agent_key_required(self):
        response = self.client.post('/api/claude-agent/drafts',
                                    json={'kind': 'webull_native', 'spec': {}})
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            '/api/claude-agent/drafts', json={'kind': 'webull_native', 'spec': {}},
            headers=self._headers('claude_bogus-key'))
        self.assertEqual(response.status_code, 401)

    def test_feature_off_refuses_drafts(self):
        config = agent.get_or_create_config(self.user.id)
        agent.set_pin(config, FAKE_PIN)
        key = agent.generate_agent_key(config)
        response = self._draft(key, 'webull_native',
                               {'account_id': 'ACCT1', 'symbol': 'ANT'})
        self.assertEqual(response.status_code, 403)

    def test_no_pin_refuses_drafts(self):
        config = agent.get_or_create_config(self.user.id)
        config.enabled = True
        db.session.commit()
        key = agent.generate_agent_key(config)
        response = self._draft(key, 'webull_native',
                               {'account_id': 'ACCT1', 'symbol': 'ANT'})
        self.assertEqual(response.status_code, 403)

    def test_draft_expiry_blocks_confirm(self):
        key = self._enable_with_pin()
        with patch.object(UserSetting, 'query', _Query(_webull_setting())):
            created = self._draft(key, 'webull_native', {
                'account_id': 'ACCT1', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
        self.assertEqual(created.status_code, 201, created.get_json())
        draft_id = created.get_json()['draft']['id']
        draft = db.session.get(ClaudeOrderDraft, draft_id)
        draft.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        response = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.session.get(ClaudeOrderDraft, draft_id).status, 'EXPIRED')

    def test_lockout_after_three_failed_pins(self):
        key = self._enable_with_pin()
        with patch.object(UserSetting, 'query', _Query(_webull_setting())):
            created = self._draft(key, 'webull_native', {
                'account_id': 'ACCT1', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
        draft_id = created.get_json()['draft']['id']
        for _ in range(3):
            response = self._confirm(key, draft_id, OTHER_PIN)
            self.assertEqual(response.status_code, 403)
        config = agent.get_or_create_config(self.user.id)
        self.assertTrue(config.locked)
        response = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.session.get(ClaudeOrderDraft, draft_id).status, 'PENDING')

    def test_disabled_account_refused_while_others_work(self):
        key = self._enable_with_pin()
        config = agent.get_or_create_config(self.user.id)
        agent.set_disabled_accounts(config, ['webull:ACCT1'])
        with patch.object(UserSetting, 'query', _Query(_webull_setting())):
            refused = self._draft(key, 'webull_native', {
                'account_id': 'ACCT1', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
            allowed = self._draft(key, 'webull_native', {
                'account_id': 'ACCT2', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(allowed.status_code, 201, allowed.get_json())


class PlacementRoutingTests(ClaudeAgentTestBase):
    def test_webull_native_real_routing_and_audit(self):
        key = self._enable_with_pin()
        with patch.object(UserSetting, 'query', _Query(_webull_setting())), \
                patch.object(Credential, 'query', _Query(_webull_credential())), \
                patch('services.webull_service.place_webull_order',
                      return_value={'order_id': 'W123'}) as place:
            created = self._draft(key, 'webull_native', {
                'account_id': 'ACCT1', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
            self.assertEqual(created.status_code, 201, created.get_json())
            readback = created.get_json()['draft']['readback']
            self.assertIn('REAL account', readback['summary'])
            draft_id = created.get_json()['draft']['id']
            confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        place.assert_called_once()
        self.assertEqual(place.call_args.kwargs['account_id'], 'ACCT1')
        self.assertEqual(db.session.get(ClaudeOrderDraft, draft_id).status, 'CONFIRMED')
        audit = ClaudeOrderAudit.query.filter_by(user_id=self.user.id).all()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0].action, 'place')
        self.assertEqual(audit[0].result_status, 'SUCCESS')
        self.assertEqual(audit[0].broker_order_id, 'W123')
        self.assertEqual(audit[0].environment, 'real')

    def test_webull_paper_routing(self):
        key = self._enable_with_pin()
        with patch.object(UserSetting, 'query', _Query(_webull_setting(test_mode=True))), \
                patch('services.webull_paper_trading_service.execute_webull_test_order',
                      return_value={'order_id': 'SIM999'}) as paper_place, \
                patch('services.webull_service.place_webull_order') as live_place:
            created = self._draft(key, 'webull_native', {
                'account_id': 'TEST_PAPER_ACCOUNT', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
            self.assertEqual(created.status_code, 201, created.get_json())
            readback = created.get_json()['draft']['readback']
            self.assertIn('PAPER account', readback['summary'])
            draft_id = created.get_json()['draft']['id']
            confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        paper_place.assert_called_once()
        live_place.assert_not_called()

    def test_synthetic_ladder_routing_and_source_marker(self):
        key = self._enable_with_pin()
        ladder = LadderOrder(id=777, user_id=self.user.id, symbol='BTCUSDT',
                             side='BUY', total_quantity=0.5, broker='binance',
                             test_mode=True)
        db.session.add(ladder)
        db.session.commit()
        with patch('services.synthetic_execution_service.check_synthetic_order_capacity'), \
                patch('services.ladder_order_service.create_ladder_order',
                      return_value={'id': 777}) as create:
            created = self._draft(key, 'synthetic_ladder', {
                'broker': 'binance', 'test_mode': True, 'symbol': 'BTCUSDT',
                'side': 'BUY', 'total_quantity': 0.5})
            self.assertEqual(created.status_code, 201, created.get_json())
            draft_id = created.get_json()['draft']['id']
            confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        create.assert_called_once()
        self.assertEqual(db.session.get(LadderOrder, 777).source, 'CLAUDE_AGENT')
        audit = ClaudeOrderAudit.query.filter_by(user_id=self.user.id).all()
        self.assertEqual(audit[0].ladder_order_id, 777)

    def test_synthetic_conditional_routing(self):
        key = self._enable_with_pin()
        parent = LadderOrder(user_id=self.user.id, symbol='ANT', side='BUY',
                             total_quantity=4, broker='webull', test_mode=False)
        db.session.add(parent)
        db.session.commit()
        with patch('services.synthetic_execution_service.check_synthetic_order_capacity'), \
                patch('services.synthetic_conditional_service.create_conditional',
                      return_value=parent) as create:
            created = self._draft(key, 'synthetic_conditional', {
                'broker': 'webull', 'account_id': 'ACCT1', 'test_mode': False,
                'symbol': 'ANT', 'side': 'BUY', 'total_quantity': 4})
            self.assertEqual(created.status_code, 201, created.get_json())
            draft_id = created.get_json()['draft']['id']
            with patch.object(UserSetting, 'query', _Query(_webull_setting())):
                confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        create.assert_called_once()
        self.assertEqual(parent.source, 'CLAUDE_AGENT')

    def test_binance_spot_real_routing(self):
        key = self._enable_with_pin()
        with patch.object(TradingSettings, 'query',
                          _Query(SimpleNamespace(test_mode_enabled=False))), \
                patch.object(Credential, 'query', _Query(_webull_credential())), \
                patch('binance.client.Client', FakeBinanceClient):
            created = self._draft(key, 'binance_spot', {
                'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET',
                'quantity': 0.01})
            self.assertEqual(created.status_code, 201, created.get_json())
            draft_id = created.get_json()['draft']['id']
            confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        orders = RealOrder.query.filter_by(user_id=self.user.id).all()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].binance_order_id, 424242)
        self.assertEqual(orders[0].source, 'CLAUDE_AGENT')

    def test_binance_paper_routing(self):
        key = self._enable_with_pin()
        db.session.add(TestPortfolio(user_id=self.user.id, symbol='USDT',
                                     quantity=100000.0, total_cost_basis=100000.0,
                                     realized_pnl=0.0))
        db.session.commit()
        with patch.object(TradingSettings, 'query',
                          _Query(SimpleNamespace(test_mode_enabled=True))), \
                patch('services.synthetic_execution_service.binance_client',
                      return_value=FakeBinanceClient()):
            created = self._draft(key, 'binance_spot', {
                'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET',
                'quantity': 0.01})
            self.assertEqual(created.status_code, 201, created.get_json())
            self.assertIn('PAPER account',
                          created.get_json()['draft']['readback']['summary'])
            draft_id = created.get_json()['draft']['id']
            confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        orders = TestOrder.query.filter_by(user_id=self.user.id).all()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].source, 'CLAUDE_AGENT')
        self.assertEqual(orders[0].status, 'FILLED')

    def test_binance_staking_routing(self):
        key = self._enable_with_pin()
        with patch.object(Credential, 'query', _Query(_webull_credential())), \
                patch('services.staking_purchase_service.purchase',
                      return_value={'status': 'SUBMITTED'}) as purchase:
            created = self._draft(key, 'binance_staking', {
                'asset': 'SOL', 'quoteAsset': 'USD', 'quoteAmount': '50'})
            self.assertEqual(created.status_code, 201, created.get_json())
            draft_id = created.get_json()['draft']['id']
            confirmed = self._confirm(key, draft_id, FAKE_PIN)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        purchase.assert_called_once()

    def test_replace_native_routing(self):
        key = self._enable_with_pin()
        with patch.object(UserSetting, 'query', _Query(_webull_setting())), \
                patch.object(Credential, 'query', _Query(_webull_credential())), \
                patch('services.order_replacement_service.cancel_any_order',
                      return_value={'success': True, 'order_id': 'W100'}) as cancel, \
                patch('services.webull_service.place_webull_order',
                      return_value={'order_id': 'W200'}) as place:
            response = self.client.post('/api/claude-agent/replace', json={
                'order_id': 'W100', 'kind': 'webull_native',
                'spec': {'account_id': 'ACCT1', 'symbol': 'ANT', 'side': 'BUY',
                         'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 82},
                'pin': FAKE_PIN}, headers=self._headers(key))
        self.assertEqual(response.status_code, 200, response.get_json())
        cancel.assert_called_once()
        place.assert_called_once()
        audit = ClaudeOrderAudit.query.filter_by(user_id=self.user.id).all()
        self.assertEqual(audit[0].action, 'replace')

    def test_replace_synthetic_routing(self):
        key = self._enable_with_pin()
        with patch('services.order_replacement_service.cancel_any_order',
                   return_value={'success': True, 'order_id': '55'}) as cancel, \
                patch('services.ladder_order_service.create_ladder_order',
                      return_value={'id': 778}) as create:
            response = self.client.post('/api/claude-agent/replace', json={
                'order_id': 'ladder_55', 'kind': 'synthetic_ladder',
                'spec': {'broker': 'binance', 'test_mode': True,
                         'symbol': 'BTCUSDT', 'side': 'BUY', 'total_quantity': 0.25},
                'pin': FAKE_PIN}, headers=self._headers(key))
        self.assertEqual(response.status_code, 200, response.get_json())
        cancel.assert_called_once()
        create.assert_called_once()

    def test_cancel_routing(self):
        key = self._enable_with_pin()
        with patch('services.order_replacement_service.cancel_any_order',
                   return_value={'success': True}) as cancel:
            response = self.client.post('/api/claude-agent/cancel', json={
                'order_id': 'ladder_55', 'pin': FAKE_PIN, 'broker': 'binance'},
                headers=self._headers(key))
        self.assertEqual(response.status_code, 200, response.get_json())
        cancel.assert_called_once()
        audit = ClaudeOrderAudit.query.filter_by(user_id=self.user.id).all()
        self.assertEqual(audit[0].action, 'cancel')
        self.assertEqual(audit[0].result_status, 'SUCCESS')

    def test_wrong_pin_places_nothing(self):
        key = self._enable_with_pin()
        with patch.object(UserSetting, 'query', _Query(_webull_setting())), \
                patch('services.webull_service.place_webull_order') as place:
            created = self._draft(key, 'webull_native', {
                'account_id': 'ACCT1', 'symbol': 'ANT', 'side': 'BUY',
                'order_type': 'LIMIT', 'quantity': 5, 'limit_price': 80})
            draft_id = created.get_json()['draft']['id']
            response = self._confirm(key, draft_id, OTHER_PIN)
        self.assertEqual(response.status_code, 403)
        place.assert_not_called()
        self.assertEqual(ClaudeOrderAudit.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
