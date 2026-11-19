"""Replace flow for synthetic conditional (combo) orders.

The combo builder's Replace action re-enters the conditional create route
with ``replacing_order_id='ladder_<id>'``: the route cancels the old parent
through the same replacement machinery the ladder/trailing routes use and
then creates the edited order, so a changed limit takes effect and a
guardian (backstop) link round-trips into the replacement's spec. All venue
I/O is mocked; these tests never connect to a broker or the app database.
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.extensions import db
from models import WebullOrder
from trading_models import LadderOrder
from services import synthetic_execution_service as ex
from services import synthetic_conditional_service as conditional
from services.order_replacement_service import cancel_any_order
from tests import test_synthetic_order_lifecycle as base


class ConditionalReplaceTests(base.SyntheticLifecycleTests):
    def setUp(self):
        super().setUp()
        WebullOrder.__table__.create(db.engine, checkfirst=True)
        cred = SimpleNamespace(webull_app_key='key', webull_app_secret='secret',
                               webull_access_token='token')
        self.extra_patchers = [
            patch.object(ex, 'webull_credentials', return_value=(cred, 'production')),
            patch('services.webull_service.get_webull_account_balance',
                  return_value={'available_cash': 100000}),
            patch('services.webull_service.get_webull_order_detail',
                  Mock(return_value={'order_id': 'WB1', 'status': 'NEW', 'filled_qty': '0'})),
        ]
        for p in self.extra_patchers:
            p.start()
        self.webull_submit.side_effect = None
        self.webull_submit.return_value = {'success': True, 'order_id': 'WB1', 'status': 'NEW'}

    def tearDown(self):
        for p in reversed(self.extra_patchers):
            p.stop()
        super().tearDown()

    # -- helpers -----------------------------------------------------------
    def conditional(self, price=88, **extra):
        data = dict(strategy_type='LIMIT', symbol='ANT', side='BUY', broker='webull',
                    instrument_type='EQUITY', account_id='ACC1', trading_session='CORE',
                    total_quantity=5, test_mode=False,
                    legs=[dict(side='BUY', order_type='LIMIT', price=price)])
        data.update(extra)
        return conditional.create_conditional(1, data)

    def replace(self, old, price, **extra):
        """Mirror the route: cancel the old parent, then create the edited one."""
        res = cancel_any_order(f'ladder_{old.id}', user_id=1, symbol='ANT',
                               test_mode=False, broker='webull', account_id='ACC1')
        assert res['success'], res
        return self.conditional(price=price, **extra)

    def spec(self, parent):
        return json.loads(parent.conditional_spec)

    def make_native(self, **kw):
        args = dict(user_id=1, account_id='ACC1', provider_order_id='PROV1',
                    client_order_id='native-client-1', symbol='ANT', instrument_type='EQUITY',
                    side='BUY', order_type='LIMIT', quantity=5, filled_quantity=0,
                    price=88, status='CANCELLED')
        args.update(kw)
        row = WebullOrder(**args)
        db.session.add(row)
        db.session.commit()
        return row

    # -- tests -------------------------------------------------------------
    def test_replace_cancels_old_and_creates_new_at_new_limit(self):
        old = self.conditional(price=88)
        new = self.replace(old, price=95)
        db.session.refresh(old)
        self.assertEqual(old.status, 'CANCELLED')
        self.assertEqual(new.status, 'ACTIVE')
        self.assertEqual(self.spec(new)['legs'][0]['price'], 95)
        self.assertNotEqual(new.id, old.id)

    def test_replace_preserves_guardian_link(self):
        native = self.make_native()
        old = self.conditional(price=88, guardian_order_ref=str(native.id))
        self.assertEqual(self.spec(old)['guardian']['webull_order_id'], native.id)
        new = self.replace(old, price=100, guardian_order_ref=str(native.id))
        spec = self.spec(new)
        self.assertEqual(spec['legs'][0]['price'], 100)
        self.assertEqual(spec['guardian']['webull_order_id'], native.id)

    def test_replace_with_wrong_symbol_is_refused_and_old_survives(self):
        old = self.conditional(price=88)
        res = cancel_any_order(f'ladder_{old.id}', user_id=1, symbol='MSFT',
                               test_mode=False, broker='webull', account_id='ACC1')
        self.assertFalse(res['success'])
        db.session.refresh(old)
        self.assertEqual(old.status, 'ACTIVE')

    def test_terminal_parent_cannot_be_replaced(self):
        old = self.conditional(price=88)
        old.status = 'FAILED'
        db.session.commit()
        res = cancel_any_order(f'ladder_{old.id}', user_id=1, symbol='ANT',
                               test_mode=False, broker='webull', account_id='ACC1')
        self.assertFalse(res['success'])
        db.session.refresh(old)
        self.assertEqual(old.status, 'FAILED')

    def test_conditional_route_wires_replacement(self):
        """The conditional create route must honor replacing_order_id like the
        ladder route does: cancel first, skip the capacity check when a
        replacement was cancelled, and report the replaced id."""
        import pathlib
        source = pathlib.Path('routes/portfolio.py').read_text()
        start = source.index('def api_create_synthetic_conditional')
        body = source[start:start + 1600]
        self.assertIn('_cancel_replaced_synthetic_order(data, current_user.id, test_mode)', body)
        self.assertIn('if not replaced_order_id:', body)
        self.assertIn('replaced_order_id=replaced_order_id', body)


if __name__ == '__main__':
    unittest.main()
