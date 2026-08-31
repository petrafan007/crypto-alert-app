
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
    custom_lower_type = db.Column(db.String(10), default="#")
    custom_upper_type = db.Column(db.String(10), default="#")
    custom_lower_val = db.Column(db.Float, nullable=True)
    custom_upper_val = db.Column(db.Float, nullable=True)
    avg_entry = db.Column(db.Float, default=0.0)
    initial_value = db.Column(db.Float, default=0.0)
    purchase_date = db.Column(db.String(25))  # Date only, no time component
    sentiment = db.Column(db.String(50), default="Hold")
    sentiment_reason = db.Column(db.Text, default="")
    sentiment_last_updated = db.Column(db.DateTime, nullable=True)
    sentiment_provider = db.Column(db.String(50), nullable=True)
    sentiment_model = db.Column(db.String(100), nullable=True)
    sentiment_tier = db.Column(db.String(50), nullable=True)
    sentiment_search_status = db.Column(db.String(100), nullable=True)
    sentiment_failover_history = db.Column(db.Text, nullable=True)
    sentiment_tracking_enabled = db.Column(db.Boolean, default=True)
    note = db.Column(db.Text, default="")
    volatility_pct = db.Column(db.Float, nullable=True)
    last_volatility_alert_time = db.Column(db.DateTime, nullable=True)
    auto_sell_enabled = db.Column(db.Boolean, default=False)
    auto_sell_volatility_pct = db.Column(db.Float, nullable=True)
    auto_sell_quote_currency = db.Column(db.String(10), default='USDT')
    auto_sell_triggered_at = db.Column(db.DateTime, nullable=True)
    auto_sell_confirmation_started_at = db.Column(db.DateTime, nullable=True)
    auto_buy_enabled = db.Column(db.Boolean, default=False)
    auto_buy_volatility_pct = db.Column(db.Float, nullable=True)
    auto_buy_quote_currency = db.Column(db.String(10), default='USDT')
    auto_buy_amount = db.Column(db.Float, nullable=True)
    auto_buy_triggered_at = db.Column(db.DateTime, nullable=True)
    auto_buy_confirmation_started_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('ix_coins_user_symbol', 'user_id', 'symbol'),
    )


class WebullAccountSnapshot(db.Model):
    """Latest read-only account summary imported from Webull."""
    __tablename__ = 'webull_account_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    account_id = db.Column(db.String(80), nullable=False)
    environment = db.Column(db.String(20), nullable=False, default='production')
    account_type = db.Column(db.String(80), nullable=True)
    account_name = db.Column(db.String(160), nullable=True)
    currency = db.Column(db.String(12), default='USD')
    total_net_liquidation_value = db.Column(db.Float, default=0.0)
    total_cash_balance = db.Column(db.Float, default=0.0)
    total_market_value = db.Column(db.Float, default=0.0)
    total_unrealized_profit_loss = db.Column(db.Float, nullable=True)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    activity_synced_at = db.Column(db.DateTime, nullable=True)
    activity_sync_environment = db.Column(db.String(20), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'account_id', name='uq_webull_account_snapshot_user_account'),
        db.Index('ix_webull_account_snapshot_user', 'user_id'),
    )


class WebullActivity(db.Model):
    """Authoritative read-only Webull cash/activity ledger.

    This table is intentionally separate from ``AllActivity``.  The latter is
    used by Binance cost-basis and automation code, while these rows can cover
    every Webull asset class plus deposits, withdrawals, transfers, fees,
    dividends, interest, corporate actions, and event-contract settlements.
    """
    __tablename__ = 'webull_activities'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    environment = db.Column(db.String(20), nullable=False, default='production')
    account_id = db.Column(db.String(80), nullable=False)
    webull_activity_id = db.Column(db.String(120), nullable=False)
    activity_type = db.Column(db.String(40), nullable=True)
    activity_sub_type = db.Column(db.String(80), nullable=True)
    currency = db.Column(db.String(12), nullable=True)
    market = db.Column(db.String(20), nullable=True)
    symbol = db.Column(db.String(80), nullable=True)
    trade_date = db.Column(db.Date, nullable=True)
    net_amount = db.Column(db.Float, nullable=True)
    biz_time = db.Column(db.DateTime, nullable=True)
    raw_details = db.Column(db.Text, nullable=True)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'environment', 'account_id', 'webull_activity_id',
            name='uq_webull_activity_user_env_account_activity',
        ),
        db.Index('ix_webull_activity_user_time', 'user_id', 'biz_time'),
        db.Index('ix_webull_activity_user_account', 'user_id', 'account_id'),
    )


class WebullEventSettlement(db.Model):
    """Provider-explicit Event Contract settlement received from Webull's event stream."""
    __tablename__ = 'webull_event_settlements'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    environment = db.Column(db.String(20), nullable=False, default='production')
    account_id = db.Column(db.String(80), nullable=False)
    event_key = db.Column(db.String(180), nullable=False)
    position_id = db.Column(db.String(120), nullable=True)
    symbol = db.Column(db.String(120), nullable=True)
    event_name = db.Column(db.String(300), nullable=True)
    yes_condition = db.Column(db.String(500), nullable=True)
    settle_result = db.Column(db.String(40), nullable=True)
    settle_side = db.Column(db.String(20), nullable=True)
    quantity = db.Column(db.Float, nullable=True)
    cost = db.Column(db.Float, nullable=True)
    settle_amount = db.Column(db.Float, nullable=True)
    biz_type = db.Column(db.String(80), nullable=True)
    event_time = db.Column(db.DateTime, nullable=True)
    raw_details = db.Column(db.Text, nullable=True)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'environment', 'account_id', 'event_key', name='uq_webull_event_settlement'),
        db.Index('ix_webull_event_settlement_user_time', 'user_id', 'event_time'),
        db.Index('ix_webull_event_settlement_account', 'user_id', 'account_id'),
    )


class WebullHistoricalOrder(db.Model):
    """Durable read-only copy of Webull historical orders.

    Webull order history is synchronized in the background so history screens
    never need to wait for the provider's serialized, rate-limited endpoint.
    """
    __tablename__ = 'webull_historical_orders'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    environment = db.Column(db.String(20), nullable=False, default='production')
    account_id = db.Column(db.String(80), nullable=False)
    order_key = db.Column(db.String(180), nullable=False)
    webull_order_id = db.Column(db.String(160), nullable=True)
    client_order_id = db.Column(db.String(160), nullable=True)
    symbol = db.Column(db.String(180), nullable=False, default='UNKNOWN')
    side = db.Column(db.String(30), nullable=True)
    order_type = db.Column(db.String(50), nullable=True)
    instrument_type = db.Column(db.String(40), nullable=True)
    quantity = db.Column(db.Float, default=0.0)
    price = db.Column(db.Float, default=0.0)
    stop_price = db.Column(db.Float, nullable=True)
    filled_quantity = db.Column(db.Float, default=0.0)
    filled_price = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(40), nullable=True)
    time_in_force = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)
    raw_details = db.Column(db.Text, nullable=True)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'environment', 'account_id', 'order_key',
            name='uq_webull_history_user_env_account_order',
        ),
        db.Index('ix_webull_history_user_time', 'user_id', 'created_at'),
        db.Index('ix_webull_history_user_account', 'user_id', 'account_id'),
    )


class WebullHolding(db.Model):
    """Latest read-only Webull position snapshot; never a Binance trading record."""
    __tablename__ = 'webull_holdings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    account_id = db.Column(db.String(80), nullable=False)
    symbol = db.Column(db.String(40), nullable=False)
    instrument_type = db.Column(db.String(60), nullable=True)
    # Contract identity is required for options.  It is stored independently
    # from the display symbol so an option can never be confused with its
    # underlying equity or another strike/expiration.
    webull_position_id = db.Column(db.String(100), nullable=True)
    instrument_id = db.Column(db.String(100), nullable=True)
    underlying_symbol = db.Column(db.String(40), nullable=True)
    option_expiration = db.Column(db.String(20), nullable=True)
    option_strike = db.Column(db.Float, nullable=True)
    option_type = db.Column(db.String(12), nullable=True)
    option_multiplier = db.Column(db.Float, nullable=True)
    # Monitoring preferences are deliberately local to Crypto & Securities Dashboard. They
    # never grant Webull trading permission or create an order at Webull.
    custom_lower_type = db.Column(db.String(10), default='#')
    custom_upper_type = db.Column(db.String(10), default='#')
    custom_lower_val = db.Column(db.Float, nullable=True)
    custom_upper_val = db.Column(db.Float, nullable=True)
    custom_lower_pct = db.Column(db.Float, nullable=True)
    custom_upper_pct = db.Column(db.Float, nullable=True)
    alert_enabled = db.Column(db.Boolean, default=False)
    volatility_pct = db.Column(db.Float, nullable=True)
    sentiment_tracking_enabled = db.Column(db.Boolean, default=True)
    quantity = db.Column(db.Float, default=0.0)
    last_price = db.Column(db.Float, nullable=True)
    cost_price = db.Column(db.Float, nullable=True)
    current_value = db.Column(db.Float, default=0.0)
    unrealized_profit_loss = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(12), default='USD')
    synced_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'account_id', 'symbol', 'instrument_type', name='uq_webull_holding_user_account_symbol_type'),
        db.Index('ix_webull_holding_user', 'user_id'),
        db.Index('ix_webull_holding_option_contract', 'user_id', 'instrument_id'),
    )


class WebullTestAccount(db.Model):
    """Simulated paper trading account for Webull test mode."""
    __tablename__ = 'webull_test_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    cash_balance = db.Column(db.Float, default=0.0, nullable=False)
    currency = db.Column(db.String(10), default='USD', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'cash_balance': float(self.cash_balance or 0.0),
            'currency': self.currency or 'USD',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WebullTestPosition(db.Model):
    """Simulated holdings/positions for Webull paper trading."""
    __tablename__ = 'webull_test_positions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    symbol = db.Column(db.String(80), nullable=False)
    instrument_type = db.Column(db.String(40), default='EQUITY', nullable=False)
    side = db.Column(db.String(20), default='LONG', nullable=False)
    quantity = db.Column(db.Float, default=0.0, nullable=False)
    cost_price = db.Column(db.Float, default=0.0, nullable=False)
    last_price = db.Column(db.Float, default=0.0, nullable=True)
    market_value = db.Column(db.Float, default=0.0, nullable=True)
    unrealized_pnl = db.Column(db.Float, default=0.0, nullable=True)
    contract_multiplier = db.Column(db.Integer, default=1, nullable=False)
    option_type = db.Column(db.String(10), nullable=True)
    option_strike = db.Column(db.Float, nullable=True)
    option_expiration = db.Column(db.String(20), nullable=True)
    underlying_symbol = db.Column(db.String(40), nullable=True)
    event_outcome = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'symbol', 'instrument_type', 'side', name='uq_webull_test_pos_user_sym_type_side'),
        db.Index('ix_webull_test_pos_user_sym', 'user_id', 'symbol'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'underlying_symbol': self.underlying_symbol,
            'instrument_type': self.instrument_type,
            'side': self.side,
            'quantity': float(self.quantity or 0.0),
            'cost_price': float(self.cost_price or 0.0),
            'last_price': float(self.last_price or 0.0),
            'market_value': float(self.market_value or 0.0),
            'unrealized_pnl': float(self.unrealized_pnl or 0.0),
            'contract_multiplier': self.contract_multiplier,
            'option_type': self.option_type,
            'option_strike': self.option_strike,
            'option_expiration': self.option_expiration,
            'event_outcome': self.event_outcome,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WebullTestOrder(db.Model):
    """Simulated orders for Webull paper trading."""
    __tablename__ = 'webull_test_orders'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(80), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    symbol = db.Column(db.String(80), nullable=False)
    instrument_type = db.Column(db.String(40), default='EQUITY', nullable=False)
    side = db.Column(db.String(20), nullable=False)
    order_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    limit_price = db.Column(db.Float, nullable=True)
    stop_price = db.Column(db.Float, nullable=True)
    filled_price = db.Column(db.Float, nullable=True)
    filled_quantity = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='Filled', nullable=False)
    combo_type = db.Column(db.String(30), nullable=True)
    combo_orders = db.Column(db.Text, nullable=True)
    time_in_force = db.Column(db.String(20), default='DAY')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'instrument_type': self.instrument_type,
            'side': self.side,
            'order_type': self.order_type,
            'quantity': float(self.quantity or 0.0),
            'limit_price': self.limit_price,
            'stop_price': self.stop_price,
            'filled_price': self.filled_price,
            'filled_quantity': float(self.filled_quantity or 0.0),
            'status': self.status,
            'combo_type': self.combo_type,
            'combo_orders': self.combo_orders,
            'time_in_force': self.time_in_force,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ExternalSentimentSignal(db.Model):
    """A broker-neutral, stored AI signal for non-Binance instruments.

    This is deliberately separate from ``SentimentHistory``: that legacy table
    drives the Binance chart and depends on Binance price-history rows.  A
    connector supplies the instrument and evaluation price for this table, so
    future broker integrations can use the same lifecycle without pretending a
    stock or ETF is a Binance coin.
    """
    __tablename__ = 'external_sentiment_signals'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    provider = db.Column(db.String(40), nullable=False)  # e.g. webull
    account_id = db.Column(db.String(80), nullable=True)
    symbol = db.Column(db.String(80), nullable=False)
    instrument_type = db.Column(db.String(40), nullable=False)
    prompt_family = db.Column(db.String(40), nullable=False)  # crypto or equity
    recommendation = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    market_context = db.Column(db.Text, nullable=True)
    entry_price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(12), default='USD')
    provider_model = db.Column(db.String(100), nullable=True)
    ai_provider = db.Column(db.String(50), nullable=True)
    ai_tier = db.Column(db.String(50), nullable=True)
    search_status = db.Column(db.String(100), nullable=True)
    failover_history = db.Column(db.Text, nullable=True)
    origin = db.Column(db.String(20), default='manual')  # manual or scheduled
    forecast_horizon_hours = db.Column(db.Float, nullable=False, default=24.0)
    target_evaluation_at = db.Column(db.DateTime, nullable=False)
    grading_config = db.Column(db.Text, nullable=True)
    outcome_price = db.Column(db.Float, nullable=True)
    outcome_pct = db.Column(db.Float, nullable=True)
    outcome_status = db.Column(db.String(20), default='tracking')
    outcome_reason = db.Column(db.Text, nullable=True)
    outcome_evaluated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index('ix_external_sentiment_user_created', 'user_id', 'created_at'),
        db.Index('ix_external_sentiment_due', 'provider', 'target_evaluation_at'),
        db.Index('ix_external_sentiment_instrument', 'user_id', 'provider', 'symbol', 'instrument_type'),
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
    sentiment_reason = db.Column(db.Text, default="")
    volatility_pct = db.Column(db.Float, nullable=True)
    last_volatility_alert_time = db.Column(db.DateTime, nullable=True)
    auto_sell_enabled = db.Column(db.Boolean, default=False)
    auto_sell_volatility_pct = db.Column(db.Float, nullable=True)
    auto_sell_quote_currency = db.Column(db.String(10), default='USDT')
    auto_sell_triggered_at = db.Column(db.DateTime, nullable=True)
    auto_sell_confirmation_started_at = db.Column(db.DateTime, nullable=True)
    auto_buy_enabled = db.Column(db.Boolean, default=False)
    auto_buy_volatility_pct = db.Column(db.Float, nullable=True)
    auto_buy_quote_currency = db.Column(db.String(10), default='USDT')
    auto_buy_amount = db.Column(db.Float, nullable=True)
    auto_buy_triggered_at = db.Column(db.DateTime, nullable=True)
    auto_buy_confirmation_started_at = db.Column(db.DateTime, nullable=True)
    sentiment_last_updated = db.Column(db.DateTime, nullable=True)
    sentiment_provider = db.Column(db.String(50), nullable=True)
    sentiment_model = db.Column(db.String(100), nullable=True)
    sentiment_tier = db.Column(db.String(50), nullable=True)
    sentiment_search_status = db.Column(db.String(100), nullable=True)
    sentiment_failover_history = db.Column(db.Text, nullable=True)
    sentiment_tracking_enabled = db.Column(db.Boolean, default=True)
    # 'crypto' for Binance/crypto assets, 'stock' for stocks/ETFs priced via Yahoo Finance
    asset_type = db.Column(db.String(20), default='crypto')
    
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
    sentiment_prompt_pre = db.Column(db.Text)  # Portfolio Sentiment analysis pre-search prompt
    watchlist_sentiment_prompt_pre = db.Column(db.Text)  # Watchlist Sentiment analysis pre-search prompt
    copilot_chat_pre = db.Column(db.Text)  # AI Copilot pre-search prompt
    
    # Stage 2 (Post-search) prompts for final analysis
    coin_analysis_post = db.Column(db.Text)
    market_analysis_post = db.Column(db.Text)
    portfolio_review_post = db.Column(db.Text)
    risk_assessment_post = db.Column(db.Text)
    news_analysis_post = db.Column(db.Text)
    sentiment_prompt_post = db.Column(db.Text)  # Portfolio Sentiment analysis post-search prompt
    watchlist_sentiment_prompt_post = db.Column(db.Text)  # Watchlist Sentiment analysis post-search prompt
    copilot_chat_post = db.Column(db.Text)  # AI Copilot post-search prompt

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
    watchlist_sentiment_prompt_pre = db.Column(db.Text)
    copilot_chat_pre = db.Column(db.Text)
    
    # Stage 2 (Post-search) prompts
    coin_analysis_post = db.Column(db.Text)
    market_analysis_post = db.Column(db.Text)
    portfolio_review_post = db.Column(db.Text)
    risk_assessment_post = db.Column(db.Text)
    news_analysis_post = db.Column(db.Text)
    sentiment_prompt_post = db.Column(db.Text)
    watchlist_sentiment_prompt_post = db.Column(db.Text)
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
    provider = db.Column(db.String(50), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    tier = db.Column(db.String(50), nullable=True)
    
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


class AssetIconCache(db.Model):
    """Persistent provider metadata for cryptocurrency symbol icons."""
    __tablename__ = 'asset_icon_cache'

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False, unique=True, index=True)
    icon_url = db.Column(db.Text, nullable=True)
    asset_id = db.Column(db.String(120), nullable=True)
    asset_name = db.Column(db.String(200), nullable=True)
    provider = db.Column(db.String(50), nullable=False, default='CoinGecko')
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

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
    volume = db.Column(db.Float, default=0.0)
    quote_volume = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.BigInteger, nullable=False) # Unix timestamp
    exchange = db.Column(db.String(20), default='binance')
    date_int = db.Column(db.BigInteger, nullable=True)
    
    __table_args__ = (
        db.Index('ix_price_history_symbol_ts', 'symbol', 'timestamp'),
    )

class SentimentHistory(db.Model):
    """Historical sentiment log for accuracy and thesis tracking"""
    __tablename__ = 'sentiment_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    coin_id = db.Column(db.Integer, nullable=True)
    symbol = db.Column(db.String(20), nullable=False)
    source_type = db.Column(db.String(20), default='portfolio')  # 'portfolio' or 'watchlist'
    sentiment = db.Column(db.String(50), nullable=False)
    sentiment_reason = db.Column(db.Text, nullable=True)
    price_at_prediction = db.Column(db.Float, nullable=False, default=0.0)
    provider = db.Column(db.String(50), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    tier = db.Column(db.String(50), nullable=True)
    sentiment_search_status = db.Column(db.String(100), nullable=True)
    failover_history = db.Column(db.Text, nullable=True)
    outcome_price = db.Column(db.Float, nullable=True)
    outcome_pct = db.Column(db.Float, nullable=True)
    outcome_status = db.Column(db.String(20), default='tracking')  # 'correct', 'wrong', 'tracking', 'neutral'
    outcome_evaluated_at = db.Column(db.DateTime, nullable=True)
    forecast_horizon_hours = db.Column(db.Float, nullable=True)
    target_evaluation_at = db.Column(db.DateTime, nullable=True)
    evaluation_method = db.Column(db.String(32), nullable=True)
    grading_config = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_sentiment_history_user_id', 'user_id'),
        db.Index('ix_sentiment_history_symbol', 'symbol'),
        db.Index('ix_sentiment_history_created_at', 'created_at'),
    )
