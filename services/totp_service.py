"""Shared six-digit TOTP validation for every authentication flow."""

import re

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
