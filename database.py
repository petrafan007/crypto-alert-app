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
    
    if ctx:
        with ctx:
            db.create_all()
            try:
                from sqlalchemy import text
                db.session.execute(text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS ai_reasoning_level VARCHAR DEFAULT 'medium'"))
                db.session.commit()
            except Exception:
                db.session.rollback()
    else:
        db.create_all()
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS ai_reasoning_level VARCHAR DEFAULT 'medium'"))
            db.session.commit()
        except Exception:
            db.session.rollback()
    
    return db