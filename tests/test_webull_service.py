import unittest
from unittest.mock import Mock, patch

from services.webull_service import (
    WebullConnectionError,
    check_webull_access_token,
    create_webull_access_token,
    generate_webull_signature,
    get_webull_accounts,
    get_webull_market_bars,
    get_webull_option_snapshot,
    get_webull_order_history,
    get_webull_open_orders,
    get_webull_portfolio_preview,
    get_webull_stock_movers,
    place_webull_order,
    cancel_webull_order,
    normalize_webull_environment,
    parse_webull_expiry,
    test_webull_connection as check_webull_connection,
    clear_webull_order_cache,
)


class WebullServiceTests(unittest.TestCase):
    def setUp(self):
        clear_webull_order_cache()

    def test_environment_normalization_accepts_only_supported_values(self):
        self.assertEqual(normalize_webull_environment('Production'), 'production')
        self.assertEqual(normalize_webull_environment('sandbox'), 'sandbox')
        with self.assertRaises(WebullConnectionError):
            normalize_webull_environment('staging')

    def test_account_list_connection_check_returns_non_sensitive_summary(self):
        response = Mock(status_code=200)
        response.json.return_value = [
            {'account_id': '111111', 'account_type': 'STOCK'},
            {'account_id': '222222', 'account_type': 'OPTION'},
        ]
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            result = check_webull_connection('app-key', 'app-secret', 'sandbox')

        self.assertEqual(result, {
            'environment': 'sandbox',
            'account_count': 2,
            'account_types': ['OPTION', 'STOCK'],
        })

    def test_account_discovery_accepts_enveloped_webull_account_lists(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'accounts': [{'accountId': '12345678', 'accountType': 'OPTION', 'accountName': 'Options'}]}
        }
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            accounts = get_webull_accounts('app-key', 'app-secret', access_token='private-token')

        self.assertEqual(accounts, [{
            'account_id': '12345678', 'account_type': 'OPTION', 'account_name': 'Options'
        }])

    def test_account_discovery_handles_subtypes_and_defaults(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': [{'accountId': '98765432', 'accountType': 'CASH', 'accountSubType': 'ROTH'}]
        }
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            accounts = get_webull_accounts('app-key', 'app-secret', access_token='token')

        self.assertEqual(accounts, [{
            'account_id': '98765432',
            'account_type': 'CASH',
            'account_sub_type': 'ROTH',
            'account_name': 'CASH (ROTH)',
        }])

    def test_non_success_response_is_not_treated_as_connected(self):
        response = Mock(status_code=401, text='Unauthorized')
        with patch('services.webull_service.get_webull_account_list', return_value=response):
            with self.assertRaisesRegex(WebullConnectionError, 'HTTP 401'):
                check_webull_connection('app-key', 'app-secret')

    def test_create_token_normalizes_pending_response_without_exposing_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'token': 'private-token', 'status': 'PENDING', 'expires': '2026-08-27T12:00:00Z'
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = create_webull_access_token('app-key', 'app-secret', 'production')

        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(result['token'], 'private-token')
        self.assertEqual(request_mock.call_args.args[4], '/openapi/auth/token/create')

    def test_check_token_posts_the_saved_token(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'token': 'private-token', 'status': 'NORMAL', 'expires': 1787832000}
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = check_webull_access_token('app-key', 'app-secret', 'private-token', 'sandbox')

        self.assertEqual(result['status'], 'NORMAL')
        self.assertEqual(request_mock.call_args.kwargs['body'], {'token': 'private-token'})
        self.assertIsNotNone(parse_webull_expiry(result['expires']))

    def test_token_creation_retries_the_documented_path_after_sdk_path_auth_failure(self):
        rejected = Mock(status_code=401, text='Unauthorized')
        accepted = Mock(status_code=200)
        accepted.json.return_value = {
            'token': 'private-token', 'status': 'PENDING', 'expires': '2026-08-27T12:00:00Z'
        }
        with patch('services.webull_service._webull_request', side_effect=[rejected, accepted]) as request_mock:
            result = create_webull_access_token('app-key', 'app-secret')

        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(request_mock.call_args_list[1].args[4], '/auth/tokens/create')

    def test_expiry_parser_accepts_webull_epoch_milliseconds(self):
        parsed = parse_webull_expiry(1787832000000)
        self.assertEqual(parsed.year, 2026)

    def test_portfolio_preview_uses_all_discovered_accounts_without_importing(self):
        accounts = [{'account_id': '1234', 'account_type': 'STOCK', 'account_name': 'Individual'}]
        with patch('services.webull_service.get_webull_accounts', return_value=accounts), \
             patch('services.webull_service.get_webull_account_balance', return_value={'total_cash_balance': '10'}), \
             patch('services.webull_service.get_webull_account_positions', return_value=[{'symbol': 'AAPL'}]):
            preview = get_webull_portfolio_preview('app-key', 'app-secret', access_token='private-token')

        self.assertEqual(preview, [{
            'account_id': '1234', 'account_type': 'STOCK', 'account_name': 'Individual',
            'balance': {'total_cash_balance': '10'}, 'positions': [{'symbol': 'AAPL'}],
        }])

    def test_open_orders_are_read_only_and_tagged_with_the_source_account(self):
        accounts = [{'account_id': '1234', 'account_type': 'STOCK', 'account_name': 'Individual'}]
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'orders': [{'order_id': 'order-1', 'symbol': 'AAPL'}]}}
        with patch('services.webull_service.get_webull_accounts', return_value=accounts), \
             patch('services.webull_service._webull_request', return_value=response) as request_mock:
            orders = get_webull_open_orders('app-key', 'app-secret', access_token='private-token')

        self.assertEqual(orders, [{
            'order_id': 'order-1', 'symbol': 'AAPL',
            '_webull_account_id': '1234', '_webull_account_type': 'STOCK',
        }])
        self.assertEqual(request_mock.call_args.args[4], '/trading/orders/open-orders/list')
        self.assertEqual(request_mock.call_args.kwargs['query_params']['account_id'], '1234')

    def test_order_history_flattens_grouped_order_items(self):
        accounts = [{'account_id': '1234', 'account_type': 'STOCK', 'account_name': 'Individual'}]
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'items': [{
            'client_order_id': 'parent-order', 'status': 'FILLED',
            'filled_time_at': '2026-08-27T12:00:00Z',
            'items': [{'symbol': 'AAPL', 'side': 'BUY', 'order_type': 'LIMIT', 'total_quantity': '2'}],
        }]}}
        with patch('services.webull_service.get_webull_accounts', return_value=accounts), \
             patch('services.webull_service._webull_request', return_value=response):
            orders = get_webull_order_history('app-key', 'app-secret', access_token='private-token')

        self.assertEqual(orders, [{
            'client_order_id': 'parent-order', 'status': 'FILLED',
            'filled_time_at': '2026-08-27T12:00:00Z', 'symbol': 'AAPL',
            'side': 'BUY', 'order_type': 'LIMIT', 'total_quantity': '2',
            '_webull_account_id': '1234', '_webull_account_type': 'STOCK',
        }])

    def test_market_bars_choose_the_crypto_endpoint_and_normalize_epoch_milliseconds(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'bars': [
            {'timestamp': 1787832000000, 'o': '100', 'h': '105', 'l': '99', 'c': '102', 'v': '12'},
        ]}}
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            bars = get_webull_market_bars(
                'app-key', 'app-secret', access_token='private-token',
                symbol='BTCUSD', instrument_type='crypto', interval='h1', limit=50,
            )

        self.assertEqual(request_mock.call_args.args[4], '/market-data/crypto/bars/list')
        self.assertEqual(request_mock.call_args.kwargs['query_params']['interval'], 'H1')
        self.assertEqual(bars, [{
            'time': 1787832000, 'open': 100.0, 'high': 105.0, 'low': 99.0,
            'close': 102.0, 'volume': 12.0,
        }])

    def test_market_bars_use_stock_endpoint_and_options_require_a_contract_id(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'time': 1787832000, 'close': '250'}]}
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            bars = get_webull_market_bars(
                'app-key', 'app-secret', access_token='private-token',
                symbol='AAPL', instrument_type='ETF', interval='D', limit=20,
            )
            self.assertEqual(request_mock.call_args.args[4], '/market-data/stocks/bars/get')
            self.assertEqual(bars[0]['close'], 250.0)
            with self.assertRaisesRegex(WebullConnectionError, 'contract identifier'):
                get_webull_market_bars(
                    'app-key', 'app-secret', access_token='private-token',
                    symbol='AAPL260918C00100000', instrument_type='OPTION', interval='D', limit=20,
                )
        self.assertEqual(request_mock.call_count, 1)

    def test_option_bars_and_snapshot_use_option_endpoints_and_keep_contract_identity(self):
        bars_response = Mock(status_code=200)
        bars_response.json.return_value = {'data': {'bars': [{'timestamp': 1787832000000, 'c': '3.25'}]}}
        quote_response = Mock(status_code=200)
        quote_response.json.return_value = {'data': [{'symbol': 'AAPL260918C00100000', 'instrument_id': 'opt-1', 'last_price': '3.25', 'bid': '3.2', 'ask': '3.3', 'greeks': {'delta': '0.51', 'gamma': '0.04', 'theta': '-0.02', 'vega': '0.11'}}]}
        with patch('services.webull_service._webull_request', side_effect=[bars_response, quote_response]) as request_mock:
            bars = get_webull_market_bars(
                'app-key', 'app-secret', access_token='private-token', symbol='AAPL260918C00100000',
                instrument_type='OPTION', instrument_id='opt-1', interval='D', limit=20,
            )
            quote = get_webull_option_snapshot(
                'app-key', 'app-secret', access_token='private-token', symbol='AAPL260918C00100000', instrument_id='opt-1',
            )
        self.assertEqual(bars[0]['close'], 3.25)
        self.assertEqual(request_mock.call_args_list[0].args[4], '/market-data/options/bars/list')
        self.assertEqual(request_mock.call_args_list[0].kwargs['query_params']['instrument_id'], 'opt-1')
        self.assertEqual(request_mock.call_args_list[1].args[4], '/market-data/options/snapshots/list')
        self.assertEqual(quote['delta'], 0.51)
        self.assertEqual(quote['theta'], -0.02)

    def test_signature_matches_webulls_documented_example(self):
        signature = generate_webull_signature(
            '/trade/place_order',
            {'a1': 'webull', 'a2': '123', 'a3': 'xxx', 'q1': 'yyy'},
            '776da210ab4a452795d74e726ebd74b6',
            '0f50a2e853334a9aae1a783bee120c1f',
            'api.webull.com',
            '2022-01-04T03:55:31Z',
            '48ef5afed43d4d91ae514aaeafbc29ba',
            '{"k1":123,"k2":"this is the api request body","k3":true,"k4":{"foo":[1,2]}}',
        )
        self.assertEqual(signature, 'kvlS6opdZDhEBo5jq40nHYXaLvM=')

    def test_stock_movers_queries_gainers_losers_and_normalizes_pct(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': [
                {'symbol': 'AAPL', 'name': 'Apple Inc.', 'close': '235.50', 'changeRatio': '0.035', 'currency': 'USD'},
                {'symbol': 'NVDA', 'name': 'NVIDIA Corporation', 'price': '125.00', 'change_ratio': '-0.021', 'currency': 'USD'}
            ]
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            movers = get_webull_stock_movers('app-key', 'app-secret', 'sandbox', 'token-123', direction='DESC')

        self.assertEqual(len(movers), 2)
        self.assertEqual(movers[0]['symbol'], 'AAPL')
        self.assertAlmostEqual(movers[0]['change'], 3.5)
        self.assertEqual(movers[0]['price'], 235.50)
        self.assertEqual(movers[1]['symbol'], 'NVDA')
        self.assertAlmostEqual(movers[1]['change'], -2.1)
        self.assertEqual(request_mock.call_args.args[4], '/market-data/screeners/gainers-losers/list')
        self.assertEqual(request_mock.call_args.kwargs['query_params']['direction'], 'DESC')

    def test_place_webull_order_payload_and_response(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'order_id': 'wb-ord-123'}
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'sandbox', 'token-123',
                account_id='acc-999',
                symbol='AAPL',
                instrument_type='EQUITY',
                side='BUY',
                order_type='LIMIT',
                quantity=10,
                limit_price=220.50,
                time_in_force='DAY',
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['order_id'], 'wb-ord-123')
        self.assertEqual(result['symbol'], 'AAPL')
        self.assertEqual(result['side'], 'BUY')
        self.assertEqual(result['quantity'], 10.0)
        self.assertEqual(request_mock.call_args.args[4], '/openapi/account/orders/place')
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['account_id'], 'acc-999')
        self.assertEqual(len(body['orders']), 1)
        self.assertEqual(body['orders'][0]['symbol'], 'AAPL')
        self.assertEqual(body['orders'][0]['limit_price'], '220.50')

    def test_place_webull_stop_and_stop_limit_orders(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'order_id': 'wb-stop-1'}
        }
        # Test STOP order
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='acc-1', symbol='TSLA', instrument_type='EQUITY',
                side='SELL', order_type='STOP', quantity=5, stop_price=210.50,
            )
        self.assertTrue(result['success'])
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['orders'][0]['order_type'], 'STOP')
        self.assertEqual(body['orders'][0]['stop_price'], '210.50')
        self.assertNotIn('limit_price', body['orders'][0])

        # Test STOP_LIMIT order
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='acc-1', symbol='NVDA', instrument_type='EQUITY',
                side='SELL', order_type='STOP_LIMIT', quantity=10,
                stop_price=120.00, limit_price=118.50,
            )
        self.assertTrue(result['success'])
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['orders'][0]['order_type'], 'STOP_LIMIT')
        self.assertEqual(body['orders'][0]['stop_price'], '120.00')
        self.assertEqual(body['orders'][0]['limit_price'], '118.50')

        # Test crypto STOP_LIMIT order
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='acc-1', symbol='BTCUSD', instrument_type='CRYPTO',
                side='BUY', order_type='STOP_LIMIT', quantity=0.5,
                stop_price=65000.0, limit_price=65100.0,
            )
        self.assertTrue(result['success'])
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['orders'][0]['symbol'], 'BTCUSD')
        self.assertEqual(body['orders'][0]['instrument_type'], 'CRYPTO')
        self.assertEqual(body['orders'][0]['order_type'], 'STOP_LIMIT')
        self.assertEqual(body['orders'][0]['stop_price'], '65000.00')
        self.assertEqual(body['orders'][0]['limit_price'], '65100.00')


    def test_cancel_webull_order_payload_and_response(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': {'status': 'CANCELLED'}
        }
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = cancel_webull_order(
                'app-key', 'app-secret', 'sandbox', 'token-123',
                account_id='acc-999',
                order_id='wb-ord-123',
                client_order_id='client-123',
            )

        self.assertTrue(result['success'])
        self.assertEqual(request_mock.call_args.args[4], '/openapi/account/orders/cancel')
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['account_id'], 'acc-999')
        self.assertEqual(body['order_id'], 'wb-ord-123')
        self.assertEqual(body['client_order_id'], 'client-123')



class AccountScopeAndFilteringTests(unittest.TestCase):
    def test_order_filtering_by_account_scope(self):
        orders = [
            {'id': '1', 'symbol': 'BTCUSDT', 'source': 'binance'},
            {'id': '2', 'symbol': 'ETHUSDT', 'source': 'auto_sell'},
            {'id': '3', 'symbol': 'AAPL', 'source': 'webull'},
            {'id': '4', 'symbol': 'TSLA', 'source': 'webull'},
        ]

        binance_orders = [o for o in orders if o.get('source') != 'webull']
        self.assertEqual([o['id'] for o in binance_orders], ['1', '2'])

        webull_orders = [o for o in orders if o.get('source') == 'webull']
        self.assertEqual([o['id'] for o in webull_orders], ['3', '4'])

        all_orders = [o for o in orders]
        self.assertEqual(len(all_orders), 4)

    def test_filter_accounts_by_enabled_ids(self):
        accounts = [
            {'account_id': 'acc-1', 'account_name': 'Individual Cash', 'account_class': 'INDIVIDUAL_CASH'},
            {'account_id': 'acc-2', 'account_name': 'Rollover IRA', 'account_class': 'ROLLOVER_IRA'},
            {'account_id': 'acc-3', 'account_name': 'Crypto', 'account_class': 'CRYPTO'},
        ]
        enabled_ids = ['acc-1', 'acc-3']
        filtered = [a for a in accounts if a['account_id'] in enabled_ids]
        self.assertEqual(len(filtered), 2)
        self.assertEqual([a['account_id'] for a in filtered], ['acc-1', 'acc-3'])
        self.assertNotIn('acc-2', [a['account_id'] for a in filtered])

    def test_open_orders_targeted_account_and_cache(self):
        from services.webull_service import get_webull_open_orders, clear_webull_order_cache
        clear_webull_order_cache()
        response = Mock(status_code=200)
        response.json.return_value = {
            'data': [{'order_id': 'wb-1', 'symbol': 'BTCUSD', 'order_type': 'STOP_LIMIT'}]
        }
        with patch('services.webull_service.get_webull_accounts', return_value=[{'account_id': 'acc-targeted', 'account_type': 'Crypto'}]) as acc_mock:
            with patch('services.webull_service._webull_request', return_value=response) as req_mock:
                # First call
                orders = get_webull_open_orders('app-key', 'app-secret', 'production', 'token', account_id='acc-targeted')
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0]['order_id'], 'wb-1')
                self.assertEqual(req_mock.call_count, 1)

                # Second call should hit cache without extra HTTP call
                orders2 = get_webull_open_orders('app-key', 'app-secret', 'production', 'token', account_id='acc-targeted')
                self.assertEqual(len(orders2), 1)
                self.assertEqual(req_mock.call_count, 1)  # Still 1 because cached!


