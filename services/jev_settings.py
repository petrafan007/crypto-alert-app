"""Shared settings validation for both settings APIs and workers."""
import math
import os
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = 'https://ai-gateway.vercel.sh/v1/evaluate'
DEFAULTS = {
    'jev_enabled': False, 'jev_transport': 'vercel', 'jev_model': 'typesafe-ai/jev',
    'jev_endpoint': DEFAULT_ENDPOINT, 'jev_timeout_seconds': 3.0,
    'jev_confidence_threshold': 0.8, 'jev_conflict_threshold': 0.5,
    'jev_sentiment_mode': 'off', 'jev_generative_fallback_enabled': True,
    'jev_quant_shadow_enabled': False,
}


def validate_endpoint(endpoint):
    # Additional transports require an operator allowlist, never an arbitrary
    # browser-supplied destination that could receive a saved credential.
    allowed = {DEFAULT_ENDPOINT, *filter(None, os.getenv('JEV_ALLOWED_ENDPOINTS', '').split(','))}
    parsed = urlsplit(endpoint)
    if endpoint not in allowed or parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Jev endpoint must be an operator-approved HTTPS evaluation endpoint.')
    return endpoint


def validate_settings(data):
    values = {}
    if data.get('jev_quant_paper_gate_enabled') not in (None, False):
        raise ValueError('Jev paper gating is unavailable; quant supports shadow mode only.')
    for key, default in DEFAULTS.items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(default, bool):
            if type(value) is not bool:
                raise ValueError(f'{key} must be true or false.')
        elif isinstance(default, float):
            if isinstance(value, bool):
                raise ValueError(f'{key} must be numeric.')
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f'{key} must be numeric.') from None
            low, high = (0.25, 15) if key == 'jev_timeout_seconds' else (0, 1)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key} must be between {low} and {high}.')
        elif key == 'jev_transport' and value != 'vercel':
            raise ValueError('Only Vercel AI Gateway transport is supported.')
        elif key == 'jev_sentiment_mode' and value not in ('off', 'shadow', 'first'):
            raise ValueError('Jev sentiment mode must be off, shadow, or first.')
        elif key == 'jev_endpoint':
            validate_endpoint(value if isinstance(value, str) else '')
        elif key == 'jev_model':
            if not isinstance(value, str) or not value.startswith('typesafe-ai/jev') or len(value) > 100 or any(c.isspace() for c in value):
                raise ValueError('Select a TypeSafe Jev evaluation model.')
        values[key] = value
    if 'ai_gateway_key' in data and (not isinstance(data['ai_gateway_key'], str) or len(data['ai_gateway_key']) > 4096):
        raise ValueError('Vercel API key must be text of at most 4096 characters.')
    return values


def settings_for(row):
    return {k: getattr(row, k, None) if getattr(row, k, None) is not None else v for k, v in DEFAULTS.items()}


def save_settings(row, data):
    for key, value in validate_settings(data).items():
        setattr(row, key, value)


def schema_columns():
    """Additive PostgreSQL declarations shared by startup migration and verification."""
    columns = [('credentials', 'ai_gateway_key', 'VARCHAR')]
    for name, value in DEFAULTS.items():
        if isinstance(value, bool):
            declaration = 'BOOLEAN DEFAULT ' + ('TRUE' if value else 'FALSE')
        elif isinstance(value, float):
            declaration = f'DOUBLE PRECISION DEFAULT {value}'
        else:
            declaration = f"VARCHAR(300) DEFAULT '{value}'"
        columns.append(('user_settings', name, declaration))
    return columns
