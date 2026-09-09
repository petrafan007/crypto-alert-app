"""Bounded, read-only historical replay of the implemented spot strategies.

This is deliberately not a broker fill emulator or a five-module backtest.
Only uploaded observations are consumed; no database, provider or AI calls.
"""
from bisect import bisect_right
from collections import Counter
from datetime import timedelta
import math

from services.portfolio_execution_math import costs, entry_quantity, fill_price, spot_exit
from services.portfolio_strategy_signals import ET, crypto_signal, equity_signal, finite, performance, utc

MAX_BARS = 12000
MAX_QUOTES = 3000
MAX_SPAN_DAYS = 3653
SCENARIOS = (
    ('baseline', 1.0, 1.0, False, False),
    ('double_execution_costs', 2.0, 2.0, False, False),
    ('one_observation_entry_delay', 1.0, 1.0, True, False),
    ('every_second_entry_unfilled', 1.0, 1.0, False, True),
)


def _time(value, name):
    try:
        result = utc(value)
        if not 1990 <= result.year <= 2100:
            raise ValueError()
        return result
    except (ValueError, TypeError, OverflowError, OSError):
        raise ValueError(f'{name} must be an ISO-8601 timestamp between 1990 and 2100.') from None


def _rows(value, name, limit, required=True):
    if not isinstance(value, list) or len(value) > limit or (required and not value):
        raise ValueError(f'{name} must contain {1 if required else 0}–{limit} observations.')
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f'Each {name} observation must be an object.')
    return value


def _ordered(rows, name):
    rows.sort(key=lambda row: row['time'])
    if any(a['time'] == b['time'] for a, b in zip(rows, rows[1:])):
        raise ValueError(f'{name} contains duplicate timestamps; supply one observed value per time.')
    if rows and (rows[-1]['time'] - rows[0]['time']).total_seconds() > MAX_SPAN_DAYS * 86400:
        raise ValueError(f'{name} exceeds the ten-year replay bound.')
    return rows


def _session_calendar(module, bars, benchmark, quotes):
    if module != 'equities':
        return {}
    # Bulk schedule matches live NYSE session semantics without one expensive
    # pandas calendar construction for every imported candle.
    import pandas_market_calendars as calendars
    dates = [row['time'].date() if row['time'].hour == 0 else row['time'].astimezone(ET).date()
             for row in bars + benchmark]
    dates += [row['time'].astimezone(ET).date() for row in quotes]
    if (max(dates) - min(dates)).days > MAX_SPAN_DAYS:
        raise ValueError('Combined history exceeds the ten-year replay bound.')
    schedule = calendars.get_calendar('NYSE').schedule(start_date=min(dates), end_date=max(dates))
    return {index.date(): (row.market_open.to_pydatetime(), row.market_close.to_pydatetime())
            for index, row in schedule.iterrows()}


def _bars(rows, module, sessions):
    clean = []
    for row in rows:
        item = {key: finite(row.get(key), key, 0.000001) for key in ('open', 'high', 'low', 'close')}
        item['volume'] = finite(row.get('volume', 0), 'volume')
        if item['low'] > min(item['open'], item['close']) or item['high'] < max(item['open'], item['close']):
            raise ValueError('Invalid OHLC candle.')
        stamp = row['time']
        if module == 'equities':
            day = stamp.date() if stamp.hour == 0 else stamp.astimezone(ET).date()
            if day not in sessions:
                raise ValueError('Equity daily bars must belong to actual NYSE trading sessions.')
            complete = sessions[day][1]
        else:
            complete = stamp + timedelta(hours=1)
        # A provider may publish a finalized candle later than its scheduled
        # close; available_at can delay availability, never bring it forward.
        available = _time(row.get('available_at', complete), 'bar available_at')
        if available < complete:
            raise ValueError('A bar cannot be available before it completes.')
        clean.append({**item, 'time': stamp.timestamp(), 'available_at': available.timestamp()})
    if any(a['available_at'] >= b['available_at'] for a, b in zip(clean, clean[1:])):
        raise ValueError('Bar availability must be strictly chronological; revised/reordered feeds are unsupported.')
    return clean


def _history(rows, now, limit, module):
    index = bisect_right(rows['available'], now.timestamp())
    history = rows['bars'][max(0, index - limit):index]
    if not history:
        raise ValueError('No completed market candles.')
    allowance = 7 * 86400 if module == 'equities' else 7200
    # Freshness starts when the latest completed candle became usable, not at
    # its opening timestamp. Measuring an hourly candle from its open marks a
    # normally published bar stale up to an hour too early.
    if now.timestamp() - history[-1]['available_at'] > allowance:
        raise ValueError('Historical candles are stale.')
    return history


def _dominance(symbol, observations, now):
    if symbol == 'BTC':
        return True
    index = bisect_right(observations['times'], now)
    if not index or (now - observations['rows'][index - 1]['time']).total_seconds() > 3600:
        raise ValueError('Altcoin replay requires a BTC-dominance observation within the preceding hour.')
    current = observations['rows'][index - 1]['value']
    previous = []
    for offset in range(1, 8):
        day = now.date() - timedelta(days=offset)
        day_rows = observations['days'].get(day, [])
        if not day_rows:
            raise ValueError('Altcoin replay requires all seven preceding UTC days of observed BTC dominance.')
        previous.append(day_rows[-1]['value'])
    return current <= sum(previous) / len(previous)


def _signal(module, symbol, now, price, histories, settings, dominance, managing=False):
    limit = max(settings.get('trend_sma_days', 200) + 10, 260) if module == 'equities' else 150
    bars = _history(histories['bars'], now, limit, module)
    if module == 'equities':
        return equity_signal(bars, price, settings, _history(histories['benchmark'], now, 260, module))
    return crypto_signal(bars, price, settings, True if managing else _dominance(symbol, dominance, now))


def _replay(module, symbol, quotes, histories, settings, dominance, sessions,
            initial, allocation, target, scenario):
    name, fee_factor, slip_factor, delayed, missed = scenario
    cash, equity, position, paused, pending = initial, initial, None, False, None
    consumed, closed, decisions = set(), [], Counter()
    snapshots = [{'time': quotes[0]['time'], 'equity': initial}]
    entries, entry_attempts, max_utilization = 0, 0, 0.0
    circuit_at = None

    def close(price, now, reason):
        nonlocal cash, position
        exit_price = fill_price(module, price, 'LONG', closing=True, slippage_multiplier=slip_factor)
        exit_fee = costs(module, exit_price, position['quantity'], fee_factor)
        gross = (exit_price - position['price']) * position['quantity']
        cash += position['collateral'] + gross - exit_fee
        closed.append({**position, 'closed_at': now.isoformat(), 'exit_price': exit_price,
                       'exit_fee': exit_fee, 'net_pnl': gross - position['entry_fee'] - exit_fee,
                       'reason': reason})
        position = None

    def mark(price):
        return cash + (position['collateral'] + (price - position['price']) * position['quantity'] if position else 0)

    for quote in quotes:
        now, price = quote['time'], quote['price']
        if module == 'equities':
            session = sessions.get(now.astimezone(ET).date())
            if not session or not session[0] <= now < session[1]:
                decisions['market_closed'] += 1
                snapshots.append({'time': now, 'equity': equity})
                continue
        signal = None
        try:
            signal = _signal(module, symbol, now, price, histories, settings, dominance, managing=bool(position))
        except ValueError as exc:
            decisions[str(exc)] += 1
        if position:
            reason, position['stop'] = spot_exit(module, price, 'LONG', position['stop'], signal)
            if reason:
                close(price, now, reason)
            equity = mark(price)
            if equity <= initial * 0.9:
                paused = True
                circuit_at = circuit_at or now.isoformat()
            if position and not paused and equity > 0:
                capital = position['collateral'] + (price - position['price']) * position['quantity']
                if capital / equity * 100 - allocation > 3:
                    close(price, now, 'REBALANCE_TRIM')
                    equity = mark(price)
            # The entry path must apply dominance even when an existing
            # holding was just closed (live management bypasses that gate).
            if module == 'crypto' and not position and signal:
                try:
                    signal = _signal(module, symbol, now, price, histories, settings, dominance)
                except ValueError as exc:
                    decisions[str(exc)] += 1
                    signal = None
        eligible = bool(signal and signal.get('enter'))
        if eligible:
            decisions['qualified_observations'] += 1
        execute = eligible
        if delayed:
            execute = pending is not None and eligible
            if pending is not None and not eligible:
                decisions['delayed_entry_failed_revalidation'] += 1
            if execute:
                decisions['entry_delay_total_seconds'] += (now - pending).total_seconds()
            pending = None if pending is not None else now if eligible and not position and not paused else None
            # One queued order is consumed at the next observed quote, never
            # at a fabricated in-between price or at the original stale quote.
            if execute:
                pending = None
        if execute:
            key = f'{module}:{symbol}:{now.astimezone(ET).date()}'
            if paused:
                decisions['circuit_entry_blocked'] += 1
            elif position:
                decisions['existing_position'] += 1
            elif key in consumed:
                decisions['signal_already_consumed'] += 1
            else:
                entry_attempts += 1
                if missed and entry_attempts % 2 == 0:
                    decisions['scenario_unfilled_entry'] += 1
                else:
                    execution = fill_price(module, price, 'LONG', slippage_multiplier=slip_factor)
                    budget = min(cash, max(0, equity) * allocation / 100 * 0.2)
                    quantity = entry_quantity(module, execution, budget, equity, signal.get('stop'), cost_multiplier=fee_factor)
                    if quantity <= 0:
                        decisions['insufficient_risk_or_cash_budget'] += 1
                    else:
                        fee = costs(module, execution, quantity, fee_factor)
                        position = {'opened_at': now.isoformat(), 'price': execution, 'quantity': quantity,
                                    'stop': signal.get('stop'), 'collateral': execution * quantity, 'entry_fee': fee}
                        cash -= position['collateral'] + fee
                        consumed.add(key)
                        entries += 1
                        equity = mark(price)
        if equity <= initial * 0.9:
            paused = True
            circuit_at = circuit_at or now.isoformat()
        if position and equity > 0:
            max_utilization = max(max_utilization, position['collateral'] / equity * 100)
        snapshots.append({'time': now, 'equity': equity})
    metrics = performance(snapshots, initial, [trade['net_pnl'] for trade in closed])
    days = (quotes[-1]['time'] - quotes[0]['time']).total_seconds() / 86400
    target_equity = initial * (1 + target / 100) ** (days / 365)
    annual = metrics['annualized_return_pct']
    return {
        'scenario': name, 'starting_equity': initial, 'ending_equity': equity,
        'period_return_pct': (equity / initial - 1) * 100, **metrics,
        'observation_days': days, 'annualized_estimate_preliminary': days < 365,
        'target_cagr_pct': target, 'target_equity': target_equity,
        'target_equity_gap': equity - target_equity,
        'cagr_gap_percentage_points': annual - target if annual is not None else None,
        'entries': entries, 'open_positions': int(position is not None),
        'open_position': position, 'circuit_paused': paused, 'circuit_at': circuit_at,
        'maximum_observed_capital_utilization_pct': max_utilization,
        'decisions': dict(decisions), 'unfilled_pending_at_end': int(pending is not None),
        'trades': closed[-200:], 'trades_truncated': max(0, len(closed) - 200),
        'equity_curve': [{'time': row['time'].isoformat(), 'equity': row['equity']} for row in snapshots],
    }


def run_validation(payload, settings, allocation_pct, initial_balance, target_cagr_pct=18.5):
    """POST computation contract; caller enforces admin/auth/CSRF/body size.

    settings: the selected module's saved settings, never a strategy chosen
    through optimization. No writes or AI prompts are created by this function.
    """
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise ValueError('Historical input must be an object with schema_version: 1.')
    module = payload.get('module')
    if module not in ('equities', 'crypto'):
        raise ValueError('Replay currently supports equities and crypto only; other modules require separate datasets and validation.')
    symbol = str(payload.get('symbol') or '').strip().upper()
    if not symbol or len(symbol) > 24 or any(not (c.isalnum() or c in '.-/') for c in symbol):
        raise ValueError('Provide one valid symbol matching the imported historical data.')
    source = payload.get('source')
    if not isinstance(source, str) or not 3 <= len(source.strip()) <= 500:
        raise ValueError('Describe the historical source and timestamp/adjustment assumptions in source (3–500 characters).')
    if not isinstance(settings, dict):
        raise ValueError('Saved module settings are required.')
    # Reject pathological settings even if this helper is invoked outside its
    # production config-validation boundary.
    required = {'equities': ('trend_sma_days', 'rsi_period', 'rsi_entry_threshold', 'bollinger_std'),
                'crypto': ('entry_channel_periods', 'exit_channel_periods', 'atr_stop_multiplier')}[module]
    strategy = {key: finite(settings.get(key), key, 0.000001, 1000) for key in required}
    for key in ('trend_sma_days', 'rsi_period', 'entry_channel_periods', 'exit_channel_periods'):
        if key in strategy:
            if int(strategy[key]) != strategy[key]:
                raise ValueError(f'{key} must be an integer.')
            strategy[key] = int(strategy[key])
    initial = finite(initial_balance, 'initial_balance', 1, 1e9)
    allocation = finite(allocation_pct, 'allocation_pct', 0, 100)
    target = finite(target_cagr_pct, 'target_cagr_pct', 0, 100)
    raw = {}
    for name in ('bars', 'benchmark_bars', 'quotes', 'dominance_observations'):
        required_rows = name in ('bars', 'quotes') or name == 'benchmark_bars' and module == 'equities'
        limit = MAX_QUOTES if name == 'quotes' else MAX_BARS
        raw[name] = _ordered([{**row, 'time': _time(row.get('time'), f'{name} time')}
                              for row in _rows(payload.get(name, []), name, limit, required_rows)], name)
    for row in raw['quotes']:
        row['price'] = finite(row.get('price'), 'quote price', 0.000001)
    if len(raw['quotes']) < 4:
        raise ValueError('At least four historical quote observations are required.')
    start = _time(payload.get('evaluation_start'), 'evaluation_start')
    split = _time(payload.get('split_at'), 'split_at')
    if start >= split:
        raise ValueError('evaluation_start must precede split_at.')
    windows = {'development': [row for row in raw['quotes'] if start <= row['time'] < split],
               'held_out': [row for row in raw['quotes'] if row['time'] >= split]}
    if any(len(rows) < 2 for rows in windows.values()):
        raise ValueError('Both development and held-out windows require at least two quote observations.')
    sessions = _session_calendar(module, raw['bars'], raw['benchmark_bars'], raw['quotes'])
    histories = {}
    for name, input_name in (('bars', 'bars'), ('benchmark', 'benchmark_bars')):
        bars = _bars(raw[input_name], module, sessions)
        histories[name] = {'bars': bars, 'available': [row['available_at'] for row in bars]}
    dominance = {'rows': raw['dominance_observations'], 'times': [], 'days': {}}
    for row in dominance['rows']:
        row['value'] = finite(row.get('value'), 'dominance value', 0.01, 100)
        dominance['times'].append(row['time'])
        dominance['days'].setdefault(row['time'].date(), []).append(row)
    outcomes = {}
    for window, quotes in windows.items():
        outcomes[window] = {
            'label': 'Development evaluation' if window == 'development' else 'Chronologically held-out evaluation',
            'start': quotes[0]['time'].isoformat(), 'end': quotes[-1]['time'].isoformat(),
            'quote_observations': len(quotes),
            'scenarios': [_replay(module, symbol, quotes, histories, strategy, dominance, sessions,
                                  initial, allocation, target, scenario) for scenario in SCENARIOS],
        }
    return {
        'schema_version': 1, 'scope': 'single_symbol_historical_replay', 'module': module, 'symbol': symbol,
        'source': source.strip(), 'source_verified': False, 'saved_parameters': strategy,
        'allocation_pct': allocation, 'target_cagr_pct': target, 'windows': outcomes,
        'coverage': {name: ('replayed_single_symbol_only' if name == module else 'NOT_VALIDATED')
                     for name in ('equities', 'crypto', 'options', 'futures', 'events')},
        'assumptions': [
            'Imported historical provenance, quote accuracy, split/dividend adjustments, and survivorship are declared by the uploader, not independently verified.',
            'Each quote is a scan observation. Only bars completed and available by that timestamp enter the unchanged saved signal rules. Intrabar moves between quotes are unobserved.',
            'Development and held-out windows use the same saved parameters and separate fresh paper ledgers. Earlier history is indicator warm-up only; no automated threshold optimization occurs.',
            'Held-out means chronological separation only. Repeated inspection or parameter changes can contaminate a holdout; this tool cannot certify unseen data.',
            'The module retains its configured allocation and 20% bucket position cap; all other capital is idle cash. This is not a blended-portfolio CAGR forecast or validation.',
            'Paper baseline assumes 10 basis points commission each side and 5 basis points adverse slippage each side, 0.5% initial stop-risk sizing, one position per symbol and one entry per ET date.',
            'The 10% starting-bankroll floor pauses new entries, while marking and exits continue. Stops execute at the next observed price, not at a guaranteed stop price.',
            'Stress scenarios independently double commissions/slippage, delay entries one quote with revalidation, or reject every second entry attempt. These are sensitivity tests, not estimated fill probabilities.',
            'No market-depth, funding, borrowing, taxes, partial-fill, corporate-action, or tick-level latency model. Open positions remain marked at the final observed quote, without artificial liquidation.',
            'Options, futures, event settlements, multi-symbol contention, cross-module correlation, and full-portfolio risk are not validated by this replay.',
            'Results do not change settings or trades and are not evidence of achieving 18.5% CAGR. Annualization is unavailable below 30 days and preliminary below one year.',
        ],
    }
