"""Price-history collection and portfolio performance calculations."""

import threading
import time

from core.extensions import db
from log import logger
from models import PriceHistory
from services.binance_service import STABLE_COINS


PERFORMANCE_WINDOWS = (
    ("change_7d", 7 * 24 * 60 * 60),
    ("change_3d", 3 * 24 * 60 * 60),
    ("change_1d", 24 * 60 * 60),
    ("change_12h", 12 * 60 * 60),
    ("change_1h", 60 * 60),
)

_BASELINE_TOLERANCE_SECONDS = 90 * 60
_HISTORY_LOOKBACK_SECONDS = 8 * 24 * 60 * 60
_SEED_RETRY_SECONDS = 15 * 60
_seed_attempts = {}
_seed_lock = threading.Lock()


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_qualifying_portfolio_coin(coin):
    """Return whether a holding belongs in the performance table."""
    symbol = (getattr(coin, "symbol", "") or "").strip().upper()
    if not symbol or symbol in STABLE_COINS or bool(getattr(coin, "hidden", False)):
        return False

    amount = _as_float(getattr(coin, "amount", 0))
    current_price = _as_float(getattr(coin, "current", 0))
    return amount > 0 and current_price > 0 and amount * current_price >= 1.0


def calculate_performance_changes(points, current_price, now_timestamp=None, is_traditional=False):
    """Calculate performance against the closest trustworthy hourly baseline."""
    now_timestamp = int(now_timestamp or time.time())
    current_price = _as_float(current_price)
    valid_points = sorted(
        (int(timestamp), _as_float(price))
        for timestamp, price in points
        if _as_float(price) > 0 and int(timestamp) <= now_timestamp
    )

    if not valid_points or current_price <= 0:
        return {key: None for key, _ in PERFORMANCE_WINDOWS}

    if is_traditional:
        from datetime import datetime
        import zoneinfo

        try:
            eastern = zoneinfo.ZoneInfo("America/New_York")
        except Exception:
            eastern = None

        day_points = {}
        for ts, pr in valid_points:
            if eastern:
                d = datetime.fromtimestamp(ts, tz=eastern).strftime("%Y-%m-%d")
            else:
                d = time.strftime("%Y-%m-%d", time.gmtime(ts))
            day_points.setdefault(d, []).append((ts, pr))
        sorted_days = sorted(day_points.keys())

        changes = {}
        # 1H: previous trading hour point if available
        if len(valid_points) >= 2:
            p1h = valid_points[-2][1]
            changes["change_1h"] = round(((current_price - p1h) / p1h) * 100, 2)
        else:
            changes["change_1h"] = None

        # 12H: day open / morning point of latest trading session
        latest_day = sorted_days[-1]
        p12h = day_points[latest_day][0][1]
        if p12h > 0:
            changes["change_12h"] = round(((current_price - p12h) / p12h) * 100, 2)
        else:
            changes["change_12h"] = None

        # 1D: closing price of previous trading day
        if len(sorted_days) >= 2:
            p1d = day_points[sorted_days[-2]][-1][1]
            changes["change_1d"] = round(((current_price - p1d) / p1d) * 100, 2)
        else:
            changes["change_1d"] = None

        # 3D: closing price 3 trading days prior
        if len(sorted_days) >= 4:
            p3d = day_points[sorted_days[-4]][-1][1]
            changes["change_3d"] = round(((current_price - p3d) / p3d) * 100, 2)
        else:
            changes["change_3d"] = None

        # 7D: closing price ~5 trading days prior (1 calendar week)
        if len(sorted_days) >= 6:
            p7d = day_points[sorted_days[-6]][-1][1]
            changes["change_7d"] = round(((current_price - p7d) / p7d) * 100, 2)
        else:
            changes["change_7d"] = None

        return changes

    changes = {}
    for key, seconds_ago in PERFORMANCE_WINDOWS:
        target = now_timestamp - seconds_ago
        baseline = min(valid_points, key=lambda point: abs(point[0] - target), default=None)
        if not baseline or abs(baseline[0] - target) > _BASELINE_TOLERANCE_SECONDS or current_price <= 0:
            changes[key] = None
            continue
        changes[key] = round(((current_price - baseline[1]) / baseline[1]) * 100, 2)
    return changes


def _has_complete_performance_history(rows, now_timestamp, is_traditional=False):
    points = [
        (int(row.timestamp), _as_float(row.price))
        for row in rows
        if _as_float(row.price) > 0
    ]
    if not points:
        return False
    if is_traditional:
        oldest = min(ts for ts, _ in points)
        newest = max(ts for ts, _ in points)
        return len(points) >= 15 and (newest - oldest) >= 5 * 86400
    return all(
        any(abs(timestamp - (now_timestamp - seconds_ago)) <= _BASELINE_TOLERANCE_SECONDS for timestamp, _ in points)
        for _, seconds_ago in PERFORMANCE_WINDOWS
    )


def ensure_price_history(symbol, now_timestamp=None, is_traditional=False):
    """Backfill only the requested market: equity tickers never use crypto pairs."""
    symbol = (symbol or '').strip().upper()
    if not symbol or symbol in STABLE_COINS:
        return False
    now_timestamp = int(now_timestamp or time.time())
    exchange = 'equity' if is_traditional else 'binance'
    cutoff = now_timestamp - (21 * 86400 if is_traditional else _HISTORY_LOOKBACK_SECONDS)
    rows = PriceHistory.query.filter(PriceHistory.symbol == symbol, PriceHistory.exchange == exchange,
        PriceHistory.timestamp >= cutoff).order_by(PriceHistory.timestamp).all()
    complete = _has_complete_performance_history(rows, now_timestamp, is_traditional)
    if is_traditional:
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        from services.portfolio_strategy_signals import session_bounds, in_session
        now_utc = datetime.fromtimestamp(now_timestamp, timezone.utc)
        latest_required = now_timestamp - 5400
        if not in_session(now_utc):
            day = now_utc.astimezone(ZoneInfo('America/New_York')).date()
            for _ in range(10):
                bounds = session_bounds(day)
                if bounds and bounds[1] <= now_utc:
                    latest_required = int(bounds[1].timestamp())
                    break
                day -= timedelta(days=1)
        complete = complete and bool(rows) and int(rows[-1].timestamp) >= latest_required
    if complete:
        return False
    key = (exchange, symbol)
    with _seed_lock:
        if time.monotonic() - _seed_attempts.get(key, 0) < _SEED_RETRY_SECONDS:
            return False
        _seed_attempts[key] = time.monotonic()
    try:
        points = []
        if is_traditional:
            import yfinance as yf
            history = yf.Ticker(symbol).history(period='1mo', interval='1h', auto_adjust=False, prepost=False, timeout=8)
            if history is not None and not history.empty:
                # Hourly bars carry opening timestamps. Ignore unfinished bars.
                for dt, row in history.iterrows():
                    bounds = session_bounds(dt.date())
                    if not bounds:
                        continue
                    close_at = min(int(dt.timestamp()) + 3600, int(bounds[1].timestamp()))
                    if close_at <= now_timestamp:
                        points.append((close_at, _as_float(row['Close']), _as_float(row.get('Volume'))))
        else:
            from binance.client import Client
            client = Client(tld='us', requests_params={'timeout': 8})
            for pair in (f'{symbol}USDT', f'{symbol}USD'):
                try:
                    bars = client.get_klines(symbol=pair, interval='1h', limit=193)
                    points = [(int(k[6]) // 1000, _as_float(k[4]), _as_float(k[5])) for k in bars if int(k[6]) // 1000 <= now_timestamp]
                    if points:
                        break
                except Exception:
                    continue
        existing = {int(row.timestamp) // 3600 for row in rows}
        added = 0
        for ts, price, volume in points:
            if ts < cutoff or price <= 0 or ts // 3600 in existing:
                continue
            db.session.add(PriceHistory(symbol=symbol, price=price, volume=volume, quote_volume=volume * price,
                timestamp=ts, exchange=exchange))
            existing.add(ts // 3600)
            added += 1
        if added:
            db.session.commit()
        return bool(added)
    except Exception as error:
        db.session.rollback()
        logger.warning('Unable to backfill %s history for %s: %s', exchange, symbol, type(error).__name__)
        return False


def record_price_history_snapshot(symbol, price, volume=0.0, quote_volume=0.0, now_timestamp=None, min_interval_seconds=60, exchange="binance"):
    """Add a current price and volume snapshot when the last stored sample is old enough."""
    symbol = (symbol or "").strip().upper()
    price = _as_float(price)
    volume = _as_float(volume)
    quote_volume = _as_float(quote_volume)
    now_timestamp = int(now_timestamp or time.time())
    if not symbol or symbol in STABLE_COINS or price <= 0:
        return False

    latest = PriceHistory.query.filter_by(symbol=symbol, exchange=exchange).order_by(PriceHistory.timestamp.desc()).first()
    if latest and now_timestamp - int(latest.timestamp) < min_interval_seconds:
        return False

    db.session.add(PriceHistory(
        symbol=symbol,
        price=price,
        volume=volume,
        quote_volume=quote_volume,
        timestamp=now_timestamp,
        exchange=exchange,
    ))
    return True


def get_last_nh_price_and_volume(symbol, lookback_hours=12, now_timestamp=None):
    """
    Retrieve the hourly price and volume data points for the specified lookback window.
    Returns a list of structured dicts and a formatted text block for AI sentiment context.
    """
    from datetime import datetime
    symbol = (symbol or "").strip().upper()
    if not symbol or symbol in STABLE_COINS:
        return [], ""

    lookback_hours = max(1, min(int(lookback_hours or 12), 72))
    now_timestamp = int(now_timestamp or time.time())
    ensure_price_history(symbol, now_timestamp)

    cutoff = now_timestamp - (lookback_hours * 3600 + 1800)
    rows = PriceHistory.query.filter(
        PriceHistory.symbol == symbol,
        PriceHistory.exchange == "binance",
        PriceHistory.timestamp >= cutoff,
        PriceHistory.timestamp <= now_timestamp,
    ).order_by(PriceHistory.timestamp.asc()).all()

    hourly_buckets = {}
    for r in rows:
        b = int(r.timestamp) // 3600
        hourly_buckets[b] = r

    current_bucket = now_timestamp // 3600
    points = []
    for h in range(lookback_hours, 0, -1):
        target_b = current_bucket - h
        row = hourly_buckets.get(target_b)
        if row and _as_float(row.price) > 0:
            dt_str = datetime.utcfromtimestamp(row.timestamp).strftime('%Y-%m-%d %H:%M UTC')
            p = _as_float(row.price)
            v = _as_float(getattr(row, 'volume', 0.0))
            qv = _as_float(getattr(row, 'quote_volume', 0.0))
            points.append({
                "hours_ago": h,
                "datetime": dt_str,
                "price": p,
                "volume": v,
                "quote_volume": qv
            })

    if not points:
        return [], f"No historical price/volume data available for {symbol}."

    lines = [f"=== LAST {lookback_hours} HOURS HOURLY PRICE & VOLUME HISTORY ({symbol}) ==="]
    for pt in points:
        price_fmt = f"${pt['price']:,.2f}" if pt['price'] >= 1 else f"${pt['price']:,.6f}"
        vol_str = f"{pt['volume']:,.2f} {symbol}" if pt['volume'] > 0 else "N/A"
        if pt['quote_volume'] > 0:
            if pt['quote_volume'] >= 1_000_000:
                qv_str = f" (${pt['quote_volume']/1_000_000:.2f}M USDT)"
            elif pt['quote_volume'] >= 1_000:
                qv_str = f" (${pt['quote_volume']/1_000:.1f}K USDT)"
            else:
                qv_str = f" (${pt['quote_volume']:.2f} USDT)"
        else:
            qv_str = ""
        lines.append(f"- {pt['hours_ago']}h ago ({pt['datetime']}): Price: {price_fmt} | Volume: {vol_str}{qv_str}")

    prompt_text = "\n".join(lines)
    return points, prompt_text


def get_symbol_performance(symbol, current_price, now_timestamp=None, is_traditional=False):
    """Compare prices within one market identity and one consistent timestamp."""
    symbol = (symbol or '').strip().upper()
    now_timestamp = int(now_timestamp or time.time())
    ensure_price_history(symbol, now_timestamp, is_traditional=is_traditional)
    exchange = 'equity' if is_traditional else 'binance'
    rows = PriceHistory.query.filter(PriceHistory.symbol == symbol, PriceHistory.exchange == exchange,
        PriceHistory.timestamp >= now_timestamp - (21 * 86400 if is_traditional else _HISTORY_LOOKBACK_SECONDS),
        PriceHistory.timestamp <= now_timestamp).order_by(PriceHistory.timestamp).all()
    points = [(int(row.timestamp), _as_float(row.price)) for row in rows]
    # Imported holdings can be days old. For a rolling performance window, use
    # the same market's latest completed bar, not an unrelated account snapshot.
    price = points[-1][1] if is_traditional and points else _as_float(current_price)
    return {'symbol': symbol, 'current_price': price, 'price_source': exchange,
        'as_of': points[-1][0] if points else None,
        **calculate_performance_changes(points, price, now_timestamp, is_traditional=is_traditional)}
