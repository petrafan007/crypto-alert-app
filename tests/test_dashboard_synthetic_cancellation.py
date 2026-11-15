"""The dashboard broker endpoint must intercept local synthetic IDs before broker I/O."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from core.extensions import db
from credentials import UserSetting
from trading_models import SyntheticExecution
from tests import test_synthetic_order_lifecycle as base
from services import synthetic_execution_service as ex

class DashboardCancellationTests(unittest.TestCase):
    setUp, tearDown, create = base.SyntheticLifecycleTests.setUp, base.SyntheticLifecycleTests.tearDown, base.SyntheticLifecycleTests.create

    def parent(self):
        settings=db.session.get(UserSetting, 1)
        settings.webull_test_mode_enabled=False
        parent=self.create(broker='webull', instrument_type='EQUITY', symbol='NVDA', side='BUY', total_quantity=1,
            account_id='ACC1', trading_session='ALL', test_mode=False, upside_mode='SINGLE', upside_target_price=110)
        db.session.commit()
        return parent

    def cancel(self, parent, user=1, code='123456', **extra):
        from routes import system
        data=dict(order_id=f'ladder_{parent.id}', account_id='ACC1', symbol='NVDA', two_factor_code=code)
        data.update(extra)
        with self.app.test_request_context(method='POST', json=data), patch.object(system, 'current_user', SimpleNamespace(id=user)):
            return system.api_webull_cancel_order.__wrapped__()

    def test_untriggered_strategy_cancels_locally_without_webull_request(self):
        parent=self.parent()
        with patch('routes.system._cancellation_2fa_error', return_value=None), patch('routes.system.cancel_webull_order') as native, patch('services.webull_service.cancel_webull_order') as child:
            response=self.cancel(parent)
        self.assertEqual(response.get_json()['status'],'CANCELLED')
        native.assert_not_called(); child.assert_not_called()
        self.assertEqual(parent.status,'CANCELLED')

    def test_live_code_required_before_local_cancellation(self):
        parent=self.parent()
        response,status=self.cancel(parent,code='')
        self.assertEqual(status,403)
        self.assertTrue(response.get_json()['requires_2fa'])
        self.assertEqual(parent.status,'ACTIVE')

    def test_account_mismatch_and_other_user_do_not_cancel(self):
        parent=self.parent()
        response,status=self.cancel(parent, account_id='OTHER')
        self.assertEqual(status,400)
        response,status=self.cancel(parent,user=999)
        self.assertEqual(status,404)
        self.assertEqual(parent.status,'ACTIVE')

    def test_pending_child_is_not_reported_as_final_cancellation(self):
        parent=self.parent()
        row=SyntheticExecution(user_id=1,parent_kind='LADDER',parent_id=parent.id,leg='TAKE_PROFIT',
            quantity=1,filled_quantity=0,status='UNKNOWN',client_order_id='syn-pending')
        db.session.add(row); db.session.commit()
        with patch('routes.system._cancellation_2fa_error',return_value=None), patch.object(ex,'reconcile_executions',return_value=[row]), patch('routes.system.cancel_webull_order') as native:
            response=self.cancel(parent)
        self.assertEqual(response.get_json()['status'],'CANCEL_PENDING')
        native.assert_not_called()
