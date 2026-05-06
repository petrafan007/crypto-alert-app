import datetime
import pytz

def get_eastern_now():
    return datetime.datetime.now(pytz.timezone('US/Eastern'))

def get_eastern_datetime(dt=None):
    if dt is None:
        return get_eastern_now()
    if dt.tzinfo is None:
        return pytz.timezone('UTC').localize(dt).astimezone(pytz.timezone('US/Eastern'))
    return dt.astimezone(pytz.timezone('US/Eastern'))

def format_eastern_datetime(dt=None, format_str="%Y-%m-%d %H:%M:%S EST"):
    eastern_dt = get_eastern_datetime(dt)
    return eastern_dt.strftime(format_str)

def format_eastern_datetime_ampm(dt=None, format_str="%m/%d/%Y %I:%M %p EST"):
    eastern_dt = get_eastern_datetime(dt)
    return eastern_dt.strftime(format_str)

def get_eastern_now_ampm():
    return format_eastern_datetime_ampm()

def get_eastern_now_iso():
    return get_eastern_now().isoformat()

def coerce_datetime(val):
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.datetime.fromisoformat(val.replace('Z', '+00:00'))
        except:
            pass
    return None

def format_date_only(dt):
    if not dt: return ""
    return dt.strftime("%Y-%m-%d")

def format_date(dt):
    if not dt: return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")

