"""Write-only credential fields for browser settings; never export stored secrets."""
MASK = '********'
SECRET_FIELDS = frozenset({
    'api_key', 'api_secret', 'trading_api_key', 'trading_api_secret',
    'telegram_token', 'telegram_chat_id', 'news_api', 'news_api_key',
    'brave_search_api_key', 'brave_search_api_key_fallback',
    'webull_app_key', 'webull_app_secret', 'webull_access_token',
    'credentials_encryption_key',
} | {f'{provider}_key{suffix}' for provider in
     ('openai', 'zai', 'perplexity', 'gemini', 'inception') for suffix in
     ('', '_fallback', '_secondary', '_tertiary', '_quaternary')})


def masked_settings(values):
    return {key: (MASK if value else '') if key in SECRET_FIELDS else value
            for key, value in values.items()}


def credential_changes(values):
    """Round-tripped masks preserve secrets; explicit empty strings clear them."""
    return {key: value for key, value in values.items()
            if not (key in SECRET_FIELDS and value == MASK)}


def saved_or_supplied(value, credential, field):
    if value == MASK:
        return getattr(credential, field, None) if credential else None
    return value
