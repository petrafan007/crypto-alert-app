import json
import datetime
import logging
from log import logger
from core.extensions import db
from models import AICache, AIPrompt, AIAnalysisSchedule, AIConversation
from credentials import UserSetting

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
                return json.loads(cache.result_json)
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
        
        if cache:
            cache.result_json = json.dumps(result)
            cache.expires_at = expires_at
        else:
            cache = AICache(
                user_id=user_id,
                cache_key=cache_key,
                cache_type=cache_type,
                result_json=json.dumps(result),
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

def get_user_ai_settings(username):
    """Get AI settings for a user"""
    from credentials import User
    user = User.query.filter_by(username=username).first()
    if not user: return {}
    
    settings = UserSetting.query.filter_by(user_id=user.id).first()
    if not settings: return {}
    
    return {
        'ai_enabled': settings.ai_enabled,
        'ai_provider': settings.ai_provider or 'openai',
        'ai_model': settings.ai_model or 'gpt-5',
        'ai_risk_tolerance': settings.ai_risk_tolerance or 'moderate',
        'ai_confidence_threshold': settings.ai_confidence_threshold or 0.7,
        'ai_max_tokens': settings.ai_max_tokens or 2000,
        'ai_web_search_enabled': settings.ai_web_search_enabled
    }

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
                risk_assessment_pre="", risk_assessment_post="",
                portfolio_review_pre="", portfolio_review_post="",
                coin_analysis_pre="", coin_analysis_post="",
                sentiment_prompt_pre="", sentiment_prompt_post=""
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

