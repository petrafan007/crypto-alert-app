"""Market Calendar and Trading Session Utilities.

Determines regular trading days, official market holidays,
and calculates market opens using exchange_calendars.
"""

from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
import exchange_calendars as xcals
import pandas as pd

ET_TZ = ZoneInfo("America/New_York")

def _get_calendar(venue="XNYS"):
    return xcals.get_calendar(venue)

def is_regular_market_hours(now: datetime | None = None, venue: str = "XNYS") -> bool:
    """Check if the given time is during regular trading hours."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
        
    cal = _get_calendar(venue)
    return cal.is_open_on_minute(pd.Timestamp(now))

def is_trading_day(d: date, venue: str = "XNYS") -> bool:
    """Return True if the date is a regular trading day."""
    cal = _get_calendar(venue)
    return cal.is_session(pd.Timestamp(d))

def get_next_regular_market_open(now: datetime | None = None, venue: str = "XNYS") -> tuple[datetime, datetime, str]:
    """Calculate the next market open time.
    Returns:
        tuple of (target_utc_datetime, target_et_datetime, target_date_str)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
        
    cal = _get_calendar(venue)
    ts = pd.Timestamp(now)
    
    if cal.is_session(ts.date()) and ts < cal.session_open(ts.date()):
        next_open = cal.session_open(ts.date())
    else:
        next_open = cal.next_open(ts)
        
    target_utc = next_open.to_pydatetime()
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=timezone.utc)
        
    target_et = target_utc.astimezone(ET_TZ)
    return target_utc, target_et, target_et.strftime("%Y-%m-%d")

def is_crypto_market_open() -> bool:
    """Crypto markets are 24/7."""
    return True

