"""Resumable onboarding defaults and completion rules.

Only explicitly approved, non-secret configuration is snapshotted. Each new
user receives an independent database copy; the source account is never read
again during that user's onboarding.
"""

import json
from core.extensions import db
from credentials import OnboardingDefaultProfile, UserSetting
from models import AIPrompt, DefaultAIPrompt


SETTING_DEFAULT_FIELDS = (
    'tax_cost_basis_method', 'volatility_hours',
    'automated_trigger_confirmation_minutes', 'max_slippage_pct',
    'sentiment_analysis_frequency_hours',
    'watchlist_sentiment_analysis_frequency_hours',
    'sentiment_history_lookback_hours',
    'watchlist_sentiment_history_lookback_hours',
    'sentiment_forecast_horizon_hours',
    'watchlist_sentiment_forecast_horizon_hours',
    'portfolio_schedule_start_time', 'watchlist_schedule_start_time',
    'ai_outcome_neutral_threshold_pct',
    'sentiment_buy_immediately_correct_pct',
    'sentiment_buy_immediately_wrong_pct',
    'sentiment_consider_buying_correct_pct',
    'sentiment_consider_buying_wrong_pct',
    'sentiment_hold_correct_pct', 'sentiment_hold_wrong_pct',
    'sentiment_hold_steady_pct',
    'sentiment_consider_selling_correct_pct',
    'sentiment_consider_selling_wrong_pct',
    'sentiment_sell_immediately_correct_pct',
    'sentiment_sell_immediately_wrong_pct',
    'sentiment_chart_default_range',
)

PROMPT_DEFAULT_FIELDS = (
    'market_analysis_pre', 'market_analysis_post',
    'risk_assessment_pre', 'risk_assessment_post',
    'portfolio_review_pre', 'portfolio_review_post',
    'coin_analysis_pre', 'coin_analysis_post',
    'sentiment_prompt_pre', 'sentiment_prompt_post',
    'watchlist_sentiment_prompt_pre', 'watchlist_sentiment_prompt_post',
    'news_analysis_pre', 'news_analysis_post',
    'copilot_chat_pre', 'copilot_chat_post',
)

ONBOARDING_PAGES = {
    'security-choice', 'security-setup', 'exchanges', 'binance', 'webull',
    'webull-accounts', 'ai-choice', 'ai-primary', 'ai-secondary',
    'ai-tertiary', 'ai-quartan', 'search-news', 'telegram', 'review',
}


def _clean_json(raw):
    try:
        value = json.loads(raw or '{}')
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def snapshot_defaults(source_user_id):
    """Replace the single seed profile from one user's non-secret settings."""
    source_settings = UserSetting.query.filter_by(user_id=source_user_id).first()
    if not source_settings:
        raise ValueError('The source user has no settings record.')
    source_prompts = AIPrompt.query.filter_by(user_id=source_user_id).first()
    settings_payload = {
        field: getattr(source_settings, field)
        for field in SETTING_DEFAULT_FIELDS
        if hasattr(source_settings, field)
    }
    prompts_payload = {
        field: getattr(source_prompts, field)
        for field in PROMPT_DEFAULT_FIELDS
        if source_prompts is not None and hasattr(source_prompts, field)
    }
    profile = db.session.get(OnboardingDefaultProfile, 1)
    if not profile:
        profile = OnboardingDefaultProfile(id=1)
        db.session.add(profile)
    profile.settings_json = json.dumps(settings_payload)
    profile.prompts_json = json.dumps(prompts_payload)
    db.session.flush()
    return profile


def seed_new_user_defaults(user_id, user_setting=None):
    """Copy the stored profile (or application defaults) to a new user."""
    setting = user_setting or UserSetting.query.filter_by(user_id=user_id).first()
    if not setting:
        setting = UserSetting(user_id=user_id)
        db.session.add(setting)

    profile = db.session.get(OnboardingDefaultProfile, 1)
    settings_payload = _clean_json(profile.settings_json) if profile else {}
    for field, value in settings_payload.items():
        if field in SETTING_DEFAULT_FIELDS and hasattr(setting, field):
            setattr(setting, field, value)
    setting.tax_cost_basis_method = setting.tax_cost_basis_method or 'fifo'

    prompts = AIPrompt.query.filter_by(user_id=user_id).first()
    if not prompts:
        prompts = AIPrompt(user_id=user_id)
        db.session.add(prompts)
    prompt_payload = _clean_json(profile.prompts_json) if profile else {}
    if not prompt_payload:
        default_prompts = DefaultAIPrompt.query.first()
        if default_prompts:
            prompt_payload = {
                field: getattr(default_prompts, field, '')
                for field in PROMPT_DEFAULT_FIELDS
            }
    for field, value in prompt_payload.items():
        if field in PROMPT_DEFAULT_FIELDS and hasattr(prompts, field):
            setattr(prompts, field, value)
    return setting, prompts


def exchange_requirement_met(setting):
    choice = (getattr(setting, 'onboarding_exchange_choice', None) or '').lower()
    binance_ok = bool(getattr(setting, 'onboarding_binance_verified', False))
    webull_ok = bool(getattr(setting, 'onboarding_webull_verified', False))
    if choice == 'binance':
        return binance_ok
    if choice == 'webull':
        return webull_ok
    if choice == 'both':
        return binance_ok or webull_ok
    return False
