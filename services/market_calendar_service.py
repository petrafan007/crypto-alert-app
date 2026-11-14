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

def equity_session_phase(now: datetime | None = None, venue: str = "XNYS") -> str | None:
    """Return the US stock session in progress: 'CORE', 'EXTENDED' or None.

    'EXTENDED' covers pre-market (4:00 AM ET to the open) and after-hours
    (the close until four hours later, normally 8:00 PM ET; 5:00 PM ET on
    early-close days). Weekends, market holidays and the overnight window
    return None.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cal = _get_calendar(venue)
    et_now = now.astimezone(ET_TZ)
    session_day = pd.Timestamp(et_now.date())
    if not cal.is_session(session_day):
        return None
    ts = pd.Timestamp(now)
    session_open = cal.session_open(session_day)
    session_close = cal.session_close(session_day)
    pre_market_start = pd.Timestamp(datetime.combine(et_now.date(), time(4, 0), tzinfo=ET_TZ))
    after_hours_end = session_close + pd.Timedelta(hours=4)
    if session_open <= ts < session_close:
        return "CORE"
    if pre_market_start <= ts < session_open or session_close <= ts < after_hours_end:
        return "EXTENDED"
    return None


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

