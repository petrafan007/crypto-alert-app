"""Server-side sync safety (audit F29-F34).

Provider replies that are incomplete never delete data; paging is followed or
reported; stored orders only move forward; caches are invalidated in every
process; competing refreshes of one user do not interleave; and display reads
do not switch off a coin's automation. No provider is contacted.
"""
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.extensions import db
from credentials import UserSetting
from models import BinanceOrder, Coin, WatchlistCoin, WebullAccountSnapshot, WebullHolding, WebullOrder
from services import shared_state
from trading_models import PortfolioValueHistory
from services import webull_service as ws
from services.webull_import_service import import_webull_orders, import_webull_portfolio_snapshot
from services.order_history_sync_service import import_binance_orders
from tests import test_synthetic_order_lifecycle as base


class SyncSafetyBase(unittest.TestCase):
    def setUp(self):
        base.SyntheticLifecycleTests.setUp(self)
        for model in (Coin, WatchlistCoin, WebullAccountSnapshot, WebullHolding, WebullOrder, BinanceOrder, PortfolioValueHistory):
            model.__table__.create(db.engine, checkfirst=True)
        self.state = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CSD_SHARED_STATE_DIR': self.state.name})
        self.env.start()
        ws.clear_webull_order_cache()

    def tearDown(self):
        self.env.stop()
        self.state.cleanup()
        base.SyntheticLifecycleTests.tearDown(self)

    def holdings(self, account_id=None):
        query = WebullHolding.query.filter_by(user_id=1)
        if account_id:
            query = query.filter_by(account_id=account_id)
        return sorted((holding.account_id, holding.symbol, holding.quantity) for holding in query.all())


class WebullReplyTests(SyncSafetyBase):
    def reply(self, payload):
        response = Mock(status_code=200)
        response.json.return_value = payload
        return response

    def test_positions_reply_in_an_unexpected_shape_is_not_an_empty_account(self):
        for payload in ({'data': None}, {'data': {}}, {'data': {'unexpected': 1}}, {'data': 'x'}):
            with patch.object(ws, '_get_webull_account_resource', return_value=payload):
                with self.assertRaises(ws.WebullIncompleteResponse, msg=payload):
                    ws.get_webull_account_positions('k', 's', 'production', 't', 'A')
        for payload, expected in (({'data': []}, []), ({'data': {'positions': []}}, []), ({'data': {'items': [{'symbol': 'X'}]}}, [{'symbol': 'X'}])):
            with patch.object(ws, '_get_webull_account_resource', return_value=payload):
                self.assertEqual(ws.get_webull_account_positions('k', 's', 'production', 't', 'A'), expected)

    def test_preview_marks_one_incomplete_account_and_keeps_the_others(self):
        accounts = [{'account_id': 'A', 'account_type': 'STOCK'}, {'account_id': 'B', 'account_type': 'STOCK'}]

        def positions(*args):
            if args[4] == 'B':
                raise ws.WebullIncompleteResponse('odd reply')
            return [{'symbol': 'AAPL', 'quantity': '1'}]
        with patch.object(ws, 'get_webull_accounts', return_value=accounts), \
                patch.object(ws, 'get_webull_account_balance', return_value={'total_cash_balance': '5'}), \
                patch.object(ws, 'get_webull_account_positions', side_effect=positions), patch.object(ws.time, 'sleep'):
            preview = ws.get_webull_portfolio_preview('k', 's', access_token='t')
        self.assertEqual([(a['account_id'], a['positions_complete'], a['balance_complete']) for a in preview], [('A', True, True), ('B', False, True)])

    def test_open_orders_follow_every_page(self):
        page_one = [{'order_id': str(i), 'client_order_id': f'c{i}', 'symbol': 'AAPL'} for i in range(100)]
        page_two = [{'order_id': '100', 'client_order_id': 'c100', 'symbol': 'AAPL'}]
        with patch.object(ws, '_rate_limited_order_request', side_effect=[self.reply({'data': page_one}), self.reply({'data': {'orders': page_two}})]) as request:
            orders = ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A')
        self.assertEqual(len(orders), 101)
        self.assertNotIn('last_client_order_id', request.call_args_list[0].kwargs['query_params'])
        self.assertEqual(request.call_args_list[1].kwargs['query_params']['last_client_order_id'], 'c99')

    def test_open_orders_that_cannot_be_completed_raise_instead_of_returning_part(self):
        full = [{'order_id': str(i), 'client_order_id': f'c{i}', 'symbol': 'AAPL'} for i in range(100)]
        cases = [
            [self.reply({'data': [dict(order, client_order_id=None) for order in full]})],   # full page, no cursor
            [self.reply({'data': full}), self.reply({'data': full})],                         # repeated cursor
            [self.reply({'data': {'something': []}})],                                        # unexpected shape
        ]
        for responses in cases:
            ws.clear_webull_order_cache()
            with patch.object(ws, '_rate_limited_order_request', side_effect=responses):
                with self.assertRaises(ws.WebullIncompleteResponse):
                    ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A')
        ws.clear_webull_order_cache()
        with patch.object(ws, '_rate_limited_order_request', return_value=self.reply({'data': {'orders': []}})):
            self.assertEqual(ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A'), [], 'a genuine empty list')


class SnapshotImportTests(SyncSafetyBase):
    def account(self, account_id, positions, *, cash='100', complete=True, balance_complete=True):
        return {'account_id': account_id, 'account_type': 'STOCK', 'balance': {'total_cash_balance': cash, 'total_net_liquidation_value': '500'},
                'positions': positions, 'positions_complete': complete, 'balance_complete': balance_complete}

    def seed(self):
        import_webull_portfolio_snapshot(1, [self.account('A', [{'symbol': 'AAPL', 'quantity': '2'}]), self.account('B', [{'symbol': 'MSFT', 'quantity': '3'}])],
                                         expected_account_ids=['A', 'B'])

    def test_incomplete_positions_keep_holdings_and_complete_ones_remove_sold_holdings(self):
        self.seed()
        import_webull_portfolio_snapshot(1, [self.account('A', [], complete=False), self.account('B', [])], expected_account_ids=['A', 'B'])
        self.assertEqual(self.holdings(), [('A', 'AAPL', 2.0), ('A', 'USD', 100.0), ('B', 'USD', 100.0)])

    def test_missing_balance_keeps_cash_and_totals(self):
        self.seed()
        import_webull_portfolio_snapshot(1, [{'account_id': 'A', 'balance': None, 'positions': [{'symbol': 'AAPL', 'quantity': '2'}], 'balance_complete': False}],
                                         expected_account_ids=['A', 'B'])
        snapshot = WebullAccountSnapshot.query.filter_by(user_id=1, account_id='A').one()
        self.assertEqual((snapshot.total_cash_balance, snapshot.total_net_liquidation_value), (100.0, 500.0))
        self.assertIn(('A', 'USD', 100.0), self.holdings())

    def test_only_accounts_the_user_removed_are_deleted(self):
        self.seed()
        import_webull_portfolio_snapshot(1, [self.account('A', [{'symbol': 'AAPL', 'quantity': '2'}])], expected_account_ids=['A', 'B'])
        self.assertEqual({row[0] for row in self.holdings()}, {'A', 'B'}, 'B did not answer this time and is kept')
        import_webull_portfolio_snapshot(1, [], expected_account_ids=None)
        self.assertEqual({row[0] for row in self.holdings()}, {'A', 'B'}, 'an empty reply without expectations deletes nothing')
        import_webull_portfolio_snapshot(1, [self.account('A', [{'symbol': 'AAPL', 'quantity': '2'}])], expected_account_ids=['A'])
        self.assertEqual({row[0] for row in self.holdings()}, {'A'}, 'B was disabled by the user')

    def test_an_older_observation_does_not_overwrite_a_newer_one(self):
        now = datetime.utcnow()
        import_webull_portfolio_snapshot(1, [self.account('A', [{'symbol': 'AAPL', 'quantity': '5'}])], expected_account_ids=['A'], observed_at=now)
        result = import_webull_portfolio_snapshot(1, [self.account('A', [{'symbol': 'AAPL', 'quantity': '1'}])], expected_account_ids=['A'],
                                                  observed_at=now - timedelta(seconds=30))
        self.assertEqual(result['skipped_stale_accounts'], 1)
        self.assertIn(('A', 'AAPL', 5.0), self.holdings())
        import_webull_portfolio_snapshot(1, [self.account('A', [{'symbol': 'AAPL', 'quantity': '7'}])], expected_account_ids=['A'],
                                         observed_at=now + timedelta(seconds=30))
        self.assertIn(('A', 'AAPL', 7.0), self.holdings())


class ForwardOnlyOrderTests(SyncSafetyBase):
    def test_binance_stale_open_copy_cannot_reopen_a_fill_or_shrink_it(self):
        filled = {'orderId': 9, 'symbol': 'BTCUSD', 'side': 'BUY', 'status': 'FILLED', 'origQty': '2', 'executedQty': '2',
                  'cummulativeQuoteQty': '200', 'price': '100', 'updateTime': 2_000_000_000_000}
        stale = dict(filled, status='PARTIALLY_FILLED', executedQty='1', cummulativeQuoteQty='99', updateTime=1_999_999_000_000)
        import_binance_orders(1, [filled, stale])
        record = BinanceOrder.query.filter_by(user_id=1, provider_order_id='9').one()
        self.assertEqual((record.status, record.filled_quantity, record.filled_price), ('FILLED', 2.0, 100.0))
        import_binance_orders(1, [dict(filled, status='NEW', executedQty='0')])
        self.assertEqual((record.status, record.filled_quantity), ('FILLED', 2.0))

    def test_binance_newer_states_still_apply(self):
        new = {'orderId': 10, 'symbol': 'BTCUSD', 'side': 'BUY', 'status': 'NEW', 'origQty': '2', 'executedQty': '0', 'price': '100', 'updateTime': 1_900_000_000_000}
        import_binance_orders(1, [new])
        import_binance_orders(1, [dict(new, status='PARTIALLY_FILLED', executedQty='1', cummulativeQuoteQty='100', updateTime=1_900_000_100_000)])
        import_binance_orders(1, [dict(new, status='CANCELED', executedQty='1', cummulativeQuoteQty='100', updateTime=1_900_000_200_000)])
        record = BinanceOrder.query.filter_by(user_id=1, provider_order_id='10').one()
        self.assertEqual((record.status, record.filled_quantity), ('CANCELED', 1.0))

    def test_webull_history_and_open_lists_in_either_order(self):
        history = {'order_id': 'w1', '_webull_account_id': 'A', 'symbol': 'AAPL', 'side': 'BUY', 'status': 'CANCELLED',
                   'total_quantity': '5', 'filled_quantity': '2', 'update_time': '2026-11-15T15:00:00Z'}
        open_copy = dict(history, status='PARTIALLY_FILLED', filled_quantity='1', update_time='2026-11-15T14:00:00Z')
        import_webull_orders(1, [history, open_copy])
        record = WebullOrder.query.filter_by(user_id=1, provider_order_id='w1').one()
        self.assertEqual((record.status, record.filled_quantity, record.updated_at), ('CANCELLED', 2.0, datetime(2026, 11, 15, 15)))
        import_webull_orders(1, [dict(history, status=None)])
        self.assertEqual(record.status, 'CANCELLED', 'a copy without a status does not erase it')


class SharedCacheTests(SyncSafetyBase):
    def reply(self, orders):
        response = Mock(status_code=200)
        response.json.return_value = {'data': orders}
        return response

    def test_invalidation_in_another_process_discards_this_process_cache(self):
        with patch.object(ws, '_rate_limited_order_request', side_effect=[self.reply([{'order_id': '1', 'symbol': 'AAPL'}]), self.reply([])]) as request:
            self.assertEqual(len(ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A')), 1)
            self.assertEqual(len(ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A')), 1, 'cached')
            shared_state.bump_revision(ws.WEBULL_ORDER_CACHE_REVISION)   # what clear_webull_order_cache() does elsewhere
            self.assertEqual(ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A'), [])
        self.assertEqual(request.call_count, 2)

    def test_a_read_in_flight_during_invalidation_is_not_cached(self):
        def slow_reply(*_args, **_kwargs):
            ws.clear_webull_order_cache()   # a cancellation lands while this read is in flight
            return self.reply([{'order_id': 'old', 'symbol': 'AAPL'}])
        with patch.object(ws, '_rate_limited_order_request', side_effect=lambda *a, **k: slow_reply()):
            ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A')
        self.assertEqual(ws._WEBULL_OPEN_ORDERS_CACHE, {})

    def test_binance_shared_orders_keep_the_newest_read_and_forget_after_a_change(self):
        from services.portfolio_service import binance_orders_revision, cache_binance_open_orders, cached_binance_open_orders, invalidate_binance_open_orders
        now = time.time()
        revision = binance_orders_revision()
        self.assertTrue(cache_binance_open_orders(1, [{'order_id': 'new'}], observed_at=now, revision_at_start=revision))
        self.assertFalse(cache_binance_open_orders(1, [{'order_id': 'old'}], observed_at=now - 5, revision_at_start=revision))
        self.assertEqual(cached_binance_open_orders(1), [{'order_id': 'new'}])
        invalidate_binance_open_orders(1)
        self.assertEqual(cached_binance_open_orders(1), [])
        self.assertFalse(cache_binance_open_orders(1, [{'order_id': 'pre-cancel'}], observed_at=now + 1, revision_at_start=revision),
                         'a read started before the cancellation is not kept')
        self.assertEqual(cached_binance_open_orders(1), [])


class SyncLockTests(SyncSafetyBase):
    def test_a_second_sync_of_the_same_user_does_not_interleave(self):
        from services.sync_locks import user_sync_lock
        with user_sync_lock('binance-account', 1) as first:
            self.assertTrue(first)
            results = []
            thread = threading.Thread(target=lambda: results.append(user_sync_lock('binance-account', 1).__enter__()))
            thread.start(); thread.join()
            self.assertEqual(results, [False])
            with user_sync_lock('binance-account', 2) as other_user:
                self.assertTrue(other_user)
        with user_sync_lock('binance-account', 1) as again:
            self.assertTrue(again)

    def test_binance_sync_applies_balances_read_after_trade_history(self):
        from services import binance_service
        client = Mock()
        client.get_account.side_effect = [{'balances': [{'asset': 'BTC', 'free': '1', 'locked': '0'}]},
                                          {'balances': [{'asset': 'BTC', 'free': '0.4', 'locked': '0'}]}]
        client.get_my_trades.return_value = []
        with patch.object(binance_service, 'update_coins_from_binance_balances') as apply, patch.object(binance_service.time, 'sleep'), \
                patch.object(binance_service, 'sync_real_order_statuses_for_user'), \
                patch('services.portfolio_service.compute_portfolio_total_value', return_value=0):
            binance_service.sync_binance_account(1, 'tester', client, None)
        self.assertEqual(apply.call_args.args[1], [{'asset': 'BTC', 'free': '0.4', 'locked': '0'}])


class DisplayReadSideEffectTests(SyncSafetyBase):
    def test_pending_order_read_no_longer_switches_off_automation_or_hides_coins(self):
        from routes import portfolio
        db.session.get(UserSetting, 1).webull_test_mode_enabled = False
        db.session.add(Coin(user_id=1, symbol='ETH', amount=0, hidden=False, auto_buy_enabled=True, auto_sell_enabled=True, alert_enabled=True))
        db.session.commit()
        creds = SimpleNamespace(api_key='k', api_secret='s', webull_token_status=None, webull_token_environment=None, webull_access_token=None)
        stub = SimpleNamespace(query=SimpleNamespace(filter_by=lambda **_: SimpleNamespace(first=lambda: creds)))
        with self.app.test_request_context(), patch.object(portfolio, 'current_user', SimpleNamespace(id=1, username='tester')), \
                patch.object(portfolio, 'Credential', stub), patch.object(portfolio, 'decrypt_secret', side_effect=lambda value: value), \
                patch('binance.client.Client') as client:
            client.return_value.get_open_orders.return_value = [
                {'orderId': 1, 'symbol': 'SOLUSD', 'side': 'BUY', 'type': 'LIMIT', 'price': '20', 'origQty': '1', 'executedQty': '0', 'status': 'NEW'}]
            portfolio.api_pending_orders.__wrapped__()
        coin = Coin.query.filter_by(user_id=1, symbol='ETH').one()
        self.assertEqual((coin.hidden, coin.auto_buy_enabled, coin.auto_sell_enabled, coin.alert_enabled), (False, True, True, True))
        watch = WatchlistCoin.query.filter_by(user_id=1, symbol='SOL').one()
        self.assertEqual((watch.hidden, watch.current_price), (False, 20.0), 'an unfilled BUY is still placed on the watchlist')


if __name__ == '__main__':
    unittest.main()
