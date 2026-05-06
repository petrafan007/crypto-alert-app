from flask_sqlalchemy import SQLAlchemy
from flask import current_app
import os

db = SQLAlchemy()

def init_db():
    """Initialize the database with all models"""
    # Import models here to avoid circular imports
    from models import Coin, WatchlistCoin, Notification, AIPrompt, DefaultAIPrompt, StakedCoin, StakingReward, AIConversation, AICache, AIAnalysisSchedule, PriceHistory
    from credentials import User, Credential, UserSetting, DesktopToken
    from trading_models import TestOrder, RealOrder, TestPortfolio, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder
    
    # Get the database path from the app config or use default
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'postgresql:///cryptoalertapp?host=/var/run/postgresql&port=5433')
    
    # Create all tables
    with current_app.app_context():
        db.create_all()
    
    return db