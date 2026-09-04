import json
import datetime
import logging
from log import logger
from core.extensions import db
from models import AICache, AIPrompt, AIAnalysisSchedule, AIConversation
from credentials import UserSetting
from event_algo import is_event_strategy_admin

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
            'ai_provider': 'openai',
            'ai_model': 'gpt-5',
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
            'ai_provider_quartan': '',
            'ai_model_quartan': '',
            'ai_reasoning_level_quartan': 'medium',
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
            'copilot_chat_pre': (
                "You are the search intelligence module for the AI Copilot in Crypto & Securities Dashboard as of {datetime}. "
                "You assist an active multi-asset trader and portfolio manager who has real-time access to their live portfolio holdings, watchlist assets, pending orders, execution logs, and sentiment ratings across both Binance.US (cryptocurrency) and Webull (cryptocurrency, equities, ETFs, options). "
                "Analyze the user's inquiry and selected isolated chat session to generate 1 to 3 targeted, highly effective searches for current market data, breaking news, earnings, regulatory developments, technical momentum, or protocol updates. Treat any separately supplied live account snapshot as authoritative over historical chat text."
            ),
            'copilot_chat_post': (
                "You are the AI Copilot for Crypto & Securities Dashboard, an expert cross-asset portfolio strategist and multi-market analyst. "
                "You have direct access to the user's live portfolio, watchlist, pending orders, execution history, recent sentiment ratings & reasons, and the selected isolated Copilot session across Binance.US and Webull as of {datetime}. Earlier sessions are historical reference only when explicitly supplied.\n\n"
                "When answering the user:\n"
                "- Provide actionable, data-backed guidance considering technical momentum, sentiment ratings, risk/reward, and current portfolio exposure across both digital assets and traditional securities.\n"
                "- When referencing sentiment signals (e.g. 'Consider Selling', 'Consider Buying', 'Hold'), explain the underlying market drivers, catalysts, and whether contrarian opportunities or caution are warranted.\n"
                "- Directly address proposed trades, limit/stop orders, entry/exit price targets, and market trends with clear reasoning for both crypto and equities.\n"
                "- For every crypto or security question, use fresh web-search results for time-sensitive claims. For an owned or watched asset, verify ownership, balances, orders, and watchlist status against the live database snapshot in this request; never substitute old chat context.\n"
                "- CRITICAL EXCHANGE ARCHITECTURE RULE (OCO ORDERS): On Binance and Binance.US, an OCO (One-Cancels-the-Other) order is natively created and managed by the exchange matching engine as an Order List (orderListId) containing two linked legs: a STOP_LOSS_LIMIT leg and a LIMIT_MAKER leg. When the user's data shows an active OCO order bracket with an OrderListId or paired limit/stop-loss legs, this IS a confirmed, native, fully linked exchange OCO order. The exchange automatically cancels the opposing leg if either executes or triggers. NEVER tell the user their OCO orders are 'separate independent orders', 'unlinked', or that 'Binance.US does not support an OCO wrapper'. NEVER instruct the user to 'link them into an OCO order'—they are ALREADY natively linked on the exchange. Analyze them directly as a unified OCO trading strategy.\n"
                "- Maintain a concise, structured, and professional tone with bullet points where appropriate."
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
                    "You are an intelligent search query generator for comprehensive market analysis across cryptocurrency and traditional securities (equities and ETFs) as of {datetime}. "
                    "Analyze the current macro landscape, including crypto market trends, major equity indices (S&P 500, Nasdaq), Federal Reserve interest rate expectations, sector rotations, and breaking geopolitical/economic news. "
                    "Generate 1 to 3 targeted, highly effective search queries to gather real-time data on both digital assets and securities markets."
                ),
                'market_analysis_post': (
                    "You are a premier cross-asset market strategist specializing in both cryptocurrency (Binance.US / Webull) and traditional securities (equities and ETFs on Webull) as of {datetime}. "
                    "Synthesize the provided web search results, market indicators, and macroeconomic developments into a cohesive market briefing.\n\n"
                    "Evaluate:\n"
                    "1. Macroeconomic environment (interest rates, inflation, treasury yields, dollar strength).\n"
                    "2. Cryptocurrency market momentum, Bitcoin/Ethereum trend strength, and altcoin dynamics.\n"
                    "3. Equity market trend, sector leadership, and risk-on vs. risk-off sentiment.\n"
                    "4. Cross-market correlation and actionable tactical outlook for active traders.\n\n"
                    "Provide a structured, executive-ready analysis with concise bullet points and clear risk parameters."
                ),
                'portfolio_review_pre': (
                    "You are an intelligent search query generator for multi-asset portfolio review as of {datetime}. "
                    "The portfolio contains holdings across both cryptocurrency (Binance.US, Webull) and traditional securities/equities (Webull). "
                    "Generate 1 to 3 targeted search queries to identify breaking news, recent earnings, technical momentum shifts, and regulatory catalysts impacting these specific holdings and their respective asset classes."
                ),
                'portfolio_review_post': (
                    "You are a professional portfolio manager and multi-asset strategist evaluating a unified portfolio of cryptocurrency (Binance.US / Webull) and securities (equities, ETFs, options on Webull) as of {datetime}. "
                    "Based on current live prices, cost basis, unrealized P&L, asset weighting, and recent web search news:\n"
                    "1. Assess portfolio risk balance between high-volatility crypto and equity allocations.\n"
                    "2. Identify top outperforming positions, concentration risks, and underperforming assets.\n"
                    "3. Highlight near-term catalysts (earnings, protocol upgrades, macro events) affecting key holdings.\n"
                    "4. Provide actionable portfolio rebalancing, risk mitigation, and profit-taking/stop-loss recommendations.\n\n"
                    "Format your response clearly with concise sections and actionable takeaways."
                ),
                'coin_analysis_pre': (
                    "You are an intelligent search query generator for single-asset research as of {datetime}. "
                    "The target asset is {symbol}, which may be a cryptocurrency or a traditional equity/ETF/security traded on Binance.US or Webull. "
                    "Generate 1 to 3 targeted search queries to find the latest breaking news, technical price action, earnings reports, regulatory updates, or protocol developments for {symbol}."
                ),
                'coin_analysis_post': (
                    "You are a senior investment analyst evaluating {symbol} as of {datetime}. "
                    "Whether {symbol} is a cryptocurrency or traditional equity/security, synthesize the live price data, consecutive hourly price/volume dynamics, and recent web search findings to deliver an in-depth asset evaluation:\n"
                    "1. Key Drivers & Catalysts: Summarize recent news, corporate earnings or protocol updates, and macroeconomic tailwinds/headwinds.\n"
                    "2. Technical & Volume Assessment: Analyze price momentum, key support/resistance levels, and volume behavior.\n"
                    "3. Risk/Reward Profile: Evaluate downside risks versus upside potential over the immediate and medium horizons.\n"
                    "4. Strategic Conclusion: Clear, definitive outlook on whether to buy, hold, accumulate on dips, or trim exposure.\n\n"
                    "Keep your analysis objective, data-driven, and well-structured."
                ),
                'sentiment_prompt_pre': (
                    "You are an intelligent search query generator for multi-asset sentiment analysis as of {datetime}. "
                    "I currently hold {amount} of {symbol} in my portfolio (cryptocurrency or equity/security). "
                    "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} to evaluate my position."
                ),
                'sentiment_prompt_post': (
                    "You are a cross-asset financial analysis expert with access to current web search results, live pricing, and historical price/volume data for {symbol} as of {datetime}. "
                    "I currently hold {amount} of {symbol} in my portfolio across my connected exchange/broker accounts (Binance.US or Webull). "
                    "Based on the current live price, the consecutive hourly price & volume history, recent market data, price trends, volume dynamics, catalysts, and risk/reward provided, evaluate whether I should hold, accumulate more, or take profits/cut losses on this holding.\n\n"
                    "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
                    "{\n"
                    '  "sentiment": "<one of: Buy Immediately, Consider Buying, Hold, Consider Selling, Sell Immediately>",\n'
                    '  "reason": "<1-2 sentences explaining your recommendation based on the live price, hourly price/volume dynamics, position risk/reward, and recent news>"\n'
                    "}\n\n"
                    "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
                ),
                'watchlist_sentiment_prompt_pre': (
                    "You are an intelligent search query generator for watchlist evaluation as of {datetime}. "
                    "I am currently monitoring {symbol} on my watchlist as a prospective investment opportunity (cryptocurrency or equity/security). "
                    "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} to evaluate whether now is an attractive entry point."
                ),
                'watchlist_sentiment_prompt_post': (
                    "You are a cross-asset financial analysis expert with access to current web search results, live pricing, and historical price/volume data for {symbol} as of {datetime}. "
                    "I am monitoring {symbol} on my watchlist across Binance.US and Webull and evaluating whether to initiate a new position or stay on the sidelines. "
                    "Based on the current live price, the consecutive hourly price & volume history, recent market data, price trends, volume dynamics, catalysts, and prospective risk/reward provided, evaluate whether I should enter the market, continue monitoring, or avoid this asset.\n\n"
                    "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
                    "{\n"
                    '  "sentiment": "<one of: Avoid, Watch, Consider Buying, Definitely Buy>",\n'
                    '  "reason": "<1-2 sentences explaining your recommendation based on current market conditions, hourly price/volume dynamics, prospective entry risk/reward, and recent news>"\n'
                    "}\n\n"
                    "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
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
                
                settings['ai_provider_fallback'] = getattr(user_setting, 'ai_provider_secondary', None) or user_setting.ai_provider_fallback
                settings['ai_model_fallback'] = getattr(user_setting, 'ai_model_secondary', None) or user_setting.ai_model_fallback
                settings['ai_reasoning_level_fallback'] = getattr(user_setting, 'ai_reasoning_level_secondary', None) or getattr(user_setting, 'ai_reasoning_level_fallback', 'medium') or 'medium'
                
                settings['ai_provider_secondary'] = settings['ai_provider_fallback']
                settings['ai_model_secondary'] = settings['ai_model_fallback']
                settings['ai_reasoning_level_secondary'] = settings['ai_reasoning_level_fallback']

                settings['ai_provider_tertiary'] = getattr(user_setting, 'ai_provider_tertiary', '')
                settings['ai_model_tertiary'] = getattr(user_setting, 'ai_model_tertiary', '')
                settings['ai_reasoning_level_tertiary'] = getattr(user_setting, 'ai_reasoning_level_tertiary', 'medium') or 'medium'
                settings['ai_provider_quartan'] = getattr(user_setting, 'ai_provider_quartan', '')
                settings['ai_model_quartan'] = getattr(user_setting, 'ai_model_quartan', '')
                settings['ai_reasoning_level_quartan'] = getattr(user_setting, 'ai_reasoning_level_quartan', 'medium') or 'medium'

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

        provider = str(settings.get('ai_provider', 'openai') or 'openai').strip().lower()
        settings['ai_provider'] = provider
        model = settings.get('ai_model')

        for provider_field in ('ai_provider_fallback', 'ai_provider_secondary', 'ai_provider_tertiary', 'ai_provider_quartan'):
            current_provider = settings.get(provider_field)
            settings[provider_field] = str(current_provider or '').strip().lower()

        ollama_allowed = bool(user_obj and is_event_strategy_admin(user_obj))
        valid_providers = {'openai', 'zai', 'perplexity', 'gemini', 'inception'}
        if ollama_allowed:
            valid_providers.add('ollama')
        if provider not in valid_providers:
            provider = 'openai'
            settings['ai_provider'] = provider

        openai_models = {
            'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1', 'gpt-4.1-mini',
            'gpt-4.1-nano', 'o4-mini', 'o3', 'o3-mini',
        }
        zai_models = {
            'glm-4.5-flash', 'glm-4.5', 'glm-4.5-air', 'glm-4.6', 'glm-4.7', 'glm-5.2', 'glm-5.3', 'glm-5.3-flash',
        }
        perplexity_models = {
            'sonar-pro', 'sonar', 'sonar-reasoning',
        }
        gemini_models = {
            'gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.7-flash', 'gemini-3.8-flash',
        }
        inception_models = {
            'mercury-2', 'mercury'
        }
        default_models = {
            'openai': 'gpt-5',
            'zai': 'glm-4.5-flash',
            'perplexity': 'sonar-pro',
            'gemini': 'gemini-3.7-flash',
            'inception': 'mercury-2',
        }

        if provider == 'openai':
            if model not in openai_models:
                settings['ai_model'] = default_models['openai']
        elif provider == 'zai':
            if model not in zai_models:
                settings['ai_model'] = default_models['zai']
        elif provider == 'perplexity':
            if model not in perplexity_models:
                settings['ai_model'] = 'sonar-pro'
        elif provider == 'gemini':
            if model not in gemini_models:
                settings['ai_model'] = default_models['gemini']
        elif provider == 'inception':
            if model not in inception_models:
                settings['ai_model'] = default_models['inception']
        elif provider == 'ollama':
            # Ollama models are discovered from the administrator's local
            # service. Do not replace a selected local model with a cloud
            # default or require an API key.
            settings['ai_model'] = str(model or '').strip()
        else:
            settings['ai_model'] = default_models['openai']

        # A saved value or forged request must never make Ollama available to
        # another account. Empty fallback tiers remain unconfigured.
        if not ollama_allowed:
            for provider_field, model_field, default_value in (
                ('ai_provider_secondary', 'ai_model_secondary', ''),
                ('ai_provider_tertiary', 'ai_model_tertiary', ''),
                ('ai_provider_quartan', 'ai_model_quartan', ''),
            ):
                if str(settings.get(provider_field) or '').strip().lower() == 'ollama':
                    settings[provider_field] = ''
                    settings[model_field] = default_value
            if str(settings.get('ai_provider') or '').strip().lower() == 'ollama':
                settings['ai_provider'] = 'openai'
                settings['ai_model'] = default_models['openai']

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
            
            if not settings.get('copilot_chat_pre'):
                def_prompts = DefaultAIPrompt.query.first()
                if def_prompts:
                    settings['copilot_chat_pre'] = def_prompts.copilot_chat_pre
                    settings['copilot_chat_post'] = def_prompts.copilot_chat_post

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
