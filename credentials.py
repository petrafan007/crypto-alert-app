from flask_sqlalchemy import SQLAlchemy
from flask import Flask
from datetime import datetime
from flask_login import UserMixin, LoginManager
from werkzeug.security import generate_password_hash, check_password_hash

from credential_security import decrypt_secret, normalize_secret_for_storage
from core.extensions import db

# credentials_app and credentials_db removed - using shared db instance

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    pwd_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.pwd_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pwd_hash, password)
    
def reset_user_password(username, new_password):
    """Reset the password for a user to a new password (hashes it)."""
    from werkzeug.security import generate_password_hash
    # User is already imported in this file, but if called externally, ensure db is available
    # Assuming this is run within an app context of the main app
    user = User.query.filter_by(username=username).first()
    if user:
        user.pwd_hash = generate_password_hash(new_password)
        db.session.commit()
        print(f"Password for {username} reset successfully.")
    else:
        print(f"User {username} not found.")

class Credential(db.Model):
    __tablename__ = "credentials"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    username = db.Column(db.String, unique=True, nullable=False)  # Kept for backward compat, but user_id is source of truth
    
    # Relationship to access user details if needed
    user = db.relationship('User', backref=db.backref('credential', uselist=False))
    
    # API Keys (Unified for Portfolio, Trading, and Price Tracking)
    _api_key = db.Column("api_key", db.String)  # Encrypted Binance API Key
    _api_secret = db.Column("api_secret", db.String)  # Encrypted Binance API Secret

    # Webull OpenAPI credentials. These use the same encrypted-at-rest handling
    # as all other credentials and are never returned by the settings API.
    _webull_app_key = db.Column("webull_app_key", db.String)
    _webull_app_secret = db.Column("webull_app_secret", db.String)
    _webull_access_token = db.Column("webull_access_token", db.String)
    webull_token_environment = db.Column(db.String(20))
    webull_token_status = db.Column(db.String(20))
    webull_token_expires_at = db.Column(db.DateTime)
    
    # DEPRECATED: Trading API Keys (merged into main api_key)
    # These columns exist in DB but should be ignored/wiped.
    _trading_api_key = db.Column("trading_api_key", db.String)
    _trading_api_secret = db.Column("trading_api_secret", db.String)
    
    # AI Integration (Primary)
    _openai_key = db.Column("openai_key", db.String)  # Encrypted OpenAI API Key
    _zai_key = db.Column("zai_key", db.String)  # Encrypted Z.AI API Key
    _perplexity_key = db.Column("perplexity_key", db.String) # Encrypted Perplexity API Key
    _gemini_key = db.Column("gemini_key", db.String) # Encrypted Gemini API Key
    _inception_key = db.Column("inception_key", db.String) # Encrypted Inception Labs API Key
    ai_provider = db.Column(db.String, default='openai')  # AI provider: 'openai', 'zai', 'perplexity', 'gemini', or 'inception'

    # Notifications
    _telegram_token = db.Column("telegram_token", db.String)
    _telegram_chat_id = db.Column("telegram_chat_id", db.String)
    
    # External APIs
    _news_api = db.Column("news_api", db.String)
    _brave_search_api_key = db.Column("brave_search_api_key", db.String)  # Brave Search API Key
    _brave_search_api_key_fallback = db.Column("brave_search_api_key_fallback", db.String)  # Fallback Brave Search API Key
    
    # Secondary (Fallback) AI Keys
    _openai_key_fallback = db.Column("openai_key_fallback", db.String)
    _zai_key_fallback = db.Column("zai_key_fallback", db.String)
    _perplexity_key_fallback = db.Column("perplexity_key_fallback", db.String)
    _gemini_key_fallback = db.Column("gemini_key_fallback", db.String)
    _inception_key_fallback = db.Column("inception_key_fallback", db.String)

    # Tertiary AI Keys
    _openai_key_tertiary = db.Column("openai_key_tertiary", db.String)
    _zai_key_tertiary = db.Column("zai_key_tertiary", db.String)
    _perplexity_key_tertiary = db.Column("perplexity_key_tertiary", db.String)
    _gemini_key_tertiary = db.Column("gemini_key_tertiary", db.String)
    _inception_key_tertiary = db.Column("inception_key_tertiary", db.String)

    # Quartan (fourth fallback) AI Keys
    _openai_key_quartan = db.Column("openai_key_quartan", db.String)
    _zai_key_quartan = db.Column("zai_key_quartan", db.String)
    _perplexity_key_quartan = db.Column("perplexity_key_quartan", db.String)
    _gemini_key_quartan = db.Column("gemini_key_quartan", db.String)
    _inception_key_quartan = db.Column("inception_key_quartan", db.String)

    
    # OAuth (Legacy/Unused fields removed)
    secret_key = db.Column(db.Text, nullable=True) # Flask SECRET_KEY override
    @property
    def api_key(self):
        return decrypt_secret(self._api_key)

    @api_key.setter
    def api_key(self, value):
        self._api_key = normalize_secret_for_storage(value)

    @property
    def api_secret(self):
        return decrypt_secret(self._api_secret)

    @api_secret.setter
    def api_secret(self, value):
        self._api_secret = normalize_secret_for_storage(value)

    @property
    def webull_app_key(self):
        return decrypt_secret(self._webull_app_key)

    @webull_app_key.setter
    def webull_app_key(self, value):
        self._webull_app_key = normalize_secret_for_storage(value)

    @property
    def webull_app_secret(self):
        return decrypt_secret(self._webull_app_secret)

    @webull_app_secret.setter
    def webull_app_secret(self, value):
        self._webull_app_secret = normalize_secret_for_storage(value)

    @property
    def webull_access_token(self):
        return decrypt_secret(self._webull_access_token)

    @webull_access_token.setter
    def webull_access_token(self, value):
        self._webull_access_token = normalize_secret_for_storage(value)

    def clear_webull_access_token(self):
        """Forget the environment-bound Webull 2FA token without touching App credentials."""
        self._webull_access_token = None
        self.webull_token_environment = None
        self.webull_token_status = None
        self.webull_token_expires_at = None

    @property
    def trading_api_key(self):
        # Redirect to unified API key
        return decrypt_secret(self._api_key)

    @trading_api_key.setter
    def trading_api_key(self, value):
        # Redirect to unified API key
        self._api_key = normalize_secret_for_storage(value)

    @property
    def trading_api_secret(self):
        # Redirect to unified API secret
        return decrypt_secret(self._api_secret)

    @trading_api_secret.setter
    def trading_api_secret(self, value):
        # Redirect to unified API secret
        self._api_secret = normalize_secret_for_storage(value)

    @property
    def openai_key(self):
        return decrypt_secret(self._openai_key)

    @openai_key.setter
    def openai_key(self, value):
        self._openai_key = normalize_secret_for_storage(value)

    @property
    def zai_key(self):
        return decrypt_secret(self._zai_key)

    @zai_key.setter
    def zai_key(self, value):
        self._zai_key = normalize_secret_for_storage(value)

    @property
    def perplexity_key(self):
        return decrypt_secret(self._perplexity_key)

    @perplexity_key.setter
    def perplexity_key(self, value):
        self._perplexity_key = normalize_secret_for_storage(value)

    @property
    def gemini_key(self):
        return decrypt_secret(self._gemini_key)

    @gemini_key.setter
    def gemini_key(self, value):
        self._gemini_key = normalize_secret_for_storage(value)

    @property
    def inception_key(self):
        return decrypt_secret(self._inception_key)

    @inception_key.setter
    def inception_key(self, value):
        self._inception_key = normalize_secret_for_storage(value)

    # Secondary (Fallback) Keys
    @property
    def openai_key_fallback(self):
        return decrypt_secret(self._openai_key_fallback)

    @openai_key_fallback.setter
    def openai_key_fallback(self, value):
        self._openai_key_fallback = normalize_secret_for_storage(value)

    @property
    def openai_key_secondary(self):
        return self.openai_key_fallback

    @openai_key_secondary.setter
    def openai_key_secondary(self, value):
        self.openai_key_fallback = value

    @property
    def zai_key_fallback(self):
        return decrypt_secret(self._zai_key_fallback)

    @zai_key_fallback.setter
    def zai_key_fallback(self, value):
        self._zai_key_fallback = normalize_secret_for_storage(value)

    @property
    def zai_key_secondary(self):
        return self.zai_key_fallback

    @zai_key_secondary.setter
    def zai_key_secondary(self, value):
        self.zai_key_fallback = value

    @property
    def perplexity_key_fallback(self):
        return decrypt_secret(self._perplexity_key_fallback)

    @perplexity_key_fallback.setter
    def perplexity_key_fallback(self, value):
        self._perplexity_key_fallback = normalize_secret_for_storage(value)

    @property
    def perplexity_key_secondary(self):
        return self.perplexity_key_fallback

    @perplexity_key_secondary.setter
    def perplexity_key_secondary(self, value):
        self.perplexity_key_fallback = value

    @property
    def gemini_key_fallback(self):
        return decrypt_secret(self._gemini_key_fallback)

    @gemini_key_fallback.setter
    def gemini_key_fallback(self, value):
        self._gemini_key_fallback = normalize_secret_for_storage(value)

    @property
    def gemini_key_secondary(self):
        return self.gemini_key_fallback

    @gemini_key_secondary.setter
    def gemini_key_secondary(self, value):
        self.gemini_key_fallback = value

    @property
    def inception_key_fallback(self):
        return decrypt_secret(self._inception_key_fallback)

    @inception_key_fallback.setter
    def inception_key_fallback(self, value):
        self._inception_key_fallback = normalize_secret_for_storage(value)

    @property
    def inception_key_secondary(self):
        return self.inception_key_fallback

    @inception_key_secondary.setter
    def inception_key_secondary(self, value):
        self.inception_key_fallback = value

    # Tertiary Keys
    @property
    def openai_key_tertiary(self):
        return decrypt_secret(self._openai_key_tertiary)

    @openai_key_tertiary.setter
    def openai_key_tertiary(self, value):
        self._openai_key_tertiary = normalize_secret_for_storage(value)

    @property
    def zai_key_tertiary(self):
        return decrypt_secret(self._zai_key_tertiary)

    @zai_key_tertiary.setter
    def zai_key_tertiary(self, value):
        self._zai_key_tertiary = normalize_secret_for_storage(value)

    @property
    def perplexity_key_tertiary(self):
        return decrypt_secret(self._perplexity_key_tertiary)

    @perplexity_key_tertiary.setter
    def perplexity_key_tertiary(self, value):
        self._perplexity_key_tertiary = normalize_secret_for_storage(value)

    @property
    def gemini_key_tertiary(self):
        return decrypt_secret(self._gemini_key_tertiary)

    @gemini_key_tertiary.setter
    def gemini_key_tertiary(self, value):
        self._gemini_key_tertiary = normalize_secret_for_storage(value)

    @property
    def inception_key_tertiary(self):
        return decrypt_secret(self._inception_key_tertiary)

    @inception_key_tertiary.setter
    def inception_key_tertiary(self, value):
        self._inception_key_tertiary = normalize_secret_for_storage(value)

    # Quartan (fourth fallback) Keys
    @property
    def openai_key_quartan(self):
        return decrypt_secret(self._openai_key_quartan)

    @openai_key_quartan.setter
    def openai_key_quartan(self, value):
        self._openai_key_quartan = normalize_secret_for_storage(value)

    @property
    def zai_key_quartan(self):
        return decrypt_secret(self._zai_key_quartan)

    @zai_key_quartan.setter
    def zai_key_quartan(self, value):
        self._zai_key_quartan = normalize_secret_for_storage(value)

    @property
    def perplexity_key_quartan(self):
        return decrypt_secret(self._perplexity_key_quartan)

    @perplexity_key_quartan.setter
    def perplexity_key_quartan(self, value):
        self._perplexity_key_quartan = normalize_secret_for_storage(value)

    @property
    def gemini_key_quartan(self):
        return decrypt_secret(self._gemini_key_quartan)

    @gemini_key_quartan.setter
    def gemini_key_quartan(self, value):
        self._gemini_key_quartan = normalize_secret_for_storage(value)

    @property
    def inception_key_quartan(self):
        return decrypt_secret(self._inception_key_quartan)

    @inception_key_quartan.setter
    def inception_key_quartan(self, value):
        self._inception_key_quartan = normalize_secret_for_storage(value)


    @property
    def telegram_token(self):
        return decrypt_secret(self._telegram_token)

    @telegram_token.setter
    def telegram_token(self, value):
        self._telegram_token = normalize_secret_for_storage(value)

    @property
    def telegram_chat_id(self):
        return decrypt_secret(self._telegram_chat_id)

    @telegram_chat_id.setter
    def telegram_chat_id(self, value):
        self._telegram_chat_id = normalize_secret_for_storage(value)

    @property
    def news_api(self):
        return decrypt_secret(self._news_api)

    @news_api.setter
    def news_api(self, value):
        self._news_api = normalize_secret_for_storage(value)

    @property
    def brave_search_api_key(self):
        return decrypt_secret(self._brave_search_api_key)

    @brave_search_api_key.setter
    def brave_search_api_key(self, value):
        self._brave_search_api_key = normalize_secret_for_storage(value)

    @property
    def brave_search_api_key_fallback(self):
        return decrypt_secret(self._brave_search_api_key_fallback)

    @brave_search_api_key_fallback.setter
    def brave_search_api_key_fallback(self, value):
        self._brave_search_api_key_fallback = normalize_secret_for_storage(value)

    __table_args__ = (
        db.Index('ix_credentials_user_id', 'user_id'),
    )

class UserSetting(db.Model):
    __tablename__ = "user_settings"
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    ai_enabled = db.Column(db.Boolean, default=False)
    
    # Primary AI Tier
    ai_provider = db.Column(db.String, default='openai')
    ai_model = db.Column(db.String, default='gpt-4o')
    ai_reasoning_level = db.Column(db.String, default='medium')

    # Secondary AI Tier (fallback alias)
    ai_provider_fallback = db.Column(db.String)
    ai_model_fallback = db.Column(db.String)
    ai_reasoning_level_fallback = db.Column(db.String, default='medium')
    ai_provider_secondary = db.Column(db.String)
    ai_model_secondary = db.Column(db.String)
    ai_reasoning_level_secondary = db.Column(db.String, default='medium')

    # Tertiary AI Tier
    ai_provider_tertiary = db.Column(db.String)
    ai_model_tertiary = db.Column(db.String)
    ai_reasoning_level_tertiary = db.Column(db.String, default='medium')

    # Quartan (fourth fallback) AI Tier
    ai_provider_quartan = db.Column(db.String)
    ai_model_quartan = db.Column(db.String)
    ai_reasoning_level_quartan = db.Column(db.String, default='medium')

    ai_risk_tolerance = db.Column(db.String, default='medium')
    ai_confidence_threshold = db.Column(db.Float, default=0.7)
    ai_notifications_enabled = db.Column(db.Boolean, default=True)
    ai_analysis_frequency = db.Column(db.String, default='daily')
    ai_cache_duration_hours = db.Column(db.Integer, default=24)
    ai_analysis_window_start = db.Column(db.String, default='09:00')
    ai_analysis_window_end = db.Column(db.String, default='17:00')
    ai_max_tokens = db.Column(db.Integer, default=4000)
    ai_web_search_enabled = db.Column(db.Boolean, default=True)
    tax_manual_invested_updated = db.Column(db.String)
    tax_webull_manual_invested_updated = db.Column(db.String)
    tax_cost_basis_method = db.Column(db.String, default='fifo')
    credentials_encryption_key_configured = db.Column(db.Boolean, default=False)
    has_seen_onboarding = db.Column(db.Boolean, default=False)
    # Full first-run onboarding is opt-in for newly registered users so an
    # upgrade never blocks established accounts. The page key makes the flow
    # resumable without storing any secret in the browser.
    onboarding_required = db.Column(db.Boolean, default=False)
    onboarding_completed = db.Column(db.Boolean, default=False)
    onboarding_page = db.Column(db.String(40), default='security-choice')
    onboarding_exchange_choice = db.Column(db.String(20))
    onboarding_binance_verified = db.Column(db.Boolean, default=False)
    onboarding_webull_verified = db.Column(db.Boolean, default=False)
    onboarding_two_factor_deferred = db.Column(db.Boolean, default=False)
    onboarding_ai_skipped = db.Column(db.Boolean, default=False)
    onboarding_search_skipped = db.Column(db.Boolean, default=False)
    onboarding_telegram_skipped = db.Column(db.Boolean, default=False)
    browser_notifications_enabled = db.Column(db.Boolean, default=True)
    copilot_chat_pre = db.Column(db.Text)
    copilot_chat_post = db.Column(db.Text)
    sentiment_analysis_frequency_hours = db.Column(db.Integer, default=24)
    watchlist_sentiment_analysis_frequency_hours = db.Column(db.Integer, default=24)
    sentiment_history_lookback_hours = db.Column(db.Integer, default=12)
    watchlist_sentiment_history_lookback_hours = db.Column(db.Integer, default=12)
    sentiment_forecast_horizon_hours = db.Column(db.Integer, nullable=True)
    watchlist_sentiment_forecast_horizon_hours = db.Column(db.Integer, nullable=True)
    portfolio_schedule_start_time = db.Column(db.String, default='08:00')
    watchlist_schedule_start_time = db.Column(db.String, default='08:00')
    volatility_hours = db.Column(db.Integer, default=24)
    automated_trigger_confirmation_minutes = db.Column(db.Integer, default=15)
    webull_environment = db.Column(db.String(20), default='production')
    webull_account_selection_mode = db.Column(db.String(20), default='all')
    # The account selected when the user opens the Webull Trading workspace.
    # It is deliberately separate from the enabled-account list.
    webull_default_account_id = db.Column(db.String(100), nullable=True)
    webull_account_aliases = db.Column(db.Text, default='{}')
    webull_connected_accounts = db.Column(db.Text, default='[]')
    webull_enabled_account_ids = db.Column(db.Text, default='[]')
    # Disabled by default so connecting Webull never starts paid AI requests.
    # When enabled, manual and scheduled runs write the same broker-neutral
    # signal records and use their own asset-class cadence/horizon.
    webull_ai_scheduling_enabled = db.Column(db.Boolean, default=False)
    webull_crypto_sentiment_frequency_hours = db.Column(db.Integer, default=24)
    webull_equity_sentiment_frequency_hours = db.Column(db.Integer, default=24)
    webull_crypto_sentiment_horizon_hours = db.Column(db.Integer, default=24)
    webull_equity_sentiment_horizon_hours = db.Column(db.Integer, default=24)
    ai_outcome_neutral_threshold_pct = db.Column(db.Float, default=5.0)
    sentiment_buy_immediately_correct_pct = db.Column(db.Float, default=5.0)
    sentiment_buy_immediately_wrong_pct = db.Column(db.Float, default=5.0)
    sentiment_consider_buying_correct_pct = db.Column(db.Float, default=5.0)
    sentiment_consider_buying_wrong_pct = db.Column(db.Float, default=5.0)
    sentiment_hold_correct_pct = db.Column(db.Float, default=5.0)
    sentiment_hold_wrong_pct = db.Column(db.Float, default=5.0)
    sentiment_hold_steady_pct = db.Column(db.Float, default=1.0)
    sentiment_consider_selling_correct_pct = db.Column(db.Float, default=5.0)
    sentiment_consider_selling_wrong_pct = db.Column(db.Float, default=5.0)
    sentiment_sell_immediately_correct_pct = db.Column(db.Float, default=5.0)
    sentiment_sell_immediately_wrong_pct = db.Column(db.Float, default=5.0)
    sentiment_chart_default_range = db.Column(db.String(10), default='3d')
    max_slippage_pct = db.Column(db.Float, default=2.0)
    webull_test_mode_enabled = db.Column(db.Boolean, default=False)


class OnboardingDefaultProfile(db.Model):
    """One-time, non-secret seed copied independently to every new user."""
    __tablename__ = 'onboarding_default_profiles'
    id = db.Column(db.Integer, primary_key=True, default=1)
    settings_json = db.Column(db.Text, nullable=False, default='{}')
    prompts_json = db.Column(db.Text, nullable=False, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

class DesktopToken(db.Model):
    __tablename__ = "desktop_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    device_name = db.Column(db.String(100), default='Desktop App')
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('ix_desktop_tokens_user_id', 'user_id'),
        db.Index('ix_desktop_tokens_token', 'token'),
    )

class CredentialEncryptionKey(db.Model):
    """Stores the system-wide encryption key for credentials."""
    __tablename__ = "credential_settings"
    key = db.Column(db.String, primary_key=True)
    value = db.Column(db.String, nullable=False)
