from services.prompt_catalog import default_prompt
import json
import datetime
import logging
from log import logger
from core.extensions import db
from models import AICache, AIPrompt, AIAnalysisSchedule, AIConversation
from credentials import UserSetting
from services.copilot_context import DEFAULT_COPILOT_RESPONSE_PROMPT, DEFAULT_COPILOT_SEARCH_PROMPT

def get_ai_cache(user_id, cache_key, cache_type):
    """Get cached AI analysis result"""
    try:
        cache = AICache.query.filter_by(
            user_id=user_id, 
            cache_key=cache_key, 
            cache_type=cache_type
        ).first()
        
        if cache:
            # Check if cache is still valid
            if cache.expires_at > datetime.datetime.utcnow():
                cache_content = getattr(cache, 'data', None) or getattr(cache, 'result_json', None)
                return json.loads(cache_content) if cache_content else None
            else:
                db.session.delete(cache)
                db.session.commit()
        return None
    except Exception as e:
        logger.error(f"Error getting AI cache: {e}")
        return None

def set_ai_cache(user_id, cache_key, cache_type, result, duration_hours=24):
    """Cache AI analysis result"""
    try:
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=duration_hours)
        cache = AICache.query.filter_by(
            user_id=user_id, 
            cache_key=cache_key, 
            cache_type=cache_type
        ).first()
        
        serialized = json.dumps(result)
        if cache:
            cache.data = serialized
            cache.expires_at = expires_at
        else:
            cache = AICache(
                user_id=user_id,
                cache_key=cache_key,
                cache_type=cache_type,
                data=serialized,
                expires_at=expires_at
            )
            db.session.add(cache)
        db.session.commit()
    except Exception as e:
        logger.error(f"Error setting AI cache: {e}")
        db.session.rollback()

def is_ai_enabled(username):
    """Check if AI is enabled for a user"""
    try:
        from credentials import User
        user = User.query.filter_by(username=username).first()
        if not user: return False
        
        settings = UserSetting.query.filter_by(user_id=user.id).first()
        return settings.ai_enabled if settings else False
    except:
        return False

def get_user_ai_settings(username: str) -> dict:
    """
    Return AI/user settings merged with defaults.
    - Loads defaults from database first, fallback to built-in defaults
    - Overlays values from credentials (ai_provider only)
    - Overlays per-user entries from user_settings table
    - Normalizes time strings and fixes '24:00' -> '23:59'
    """
    try:
        from credentials import User, UserSetting
        from models import DefaultAIPrompt

        settings = {
            'ai_enabled': True,
            'ai_provider': '',
            'ai_model': '',
            'ai_reasoning_level': 'medium',
            'ai_provider_fallback': '',
            'ai_model_fallback': '',
            'ai_reasoning_level_fallback': 'medium',
            'ai_provider_secondary': '',
            'ai_model_secondary': '',
            'ai_reasoning_level_secondary': 'medium',
            'ai_provider_tertiary': '',
            'ai_model_tertiary': '',
            'ai_reasoning_level_tertiary': 'medium',
            'ai_provider_quaternary': '',
            'ai_model_quaternary': '',
            'ai_reasoning_level_quaternary': 'medium',
            'ai_cache_duration_hours': 1,
            'ai_confidence_threshold': 70,
            'ai_risk_tolerance': 'moderate',
            'ai_analysis_window_start': '08:00',
            'ai_analysis_window_end': '23:59',
            'ai_notifications_enabled': True,
            'ai_max_tokens': 800,
            'ai_web_search_enabled': True,
            'tax_manual_invested_updated': None,
            'tax_cost_basis_method': 'fifo',
            'credentials_encryption_key_configured': False,
            'ai_prompts': {
                'market_analysis_pre': '',
                'market_analysis_post': '',
                'portfolio_review_pre': '',
                'portfolio_review_post': '',
                'coin_analysis_pre': '',
                'coin_analysis_post': '',
                'sentiment_prompt_pre': '',
                'sentiment_prompt_post': '',
                'watchlist_sentiment_prompt_pre': '',
                'watchlist_sentiment_prompt_post': '',
            },
            'copilot_chat_pre': DEFAULT_COPILOT_SEARCH_PROMPT,
            'copilot_chat_post': DEFAULT_COPILOT_RESPONSE_PROMPT,
            'copilot_title_prompt': default_prompt('seed.analysis.copilot_title_prompt'),
            'event_strategy_audit_prompt': (
                default_prompt('seed.analysis.event_strategy_audit_prompt')
            ),
            'portfolio_schedule_start_time': '08:00',
            'watchlist_schedule_start_time': '08:00',
            'sentiment_analysis_frequency_hours': 24,
            'watchlist_sentiment_analysis_frequency_hours': 24,
            'sentiment_history_lookback_hours': 12,
            'watchlist_sentiment_history_lookback_hours': 12,
            'sentiment_forecast_horizon_hours': 24,
            'watchlist_sentiment_forecast_horizon_hours': 24,
            'volatility_hours': 24,
            'automated_trigger_confirmation_minutes': 15,
            'sentiment_buy_immediately_correct_pct': 5.0,
            'sentiment_buy_immediately_wrong_pct': 5.0,
            'sentiment_consider_buying_correct_pct': 5.0,
            'sentiment_consider_buying_wrong_pct': 5.0,
            'sentiment_hold_steady_pct': 1.0,
            'sentiment_hold_wrong_pct': 5.0,
            'sentiment_consider_selling_correct_pct': 5.0,
            'sentiment_consider_selling_wrong_pct': 5.0,
            'sentiment_sell_immediately_correct_pct': 5.0,
            'sentiment_sell_immediately_wrong_pct': 5.0,
            'sentiment_chart_default_range': '3d',
            'ai_prompts': {
                'market_analysis_pre': (
                    default_prompt('seed.analysis.market_analysis_pre')
                ),
                'market_analysis_post': (
                    default_prompt('seed.analysis.market_analysis_post')
                ),
                'portfolio_review_pre': (
                    default_prompt('seed.analysis.portfolio_review_pre')
                ),
                'portfolio_review_post': (
                    default_prompt('seed.analysis.portfolio_review_post')
                ),
                'coin_analysis_pre': (
                    default_prompt('seed.analysis.coin_analysis_pre')
                ),
                'coin_analysis_post': (
                    default_prompt('seed.analysis.coin_analysis_post')
                ),
                'sentiment_prompt_pre': (
                    default_prompt('seed.analysis.sentiment_prompt_pre')
                ),
                'sentiment_prompt_post': (
                    default_prompt('seed.analysis.sentiment_prompt_post')
                ),
                'watchlist_sentiment_prompt_pre': (
                    default_prompt('seed.analysis.watchlist_sentiment_prompt_pre')
                ),
                'watchlist_sentiment_prompt_post': (
                    default_prompt('seed.analysis.watchlist_sentiment_prompt_post')
                ),
            },
        }

        user_obj = User.query.filter_by(username=username).first()
        if user_obj:
            try:
                user_setting = UserSetting.query.filter_by(user_id=user_obj.id).first()
            except Exception as e:
                logger.error(f"Error querying UserSetting for {username}: {e}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
                user_setting = None
            if user_setting:
                settings['ai_enabled'] = user_setting.ai_enabled
                settings['ai_provider'] = user_setting.ai_provider
                settings['ai_model'] = user_setting.ai_model
                settings['ai_reasoning_level'] = getattr(user_setting, 'ai_reasoning_level', 'medium') or 'medium'
                
                secondary = getattr(user_setting, 'ai_provider_secondary', None)
                prefix = 'secondary' if secondary is not None else 'fallback'
                for field in ('provider', 'model', 'reasoning_level'):
                    value = getattr(user_setting, f'ai_{field}_{prefix}', None)
                    settings[f'ai_{field}_secondary'] = value
                    settings[f'ai_{field}_fallback'] = value

                settings['ai_provider_tertiary'] = getattr(user_setting, 'ai_provider_tertiary', '')
                settings['ai_model_tertiary'] = getattr(user_setting, 'ai_model_tertiary', '')
                settings['ai_reasoning_level_tertiary'] = getattr(user_setting, 'ai_reasoning_level_tertiary', 'medium') or 'medium'
                settings['ai_provider_quaternary'] = getattr(user_setting, 'ai_provider_quaternary', '')
                settings['ai_model_quaternary'] = getattr(user_setting, 'ai_model_quaternary', '')
                settings['ai_reasoning_level_quaternary'] = getattr(user_setting, 'ai_reasoning_level_quaternary', 'medium') or 'medium'

                settings['ai_risk_tolerance'] = user_setting.ai_risk_tolerance
                settings['ai_confidence_threshold'] = user_setting.ai_confidence_threshold
                settings['ai_notifications_enabled'] = user_setting.ai_notifications_enabled
                settings['ai_analysis_frequency'] = user_setting.ai_analysis_frequency
                settings['ai_cache_duration_hours'] = user_setting.ai_cache_duration_hours
                settings['ai_analysis_window_start'] = user_setting.ai_analysis_window_start
                settings['ai_analysis_window_end'] = user_setting.ai_analysis_window_end
                settings['ai_max_tokens'] = user_setting.ai_max_tokens
                settings['ai_web_search_enabled'] = user_setting.ai_web_search_enabled
                settings['tax_manual_invested_updated'] = user_setting.tax_manual_invested_updated
                settings['tax_cost_basis_method'] = user_setting.tax_cost_basis_method
                settings['credentials_encryption_key_configured'] = user_setting.credentials_encryption_key_configured

                if hasattr(user_setting, 'copilot_chat_pre') and user_setting.copilot_chat_pre:
                    settings['copilot_chat_pre'] = user_setting.copilot_chat_pre
                if hasattr(user_setting, 'copilot_chat_post') and user_setting.copilot_chat_post:
                    settings['copilot_chat_post'] = user_setting.copilot_chat_post
                if hasattr(user_setting, 'copilot_title_prompt') and user_setting.copilot_title_prompt:
                    settings['copilot_title_prompt'] = user_setting.copilot_title_prompt
                if hasattr(user_setting, 'event_strategy_audit_prompt') and user_setting.event_strategy_audit_prompt:
                    settings['event_strategy_audit_prompt'] = user_setting.event_strategy_audit_prompt

                if hasattr(user_setting, 'sentiment_analysis_frequency_hours'):
                    settings['sentiment_analysis_frequency_hours'] = user_setting.sentiment_analysis_frequency_hours or 24

                if hasattr(user_setting, 'watchlist_sentiment_analysis_frequency_hours'):
                    settings['watchlist_sentiment_analysis_frequency_hours'] = user_setting.watchlist_sentiment_analysis_frequency_hours or 24

                if hasattr(user_setting, 'sentiment_history_lookback_hours'):
                    settings['sentiment_history_lookback_hours'] = user_setting.sentiment_history_lookback_hours or 12

                if hasattr(user_setting, 'watchlist_sentiment_history_lookback_hours'):
                    settings['watchlist_sentiment_history_lookback_hours'] = user_setting.watchlist_sentiment_history_lookback_hours or 12

                portfolio_frequency = settings.get('sentiment_analysis_frequency_hours', 24)
                watchlist_frequency = settings.get('watchlist_sentiment_analysis_frequency_hours', 24)
                settings['sentiment_forecast_horizon_hours'] = (
                    getattr(user_setting, 'sentiment_forecast_horizon_hours', None) or portfolio_frequency
                )
                settings['watchlist_sentiment_forecast_horizon_hours'] = (
                    getattr(user_setting, 'watchlist_sentiment_forecast_horizon_hours', None) or watchlist_frequency
                )

                if hasattr(user_setting, 'portfolio_schedule_start_time'):
                    settings['portfolio_schedule_start_time'] = user_setting.portfolio_schedule_start_time or '08:00'

                if hasattr(user_setting, 'watchlist_schedule_start_time'):
                    settings['watchlist_schedule_start_time'] = user_setting.watchlist_schedule_start_time or '08:00'

                if hasattr(user_setting, 'volatility_hours'):
                    settings['volatility_hours'] = user_setting.volatility_hours or 24

                if hasattr(user_setting, 'automated_trigger_confirmation_minutes'):
                    settings['automated_trigger_confirmation_minutes'] = user_setting.automated_trigger_confirmation_minutes or 15

                settings['ai_outcome_neutral_threshold_pct'] = float(getattr(user_setting, 'ai_outcome_neutral_threshold_pct', 5.0) or 5.0)
                from services.sentiment_outcome_service import (
                    DEFAULT_SENTIMENT_CHART_RANGE,
                    HOLD_VARIABLE,
                    SENTIMENT_CHART_RANGE_VALUES,
                    SENTIMENT_THRESHOLD_FIELDS,
                )
                for field in SENTIMENT_THRESHOLD_FIELDS:
                    default_value = 1.0 if field == HOLD_VARIABLE['steady_field'] else 5.0
                    stored_value = getattr(user_setting, field, None)
                    settings[field] = float(default_value if stored_value is None else stored_value)
                stored_chart_range = str(
                    getattr(user_setting, 'sentiment_chart_default_range', '') or ''
                ).strip().lower()
                settings['sentiment_chart_default_range'] = (
                    stored_chart_range
                    if stored_chart_range in SENTIMENT_CHART_RANGE_VALUES
                    else DEFAULT_SENTIMENT_CHART_RANGE
                )
                settings['max_slippage_pct'] = float(getattr(user_setting, 'max_slippage_pct', 2.0) or 2.0)

                b_enabled = getattr(user_setting, 'browser_notifications_enabled', True)
                if b_enabled is None:
                    b_enabled = True
                settings['browser_notifications_enabled'] = bool(b_enabled)
                settings['toast_notifications_enabled'] = bool(b_enabled)
                settings['telegram_notifications_enabled'] = getattr(user_setting, 'telegram_notifications_enabled', True) is not False

        # Saved provider/model values are authoritative. Do not reinterpret an
        # unavailable model or a restricted provider as an OpenAI selection.
        for suffix in ('', '_fallback', '_secondary', '_tertiary', '_quaternary'):
            settings[f'ai_provider{suffix}'] = str(settings.get(f'ai_provider{suffix}') or '').strip().lower()
            settings[f'ai_model{suffix}'] = str(settings.get(f'ai_model{suffix}') or '').strip()

        def _fix_time(s: str, default: str) -> str:
            try:
                s = (s or '').strip()
                if s == '24:00':
                    return '23:59'
                parts = s.split(':')
                if len(parts) < 2:
                    return default
                hh = int(parts[0])
                mm = int(parts[1])
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    return default
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return default

        settings['ai_analysis_window_start'] = _fix_time(settings.get('ai_analysis_window_start', '08:00'), '08:00')
        settings['ai_analysis_window_end'] = _fix_time(settings.get('ai_analysis_window_end', '23:59'), '23:59')

        if user_obj:
            ai_prompts_obj = get_user_ai_prompts(user_obj.id)
            if ai_prompts_obj:
                settings['ai_prompts'] = {
                    'market_analysis_pre': getattr(ai_prompts_obj, 'market_analysis_pre', settings['ai_prompts']['market_analysis_pre']),
                    'market_analysis_post': getattr(ai_prompts_obj, 'market_analysis_post', settings['ai_prompts']['market_analysis_post']),
                    'portfolio_review_pre': getattr(ai_prompts_obj, 'portfolio_review_pre', settings['ai_prompts']['portfolio_review_pre']),
                    'portfolio_review_post': getattr(ai_prompts_obj, 'portfolio_review_post', settings['ai_prompts']['portfolio_review_post']),
                    'coin_analysis_pre': getattr(ai_prompts_obj, 'coin_analysis_pre', settings['ai_prompts']['coin_analysis_pre']),
                    'coin_analysis_post': getattr(ai_prompts_obj, 'coin_analysis_post', settings['ai_prompts']['coin_analysis_post']),
                    'sentiment_prompt_pre': getattr(ai_prompts_obj, 'sentiment_prompt_pre', settings['ai_prompts']['sentiment_prompt_pre']),
                    'sentiment_prompt_post': getattr(ai_prompts_obj, 'sentiment_prompt_post', settings['ai_prompts']['sentiment_prompt_post']),
                    'watchlist_sentiment_prompt_pre': getattr(ai_prompts_obj, 'watchlist_sentiment_prompt_pre', settings['ai_prompts']['watchlist_sentiment_prompt_pre']),
                    'watchlist_sentiment_prompt_post': getattr(ai_prompts_obj, 'watchlist_sentiment_prompt_post', settings['ai_prompts']['watchlist_sentiment_prompt_post']),
                }
            
            if not settings.get('copilot_chat_pre') or not settings.get('event_strategy_audit_prompt'):
                def_prompts = DefaultAIPrompt.query.first()
                if def_prompts:
                    if not settings.get('copilot_chat_pre'):
                        settings['copilot_chat_pre'] = def_prompts.copilot_chat_pre
                        settings['copilot_chat_post'] = def_prompts.copilot_chat_post
                    if not settings.get('event_strategy_audit_prompt') and getattr(def_prompts, 'event_strategy_audit_prompt', None):
                        settings['event_strategy_audit_prompt'] = def_prompts.event_strategy_audit_prompt

        from services.jev_settings import settings_for as jev_settings_for
        settings.update(jev_settings_for(locals().get('user_setting')))
        return settings
    except Exception as e:
        logger.error(f"Error building user AI settings for {username}: {e}")
        return {}

def calculate_volatility(price_data):
    if not price_data or len(price_data) < 2: return 0.0
    import statistics
    returns = [(price_data[i] - price_data[i-1]) / price_data[i-1] for i in range(1, len(price_data)) if price_data[i-1] > 0]
    return statistics.stdev(returns) if len(returns) > 1 else 0.0

def calculate_symbol_snapshot(symbol, get_last_7d_prices_func):
    """Compute technical snapshot for a symbol"""
    try:
        price_data = get_last_7d_prices_func(symbol)
        if not price_data or len(price_data) < 2: return None
        
        current_price = float(price_data[-1])
        volatility = calculate_volatility(price_data)
        
        # simplified for brevity in this refactor
        return {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "volatility": volatility,
            "technical_score": 70, # mock
            "signal": "HOLD"
        }
    except Exception as e:
        logger.error(f"Error calculating snapshot for {symbol}: {e}")
        return None


def get_user_ai_prompts(user_id):
    from models import AIPrompt
    try:
        ai_prompts = AIPrompt.query.filter_by(user_id=user_id).first()
        if not ai_prompts:
            ai_prompts = AIPrompt(
                user_id=user_id,
                market_analysis_pre="", market_analysis_post="",
                portfolio_review_pre="", portfolio_review_post="",
                coin_analysis_pre="", coin_analysis_post="",
                sentiment_prompt_pre="", sentiment_prompt_post="",
                watchlist_sentiment_prompt_pre="", watchlist_sentiment_prompt_post=""
            )
            db.session.add(ai_prompts)
            db.session.commit()
        return ai_prompts
    except Exception as e:
        logger.error(f"Error getting AI prompts: {e}")
        return None

def get_ai_conversations(user_id, limit=20, offset=0):
    from models import AIConversation
    return AIConversation.query.filter_by(user_id=user_id).order_by(AIConversation.id.desc()).limit(limit).offset(offset).all()

def log_ai_communication(user_id, prompt_type, message):
    # simplified
    pass
