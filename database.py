from flask import current_app
import os
from core.extensions import db

def init_db(app=None):
    """Initialize the database with all models"""
    # Import models here to avoid circular imports
    from models import Coin, WatchlistCoin, Notification, AIPrompt, DefaultAIPrompt, StakedCoin, StakingReward, AIConversation, AICache, AIAnalysisSchedule, PriceHistory
    from credentials import User, Credential, UserSetting, DesktopToken
    from trading_models import TestOrder, RealOrder, TestPortfolio, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder
    
    target_app = app if app is not None else current_app
    ctx = target_app.app_context() if target_app else None
    
    def run_migrations():
        try:
            db.create_all()
        except Exception as e:
            print(f"db.create_all error: {e}")
        
        # Ensure recently added columns exist in PostgreSQL
        columns_to_ensure = [
            ("user_settings", "ai_reasoning_level", "VARCHAR DEFAULT 'medium'"),
            ("user_settings", "ai_reasoning_level_fallback", "VARCHAR DEFAULT 'medium'"),
            ("user_settings", "ai_provider_fallback", "VARCHAR"),
            ("user_settings", "ai_model_fallback", "VARCHAR"),
            ("user_settings", "watchlist_sentiment_analysis_frequency_hours", "INTEGER DEFAULT 24"),
            ("coins", "sentiment_reason", "TEXT"),
            ("watchlist", "sentiment_reason", "TEXT"),
            ("coins", "cached_news", "TEXT"),
            ("watchlist", "cached_news", "TEXT"),
            ("coins", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "sentiment_last_updated", "TIMESTAMP"),
            ("ai_prompts", "watchlist_sentiment_prompt_pre", "TEXT"),
            ("ai_prompts", "watchlist_sentiment_prompt_post", "TEXT"),
            ("default_ai_prompts", "watchlist_sentiment_prompt_pre", "TEXT"),
            ("default_ai_prompts", "watchlist_sentiment_prompt_post", "TEXT")
        ]
        for table, col, col_type in columns_to_ensure:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
            except Exception as ex:
                print(f"Migration note for {table}.{col}: {ex}")

        # Seed default watchlist prompts if empty
        default_wl_pre = (
            "You are an intelligent search query generator for cryptocurrency analysis. "
            "I am currently monitoring {symbol} on my watchlist as a prospective investment opportunity. "
            "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} as of {datetime} to evaluate whether now is a good entry point."
        )
        default_wl_post = (
            "You are a cryptocurrency and financial analysis expert with access to current web search results for {symbol} as of {datetime}. "
            "I am monitoring {symbol} on my watchlist and evaluating whether to initiate a new position or stay on the sidelines. "
            "Based on the current market data, price trends, catalysts, risk/reward, and web search results provided, evaluate whether I should enter the market, continue monitoring, or avoid this coin.\n\n"
            "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
            "{\n"
            '  "sentiment": "<one of: Avoid, Watch, Consider Buying, Definitely Buy>",\n'
            '  "reason": "<1-2 sentences explaining your recommendation based on current market conditions, prospective entry risk/reward, and recent news>"\n'
            "}\n\n"
            "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
        )
        try:
            def_prompt = DefaultAIPrompt.query.first()
            if def_prompt:
                if not def_prompt.watchlist_sentiment_prompt_pre:
                    def_prompt.watchlist_sentiment_prompt_pre = default_wl_pre
                if not def_prompt.watchlist_sentiment_prompt_post:
                    def_prompt.watchlist_sentiment_prompt_post = default_wl_post
                db.session.commit()
            
            user_prompts = AIPrompt.query.all()
            for up in user_prompts:
                updated = False
                if not up.watchlist_sentiment_prompt_pre:
                    up.watchlist_sentiment_prompt_pre = default_wl_pre
                    updated = True
                if not up.watchlist_sentiment_prompt_post:
                    up.watchlist_sentiment_prompt_post = default_wl_post
                    updated = True
                if updated:
                    db.session.commit()
        except Exception as seed_err:
            print(f"Error seeding default watchlist prompts: {seed_err}")
            db.session.rollback()

    if ctx:
        with ctx:
            run_migrations()
    else:
        run_migrations()
    
    return db