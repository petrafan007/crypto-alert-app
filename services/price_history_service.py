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


def calculate_performance_changes(points, current_price, now_timestamp=None):
    """Calculate performance against the closest trustworthy hourly baseline."""
    now_timestamp = int(now_timestamp or time.time())
    current_price = _as_float(current_price)
    valid_points = sorted(
        (int(timestamp), _as_float(price))
        for timestamp, price in points
        if _as_float(price) > 0 and int(timestamp) <= now_timestamp
    )

    changes = {}
    for key, seconds_ago in PERFORMANCE_WINDOWS:
        target = now_timestamp - seconds_ago
        baseline = min(valid_points, key=lambda point: abs(point[0] - target), default=None)
        if not baseline or abs(baseline[0] - target) > _BASELINE_TOLERANCE_SECONDS or current_price <= 0:
            changes[key] = None
            continue
        changes[key] = round(((current_price - baseline[1]) / baseline[1]) * 100, 2)
    return changes


def _has_complete_performance_history(rows, now_timestamp):
    points = [
        (int(row.timestamp), _as_float(row.price))
        for row in rows
        if _as_float(row.price) > 0
    ]
    return all(
        any(abs(timestamp - (now_timestamp - seconds_ago)) <= _BASELINE_TOLERANCE_SECONDS for timestamp, _ in points)
        for _, seconds_ago in PERFORMANCE_WINDOWS
    )


def ensure_price_history(symbol, now_timestamp=None):
    """Backfill missing hourly history from public Binance.US market data."""
    symbol = (symbol or "").strip().upper()
    if not symbol or symbol in STABLE_COINS:
        return False

    now_timestamp = int(now_timestamp or time.time())
    cutoff = now_timestamp - _HISTORY_LOOKBACK_SECONDS
    rows = PriceHistory.query.filter(
        PriceHistory.symbol == symbol,
        PriceHistory.timestamp >= cutoff,
    ).order_by(PriceHistory.timestamp.asc()).all()
    if _has_complete_performance_history(rows, now_timestamp):
        return False

    with _seed_lock:
        last_attempt = _seed_attempts.get(symbol, 0)
        if time.monotonic() - last_attempt < _SEED_RETRY_SECONDS:
            return False
        _seed_attempts[symbol] = time.monotonic()

    try:
        from binance.client import Client

        client = Client(tld="us", requests_params={"timeout": 10})
        klines = None
        selected_pair = None
        for pair in (f"{symbol}USDT", f"{symbol}USD"):
            try:
                candidate = client.get_klines(symbol=pair, interval="1h", limit=169)
                if candidate:
                    klines = candidate
                    selected_pair = pair
                    break
            except Exception as pair_error:
                logger.debug("No Binance.US hourly history for %s: %s", pair, pair_error)

        if not klines:
            logger.warning("No Binance.US hourly price history found for %s", symbol)
            return False

        existing_buckets = {int(row.timestamp) // 3600 for row in rows}
        added = 0
        for kline in klines:
            close_timestamp = min(int(kline[6]) // 1000, now_timestamp)
            close_price = _as_float(kline[4])
            bucket = close_timestamp // 3600
            if close_timestamp < cutoff or close_price <= 0 or bucket in existing_buckets:
                continue
            db.session.add(PriceHistory(
                symbol=symbol,
                price=close_price,
                timestamp=close_timestamp,
                exchange="binance",
            ))
            existing_buckets.add(bucket)
            added += 1

        if added:
            db.session.commit()
            logger.info("Backfilled %s hourly price points for %s from %s", added, symbol, selected_pair)
        return bool(added)
    except Exception as error:
        db.session.rollback()
        logger.warning("Failed to backfill price history for %s: %s", symbol, error)
        return False


def record_price_history_snapshot(symbol, price, now_timestamp=None, min_interval_seconds=60):
    """Add a current price snapshot when the last stored sample is old enough."""
    symbol = (symbol or "").strip().upper()
    price = _as_float(price)
    now_timestamp = int(now_timestamp or time.time())
    if not symbol or symbol in STABLE_COINS or price <= 0:
        return False

    latest = PriceHistory.query.filter_by(symbol=symbol).order_by(PriceHistory.timestamp.desc()).first()
    if latest and now_timestamp - int(latest.timestamp) < min_interval_seconds:
        return False

    db.session.add(PriceHistory(
        symbol=symbol,
        price=price,
        timestamp=now_timestamp,
        exchange="binance",
    ))
    return True


def get_symbol_performance(symbol, current_price, now_timestamp=None):
    """Return all configured performance windows for one symbol."""
    symbol = (symbol or "").strip().upper()
    now_timestamp = int(now_timestamp or time.time())
    ensure_price_history(symbol, now_timestamp)

    cutoff = now_timestamp - _HISTORY_LOOKBACK_SECONDS
    rows = PriceHistory.query.filter(
        PriceHistory.symbol == symbol,
        PriceHistory.timestamp >= cutoff,
        PriceHistory.timestamp <= now_timestamp,
    ).order_by(PriceHistory.timestamp.asc()).all()
    points = [(int(row.timestamp), _as_float(row.price)) for row in rows]

    current_price = _as_float(current_price)
    if current_price <= 0 and points:
        current_price = points[-1][1]

    return {
        "symbol": symbol,
        "current_price": current_price,
        **calculate_performance_changes(points, current_price, now_timestamp),
    }
