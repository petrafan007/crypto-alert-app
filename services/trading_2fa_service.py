"""One-time two-factor authorization for every manual live-trading mutation."""
import time

from flask import session

from trading_models import TradingSettings
from services.totp_service import consume_totp_code, matching_time_step


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
    if code:
        try:
            if consume_totp_code(settings, code):
                return None
            if matching_time_step(settings.totp_secret, code) is not None:
                return (f'That two-factor code was already used. Wait for the next code in your '
                        f'authenticator app to {action}.')
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Two-factor verification failed')
    return f'Enter a fresh six-digit two-factor code to {action}.'
