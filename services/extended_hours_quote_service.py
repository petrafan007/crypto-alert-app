"""Extended-hours (pre-market and after-hours) US stock prices from Yahoo Finance.

Webull's basic snapshot only reports the regular-session last trade, so
synthetic orders that run in extended hours read their trigger price here.
Yahoo's data is unofficial and can lag; each price carries the time of the
minute bar it came from so callers can refuse a stale one. Yahoo does not
cover the overnight (8:00 PM - 4:00 AM ET) session.
"""
import threading
import time
from datetime import datetime, timezone

from log import logger

CACHE_SECONDS = 15
MAX_AGE_SECONDS = 300

_cache = {}
_cache_lock = threading.Lock()


def _latest_bar(symbol):
    import yfinance as yf
    history = yf.Ticker(symbol).history(period='5d', interval='1m', prepost=True, auto_adjust=False, timeout=8)
    if history is None or history.empty:
        raise ValueError(f'Yahoo Finance returned no extended-hours data for {symbol}.')
    closes = history['Close'].dropna()
    closes = closes[closes > 0]
    if closes.empty:
        raise ValueError(f'Yahoo Finance returned no extended-hours price for {symbol}.')
    stamp = closes.index[-1].to_pydatetime()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    # A one-minute bar's close is observed at the end of its minute.
    return float(closes.iloc[-1]), stamp.astimezone(timezone.utc).timestamp() + 60


def get_extended_hours_price(symbol, now=None, require_fresh=True):
    """Return ``(price, as_of)`` for ``symbol``, using a short per-symbol cache.

    With ``require_fresh`` a price older than ``MAX_AGE_SECONDS`` raises
    ``ValueError`` so no order is triggered on an old quote.
    """
    clean = str(symbol or '').strip().upper()
    if not clean:
        raise ValueError('A stock symbol is required for an extended-hours quote.')
    with _cache_lock:
        cached = _cache.get(clean)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        price, as_of = cached[1], cached[2]
    else:
        try:
            price, as_of = _latest_bar(clean)
        except ValueError:
            raise
        except Exception as exc:
            logger.warning('Yahoo extended-hours quote failed for %s: %s', clean, exc)
            raise ValueError(f'The extended-hours quote for {clean} is unavailable right now.') from None
        with _cache_lock:
            _cache[clean] = (time.monotonic(), price, as_of)
    current = (now or datetime.now(timezone.utc)).timestamp()
    if require_fresh and current - as_of > MAX_AGE_SECONDS:
        raise ValueError(f'The extended-hours quote for {clean} is stale; waiting for a current price.')
    return price, datetime.fromtimestamp(as_of, timezone.utc)
