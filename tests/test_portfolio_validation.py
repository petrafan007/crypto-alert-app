"""Synthetic unit fixtures test code behavior, never claim market performance."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.portfolio_execution_math import costs, entry_quantity, fill_price, spot_exit
from services.portfolio_strategy_signals import crypto_signal, utc
from services.portfolio_validation import MAX_QUOTES, _dominance, run_validation


SETTINGS = {'entry_channel_periods': 20, 'exit_channel_periods': 10, 'atr_stop_multiplier': 2.5}


def fixture(days=8, exit_price=96):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = [{'time': (start + timedelta(hours=hour)).isoformat(), 'open': 100, 'high': 101,
             'low': 99, 'close': 100, 'volume': 10} for hour in range(24 * (days + 1))]
    quotes = []
    for day in range(days):
        entry = start + timedelta(days=day, hours=20, minutes=15)
        quotes += [{'time': entry.isoformat(), 'price': 102},
                   {'time': (entry + timedelta(hours=1)).isoformat(), 'price': exit_price}]
    return {'schema_version': 1, 'module': 'crypto', 'symbol': 'BTC',
            'source': 'SYNTHETIC UNIT-TEST FIXTURE; not historical market results',
            'evaluation_start': quotes[0]['time'], 'split_at': quotes[len(quotes) // 2]['time'],
            'bars': bars, 'quotes': quotes}


def run(payload, allocation=20):
    return run_validation(payload, SETTINGS, allocation, 50000, 18.5)


def baseline(result, window='development'):
    return result['windows'][window]['scenarios'][0]


class SharedExecutionMathTests(unittest.TestCase):
    def test_live_commission_and_adverse_fill_defaults(self):
        self.assertEqual(costs('options', 100, 2), 2.6)
        self.assertEqual(costs('futures', 100, 2), 2.5)
        self.assertEqual(costs('events', 0.5, 2), 0.03)
        self.assertAlmostEqual(costs('crypto', 100, 2), 0.2)
        self.assertAlmostEqual(fill_price('crypto', 100, 'LONG'), 100.05)
        self.assertAlmostEqual(fill_price('crypto', 100, 'LONG', closing=True), 99.95)
        self.assertAlmostEqual(fill_price('equities', 100, 'SHORT'), 99.95)
        self.assertEqual(fill_price('events', 0.5, 'LONG'), 0.5)

    def test_cash_stop_risk_and_daily_loss_caps(self):
        quantity = entry_quantity('crypto', 100, 100000, 50000, 90)
        self.assertLessEqual(quantity * (10 + 2 * costs('crypto', 100, 1)), 250)
        self.assertLessEqual(entry_quantity('equities', 100, 1000, 50000, 90) * 100.1, 1000)
        self.assertEqual(entry_quantity('equities', 100, 99, 50000, 90), 0)
        self.assertEqual(entry_quantity('crypto', 100, 0, 50000, 90), 0)
        capped = entry_quantity('futures', 100, 50000, 50000, 90, max_loss=20)
        self.assertLessEqual(capped * 12.5, 20)
        self.assertEqual(entry_quantity('events', 0.5, 1000, 50000), 50)

    def test_stop_precedes_trailing_update_and_strategy_exit(self):
        self.assertEqual(spot_exit('crypto', 90, 'LONG', 95, {'exit': True, 'stop': 99}), ('STOP_LOSS', 95))
        self.assertEqual(spot_exit('crypto', 101, 'LONG', 95, {'exit': False, 'stop': 98}), (None, 98))
        self.assertEqual(spot_exit('crypto', 101, 'LONG', 99, {'exit': False, 'stop': 98}), (None, 99))
        self.assertEqual(spot_exit('equities', 101, 'LONG', 95, {'exit': False, 'stop': 98}), (None, 95))
        self.assertEqual(spot_exit('crypto', 90, 'LONG', 95, None), ('STOP_LOSS', 95))


class PortfolioValidationTests(unittest.TestCase):
    def test_actual_signal_rules_make_trades_and_charge_both_sides(self):
        result = run(fixture())
        sample = baseline(result)
        self.assertGreater(sample['closed_trades'], 0)
        trade = sample['trades'][0]
        self.assertEqual(trade['reason'], 'STOP_LOSS')
        self.assertAlmostEqual(trade['net_pnl'], (trade['exit_price'] - trade['price']) * trade['quantity'] - trade['entry_fee'] - trade['exit_fee'])
        self.assertAlmostEqual(sample['ending_equity'], 50000 + sum(row['net_pnl'] for row in sample['trades']))
        self.assertTrue(all(trade['collateral'] + trade['entry_fee'] <= 50000 * .20 * .20 for trade in sample['trades']))
        self.assertLess(sample['target_equity_gap'], 0)
        self.assertIsNone(sample['annualized_return_pct'])

    def test_windows_are_chronological_independent_and_do_not_optimize(self):
        data = fixture()
        result = run(data)
        development, holdout = result['windows']['development'], result['windows']['held_out']
        self.assertLess(utc(development['end']), utc(holdout['start']))
        self.assertEqual(baseline(result)['starting_equity'], baseline(result, 'held_out')['starting_equity'])
        self.assertEqual(result['saved_parameters'], SETTINGS)
        self.assertIn('held-out', holdout['label'])
        self.assertFalse(result['source_verified'])
        for module in ('equities', 'options', 'futures', 'events'):
            self.assertEqual(result['coverage'][module], 'NOT_VALIDATED')

    def test_future_and_forming_candles_never_enter_signal(self):
        data = fixture()
        seen = []

        def inspect(bars, price, settings, dominance_ok):
            seen.append(bars)
            return crypto_signal(bars, price, settings, dominance_ok)

        with patch('services.portfolio_validation.crypto_signal', side_effect=inspect):
            original = run(data)
        # First quote is at 20:15; only hours 0..19 may be completed.
        self.assertEqual(len(seen[0]), 20)
        self.assertEqual(seen[0][-1]['time'], utc(data['bars'][19]['time']).timestamp())
        future = copy.deepcopy(data)
        future['bars'].append({'time': '2025-02-01T00:00:00Z', 'open': 1e8, 'high': 1e9, 'low': 1, 'close': 1e8})
        self.assertEqual(original['windows'], run(future)['windows'])

    def test_future_holdout_prices_cannot_change_development(self):
        data = fixture()
        original = run(data)
        for quote in data['quotes']:
            if utc(quote['time']) >= utc(data['split_at']):
                quote['price'] *= 2
        altered = run(data)
        self.assertEqual(original['windows']['development'], altered['windows']['development'])
        self.assertNotEqual(original['windows']['held_out'], altered['windows']['held_out'])

    def test_publication_delay_is_respected(self):
        data = fixture()
        data['bars'][19]['available_at'] = '2025-01-01T20:30:00Z'
        result = run(data)
        self.assertGreater(baseline(result)['decisions'].get('Insufficient completed hourly channel history.', 0), 0)
        data['bars'][19]['available_at'] = '2025-01-01T19:30:00Z'
        with self.assertRaisesRegex(ValueError, 'before it completes'):
            run(data)

    def test_same_date_signal_cannot_reenter_after_stop(self):
        data = fixture()
        first = utc(data['quotes'][0]['time'])
        data['quotes'] += [{'time': (first + timedelta(hours=2)).isoformat(), 'price': 102},
                           {'time': (first + timedelta(hours=3)).isoformat(), 'price': 98}]
        result = baseline(run(data))
        dates = [utc(trade['opened_at']).date() for trade in result['trades']]
        self.assertEqual(len(dates), len(set(dates)))
        self.assertGreater(result['decisions'].get('signal_already_consumed', 0), 0)

    def test_stresses_have_explicit_cost_latency_and_missed_fill_effects(self):
        scenarios = run(fixture())['windows']['development']['scenarios']
        normal, expensive, delayed, missed = scenarios
        self.assertLess(expensive['ending_equity'], normal['ending_equity'])
        self.assertEqual(delayed['entries'], 0)
        self.assertGreater(delayed['decisions']['delayed_entry_failed_revalidation'], 0)
        self.assertLess(missed['entries'], normal['entries'])
        self.assertGreater(missed['decisions']['scenario_unfilled_entry'], 0)

    def test_circuit_stops_entries_but_continues_management(self):
        result = baseline(run(fixture(days=12, exit_price=1), allocation=100))
        self.assertTrue(result['circuit_paused'])
        self.assertIsNotNone(result['circuit_at'])
        self.assertLessEqual(result['ending_equity'], 45000)
        self.assertEqual(result['open_positions'], 0)
        self.assertGreater(result['decisions']['circuit_entry_blocked'], 0)

    def test_stale_history_still_allows_existing_stop(self):
        data = fixture()
        data['bars'] = data['bars'][:20]
        data['quotes'][1]['time'] = '2025-01-02T00:00:00Z'
        result = baseline(run(data))
        self.assertGreater(result['decisions'].get('Historical candles are stale.', 0), 0)
        self.assertEqual(result['trades'][0]['reason'], 'STOP_LOSS')

    def test_bounds_nonfinite_duplicates_and_unsupported_module(self):
        for modify, message in (
            (lambda data: data.update(module='events'), 'supports equities and crypto'),
            (lambda data: data['quotes'].extend(copy.deepcopy(data['quotes'][:1])), 'duplicate timestamps'),
            (lambda data: data['quotes'][0].update(price=float('nan')), 'quote price'),
            (lambda data: data.update(quotes=[{}] * (MAX_QUOTES + 1)), '3000'),
            (lambda data: data.update(split_at=data['evaluation_start']), 'must precede'),
        ):
            data = fixture()
            modify(data)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                run(data)

    def test_altcoins_require_observed_dominance_not_invented_history(self):
        data = fixture()
        data['symbol'] = 'ETH'
        unavailable = baseline(run(data))
        self.assertEqual(unavailable['entries'], 0)
        self.assertTrue(any('dominance' in key for key in unavailable['decisions']))
        now = utc('2025-01-08T20:00:00Z')
        rows = [{'time': now - timedelta(days=day), 'value': 50 + day} for day in range(7, -1, -1)]
        observed = {'rows': rows, 'times': [row['time'] for row in rows],
                    'days': {row['time'].date(): [row] for row in rows}}
        self.assertTrue(_dominance('ETH', observed, now))
        # A future current-day observation cannot make the gate pass.
        with self.assertRaisesRegex(ValueError, 'preceding hour'):
            _dominance('ETH', observed, now - timedelta(minutes=1))
        del observed['days'][(now - timedelta(days=3)).date()]
        with self.assertRaisesRegex(ValueError, 'seven preceding'):
            _dominance('ETH', observed, now)

    def test_equity_requires_benchmark_and_uses_nyse_completion(self):
        data = fixture()
        data['module'] = 'equities'
        settings = {'trend_sma_days': 200, 'rsi_period': 2, 'rsi_entry_threshold': 10, 'bollinger_std': 2}
        with self.assertRaisesRegex(ValueError, 'benchmark_bars'):
            run_validation(data, settings, 35, 50000)
        # A holiday must not be accepted as a completed NYSE daily bar.
        data['benchmark_bars'] = data['bars'][:1]
        data['bars'] = data['bars'][:1]
        with self.assertRaisesRegex(ValueError, 'actual NYSE'):
            run_validation(data, settings, 35, 50000)


if __name__ == '__main__':
    unittest.main()
