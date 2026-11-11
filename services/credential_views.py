"""Write-only credential fields for browser settings; never export stored secrets."""
MASK = '********'
SECRET_FIELDS = frozenset({
    'ai_gateway_key', 'openrouter_api_key', 'subq_api_key', 'inception_decisions_key',
    'api_key', 'api_secret', 'trading_api_key', 'trading_api_secret',
    'telegram_token', 'telegram_chat_id', 'news_api', 'news_api_key',
    'brave_search_api_key', 'brave_search_api_key_fallback',
    'coingecko_api_key', 'coinstats_api_key',
    'webull_app_key', 'webull_app_secret', 'webull_access_token',
    'credentials_encryption_key',
} | {f'{provider}_key{suffix}' for provider in
     ('openai', 'zai', 'perplexity', 'gemini', 'inception', 'ollama') for suffix in
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


def decision_credential_status(credential, master_ai_config=None):
    """Confirm usable stored values without returning keys or key fingerprints."""
    values = {}
    for field in ('ai_gateway_key', 'openrouter_api_key', 'subq_api_key', 'inception_decisions_key'):
        value = getattr(credential, field, None) if credential else None
        configured = bool(value and value.strip() and value.strip() != MASK)
        values[field] = MASK if configured else ''
        values[field + '_configured'] = configured
    if not values['inception_decisions_key_configured']:
        # Mercury Decide shares the general Inception key, including the one
        # saved in the dedicated audit cascade, so readiness must reflect it.
        from services.decision_settings import key_for_transport
        shared = key_for_transport(credential, 'inception', master_ai_config)
        values['inception_decisions_key_configured'] = bool(shared and shared != MASK)
    return values


def decision_status_for_user(user_id, credential):
    from portfolio_algo_models import PortfolioStrategyConfig
    row = PortfolioStrategyConfig.query.filter_by(user_id=user_id).first()
    return decision_credential_status(credential, row.master_ai_config if row else None)
