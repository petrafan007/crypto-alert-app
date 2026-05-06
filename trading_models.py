"""
Trading Models
Created: October 13, 2025
Purpose: SQLAlchemy models for trading functionality (test orders, real orders, test portfolio)
Database: exchange_logs.db (separate database binding)
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, BigInteger, Index
from core.extensions import db

class TestOrder(db.Model):
    """
    Test orders for simulated trading practice
    These orders validate against Binance.US but do not execute
    """
    __tablename__ = 'test_orders'
    # __bind_key__ removed for Postgres migration
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # BUY, SELL
    type = Column(String(20), nullable=False)  # LIMIT, MARKET, STOP_LOSS, etc.
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # NULL for MARKET orders
    stop_price = Column(Float, nullable=True)  # For STOP_LOSS orders
    time_in_force = Column(String(10), nullable=True)  # GTC, IOC, FOK
    status = Column(String(20), default='NEW')  # NEW, FILLED, CANCELED, REJECTED
    simulated_fill_price = Column(Float, nullable=True)
    simulated_fill_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    validation_response = Column(Text, nullable=True)  # JSON from Binance test endpoint
    notes = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_test_orders_user', 'user_id'),
        Index('idx_test_orders_symbol', 'symbol'),
        Index('idx_test_orders_status', 'status'),
    )
    
    def to_dict(self):
        """Convert model to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'side': self.side,
            'type': self.type,
            'quantity': self.quantity,
            'price': self.price,
            'stop_price': self.stop_price,
            'time_in_force': self.time_in_force,
            'status': self.status,
            'simulated_fill_price': self.simulated_fill_price,
            'simulated_fill_time': self.simulated_fill_time.isoformat() if self.simulated_fill_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notes': self.notes
        }

class RealOrder(db.Model):
    """
    Real orders placed on Binance.US
    These orders execute actual trades with real money
    """
    __tablename__ = 'real_orders'
    # __bind_key__ removed
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    type = Column(String(20), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    time_in_force = Column(String(10), nullable=True)
    status = Column(String(20), default='NEW')
    binance_order_id = Column(BigInteger, unique=True, nullable=True)
    binance_client_order_id = Column(String(100), nullable=True)
    executed_qty = Column(Float, default=0.0)
    cumulative_quote_qty = Column(Float, default=0.0)
    avg_fill_price = Column(Float, nullable=True)
    commission = Column(Float, nullable=True)
    commission_asset = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    order_response = Column(Text, nullable=True)  # Full JSON response from Binance
    fill_notified = Column(Boolean, default=False)
    
    __table_args__ = (
        Index('idx_real_orders_user', 'user_id'),
        Index('idx_real_orders_symbol', 'symbol'),
        Index('idx_real_orders_status', 'status'),
        Index('idx_real_orders_binance_id', 'binance_order_id'),
    )
    
    def to_dict(self):
        """Convert model to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'side': self.side,
            'type': self.type,
            'quantity': self.quantity,
            'price': self.price,
            'stop_price': self.stop_price,
            'time_in_force': self.time_in_force,
            'status': self.status,
            'binance_order_id': self.binance_order_id,
            'binance_client_order_id': self.binance_client_order_id,
            'executed_qty': self.executed_qty,
            'cumulative_quote_qty': self.cumulative_quote_qty,
            'avg_fill_price': self.avg_fill_price,
            'commission': self.commission,
            'commission_asset': self.commission_asset,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'canceled_at': self.canceled_at.isoformat() if self.canceled_at else None
        }

class TestPortfolio(db.Model):
    """
    Test portfolio for tracking simulated holdings
    Updated after each test order fill
    """
    __tablename__ = 'test_portfolio'
    # __bind_key__ removed
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)
    quantity = Column(Float, default=0.0)
    avg_entry_price = Column(Float, nullable=True)
    total_cost_basis = Column(Float, nullable=True)
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_test_portfolio_user', 'user_id'),
        Index('idx_test_portfolio_symbol', 'symbol'),
    )
    
    def to_dict(self):
        """Convert model to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'quantity': self.quantity,
            'avg_entry_price': self.avg_entry_price,
            'total_cost_basis': self.total_cost_basis,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.unrealized_pnl,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }

class TradingSettings(db.Model):
    """
    User-specific trading settings and preferences
    Controls test mode, order limits, safety features
    """
    __tablename__ = 'trading_settings'
    # __bind_key__ removed
    
    user_id = Column(Integer, primary_key=True)
    test_mode_enabled = Column(Boolean, default=True)  # Default to test mode for safety
    max_order_size_usd = Column(Float, default=1000.0)
    daily_trade_limit = Column(Integer, default=50)
    require_confirmation = Column(Boolean, default=True)
    require_2fa = Column(Boolean, default=False)  # Require 2FA for all orders
    totp_secret = Column(String(32), nullable=True)  # TOTP secret for 2FA
    default_time_in_force = Column(String(10), default='GTC')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    
    @property
    def totp_enabled(self):
        """Return True when a TOTP secret has been provisioned for the user."""
        return bool(self.totp_secret)

    def to_dict(self):
        """Convert model to dictionary for API responses"""
        return {
            'user_id': self.user_id,
            'test_mode_enabled': self.test_mode_enabled,
            'max_order_size_usd': self.max_order_size_usd,
            'daily_trade_limit': self.daily_trade_limit,
            'require_confirmation': self.require_confirmation,
            'require_2fa': self.require_2fa,
            'totp_enabled': bool(self.totp_secret),  # Don't expose the secret
            'default_time_in_force': self.default_time_in_force,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class AllActivity(db.Model):
    """
    Consolidated activity log for all exchanges and actions
    """
    __tablename__ = 'all_activities'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False)
    type = Column(String(20), nullable=False)
    asset = Column(String(10), nullable=False)
    amount = Column(Float, nullable=False)
    proceeds = Column(Float, nullable=True)
    cost_basis = Column(Float, nullable=True)
    gain_loss = Column(Float, nullable=True)
    fee = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    avg_entry = Column(Float, nullable=True)
    exchange = Column(String(20), nullable=True)
    status = Column(String(20), default='completed')
    details = Column(Text, nullable=True)
    txid = Column(String(100), nullable=True)
    price_sold_at = Column(Float, nullable=True)
    
    __table_args__ = (
        Index('idx_all_activities_user', 'user_id'),
        Index('idx_all_activities_date', 'date'),
    )

class PortfolioValueHistory(db.Model):
    """
    Snapshot of portfolio value over time
    """
    __tablename__ = 'portfolio_value_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    date = Column(String(30), nullable=True)
    timestamp = Column(DateTime, nullable=True)
    value = Column(Float, nullable=False)
    change_24h = Column(Float, nullable=True)
    change_pct_24h = Column(Float, nullable=True)
    
    __table_args__ = (
        Index('idx_portfolio_history_user', 'user_id'),
        Index('idx_portfolio_history_date', 'date'),
    )
class StakingOrder(db.Model):
    """
    Staking orders for Binance.US
    """
    __tablename__ = 'staking_orders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)
    action = Column(String(20), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)
    transaction_id = Column(String(100), nullable=True)
    auto_restake = Column(Boolean, default=False)
    apr = Column(Float, nullable=True)
    apy = Column(Float, nullable=True)
    reward_asset = Column(String(20), nullable=True)
    usd_value = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    extra_metadata = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_staking_orders_user_action', 'user_id', 'action'),
        Index('idx_staking_orders_txid', 'transaction_id'),
    )
    
    def to_dict(self):
        """Convert model to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'action': self.action,
            'amount': self.amount,
            'status': self.status,
            'transaction_id': self.transaction_id,
            'auto_restake': self.auto_restake,
            'apr': self.apr,
            'apy': self.apy,
            'reward_asset': self.reward_asset,
            'usd_value': self.usd_value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'metadata': self.extra_metadata
        }
