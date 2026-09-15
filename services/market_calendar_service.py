"""NYSE Market Calendar and Trading Session Utilities.

Determines regular trading days, official NYSE market holidays,
and calculates the exact next 9:30:00 AM Eastern Time market open
for scheduling fractional stock and ETF orders.
"""

from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")


def _easter_date(year: int) -> date:
    """Calculate Western Easter Sunday using the anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed_date(dt: date) -> date:
    """Return observed holiday date (Saturday -> Friday, Sunday -> Monday)."""
    if dt.weekday() == 5:  # Saturday -> preceding Friday
        return dt - timedelta(days=1)
    elif dt.weekday() == 6:  # Sunday -> following Monday
        return dt + timedelta(days=1)
    return dt


def get_nyse_holidays(year: int) -> set[date]:
    """Return the set of official NYSE market holiday dates for a given year."""
    holidays = set()

    # 1. New Year's Day (Jan 1) - observed
    nyd = _observed_date(date(year, 1, 1))
    if nyd.year == year:
        holidays.add(nyd)

    # 2. Martin Luther King Jr. Day (Third Monday in January)
    first_jan = date(year, 1, 1)
    mlk_day = first_jan + timedelta(days=(0 - first_jan.weekday() + 7) % 7 + 14)
    holidays.add(mlk_day)

    # 3. Washington's Birthday / Presidents Day (Third Monday in February)
    first_feb = date(year, 2, 1)
    presidents_day = first_feb + timedelta(days=(0 - first_feb.weekday() + 7) % 7 + 14)
    holidays.add(presidents_day)

    # 4. Good Friday (Friday before Easter Sunday)
    easter = _easter_date(year)
    good_friday = easter - timedelta(days=2)
    holidays.add(good_friday)

    # 5. Memorial Day (Last Monday in May)
    last_may = date(year, 5, 31)
    memorial_day = last_may - timedelta(days=(last_may.weekday() - 0) % 7)
    holidays.add(memorial_day)

    # 6. Juneteenth National Independence Day (June 19) - observed
    juneteenth = _observed_date(date(year, 6, 19))
    holidays.add(juneteenth)

    # 7. Independence Day (July 4) - observed
    july4 = _observed_date(date(year, 7, 4))
    holidays.add(july4)

    # 8. Labor Day (First Monday in September)
    first_sep = date(year, 9, 1)
    labor_day = first_sep + timedelta(days=(0 - first_sep.weekday() + 7) % 7)
    holidays.add(labor_day)

    # 9. Thanksgiving Day (Fourth Thursday in November)
    first_nov = date(year, 11, 1)
    thanksgiving = first_nov + timedelta(days=(3 - first_nov.weekday() + 7) % 7 + 21)
    holidays.add(thanksgiving)

    # 10. Christmas Day (December 25) - observed
    christmas = _observed_date(date(year, 12, 25))
    holidays.add(christmas)

    return holidays


def is_nyse_holiday(d: date) -> bool:
    """Return True if the date is an official NYSE market holiday."""
    return d in get_nyse_holidays(d.year)


def is_trading_day(d: date) -> bool:
    """Return True if the date is a regular NYSE trading day (Mon-Fri and not holiday)."""
    return d.weekday() < 5 and not is_nyse_holiday(d)


def get_next_trading_day(d: date) -> date:
    """Find the earliest trading day strictly after the given date."""
    candidate = d + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def get_next_regular_market_open(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """Calculate the next 9:30:00 AM Eastern Time NYSE market open.

    Returns:
        tuple of (target_utc_datetime, target_et_datetime, target_date_str)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now_et = now.astimezone(ET_TZ)
    current_date = now_et.date()
    market_open_time = time(9, 30, 0)

    if is_trading_day(current_date) and now_et.time() < market_open_time:
        target_date = current_date
    else:
        target_date = get_next_trading_day(current_date)

    target_et = datetime.combine(target_date, market_open_time, tzinfo=ET_TZ)
    target_utc = target_et.astimezone(timezone.utc)
    return target_utc, target_et, target_date.strftime("%Y-%m-%d")


def is_regular_market_hours(now: datetime | None = None) -> bool:
    """Check if the given time is during regular US trading hours (9:30 AM - 4:00 PM ET)."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now_et = now.astimezone(ET_TZ)
    if not is_trading_day(now_et.date()):
        return False

    return time(9, 30, 0) <= now_et.time() < time(16, 0, 0)
