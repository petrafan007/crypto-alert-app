"""Persistence models for the Webull Event Contract strategy engine.

The strategy engine deliberately keeps its research/decision ledger separate
from the ordinary trading ledgers.  This lets paper research run without
mutating live order tables and preserves enough provenance to reproduce every
decision later.
"""

from datetime import datetime

from core.extensions import db


class EventStrategyConfig(db.Model):
    __tablename__ = "event_strategy_configs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    mode = db.Column(db.String(12), default="PAPER", nullable=False)
    worker_status = db.Column(db.String(24), default="STOPPED", nullable=False)
    strategy_version = db.Column(db.String(40), default="1.0.0", nullable=False)
    model_version = db.Column(db.String(80), default="empirical-v1", nullable=False)
    symbols = db.Column(db.Text, default="[\"BTC\", \"ETH\"]", nullable=False)
    durations = db.Column(db.Text, default="[\"FIFTEEN_MINUTES\", \"HOURLY\"]", nullable=False)
    risk_config = db.Column(db.Text, default="{}", nullable=False)
    signal_config = db.Column(db.Text, default="{}", nullable=False)
    kill_switch = db.Column(db.Boolean, default=False, nullable=False)
    last_run_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_event_strategy_config_user_name"),
        db.Index("ix_event_strategy_config_user_enabled", "user_id", "enabled"),
    )


class EventStrategyRun(db.Model):
    __tablename__ = "event_strategy_runs"

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    mode = db.Column(db.String(12), default="PAPER", nullable=False)
    status = db.Column(db.String(24), default="STARTING", nullable=False)
    worker_id = db.Column(db.String(120), nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)
    heartbeat_at = db.Column(db.DateTime, nullable=True)
    scanned_count = db.Column(db.Integer, default=0, nullable=False)
    qualified_count = db.Column(db.Integer, default=0, nullable=False)
    no_trade_count = db.Column(db.Integer, default=0, nullable=False)
    error_count = db.Column(db.Integer, default=0, nullable=False)
    paper_equity = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    diagnostics_json = db.Column(db.Text, default="[]", nullable=False)

    __table_args__ = (
        db.Index("ix_event_strategy_run_user_started", "user_id", "started_at"),
        db.Index("ix_event_strategy_run_config_status", "config_id", "status"),
    )


class EventMarketSnapshot(db.Model):
    __tablename__ = "event_market_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    config_id = db.Column(db.Integer, nullable=True, index=True)
    run_id = db.Column(db.Integer, nullable=True, index=True)
    contract_symbol = db.Column(db.String(160), nullable=False)
    category_code = db.Column(db.String(60), nullable=True)
    series_symbol = db.Column(db.String(120), nullable=True)
    underlying_symbol = db.Column(db.String(40), nullable=True)
    provider_timestamp = db.Column(db.DateTime, nullable=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    cutoff_at = db.Column(db.DateTime, nullable=True)
    yes_bid = db.Column(db.Float, nullable=True)
    yes_ask = db.Column(db.Float, nullable=True)
    no_bid = db.Column(db.Float, nullable=True)
    no_ask = db.Column(db.Float, nullable=True)
    yes_bid_size = db.Column(db.Float, nullable=True)
    yes_ask_size = db.Column(db.Float, nullable=True)
    no_bid_size = db.Column(db.Float, nullable=True)
    no_ask_size = db.Column(db.Float, nullable=True)
    volume = db.Column(db.Float, nullable=True)
    open_interest = db.Column(db.Float, nullable=True)
    underlying_price = db.Column(db.Float, nullable=True)
    underlying_change_pct = db.Column(db.Float, nullable=True)
    realized_volatility = db.Column(db.Float, nullable=True)
    time_remaining_seconds = db.Column(db.Float, nullable=True)
    spread_yes = db.Column(db.Float, nullable=True)
    spread_no = db.Column(db.Float, nullable=True)
    feature_json = db.Column(db.Text, default="{}", nullable=False)
    raw_json = db.Column(db.Text, default="{}", nullable=False)

    __table_args__ = (
        db.Index("ix_event_snapshot_contract_received", "contract_symbol", "received_at"),
        db.Index("ix_event_snapshot_user_received", "user_id", "received_at"),
    )


class EventStrategyDecision(db.Model):
    __tablename__ = "event_strategy_decisions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    config_id = db.Column(db.Integer, nullable=False, index=True)
    run_id = db.Column(db.Integer, nullable=True, index=True)
    snapshot_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    contract_symbol = db.Column(db.String(160), nullable=False)
    action = db.Column(db.String(24), nullable=False)
    outcome = db.Column(db.String(8), nullable=True)
    reason_codes = db.Column(db.Text, default="[]", nullable=False)
    probability_yes = db.Column(db.Float, nullable=True)
    probability_no = db.Column(db.Float, nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    fair_value_yes = db.Column(db.Float, nullable=True)
    fair_value_no = db.Column(db.Float, nullable=True)
    executable_price = db.Column(db.Float, nullable=True)
    gross_edge = db.Column(db.Float, nullable=True)
    net_edge = db.Column(db.Float, nullable=True)
    opportunity_score = db.Column(db.Float, nullable=True)
    eligible = db.Column(db.Boolean, default=False, nullable=False)
    model_version = db.Column(db.String(80), nullable=True)
    feature_json = db.Column(db.Text, default="{}", nullable=False)

    __table_args__ = (
        db.Index("ix_event_decision_user_created", "user_id", "created_at"),
        db.Index("ix_event_decision_contract_created", "contract_symbol", "created_at"),
        db.Index("ix_event_decision_action", "action"),
    )


class EventStrategyOrder(db.Model):
    __tablename__ = "event_strategy_orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    config_id = db.Column(db.Integer, nullable=False, index=True)
    decision_id = db.Column(db.Integer, nullable=True, index=True)
    mode = db.Column(db.String(12), default="PAPER", nullable=False)
    broker = db.Column(db.String(30), default="WEBULL", nullable=False)
    client_order_id = db.Column(db.String(120), nullable=True, unique=True)
    provider_order_id = db.Column(db.String(120), nullable=True)
    contract_symbol = db.Column(db.String(160), nullable=False)
    outcome = db.Column(db.String(8), nullable=False)
    side = db.Column(db.String(12), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    limit_price = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(30), default="SIMULATED", nullable=False)
    filled_quantity = db.Column(db.Float, default=0.0, nullable=False)
    filled_price = db.Column(db.Float, nullable=True)
    fee = db.Column(db.Float, default=0.0, nullable=False)
    realized_pnl = db.Column(db.Float, default=0.0, nullable=False)
    settled_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    rejection_code = db.Column(db.String(80), nullable=True)

    __table_args__ = (
        db.Index("ix_event_strategy_order_user_submitted", "user_id", "submitted_at"),
        db.Index("ix_event_strategy_order_status", "status"),
    )


class EventStrategyPosition(db.Model):
    __tablename__ = "event_strategy_positions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    config_id = db.Column(db.Integer, nullable=False, index=True)
    mode = db.Column(db.String(12), default="PAPER", nullable=False)
    contract_symbol = db.Column(db.String(160), nullable=False)
    outcome = db.Column(db.String(8), nullable=False)
    quantity = db.Column(db.Float, default=0.0, nullable=False)
    average_entry_price = db.Column(db.Float, default=0.0, nullable=False)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    last_mark_price = db.Column(db.Float, nullable=True)
    realized_pnl = db.Column(db.Float, default=0.0, nullable=False)
    unrealized_pnl = db.Column(db.Float, default=0.0, nullable=False)
    exit_reason = db.Column(db.String(80), nullable=True)

    __table_args__ = (
        db.Index("ix_event_position_user_opened", "user_id", "opened_at"),
        db.Index("ix_event_position_contract_mode", "contract_symbol", "mode"),
    )


class EventStrategyPerformance(db.Model):
    __tablename__ = "event_strategy_performance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    config_id = db.Column(db.Integer, nullable=False, index=True)
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)
    strategy_version = db.Column(db.String(40), nullable=False)
    model_version = db.Column(db.String(80), nullable=False)
    mode = db.Column(db.String(12), default="PAPER", nullable=False)
    symbol = db.Column(db.String(40), nullable=True)
    duration = db.Column(db.String(40), nullable=True)
    trades = db.Column(db.Integer, default=0, nullable=False)
    wins = db.Column(db.Integer, default=0, nullable=False)
    losses = db.Column(db.Integer, default=0, nullable=False)
    gross_pnl = db.Column(db.Float, default=0.0, nullable=False)
    fees = db.Column(db.Float, default=0.0, nullable=False)
    net_pnl = db.Column(db.Float, default=0.0, nullable=False)
    max_drawdown = db.Column(db.Float, default=0.0, nullable=False)
    profit_factor = db.Column(db.Float, nullable=True)
    expectancy = db.Column(db.Float, nullable=True)
    brier_score = db.Column(db.Float, nullable=True)
    calibration_error = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index("ix_event_performance_user_period", "user_id", "period_start", "period_end"),
        db.Index("ix_event_performance_config_mode", "config_id", "mode"),
    )


class EventContractOutcome(db.Model):
    """Provider-confirmed settlement for a Webull Event Contract.

    Outcomes are deliberately separate from snapshots and decisions: a quote
    can be stale or disappear, while a settlement is immutable evidence.  The
    engine never infers YES/NO from a price; unresolved contracts remain
    PENDING until Webull supplies an explicit result.
    """

    __tablename__ = "event_contract_outcomes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    config_id = db.Column(db.Integer, nullable=True, index=True)
    contract_symbol = db.Column(db.String(160), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, nullable=True, index=True)
    decision_id = db.Column(db.Integer, nullable=True, index=True)
    outcome = db.Column(db.String(8), nullable=True)
    settlement_status = db.Column(db.String(20), default="PENDING", nullable=False)
    provider_timestamp = db.Column(db.DateTime, nullable=True)
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    cutoff_at = db.Column(db.DateTime, nullable=True)
    settlement_at = db.Column(db.DateTime, nullable=True)
    settlement_price = db.Column(db.Float, nullable=True)
    resolved_source = db.Column(db.String(40), nullable=True)
    raw_json = db.Column(db.Text, default="{}", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index("ix_event_outcome_user_status", "user_id", "settlement_status"),
        db.Index("ix_event_outcome_contract_cutoff", "contract_symbol", "cutoff_at"),
    )
