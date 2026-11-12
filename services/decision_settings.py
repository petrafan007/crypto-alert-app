"""Shared settings validation for the Decision Engine.

The Decision Engine is provider neutral. Two providers are supported:

  subq       https://api.subq.ai/v1/systemone          model subq-snap-1.1
  inception  https://api.inceptionlabs.ai/v1/decisions  model mercury-decide
  gemini     https://generativelanguage.googleapis.com/v1beta/decisions  model gemini-decision-1

Settings live on ``user_settings`` under ``decision_*`` columns and the
provider API key lives in ``credentials``.
"""
import json
import math
import os
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = SUBQ_ENDPOINT = 'https://api.subq.ai/v1/systemone'
SUBQ_MODEL = 'subq-snap-1.1'
INCEPTION_DECISIONS_ENDPOINT = 'https://api.inceptionlabs.ai/v1/decisions'
INCEPTION_DECISIONS_MODEL = 'mercury-decide'
GEMINI_DECISIONS_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/decisions'
GEMINI_DECISIONS_MODEL = 'gemini-decision-1'

TRANSPORTS = ('subq', 'inception', 'gemini')

DEFAULTS = {
    'decision_enabled': False,
    'decision_transport': 'subq',
    'decision_model': SUBQ_MODEL,
    'decision_endpoint': SUBQ_ENDPOINT,
    'decision_timeout_seconds': 8.0,
    'decision_confidence_threshold': 0.8,
    'decision_conflict_threshold': 0.5,
    'decision_sentiment_mode': 'first',
    'decision_quant_enabled': False,
}

# Legacy column names kept so a saved configuration survives the rename.
LEGACY_COLUMN_MAP = {
    'decision_enabled': 'jev_enabled',
    'decision_transport': 'jev_transport',
    'decision_model': 'jev_model',
    'decision_endpoint': 'jev_endpoint',
    'decision_timeout_seconds': 'jev_timeout_seconds',
    'decision_confidence_threshold': 'jev_confidence_threshold',
    'decision_conflict_threshold': 'jev_conflict_threshold',
    'decision_sentiment_mode': 'jev_sentiment_mode',
}


def validate_endpoint(endpoint):
    """Only an operator-approved HTTPS decision endpoint may receive a key."""
    allowed = {DEFAULT_ENDPOINT, INCEPTION_DECISIONS_ENDPOINT, GEMINI_DECISIONS_ENDPOINT,
               *filter(None, os.getenv('DECISION_ALLOWED_ENDPOINTS', '').split(','))}
    parsed = urlsplit(endpoint)
    if (endpoint not in allowed or parsed.scheme != 'https' or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('The decision endpoint must be an operator-approved HTTPS decisions endpoint.')
    return endpoint


def validate_settings(data):
    values = {}
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
            low, high = (0.25, 15) if key == 'decision_timeout_seconds' else (0, 1)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key} must be between {low} and {high}.')
        elif key == 'decision_transport' and value not in TRANSPORTS:
            raise ValueError('Select SubQ, Inception Mercury Decide, or Google Gemini Decisions.')
        elif key == 'decision_sentiment_mode' and value not in ('off', 'first'):
            raise ValueError('The decision sentiment mode must be off or first.')
        elif key == 'decision_endpoint':
            validate_endpoint(value if isinstance(value, str) else '')
        elif key == 'decision_model':
            transport = data.get('decision_transport', DEFAULTS['decision_transport'])
            if transport == 'subq' and value != SUBQ_MODEL:
                raise ValueError(f'SubQ supports only the {SUBQ_MODEL} decision model.')
            if transport == 'inception' and value != INCEPTION_DECISIONS_MODEL:
                raise ValueError(f'Inception supports only the {INCEPTION_DECISIONS_MODEL} decision model.')
            if transport == 'gemini' and value != GEMINI_DECISIONS_MODEL:
                raise ValueError(f'Gemini supports only the {GEMINI_DECISIONS_MODEL} decision model.')
        values[key] = value
    if 'subq_api_key' in data and (not isinstance(data['subq_api_key'], str) or len(data['subq_api_key']) > 4096):
        raise ValueError('SubQ API key must be text of at most 4096 characters.')
    if 'inception_decisions_key' in data and (not isinstance(data['inception_decisions_key'], str) or len(data['inception_decisions_key']) > 4096):
        raise ValueError('Inception API key must be text of at most 4096 characters.')
    if 'gemini_key' in data and (not isinstance(data['gemini_key'], str) or len(data['gemini_key']) > 4096):
        raise ValueError('Gemini API key must be text of at most 4096 characters.')
    return values


def _inception_tier_key(master_ai_config):
    """The Inception key saved in the dedicated audit cascade.

    The Mercury audit tiers store their own encrypted keys, so a user who
    configured Inception only there has no key in the credential columns.
    Mercury Decide shares that same key.
    """
    if isinstance(master_ai_config, str):
        try:
            master_ai_config = json.loads(master_ai_config)
        except (TypeError, ValueError):
            return None
    if not isinstance(master_ai_config, dict):
        return None
    from credential_security import decrypt_secret
    for name in ('primary', 'secondary', 'tertiary', 'quaternary'):
        tier = master_ai_config.get(name)
        if (isinstance(tier, dict)
                and str(tier.get('provider') or '').strip().lower() == 'inception'
                and tier.get('api_key')):
            key = decrypt_secret(tier['api_key'])
            if key and key != '********':
                return key
    return None


def key_for_transport(credential, transport, master_ai_config=None):
    """The API key for a decision transport.

    Inception uses one key for chat completions and Mercury Decide, so a
    dedicated decisions key is optional. Resolution follows the same sources
    the Mercury audit cascade uses: the dedicated audit-tier key, then the
    general credential key and its fallback variants.
    """
    if transport == 'inception':
        dedicated = getattr(credential, 'inception_decisions_key', None) if credential else None
        if dedicated and dedicated != '********':
            return dedicated
        tier_key = _inception_tier_key(master_ai_config)
        if tier_key:
            return tier_key
        for field in ('inception_key', 'inception_key_fallback',
                      'inception_key_tertiary', 'inception_key_quaternary'):
            value = getattr(credential, field, None) if credential else None
            if value and value != '********':
                return value
        return None
    if transport == 'gemini':
        # Gemini Decisions reuses the Gemini key already stored for the
        # Gemini chat models (primary, then the same fallback tiers).
        if credential is None:
            return None
        for field in ('gemini_key', 'gemini_key_fallback',
                      'gemini_key_tertiary', 'gemini_key_quaternary'):
            value = getattr(credential, field, None)
            if value and value != '********':
                return value
        return None
    field = {'subq': 'subq_api_key'}.get(transport)
    return getattr(credential, field, None) if credential and field else None


def normalize_transport(config):
    """Repair a transport selection to its own endpoint and model."""
    config = dict(config)
    transport = config.get('decision_transport')
    if transport == 'subq':
        config['decision_endpoint'] = SUBQ_ENDPOINT
        config['decision_model'] = SUBQ_MODEL
    elif transport == 'inception':
        config['decision_endpoint'] = INCEPTION_DECISIONS_ENDPOINT
        config['decision_model'] = INCEPTION_DECISIONS_MODEL
    elif transport == 'gemini':
        config['decision_endpoint'] = GEMINI_DECISIONS_ENDPOINT
        config['decision_model'] = GEMINI_DECISIONS_MODEL
    return config


def settings_for(row):
    """Read the Decision Engine settings, falling back to a legacy column."""
    values = {}
    for key, default in DEFAULTS.items():
        value = getattr(row, key, None) if row is not None else None
        if value is None:
            legacy = LEGACY_COLUMN_MAP.get(key)
            value = getattr(row, legacy, None) if legacy and row is not None else None
        values[key] = default if value is None else value
    if values['decision_transport'] in ('vercel', 'openrouter'):
        # The legacy transports are retired; a saved selection migrates to SubQ.
        values['decision_transport'] = 'subq'
    values = normalize_transport(values)
    if values['decision_sentiment_mode'] == 'shadow':
        values['decision_sentiment_mode'] = 'first'
    return values


def save_settings(row, data):
    validated = validate_settings(data)
    config = {**settings_for(row), **validated}
    config = normalize_transport(config)
    if config['decision_sentiment_mode'] == 'shadow':
        config['decision_sentiment_mode'] = 'first'
    for key, value in config.items():
        setattr(row, key, value)


def schema_columns():
    """Additive PostgreSQL declarations shared by startup migration and verification."""
    columns = [('credentials', 'subq_api_key', 'VARCHAR'),
               ('credentials', 'inception_decisions_key', 'VARCHAR')]
    for name, value in DEFAULTS.items():
        if isinstance(value, bool):
            declaration = 'BOOLEAN DEFAULT ' + ('TRUE' if value else 'FALSE')
        elif isinstance(value, float):
            declaration = f'DOUBLE PRECISION DEFAULT {value}'
        else:
            declaration = f"VARCHAR(300) DEFAULT '{value}'"
        columns.append(('user_settings', name, declaration))
    return columns
