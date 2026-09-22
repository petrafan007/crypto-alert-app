"""One-time two-factor authorization for every manual live-trading mutation."""
import time

from flask import session

from trading_models import TradingSettings
from services.totp_service import verify_totp_code


def require_live_trading_2fa(user_id, data, action='continue with live trading'):
    """Return None only after a fresh token or supplied code is verified."""
    settings = TradingSettings.query.filter_by(user_id=user_id).first()
    if not settings or not settings.totp_secret:
        return f'Set up two-factor authentication in Settings before you {action}.'

    payload = data or {}
    token = str(payload.get('twofa_token') or '').strip()
    if token:
        token_data = session.pop(f'2fa_verified_{token}', None)
        if (token_data and token_data.get('user_id') == user_id
                and time.time() - token_data.get('timestamp', 0) <= 120):
            return None

    code = payload.get('two_factor_code') or payload.get('twofa_code')
    try:
        if code and verify_totp_code(settings.totp_secret, code):
            return None
    except Exception:
        pass
    return f'Enter a fresh six-digit two-factor code to {action}.'
