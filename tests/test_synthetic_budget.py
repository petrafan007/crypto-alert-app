"""Buy strategies sized by an order value: either side spends at most the budget.

Uses the isolated paper harness of the lifecycle tests; no broker is contacted.
"""
import unittest
from core.extensions import db
from trading_models import LadderOrder
from services import synthetic_execution_service as ex
from services import pending_order_serializer as serializer
from services.synthetic_recovery_service import recover
from tests import test_synthetic_order_lifecycle as base


class SyntheticBudgetTests(unittest.TestCase):
    setUp, tearDown, create, tick = (base.SyntheticLifecycleTests.setUp, base.SyntheticLifecycleTests.tearDown,
                                     base.SyntheticLifecycleTests.create, base.SyntheticLifecycleTests.tick)

    def bracket(self, **extra):
        # Reference price 100: breakout steps 102/104/106 (33.33/33.33/33.34%), dip steps 97/95/92 (30/30/40%).
        args = dict(side='BUY', total_quantity=None, quote_budget=1000, upside_mode='LADDER', downside_mode='LADDER',
                    downside_rungs=[dict(offset_pct=offset, pct_of_total=pct) for offset, pct in ((-3, 30), (-5, 30), (-8, 40))])
        args.update(extra)
        return self.create(**args)

    def spent(self, parent):
        return sum(r.filled_quantity * r.filled_price for r in ex.executions(parent, 'LADDER'))

    def test_each_step_buys_its_share_of_the_budget_at_its_own_price(self):
        parent = self.bracket()
        self.assertEqual(parent.quote_budget, 1000)
        for kind in ('TAKE_PROFIT', 'STOP_LOSS'):
            steps = [r for r in parent.rungs if r.rung_type == kind]
            self.assertAlmostEqual(sum(r.percentage_of_total for r in steps), 100)
            for rung in steps:
                share = 1000 * rung.percentage_of_total / 100
                self.assertLessEqual(rung.quantity * rung.target_price, share + 1e-9)
                self.assertGreater(rung.quantity * rung.target_price, share - 0.00001 * rung.target_price)
        breakout = sum(r.quantity for r in parent.rungs if r.rung_type == 'TAKE_PROFIT')
        dip = sum(r.quantity for r in parent.rungs if r.rung_type == 'STOP_LOSS')
        self.assertLess(breakout, 10)
        self.assertGreater(dip, 10)
        self.assertAlmostEqual(parent.total_quantity, dip, places=5, msg='total shows the most either side can buy')

    def test_the_hold_is_the_budget_not_the_breakout_cost(self):
        parent = self.bracket()
        self.assertAlmostEqual(parent.to_dict()['budget_remaining'], 1000)
        self.assertAlmostEqual(serializer.serialize_ladder(parent)['quantity_usdt'], 1000)
        self.assertAlmostEqual(ex.get_synthetic_locked_funds(1, 'BTCUSD', 'BUY', broker='binance', test_mode=True), 1000)

    def test_both_sides_draw_on_one_budget_and_complete_when_it_is_used(self):
        parent = self.bracket()
        self.tick(parent, 102)
        self.assertAlmostEqual(parent.to_dict()['budget_used_pct'], 33.33)
        self.assertAlmostEqual(ex.get_synthetic_locked_funds(1, 'BTCUSD', 'BUY', broker='binance', test_mode=True), 666.7, places=6)
        for price in (97, 95):
            self.tick(parent, price)
            self.assertIn(parent.status, {'ACTIVE', 'PARTIALLY_FILLED'})
        self.tick(parent, 92)
        last = ex.executions(parent, 'LADDER')[-1]
        dip_last = next(r for r in parent.rungs if r.rung_type == 'STOP_LOSS' and r.target_price == 92)
        self.assertLess(last.quantity, dip_last.quantity, 'the final step is capped to the unused budget')
        self.assertEqual(parent.status, 'COMPLETED')
        self.assertAlmostEqual(parent.to_dict()['budget_used_pct'], 100)
        self.assertLessEqual(self.spent(parent), 1000 + 1e-6)
        self.assertGreater(self.spent(parent), 999.9)

    def test_single_breakout_buys_the_whole_budget_at_the_trigger(self):
        parent = self.bracket(upside_mode='SINGLE', upside_target_price=110, downside_mode='NONE')
        self.tick(parent, 111)
        self.assertEqual(parent.status, 'COMPLETED')
        self.assertLessEqual(self.spent(parent), 1000 + 1e-6)
        self.assertGreater(self.spent(parent), 999.99)

    def test_a_budget_applies_only_to_buys(self):
        with self.assertRaisesRegex(ValueError, 'only to buy'):
            self.create(side='SELL', quote_budget=1000)

    def test_recovery_keeps_only_the_unused_budget(self):
        parent = self.bracket()
        self.tick(parent, 102)
        parent.status = 'FAILED'
        db.session.commit()
        result = recover(1, 'LADDER', parent.id, {'action': 'REPLACE'})
        replacement = db.session.get(LadderOrder, result['replacement_id'])
        self.assertAlmostEqual(replacement.quote_budget, 666.7, places=6)
        self.assertAlmostEqual(replacement.to_dict()['budget_remaining'], 666.7, places=6)
        for rung in replacement.rungs:
            self.assertLessEqual(rung.quantity * rung.target_price, 666.7 * rung.percentage_of_total / 100 + 1e-9)


if __name__ == '__main__':
    unittest.main()
