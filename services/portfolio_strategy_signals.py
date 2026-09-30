"""Pure, deterministic paper-strategy calculations; no broker execution imports."""
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
MODULES = ('equities', 'options', 'crypto', 'futures', 'events')
TYPES = dict(zip(MODULES, ('EQUITY', 'OPTION', 'CRYPTO', 'FUTURES', 'EVENT')))


def finite(value, name='value', minimum=0, maximum=1e12):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a finite number.')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a finite number.') from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}.')
    return number


def utc(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).isdigit()):
        stamp = float(value)
        return datetime.fromtimestamp(stamp / 1000 if stamp > 1e11 else stamp, timezone.utc)
    return utc(datetime.fromisoformat(str(value).replace('Z', '+00:00')))


@lru_cache(maxsize=24)
def _year_session_bounds(year):
    """Build each exchange year once instead of rebuilding holidays per bar."""
    import pandas_market_calendars as calendars
    schedule = calendars.get_calendar('NYSE').schedule(start_date=f'{year}-01-01', end_date=f'{year}-12-31')
    return {index.date(): (row.market_open.to_pydatetime(), row.market_close.to_pydatetime())
            for index, row in schedule.iterrows()}


@lru_cache(maxsize=4096)
def session_bounds(day):
    return _year_session_bounds(day.year).get(day)

from services.market_calendar_service import is_regular_market_hours

def in_session(now):
    return is_regular_market_hours(utc(now))


def fresh_quote(quote, now, seconds=120):
    price = finite(quote.get('price'), 'quote price', 0.000001)
    try:
        age = (utc(now) - utc(quote.get('as_of'))).total_seconds()
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Quote timestamp is missing or invalid.') from None
    if not -5 <= age <= seconds:
        raise ValueError('Quote is stale or from the future.')
    return price


def completed_bars(rows, now, *, daily=False, seconds=60, crypto=False):
    """Exclude forming candles. Daily US bars end at the actual session close."""
    result = {}
    for row in rows:
        stamp = utc(row['time'])
        if daily and not crypto:
            # Providers label daily bars at UTC midnight or the local session open.
            day = stamp.date() if stamp.hour == 0 else stamp.astimezone(ET).date()
            bounds = session_bounds(day)
            end = bounds[1] if bounds else utc(now) + timedelta(days=1)
        else:
            end = stamp + timedelta(seconds=86400 if daily else seconds)
        if end > utc(now):
            continue
        clean = {key: finite(row[key], key, 0.000001) for key in ('open', 'high', 'low', 'close')}
        clean['volume'] = finite(row.get('volume', 0), 'volume')
        clean['time'] = stamp.timestamp()
        if clean['low'] > min(clean['open'], clean['close']) or clean['high'] < max(clean['open'], clean['close']):
            raise ValueError('Invalid OHLC candle.')
        result[stamp] = clean
    return [result[key] for key in sorted(result)]


def rsi(closes, period=2):
    if len(closes) <= period:
        raise ValueError('Insufficient RSI history.')
    changes = [b-a for a, b in zip(closes, closes[1:])]
    gain = sum(max(0, x) for x in changes[:period]) / period
    loss = sum(max(0, -x) for x in changes[:period]) / period
    for change in changes[period:]:
        gain = (gain * (period-1) + max(0, change)) / period
        loss = (loss * (period-1) + max(0, -change)) / period
    
    # Handle flat/monotonic windows safely
    if gain == 0 and loss == 0:
        return 50.0
    if loss == 0:
        return 100.0
    if gain == 0:
        return 0.0
        
    rs = gain / loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(bars, period=14):
    if len(bars) <= period:
        raise ValueError('Insufficient ATR history.')
    ranges = [max(b['high']-b['low'], abs(b['high']-a['close']), abs(b['low']-a['close'])) for a, b in zip(bars, bars[1:])]
    return sum(ranges[-period:]) / period


def equity_rotation_scores(histories, benchmark, settings):
    """Rank only completed-session trends using the same SPY observation."""
    if len(benchmark) < 64:
        raise ValueError('SPY requires 64 completed daily bars.')
    spy_momentum = benchmark[-1]['close'] / benchmark[-64]['close'] - 1
    ranked = []
    n = settings['trend_sma_days']
    for symbol, bars in histories.items():
        if len(bars) < max(n, 64):
            continue
        closes = [row['close'] for row in bars]
        momentum = closes[-1] / closes[-64] - 1
        relative = momentum - spy_momentum
        average = sum(closes[-n:]) / n
        if closes[-1] > average and momentum > 0 and relative >= 0:
            ranked.append((symbol, relative, momentum))
    ranked.sort(key=lambda row: (-row[1], -row[2], row[0]))
    return {symbol: index + 1 for index, (symbol, _, _) in enumerate(ranked)}


def equity_signal(bars, price, settings, benchmark, rotation_rank=None):
    n = settings['trend_sma_days']
    if len(bars) < max(n, 64, settings['rsi_period'] + 1, 21) or len(benchmark) < 64:
        raise ValueError('Insufficient completed daily history for trend and relative momentum.')
    closes = [b['close'] for b in bars]
    momentum = closes[-1] / closes[-64] - 1
    relative = momentum - (benchmark[-1]['close'] / benchmark[-64]['close'] - 1)
    average = sum(closes[-n:]) / n
    pullback = rsi(closes, settings['rsi_period'])
    middle = sum(closes[-20:]) / 20
    deviation = math.sqrt(sum((x-middle)**2 for x in closes[-20:]) / 20)
    lower = middle - settings['bollinger_std'] * deviation
    trend = closes[-1] > average and momentum > 0
    rotation = trend and relative >= 0 and rotation_rank is not None and rotation_rank <= 2
    reversal = trend and pullback < settings['rsi_entry_threshold'] and closes[-1] <= lower
    setup = 'TREND_ROTATION_V1' if rotation else 'TREND_PULLBACK_V1' if reversal else None
    return {'enter': bool(setup), 'setup': setup,
            'checks': {'completed_daily_bars': len(bars), 'trend_sma': average,
                       'completed_close_above_sma': closes[-1] > average,
                       'current_price_above_sma': price > average,
                       'momentum_63_sessions': momentum, 'relative_momentum_vs_spy': relative,
                       'rotation_rank': rotation_rank, 'rotation_top_two': bool(rotation),
                       'rsi': pullback, 'rsi_below_entry_threshold': pullback < settings['rsi_entry_threshold'],
                       'lower_bollinger_band': lower, 'close_below_lower_band': closes[-1] <= lower,
                       'pullback_qualified': bool(reversal)},
            'exit': price < average or pullback > 70,
            'stop': price - 2 * atr(bars),
            'reason': (setup or f'No trend rotation or pullback setup; RSI {pullback:.1f}, relative momentum {relative:.4f}'),
            'side': 'LONG', 'completed_bar_time': bars[-1].get('time')}


def realized_volatility(bars, sessions=20):
    if len(bars) <= sessions:
        raise ValueError(f'{sessions + 1} completed underlying bars are required.')
    closes = [finite(row['close'], 'underlying close', 0.000001) for row in bars[-sessions-1:]]
    returns = [math.log(right / left) for left, right in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean)**2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance * 252)


def option_regime(bars, price, current_iv, rank_30=None, rank_252=None, min_ivr=40):
    if len(bars) < 61:
        raise ValueError('61 completed underlying bars are required for option trend and volatility.')
    iv = finite(current_iv, 'current ATM IV', 0.000001, 10)
    rv20, rv60 = realized_volatility(bars, 20), realized_volatility(bars, 60)
    closes = [row['close'] for row in bars]
    trend = closes[-1] / closes[-21] - 1
    average = sum(closes[-50:]) / 50
    kind = 'PUT' if trend > 0 and closes[-1] > average else 'CALL' if trend < 0 and closes[-1] < average else None
    basis = 'ANNUAL_IV_RANK_252' if rank_252 is not None else 'SHORT_IV_PERCENTILE_30' if rank_30 is not None else 'CURRENT_IV_VS_REALIZED_VOL'
    ready = bool(kind and (rank_252 >= min_ivr if rank_252 is not None else rank_30 >= min_ivr if rank_30 is not None else iv >= 1.05 * rv20))
    return {'enter': ready, 'option_type': kind, 'basis': basis,
            'checks': {'underlying_bars': len(bars), 'trend_20_sessions': trend,
                       'underlying_sma_50': average, 'rv_20': rv20, 'rv_60': rv60,
                       'current_atm_iv': iv, 'short_iv_percentile_30': rank_30,
                       'annual_iv_rank_252': rank_252, 'direction': kind,
                       'current_iv_above_1_05x_rv20': iv >= 1.05 * rv20},
            'reason': basis if ready else 'No aligned underlying trend and eligible volatility regime.'}


def crypto_signal(bars, price, settings, dominance_ok):
    entry, leave = settings['entry_channel_periods'], settings['exit_channel_periods']
    if len(bars) < max(entry, leave, 15):
        raise ValueError('Insufficient completed hourly channel history.')
    # The live quote is compared with prior completed bars, never its own high.
    upper = max(b['high'] for b in bars[-entry:])
    volatility = atr(bars)
    return {'enter': dominance_ok and price > upper,
            'checks': {'completed_hourly_bars': len(bars), 'entry_channel_high': upper,
                       'price_above_entry_channel': price > upper, 'dominance_gate_passed': bool(dominance_ok),
                       'atr_period': 14, 'atr': volatility},
            'exit': price < min(b['low'] for b in bars[-leave:]),
            'stop': price - settings['atr_stop_multiplier'] * volatility, 'side': 'LONG',
            'reason': ('Breakout and dominance gates passed.' if dominance_ok and price > upper else
                       'Price has not exceeded the completed-bar Donchian high.' if price <= upper else
                       'Altcoin dominance gate did not pass.')}


def futures_signal(bars, price, settings, now):
    bounds = session_bounds(utc(now).astimezone(ET).date())
    if not bounds:
        raise ValueError('US cash session is closed.')
    start, end = bounds
    minutes = settings['opening_range_minutes']
    opening_end = start + timedelta(minutes=minutes)
    session = [b for b in bars if start.timestamp() <= b['time'] < end.timestamp()]
    opening = [b for b in session if b['time'] < opening_end.timestamp()]
    if utc(now) < opening_end or len({int(b['time']//60) for b in opening}) != minutes:
        raise ValueError('Opening range is incomplete; every one-minute candle is required.')
    volume = sum(b['volume'] for b in session)
    if volume <= 0:
        raise ValueError('VWAP requires positive session volume.')
    vwap = sum((b['high']+b['low']+b['close'])/3*b['volume'] for b in session)/volume
    high, low = max(b['high'] for b in opening), min(b['low'] for b in opening)
    long, short = price > high and price > vwap, price < low and price < vwap
    side = 'SHORT' if short else 'LONG'
    return {'enter': (long or short) and utc(now) < end-timedelta(minutes=15),
            'exit': utc(now) >= end-timedelta(minutes=5), 'side': side,
            'stop': high if short else low, 'vwap': vwap, 'session_end': end.isoformat(),
            'reason': 'Opening range breakout with directional VWAP confirmation'}


def select_credit_spread(contracts, price, iv_rank, settings, now, *, allow_warmup=False, preferred_kind=None):
    if not allow_warmup and (iv_rank is None or iv_rank < settings['min_ivr']):
        raise ValueError('IV rank is unavailable, warming up, or below the entry threshold.')
    today = utc(now).astimezone(ET).date()
    candidates = []
    missing_depth = False
    for short in contracts:
        try:
            strike = finite(short['strike'], 'strike', 0.000001)
            delta = finite(abs(float(short['delta'])), 'absolute delta', 0.01, 0.5)
            dte = (datetime.fromisoformat(short['expiration']).date()-today).days
            kind = short['option_type']
            if kind not in ('PUT', 'CALL') or (preferred_kind and kind != preferred_kind) or not 20 <= dte <= 65:
                continue
            if (kind == 'PUT' and strike >= price) or (kind == 'CALL' and strike <= price):
                continue
            for long in contracts:
                if long['expiration'] != short['expiration'] or long['option_type'] != kind:
                    continue
                width = strike-float(long['strike']) if kind == 'PUT' else float(long['strike'])-strike
                credit = float(short['bid'])-float(long['ask'])
                if width <= 0 or not 0 < credit < width or credit * 100 <= 2.60:
                    continue
                depth = (short.get('bid_size'), long.get('ask_size'))
                if any(value is None or float(value) < 1 for value in depth):
                    missing_depth = True
                    continue
                candidates.append((abs(dte-settings['target_dte']), abs(delta-settings['target_delta']/100), width,
                                   {'short': short, 'long': long, 'credit': credit, 'width': width, 'expiration': short['expiration']}))
        except (KeyError, ValueError, TypeError):
            continue
    if not candidates:
        if missing_depth:
            raise ValueError('No reported two-leg option depth.')
        raise ValueError('No quoted, defined-risk OTM spread with provider Greeks.')
    return min(candidates, key=lambda item: item[:3])[3]


def performance(snapshots, initial, closed_pnls):
    """Calendar-day returns (365 days for a portfolio including 24/7 crypto)."""
    ordered = sorted(snapshots, key=lambda s: s['time'])
    daily = {}
    peak, drawdown = initial, 0.0
    for item in ordered:
        peak = max(peak, item['equity'])
        drawdown = max(drawdown, (peak-item['equity'])/peak if peak else 0)
        daily[utc(item['time']).date()] = item['equity']
    returns = []
    days = sorted(daily)
    for previous, current in zip(days, days[1:]):
        # Do not pretend a multi-day collection gap is a daily return.
        if (current-previous).days == 1 and daily[previous] > 0:
            returns.append(daily[current]/daily[previous]-1)
    annual = sharpe = sortino = None
    span = (utc(ordered[-1]['time'])-utc(ordered[0]['time'])).total_seconds()/86400 if len(ordered)>1 else 0
    if span >= 30 and initial > 0 and ordered[-1]['equity'] > 0:
        exponent = math.log(ordered[-1]['equity']/initial)*365/span
        annual = math.expm1(exponent)*100 if abs(exponent)<700 else None
    if len(returns) >= 30:
        mean = sum(returns)/len(returns)
        std = math.sqrt(sum((r-mean)**2 for r in returns)/(len(returns)-1))
        downside = math.sqrt(sum(min(r, 0)**2 for r in returns)/len(returns))
        sharpe = mean/std*math.sqrt(365) if std else None
        sortino = mean/downside*math.sqrt(365) if downside else None
    return {'annualized_return_pct': annual, 'sharpe': sharpe, 'sortino': sortino,
            'max_drawdown_pct': drawdown*100, 'win_rate_pct': sum(p>0 for p in closed_pnls)/len(closed_pnls)*100 if closed_pnls else None,
            'closed_trades': len(closed_pnls), 'daily_return_samples': len(returns), 'risk_free_rate': 0}
