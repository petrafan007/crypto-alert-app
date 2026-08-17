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
            ("coins", "sentiment_reason", "TEXT"),
            ("watchlist", "sentiment_reason", "TEXT"),
            ("coins", "cached_news", "TEXT"),
            ("watchlist", "cached_news", "TEXT"),
            ("coins", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "cached_news_date", "TIMESTAMP")
        ]
        for table, col, col_type in columns_to_ensure:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
            except Exception as ex:
                print(f"Migration note for {table}.{col}: {ex}")

    if ctx:
        with ctx:
            run_migrations()
    else:
        run_migrations()
    
    return db