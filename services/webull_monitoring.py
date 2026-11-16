"""Webull price alerts and access-token health.

* Price alerts: a Webull holding with alerts on and a lower or upper
  threshold notifies once when the price crosses it, the same way Binance.US
  portfolio alerts do. Prices come from the portfolio sync; a holding whose
  price has not refreshed recently is skipped rather than alerted on.
* Token health: the stored Webull token is re-checked with Webull, which
  refreshes the saved expiry. You are told a few days before it expires, and
  immediately if Webull reports it invalid or expired.
"""
import logging
from datetime import datetime, timedelta

from core.extensions import db

logger = logging.getLogger(__name__)

PRICE_MAX_AGE = timedelta(minutes=10)
TOKEN_WARNING_WINDOW = timedelta(days=3)
REARM_BUFFER = 0.01  # price must move 1% back across a threshold before it can alert again


def _thresholds(holding):
    """(lower, upper) alert prices for a holding, or None where unset."""
    base = float(holding.cost_price or 0.0)

    def resolve(kind, value, pct, sign):
        kind = (kind or '#').strip()
        if kind in ('%', 'Auto%'):
            if pct is None or base <= 0:
                return None
            return round(base * (1 + sign * float(pct) / 100), 6)
        return round(float(value), 6) if value not in (None, 0) else None

    return (resolve(holding.custom_lower_type, holding.custom_lower_val, holding.custom_lower_pct, -1),
            resolve(holding.custom_upper_type, holding.custom_upper_val, holding.custom_upper_pct, +1))


def check_webull_price_alerts(now=None):
    """Notify once per crossing for every Webull holding with alerts enabled."""
    from credentials import User
    from models import WebullHolding
    from services.notification_service import save_notification_record
    now = now or datetime.utcnow()
    sent = 0
    holdings = WebullHolding.query.filter(WebullHolding.alert_enabled.is_(True),
                                          WebullHolding.hidden.isnot(True)).all()
    users = {u.id: u for u in User.query.filter(User.id.in_({h.user_id for h in holdings})).all()} if holdings else {}
    for holding in holdings:
        price = float(holding.last_price or 0.0)
        if price <= 0 or not holding.synced_at or now - holding.synced_at > PRICE_MAX_AGE:
            continue  # never alert on a stale price
        user = users.get(holding.user_id)
        if not user:
            continue
        lower, upper = _thresholds(holding)
        label = f'{holding.display_name or holding.symbol} in Webull account {holding.account_id}'

        def record(direction, threshold, message, holding=holding, user=user):
            save_notification_record(user.id, holding.id, 'webull', holding.symbol, direction, 'price',
                                     threshold, threshold, holding.last_price, message=message)

        sent += _cross_and_notify(user, holding.symbol, f'webull:{holding.account_id}', label,
                                  price, lower, upper, record)
    return sent


WATCHLIST_REFRESH_AGE = timedelta(minutes=2)
QUOTABLE_TYPES = {'', 'EQUITY', 'STOCK', 'ETF'}


def _cross_and_notify(user, symbol, source, label, price, lower, upper, notify_record):
    """Shared one-alert-per-crossing logic; returns the number of new alerts."""
    from services.notification_service import send_telegram_message
    from services.scheduler_tasks import get_last_alert_state, set_last_alert_state
    sent = 0
    for direction, threshold, crossed, rearmed in (
        ('down', lower, lower is not None and price <= lower, lower is not None and price > lower * (1 + REARM_BUFFER)),
        ('up', upper, upper is not None and price >= upper, upper is not None and price < upper * (1 - REARM_BUFFER)),
    ):
        if threshold is None:
            continue
        state = get_last_alert_state(user.id, symbol, direction, source, threshold)
        verb = 'fell below' if direction == 'down' else 'rose above'
        if crossed:
            if state not in ('saved', 'sent'):
                notify_record(direction, threshold, f'{label} {verb} ${threshold:,.4f} (now ${price:,.4f}).')
                set_last_alert_state(user.id, symbol, direction, 'saved', source, threshold)
                state = 'saved'
                sent += 1
            if state != 'sent' and send_telegram_message(
                    user.username, f'⚠️ {label} (Webull) {verb} ${threshold:,.4f}. Current price: ${price:,.4f}'):
                set_last_alert_state(user.id, symbol, direction, 'sent', source, threshold)
        elif state in ('saved', 'sent') and rearmed:
            set_last_alert_state(user.id, symbol, direction, None, source, threshold)
    return sent


def check_webull_watchlist_alerts(now=None, price_lookup=None):
    """Alerts for Webull watchlist items with a lower or upper alert price."""
    from credentials import User
    from models import WebullWatchlistItem
    from services.notification_service import save_notification_record
    now = now or datetime.utcnow()
    items = WebullWatchlistItem.query.filter(
        WebullWatchlistItem.alert_enabled.is_(True),
        (WebullWatchlistItem.down_alert.isnot(None)) | (WebullWatchlistItem.up_alert.isnot(None)),
    ).all()
    if not items:
        return 0
    if price_lookup is None:
        from routes.portfolio import _fetch_stock_price_yf as price_lookup
    users = {u.id: u for u in User.query.filter(User.id.in_({i.user_id for i in items})).all()}
    sent = 0
    for item in items:
        user = users.get(item.user_id)
        if not user:
            continue
        stale = not item.refreshed_at or now - item.refreshed_at > WATCHLIST_REFRESH_AGE
        if stale and str(item.instrument_type or '').upper() in QUOTABLE_TYPES:
            try:
                price = float(price_lookup(item.symbol, item.user_id) or 0)
            except Exception:
                logger.debug('Watchlist price refresh failed for %s', item.symbol, exc_info=True)
                price = 0.0
            if price > 0:
                item.last_price, item.refreshed_at = price, now
                db.session.commit()
        price = float(item.last_price or 0.0)
        if price <= 0 or not item.refreshed_at or now - item.refreshed_at > PRICE_MAX_AGE:
            continue  # never alert on a stale price

        def record(direction, threshold, message, item=item, user=user):
            save_notification_record(user.id, item.id, 'webull_watchlist', item.symbol, direction, '#',
                                     threshold, threshold, item.last_price, message=message)

        sent += _cross_and_notify(user, item.symbol, 'webull-watchlist', item.display_name or item.symbol,
                                  price, item.down_alert, item.up_alert, record)
    return sent


def check_webull_token_health(now=None):
    """Refresh each stored Webull token's status and expiry; warn before it lapses."""
    from credentials import Credential, User, UserSetting
    from models import AlertState
    from services.notification_service import create_system_notification, send_telegram_message
    from services.webull_service import (
        WebullConnectionError, check_webull_access_token, normalize_webull_environment, parse_webull_expiry,
    )
    now = now or datetime.utcnow()
    for credential in Credential.query.filter(Credential.webull_token_status == 'NORMAL').all():
        if not credential.webull_access_token:
            continue
        setting = UserSetting.query.filter_by(user_id=credential.user_id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if credential.webull_token_environment != environment:
            continue
        user = db.session.get(User, credential.user_id)
        try:
            details = check_webull_access_token(credential.webull_app_key, credential.webull_app_secret,
                                                credential.webull_access_token, environment)
        except WebullConnectionError as exc:
            logger.warning('Webull token check failed for user %s: %s', credential.user_id, exc)
            continue
        credential.webull_token_status = details['status']
        expires_at = parse_webull_expiry(details.get('expires'))
        if expires_at:
            credential.webull_token_expires_at = expires_at
        db.session.commit()

        def notify_once(key, message):
            if db.session.get(AlertState, (credential.user_id, key)):
                return
            db.session.add(AlertState(user_id=credential.user_id, alert_key=key, state='sent'))
            create_system_notification(credential.user_id, 'system_error' if 'disconnected' in message else 'warning',
                                       'WEBULL', message)
            if user:
                send_telegram_message(user.username, f'⚠️ {message}')
            db.session.commit()

        if details['status'] in {'INVALID', 'EXPIRED'}:
            notify_once(f'webull_token:{details["status"]}:{now:%Y-%m-%d}',
                        'Webull disconnected: its access token is no longer valid. Reconnect Webull in '
                        'Settings → Integrations to resume syncing, orders and alerts.')
        elif expires_at and expires_at - now <= TOKEN_WARNING_WINDOW:
            days = max(0, (expires_at - now).days)
            notify_once(f'webull_token:expiring:{expires_at:%Y-%m-%d}',
                        f'Your Webull access token expires {"today" if days == 0 else f"in {days} day(s)"} '
                        f'({expires_at:%Y-%m-%d %H:%M} UTC). Renew it in Settings → Integrations so syncing '
                        'and orders keep working.')
