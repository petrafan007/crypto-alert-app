"""Shared six-digit TOTP validation for every authentication flow."""

import hmac
import re
import time

import pyotp

TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
TOTP_VALID_WINDOW = 1
_TOTP_CODE_PATTERN = re.compile(r"^[0-9]{6}$")


def normalize_totp_code(value):
    """Return an exact ASCII six-digit code, preserving leading zeroes."""
    code = str(value or '').strip()
    return code if _TOTP_CODE_PATTERN.fullmatch(code) else None


def verify_totp_code(secret, value, *, for_time=None):
    """Verify one app TOTP code with the application's clock-drift tolerance."""
    code = normalize_totp_code(value)
    if not secret or not code:
        return False
    totp = pyotp.TOTP(
        secret,
        digits=TOTP_DIGITS,
        interval=TOTP_INTERVAL_SECONDS,
    )
    kwargs = {'valid_window': TOTP_VALID_WINDOW}
    if for_time is not None:
        kwargs['for_time'] = for_time
    return bool(totp.verify(code, **kwargs))


def matching_time_step(secret, value, *, for_time=None):
    """Return the TOTP time step the code belongs to, or None."""
    code = normalize_totp_code(value)
    if not secret or not code:
        return None
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS)
    now = time.time() if for_time is None else (for_time.timestamp() if hasattr(for_time, 'timestamp') else for_time)
    base = int(now // TOTP_INTERVAL_SECONDS)
    for step in range(base - TOTP_VALID_WINDOW, base + TOTP_VALID_WINDOW + 1):
        if hmac.compare_digest(totp.at(step * TOTP_INTERVAL_SECONDS), code):
            return step
    return None


def consume_totp_code(settings, value, *, for_time=None):
    """Verify a code and mark it used so it cannot authorize a second action.

    The update is atomic: of two concurrent requests with the same code, only
    one succeeds. A code from an earlier time step than one already used is
    also refused.
    """
    if settings is None:
        return False
    step = matching_time_step(settings.totp_secret, value, for_time=for_time)
    if step is None:
        return False
    from sqlalchemy import text
    from core.extensions import db
    with db.engine.begin() as connection:
        updated = connection.execute(text(
            'UPDATE trading_settings SET totp_last_used_step = :step '
            'WHERE user_id = :user_id AND (totp_last_used_step IS NULL OR totp_last_used_step < :step)'
        ), {'step': step, 'user_id': settings.user_id}).rowcount
    if updated:
        settings.totp_last_used_step = step
    return bool(updated)
