"""Persistence models for the Webull Multi-Asset Quantitative Strategy Engine.

Maintains an isolated paper trading ledger (account, positions, orders)
and master portfolio configuration completely separated from manual Webull
Test Mode and Binance paper trading.
"""

import json
from datetime import datetime

from core.extensions import db

DEFAULT_QUANT_WATCHLISTS = {
    "equities": ["SPY", "QQQ", "IWM", "SMH", "XLK", "NVDA", "AAPL", "MSFT", "AMZN", "TSLA"],
    "crypto": ["BTC", "ETH", "SOL"],
    "options": ["SPY", "QQQ", "IWM", "NVDA", "TSLA"],
    "futures": ["MES", "MNQ", "MGC", "MCL"],
    "events": ["KXBTC15M", "KXBTCD", "KXETH15M", "KXINXD"],
}

DEFAULT_ALLOCATIONS = {
    "equities": 35.0,
    "options": 25.0,
    "crypto": 20.0,
    "futures": 10.0,
    "events": 10.0,
}

DEFAULT_MASTER_CIO_PROMPT = (
    "You are the Quantitative Chief Investment Officer (CIO) and Portfolio Risk Auditor for an autonomous multi-asset "
    "trading engine. Your mandate is to evaluate the blended portfolio ($50,000 baseline) across 5 asset classes "
    "(Equities & ETFs, Options Strategies, Cryptocurrency Spot, Micro Futures, and Event Contracts). "
    "Audit portfolio progress toward the net annual target (16.5%–21.0% CAGR), detect cross-asset correlation spikes, "
    "identify whether any asset allocation has drifted beyond target risk weights, and issue strategic capital rebalancing directives."
)

DEFAULT_MODULE_SETTINGS = {
    "equities": {
        "strategy": "Dual-Momentum Rotation & 2-Period RSI",
        "trend_sma_days": 200,
        "rsi_period": 2,
        "rsi_entry_threshold": 10,
        "bollinger_std": 2.0,
        "target_cagr_range": "12%–16%",
        "specialist_prompt": (
            "You are a quantitative equities specialist. Evaluate 200-day SMA trend alignment, sector momentum "
            "divergence (SMH, XLK, SPY), and short-term 2-day RSI oversold pullbacks across US equities and ETFs."
        ),
    },
    "crypto": {
        "strategy": "Adaptive Donchian Breakout & ATR Stops",
        "entry_channel_periods": 20,
        "exit_channel_periods": 10,
        "atr_stop_multiplier": 2.5,
        "target_cagr_range": "20%–35%",
        "specialist_prompt": (
            "You are a quantitative crypto assets specialist. Evaluate Donchian channel breakouts, Bitcoin dominance "
            "trends, on-chain volume surges, and ATR trailing stop discipline for BTC, ETH, and SOL."
        ),
    },
    "options": {
        "strategy": "Volatility Risk Premium 45-DTE Credit Spreads",
        "min_ivr": 40,
        "target_delta": 18,
        "target_dte": 45,
        "profit_target_pct": 50,
        "target_cagr_range": "18%–24%",
        "specialist_prompt": (
            "You are a quantitative options volatility specialist. Analyze Implied Volatility Rank (IVR), Greeks "
            "(Delta, Gamma, Theta decay, Vega), and volatility skew for 45-DTE out-of-the-money credit spreads."
        ),
    },
    "futures": {
        "strategy": "Opening Range Breakout (ORB) & VWAP Reversion",
        "opening_range_minutes": 15,
        "max_intraday_loss": 250.0,
        "target_cagr_range": "15%–22%",
        "specialist_prompt": (
            "You are a quantitative futures intraday specialist. Evaluate the 15-minute Opening Range Breakout (ORB), "
            "institutional volume at cash open (9:30 AM ET), and Volume-Weighted Average Price (VWAP) distance on MES and MNQ."
        ),
    },
    "events": {
        "strategy": "Binary Probability & Velocity Arbitrage",
        "min_confidence": 0.50,
        "min_net_edge": 0.015,
        "target_cagr_range": "20%–30%",
        "specialist_prompt": (
            "You are a quantitative binary event derivatives specialist. Audit 15-minute and hourly BTC/ETH event contracts, "
            "order book probability mispricings, and underlying spot velocity to capture risk-adjusted net edge."
        ),
    },
}


class PortfolioStrategyConfig(db.Model):
    __tablename__ = "portfolio_strategy_configs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), default="Default Multi-Asset Portfolio", nullable=False)
    total_bankroll = db.Column(db.Float, default=50000.0, nullable=False)
    target_annual_return = db.Column(db.Float, default=18.5, nullable=False)
    allocations_json = db.Column(db.Text, default=json.dumps(DEFAULT_ALLOCATIONS), nullable=False)
    watchlists_json = db.Column(db.Text, default=json.dumps(DEFAULT_QUANT_WATCHLISTS), nullable=False)
    module_settings_json = db.Column(db.Text, default=json.dumps(DEFAULT_MODULE_SETTINGS), nullable=False)
    master_ai_prompt = db.Column(db.Text, default=DEFAULT_MASTER_CIO_PROMPT, nullable=False)
    master_ai_config = db.Column(db.Text, default="{}", nullable=False)
    mode = db.Column(db.String(12), default="PAPER", nullable=False)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    worker_status = db.Column(db.String(24), default="STOPPED", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_portfolio_strategy_config_user_name"),
        db.Index("ix_portfolio_strategy_config_user_enabled", "user_id", "enabled"),
    )


class PortfolioStrategyAccount(db.Model):
    __tablename__ = "portfolio_strategy_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    initial_balance = db.Column(db.Float, default=50000.0, nullable=False)
    cash_balance = db.Column(db.Float, default=50000.0, nullable=False)
    total_equity = db.Column(db.Float, default=50000.0, nullable=False)
    currency = db.Column(db.String(10), default="USD", nullable=False)
    reset_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PortfolioStrategyPosition(db.Model):
    __tablename__ = "portfolio_strategy_positions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    symbol = db.Column(db.String(64), nullable=False)
    instrument_type = db.Column(db.String(24), nullable=False)  # EQUITY, CRYPTO, OPTION, FUTURES, EVENT
    side = db.Column(db.String(8), default="LONG", nullable=False)  # LONG, SHORT
    quantity = db.Column(db.Float, default=0.0, nullable=False)
    average_cost = db.Column(db.Float, default=0.0, nullable=False)
    market_price = db.Column(db.Float, default=0.0, nullable=False)
    market_value = db.Column(db.Float, default=0.0, nullable=False)
    unrealized_pnl = db.Column(db.Float, default=0.0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PortfolioStrategyOrder(db.Model):
    __tablename__ = "portfolio_strategy_orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    module_name = db.Column(db.String(32), nullable=False)  # EQUITIES, CRYPTO, OPTIONS, FUTURES, EVENTS
    symbol = db.Column(db.String(64), nullable=False)
    instrument_type = db.Column(db.String(24), nullable=False)
    side = db.Column(db.String(8), nullable=False)  # BUY, SELL
    order_type = db.Column(db.String(16), default="MARKET", nullable=False)
    quantity = db.Column(db.Float, default=0.0, nullable=False)
    price = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(24), default="FILLED", nullable=False)
    pnl = db.Column(db.Float, default=0.0, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PortfolioEngineState(db.Model):
    """Worker ownership and reset generations; existing v2.88 tables stay intact."""
    __tablename__ = "portfolio_engine_states"
    user_id = db.Column(db.Integer, primary_key=True)
    generation = db.Column(db.Integer, default=1, nullable=False)
    kill_switch = db.Column(db.Boolean, default=False, nullable=False)
    pause_reason = db.Column(db.Text)
    lease_token = db.Column(db.String(64))
    lease_until = db.Column(db.DateTime)
    heartbeat_at = db.Column(db.DateTime)
    last_scan_at = db.Column(db.DateTime)
    last_audit_at = db.Column(db.DateTime)
    telemetry_json = db.Column(db.Text, default="{}", nullable=False)


class PortfolioStrategyLot(db.Model):
    """Collateral, exits and provenance for a position, including archived runs."""
    __tablename__ = "portfolio_strategy_lots"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    position_id = db.Column(db.Integer, db.ForeignKey("portfolio_strategy_positions.id"), unique=True, nullable=False)
    generation = db.Column(db.Integer, nullable=False, index=True)
    module = db.Column(db.String(16), nullable=False)
    signal_key = db.Column(db.String(240), nullable=False)
    collateral = db.Column(db.Float, nullable=False)
    multiplier = db.Column(db.Float, default=1.0, nullable=False)
    stop_price = db.Column(db.Float)
    target_price = db.Column(db.Float)
    entry_fee = db.Column(db.Float, default=0.0, nullable=False)
    realized_pnl = db.Column(db.Float, default=0.0, nullable=False)
    details_json = db.Column(db.Text, default="{}", nullable=False)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint("user_id", "generation", "signal_key", name="uq_portfolio_lot_signal"),)


class PortfolioEquitySnapshot(db.Model):
    __tablename__ = "portfolio_equity_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    generation = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    equity = db.Column(db.Float, nullable=False)
    cash = db.Column(db.Float, nullable=False)
    realized_pnl = db.Column(db.Float, nullable=False)
    unrealized_pnl = db.Column(db.Float, nullable=False)
    modules_json = db.Column(db.Text, default="{}", nullable=False)


class PortfolioAudit(db.Model):
    __tablename__ = "portfolio_strategy_audits"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    generation = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(24), default="PENDING", nullable=False)
    content = db.Column(db.Text)
    evidence_json = db.Column(db.Text, default="{}", nullable=False)
    provider = db.Column(db.String(80))
    model = db.Column(db.String(120))


class PortfolioMarketObservation(db.Model):
    """Daily measured IV and Bitcoin dominance; never fabricate a warm-up history."""
    __tablename__ = "portfolio_market_observations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    series = db.Column(db.String(80), nullable=False)
    day = db.Column(db.Date, nullable=False)
    value = db.Column(db.Float, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "series", "day", name="uq_portfolio_observation_day"),)
