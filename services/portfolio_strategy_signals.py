"""Pure, deterministic paper-strategy calculations; no broker execution imports."""
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
MODULES = ('equities', 'options', 'crypto', 'futures', 'events')
TYPES = dict(zip(MODULES, ('EQUITY', 'OPTION', 'CRYPTO', 'FUTURES', 'EVENT')))
# The overbought exit uses a standard 14-period oscillator. It is deliberately
# decoupled from the configured entry RSI period.
EXIT_RSI_PERIOD = 14
# A 20-session trend smaller than this is noise, not direction; trading credit
# spreads against it flips PUT/CALL on every scan and only pays friction.
DIRECTION_CONFIRMATION_BAND = 0.02
CRYPTO_TREND_SMA_PERIODS = 20
# Breakouts in a flat tape are almost always false; require hourly range
# activity of at least this fraction of price before a Donchian entry counts.
CRYPTO_MIN_ATR_FRACTION = 0.0025
EQUITY_REGIME_SMA_SESSIONS = 50
# Composite watchlist regime weights: index ETFs carry higher weight than
# single-name stocks so one index cannot freeze the book while broad leaders
# remain constructive, yet broad index deterioration is still respected.
INDEX_ETF_WEIGHTS = {'SPY': 2.5, 'QQQ': 2.5, 'IWM': 2.0, 'SMH': 2.0}
REGIME_HEALTHY_BREADTH = 0.55
REGIME_PULLBACK_BREADTH = 0.30
MARKET_STATES = ('bottoming', 'still_falling', 'topping', 'still_rising', 'neutral')


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
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(0, x) for x in changes[:period]) / period
    loss = sum(max(0, -x) for x in changes[:period]) / period
    for change in changes[period:]:
        gain = (gain * (period - 1) + max(0, change)) / period
        loss = (loss * (period - 1) + max(0, -change)) / period

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
    ranges = [max(b['high'] - b['low'], abs(b['high'] - a['close']), abs(b['low'] - a['close']))
              for a, b in zip(bars, bars[1:])]
    return sum(ranges[-period:]) / period


def classify_market_state(bars, price=None):
    """Classify per-symbol market state from stored OHLCV history.

    Evaluates trend direction/slope, drawdown depth from recent swing highs,
    volatility expansion/contraction (short vs. long ATR), and volume behavior
    (selling climax, drying-up volume, turn accumulation, distribution).

    Returns one of: ``bottoming``, ``still_falling``, ``topping``,
    ``still_rising``, ``neutral``.
    """
    if not bars or len(bars) < 20:
        return {
            'state': 'neutral',
            'confidence': 0.0,
            'drawdown_pct': 0.0,
            'rebound_from_low_pct': 0.0,
            'slope_fast': 0.0,
            'recent_ret_5': 0.0,
            'recent_ret_20': 0.0,
            'extension_from_sma20': 0.0,
            'atr_ratio': 1.0,
            'rsi_14': 50.0,
            'volume_state': 'unavailable',
            'holding_base': False,
            'making_lower_lows': False,
            'rollover': False,
            'collapse': False,
            'reason': 'Insufficient history for market-state classification.',
        }

    norm_bars = [
        {
            'open': float(b.get('open', b['close'])),
            'high': float(b.get('high', b['close'])),
            'low': float(b.get('low', b['close'])),
            'close': float(b['close']),
            'volume': float(b.get('volume') or 0.0),
        }
        for b in bars
    ]
    bars = norm_bars
    closes = [b['close'] for b in bars]
    curr = float(price) if price is not None else closes[-1]
    lookback = min(len(bars), 60)
    window = bars[-lookback:]

    sma_fast = sum(closes[-10:]) / 10.0
    sma_slow = sum(closes[-20:]) / 20.0
    prev_fast_slice = closes[-15:-5] if len(closes) >= 15 else closes[:10]
    prev_sma_fast = sum(prev_fast_slice) / len(prev_fast_slice)
    slope_fast = (sma_fast - prev_sma_fast) / prev_sma_fast if prev_sma_fast > 0 else 0.0

    recent_ret_5 = (curr / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] > 0 else 0.0
    recent_ret_20 = (curr / closes[-21] - 1.0) if len(closes) >= 21 and closes[-21] > 0 else (curr / closes[0] - 1.0)
    extension_from_sma20 = (curr - sma_slow) / sma_slow if sma_slow > 0 else 0.0

    swing_high = max(float(b['high']) for b in window)
    swing_low = min(float(b['low']) for b in window)
    drawdown_pct = (curr - swing_high) / swing_high if swing_high > 0 else 0.0
    rebound_from_low_pct = (curr - swing_low) / swing_low if swing_low > 0 else 0.0

    recent_low_5 = min(float(b['low']) for b in bars[-5:])
    prior_low_15 = min(float(b['low']) for b in bars[-20:-5])
    prior_low_10 = min(float(b['low']) for b in bars[-10:])
    making_lower_lows = (recent_low_5 < prior_low_15 * 0.995) or (curr < prior_low_10 * 0.995)
    holding_base = (recent_low_5 >= prior_low_15 * 0.985) and (curr >= recent_low_5 * 1.003)

    atr_short = atr(bars, 5)
    atr_long = atr(bars, 14)
    atr_ratio = (atr_short / atr_long) if atr_long > 0 else 1.0
    vol_expanding = atr_ratio >= 1.25
    vol_contracting = atr_ratio <= 0.95

    rsi_series = closes + ([curr] if abs(curr - closes[-1]) > 1e-12 else [])
    rsi_14 = rsi(rsi_series, 14) if len(rsi_series) > 14 else 50.0
    prev_rsi_14 = rsi(closes[:-1], 14) if len(closes) > 15 else rsi_14
    rsi_turning_up = rsi_14 > prev_rsi_14 + 0.5

    # Volume behavior analysis (gracefully degrades when bars carry zero volume)
    vol_window = bars[-20:]
    vols = [float(b.get('volume') or 0.0) for b in vol_window]
    total_vol = sum(vols)
    prior_down_climax = False
    selling_climax_now = False
    volume_drying_up = False
    turn_volume = False
    if total_vol > 0:
        avg_vol = total_vol / len(vols)
        last_bar = bars[-1]
        last_open = float(last_bar.get('open', last_bar['close']))
        last_close = float(last_bar['close'])
        last_vol = float(last_bar.get('volume') or 0.0)
        last3_vol = sum(float(b.get('volume') or 0.0) for b in bars[-3:]) / 3.0
        prior_down_climax = any(
            float(b.get('volume') or 0.0) >= 1.45 * avg_vol and float(b['close']) < float(b.get('open', b['close']))
            for b in bars[-12:-2]
        )
        selling_climax_now = (
            (last_close < last_open or curr < closes[-2])
            and last_vol >= 1.40 * avg_vol
        )
        volume_drying_up = last3_vol <= 0.85 * avg_vol
        recent_up = [float(b.get('volume') or 0.0) for b in bars[-5:] if float(b['close']) >= float(b.get('open', b['close']))]
        recent_down = [float(b.get('volume') or 0.0) for b in bars[-5:] if float(b['close']) < float(b.get('open', b['close']))]
        up_dominates = bool(recent_up) and (sum(recent_up) / len(recent_up)) > (sum(recent_down) / len(recent_down) if recent_down else 0.0) * 1.15
        turn_volume = (curr >= last_open and last_vol >= 1.15 * avg_vol) or (curr > closes[-2] and up_dominates)
        distribution_now = (
            drawdown_pct >= -0.04
            and (last_close < last_open or curr < last_close)
            and last_vol >= 1.35 * avg_vol
        )
        if selling_climax_now:
            volume_state = 'climax_selling'
        elif distribution_now:
            volume_state = 'distribution'
        elif turn_volume:
            volume_state = 'turn_accumulation'
        elif volume_drying_up:
            volume_state = 'drying_up'
        else:
            volume_state = 'normal'
    else:
        volume_state = 'unavailable'
        distribution_now = False

    # Sustained multi-bar weakness vs. single-bar pullback inside an uptrend
    down_bars_5 = sum(1 for a, b in zip(closes[-6:-1], closes[-5:]) if b < a)
    sustained_selling = down_bars_5 >= 3 or (down_bars_5 >= 2 and closes[-1] < closes[-3] and recent_ret_5 <= -0.03)

    # Collapse / falling-knife detector (distinguishes ongoing crash & dead-cat bounce from real bottom)
    downward_trend = curr < sma_fast and sma_fast < sma_slow and slope_fast < -0.005
    dead_cat_bounce = (
        drawdown_pct <= -0.06
        and curr < sma_slow
        and slope_fast < -0.012
        and vol_expanding
        and sustained_selling
        and (not holding_base or selling_climax_now)
    )
    active_breakdown = (
        downward_trend
        and sustained_selling
        and (making_lower_lows or selling_climax_now or (vol_expanding and recent_ret_5 <= -0.025))
    )
    collapse = (
        drawdown_pct <= -0.08
        and curr < sma_slow
        and sustained_selling
        and (
            (making_lower_lows and (vol_expanding or recent_ret_5 <= -0.035))
            or (selling_climax_now and recent_ret_5 <= -0.035)
        )
    )

    # Top / overextension detector: requires multi-bar completed-bar stretch
    # (not a fresh first-bar breakout out of a flat consolidation base).
    completed_ext = (closes[-1] - sma_slow) / sma_slow if sma_slow > 0 else 0.0
    up_bars_5 = sum(1 for a, b in zip(closes[-6:-1], closes[-5:]) if b > a)
    sustained_rally = completed_ext >= 0.04 and (up_bars_5 >= 3 or recent_ret_20 >= 0.08)
    overextended = sustained_rally and ((extension_from_sma20 >= 0.08 and rsi_14 >= 70.0) or (extension_from_sma20 >= 0.12))
    last_high = max(float(b['high']) for b in bars[-3:])
    rollover = (
        (curr < last_high * 0.985 and curr < closes[-2])
        or (rsi_14 < prev_rsi_14 - 1.0 and prev_rsi_14 >= 70.0)
        or distribution_now
    )
    topping_exhaustion = (
        (drawdown_pct >= -0.04 and overextended)
        or (sustained_rally and drawdown_pct >= -0.035 and rsi_14 >= 72.0 and extension_from_sma20 >= 0.05 and rollover)
    )

    # Bottom / basing detector (must show stabilization + turn confirmation)
    had_pullback = drawdown_pct <= -0.035 or min(rsi_14, prev_rsi_14) <= 38.0
    stabilized = holding_base and not making_lower_lows and not selling_climax_now and (vol_contracting or atr_ratio <= 1.15)
    completed_turn = closes[-1] > closes[-3] and closes[-1] >= closes[-2]
    turn_confirmed = (
        completed_turn
        and (curr > closes[-2] and curr >= closes[-1] * 0.999)
        and (rsi_turning_up or turn_volume or volume_drying_up or prior_down_climax)
    )
    not_crashing = recent_ret_5 >= -0.035 and curr >= closes[-3] * 0.995

    if active_breakdown or dead_cat_bounce or collapse:
        state = 'still_falling'
        conf = 0.60
        if making_lower_lows:
            conf += 0.15
        if vol_expanding:
            conf += 0.10
        if selling_climax_now or collapse:
            conf += 0.15
        reason = (
            'Active crash/collapse breakdown; avoid longs and evaluate exits.'
            if collapse else
            'Volatile dead-cat bounce inside downtrend; not a confirmed bottom.'
            if dead_cat_bounce else
            'Price making lower lows below declining averages; still falling.'
        )
    elif topping_exhaustion:
        state = 'topping'
        conf = 0.60 + (0.15 if rsi_14 >= 75.0 else 0.0) + (0.15 if rollover else 0.0) + (0.10 if distribution_now else 0.0)
        reason = (
            'Overextended near highs with momentum rollover/distribution; topping exit signal.'
            if rollover else
            'Stretched near recent highs (overextended); avoid chasing new entries.'
        )
    elif had_pullback and stabilized and turn_confirmed and not_crashing:
        state = 'bottoming'
        conf = 0.55
        if vol_contracting:
            conf += 0.12
        if turn_volume or prior_down_climax:
            conf += 0.15
        elif volume_drying_up:
            conf += 0.10
        if rsi_turning_up:
            conf += 0.10
        reason = (
            f'Confirmed base after {abs(drawdown_pct)*100:.1f}% drawdown '
            f'(ATR ratio {atr_ratio:.2f}, volume {volume_state}); turning higher.'
        )
    elif curr > sma_fast and sma_fast >= sma_slow * 0.995 and slope_fast > 0.001 and drawdown_pct > -0.05:
        state = 'still_rising'
        conf = 0.65 + (0.15 if curr > sma_slow and recent_ret_5 > 0 else 0.0)
        reason = 'Constructive uptrend above rising short and medium averages.'
    else:
        state = 'neutral'
        conf = 0.50
        reason = 'Balanced or range-bound price action with no strong bottom, top, or breakdown.'

    return {
        'state': state,
        'confidence': round(min(1.0, conf), 4),
        'drawdown_pct': round(drawdown_pct, 6),
        'rebound_from_low_pct': round(rebound_from_low_pct, 6),
        'slope_fast': round(slope_fast, 6),
        'recent_ret_5': round(recent_ret_5, 6),
        'recent_ret_20': round(recent_ret_20, 6),
        'extension_from_sma20': round(extension_from_sma20, 6),
        'atr_ratio': round(atr_ratio, 4),
        'rsi_14': round(rsi_14, 2),
        'volume_state': volume_state,
        'holding_base': bool(holding_base),
        'making_lower_lows': bool(making_lower_lows),
        'rollover': bool(rollover),
        'collapse': bool(collapse),
        'reason': reason,
    }


def compute_watchlist_regime(histories, watchlist=None, index_weights=None):
    """Build composite equities/ETF regime from the configured watchlist.

    Replaces the single-SPY 50-SMA switch with weighted breadth across the
    configured equities/ETFs watchlist, weighted toward index ETFs
    (SPY, QQQ, IWM, SMH). Returns three states:
      - ``healthy``      (size_multiplier=1.0, regime_ok=True)
      - ``pullback``     (size_multiplier=0.5, regime_ok=True)
      - ``falling_hard`` (size_multiplier=0.0, regime_ok=False)
    """
    weights_map = index_weights if index_weights is not None else INDEX_ETF_WEIGHTS
    symbols = list(watchlist) if watchlist is not None else list((histories or {}).keys())
    weighted_above = 0.0
    weighted_score = 0.0
    weighted_ret63 = 0.0
    total_weight = 0.0
    above_count = 0
    evaluated = 0
    members = {}

    for sym in symbols:
        bars = (histories or {}).get(sym)
        if not bars or len(bars) < EQUITY_REGIME_SMA_SESSIONS:
            continue
        closes = [float(b['close']) for b in bars]
        sma50 = sum(closes[-EQUITY_REGIME_SMA_SESSIONS:]) / EQUITY_REGIME_SMA_SESSIONS
        sma20 = sum(closes[-20:]) / 20.0
        above_sma50 = closes[-1] > sma50
        above_sma20 = closes[-1] > sma20
        ret20 = (closes[-1] / closes[-21] - 1.0) if len(closes) >= 21 and closes[-21] > 0 else 0.0
        ret63 = (closes[-1] / closes[-64] - 1.0) if len(closes) >= 64 and closes[-64] > 0 else ret20
        state_info = classify_market_state(bars, closes[-1])

        w = float(weights_map.get(str(sym).upper(), 1.0))
        member_score = 1.0 if above_sma50 else (0.50 if state_info['state'] == 'bottoming' else 0.35 if (above_sma20 and ret20 > -0.02) else 0.0)
        weighted_above += w if above_sma50 else 0.0
        weighted_score += w * member_score
        weighted_ret63 += w * ret63
        total_weight += w
        above_count += int(above_sma50)
        evaluated += 1
        members[sym] = {
            'weight': w,
            'above_sma50': above_sma50,
            'sma50': round(sma50, 4),
            'close': round(closes[-1], 4),
            'ret63': round(ret63, 6),
            'market_state': state_info['state'],
        }

    if total_weight <= 0 or evaluated == 0:
        return {
            'state': 'falling_hard',
            'regime_ok': False,
            'size_multiplier': 0.0,
            'weighted_breadth': 0.0,
            'composite_score': 0.0,
            'benchmark_momentum': 0.0,
            'evaluated_symbols': 0,
            'above_sma50_count': 0,
            'watchlist_size': len(symbols),
            'members': {},
            'reason': 'No configured watchlist equities had sufficient history for composite regime.',
        }

    weighted_breadth = weighted_above / total_weight
    composite_score = weighted_score / total_weight
    benchmark_momentum = weighted_ret63 / total_weight

    if weighted_breadth >= REGIME_HEALTHY_BREADTH or composite_score >= 0.60:
        state, size_mult, ok = 'healthy', 1.0, True
        reason = f'Composite watchlist regime healthy ({above_count}/{evaluated} above 50-SMA, weighted breadth {weighted_breadth:.0%}).'
    elif weighted_breadth >= REGIME_PULLBACK_BREADTH or composite_score >= 0.35:
        state, size_mult, ok = 'pullback', 0.5, True
        reason = f'Composite watchlist regime pullback ({above_count}/{evaluated} above 50-SMA, weighted breadth {weighted_breadth:.0%}); trading strongest/bottoming setups at half size.'
    else:
        state, size_mult, ok = 'falling_hard', 0.0, False
        reason = f'Composite watchlist regime falling_hard ({above_count}/{evaluated} above 50-SMA, weighted breadth {weighted_breadth:.0%}); defensive — no new longs.'

    return {
        'state': state,
        'regime_ok': ok,
        'size_multiplier': size_mult,
        'weighted_breadth': round(weighted_breadth, 4),
        'composite_score': round(composite_score, 4),
        'benchmark_momentum': benchmark_momentum,
        'evaluated_symbols': evaluated,
        'above_sma50_count': above_count,
        'watchlist_size': len(symbols),
        'members': members,
        'reason': reason,
    }


def compute_crypto_regime(histories, watchlist=None):
    """Build per-module crypto regime strictly from the configured crypto watchlist."""
    symbols = list(watchlist) if watchlist is not None else list((histories or {}).keys())
    above = 0
    bottoming_count = 0
    falling_count = 0
    evaluated = 0
    members = {}

    for sym in symbols:
        bars = (histories or {}).get(sym)
        if not bars or len(bars) < CRYPTO_TREND_SMA_PERIODS:
            continue
        closes = [float(b['close']) for b in bars]
        sma20 = sum(closes[-CRYPTO_TREND_SMA_PERIODS:]) / CRYPTO_TREND_SMA_PERIODS
        above_sma = closes[-1] > sma20
        ms = classify_market_state(bars, closes[-1])
        above += int(above_sma)
        bottoming_count += int(ms['state'] == 'bottoming')
        falling_count += int(ms['state'] == 'still_falling')
        evaluated += 1
        members[sym] = {
            'above_sma20h': above_sma,
            'market_state': ms['state'],
            'close': round(closes[-1], 4),
        }

    if evaluated == 0:
        return {
            'state': 'neutral',
            'regime_ok': True,
            'size_multiplier': 1.0,
            'breadth': 0.0,
            'evaluated_symbols': 0,
            'members': {},
        }

    breadth = above / evaluated
    if breadth >= 0.50:
        state, size_mult, ok = 'healthy', 1.0, True
    elif breadth > 0.0 or bottoming_count > 0 or falling_count < evaluated:
        state, size_mult, ok = 'pullback', 0.5, True
    else:
        state, size_mult, ok = 'falling_hard', 0.0, False

    return {
        'state': state,
        'regime_ok': ok,
        'size_multiplier': size_mult,
        'breadth': round(breadth, 4),
        'evaluated_symbols': evaluated,
        'bottoming_count': bottoming_count,
        'falling_count': falling_count,
        'members': members,
    }


def equity_rotation_scores(histories, benchmark, settings, *, watchlist=None, composite_regime=None):
    """Rank completed-session trends relative to the composite watchlist or benchmark."""
    if composite_regime is not None:
        ref_momentum = float(composite_regime.get('benchmark_momentum', 0.0))
    else:
        if len(benchmark) < 64:
            raise ValueError('SPY requires 64 completed daily bars.')
        ref_momentum = benchmark[-1]['close'] / benchmark[-64]['close'] - 1
    ranked = []
    n = settings['trend_sma_days']
    allowed = set(watchlist) if watchlist is not None else None
    for symbol, bars in histories.items():
        if allowed is not None and symbol not in allowed:
            continue
        if len(bars) < max(n, 64):
            continue
        closes = [row['close'] for row in bars]
        momentum = closes[-1] / closes[-64] - 1
        relative = momentum - ref_momentum
        average = sum(closes[-n:]) / n
        if closes[-1] > average and momentum > 0 and relative >= -1e-9:
            ranked.append((symbol, relative, momentum))
    ranked.sort(key=lambda row: (-row[1], -row[2], row[0]))
    return {symbol: index + 1 for index, (symbol, _, _) in enumerate(ranked)}


def equity_signal(bars, price, settings, benchmark, rotation_rank=None, *, composite_regime=None):
    n = settings['trend_sma_days']
    if len(bars) < max(n, 64, settings['rsi_period'] + 1, 21) or (composite_regime is None and len(benchmark) < 64):
        raise ValueError('Insufficient completed daily history for trend and relative momentum.')
    closes = [b['close'] for b in bars]
    momentum = closes[-1] / closes[-64] - 1
    if composite_regime is not None:
        ref_momentum = float(composite_regime.get('benchmark_momentum', 0.0))
    else:
        ref_momentum = benchmark[-1]['close'] / benchmark[-64]['close'] - 1
    relative = momentum - ref_momentum
    average = sum(closes[-n:]) / n
    pullback = rsi(closes, settings['rsi_period'])
    # The exit oscillator must not reuse the entry oscillator. A 2-period RSI
    # is a useful pullback trigger but a meaningless overbought threshold: it
    # reads above 70 in normal conditions and closed healthy trend positions
    # minutes after they were opened, turning the exit into pure fee churn.
    exit_rsi = rsi(closes, EXIT_RSI_PERIOD) if len(closes) > EXIT_RSI_PERIOD else pullback
    middle = sum(closes[-20:]) / 20
    deviation = math.sqrt(sum((x - middle) ** 2 for x in closes[-20:]) / 20)
    lower = middle - settings['bollinger_std'] * deviation

    if benchmark and len(benchmark) >= EQUITY_REGIME_SMA_SESSIONS:
        regime_average = sum(b['close'] for b in benchmark[-EQUITY_REGIME_SMA_SESSIONS:]) / EQUITY_REGIME_SMA_SESSIONS
        spy_above_50 = benchmark[-1]['close'] > regime_average
    else:
        regime_average = None
        spy_above_50 = None

    if composite_regime is not None:
        regime_state = composite_regime['state']
        regime_ok = bool(composite_regime['regime_ok'])
        size_multiplier = float(composite_regime.get('size_multiplier', 1.0))
    else:
        regime_ok = bool(spy_above_50)
        regime_state = 'healthy' if regime_ok else 'falling_hard'
        size_multiplier = 1.0 if regime_ok else 0.0

    market_state = classify_market_state(bars, price)
    ms_label = market_state['state']
    ms_blocks_entry = ms_label in ('still_falling', 'topping')

    trend = closes[-1] > average and momentum > 0
    max_rotation_rank = 1 if regime_state == 'pullback' else 2
    rotation = (
        trend and relative >= 0 and regime_ok and not ms_blocks_entry
        and rotation_rank is not None and rotation_rank <= max_rotation_rank
    )
    reversal = (
        trend and regime_ok and not ms_blocks_entry
        and pullback < settings['rsi_entry_threshold'] and closes[-1] <= lower
    )
    dip_entry = (
        regime_ok
        and ms_label == 'bottoming'
        and market_state['confidence'] >= 0.55
        and not market_state['collapse']
    )

    setup = (
        'TREND_ROTATION_V1' if rotation else
        'TREND_PULLBACK_V1' if reversal else
        'MARKET_STATE_BOTTOM_V1' if dip_entry else
        None
    )
    top_exit = (ms_label == 'topping' and market_state['rollover'])
    exit_flag = price < average or exit_rsi > 70 or top_exit
    exit_reason = 'EQUITY_TOP_EXIT' if (top_exit and not (price < average or exit_rsi > 70)) else ('STRATEGY_EXIT' if exit_flag else None)

    return {
        'enter': bool(setup),
        'setup': setup,
        'size_multiplier': size_multiplier,
        'checks': {
            'completed_daily_bars': len(bars),
            'trend_sma': average,
            'completed_close_above_sma': closes[-1] > average,
            'current_price_above_sma': price > average,
            'momentum_63_sessions': momentum,
            'relative_momentum_vs_spy': relative,
            'benchmark_sma_50': regime_average,
            'benchmark_regime_ok': regime_ok,
            'composite_regime_state': regime_state,
            'composite_regime_ok': regime_ok,
            'composite_weighted_breadth': composite_regime.get('weighted_breadth') if composite_regime else None,
            'size_multiplier': size_multiplier,
            'rotation_rank': rotation_rank,
            'rotation_top_two': bool(rotation),
            'rsi': pullback,
            'rsi_below_entry_threshold': pullback < settings['rsi_entry_threshold'],
            'exit_rsi': exit_rsi,
            'lower_bollinger_band': lower,
            'close_below_lower_band': closes[-1] <= lower,
            'pullback_qualified': bool(reversal),
            'dip_entry_qualified': bool(dip_entry),
            'market_state': ms_label,
            'market_state_confidence': market_state['confidence'],
            'market_state_drawdown_pct': market_state['drawdown_pct'],
            'market_state_atr_ratio': market_state['atr_ratio'],
            'market_state_volume': market_state['volume_state'],
            'market_state_reason': market_state['reason'],
        },
        'exit': exit_flag,
        'exit_reason': exit_reason,
        'stop': price - 2 * atr(bars),
        'reason': (
            setup or (
                f'Regime {regime_state}, market state {ms_label}; '
                f'RSI {pullback:.1f}, relative momentum {relative:.4f}'
            )
        ),
        'side': 'LONG',
        'completed_bar_time': bars[-1].get('time'),
    }


def realized_volatility(bars, sessions=20):
    if len(bars) <= sessions:
        raise ValueError(f'{sessions + 1} completed underlying bars are required.')
    closes = [finite(row['close'], 'underlying close', 0.000001) for row in bars[-sessions - 1:]]
    returns = [math.log(right / left) for left, right in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance * 252)


def option_regime(bars, price, current_iv, rank_30=None, rank_252=None, min_ivr=40):
    if len(bars) < 61:
        raise ValueError('61 completed underlying bars are required for option trend and volatility.')
    iv = finite(current_iv, 'current ATM IV', 0.000001, 10)
    rv20, rv60 = realized_volatility(bars, 20), realized_volatility(bars, 60)
    closes = [row['close'] for row in bars]
    trend = closes[-1] / closes[-21] - 1
    average = sum(closes[-50:]) / 50
    market_state = classify_market_state(bars, price)
    # A direction is only established once the 20-session trend clears the
    # confirmation band. Inside the band the trend is noise, and flipping
    # between PUT and CALL spreads on every scan only pays friction.
    kind = ('PUT' if trend > DIRECTION_CONFIRMATION_BAND and closes[-1] > average else
            'CALL' if trend < -DIRECTION_CONFIRMATION_BAND and closes[-1] < average else None)
    basis = ('ANNUAL_IV_RANK_252' if rank_252 is not None else
             'SHORT_IV_PERCENTILE_30' if rank_30 is not None else
             'CURRENT_IV_VS_REALIZED_VOL')
    ready = bool(kind and (rank_252 >= min_ivr if rank_252 is not None else rank_30 >= min_ivr if rank_30 is not None else iv >= 1.05 * rv20))
    return {'enter': ready, 'option_type': kind, 'basis': basis,
            'checks': {'underlying_bars': len(bars), 'trend_20_sessions': trend,
                       'underlying_sma_50': average, 'rv_20': rv20, 'rv_60': rv60,
                       'current_atm_iv': iv, 'short_iv_percentile_30': rank_30,
                       'annual_iv_rank_252': rank_252, 'direction': kind,
                       'direction_confirmation_band': DIRECTION_CONFIRMATION_BAND,
                       'trend_clears_confirmation_band': abs(trend) > DIRECTION_CONFIRMATION_BAND,
                       'current_iv_above_1_05x_rv20': iv >= 1.05 * rv20,
                       'market_state': market_state['state'],
                       'market_state_confidence': market_state['confidence']},
            'reason': basis if ready else 'No aligned underlying trend and eligible volatility regime.'}


def crypto_signal(bars, price, settings, dominance_ok, *, crypto_regime=None):
    entry, leave = settings['entry_channel_periods'], settings['exit_channel_periods']
    if len(bars) < max(entry, leave, CRYPTO_TREND_SMA_PERIODS, 15):
        raise ValueError('Insufficient completed hourly channel history.')
    # The live quote is compared with prior completed bars, never its own high.
    upper = max(b['high'] for b in bars[-entry:])
    exit_low = min(b['low'] for b in bars[-leave:])
    volatility = atr(bars)
    closes = [b['close'] for b in bars]
    trend_average = sum(closes[-CRYPTO_TREND_SMA_PERIODS:]) / CRYPTO_TREND_SMA_PERIODS
    trend_ok = price > trend_average
    atr_ok = volatility >= CRYPTO_MIN_ATR_FRACTION * price

    market_state = classify_market_state(bars, price)
    ms_label = market_state['state']
    regime_state = (crypto_regime or {}).get('state', 'healthy')
    regime_blocks_breakout = regime_state == 'falling_hard'
    size_multiplier = float((crypto_regime or {}).get('size_multiplier', 1.0))

    breakout_enter = (
        bool(dominance_ok)
        and price > upper
        and trend_ok
        and atr_ok
        and not regime_blocks_breakout
        and ms_label not in ('still_falling', 'topping')
    )
    dip_enter = (
        bool(dominance_ok)
        and atr_ok
        and ms_label == 'bottoming'
        and market_state['confidence'] >= 0.55
        and not market_state['collapse']
        and (not regime_blocks_breakout or market_state['confidence'] >= 0.75)
    )
    enter = breakout_enter or dip_enter
    if dip_enter and not breakout_enter and size_multiplier <= 0:
        size_multiplier = 0.5

    # Continuous sell-side evaluation: falls are actively evaluated for
    # collapse, trend break, or top rollover rather than merely skipping buys.
    channel_exit = price < exit_low
    trend_break_exit = (
        price < trend_average * 0.985
        and market_state['slope_fast'] < -0.005
        and price < closes[-1]
    )
    top_exit = (ms_label == 'topping' and market_state['rollover'])
    collapse_exit = (ms_label == 'still_falling' and market_state['collapse'])
    exit_flag = channel_exit or trend_break_exit or top_exit or collapse_exit
    exit_reason = (
        'CRYPTO_COLLAPSE_EXIT' if collapse_exit else
        'CRYPTO_TOP_EXIT' if top_exit else
        'CRYPTO_TREND_BREAK' if trend_break_exit else
        'STRATEGY_EXIT' if channel_exit else
        None
    )

    reason = (
        'Confirmed bottoming dip setup with stabilized volatility and volume.' if (dip_enter and not breakout_enter) else
        'Breakout, trend, volatility and dominance gates passed.' if breakout_enter else
        'Market-state classifier flagged falling knife or overextension.' if ms_label in ('still_falling', 'topping') else
        'Crypto watchlist regime is falling_hard; defensive stance.' if regime_blocks_breakout else
        'Price has not exceeded the completed-bar Donchian high and is not bottoming.' if price <= upper else
        'Price is below the 20-hour trend average.' if not trend_ok else
        'Hourly range is too flat for a breakout to be meaningful.' if not atr_ok else
        'Altcoin dominance gate did not pass.'
    )
    return {
        'enter': enter,
        'setup': 'DONCHIAN_DOMINANCE_V1' if breakout_enter else ('CRYPTO_BOTTOM_DIP_V1' if dip_enter else None),
        'size_multiplier': size_multiplier,
        'checks': {
            'completed_hourly_bars': len(bars),
            'entry_channel_high': upper,
            'exit_channel_low': exit_low,
            'price_above_entry_channel': price > upper,
            'dominance_gate_passed': bool(dominance_ok),
            'trend_sma_20h': trend_average,
            'price_above_trend_sma': trend_ok,
            'min_atr_fraction': CRYPTO_MIN_ATR_FRACTION,
            'atr_above_noise_floor': atr_ok,
            'atr_period': 14,
            'atr': volatility,
            'dip_entry_qualified': bool(dip_enter),
            'crypto_regime_state': regime_state,
            'market_state': ms_label,
            'market_state_confidence': market_state['confidence'],
            'market_state_drawdown_pct': market_state['drawdown_pct'],
            'market_state_atr_ratio': market_state['atr_ratio'],
            'market_state_volume': market_state['volume_state'],
            'market_state_reason': market_state['reason'],
            'sell_evaluation': {
                'exit_triggered': bool(exit_flag),
                'exit_reason': exit_reason,
                'channel_exit': bool(channel_exit),
                'trend_break_exit': bool(trend_break_exit),
                'top_exit': bool(top_exit),
                'collapse_exit': bool(collapse_exit),
            },
        },
        'exit': exit_flag,
        'exit_reason': exit_reason,
        'stop': price - settings['atr_stop_multiplier'] * volatility,
        'side': 'LONG',
        'reason': reason,
    }


def futures_signal(bars, price, settings, now):
    bounds = session_bounds(utc(now).astimezone(ET).date())
    if not bounds:
        raise ValueError('US cash session is closed.')
    start, end = bounds
    minutes = settings['opening_range_minutes']
    opening_end = start + timedelta(minutes=minutes)
    session = [b for b in bars if start.timestamp() <= b['time'] < end.timestamp()]
    opening = [b for b in session if b['time'] < opening_end.timestamp()]
    if utc(now) < opening_end or len({int(b['time'] // 60) for b in opening}) != minutes:
        raise ValueError('Opening range is incomplete; every one-minute candle is required.')
    volume = sum(b['volume'] for b in session)
    if volume <= 0:
        raise ValueError('VWAP requires positive session volume.')
    vwap = sum((b['high'] + b['low'] + b['close']) / 3 * b['volume'] for b in session) / volume
    high, low = max(b['high'] for b in opening), min(b['low'] for b in opening)
    long, short = price > high and price > vwap, price < low and price < vwap
    side = 'SHORT' if short else 'LONG'
    return {'enter': (long or short) and utc(now) < end - timedelta(minutes=15),
            'exit': utc(now) >= end - timedelta(minutes=5), 'side': side,
            'stop': high if short else low, 'vwap': vwap, 'session_end': end.isoformat(),
            'reason': 'Opening range breakout with directional VWAP confirmation'}


def select_credit_spread(contracts, price, iv_rank, settings, now, *, allow_warmup=False, preferred_kind=None, diagnostics=None):
    if not allow_warmup and (iv_rank is None or iv_rank < settings['min_ivr']):
        raise ValueError('IV rank is unavailable, warming up, or below the entry threshold.')
    today = utc(now).astimezone(ET).date()
    candidates = []
    missing_depth = False
    loss_ratio = settings['max_loss_ratio']
    rejections = {
        'short_delta': 0,
        'option_type_or_dte': 0,
        'otm_moneyness': 0,
        'width_or_credit_bounds': 0,
        'min_credit_2_60': 0,
        'max_friction_ratio': 0,
        'max_break_even_win_rate': 0,
        'entry_mark_above_stop': 0,
        'missing_depth': 0,
        'invalid_quote_data': 0,
    }
    samples = []
    pairs_evaluated = 0
    short_legs_considered = 0

    def record_rejection(bucket, short_strike=None, long_strike=None, detail=''):
        rejections[bucket] = rejections.get(bucket, 0) + 1
        if len(samples) < 8:
            samples.append({
                'filter': bucket,
                'short_strike': short_strike,
                'long_strike': long_strike,
                'detail': detail,
            })

    for short in contracts:
        try:
            strike = finite(short['strike'], 'strike', 0.000001)
            delta = finite(abs(float(short['delta'])), 'absolute delta', 0.01, 0.5)
            max_short_delta = settings.get('max_short_delta', 0.25)
            if delta > max_short_delta:
                record_rejection('short_delta', strike, None, f'delta={delta:.3f} > max={max_short_delta:.3f}')
                continue
            dte = (datetime.fromisoformat(short['expiration']).date() - today).days
            kind = short['option_type']
            if kind not in ('PUT', 'CALL') or (preferred_kind and kind != preferred_kind) or not 20 <= dte <= 65:
                record_rejection('option_type_or_dte', strike, None, f'kind={kind} preferred={preferred_kind} dte={dte}')
                continue
            if (kind == 'PUT' and strike >= price) or (kind == 'CALL' and strike <= price):
                record_rejection('otm_moneyness', strike, None, f'{kind} strike={strike} vs price={price}')
                continue
            short_legs_considered += 1
            for long in contracts:
                if long['expiration'] != short['expiration'] or long['option_type'] != kind:
                    continue
                long_strike = float(long['strike'])
                width = strike - long_strike if kind == 'PUT' else long_strike - strike
                if width <= 0:
                    continue
                pairs_evaluated += 1
                credit = float(short['bid']) - float(long['ask'])
                if not 0 < credit < width:
                    record_rejection('width_or_credit_bounds', strike, long_strike, f'credit={credit:.3f} width={width:.2f}')
                    continue
                if credit * 100 <= 2.60:
                    record_rejection('min_credit_2_60', strike, long_strike, f'credit_usd={credit*100:.2f} <= 2.60')
                    continue
                # The credit must pay for the spread the engine will pay to trade it.
                friction = (float(short['ask']) - float(short['bid'])) + \
                           (float(long['ask']) - float(long['bid']))
                if friction > settings['max_friction_ratio'] * credit:
                    ratio = friction / credit if credit > 0 else 99.0
                    record_rejection('max_friction_ratio', strike, long_strike,
                                     f'friction={friction:.3f} credit={credit:.3f} ratio={ratio:.2f} > {settings["max_friction_ratio"]:.2f}')
                    continue
                target = settings['profit_target_pct'] / 100
                win = target * credit
                loss = loss_ratio * (width - credit)
                if win + loss <= 0:
                    record_rejection('width_or_credit_bounds', strike, long_strike, 'non-positive win+loss')
                    continue
                break_even = loss / (win + loss)
                if break_even > settings['max_break_even_win_rate']:
                    record_rejection('max_break_even_win_rate', strike, long_strike,
                                     f'break_even={break_even:.3f} > {settings["max_break_even_win_rate"]:.3f}')
                    continue
                entry_mark = credit + friction
                stop = credit + loss
                if entry_mark >= stop:
                    record_rejection('entry_mark_above_stop', strike, long_strike,
                                     f'entry_mark={entry_mark:.3f} >= stop={stop:.3f}')
                    continue
                depth = (short.get('bid_size'), long.get('ask_size'))
                if any(value is None or float(value) < 1 for value in depth):
                    missing_depth = True
                    record_rejection('missing_depth', strike, long_strike, f'depth={depth}')
                    continue
                candidates.append((abs(dte - settings['target_dte']), abs(delta - settings['target_delta'] / 100),
                                   width,
                                   friction / credit if credit > 0 else 9.99, break_even,
                                   {'short': short, 'long': long, 'credit': credit, 'width': width,
                                    'friction': friction, 'break_even_win_rate': break_even,
                                    'expiration': short['expiration'], 'legs': 2,
                                    'entry_mark': credit + friction}))
        except (KeyError, ValueError, TypeError) as exc:
            record_rejection('invalid_quote_data', short.get('strike') if isinstance(short, dict) else None, None, str(exc)[:80])
            continue

    nonzero_rejections = {k: v for k, v in rejections.items() if v > 0}
    if isinstance(diagnostics, dict):
        diagnostics.update({
            'total_contracts': len(contracts),
            'short_legs_considered': short_legs_considered,
            'pairs_evaluated': pairs_evaluated,
            'accepted_candidates': len(candidates),
            'rejections': rejections,
            'nonzero_rejections': nonzero_rejections,
            'rejection_samples': samples,
        })

    if not candidates:
        breakdown = ', '.join(f'{k}={v}' for k, v in sorted(nonzero_rejections.items(), key=lambda kv: -kv[1]))
        suffix = f' [filters: {breakdown}]' if breakdown else ''
        if missing_depth:
            raise ValueError('No reported two-leg option depth.' + suffix)
        raise ValueError('No quoted, defined-risk OTM spread with provider Greeks.' + suffix)
    return min(candidates, key=lambda item: item[:5])[5]


def performance(snapshots, initial, closed_pnls):
    """Calendar-day returns (365 days for a portfolio including 24/7 crypto)."""
    ordered = sorted(snapshots, key=lambda s: s['time'])
    daily = {}
    peak, drawdown = initial, 0.0
    for item in ordered:
        peak = max(peak, item['equity'])
        drawdown = max(drawdown, (peak - item['equity']) / peak if peak else 0)
        daily[utc(item['time']).date()] = item['equity']
    returns = []
    days = sorted(daily)
    for previous, current in zip(days, days[1:]):
        # Do not pretend a multi-day collection gap is a daily return.
        if (current - previous).days == 1 and daily[previous] > 0:
            returns.append(daily[current] / daily[previous] - 1)
    annual = sharpe = sortino = None
    span = (utc(ordered[-1]['time']) - utc(ordered[0]['time'])).total_seconds() / 86400 if len(ordered) > 1 else 0
    if span >= 30 and initial > 0 and ordered[-1]['equity'] > 0:
        exponent = math.log(ordered[-1]['equity'] / initial) * 365 / span
        annual = math.expm1(exponent) * 100 if abs(exponent) < 700 else None
    if len(returns) >= 30:
        mean = sum(returns) / len(returns)
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        downside = math.sqrt(sum(min(r, 0) ** 2 for r in returns) / len(returns))
        sharpe = mean / std * math.sqrt(365) if std else None
        sortino = mean / downside * math.sqrt(365) if downside else None
    return {'annualized_return_pct': annual, 'sharpe': sharpe, 'sortino': sortino,
            'max_drawdown_pct': drawdown * 100, 'win_rate_pct': sum(p > 0 for p in closed_pnls) / len(closed_pnls) * 100 if closed_pnls else None,
            'closed_trades': len(closed_pnls), 'daily_return_samples': len(returns), 'risk_free_rate': 0}
