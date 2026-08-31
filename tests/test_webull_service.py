import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.webull_service import (
    _normalise_option_snapshot_record,
    WebullConnectionError,
    check_webull_access_token,
    create_webull_access_token,
    generate_webull_signature,
    get_webull_accounts,
    get_webull_account_list,
    get_webull_market_bars,
    get_webull_futures_catalog,
    get_webull_futures_contracts,
    get_webull_futures_snapshot,
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
    clear_webull_event_cache,
    get_webull_event_categories,
    get_webull_event_catalog,
    get_webull_event_market,
    get_webull_event_markets,
    _normalise_event_market,
    validate_webull_event_order_market,
)
from routes.system import _require_webull_instrument_account_match, _webull_account_response
from services.webull_paper_trading_service import _utc_iso


class WebullServiceTests(unittest.TestCase):
    def setUp(self):
        clear_webull_order_cache()
        clear_webull_event_cache()

    @staticmethod
    def _response(payload, status_code=200):
        response = Mock(status_code=status_code, text='' if status_code == 200 else 'provider error')
        response.json.return_value = payload
        return response

    def test_event_catalog_traverses_categories_series_and_markets_then_ranks_live_volume(self):
        def provider(*args, **kwargs):
            path = args[4]
            params = kwargs.get('query_params') or {}
            if path.endswith('/categories/list'):
                return self._response({'data': [{'category': 'ECONOMICS', 'name': 'Economics'}]})
            if path.endswith('/series/list'):
                self.assertEqual(params['category'], 'ECONOMICS')
                self.assertEqual(params['page_size'], 500)
                return self._response({'data': [
                    {'series_id': 's1', 'symbol': 'KXRATE', 'name': 'Fed rates'},
                    {'series_id': 's2', 'symbol': 'KXCPI', 'name': 'Inflation'},
                ]})
            if path.endswith('/markets/list'):
                self.assertIn(params['series_symbol'], {'KXRATE', 'KXCPI'})
                symbol = 'KXRATE-26-T3' if params['series_symbol'] == 'KXRATE' else 'KXCPI-26-HIGH'
                return self._response({'data': [{
                    'instrument_id': f'i-{symbol}', 'symbol': symbol, 'name': f'{symbol} market',
                    'status': 'LISTING', 'tradable_status': 'OC', 'fractionable': False,
                    'price_ranges': [{'start': '0.01', 'end': '0.99', 'step': '0.01'}],
                }]})
            if path.endswith('/snapshots/list'):
                self.assertEqual(params['category'], 'US_EVENT')
                return self._response({'data': [
                    {'symbol': 'KXRATE-26-T3', 'price': '0.42', 'volume': '125', 'open_interest': '50', 'yes_ask': '0.43', 'no_ask': '0.59'},
                    {'symbol': 'KXCPI-26-HIGH', 'price': '0.25', 'volume': '900', 'open_interest': '80', 'yes_ask': '0.26', 'no_ask': '0.76'},
                ]})
            raise AssertionError(f'Unexpected Webull path: {path}')

        with patch('services.webull_service._webull_request', side_effect=provider) as request_mock:
            result = get_webull_event_markets(
                'app-key', 'app-secret', access_token='token', category_id='ECONOMICS', limit=10,
            )

        self.assertEqual([item['symbol'] for item in result['markets']], ['KXCPI-26-HIGH', 'KXRATE-26-T3'])
        self.assertEqual(result['markets'][0]['category_code'], 'ECONOMICS')
        self.assertEqual(result['markets'][0]['rules']['trading_hours'], 'Monday–Friday, 8:00 AM–11:00 PM ET')
        market_calls = [call for call in request_mock.call_args_list if call.args[4].endswith('/markets/list')]
        self.assertEqual(len(market_calls), 2)

    def test_event_search_matches_symbol_title_and_condition_without_a_fabricated_list(self):
        catalog = {
            'categories': [{'category_id': 'ECONOMICS', 'category_code': 'ECONOMICS', 'name': 'Economics'}],
            'markets': [
                {'symbol': 'KXRATE-ONE', 'name': 'Will rates fall?', 'yes_condition': 'Fed cuts once', 'category_code': 'ECONOMICS', 'price_ranges': [], 'tradable_status': 'OC'},
                {'symbol': 'KXCPI-TWO', 'name': 'Will CPI rise?', 'yes_condition': 'CPI exceeds estimate', 'category_code': 'ECONOMICS', 'price_ranges': [], 'tradable_status': 'OC'},
            ],
            'as_of': '2026-08-30T00:00:00+00:00',
        }
        snapshots = {
            'KXRATE-ONE': {'symbol': 'KXRATE-ONE', 'volume': 10},
            'KXCPI-TWO': {'symbol': 'KXCPI-TWO', 'volume': 20},
        }
        with patch('services.webull_service.get_webull_event_catalog', return_value=catalog), \
             patch('services.webull_service.get_webull_event_snapshots', return_value=snapshots):
            by_title = get_webull_event_markets('a', 's', category_id='ECONOMICS', query='rates')
            by_symbol = get_webull_event_markets('a', 's', category_id='ECONOMICS', query='kxcpi')
            by_condition = get_webull_event_markets('a', 's', category_id='ECONOMICS', query='estimate')

        self.assertEqual(by_title['markets'][0]['symbol'], 'KXRATE-ONE')
        self.assertEqual(by_symbol['markets'][0]['symbol'], 'KXCPI-TWO')
        self.assertEqual(by_condition['markets'][0]['symbol'], 'KXCPI-TWO')

    def test_event_validation_honors_provider_tradable_status_fractionality_and_tick(self):
        market = {
            'tradable_status': 'OC', 'fractionable': False,
            'price_ranges': [{'start': 0.01, 'end': 0.99, 'step': 0.01}],
        }
        validate_webull_event_order_market(market, side='BUY', quantity=1, limit_price=0.42)
        with self.assertRaisesRegex(WebullConnectionError, 'whole-number'):
            validate_webull_event_order_market(market, side='BUY', quantity=1.5, limit_price=0.42)
        with self.assertRaisesRegex(WebullConnectionError, 'tick size'):
            validate_webull_event_order_market(market, side='BUY', quantity=1, limit_price=0.425)
        with self.assertRaisesRegex(WebullConnectionError, 'not currently open'):
            validate_webull_event_order_market({**market, 'tradable_status': 'NT'}, side='BUY', quantity=1, limit_price=0.42)
        validate_webull_event_order_market({**market, 'tradable_status': 'CO'}, side='SELL', quantity=1, limit_price=0.42)

    def test_event_categories_fail_closed_instead_of_returning_hardcoded_markets(self):
        with patch('services.webull_service._webull_request', return_value=self._response({}, status_code=500)):
            with self.assertRaisesRegex(WebullConnectionError, 'HTTP 500'):
                get_webull_event_categories('app-key', 'app-secret', access_token='token')

    def test_event_categories_exclude_taxonomies_rejected_by_series_endpoint(self):
        payload = {'data': [
            {'category': 'ECONOMICS', 'name': 'Economics'},
            {'category': 'ELECTIONS', 'name': 'Elections'},
            {'category': 'COMMODITIES', 'name': 'Commodities'},
            {'category': 'POLITICS', 'name': 'Politics'},
        ]}
        with patch('services.webull_service._webull_request', return_value=self._response(payload)):
            categories = get_webull_event_categories('app-key', 'app-secret', access_token='token')

        self.assertEqual([item['category_code'] for item in categories], ['ECONOMICS', 'POLITICS'])

    def test_event_categories_are_cached_per_connection_principal(self):
        payload = {'data': [{'category': 'CRYPTO', 'name': 'Crypto'}]}
        with patch('services.webull_service._webull_request', return_value=self._response(payload)) as request_mock:
            first = get_webull_event_categories('app-key', 'app-secret', access_token='token')
            second = get_webull_event_categories('app-key', 'app-secret', access_token='token')

        self.assertEqual(first, second)
        self.assertEqual(request_mock.call_count, 1)

    def test_event_market_exposes_readable_condition_and_symbol_threshold_fallback(self):
        explicit = _normalise_event_market({
            'symbol': 'KXETHD-26SEP0417-T3409.99',
            'name': 'Ethereum price at Sep 4, 2026 at 5pm EDT?',
            'series_symbol': 'KXETHD',
            'yes_condition': '$3,410 or above',
        }, {'KXETHD': 'CRYPTO'})
        fallback = _normalise_event_market({
            'symbol': 'KXETHD-26SEP0417-T3409.99',
            'name': 'Ethereum price at Sep 4, 2026 at 5pm EDT?',
            'series_symbol': 'KXETHD',
        }, {'KXETHD': 'CRYPTO'})

        self.assertEqual(explicit['display_condition'], '$3,410 or above')
        self.assertEqual(fallback['display_condition'], 'Threshold: $3,409.99')

    def test_event_market_results_are_cached_briefly_for_repeat_category_views(self):
        catalog = {
            'categories': [{'category_id': 'CRYPTO', 'category_code': 'CRYPTO', 'name': 'Crypto'}],
            'markets': [{
                'symbol': 'KXBTC-T100000', 'name': 'Bitcoin threshold',
                'category_code': 'CRYPTO', 'price_ranges': [], 'tradable_status': 'OC',
            }],
            'as_of': '2026-08-31T00:00:00+00:00',
        }
        snapshots = {'KXBTC-T100000': {'symbol': 'KXBTC-T100000', 'volume': 100}}
        with patch('services.webull_service.get_webull_event_catalog', return_value=catalog), \
             patch('services.webull_service.get_webull_event_snapshots', return_value=snapshots) as snapshot_mock:
            first = get_webull_event_markets('a', 's', access_token='t', category_id='CRYPTO')
            second = get_webull_event_markets('a', 's', access_token='t', category_id='CRYPTO')

        self.assertEqual(first, second)
        self.assertEqual(snapshot_mock.call_count, 1)

    def test_event_catalog_returns_initial_rows_before_warming_remaining_series(self):
        def provider(*args, **kwargs):
            path = args[4]
            params = kwargs.get('query_params') or {}
            if path.endswith('/categories/list'):
                return self._response({'data': [{'category': 'CRYPTO', 'name': 'Crypto'}]})
            if path.endswith('/series/list'):
                return self._response({'data': [
                    {'series_id': 's1', 'symbol': 'FIRST', 'name': 'First series'},
                    {'series_id': 's2', 'symbol': 'SECOND', 'name': 'Second series'},
                ]})
            if path.endswith('/markets/list') and params.get('series_symbol') == 'FIRST':
                return self._response({'data': [{
                    'instrument_id': 'm1', 'symbol': 'FIRST-YES', 'name': 'First market',
                    'status': 'LISTING', 'tradable_status': 'OC',
                }]})
            raise AssertionError(f'Unexpected Webull path: {path}')

        with patch('services.webull_service._webull_request', side_effect=provider) as request_mock, \
             patch('services.webull_service.WEBULL_EVENT_DISCOVERY_MIN_INTERVAL_SECONDS', 0), \
             patch('services.webull_service.WEBULL_EVENT_INITIAL_SERIES_LIMIT', 1), \
             patch('services.webull_service.WEBULL_EVENT_INITIAL_MARKET_TARGET', 1), \
             patch('services.webull_service._start_webull_event_catalog_warmup') as warmup_mock:
            catalog = get_webull_event_catalog(
                'app-key', 'app-secret', access_token='token', category_id='CRYPTO', progressive=True,
            )

        self.assertTrue(catalog['loading'])
        self.assertTrue(catalog['partial'])
        self.assertEqual([item['symbol'] for item in catalog['markets']], ['FIRST-YES'])
        market_calls = [call for call in request_mock.call_args_list if call.args[4].endswith('/markets/list')]
        self.assertEqual(len(market_calls), 1)
        warmup_mock.assert_called_once()

    def test_paper_order_timestamps_are_serialized_as_explicit_utc(self):
        self.assertEqual(_utc_iso(datetime(2026, 8, 31, 4, 4, 0)), '2026-08-31T04:04:00Z')
        eastern_offset = timezone(timedelta(hours=-4))
        self.assertEqual(
            _utc_iso(datetime(2026, 8, 31, 0, 4, 0, tzinfo=eastern_offset)),
            '2026-08-31T04:04:00Z',
        )

    def test_event_discovery_retries_provider_rate_limit(self):
        responses = [
            self._response({'error_code': 'TOO_MANY_REQUESTS'}, status_code=429),
            self._response({'data': [{'series_id': 's1', 'symbol': 'KXRATE'}]}),
        ]
        with patch('services.webull_service._webull_request', side_effect=responses) as request_mock, \
             patch('services.webull_service.WEBULL_EVENT_DISCOVERY_MIN_INTERVAL_SECONDS', 0), \
             patch('services.webull_service.WEBULL_EVENT_DISCOVERY_RETRY_DELAYS_SECONDS', (0,)):
            from services.webull_service import _event_paginated_records
            records = _event_paginated_records(
                'app-key', 'app-secret', 'production', 'token', '/series/list',
                action='rate-limit test',
            )

        self.assertEqual(records[0]['symbol'], 'KXRATE')
        self.assertEqual(request_mock.call_count, 2)

    def test_event_catalog_keeps_successful_series_when_another_is_rate_limited(self):
        def provider(*args, **kwargs):
            path = args[4]
            params = kwargs.get('query_params') or {}
            if path.endswith('/categories/list'):
                return self._response({'data': [{'category': 'FINANCIALS', 'name': 'Financials'}]})
            if path.endswith('/series/list'):
                return self._response({'data': [
                    {'series_id': 's1', 'symbol': 'GOOD', 'name': 'Available series'},
                    {'series_id': 's2', 'symbol': 'LIMITED', 'name': 'Limited series'},
                ]})
            if path.endswith('/markets/list') and params.get('series_symbol') == 'GOOD':
                return self._response({'data': [{
                    'instrument_id': 'm1', 'symbol': 'GOOD-YES', 'name': 'Available market',
                    'status': 'LISTING', 'tradable_status': 'OC',
                }]})
            if path.endswith('/markets/list') and params.get('series_symbol') == 'LIMITED':
                return self._response({'error_code': 'TOO_MANY_REQUESTS'}, status_code=429)
            raise AssertionError(f'Unexpected Webull path: {path}')

        with patch('services.webull_service._webull_request', side_effect=provider), \
             patch('services.webull_service.WEBULL_EVENT_DISCOVERY_MIN_INTERVAL_SECONDS', 0), \
             patch('services.webull_service.WEBULL_EVENT_DISCOVERY_RETRY_DELAYS_SECONDS', ()):
            catalog = get_webull_event_catalog(
                'app-key', 'app-secret', access_token='token', category_id='FINANCIALS',
            )

        self.assertTrue(catalog['partial'])
        self.assertEqual([item['symbol'] for item in catalog['markets']], ['GOOD-YES'])
        self.assertTrue(catalog['warnings'])

    def test_environment_normalization_accepts_only_supported_values(self):
        self.assertEqual(normalize_webull_environment('Production'), 'production')
        self.assertEqual(normalize_webull_environment('sandbox'), 'sandbox')
        with self.assertRaises(WebullConnectionError):
            normalize_webull_environment('staging')

    def test_option_snapshot_normalizes_focus_quote_greeks_and_analysis_fields(self):
        snapshot = _normalise_option_snapshot_record({
            'symbol': 'AAPL260904C00320000',
            'close': '4.25', 'bid': '4.20', 'ask': '4.30',
            'bid_size': '14', 'ask_size': '11', 'open': '4.00',
            'high': '4.60', 'low': '3.80', 'pre_close': '3.90',
            'change': '0.35', 'change_ratio': '0.0897', 'volume': '1250',
            'open_interest': '9876', 'imp_vol': '0.4621',
            'delta': '0.51', 'gamma': '0.02', 'theta': '-0.08',
            'vega': '0.04', 'rho': '0.01', 'iv_percentile': '67.5',
            'iv_5_day_change': '-1.2', 'itm_probability': '0.54',
        })

        self.assertEqual(snapshot['symbol'], 'AAPL260904C00320000')
        self.assertEqual(snapshot['last_price'], 4.25)
        self.assertEqual(snapshot['bid_size'], 14.0)
        self.assertEqual(snapshot['open_interest'], 9876.0)
        self.assertEqual(snapshot['implied_volatility'], 0.4621)
        self.assertEqual(snapshot['delta'], 0.51)
        self.assertEqual(snapshot['iv_percentile'], 67.5)
        self.assertEqual(snapshot['itm_percent'], 0.54)

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

    def test_account_list_prefers_current_path_and_falls_back_only_for_compatibility(self):
        current = Mock(status_code=200)
        with patch('services.webull_service._webull_request', return_value=current) as request_mock:
            self.assertIs(get_webull_account_list('app-key', 'app-secret', access_token='token-a'), current)
        self.assertEqual(request_mock.call_count, 1)
        self.assertEqual(request_mock.call_args.args[4], '/trading/accounts/list')

        unsupported = Mock(status_code=404)
        legacy = Mock(status_code=200)
        with patch('services.webull_service._webull_request', side_effect=[unsupported, legacy]) as request_mock:
            self.assertIs(get_webull_account_list('app-key', 'app-secret', access_token='token-a'), legacy)
        self.assertEqual([call.args[4] for call in request_mock.call_args_list], [
            '/trading/accounts/list', '/openapi/account/list',
        ])

    def test_account_cache_is_scoped_to_the_access_token(self):
        response_a = Mock(status_code=200)
        response_a.json.return_value = {'data': [{'account_id': 'account-a', 'account_type': 'CASH'}]}
        response_b = Mock(status_code=200)
        response_b.json.return_value = {'data': [{'account_id': 'account-b', 'account_type': 'CASH'}]}
        with patch('services.webull_service._webull_request', side_effect=[response_a, response_b]) as request_mock:
            accounts_a = get_webull_accounts('shared-app-key', 'app-secret', access_token='token-a')
            accounts_b = get_webull_accounts('shared-app-key', 'app-secret', access_token='token-b')

        self.assertEqual(accounts_a[0]['account_id'], 'account-a')
        self.assertEqual(accounts_b[0]['account_id'], 'account-b')
        self.assertEqual(request_mock.call_count, 2)

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

    def test_portfolio_preview_limits_reads_to_enabled_accounts(self):
        accounts = [
            {'account_id': 'cash-account', 'account_type': 'CASH', 'account_name': 'Cash'},
            {'account_id': 'crypto-account', 'account_type': 'CRYPTO', 'account_name': 'Crypto'},
        ]
        with patch('services.webull_service.get_webull_accounts', return_value=accounts), \
             patch('services.webull_service.get_webull_account_balance', return_value={'total_cash_balance': '10'}) as balance_mock, \
             patch('services.webull_service.get_webull_account_positions', return_value=[]):
            preview = get_webull_portfolio_preview(
                'app-key', 'app-secret', access_token='private-token', account_ids={'cash-account'},
            )

        self.assertEqual([account['account_id'] for account in preview], ['cash-account'])
        self.assertEqual(balance_mock.call_args.args[-1], 'cash-account')

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

    def test_futures_catalog_contract_snapshot_and_bars_use_documented_endpoints(self):
        product_response = Mock(status_code=200)
        product_response.json.return_value = {'data': [{'product_code': 'ES', 'name': 'E-mini S&P 500'}]}
        contract_response = Mock(status_code=200)
        contract_response.json.return_value = {'data': [{'symbol': 'ESZ5', 'product_code': 'ES', 'name': 'E-mini S&P 500 Dec 2025'}]}
        snapshot_response = Mock(status_code=200)
        snapshot_response.json.return_value = {'data': [{'symbol': 'ESZ5', 'last_price': '4500.25', 'bid': '4500.00', 'ask': '4500.50'}]}
        bars_response = Mock(status_code=200)
        bars_response.json.return_value = {'data': {'bars': [{'timestamp': 1787832000000, 'c': '4500.25'}]}}
        with patch('services.webull_service._webull_request', side_effect=[
            product_response, contract_response, snapshot_response, bars_response,
        ]) as request_mock:
            catalog = get_webull_futures_catalog('app-key', 'app-secret', access_token='token')
            contracts = get_webull_futures_contracts('app-key', 'app-secret', access_token='token', symbol='esz5')
            snapshot = get_webull_futures_snapshot('app-key', 'app-secret', access_token='token', symbol='esz5')
            bars = get_webull_market_bars(
                'app-key', 'app-secret', access_token='token', symbol='ESZ5',
                instrument_type='FUTURES', interval='D', limit=20,
            )

        self.assertEqual([call.args[4] for call in request_mock.call_args_list], [
            '/trading/instruments/futures/product-codes/list',
            '/trading/instruments/futures/contracts/list',
            '/market-data/futures/snapshots/list',
            '/market-data/futures/bars/list',
        ])
        self.assertEqual(catalog['products'][0]['product_code'], 'ES')
        self.assertEqual(contracts[0]['symbol'], 'ESZ5')
        self.assertEqual(snapshot['price'], 4500.25)
        self.assertEqual(bars[0]['close'], 4500.25)
        self.assertEqual(request_mock.call_args_list[1].kwargs['query_params'], {'symbols': 'ESZ5'})
        self.assertEqual(request_mock.call_args_list[2].kwargs['query_params']['category'], 'US_FUTURES')

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
        self.assertEqual(request_mock.call_args.args[4], '/trading/orders/place')
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['account_id'], 'acc-999')
        self.assertEqual(len(body['new_orders']), 1)
        self.assertEqual(body['new_orders'][0]['symbol'], 'AAPL')
        self.assertEqual(body['new_orders'][0]['limit_price'], '220.50')

    def test_fractional_equity_market_order_is_core_only_and_preserves_quantity(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'order_id': 'wb-fractional-1'}}
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='cash-account', symbol='TSLA', instrument_type='EQUITY',
                side='SELL', order_type='MARKET', quantity=0.11,
                time_in_force='DAY', support_trading_session='CORE',
            )

        self.assertTrue(result['success'])
        body = request_mock.call_args.kwargs['body']
        order = body['new_orders'][0]
        self.assertEqual(order['quantity'], '0.11')
        self.assertEqual(order['market'], 'US')
        self.assertEqual(order['entrust_type'], 'QTY')
        self.assertEqual(order['support_trading_session'], 'CORE')

    def test_fractional_equity_rejects_non_core_or_non_market_orders(self):
        with self.assertRaisesRegex(WebullConnectionError, 'Regular Hours'):
            place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='cash-account', symbol='TSLA', instrument_type='EQUITY',
                side='SELL', order_type='MARKET', quantity=0.11,
                support_trading_session='ALL',
            )

        with self.assertRaisesRegex(WebullConnectionError, 'Market orders'):
            place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='cash-account', symbol='TSLA', instrument_type='EQUITY',
                side='SELL', order_type='LIMIT', quantity=0.11,
                limit_price=350,
                support_trading_session='CORE',
            )

    def test_option_order_uses_exact_single_leg_contract_and_current_schema(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'order_id': 'wb-option-1'}}
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='options-account', symbol='TSLA240117C00250000',
                option_underlying_symbol='TSLA', instrument_type='OPTION',
                side='SELL', order_type='STOP_LIMIT', quantity=1,
                limit_price=3.80, stop_price=4.00, time_in_force='DAY',
                option_type='PUT', option_strike=250, option_expiration='2027-01-17',
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['symbol'], 'TSLA240117C00250000')
        self.assertEqual(request_mock.call_args.args[4], '/trading/orders/place')
        order = request_mock.call_args.kwargs['body']['new_orders'][0]
        self.assertEqual(order['symbol'], 'TSLA')
        self.assertEqual(order['instrument_type'], 'OPTION')
        self.assertEqual(order['market'], 'US')
        self.assertEqual(order['entrust_type'], 'QTY')
        self.assertEqual(order['order_type'], 'STOP_LOSS_LIMIT')
        self.assertEqual(order['legs'], [{
            'symbol': 'TSLA', 'side': 'SELL', 'quantity': '1',
            'strike_price': '250', 'option_expire_date': '2027-01-17',
            'instrument_type': 'OPTION', 'option_type': 'PUT', 'market': 'US',
        }])

    def test_option_order_rejects_missing_contract_fields_and_invalid_capabilities(self):
        base = {
            'account_id': 'options-account', 'symbol': 'TSLA', 'instrument_type': 'OPTION',
            'side': 'SELL', 'quantity': 1, 'time_in_force': 'DAY',
            'option_type': 'CALL', 'option_strike': 250, 'option_expiration': '2027-01-17',
        }
        with self.assertRaisesRegex(WebullConnectionError, 'support LIMIT'):
            place_webull_order('app-key', 'app-secret', order_type='MARKET', **base)
        with self.assertRaisesRegex(WebullConnectionError, 'strike'):
            place_webull_order('app-key', 'app-secret', order_type='LIMIT', option_strike=None, limit_price=2, **{k: v for k, v in base.items() if k != 'option_strike'})
        with self.assertRaisesRegex(WebullConnectionError, 'DAY'):
            place_webull_order('app-key', 'app-secret', order_type='LIMIT', time_in_force='GTC', limit_price=2, **{k: v for k, v in base.items() if k != 'time_in_force'})

    def test_option_vertical_strategy_uses_documented_strategy_and_legs(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'order_id': 'wb-option-vertical-1'}}
        legs = [
            {'instrument_type': 'OPTION', 'side': 'BUY', 'quantity': 1, 'strike_price': 180, 'option_expire_date': '2027-01-17', 'option_type': 'CALL'},
            {'instrument_type': 'OPTION', 'side': 'SELL', 'quantity': 1, 'strike_price': 190, 'option_expire_date': '2027-01-17', 'option_type': 'CALL'},
        ]
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='options-account', symbol='AAPL', option_underlying_symbol='AAPL',
                instrument_type='OPTION', side='BUY', order_type='LIMIT', quantity=2,
                limit_price=3.50, time_in_force='DAY', option_type='CALL', option_strike=180,
                option_expiration='2027-01-17', option_strategy='VERTICAL', option_legs=legs,
            )

        self.assertTrue(result['success'])
        order = request_mock.call_args.kwargs['body']['new_orders'][0]
        self.assertEqual(order['option_strategy'], 'VERTICAL')
        self.assertEqual(order['limit_price'], '3.50')
        self.assertEqual(order['legs'][0]['strike_price'], '180')
        self.assertEqual(order['legs'][0]['quantity'], '2')
        self.assertEqual(order['legs'][1]['quantity'], '2')
        self.assertEqual(order['legs'][1]['side'], 'SELL')

    def test_undocumented_ratio_strategy_is_rejected(self):
        with self.assertRaisesRegex(WebullConnectionError, 'Ratio'):
            place_webull_order(
                'app-key', 'app-secret', account_id='options-account', symbol='AAPL',
                instrument_type='OPTION', side='BUY', order_type='LIMIT', quantity=1,
                limit_price=1, option_type='CALL', option_strike=180,
                option_expiration='2027-01-17', option_strategy='RATIO', option_legs=[{}, {}],
            )

    def test_futures_order_uses_futures_schema_and_trailing_stop_fields(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': {'order_id': 'wb-futures-1'}}
        with patch('services.webull_service._webull_request', return_value=response) as request_mock:
            result = place_webull_order(
                'app-key', 'app-secret', 'production', 'token-123',
                account_id='futures-account', symbol='ESZ5', instrument_type='FUTURES',
                side='SELL', order_type='TRAILING_STOP_LOSS', quantity=2,
                trailing_type='PERCENTAGE', trailing_stop_step=1.25, time_in_force='GTC',
            )

        self.assertTrue(result['success'])
        order = request_mock.call_args.kwargs['body']['new_orders'][0]
        self.assertEqual(order, {
            'combo_type': 'NORMAL', 'client_order_id': order['client_order_id'],
            'symbol': 'ESZ5', 'instrument_type': 'FUTURES', 'market': 'US',
            'order_type': 'TRAILING_STOP_LOSS', 'side': 'SELL', 'quantity': '2',
            'time_in_force': 'GTC', 'entrust_type': 'QTY',
            'trailing_type': 'PERCENTAGE', 'trailing_stop_step': '1.25',
        })

    def test_futures_orders_reject_fractional_contracts_and_invalid_trail(self):
        base = {
            'account_id': 'futures-account', 'symbol': 'ESZ5', 'instrument_type': 'FUTURES',
            'side': 'BUY', 'time_in_force': 'DAY',
        }
        with self.assertRaisesRegex(WebullConnectionError, 'whole number'):
            place_webull_order('app-key', 'app-secret', order_type='MARKET', quantity=0.5, **base)
        with self.assertRaisesRegex(WebullConnectionError, 'AMOUNT or PERCENTAGE'):
            place_webull_order('app-key', 'app-secret', order_type='TRAILING_STOP_LOSS', quantity=1, **base)

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
        self.assertEqual(body['new_orders'][0]['order_type'], 'STOP_LOSS')
        self.assertEqual(body['new_orders'][0]['stop_price'], '210.50')
        self.assertNotIn('limit_price', body['new_orders'][0])

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
        self.assertEqual(body['new_orders'][0]['order_type'], 'STOP_LOSS_LIMIT')
        self.assertEqual(body['new_orders'][0]['stop_price'], '120.00')
        self.assertEqual(body['new_orders'][0]['limit_price'], '118.50')

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
        self.assertEqual(body['new_orders'][0]['symbol'], 'BTCUSD')
        self.assertEqual(body['new_orders'][0]['instrument_type'], 'CRYPTO')
        self.assertEqual(body['new_orders'][0]['order_type'], 'STOP_LOSS_LIMIT')
        self.assertEqual(body['new_orders'][0]['stop_price'], '65000.00')
        self.assertEqual(body['new_orders'][0]['limit_price'], '65100.00')


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
        self.assertEqual(request_mock.call_args.args[4], '/trading/orders/cancel')
        body = request_mock.call_args.kwargs['body']
        self.assertEqual(body['account_id'], 'acc-999')
        self.assertEqual(body['order_id'], 'wb-ord-123')
        self.assertEqual(body['client_order_id'], 'client-123')



class AccountScopeAndFilteringTests(unittest.TestCase):
    def test_crypto_and_non_crypto_accounts_are_kept_in_separate_asset_lanes(self):
        setting = SimpleNamespace(webull_connected_accounts=[
            {'account_id': 'crypto-account', 'account_class': 'CRYPTO', 'account_label': 'Crypto'},
            {'account_id': 'cash-account', 'account_class': 'INDIVIDUAL_CASH', 'account_label': 'Individual Cash'},
        ])

        self.assertEqual(_require_webull_instrument_account_match(setting, 'crypto-account', 'CRYPTO'), 'CRYPTO')
        self.assertEqual(_require_webull_instrument_account_match(setting, 'cash-account', 'FUTURES'), 'FUTURES')
        with self.assertRaisesRegex(WebullConnectionError, 'Crypto Webull account'):
            _require_webull_instrument_account_match(setting, 'crypto-account', 'FUTURES')
        with self.assertRaisesRegex(WebullConnectionError, 'Crypto orders require'):
            _require_webull_instrument_account_match(setting, 'cash-account', 'CRYPTO')

    def test_browser_account_response_masks_numbers_applies_alias_and_uses_local_balance(self):
        accounts = _webull_account_response(
            [{
                'account_id': 'acct-12345678',
                'account_number': 'ABCD9876',
                'account_label': 'Individual Cash',
                'account_type': 'CASH',
            }],
            aliases={'acct-12345678': 'Long-term cash'},
            snapshots={'acct-12345678': {
                'currency': 'USD',
                'total_cash_balance': 125.25,
                'total_market_value': 700.0,
                'total_net_liquidation_value': 825.25,
            }},
            enabled_ids={'acct-12345678'},
        )

        self.assertEqual(accounts, [{
            'account_id': 'acct-12345678',
            'account_label': 'Long-term cash',
            'account_class': '',
            'account_type': 'CASH',
            'account_name': 'Long-term cash',
            'account_id_masked': '••••9876',
            'balance': {
                'total_asset_currency': 'USD',
                'total_cash_balance': 125.25,
                'total_market_value': 700.0,
                'total_net_liquidation_value': 825.25,
                'total_unrealized_profit_loss': None,
            },
            'is_enabled': True,
        }])
        self.assertNotIn('account_number', accounts[0])

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
