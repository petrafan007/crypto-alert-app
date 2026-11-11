"""Timestamp provenance for Event quotes and independently observed spot prices."""
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_EVENT_SYMBOL_MONTHS = {
    'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
}
EVENT_SYMBOL_HOURLY = re.compile(
    r'-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})H(\d{2})(\d{2})(?:-|$)'
)
_EVENT_SYMBOL_DATED = re.compile(
    r'-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{2,6})(EST|EDT)?(?:-|$)'
)


def event_symbol_settlement(value):
    """Eastern settlement instant encoded in an Event contract ticker, or None.

    Handles the hourly ``-26OCT21H1400`` form, the current ``-26NOV110515``
    form and the legacy ``-26NOV010100EST`` form. The legacy timezone suffix
    once defeated the parser, producing end-of-day cutoffs that rejected
    Kalshi's finalized settlement and froze contracts open indefinitely.
    Time digits after the two-digit day are HH, HHMM or HHMMSS. An explicit
    EST/EDT suffix declares a fixed UTC offset (verified against Kalshi
    close_time during the ambiguous 2026-11-01 fall-back hour); unlabeled
    tickers use the America/New_York wall clock.
    """
    text = str(value or '').strip().upper()
    hourly = EVENT_SYMBOL_HOURLY.search(text)
    if hourly:
        try:
            return datetime(
                2000 + int(hourly.group(1)), _EVENT_SYMBOL_MONTHS[hourly.group(2)], int(hourly.group(3)),
                int(hourly.group(4)), int(hourly.group(5)), tzinfo=ZoneInfo('America/New_York'),
            )
        except (KeyError, ValueError):
            return None
    match = _EVENT_SYMBOL_DATED.search(text)
    if not match:
        return None
    digits = match.group(4)
    if len(digits) not in (2, 4, 6):
        return None
    suffix = match.group(5)
    zone = (timezone(timedelta(hours=-5)) if suffix == 'EST' else
            timezone(timedelta(hours=-4)) if suffix == 'EDT' else ZoneInfo('America/New_York'))
    try:
        return datetime(
            2000 + int(match.group(1)), _EVENT_SYMBOL_MONTHS[match.group(2)], int(match.group(3)),
            int(digits[:2]), int(digits[2:4] or 0), int(digits[4:6] or 0), tzinfo=zone,
        )
    except (KeyError, ValueError):
        return None


def observation_time(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            else:
                parsed = datetime.fromtimestamp(numeric / 1000 if numeric > 1e11 else numeric, timezone.utc)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _iso(value):
    parsed = observation_time(value)
    return parsed.isoformat() if parsed else None


def _age_status(value, now):
    timestamp = observation_time(value)
    if timestamp is None:
        return None, 'UNKNOWN' if value in (None, '') else 'INVALID'
    age = (observation_time(now) - timestamp).total_seconds()
    return round(age, 3), 'FUTURE' if age < -5 else 'STALE' if age > 30 else 'FRESH'


def normalise_quote_times(raw, retrieved_at):
    key = next((key for key in ('quote_as_of', 'quote_time', 'timestamp', 'updated_at') if raw.get(key) not in (None, '')), None)
    provider_time = observation_time(raw.get(key)) if key else None
    return {'quote_as_of': _iso(provider_time), 'quote_retrieved_at': _iso(retrieved_at),
            'quote_time_basis': 'PROVIDER' if provider_time else 'INVALID_PROVIDER' if key else 'RETRIEVAL_ONLY',
            'quote_timestamp_source': key, 'quote_provider_timestamp_raw': raw.get(key) if key else None}


def quote_freshness(market, now=None):
    now = now or datetime.now(timezone.utc)
    basis = market.get('quote_time_basis')
    provider = next((market[key] for key in ('quote_as_of', 'quote_time', 'timestamp', 'updated_at')
                     if market.get(key) not in (None, '')), None)
    if basis == 'RETRIEVAL_ONLY':
        provider = None
    retrieved = market.get('quote_retrieved_at')
    if basis == 'INVALID_PROVIDER':
        age, status = None, 'INVALID'
    else:
        age, status = _age_status(provider if provider is not None else retrieved, now)
    return {'provider_quote_at': _iso(provider), 'retrieved_at': _iso(retrieved),
            'last_trade_at': _iso(market.get('last_trade_time') or market.get('trade_time')),
            'basis': basis or ('UNSPECIFIED_QUOTE_TIME' if provider is not None else 'RETRIEVAL_ONLY' if retrieved else 'UNKNOWN'),
            'age_seconds': age, 'status': status}


def underlying_observation(market, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        observed = float(market.get('underlying_price'))
        if not math.isfinite(observed) or observed <= 0:
            observed = None
    except (TypeError, ValueError):
        observed = None
    age, status = _age_status(market.get('underlying_price_as_of'), now)
    if observed is None:
        status = 'MISSING'
    return {'price': observed if status == 'FRESH' else None, 'observed_price': observed,
            'observed_at': _iso(market.get('underlying_price_as_of')),
            'retrieved_at': _iso(market.get('underlying_price_retrieved_at')),
            'source': market.get('underlying_price_source') or 'UNKNOWN',
            'timestamp_basis': market.get('underlying_timestamp_basis') or 'UNKNOWN',
            'age_seconds': age, 'status': status}
