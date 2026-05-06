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
    
    # DEPRECATED: Trading API Keys (merged into main api_key)
    # These columns exist in DB but should be ignored/wiped.
    _trading_api_key = db.Column("trading_api_key", db.String)
    _trading_api_secret = db.Column("trading_api_secret", db.String)
    
    # AI Integration
    _openai_key = db.Column("openai_key", db.String)  # Encrypted OpenAI API Key
    _zai_key = db.Column("zai_key", db.String)  # Encrypted Z.AI API Key
    _perplexity_key = db.Column("perplexity_key", db.String) # Encrypted Perplexity API Key
    _gemini_key = db.Column("gemini_key", db.String) # Encrypted Gemini API Key
    ai_provider = db.Column(db.String, default='openai')  # AI provider: 'openai', 'zai', 'perplexity', or 'gemini'

    # Notifications
    _telegram_token = db.Column("telegram_token", db.String)
    _telegram_chat_id = db.Column("telegram_chat_id", db.String)
    
    # External APIs
    _news_api = db.Column("news_api", db.String)
    _brave_search_api_key = db.Column("brave_search_api_key", db.String)  # Brave Search API Key
    _brave_search_api_key_fallback = db.Column("brave_search_api_key_fallback", db.String)  # Fallback Brave Search API Key
    
    # Fallback AI Keys
    _openai_key_fallback = db.Column("openai_key_fallback", db.String)
    _zai_key_fallback = db.Column("zai_key_fallback", db.String)
    _perplexity_key_fallback = db.Column("perplexity_key_fallback", db.String)
    _gemini_key_fallback = db.Column("gemini_key_fallback", db.String)

    
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
    def openai_key_fallback(self):
        return decrypt_secret(self._openai_key_fallback)

    @openai_key_fallback.setter
    def openai_key_fallback(self, value):
        self._openai_key_fallback = normalize_secret_for_storage(value)

    @property
    def zai_key_fallback(self):
        return decrypt_secret(self._zai_key_fallback)

    @zai_key_fallback.setter
    def zai_key_fallback(self, value):
        self._zai_key_fallback = normalize_secret_for_storage(value)

    @property
    def perplexity_key_fallback(self):
        return decrypt_secret(self._perplexity_key_fallback)

    @perplexity_key_fallback.setter
    def perplexity_key_fallback(self, value):
        self._perplexity_key_fallback = normalize_secret_for_storage(value)

    @property
    def gemini_key_fallback(self):
        return decrypt_secret(self._gemini_key_fallback)

    @gemini_key_fallback.setter
    def gemini_key_fallback(self, value):
        self._gemini_key_fallback = normalize_secret_for_storage(value)


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
    ai_provider = db.Column(db.String, default='openai')
    ai_provider_fallback = db.Column(db.String)
    ai_model = db.Column(db.String, default='gpt-4o')
    ai_model_fallback = db.Column(db.String)

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
    tax_cost_basis_method = db.Column(db.String, default='fifo')
    credentials_encryption_key_configured = db.Column(db.Boolean, default=False)
    has_seen_onboarding = db.Column(db.Boolean, default=False)
    browser_notifications_enabled = db.Column(db.Boolean, default=True)
    copilot_chat_pre = db.Column(db.Text)
    copilot_chat_post = db.Column(db.Text)
    sentiment_analysis_frequency_hours = db.Column(db.Integer, default=24)

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
