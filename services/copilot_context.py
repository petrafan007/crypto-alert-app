"""Role-aware account context for the interactive AI Copilot.

The Copilot is read-only. These helpers expose the same persisted Webull and
quantitative-engine records used by the dashboard while keeping credentials
and provider secrets out of third-party AI requests.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from core.extensions import db


WEBULL_ORDER_CONTEXT_LIMIT = 500
WEBULL_SIGNAL_CONTEXT_LIMIT = 100
QUANT_LOG_CONTEXT_LIMIT = 500
QUANT_REPORT_CONTEXT_LIMIT = 50

DEFAULT_COPILOT_SEARCH_PROMPT = (
    "You are the search intelligence module for the AI Copilot in Crypto & Securities Dashboard as of {datetime}. "
    "You assist a multi-asset trader whose fresh request context can include Binance.US holdings and orders; "
    "Webull Real Trading accounts, holdings, watchlist, provider orders, and AI signals; Webull Test Mode cash, "
    "positions, and simulated orders; and, for authorized administrators only, the isolated paper Quantitative "
    "Strategy Engine's settings, runtime state, ledgers, logs, and audit reports. Preserve all exchange, account, "
    "and mode boundaries. Analyze the inquiry and selected isolated chat session to generate 1 to 3 targeted "
    "searches for time-sensitive external market facts. Do not search for facts already supplied by the authoritative "
    "live database snapshot, and never treat historical chat text as current account state."
)

DEFAULT_COPILOT_RESPONSE_PROMPT = (
    "You are the AI Copilot for Crypto & Securities Dashboard, an expert cross-asset portfolio strategist and "
    "multi-market analyst. You receive an authoritative, user-scoped database snapshot as of {datetime}, plus an "
    "isolated Copilot session and fresh search results for time-sensitive external facts. The snapshot can contain "
    "Binance.US, Webull Real Trading, Webull Test Mode, and—only for authorized administrators—the paper "
    "Quantitative Strategy Engine. Earlier sessions are historical reference only when explicitly supplied.\n\n"
    "When answering the user:\n"
    "- Provide actionable, data-backed guidance using current exposure, technical momentum, sentiment, risk/reward, "
    "orders, and recorded execution evidence across cryptocurrency and securities.\n"
    "- Keep Binance.US, Webull Real Trading, Webull Test Mode, and Quantitative Strategy Mode records separate. "
    "Real Trading is provider-backed, Test Mode is simulated, and Quantitative Strategy Mode is an isolated, "
    "administrator-only paper ledger that must never be described as a live Webull brokerage order.\n"
    "- Use the supplied Webull account summaries, positions, watchlist, open/recent orders, and AI signals when they "
    "are relevant; do not fall back to Binance-only assumptions.\n"
    "- When administrator-only quantitative context is present, use its full operational settings, current state, "
    "positions/orders, logs, and audit reports. Cite record IDs and timestamps where useful, honor each window's "
    "counts/truncation metadata, and distinguish recorded evidence from recommendations. If the section is absent, "
    "do not infer or disclose quantitative-engine data.\n"
    "- Explain the drivers behind sentiment signals and directly address proposed trades, entry/exit targets, and "
    "market trends with clear reasoning.\n"
    "- Use fresh web-search results for time-sensitive market claims. For owned or watched assets, verify ownership, "
    "balances, orders, and watchlist status against the live snapshot and never substitute old chat context.\n"
    "- Treat redacted credentials as unavailable secret values; never reconstruct, request, or claim access to them.\n"
    "- On Binance and Binance.US, a stored OCO Order List contains natively linked STOP_LOSS_LIMIT and LIMIT_MAKER "
    "legs. Analyze an identified orderListId as one exchange-managed OCO whose opposing leg is automatically canceled; "
    "never call those legs unlinked or instruct the user to link them.\n"
    "- Maintain a concise, structured, professional tone."
)

COPILOT_CONTEXT_INTEGRITY_RULES = (
    "\n\nMANDATORY COPILOT MODE, AUTHORIZATION, AND DATA-INTEGRITY RULES:\n"
    "- Treat the LIVE USER DATABASE SNAPSHOT in this request as authoritative for current holdings, balances, "
    "watchlists, orders, signals, and engine state. Conversation history cannot override it.\n"
    "- Keep Binance.US, Webull REAL, Webull TEST, and administrator-only QUANT records explicitly separated. REAL "
    "records are provider-backed; TEST records are simulated; QUANT records are isolated paper-strategy evidence "
    "and are never live Webull broker orders.\n"
    "- Use Webull data whenever supplied instead of assuming the user's portfolio, watchlist, or orders are "
    "Binance-only.\n"
    "- Only use quantitative settings, state, ledgers, logs, and reports when the request contains the explicitly "
    "labeled ADMINISTRATOR-ONLY context. Its absence means access was not authorized. Honor record-window counts and "
    "truncation flags, and do not claim to have inspected records outside the supplied window.\n"
    "- Credential and secret values are intentionally redacted. Never infer, reproduce, or expose them.\n"
    "- Use supplied fresh search results for time-sensitive external claims. State plainly when current external data "
    "is unavailable.\n"
    "- A Binance/Binance.US OCO with an orderListId is one native exchange-linked Order List; never describe its "
    "STOP_LOSS_LIMIT and LIMIT_MAKER legs as independent or instruct the user to link them."
)

_SENSITIVE_KEY = re.compile(
    r"(?:api[^a-z0-9]*key|access[^a-z0-9]*token|refresh[^a-z0-9]*token|secret|password|credential)",
    re.IGNORECASE,
)


def _iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat() + ("Z" if isinstance(value, datetime) and value.tzinfo is None else "")
    return value


def _json_value(value, default):
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _redact_secrets(value):
    """Preserve configuration topology without sending stored secret values."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                result[key] = "[CONFIGURED - VALUE REDACTED]" if item else None
            else:
                result[key] = _redact_secrets(item)
        return result
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return _iso(value)


def _window(query, order_column, limit):
    """Return the dashboard-sized newest record window and its total count."""
    total = query.count()
    rows = query.order_by(order_column.desc()).limit(limit).all()
    return rows, {
        "total_records": total,
        "records_in_context": len(rows),
        "newest_first": True,
        "window_truncated": total > len(rows),
    }


def _account_ref(account_id, accounts):
    account_id = str(account_id or "")
    account = accounts.get(account_id, {})
    label = account.get("account_name") or account.get("account_type") or "Webull account"
    suffix = account_id[-4:] if account_id else "none"
    return f"{label} (...{suffix})"


def build_webull_copilot_snapshot(user_id, holdings=None):
    """Return complete current Webull real/test state plus bounded ledgers."""
    from credentials import UserSetting
    from models import (
        ExternalSentimentSignal,
        WebullAccountSnapshot,
        WebullHolding,
        WebullOrder,
        WebullTestAccount,
        WebullTestOrder,
        WebullTestPosition,
        WebullWatchlistItem,
    )

    settings = UserSetting.query.filter_by(user_id=user_id).first()
    account_rows = WebullAccountSnapshot.query.filter_by(user_id=user_id).order_by(
        WebullAccountSnapshot.account_type.asc(), WebullAccountSnapshot.id.asc()
    ).all()
    accounts_by_id = {
        str(row.account_id): {
            "account_name": row.account_name,
            "account_type": row.account_type,
        }
        for row in account_rows
    }

    configured_aliases = _json_value(getattr(settings, "webull_account_aliases", None), {}) if settings else {}
    if not isinstance(configured_aliases, dict):
        configured_aliases = {}
    enabled_account_ids = _json_value(getattr(settings, "webull_enabled_account_ids", None), []) if settings else []
    if not isinstance(enabled_account_ids, list):
        enabled_account_ids = []
    enabled_ids = set(str(value) for value in enabled_account_ids)
    default_account_id = str(getattr(settings, "webull_default_account_id", "") or "") if settings else ""

    real_accounts = []
    for row in account_rows:
        account_id = str(row.account_id or "")
        real_accounts.append({
            "account_ref": _account_ref(account_id, accounts_by_id),
            "account_name": configured_aliases.get(account_id) or row.account_name,
            "provider_account_type": row.account_type,
            "enabled": not enabled_ids or account_id in enabled_ids,
            "default_for_trading": bool(default_account_id and account_id == default_account_id),
            "currency": row.currency,
            "net_liquidation_value": row.total_net_liquidation_value,
            "cash_balance": row.total_cash_balance,
            "market_value": row.total_market_value,
            "unrealized_profit_loss": row.total_unrealized_profit_loss,
            "synced_at": _iso(row.synced_at),
        })

    holding_rows = holdings if holdings is not None else WebullHolding.query.filter_by(user_id=user_id).all()
    real_holdings = [{
        "account_ref": _account_ref(row.account_id, accounts_by_id),
        "symbol": row.symbol,
        "display_name": row.display_name,
        "instrument_type": row.instrument_type,
        "is_etf": bool(row.is_etf),
        "quantity": row.quantity,
        "last_price": row.last_price,
        "cost_price": row.cost_price,
        "current_value": row.current_value,
        "unrealized_profit_loss": row.unrealized_profit_loss,
        "currency": row.currency,
        "underlying_symbol": row.underlying_symbol,
        "option_type": row.option_type,
        "option_strike": row.option_strike,
        "option_expiration": row.option_expiration,
        "option_multiplier": row.option_multiplier,
        "event_outcome": row.event_outcome,
        "monitoring": {
            "alert_enabled": bool(row.alert_enabled),
            "lower_threshold_type": row.custom_lower_type,
            "lower_threshold_value": row.custom_lower_val,
            "lower_threshold_pct": row.custom_lower_pct,
            "upper_threshold_type": row.custom_upper_type,
            "upper_threshold_value": row.custom_upper_val,
            "upper_threshold_pct": row.custom_upper_pct,
            "volatility_pct": row.volatility_pct,
            "sentiment_tracking_enabled": bool(row.sentiment_tracking_enabled),
            "hidden": bool(row.hidden),
        },
        "synced_at": _iso(row.synced_at),
    } for row in holding_rows]

    watchlist_rows = WebullWatchlistItem.query.filter_by(user_id=user_id).order_by(
        WebullWatchlistItem.id.asc()
    ).all()
    real_watchlist = [{
        "symbol": row.symbol,
        "display_name": row.display_name,
        "instrument_type": row.instrument_type,
        "underlying_symbol": row.underlying_symbol,
        "event_outcome": row.event_outcome,
        "last_price": row.last_price,
        "currency": row.currency,
        "alert_enabled": bool(row.alert_enabled),
        "note": row.note,
        "refreshed_at": _iso(row.refreshed_at),
    } for row in watchlist_rows]

    real_order_rows, real_order_window = _window(
        WebullOrder.query.filter_by(user_id=user_id), WebullOrder.created_at, WEBULL_ORDER_CONTEXT_LIMIT
    )
    real_orders = [{
        "id": row.id,
        "account_ref": _account_ref(row.account_id, accounts_by_id),
        "provider_order_id": row.provider_order_id,
        "client_order_id": row.client_order_id,
        "symbol": row.symbol,
        "instrument_type": row.instrument_type,
        "event_outcome": row.event_outcome,
        "side": row.side,
        "order_type": row.order_type,
        "quantity": row.quantity,
        "filled_quantity": row.filled_quantity,
        "price": row.price,
        "filled_price": row.filled_price,
        "fee": row.fee,
        "fee_asset": row.fee_asset,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "synced_at": _iso(row.synced_at),
    } for row in real_order_rows]

    signal_rows, signal_window = _window(
        ExternalSentimentSignal.query.filter_by(user_id=user_id, provider="webull"),
        ExternalSentimentSignal.created_at,
        WEBULL_SIGNAL_CONTEXT_LIMIT,
    )
    real_signals = [{
        "id": row.id,
        "symbol": row.symbol,
        "instrument_type": row.instrument_type,
        "recommendation": row.recommendation,
        "reason": row.reason,
        "entry_price": row.entry_price,
        "currency": row.currency,
        "origin": row.origin,
        "forecast_horizon_hours": row.forecast_horizon_hours,
        "target_evaluation_at": _iso(row.target_evaluation_at),
        "outcome_status": row.outcome_status,
        "outcome_price": row.outcome_price,
        "outcome_pct": row.outcome_pct,
        "outcome_reason": row.outcome_reason,
        "created_at": _iso(row.created_at),
    } for row in signal_rows]

    test_account = WebullTestAccount.query.filter_by(user_id=user_id).first()
    test_positions = WebullTestPosition.query.filter_by(user_id=user_id).order_by(
        WebullTestPosition.id.asc()
    ).all()
    test_order_rows, test_order_window = _window(
        WebullTestOrder.query.filter_by(user_id=user_id), WebullTestOrder.created_at, WEBULL_ORDER_CONTEXT_LIMIT
    )
    test_orders = [{
        "id": row.id,
        "order_id": row.order_id,
        "symbol": row.symbol,
        "instrument_type": row.instrument_type,
        "side": row.side,
        "order_type": row.order_type,
        "quantity": row.quantity,
        "limit_price": row.limit_price,
        "stop_price": row.stop_price,
        "filled_price": row.filled_price,
        "filled_quantity": row.filled_quantity,
        "status": row.status,
        "combo_type": row.combo_type,
        "combo_orders": _json_value(row.combo_orders, []),
        "time_in_force": row.time_in_force,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    } for row in test_order_rows]

    snapshot = {
        "mode_separation": {
            "REAL": "Provider-backed Webull accounts, positions and orders.",
            "TEST": "Locally simulated Webull test account, positions and orders.",
            "QUANT": "Administrator-only, isolated paper strategy ledger; supplied separately when authorized.",
        },
        "real_mode": {
            "connection_environment": getattr(settings, "webull_environment", None) if settings else None,
            "account_selection_mode": getattr(settings, "webull_account_selection_mode", None) if settings else None,
            "accounts": real_accounts,
            "holdings": real_holdings,
            "watchlist": real_watchlist,
            "orders": real_orders,
            "order_window": real_order_window,
            "ai_signals": real_signals,
            "ai_signal_window": signal_window,
        },
        "test_mode": {
            "enabled": bool(getattr(settings, "webull_test_mode_enabled", False)) if settings else False,
            "account": {
                "cash_balance": test_account.cash_balance,
                "currency": test_account.currency,
                "created_at": _iso(test_account.created_at),
                "updated_at": _iso(test_account.updated_at),
            } if test_account else None,
            "positions": [{
                "id": row.id,
                "symbol": row.symbol,
                "instrument_type": row.instrument_type,
                "side": row.side,
                "quantity": row.quantity,
                "cost_price": row.cost_price,
                "last_price": row.last_price,
                "market_value": row.market_value,
                "unrealized_pnl": row.unrealized_pnl,
                "contract_multiplier": row.contract_multiplier,
                "underlying_symbol": row.underlying_symbol,
                "option_type": row.option_type,
                "option_strike": row.option_strike,
                "option_expiration": row.option_expiration,
                "event_outcome": row.event_outcome,
                "updated_at": _iso(row.updated_at),
            } for row in test_positions],
            "orders": test_orders,
            "order_window": test_order_window,
        },
    }
    return _redact_secrets(snapshot)


def _portfolio_config_dict(cfg, account, state):
    from services import portfolio_engine as engine

    return {
        "id": cfg.id,
        "name": cfg.name,
        "mode": cfg.mode,
        "enabled": bool(cfg.enabled),
        "worker_status": cfg.worker_status,
        "total_bankroll": cfg.total_bankroll,
        "target_annual_return": cfg.target_annual_return,
        "allocations": engine.allocations_for(cfg),
        "allocation_weights": engine.loads(cfg.allocations_json, {}),
        "watchlists": engine.loads(cfg.watchlists_json, {}),
        "module_settings": engine.settings_for(cfg),
        "master_ai_prompt": cfg.master_ai_prompt,
        "master_ai_config": _redact_secrets(engine.loads(cfg.master_ai_config, {})),
        "created_at": _iso(cfg.created_at),
        "updated_at": _iso(cfg.updated_at),
        "account": {
            "initial_balance": account.initial_balance,
            "cash_balance": account.cash_balance,
            "total_equity": account.total_equity,
            "currency": account.currency,
            "reset_at": _iso(account.reset_at),
            "updated_at": _iso(account.updated_at),
        } if account else None,
        "engine_state": {
            "generation": state.generation,
            "kill_switch": bool(state.kill_switch),
            "pause_reason": state.pause_reason,
            "heartbeat_at": _iso(state.heartbeat_at),
            "last_scan_at": _iso(state.last_scan_at),
            "last_audit_at": _iso(state.last_audit_at),
            "telemetry": _json_value(state.telemetry_json, {}),
        } if state else None,
    }


def build_admin_quant_copilot_snapshot(user_id, user):
    """Return administrator-only multi-asset and Event engine evidence.

    Window sizes match or exceed the Settings viewers. Counts and truncation
    flags prevent claims that an older record was inspected when it was outside
    the supplied request context.
    """
    from event_algo import (
        config_to_dict,
        event_strategy_health_summary,
        event_strategy_logs,
        is_event_strategy_admin,
        list_event_strategy_reports,
        report_to_dict,
    )

    if not is_event_strategy_admin(user):
        return None

    from event_algo_models import EventStrategyConfig, EventStrategyLog, EventStrategyReport
    from portfolio_algo_models import (
        PortfolioAudit,
        PortfolioEngineLog,
        PortfolioEngineState,
        PortfolioStrategyAccount,
        PortfolioStrategyConfig,
        PortfolioStrategyOrder,
    )
    from services import portfolio_engine as engine

    cfg = PortfolioStrategyConfig.query.filter_by(user_id=user_id).order_by(
        PortfolioStrategyConfig.id.asc()
    ).first()
    account = PortfolioStrategyAccount.query.filter_by(user_id=user_id).first()
    state = db.session.get(PortfolioEngineState, user_id)

    portfolio_section = {"configured": bool(cfg)}
    if cfg:
        portfolio_section["settings"] = _portfolio_config_dict(cfg, account, state)
        try:
            if not account or not state:
                raise RuntimeError("Quantitative account or engine state is not initialized.")
            status = engine.portfolio_status(user_id)
            curve = status.get("equity_curve") or []
            if len(curve) > 250:
                status["equity_curve"] = curve[-250:]
                status["equity_curve_window"] = {
                    "total_records": len(curve),
                    "records_in_context": 250,
                    "window_truncated": True,
                }
            portfolio_section["current_status"] = status
        except Exception as exc:
            portfolio_section["current_status"] = {"unavailable": str(exc)[:500]}

        order_rows, order_window = _window(
            PortfolioStrategyOrder.query.filter_by(user_id=user_id),
            PortfolioStrategyOrder.created_at,
            WEBULL_ORDER_CONTEXT_LIMIT,
        )
        portfolio_section["orders"] = [{
            "id": row.id,
            "module_name": row.module_name,
            "symbol": row.symbol,
            "instrument_type": row.instrument_type,
            "side": row.side,
            "order_type": row.order_type,
            "quantity": row.quantity,
            "price": row.price,
            "status": row.status,
            "pnl": row.pnl,
            "notes": _json_value(row.notes, row.notes),
            "created_at": _iso(row.created_at),
        } for row in order_rows]
        portfolio_section["order_window"] = order_window

        log_rows, log_window = _window(
            PortfolioEngineLog.query.filter_by(user_id=user_id),
            PortfolioEngineLog.created_at,
            QUANT_LOG_CONTEXT_LIMIT,
        )
        portfolio_section["logs"] = [{
            "id": row.id,
            "created_at": _iso(row.created_at),
            "level": row.level,
            "event_type": row.event_type,
            "message": row.message,
            "details": _json_value(row.details_json, row.details_json),
        } for row in log_rows]
        portfolio_section["log_window"] = log_window

        audit_rows, audit_window = _window(
            PortfolioAudit.query.filter_by(user_id=user_id),
            PortfolioAudit.created_at,
            QUANT_REPORT_CONTEXT_LIMIT,
        )
        portfolio_section["reports"] = [engine.audit_dict(row) for row in audit_rows]
        portfolio_section["report_window"] = audit_window

    event_cfg = EventStrategyConfig.query.filter_by(user_id=user_id).order_by(EventStrategyConfig.id.asc()).first()
    event_section = {"configured": bool(event_cfg)}
    if event_cfg:
        event_section["settings"] = config_to_dict(event_cfg)
        try:
            event_section["health"] = event_strategy_health_summary(user_id)
        except Exception as exc:
            event_section["health"] = {"unavailable": str(exc)[:500]}
        event_section["logs"] = event_strategy_logs(user_id, limit=QUANT_LOG_CONTEXT_LIMIT)
        event_log_count = EventStrategyLog.query.filter_by(user_id=user_id).count()
        event_section["log_window"] = {
            "total_records": event_log_count,
            "records_in_context": len(event_section["logs"]),
            "newest_first": True,
            "window_truncated": event_log_count > len(event_section["logs"]),
        }
        reports = list_event_strategy_reports(user_id, limit=QUANT_REPORT_CONTEXT_LIMIT)
        event_section["reports"] = [report_to_dict(row) for row in reports]
        event_report_count = EventStrategyReport.query.filter_by(user_id=user_id).count()
        event_section["report_window"] = {
            "total_records": event_report_count,
            "records_in_context": len(reports),
            "newest_first": True,
            "window_truncated": event_report_count > len(reports),
        }

    return _redact_secrets({
        "authorization": "ADMINISTRATOR-ONLY CONTEXT",
        "security": "Secrets and credential values are deliberately redacted; operational settings remain visible.",
        "quantitative_portfolio_engine": portfolio_section,
        "event_contract_strategy_engine": event_section,
    })


def copilot_context_json(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
