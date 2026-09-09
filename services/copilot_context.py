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
QUANT_LOG_CONTEXT_LIMIT = 100
QUANT_REPORT_CATALOG_LIMIT = 200
QUANT_RECORD_BUDGET_CHARS = 40_000
QUANT_REPORT_BUDGET_CHARS = 60_000

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
    "- When administrator-only quantitative context is present, use its complete operational settings and current "
    "state plus the supplied request-matched ledger, log, and report evidence. The report catalogs and archive counts "
    "cover historical availability; only detailed records in the current request were inspected. Cite record IDs and "
    "timestamps where useful, honor all retrieval/truncation metadata, and distinguish recorded evidence from "
    "recommendations. If the section is absent, do not infer or disclose quantitative-engine data.\n"
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
    "labeled ADMINISTRATOR-ONLY context. Its absence means access was not authorized. A catalog entry proves that a "
    "record exists but is not its full content. Honor archive-search, record-window, and field-truncation metadata, "
    "and do not claim to have inspected detail that was not supplied.\n"
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


def _serialize_with_budget(rows, serializer, max_chars):
    """Serialize whole newest records until the explicit prompt budget is full."""
    result = []
    used = 2
    for row in rows:
        item = serializer(row)
        item_size = len(json.dumps(item, default=str, separators=(",", ":"))) + 1
        if not result and item_size > max_chars:
            rendered = json.dumps(item, default=str, separators=(",", ":"))
            result.append({
                "record_detail_truncated": True,
                "original_serialized_chars": len(rendered),
                "serialized_record_preview": rendered[:max(1_000, max_chars - 500)],
            })
            break
        if result and used + item_size > max_chars:
            break
        result.append(item)
        used += item_size
    return result


_QUANT_CONTEXT_WORDS = {
    "algorithm", "allocation", "audit", "cio", "configuration", "engine", "event contract",
    "log", "module", "paper", "portfolio", "quant", "quantitative", "report", "settings",
    "strategy", "telemetry", "worker",
}
_LOG_SEARCH_STOPWORDS = {
    "about", "after", "allocation", "audit", "before", "configuration", "could", "engine",
    "explain", "from", "have", "latest", "log", "logs", "paper", "please", "portfolio",
    "quant", "quantitative", "report", "reports", "settings", "show", "strategy", "that",
    "these", "this", "what", "when", "where", "which", "with", "would",
}


def _quant_context_requested(message):
    text = str(message or "").casefold()
    return any(term in text for term in _QUANT_CONTEXT_WORDS)


def _log_search_terms(message):
    return list(dict.fromkeys(
        word.casefold()
        for word in re.findall(r"[A-Za-z0-9_.-]{4,}", str(message or ""))
        if word.casefold() not in _LOG_SEARCH_STOPWORDS
    ))[:6]


def _requested_record_ids(message, labels):
    label_pattern = "|".join(re.escape(label) for label in labels)
    return [int(value) for value in re.findall(
        rf"(?:{label_pattern})\s*(?:id\s*)?#?\s*(\d+)",
        str(message or ""),
        flags=re.IGNORECASE,
    )][:5]


def _window_metadata(total, supplied, *, searched=False, matched=0):
    metadata = {
        "total_records": total,
        "records_in_context": supplied,
        "newest_first": True,
        "window_truncated": total > supplied,
    }
    if searched:
        metadata.update({
            "archive_search_performed": True,
            "archive_matches_in_context": matched,
            "archive_scope": "All records for this administrator were eligible for exact-ID and text matching.",
        })
    return metadata


def _unique_rows(*groups):
    result = []
    seen = set()
    for group in groups:
        for row in group:
            identity = (type(row), row.id)
            if identity not in seen:
                seen.add(identity)
                result.append(row)
    return result


def _archive_matches(query, model, order_column, message, text_columns, labels, limit=100):
    """Search the user's complete scoped archive without loading it into memory."""
    from sqlalchemy import or_

    record_ids = _requested_record_ids(message, labels)
    id_rows = (
        query.filter(model.id.in_(record_ids)).order_by(order_column.desc()).all()
        if record_ids else []
    )
    conditions = []
    for term in _log_search_terms(message):
        pattern = f"%{term}%"
        conditions.extend(column.ilike(pattern) for column in text_columns)
    normalized = str(message or "").casefold()
    if "error" in normalized or "failed" in normalized or "failure" in normalized:
        if hasattr(model, "level"):
            conditions.append(model.level.ilike("ERROR"))
        elif hasattr(model, "status"):
            conditions.append(model.status.ilike("%fail%"))
    if "warn" in normalized and hasattr(model, "level"):
        conditions.append(model.level.ilike("WARNING"))
    text_rows = (
        query.filter(or_(*conditions)).order_by(order_column.desc()).limit(limit).all()
        if conditions else []
    )
    return _unique_rows(id_rows, text_rows)


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


def build_admin_quant_copilot_snapshot(user_id, user, message=None):
    """Return administrator-only multi-asset and Event engine evidence.

    Complete settings and report catalogs are always present. Detailed current
    state, ledgers, logs, and full report records expand when the user's request
    concerns the quantitative engines. Exact IDs and meaningful request terms
    are matched against the complete user-scoped archives in the database.
    """
    from event_algo import (
        config_to_dict,
        event_strategy_health_summary,
        is_event_strategy_admin,
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

    detail_requested = _quant_context_requested(message)
    cfg = PortfolioStrategyConfig.query.filter_by(user_id=user_id).order_by(
        PortfolioStrategyConfig.id.asc()
    ).first()
    account = PortfolioStrategyAccount.query.filter_by(user_id=user_id).first()
    state = db.session.get(PortfolioEngineState, user_id)

    portfolio_section = {
        "configured": bool(cfg),
        "detail_retrieval_active": detail_requested,
    }
    if cfg:
        portfolio_section["settings"] = _portfolio_config_dict(cfg, account, state)
        log_query = PortfolioEngineLog.query.filter_by(user_id=user_id)
        audit_query = PortfolioAudit.query.filter_by(user_id=user_id)
        log_total = log_query.count()
        audit_total = audit_query.count()
        audit_catalog_rows = audit_query.order_by(PortfolioAudit.created_at.desc()).limit(
            QUANT_REPORT_CATALOG_LIMIT
        ).all()
        portfolio_section["report_catalog"] = [{
            "id": row.id,
            "generation": row.generation,
            "created_at": _iso(row.created_at),
            "status": row.status,
            "provider": row.provider,
            "model": row.model,
            "content_chars": len(row.content or ""),
            "evidence_chars": len(row.evidence_json or ""),
        } for row in audit_catalog_rows]
        portfolio_section["report_catalog_window"] = _window_metadata(
            audit_total, len(audit_catalog_rows)
        )
        portfolio_section["log_archive"] = {
            "total_records": log_total,
            "detail_loaded_for_this_request": detail_requested,
            "retrieval": "Newest records plus archive-wide exact-ID/text matches are supplied for quantitative requests.",
        }

        if detail_requested:
            try:
                if not account or not state:
                    raise RuntimeError("Quantitative account or engine state is not initialized.")
                status = engine.portfolio_status(user_id)
                curve = status.get("equity_curve") or []
                status["equity_curve"] = curve[-20:]
                status["equity_curve_window"] = _window_metadata(len(curve), min(len(curve), 20))
                portfolio_section["current_status"] = status
            except Exception as exc:
                portfolio_section["current_status"] = {"unavailable": str(exc)[:500]}

            def portfolio_order_dict(row):
                return {
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
                }

            order_rows, order_window = _window(
                PortfolioStrategyOrder.query.filter_by(user_id=user_id),
                PortfolioStrategyOrder.created_at,
                WEBULL_ORDER_CONTEXT_LIMIT,
            )
            orders = _serialize_with_budget(
                order_rows, portfolio_order_dict, QUANT_RECORD_BUDGET_CHARS
            )
            order_window["records_in_context"] = len(orders)
            order_window["window_truncated"] = order_window["total_records"] > len(orders)
            portfolio_section["orders"] = orders
            portfolio_section["order_window"] = order_window

            def portfolio_log_dict(row):
                return {
                    "id": row.id,
                    "created_at": _iso(row.created_at),
                    "level": row.level,
                    "event_type": row.event_type,
                    "message": row.message,
                    "details": _json_value(row.details_json, row.details_json),
                }

            recent_logs = log_query.order_by(PortfolioEngineLog.created_at.desc()).limit(
                QUANT_LOG_CONTEXT_LIMIT
            ).all()
            matching_logs = _archive_matches(
                log_query,
                PortfolioEngineLog,
                PortfolioEngineLog.created_at,
                message,
                (PortfolioEngineLog.event_type, PortfolioEngineLog.message, PortfolioEngineLog.details_json),
                ("portfolio log", "quant log", "log"),
            )
            recent_log_records = _serialize_with_budget(
                recent_logs, portfolio_log_dict, QUANT_RECORD_BUDGET_CHARS
            )
            archive_log_records = _serialize_with_budget(
                [row for row in matching_logs if row not in recent_logs],
                portfolio_log_dict,
                QUANT_RECORD_BUDGET_CHARS,
            )
            portfolio_section["logs"] = recent_log_records
            portfolio_section["archive_log_matches"] = archive_log_records
            portfolio_section["log_window"] = _window_metadata(
                log_total,
                len(recent_log_records) + len(archive_log_records),
                searched=True,
                matched=len(archive_log_records),
            )

            latest_audits = audit_query.order_by(PortfolioAudit.created_at.desc()).limit(1).all()
            matching_audits = _archive_matches(
                audit_query,
                PortfolioAudit,
                PortfolioAudit.created_at,
                message,
                (PortfolioAudit.status, PortfolioAudit.content, PortfolioAudit.evidence_json),
                ("portfolio audit", "quant report", "audit", "report"),
                limit=5,
            )
            selected_audits = _unique_rows(matching_audits, latest_audits)
            audit_records = _serialize_with_budget(
                selected_audits, engine.audit_dict, QUANT_REPORT_BUDGET_CHARS
            )
            portfolio_section["reports"] = audit_records
            portfolio_section["report_retrieval"] = {
                "total_records": audit_total,
                "detailed_records_in_context": len(audit_records),
                "archive_search_performed": True,
                "selection": "Exact-ID/text matches from the full archive, then the latest report as fallback.",
                "field_or_record_truncation_is_explicit": True,
            }

    event_cfg = EventStrategyConfig.query.filter_by(user_id=user_id).order_by(EventStrategyConfig.id.asc()).first()
    event_section = {
        "configured": bool(event_cfg),
        "detail_retrieval_active": detail_requested,
    }
    if event_cfg:
        event_section["settings"] = config_to_dict(event_cfg)
        event_log_query = EventStrategyLog.query.filter_by(user_id=user_id)
        event_report_query = EventStrategyReport.query.filter_by(user_id=user_id)
        event_log_total = event_log_query.count()
        event_report_total = event_report_query.count()
        event_catalog_rows = event_report_query.order_by(EventStrategyReport.created_at.desc()).limit(
            QUANT_REPORT_CATALOG_LIMIT
        ).all()
        event_section["report_catalog"] = [{
            "id": row.id,
            "created_at": _iso(row.created_at),
            "period_start": _iso(row.period_start),
            "period_end": _iso(row.period_end),
            "status": row.status,
            "headline": row.headline,
            "summary": (row.summary or "")[:500],
            "provider": row.provider,
            "model": row.model,
            "content_chars": len(row.content_markdown or ""),
            "metrics_chars": len(row.metrics_json or ""),
        } for row in event_catalog_rows]
        event_section["report_catalog_window"] = _window_metadata(
            event_report_total, len(event_catalog_rows)
        )
        event_section["log_archive"] = {
            "total_records": event_log_total,
            "detail_loaded_for_this_request": detail_requested,
            "retrieval": "Newest records plus archive-wide exact-ID/text matches are supplied for quantitative requests.",
        }

        if detail_requested:
            try:
                event_section["health"] = event_strategy_health_summary(user_id)
            except Exception as exc:
                event_section["health"] = {"unavailable": str(exc)[:500]}

            def event_log_dict(row):
                return {
                    "id": row.id,
                    "created_at": _iso(row.created_at),
                    "level": row.level,
                    "event_type": row.event_type,
                    "message": row.message,
                    "symbol": row.symbol,
                    "duration": row.duration,
                    "run_id": row.run_id,
                    "metadata": _json_value(row.metadata_json, {}),
                }

            recent_event_logs = event_log_query.order_by(EventStrategyLog.created_at.desc()).limit(
                QUANT_LOG_CONTEXT_LIMIT
            ).all()
            matching_event_logs = _archive_matches(
                event_log_query,
                EventStrategyLog,
                EventStrategyLog.created_at,
                message,
                (EventStrategyLog.event_type, EventStrategyLog.message, EventStrategyLog.metadata_json),
                ("event log", "strategy log", "log"),
            )
            recent_event_records = _serialize_with_budget(
                recent_event_logs, event_log_dict, QUANT_RECORD_BUDGET_CHARS
            )
            archive_event_records = _serialize_with_budget(
                [row for row in matching_event_logs if row not in recent_event_logs],
                event_log_dict,
                QUANT_RECORD_BUDGET_CHARS,
            )
            event_section["logs"] = recent_event_records
            event_section["archive_log_matches"] = archive_event_records
            event_section["log_window"] = _window_metadata(
                event_log_total,
                len(recent_event_records) + len(archive_event_records),
                searched=True,
                matched=len(archive_event_records),
            )

            latest_event_reports = event_report_query.order_by(EventStrategyReport.created_at.desc()).limit(1).all()
            matching_event_reports = _archive_matches(
                event_report_query,
                EventStrategyReport,
                EventStrategyReport.created_at,
                message,
                (EventStrategyReport.status, EventStrategyReport.headline, EventStrategyReport.summary,
                 EventStrategyReport.content_markdown, EventStrategyReport.metrics_json),
                ("event report", "event audit", "audit", "report"),
                limit=5,
            )
            selected_event_reports = _unique_rows(matching_event_reports, latest_event_reports)
            event_report_records = _serialize_with_budget(
                selected_event_reports, report_to_dict, QUANT_REPORT_BUDGET_CHARS
            )
            event_section["reports"] = event_report_records
            event_section["report_retrieval"] = {
                "total_records": event_report_total,
                "detailed_records_in_context": len(event_report_records),
                "archive_search_performed": True,
                "selection": "Exact-ID/text matches from the full archive, then the latest report as fallback.",
                "field_or_record_truncation_is_explicit": True,
            }

    return _redact_secrets({
        "authorization": "ADMINISTRATOR-ONLY CONTEXT",
        "security": "Secrets and credential values are deliberately redacted; operational settings remain visible.",
        "retrieval_scope": {
            "detail_requested": detail_requested,
            "complete_settings": True,
            "complete_archive_access": "All log/report records are searchable by the current question; report catalogs and total counts expose history without injecting every large record.",
            "evidence_rule": "Only detailed records supplied in this request may be described as inspected.",
        },
        "quantitative_portfolio_engine": portfolio_section,
        "event_contract_strategy_engine": event_section,
    })


def copilot_context_json(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
