"""The one place user preferences from Settings are validated and saved.

Both settings endpoints use this writer, so a field saves the same way
wherever it is edited, and an invalid value is reported instead of being
silently dropped while the page says "saved".
"""
from services.sentiment_outcome_service import SENTIMENT_THRESHOLD_FIELDS

BOOL_FIELDS = {
    'ai_enabled', 'ai_notifications_enabled', 'ai_web_search_enabled',
    'browser_notifications_enabled', 'telegram_notifications_enabled',
}
# field: (label, minimum, maximum)
INT_FIELDS = {
    'ai_max_tokens': ('Max Tokens per Request', 500, 8000),
    'ai_cache_duration_hours': ('AI cache duration', 0, 168),
    'sentiment_analysis_frequency_hours': ('Portfolio sentiment frequency', 1, 168),
    'watchlist_sentiment_analysis_frequency_hours': ('Watchlist sentiment frequency', 1, 168),
    'sentiment_history_lookback_hours': ('Portfolio history lookback', 1, 72),
    'watchlist_sentiment_history_lookback_hours': ('Watchlist history lookback', 1, 72),
    'sentiment_forecast_horizon_hours': ('Portfolio forecast horizon', 1, 168),
    'watchlist_sentiment_forecast_horizon_hours': ('Watchlist forecast horizon', 1, 168),
    'volatility_hours': ('Volatility Hours', 1, 720),
    'automated_trigger_confirmation_minutes': ('Automated Trigger Confirmation Window', 1, 1440),
}
FLOAT_FIELDS = {
    'ai_confidence_threshold': ('AI confidence threshold', 0, 100),
    'ai_outcome_neutral_threshold_pct': ('AI outcome neutral threshold', 0, 100),
    'max_slippage_pct': ('Max slippage', 0, 50),
    **{field: (field.replace('_', ' '), 0, 100) for field in SENTIMENT_THRESHOLD_FIELDS},
}
STR_FIELDS = {
    'ai_provider', 'ai_model', 'ai_reasoning_level', 'ai_risk_tolerance', 'ai_analysis_frequency',
    'ai_analysis_window_start', 'ai_analysis_window_end', 'tax_cost_basis_method',
    'copilot_chat_pre', 'copilot_chat_post', 'copilot_title_prompt', 'event_strategy_audit_prompt',
    'portfolio_schedule_start_time', 'watchlist_schedule_start_time', 'webull_environment',
    'sentiment_chart_default_range', 'tax_manual_invested_updated',
    *[f'{kind}_{tier}' for kind in ('ai_provider', 'ai_model', 'ai_reasoning_level')
      for tier in ('fallback', 'secondary', 'tertiary', 'quaternary')],
}
PROMPT_FIELDS = (
    'market_analysis_pre', 'market_analysis_post', 'risk_assessment_pre', 'risk_assessment_post',
    'portfolio_review_pre', 'portfolio_review_post', 'coin_analysis_pre', 'coin_analysis_post',
    'news_analysis_pre', 'news_analysis_post',
    'sentiment_prompt_pre', 'sentiment_prompt_post',
    'watchlist_sentiment_prompt_pre', 'watchlist_sentiment_prompt_post',
    'event_strategy_audit_prompt', 'copilot_title_prompt',
)


def normalize_aliases(data):
    """The toast toggle is the browser-notification setting under another name.

    The Settings page sends both keys; the toast control is the one the user
    edits, so it wins over the stale copy of the other key.
    """
    if 'toast_notifications_enabled' in data:
        data['browser_notifications_enabled'] = data.pop('toast_notifications_enabled')
    return data


def validate(data):
    """Return {field: message} for values that cannot be saved."""
    errors = {}
    if data.get('webull_environment') is not None:
        from services.webull_service import WebullConnectionError, normalize_webull_environment
        try:
            data['webull_environment'] = normalize_webull_environment(data['webull_environment'])
        except WebullConnectionError as exc:
            errors['webull_environment'] = str(exc)
    if data.get('tax_cost_basis_method') is not None:
        method = str(data['tax_cost_basis_method']).strip().lower()
        if method not in {'fifo', 'lifo', 'hifo'}:
            errors['tax_cost_basis_method'] = 'Cost basis method must be FIFO, LIFO or HIFO.'
        else:
            data['tax_cost_basis_method'] = method
    for field, (label, low, high) in INT_FIELDS.items():
        if field not in data or data[field] in (None, ''):
            continue
        try:
            value = float(data[field])
            if value != int(value):
                raise ValueError
            value = int(value)
        except (TypeError, ValueError):
            errors[field] = f'{label} must be a whole number.'
            continue
        if not low <= value <= high:
            errors[field] = f'{label} must be from {low} through {high}.'
    for field, (label, low, high) in FLOAT_FIELDS.items():
        if field not in data or data[field] in (None, ''):
            continue
        try:
            value = float(data[field])
        except (TypeError, ValueError):
            errors[field] = f'{label} must be a number.'
            continue
        if not low <= value <= high:
            errors[field] = f'{label} must be from {low:g} through {high:g}.'
    return errors


def apply(user_setting, data, prompt_record_loader=None):
    """Write validated values; call ``validate`` first."""
    for key, value in data.items():
        if key == 'ai_prompts' and isinstance(value, dict) and prompt_record_loader:
            prompts = prompt_record_loader()
            for field in PROMPT_FIELDS:
                if field in value:
                    setattr(prompts, field, value[field])
            continue
        if key in BOOL_FIELDS:
            setattr(user_setting, key, value if isinstance(value, bool) else str(value).strip().lower() in {'1', 'true', 'yes', 'on'})
        elif key in INT_FIELDS:
            if value not in (None, ''):
                setattr(user_setting, key, int(float(value)))
        elif key in FLOAT_FIELDS:
            if value not in (None, ''):
                setattr(user_setting, key, float(value))
        elif key in STR_FIELDS:
            setattr(user_setting, key, None if value is None else str(value))
