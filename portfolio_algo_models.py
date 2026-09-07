"""Persistence models for the Webull Multi-Asset Quantitative Strategy Engine.

Maintains an isolated paper trading ledger (account, positions, orders)
and master portfolio configuration completely separated from manual Webull
Test Mode and Binance paper trading.
"""

import json
from datetime import datetime

from core.extensions import db
from services.portfolio_audit_context import ENGINE_PURPOSE, STRATEGY_RULES

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
    ENGINE_PURPOSE + "\nYou are the research CIO and operational auditor. Explain the observed paper portfolio, "
    "what each enabled strategy evaluated, what actually filled or exited, and why other entries were blocked. "
    "Assess net results only over the supplied sample; distinguish operational defects from normal waiting. "
    "Recommend prioritized, testable improvements grounded in recorded data and the configured strategy rules. "
    "MANDATORY FORMAT: Always begin with '## 1. Executive Summary' containing a concise 1 to 2 paragraph narrative TL;DR "
    "explaining: (1) what the user is looking at and current portfolio state, (2) how the strategy engine is performing, "
    "(3) any errors, warnings, or data gaps encountered, and (4) actionable suggestions to improve the quantitative strategy engine. "
    "Do not begin Section 1 with a table; provide the executive narrative first, followed by supporting tables."
)

DEFAULT_MODULE_SETTINGS = {
    "equities": {
        "enabled": True,
        "strategy": "Dual-Momentum Rotation & 2-Period RSI",
        "trend_sma_days": 200,
        "rsi_period": 2,
        "rsi_entry_threshold": 10,
        "bollinger_std": 2.0,
        "target_cagr_range": "12%–16%",
        "auditor_prompt": (
            "You are the equities paper-strategy auditor. " + STRATEGY_RULES["equities"] +
            " Explain actual scans, holdings, entry/exit eligibility, missing evidence and testable improvements. "
            "Use the saved strategy parameters; do not invent a replacement trading strategy."
        ),
    },
    "crypto": {
        "enabled": True,
        "strategy": "Adaptive Donchian Breakout & ATR Stops",
        "entry_channel_periods": 20,
        "exit_channel_periods": 10,
        "atr_stop_multiplier": 2.5,
        "target_cagr_range": "20%–35%",
        "auditor_prompt": (
            "You are the crypto paper-strategy auditor. " + STRATEGY_RULES["crypto"] +
            " Explain actual scans, holdings, entry/exit eligibility, missing evidence and testable improvements. "
            "Use the saved strategy parameters; do not invent a replacement trading strategy."
        ),
    },
    "options": {
        "enabled": True,
        "strategy": "Volatility Risk Premium 45-DTE Credit Spreads",
        "min_ivr": 40,
        "target_delta": 18,
        "target_dte": 45,
        "profit_target_pct": 50,
        "target_cagr_range": "18%–24%",
        "auditor_prompt": (
            "You are the options paper-strategy auditor. " + STRATEGY_RULES["options"] +
            " Explain actual scans, holdings, entry/exit eligibility, missing evidence and testable improvements. "
            "Use the saved strategy parameters; do not invent a replacement trading strategy."
        ),
    },
    "futures": {
        "enabled": False,
        "strategy": "Opening Range Breakout (ORB) & VWAP Confirmation",
        "opening_range_minutes": 15,
        "max_intraday_loss": 250.0,
        "target_cagr_range": "15%–22%",
        "auditor_prompt": (
            "You are the futures paper-strategy auditor. " + STRATEGY_RULES["futures"] +
            " Explain actual scans, holdings, entry/exit eligibility, missing evidence and testable improvements. "
            "Use the saved strategy parameters; do not invent a replacement trading strategy."
        ),
    },
    "events": {
        "enabled": True,
        "strategy": "Binary Probability & Velocity Arbitrage",
        "min_confidence": 0.50,
        "min_net_edge": 0.015,
        "target_cagr_range": "20%–30%",
        "auditor_prompt": (
            "You are the events paper-strategy auditor. " + STRATEGY_RULES["events"] +
            " Explain actual scans, holdings, entry/exit eligibility, missing evidence and testable improvements. "
            "Use the saved strategy parameters; do not invent a replacement trading strategy."
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


class PortfolioEngineLog(db.Model):
    __tablename__ = "portfolio_engine_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    level = db.Column(db.String(24), default="INFO", nullable=False)
    event_type = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False)
    details_json = db.Column(db.Text, default="{}", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


def _record_portfolio_log(user_id, event_type, message, level="INFO", **kwargs):
    import traceback
    try:
        from database import db
        details = json.dumps(kwargs)
        row = PortfolioEngineLog(user_id=user_id, level=level, event_type=event_type, message=message, details_json=details)
        db.session.add(row)
    except Exception as exc:
        print(f"Failed to record portfolio log: {exc}\n{traceback.format_exc()}")
