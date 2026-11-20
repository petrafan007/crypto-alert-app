"""Definitive broker not-found resolves phantom UNKNOWN executions.

Execution 66 of ladder_33 (Nov 20 2026) was a market-buy submission whose
outcome was never determined; Webull had no such order, but reconcile kept
treating the failed lookup as "keep waiting", so the parent sat in
CANCEL_PENDING forever. Webull's definitive not-found answer (HTTP 417,
OPENAPI_PARAM_ERR, "Order not present." — verified live) now closes the
UNKNOWN execution as cancelled and the parent finalizes on the same pass.
Ambiguous failures still wait, and executions the broker acknowledged
(SUBMITTED and beyond) are never swept away by a not-found answer.
All venue I/O is mocked.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.extensions import db
from trading_models import LadderOrder, SyntheticExecution
from services import synthetic_execution_service as ex
from services import ladder_order_service as ladder
from services.webull_service import WebullConnectionError
from tests import test_synthetic_order_lifecycle as base

NOT_FOUND = WebullConnectionError(
    'Webull order detail request failed (HTTP 417): Parameter error, Order not present. (OPENAPI_PARAM_ERR)',
    error_code='OPENAPI_PARAM_ERR', http_status=417)
AMBIGUOUS = WebullConnectionError('Webull connection failed: read timed out')


class NotFoundReconcileTests(base.SyntheticLifecycleTests):
    def setUp(self):
        super().setUp()
        cred = SimpleNamespace(webull_app_key='key', webull_app_secret='secret',
                               webull_access_token='token')
        self.detail = Mock()
        self.extra_patchers = [
            patch.object(ex, 'webull_credentials', return_value=(cred, 'production')),
            patch('services.webull_service.get_webull_order_detail', self.detail),
            patch('services.webull_service.cancel_webull_order', return_value={'success': True}),
        ]
        for p in self.extra_patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self.extra_patchers):
            p.stop()
        super().tearDown()

    def make_parent(self, status='CANCEL_PENDING', cancel_requested=True):
        parent = LadderOrder(user_id=1, broker='webull', account_id='ACC1', symbol='ANT',
                             side='BUY', instrument_type='EQUITY', total_quantity=4,
                             strategy_type='BRACKET', trading_session='CORE',
                             test_mode=False, engine_version=2, environment='production',
                             status=status, cancel_requested=cancel_requested)
        db.session.add(parent)
        db.session.commit()
        return parent

    def add_execution(self, parent, status='UNKNOWN', order_type='MARKET'):
        row = SyntheticExecution(user_id=1, parent_kind='LADDER', parent_id=parent.id,
                                 leg='STOP_LOSS', quantity=1.3332,
                                 client_order_id='syncb78cbac11f1485e896ceb99883e7',
                                 filled_quantity=0, status=status, order_type=order_type)
        db.session.add(row)
        db.session.commit()
        return row

    def test_classifier_requires_the_definitive_signature(self):
        self.assertTrue(ex._broker_order_not_found(NOT_FOUND))
        self.assertFalse(ex._broker_order_not_found(AMBIGUOUS))
        self.assertFalse(ex._broker_order_not_found(WebullConnectionError(
            'Parameter error (OPENAPI_PARAM_ERR)', error_code='OPENAPI_PARAM_ERR', http_status=417)))
        self.assertFalse(ex._broker_order_not_found(WebullConnectionError(
            'Order not present.', http_status=500)))
        self.assertFalse(ex._broker_order_not_found(Exception('Order not present.')))

    def test_phantom_unknown_resolves_and_parent_finalizes(self):
        parent = self.make_parent()
        row = self.add_execution(parent)
        self.detail.side_effect = NOT_FOUND
        rows = ex.reconcile_executions(parent, 'LADDER')
        self.assertEqual(row.status, 'CANCELLED')
        self.assertEqual(row.error_message, ex.NOT_FOUND_EXECUTION_MESSAGE)
        ladder._sync_parent(parent, rows)
        self.assertEqual(parent.status, 'CANCELLED')

    def test_cancel_parent_finalizes_same_call(self):
        parent = self.make_parent(status='ACTIVE', cancel_requested=False)
        row = self.add_execution(parent)
        self.detail.side_effect = NOT_FOUND
        result = ex.cancel_parent(LadderOrder, 'LADDER', parent.id, 1)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(row.status, 'CANCELLED')

    def test_ambiguous_failure_keeps_waiting(self):
        parent = self.make_parent()
        row = self.add_execution(parent)
        self.detail.side_effect = AMBIGUOUS
        rows = ex.reconcile_executions(parent, 'LADDER')
        self.assertEqual(row.status, 'UNKNOWN')
        self.assertTrue(row.error_message.startswith('Awaiting broker confirmation'))
        ladder._sync_parent(parent, rows)
        self.assertEqual(parent.status, 'CANCEL_PENDING')

    def test_not_found_never_sweeps_an_acknowledged_execution(self):
        parent = self.make_parent()
        row = self.add_execution(parent, status='SUBMITTED')
        row.broker_order_id = 'WB9'
        db.session.commit()
        self.detail.side_effect = NOT_FOUND
        ex.reconcile_executions(parent, 'LADDER')
        self.assertEqual(row.status, 'SUBMITTED')


if __name__ == '__main__':
    unittest.main()
