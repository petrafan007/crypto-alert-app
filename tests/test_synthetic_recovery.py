"""Recovery and multi-stage conditional contracts; broker I/O is mocked."""
import json
import unittest
from unittest.mock import patch
from core.extensions import db
from trading_models import LadderOrder, SyntheticRecovery, SyntheticExecution
from services import synthetic_execution_service as ex
from services import synthetic_conditional_service as conditional
from services import synthetic_recovery_service as recovery
from services import ladder_order_service as ladder
from tests import test_synthetic_order_lifecycle as lifecycle
from tests import test_synthetic_extended_hours as extended
AFTER_HOURS = extended.AFTER_HOURS


class RecoveryTests(unittest.TestCase):
    setUp, tearDown, create, tick = lifecycle.SyntheticLifecycleTests.setUp, lifecycle.SyntheticLifecycleTests.tearDown, lifecycle.SyntheticLifecycleTests.create, lifecycle.SyntheticLifecycleTests.tick
    # Inherit the isolated database fixture, not its test methods.
    def failed(self, filled=0):
        parent = self.create(total_quantity=10, upside_mode='SINGLE', upside_target_price=110)
        parent.status = 'FAILED'
        db.session.add(SyntheticExecution(user_id=1, parent_kind='LADDER', parent_id=parent.id,
            leg='TAKE_PROFIT', client_order_id=f'failure{parent.id}', quantity=10, filled_quantity=filled,
            status='CANCELLED', error_message='Limit expired without enough liquidity.'))
        db.session.commit()
        return parent

    def test_partial_failure_label_recovery_and_idempotency(self):
        parent = self.failed(4)
        self.assertEqual(parent.to_dict()['status_label'], 'Partially filled — remainder cancelled')
        with patch.object(ex, 'check_synthetic_order_capacity'):
            result = recovery.recover(1, 'LADDER', parent.id, {'action': 'REGULAR'})
            again = recovery.recover(1, 'LADDER', parent.id, {'action': 'REPLACE'})
        self.assertEqual(result['replacement_id'], again['replacement_id'])
        replacement = db.session.get(LadderOrder, result['replacement_id'])
        self.assertEqual(replacement.total_quantity, 6)
        self.assertEqual(replacement.trading_session, 'CORE')
        self.assertEqual(parent.status, 'FAILED')
        self.assertEqual(parent.to_dict()['filled_quantity'], 4)
        self.assertFalse(parent.to_dict()['recovery_available'])
        self.client.create_order.assert_not_called()

    def test_unresolved_submission_blocks_recovery(self):
        parent = self.failed()
        row = ex.executions(parent, 'LADDER')[0]
        row.status = 'UNKNOWN'; db.session.commit()
        with patch.object(ex, 'reconcile_executions', return_value=[row]), self.assertRaisesRegex(ValueError, 'confirmation'):
            recovery.recover(1, 'LADDER', parent.id, {'action': 'REGULAR'})
        self.assertEqual(LadderOrder.query.count(), 1)

    def test_other_user_cannot_recover(self):
        parent = self.failed()
        with self.assertRaisesRegex(ValueError, 'not found'):
            recovery.recover(99, 'LADDER', parent.id, {'action': 'KEEP_CANCELLED'})

    def test_keep_cancelled_is_durable_and_does_not_trade(self):
        parent = self.failed()
        recovery.recover(1, 'LADDER', parent.id, {'action': 'KEEP_CANCELLED'})
        self.assertEqual(SyntheticRecovery.query.one().action, 'KEEP_CANCELLED')
        self.assertEqual(LadderOrder.query.count(), 1)
        self.client.create_order.assert_not_called()

    def test_invalid_replacement_rolls_back_without_consuming_recovery(self):
        parent = self.failed()
        with patch.object(ex, 'check_synthetic_order_capacity'), self.assertRaises(ValueError):
            recovery.recover(1, 'LADDER', parent.id, {'action': 'REPLACE', 'strategy_type': 'OCO', 'legs': []})
        db.session.rollback()
        self.assertEqual(SyntheticRecovery.query.count(), 0)
        self.assertEqual(LadderOrder.query.count(), 1)

    def test_live_recovery_requires_2fa_before_any_replacement(self):
        from types import SimpleNamespace
        from routes import portfolio
        parent = self.failed()
        parent.test_mode = False
        db.session.commit()
        with self.app.test_request_context(method='POST', json={'action':'REGULAR'}), patch.object(portfolio, 'current_user', SimpleNamespace(id=1)):
            response, status = portfolio.api_recover_synthetic.__wrapped__('LADDER', parent.id)
        self.assertEqual(status, 403)
        self.assertTrue(response.get_json()['requires_2fa'])
        self.assertEqual(LadderOrder.query.count(), 1)

    def test_replace_can_change_to_a_trailing_strategy_for_only_the_remainder(self):
        parent = self.failed(4)
        with patch.object(ex, 'check_synthetic_order_capacity'):
            result = recovery.recover(1, 'LADDER', parent.id, {'action':'REPLACE', 'strategy_type':'TRAILING', 'trail_value':2})
        from trading_models import TrailingOrder
        replacement = db.session.get(TrailingOrder, result['replacement_id'])
        self.assertEqual(result['replacement_kind'], 'TRAILING')
        self.assertEqual(replacement.quantity, 6)
        self.assertEqual(parent.to_dict()['filled_quantity'], 4)

    def test_recovery_failure_does_not_leave_an_orphan_replacement(self):
        parent = self.failed(4)
        with patch.object(ex, 'check_synthetic_order_capacity'), self.assertRaisesRegex(ValueError, 'allocate exactly'):
            recovery.recover(1, 'LADDER', parent.id, {'action':'REPLACE', 'strategy_type':'LADDER', 'rungs':[{'target_price':110,'pct_of_total':50}]})
        db.session.rollback()
        self.assertEqual(SyntheticRecovery.query.count(),0)
        self.assertEqual(LadderOrder.query.count(),1)


class ConditionalTests(unittest.TestCase):
    setUp, tearDown, tick = lifecycle.SyntheticLifecycleTests.setUp, lifecycle.SyntheticLifecycleTests.tearDown, lifecycle.SyntheticLifecycleTests.tick

    def live_patches(self, now, detail):
        return extended.ExtendedHoursExecutionTests.live_patches(self, now, detail) + [
            patch('services.webull_service.get_webull_account_positions', return_value=[{'symbol': 'NVDA', 'available_quantity': 100}])]

    def conditional(self, kind='OTOCO', **changes):
        legs = [dict(side='BUY', order_type='LIMIT', price=95),
                dict(side='SELL', order_type='LIMIT', price=110),
                dict(side='SELL', order_type='STOP_LOSS_LIMIT', stop_price=90, price=89)]
        if kind == 'OCO': legs = legs[1:]
        if kind == 'OTO': legs = legs[:2]
        data = dict(symbol='NVDA', side=legs[0]['side'], account_id='ACC1', test_mode=False,
                    total_quantity=10, strategy_type=kind, legs=legs, trading_session='ALL')
        data.update(changes)
        return conditional.create_conditional(1, data)

    def test_otoco_does_not_activate_exits_until_entry_confirmation(self):
        parent = self.conditional()
        patches = self.live_patches(AFTER_HOURS, {'status': 'NEW'})
        for p in patches: p.start()
        try:
            self.tick(parent, 94)
            self.assertEqual(self.webull_submit.call_args.kwargs['limit_price'], 95)
            self.tick(parent, 120)
            self.assertEqual(self.webull_submit.call_count, 1)
            row = ex.executions(parent, 'LADDER')[0]
            row.status='CANCELLED'; row.filled_quantity=4; db.session.commit()
            conditional.sync(parent, [row]); db.session.commit()
            self.assertEqual((parent.side, parent.total_quantity, parent.conditional_phase), ('SELL',4,'EXIT'))
            self.tick(parent, 120)
            self.assertEqual(self.webull_submit.call_count, 2)
            self.assertEqual(self.webull_submit.call_args.kwargs['quantity'], 4)
            self.assertEqual(self.webull_submit.call_args.kwargs['limit_price'], 110)
            self.tick(parent, 80)
            self.assertEqual(self.webull_submit.call_count, 2)
        finally:
            for p in reversed(patches): p.stop()

    def test_oco_preserves_stop_limit_and_never_sends_opposite_branch(self):
        parent = self.conditional('OCO')
        patches=self.live_patches(AFTER_HOURS, {'status':'NEW'})
        for p in patches: p.start()
        try:
            self.tick(parent, 88)
            self.assertEqual(self.webull_submit.call_args.kwargs['limit_price'],89)
            self.tick(parent, 115)
            self.assertEqual(self.webull_submit.call_count,1)
        finally:
            for p in reversed(patches): p.stop()

    def test_oto_entry_rejection_does_not_arm_exit(self):
        parent=self.conditional('OTO')
        row=SyntheticExecution(user_id=1,parent_kind='LADDER',parent_id=parent.id,leg='ENTRY',
            client_order_id='rejected-entry',quantity=10,filled_quantity=0,status='FAILED',error_message='Rejected')
        db.session.add(row); db.session.commit()
        conditional.sync(parent,[row])
        self.assertEqual((parent.status,parent.conditional_phase),('FAILED','ENTRY'))
        self.assertEqual(parent.to_dict()['status_label'],'Failed — no shares filled')

    def test_synthetic_conditional_rejects_fractional_extended_quantity(self):
        with self.assertRaisesRegex(ValueError,'whole shares'): self.conditional(total_quantity=1.5)

    def test_price_gap_does_not_widen_plain_stop_cap(self):
        parent=self.conditional('OCO', legs=[dict(side='SELL', order_type='LIMIT', price=110), dict(side='SELL', order_type='STOP_LOSS', stop_price=90)])
        patches=self.live_patches(AFTER_HOURS, {'status':'NEW'})
        for p in patches: p.start()
        try:
            self.tick(parent, 80)
            self.assertEqual(self.webull_submit.call_args.kwargs['limit_price'], 89.1)
        finally:
            for p in reversed(patches): p.stop()
