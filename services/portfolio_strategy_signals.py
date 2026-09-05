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


@lru_cache(maxsize=32)
def session_bounds(day):
    import pandas_market_calendars as calendars
    schedule = calendars.get_calendar('NYSE').schedule(start_date=day, end_date=day)
    if schedule.empty:
        return None
    row = schedule.iloc[0]
    return row.market_open.to_pydatetime(), row.market_close.to_pydatetime()


def in_session(now):
    bounds = session_bounds(utc(now).astimezone(ET).date())
    return bool(bounds and bounds[0] <= utc(now) < bounds[1])


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
    return 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain/loss)


def atr(bars, period=14):
    if len(bars) <= period:
        raise ValueError('Insufficient ATR history.')
    ranges = [max(b['high']-b['low'], abs(b['high']-a['close']), abs(b['low']-a['close'])) for a, b in zip(bars, bars[1:])]
    return sum(ranges[-period:]) / period


def equity_signal(bars, price, settings, benchmark):
    n = settings['trend_sma_days']
    if len(bars) < max(n, 64, settings['rsi_period'] + 1) or len(benchmark) < 64:
        raise ValueError('Insufficient completed daily history for trend and relative momentum.')
    closes = [b['close'] for b in bars]
    momentum = closes[-1] / closes[-64] - 1
    relative = momentum - (benchmark[-1]['close'] / benchmark[-64]['close'] - 1)
    average = sum(closes[-n:]) / n
    pullback = rsi(closes, settings['rsi_period'])
    deviation = math.sqrt(sum((x-sum(closes[-20:])/20)**2 for x in closes[-20:])/20)
    lower = sum(closes[-20:])/20 - settings['bollinger_std'] * deviation
    return {'enter': price > average and momentum > 0 and relative >= 0 and pullback < settings['rsi_entry_threshold'] and closes[-1] <= lower,
            'exit': price < average or pullback > 70, 'stop': price - 2 * atr(bars),
            'reason': f'RSI {pullback:.1f}, 63-session relative momentum {relative:.4f}', 'side': 'LONG'}


def crypto_signal(bars, price, settings, dominance_ok):
    entry, leave = settings['entry_channel_periods'], settings['exit_channel_periods']
    if len(bars) < max(entry, leave, 15):
        raise ValueError('Insufficient completed hourly channel history.')
    # The live quote is compared with prior completed bars, never its own high.
    return {'enter': dominance_ok and price > max(b['high'] for b in bars[-entry:]),
            'exit': price < min(b['low'] for b in bars[-leave:]),
            'stop': price - settings['atr_stop_multiplier'] * atr(bars), 'side': 'LONG',
            'reason': 'Donchian breakout with measured dominance regime'}


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


def select_credit_spread(contracts, price, iv_rank, settings, now):
    if iv_rank is None or iv_rank < settings['min_ivr']:
        raise ValueError('IV rank is unavailable, warming up, or below the entry threshold.')
    today = utc(now).astimezone(ET).date()
    candidates = []
    for short in contracts:
        try:
            strike = finite(short['strike'], 'strike', 0.000001)
            delta = finite(abs(float(short['delta'])), 'absolute delta', 0.01, 0.5)
            dte = (datetime.fromisoformat(short['expiration']).date()-today).days
            kind = short['option_type']
            if kind not in ('PUT', 'CALL') or not 20 <= dte <= 65:
                continue
            if (kind == 'PUT' and strike >= price) or (kind == 'CALL' and strike <= price):
                continue
            for long in contracts:
                if long['expiration'] != short['expiration'] or long['option_type'] != kind:
                    continue
                width = strike-float(long['strike']) if kind == 'PUT' else float(long['strike'])-strike
                credit = float(short['bid'])-float(long['ask'])
                if width <= 0 or not 0 < credit < width:
                    continue
                candidates.append((abs(dte-settings['target_dte']), abs(delta-settings['target_delta']/100), width,
                                   {'short': short, 'long': long, 'credit': credit, 'width': width, 'expiration': short['expiration']}))
        except (KeyError, ValueError, TypeError):
            continue
    if not candidates:
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
