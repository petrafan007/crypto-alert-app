"""Time and timezone utility functions.

Provides standardized UTC timestamp generation to replace deprecated
datetime.utcnow() and datetime.utcfromtimestamp() without risking
naive-vs-aware comparison errors in SQLite or SQLAlchemy columns.
"""
from datetime import datetime, timezone
from typing import Optional


def utc_now(*, aware: bool = False) -> datetime:
    """Return the current UTC datetime.

    If aware is True, returns an offset-aware datetime in timezone.utc.
    If aware is False (default), returns a timezone-naive UTC datetime
    equivalent to datetime.utcnow(), safe for SQLite and naive database columns.
    """
    now = datetime.now(timezone.utc)
    return now if aware else now.replace(tzinfo=None)


def utc_from_timestamp(timestamp: float, *, aware: bool = False) -> datetime:
    """Convert a POSIX timestamp to a UTC datetime.

    If aware is True, returns an offset-aware datetime in timezone.utc.
    If aware is False (default), returns a timezone-naive UTC datetime
    equivalent to datetime.utcfromtimestamp(), safe for SQLite comparisons.
    """
    dt = datetime.fromtimestamp(timestamp, timezone.utc)
    return dt if aware else dt.replace(tzinfo=None)


def ensure_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime is timezone-naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def ensure_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime is timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
