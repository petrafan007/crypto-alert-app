
from datetime import datetime
from core.extensions import db

# Note: Legacy SQLite migration functions removed - PostgreSQL handles schema via SQLAlchemy

class Coin(db.Model):
    __tablename__ = "coins"
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # Foreign key to users table in credentials.db
    current = db.Column(db.Float, default=0.0)
    amount = db.Column(db.Float, default=0.0)
    custom_lower_pct = db.Column(db.Float, default=0.0)
    custom_upper_pct = db.Column(db.Float, default=0.0)
    alert_enabled = db.Column(db.Boolean, default=True)
    is_manual = db.Column(db.Boolean, default=False)
    hidden = db.Column(db.Boolean, default=False)
    auto_hidden = db.Column(db.Boolean, default=False)
    force_visible = db.Column(db.Boolean, default=False)
    custom_lower_type = db.Column(db.String(10), default="%")
    custom_upper_type = db.Column(db.String(10), default="%")
    custom_lower_val = db.Column(db.Float, nullable=True)
    custom_upper_val = db.Column(db.Float, nullable=True)
    avg_entry = db.Column(db.Float, default=0.0)
    initial_value = db.Column(db.Float, default=0.0)
    purchase_date = db.Column(db.String(25))  # Date only, no time component
    sentiment = db.Column(db.String(50), default="Hold")
    sentiment_last_updated = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.Text, default="")
    volatility_pct = db.Column(db.Float, nullable=True)
    volatility_pct = db.Column(db.Float, nullable=True)
    last_volatility_alert_time = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('ix_coins_user_symbol', 'user_id', 'symbol'),
    )

# User model is defined in credentials.py

class WatchlistCoin(db.Model):
    __tablename__ = "watchlist"
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # Foreign key to users table in credentials.db
    down_alert = db.Column(db.Float, nullable=True)
    up_alert = db.Column(db.Float, nullable=True)
    alert_enabled = db.Column(db.Boolean, default=False)
    note = db.Column(db.Text, default="")
    favorite = db.Column(db.Boolean, default=False)
    hidden = db.Column(db.Boolean, default=False)
    action = db.Column(db.String(10), default="Watch")
    current_price = db.Column(db.Float, default=0.0)
    sentiment = db.Column(db.String(50), default="Watch")
    volatility_pct = db.Column(db.Float, nullable=True)
    last_volatility_alert_time = db.Column(db.DateTime, nullable=True)
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('ix_watchlist_user_symbol', 'user_id', 'symbol'),
    )

class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    coin_id = db.Column(db.Integer, nullable=False)
    table_type = db.Column(db.String(20), nullable=False)  # 'portfolio' or 'watchlist'
    category = db.Column(db.String(30), nullable=False, default='price_alert')
    symbol = db.Column(db.String(10), nullable=False)
    date = db.Column(db.String(20), nullable=False)  # e.g., 08-15-2025 (EDT/EST)
    time = db.Column(db.String(30), nullable=False)  # e.g., 12:00 AM EDT
    crossing_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float, nullable=False)
    # Useful metadata for composing client messages
    direction = db.Column(db.String(10), nullable=True)  # 'up' or 'down'
    threshold_type = db.Column(db.String(10), nullable=True)  # '#', '%', 'Auto%'
    percent_value = db.Column(db.Float, nullable=True)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_hidden = db.Column(db.Integer, default=0)
    
    # Composite indexes for efficient querying
    __table_args__ = (
        # For fetching latest notifications
        db.Index('ix_notifications_user_created', 'user_id', 'created_at'),
        # For checking specific coin notifications
        db.Index('ix_notifications_coin', 'coin_id'),
    )

class StakedCoin(db.Model):
    __tablename__ = "staked_coins"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, default=1)  # Foreign key to users table
    symbol = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    staked_at = db.Column(db.DateTime, default=datetime.utcnow)
    stake_transaction_id = db.Column(db.String(100), nullable=True)
    apr = db.Column(db.Float, nullable=True)
    apy = db.Column(db.Float, nullable=True)
    reward_asset = db.Column(db.String(10), nullable=True)
    unstaking_period_hours = db.Column(db.Integer, nullable=True)
    auto_restake = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default='active')  # 'active', 'unstaking', 'completed'
    unstake_requested_at = db.Column(db.DateTime, nullable=True)
    unstake_available_at = db.Column(db.DateTime, nullable=True)
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('ix_staked_coins_user_symbol', 'user_id', 'symbol'),
        db.Index('ix_staked_coins_status', 'status'),
    )

class StakingReward(db.Model):
    __tablename__ = "staking_rewards"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, default=1)  # Foreign key to users table
    staked_coin_id = db.Column(db.Integer, db.ForeignKey('staked_coins.id'), nullable=False)
    asset = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    usd_value = db.Column(db.Float, nullable=True)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    auto_restaked = db.Column(db.Boolean, default=False)
    tran_id = db.Column(db.BigInteger, nullable=True)
    
    # Index for efficient reward queries
    __table_args__ = (
        db.Index('ix_staking_rewards_user', 'user_id'),
        db.Index('ix_staking_rewards_staked_coin', 'staked_coin_id'),
    )

class AIPrompt(db.Model):
    __tablename__ = "ai_prompts"
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    
    # Stage 1 (Pre-search) prompts for web search query generation
    coin_analysis_pre = db.Column(db.Text)
    market_analysis_pre = db.Column(db.Text)
    portfolio_review_pre = db.Column(db.Text)
    risk_assessment_pre = db.Column(db.Text)
    news_analysis_pre = db.Column(db.Text)
    sentiment_prompt_pre = db.Column(db.Text)  # New: Sentiment analysis pre-search prompt
    
    # Stage 2 (Post-search) prompts for final analysis
    coin_analysis_post = db.Column(db.Text)
    market_analysis_post = db.Column(db.Text)
    portfolio_review_post = db.Column(db.Text)
    risk_assessment_post = db.Column(db.Text)
    news_analysis_post = db.Column(db.Text)
    sentiment_prompt_post = db.Column(db.Text)  # New: Sentiment analysis post-search prompt

class DefaultAIPrompt(db.Model):
    __tablename__ = "default_ai_prompts"
    id = db.Column(db.Integer, primary_key=True)
    
    # Stage 1 (Pre-search) prompts
    coin_analysis_pre = db.Column(db.Text)
    market_analysis_pre = db.Column(db.Text)
    portfolio_review_pre = db.Column(db.Text)
    risk_assessment_pre = db.Column(db.Text)
    news_analysis_pre = db.Column(db.Text)
    sentiment_prompt_pre = db.Column(db.Text)
    copilot_chat_pre = db.Column(db.Text)
    
    # Stage 2 (Post-search) prompts
    coin_analysis_post = db.Column(db.Text)
    market_analysis_post = db.Column(db.Text)
    portfolio_review_post = db.Column(db.Text)
    risk_assessment_post = db.Column(db.Text)
    news_analysis_post = db.Column(db.Text)
    sentiment_prompt_post = db.Column(db.Text)
    copilot_chat_post = db.Column(db.Text)

class AIConversation(db.Model):
    __tablename__ = "ai_conversations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.String(30), nullable=False)
    prompt_type = db.Column(db.String(100), nullable=False)
    sender = db.Column(db.String(50), nullable=False)
    body = db.Column(db.Text, nullable=False)
    conversation_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())
    is_hidden = db.Column(db.Integer, default=0)
    coin_id = db.Column(db.Integer)
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('ix_ai_conversations_user_id', 'user_id'),
        db.Index('ix_ai_conversations_date', 'date'),
        db.Index('ix_ai_conversations_prompt_type', 'prompt_type'),
        db.Index('ix_ai_conversations_conversation_id', 'conversation_id'),
        db.Index('ix_ai_conversations_created_at', 'created_at'),
        db.Index('ix_ai_conversations_coin_id', 'coin_id'),
    )

class AICache(db.Model):
    """Cache for AI analysis results"""
    __tablename__ = 'ai_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    cache_key = db.Column(db.String, nullable=False)
    cache_type = db.Column(db.String, nullable=False)
    data = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    __table_args__ = (
        db.Index('ix_ai_cache_lookup', 'user_id', 'cache_key', 'cache_type'),
    )

class AIAnalysisSchedule(db.Model):
    """Schedule for AI analysis runs"""
    __tablename__ = 'ai_analysis_schedule'
    
    user_id = db.Column(db.Integer, primary_key=True)
    last_analysis = db.Column(db.DateTime, nullable=True)
    next_analysis = db.Column(db.DateTime, nullable=True)
    
    __table_args__ = (
        db.Index('ix_ai_analysis_schedule_last', 'last_analysis'),
    )

class PriceHistory(db.Model):
    """Historical price data for coins"""
    __tablename__ = 'price_history'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.BigInteger, nullable=False) # Unix timestamp
    exchange = db.Column(db.String(20), default='binance')
    date_int = db.Column(db.BigInteger, nullable=True)
    
    __table_args__ = (
        db.Index('ix_price_history_symbol_ts', 'symbol', 'timestamp'),
    )
