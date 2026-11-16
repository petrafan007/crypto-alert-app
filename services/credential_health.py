"""Detect API keys that keep failing, pause background use, and tell the user.

A provider's background jobs (balance sync, order-history sync, order status
polling) stop calling the provider once its keys have been rejected
``PAUSE_AFTER_FAILURES`` times in a row. Hammering an exchange with rejected
keys risks an IP ban and floods the logs. Saving new keys, or a successful
connection test, resumes the account immediately.

Only authentication/permission failures count. Timeouts, rate limits and
outages are transient and never pause anything.
"""
import logging
from datetime import datetime

from core.extensions import db

logger = logging.getLogger(__name__)

PAUSE_AFTER_FAILURES = 3
BINANCE_AUTH_CODES = {-2015, -2014, -1022, -2008}
AUTH_MARKERS = (
    'invalid api-key', 'api-key format invalid', 'signature for this request is not valid',
    'invalid token', 'token expired', 'unauthorized', 'unauthorised', 'permission denied',
    'invalid_token', 'token_invalid', 'auth_failed', 'not authorized',
)
PROVIDER_LABELS = {'binance': 'Binance.US', 'webull': 'Webull'}


def _model():
    from models import CredentialHealth
    return CredentialHealth


def is_auth_failure(exc):
    """True only for errors that mean the keys or token were rejected."""
    code = getattr(exc, 'code', None)
    try:
        if int(code) in BINANCE_AUTH_CODES:
            return True
    except (TypeError, ValueError):
        pass
    status = getattr(exc, 'http_status', None) or getattr(exc, 'status_code', None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in AUTH_MARKERS)


def is_paused(user_id, provider):
    row = _model().query.filter_by(user_id=user_id, provider=provider).first()
    return bool(row and row.paused)


def record_success(user_id, provider):
    row = _model().query.filter_by(user_id=user_id, provider=provider).first()
    if row and (row.consecutive_failures or row.paused):
        was_paused = row.paused
        row.consecutive_failures = 0
        row.paused = False
        row.paused_at = None
        row.last_error = None
        db.session.commit()
        if was_paused:
            logger.info('%s credentials for user %s are working again; background sync resumed.',
                        PROVIDER_LABELS.get(provider, provider), user_id)


def record_failure(user_id, provider, exc):
    """Count an auth failure; pause and notify once the threshold is reached.

    Returns True when the provider is now paused.
    """
    if not is_auth_failure(exc):
        return False
    Model = _model()
    row = Model.query.filter_by(user_id=user_id, provider=provider).first()
    if row is None:
        row = Model(user_id=user_id, provider=provider, consecutive_failures=0, paused=False)
        db.session.add(row)
    now = datetime.utcnow()
    row.consecutive_failures = (row.consecutive_failures or 0) + 1
    row.first_failure_at = row.first_failure_at if row.consecutive_failures > 1 and row.first_failure_at else now
    row.last_failure_at = now
    row.last_error = str(exc)[:500]
    newly_paused = row.consecutive_failures >= PAUSE_AFTER_FAILURES and not row.paused
    if newly_paused:
        row.paused = True
        row.paused_at = now
    db.session.commit()
    if newly_paused:
        _notify_paused(user_id, provider, row)
    return row.paused


def _notify_paused(user_id, provider, row):
    from credentials import User
    from services.notification_service import create_system_notification, send_telegram_message
    label = PROVIDER_LABELS.get(provider, provider)
    message = (f'{label} background sync is paused: your API credentials were rejected '
               f'{row.consecutive_failures} times in a row ({row.last_error}). Update the keys in '
               f'Settings → Integrations, or use Test Connection once fixed; syncing resumes automatically.')
    logger.warning('Paused %s background sync for user %s after repeated credential failures.', label, user_id)
    create_system_notification(user_id, 'system_error', provider.upper(), message)
    user = db.session.get(User, user_id)
    if user:
        send_telegram_message(user.username, f'⚠️ {message}')


def resume(user_id, provider):
    row = _model().query.filter_by(user_id=user_id, provider=provider).first()
    if row:
        row.paused = False
        row.paused_at = None
        row.consecutive_failures = 0
        db.session.commit()


def status_for_user(user_id):
    return {
        row.provider: {
            'label': PROVIDER_LABELS.get(row.provider, row.provider),
            'paused': bool(row.paused),
            'consecutive_failures': row.consecutive_failures or 0,
            'last_error': row.last_error,
            'first_failure_at': row.first_failure_at.isoformat() + 'Z' if row.first_failure_at else None,
            'paused_at': row.paused_at.isoformat() + 'Z' if row.paused_at else None,
        }
        for row in _model().query.filter_by(user_id=user_id).all()
    }
