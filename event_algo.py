"""Paper-first Webull Event Contract strategy engine.

This module intentionally contains no live-order call.  It normalizes current
Webull Event Contract quotes, records an auditable decision trace, and exposes
the risk/edge calculations that a future execution adapter can consume after
forward-paper evidence is sufficient.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

from log import logger
from core.extensions import db
from credentials import Credential, UserSetting
from event_algo_models import (
    EventContractOutcome,
    EventMarketSnapshot,
    EventStrategyConfig,
    EventStrategyDecision,
    EventStrategyOrder,
    EventStrategyRun,
)


PAPER_MODE = "PAPER"
ENGINE_VERSION = "1.1.0"
MODEL_VERSION = "empirical-v1"
DEFAULT_RISK_CONFIG = {
    "max_dollars_per_trade": 10.0,
    "max_open_dollars": 30.0,
    "max_open_positions": 3,
    "max_hourly_loss": 15.0,
    "max_daily_loss": 25.0,
    "max_drawdown": 35.0,
    "max_contracts_per_trade": 50,
    "max_spread": 0.15,
    "min_volume": 1,
    "min_time_remaining_seconds": 60,
    "max_time_remaining_seconds": 86400,
}
DEFAULT_SIGNAL_CONFIG = {
    "min_net_edge": 0.03,
    "min_confidence": 0.55,
    "fee_per_contract": 0.02,
    "uncertainty_buffer": 0.01,
    "scan_interval_seconds": 60,
    "signals_only": True,
}
ALLOWED_DURATIONS = {
    "FIFTEEN_MINUTES", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL", "ONE_OFF", "CUSTOM",
}

NO_TRADE_REASONS = {
    "MODEL_UNAVAILABLE",
    "MARKET_NOT_OPEN",
    "MARKET_STATUS_UNKNOWN",
    "CONTRACT_EXPIRED",
    "STALE_QUOTE",
    "MISSING_QUOTE",
    "SPREAD_TOO_WIDE",
    "INSUFFICIENT_LIQUIDITY",
    "TOO_CLOSE_TO_EXPIRATION",
    "TOO_FAR_FROM_EXPIRATION",
    "CONFIDENCE_TOO_LOW",
    "EDGE_TOO_SMALL_AFTER_FEES",
    "PAPER_SIGNALS_ONLY",
    "KILL_SWITCH",
    "RISK_LIMIT",
    "DATA_ERROR",
}

_ACTIVE_SCAN_USERS = set()
_ACTIVE_SCAN_LOCK = threading.Lock()


def _json_load(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_dump(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _number(value, default=None):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _clamp(value, lower=0.0, upper=1.0):
    parsed = _number(value)
    if parsed is None:
        return None
    return max(lower, min(upper, parsed))


def _utc_naive(value):
    """Parse provider timestamps and store them as UTC-naive DB values."""
    if value in (None, ""):
        return None
    numeric = _number(value)
    if numeric is not None:
        try:
            if numeric > 100_000_000_000:
                numeric /= 1000
            return datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _market_cutoff(market):
    for key in (
        "contract_period_end", "cutoff_at", "cutoff_time", "last_trading_date",
        "expected_exp_date", "latest_exp_date", "expiration", "expiration_time",
    ):
        value = _utc_naive(market.get(key))
        if value:
            return value
    return None


def _market_provider_timestamp(market):
    for key in ("quote_as_of", "timestamp", "last_trade_time", "trade_time", "updated_at"):
        value = _utc_naive(market.get(key))
        if value:
            return value
    return None


_DURATION_LABELS = {
    "FIFTEEN_MINUTES": "15-minute",
    "15M": "15-minute",
    "HOURLY": "hourly",
    "1H": "hourly",
    "DAILY": "daily",
    "1D": "daily",
    "WEEKLY": "weekly",
    "MONTHLY": "monthly",
    "ANNUAL": "annual",
    "ONE_OFF": "one-off",
    "CUSTOM": "custom",
}


def _market_iso(value):
    parsed = _utc_naive(value)
    return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if parsed else None


def _market_duration_label(market):
    minutes = _number(market.get("contract_period_minutes"))
    if minutes is not None and minutes > 0:
        if minutes <= 15:
            return "15-minute"
        if minutes <= 60:
            return "hourly"
        if minutes <= 1440:
            return "daily"
        if minutes <= 10080:
            return "weekly"
    frequency = str(market.get("series_frequency") or market.get("duration") or "").strip().upper()
    if frequency in _DURATION_LABELS:
        return _DURATION_LABELS[frequency]
    match = re.search(r"(?:^|[^0-9])(?:KX)?[A-Z]+(15M|1H|1D)(?:[^A-Z0-9]|$)", str(market.get("symbol") or "").upper())
    return _DURATION_LABELS.get(match.group(1), "Unknown duration") if match else "Unknown duration"


def contract_details(market):
    """Return provider-backed, human-readable details without inventing facts."""
    market = market if isinstance(market, dict) else {}
    text_keys = ("question", "contract_question", "description", "event_name", "series_name", "name", "display_condition", "yes_condition")
    question = next((str(market.get(key)).strip() for key in text_keys if market.get(key) not in (None, "") and str(market.get(key)).strip()), None)
    cutoff = _market_cutoff(market)
    details = {
        "contract_symbol": str(market.get("symbol") or "").upper() or None,
        "underlying_symbol": str(market.get("underlying_symbol") or "").upper() or None,
        "duration_label": _market_duration_label(market),
        "question": question or str(market.get("symbol") or "").upper() or "Unknown Event Contract",
        "condition": str(market.get("display_condition") or market.get("yes_condition") or "").strip() or None,
        "category": str(market.get("category_code") or "").strip() or None,
        "series_symbol": str(market.get("series_symbol") or "").upper() or None,
        "open_at": _market_iso(market.get("contract_period_start") or market.get("open_date")),
        "cutoff_at": _market_iso(cutoff),
        "payout_at": _market_iso(market.get("payout_date")),
        "reference_price": _number(market.get("reference_price")),
        "target_value": _number(market.get("target_value")),
    }
    return details


def _market_features(market, now=None):
    now = now or datetime.utcnow()
    yes_bid = _number(market.get("yes_bid"))
    yes_ask = _number(market.get("yes_ask"))
    no_bid = _number(market.get("no_bid"))
    no_ask = _number(market.get("no_ask"))
    cutoff = _market_cutoff(market)
    time_remaining = max(0.0, (cutoff - now).total_seconds()) if cutoff else None
    underlying = _number(market.get("underlying_price"))
    reference = _number(market.get("reference_price", market.get("target_value")))
    return {
        "yes_mid": round((yes_bid + yes_ask) / 2, 6) if yes_bid is not None and yes_ask is not None else None,
        "no_mid": round((no_bid + no_ask) / 2, 6) if no_bid is not None and no_ask is not None else None,
        "spread_yes": round(max(0.0, yes_ask - yes_bid), 6) if yes_bid is not None and yes_ask is not None else None,
        "spread_no": round(max(0.0, no_ask - no_bid), 6) if no_bid is not None and no_ask is not None else None,
        "time_remaining_seconds": time_remaining,
        "underlying_price": underlying,
        "reference_price": reference,
        "distance_to_reference": round(underlying - reference, 8) if underlying is not None and reference is not None else None,
        "volume": _number(market.get("volume"), 0.0),
        "open_interest": _number(market.get("open_interest"), 0.0),
        "contract_details": contract_details(market),
    }


def default_config_for_user(user_id):
    return {
        "user_id": int(user_id),
        "name": "Bitcoin Event Paper Research",
        "enabled": False,
        "mode": PAPER_MODE,
        "worker_status": "STOPPED",
        "strategy_version": ENGINE_VERSION,
        "model_version": MODEL_VERSION,
        "symbols": ["BTC", "ETH"],
        "durations": ["FIFTEEN_MINUTES", "HOURLY"],
        "risk_config": dict(DEFAULT_RISK_CONFIG),
        "signal_config": dict(DEFAULT_SIGNAL_CONFIG),
        "kill_switch": False,
    }


def normalize_config_payload(payload, *, user_id):
    """Normalize user-editable settings while enforcing paper-only operation."""
    payload = payload if isinstance(payload, dict) else {}
    result = default_config_for_user(user_id)
    result["name"] = str(payload.get("name") or result["name"]).strip()[:120]
    symbols = payload.get("symbols", result["symbols"])
    if isinstance(symbols, str):
        symbols = [item.strip() for item in symbols.split(",")]
    result["symbols"] = list(dict.fromkeys(
        str(item).strip().upper() for item in (symbols or [])
        if str(item).strip() and len(str(item).strip()) <= 20
    ))[:10] or result["symbols"]
    durations = payload.get("durations", result["durations"])
    if isinstance(durations, str):
        durations = [item.strip().upper() for item in durations.split(",")]
    result["durations"] = list(dict.fromkeys(
        str(item).strip().upper() for item in (durations or [])
        if str(item).strip().upper() in ALLOWED_DURATIONS
    ))[:8] or result["durations"]
    result["enabled"] = bool(payload.get("enabled", False))
    result["kill_switch"] = bool(payload.get("kill_switch", False))
    risk = dict(DEFAULT_RISK_CONFIG)
    risk.update(payload.get("risk_config") if isinstance(payload.get("risk_config"), dict) else {})
    for key in DEFAULT_RISK_CONFIG:
        parsed = _number(risk.get(key))
        if parsed is not None:
            risk[key] = max(0.0, parsed)
    signal = dict(DEFAULT_SIGNAL_CONFIG)
    signal.update(payload.get("signal_config") if isinstance(payload.get("signal_config"), dict) else {})
    for key in ("min_net_edge", "min_confidence", "fee_per_contract", "uncertainty_buffer"):
        parsed = _number(signal.get(key))
        if parsed is not None:
            signal[key] = max(0.0, min(1.0, parsed))
    signal["scan_interval_seconds"] = int(max(30, min(3600, _number(signal.get("scan_interval_seconds"), 60))))
    # This flag is intentionally forced on until a future release has passed
    # the forward-paper acceptance gates and receives an explicit live review.
    signal["signals_only"] = True
    result["risk_config"] = risk
    result["signal_config"] = signal
    result["enabled"] = bool(result["enabled"] and not result["kill_switch"])
    return result


def config_to_dict(config):
    return {
        "id": config.id,
        "user_id": config.user_id,
        "name": config.name,
        "enabled": bool(config.enabled),
        "mode": PAPER_MODE,
        "worker_status": config.worker_status or "STOPPED",
        "strategy_version": config.strategy_version or ENGINE_VERSION,
        "model_version": config.model_version or MODEL_VERSION,
        "symbols": _json_load(config.symbols, []),
        "durations": _json_load(config.durations, []),
        "risk_config": _json_load(config.risk_config, {}),
        "signal_config": _json_load(config.signal_config, {}),
        "kill_switch": bool(config.kill_switch),
        "last_run_at": config.last_run_at.isoformat() if config.last_run_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def get_or_create_config(user_id):
    config = EventStrategyConfig.query.filter_by(user_id=user_id).order_by(EventStrategyConfig.id.asc()).first()
    if config:
        if config.strategy_version != ENGINE_VERSION:
            config.strategy_version = ENGINE_VERSION
        return config
    defaults = default_config_for_user(user_id)
    config = EventStrategyConfig(
        user_id=user_id,
        name=defaults["name"],
        enabled=False,
        mode=PAPER_MODE,
        worker_status="STOPPED",
        strategy_version=ENGINE_VERSION,
        model_version=MODEL_VERSION,
        symbols=_json_dump(defaults["symbols"]),
        durations=_json_dump(defaults["durations"]),
        risk_config=_json_dump(defaults["risk_config"]),
        signal_config=_json_dump(defaults["signal_config"]),
        kill_switch=False,
    )
    db.session.add(config)
    db.session.flush()
    return config


def update_config(config, payload):
    normalized = normalize_config_payload(payload, user_id=config.user_id)
    config.name = normalized["name"]
    config.enabled = normalized["enabled"]
    config.mode = PAPER_MODE
    config.worker_status = "RUNNING" if config.enabled else "STOPPED"
    config.strategy_version = ENGINE_VERSION
    config.model_version = MODEL_VERSION
    config.symbols = _json_dump(normalized["symbols"])
    config.durations = _json_dump(normalized["durations"])
    config.risk_config = _json_dump(normalized["risk_config"])
    config.signal_config = _json_dump(normalized["signal_config"])
    config.kill_switch = normalized["kill_switch"]
    if config.kill_switch:
        config.enabled = False
        config.worker_status = "KILLED"
    return config


def evaluate_market(market, config, *, now=None):
    """Return one deterministic decision without submitting an order."""
    now = now or datetime.utcnow()
    risk = _json_load(config.risk_config, dict(DEFAULT_RISK_CONFIG))
    signal = _json_load(config.signal_config, dict(DEFAULT_SIGNAL_CONFIG))
    features = _market_features(market, now)
    reasons = []
    status = str(market.get("tradable_status") or "").strip().upper()
    if status == "CO":
        reasons.append("MARKET_NOT_OPEN")
    elif status not in {"OC", ""}:
        reasons.append("MARKET_STATUS_UNKNOWN")
    if config.kill_switch:
        reasons.append("KILL_SWITCH")

    remaining = features.get("time_remaining_seconds")
    if remaining is not None:
        if remaining <= 0:
            reasons.append("CONTRACT_EXPIRED")
        elif remaining < float(risk.get("min_time_remaining_seconds", 60)):
            reasons.append("TOO_CLOSE_TO_EXPIRATION")
        elif remaining > float(risk.get("max_time_remaining_seconds", 86400)):
            reasons.append("TOO_FAR_FROM_EXPIRATION")

    provider_time = _market_provider_timestamp(market)
    if provider_time and (now - provider_time).total_seconds() > 30:
        reasons.append("STALE_QUOTE")
    yes_ask = _number(market.get("yes_ask"))
    no_ask = _number(market.get("no_ask"))
    yes_bid = _number(market.get("yes_bid"))
    no_bid = _number(market.get("no_bid"))
    if yes_ask is None and no_ask is None:
        reasons.append("MISSING_QUOTE")
    for quote in (yes_ask, no_ask):
        if quote is not None and not 0 < quote < 1:
            reasons.append("MISSING_QUOTE")
    max_spread = float(risk.get("max_spread", 0.15))
    spreads = [item for item in (features.get("spread_yes"), features.get("spread_no")) if item is not None]
    if spreads and min(spreads) > max_spread:
        reasons.append("SPREAD_TOO_WIDE")
    volume = float(features.get("volume") or 0.0)
    if volume < float(risk.get("min_volume", 1)):
        reasons.append("INSUFFICIENT_LIQUIDITY")

    # No probability is invented from the market price.  A prediction must be
    # supplied by a calibrated model once enough resolved observations exist.
    probability_yes = _clamp(
        market.get("model_probability_yes", market.get("probability_yes")),
    )
    confidence = _clamp(market.get("model_confidence", market.get("confidence")))
    if probability_yes is None:
        reasons.append("MODEL_UNAVAILABLE")
    probability_no = round(1.0 - probability_yes, 6) if probability_yes is not None else None

    fee = float(signal.get("fee_per_contract", 0.02))
    uncertainty = float(signal.get("uncertainty_buffer", 0.01))
    candidates = []
    if probability_yes is not None and yes_ask is not None:
        gross = probability_yes - yes_ask
        spread_cost = max(0.0, float(features.get("spread_yes") or 0.0)) / 2
        candidates.append((gross - fee - spread_cost - uncertainty, "YES", yes_ask, gross))
    if probability_no is not None and no_ask is not None:
        gross = probability_no - no_ask
        spread_cost = max(0.0, float(features.get("spread_no") or 0.0)) / 2
        candidates.append((gross - fee - spread_cost - uncertainty, "NO", no_ask, gross))
    best = max(candidates, default=(None, None, None, None), key=lambda item: item[0] if item[0] is not None else -math.inf)
    net_edge, outcome, executable_price, gross_edge = best
    if net_edge is not None and net_edge < float(signal.get("min_net_edge", 0.03)):
        reasons.append("EDGE_TOO_SMALL_AFTER_FEES")
    if confidence is None or confidence < float(signal.get("min_confidence", 0.55)):
        reasons.append("CONFIDENCE_TOO_LOW")

    # v2.77 is intentionally signals-only.  The future paper execution
    # adapter will consume qualified decisions after the evidence gate; this
    # scanner never calls place_webull_order or any live endpoint.
    if not reasons and signal.get("signals_only", True):
        reasons.append("PAPER_SIGNALS_ONLY")
    unique_reasons = list(dict.fromkeys(reasons))
    eligible = not unique_reasons
    score = 0.0
    if net_edge is not None:
        score += max(0.0, min(50.0, net_edge * 100))
    if confidence is not None:
        score += max(0.0, min(25.0, confidence * 25))
    if spreads:
        score += max(0.0, 15.0 - min(15.0, min(spreads) * 100))
    score += min(10.0, math.log10(1 + max(0.0, volume)))
    return {
        "contract_symbol": str(market.get("symbol") or "").upper(),
        "action": f"BUY_{outcome}" if eligible and outcome else "NO_TRADE",
        "outcome": outcome,
        "reason_codes": unique_reasons,
        "probability_yes": probability_yes,
        "probability_no": probability_no,
        "confidence": confidence,
        "fair_value_yes": probability_yes,
        "fair_value_no": probability_no,
        "executable_price": executable_price,
        "gross_edge": gross_edge,
        "net_edge": net_edge,
        "opportunity_score": round(max(0.0, min(100.0, score)), 2),
        "eligible": eligible,
        "mode": PAPER_MODE,
        "execution_allowed": False,
        "features": features,
    }


_SETTLED_OUTCOME_KEYS = (
    "settled_outcome", "winning_outcome", "resolved_outcome", "outcome", "result", "settlement_result",
)


def extract_settled_outcome(market):
    """Read an explicit provider settlement; never infer it from quotes."""
    if not isinstance(market, dict):
        return None
    candidates = []
    for key in _SETTLED_OUTCOME_KEYS:
        if key in market:
            candidates.append(market.get(key))
    for key in ("settlement", "resolution", "result_data"):
        value = market.get(key)
        if isinstance(value, dict):
            candidates.extend(value.get(item) for item in _SETTLED_OUTCOME_KEYS if item in value)
    for value in candidates:
        text = str(value or "").strip().upper()
        if text in {"YES", "NO"}:
            return text
    return None


def _latest_decision_for_snapshot(snapshot):
    if not snapshot:
        return None
    return (
        EventStrategyDecision.query
        .filter_by(snapshot_id=snapshot.id)
        .order_by(EventStrategyDecision.created_at.desc())
        .first()
    )


def _settle_simulated_orders(user_id, contract_symbol, outcome, settled_at):
    orders = (
        EventStrategyOrder.query
        .filter(
            EventStrategyOrder.user_id == user_id,
            EventStrategyOrder.contract_symbol == contract_symbol,
            EventStrategyOrder.status.in_(["SIMULATED_FILLED", "SIMULATED_PENDING"]),
        )
        .all()
    )
    for order in orders:
        entry = _number(order.filled_price if order.filled_price is not None else order.limit_price, 0.0) or 0.0
        quantity = _number(order.filled_quantity, 0.0) or 0.0
        fee = _number(order.fee, 0.0) or 0.0
        payout = quantity if str(order.outcome or "").upper() == outcome else 0.0
        order.realized_pnl = round(payout - (quantity * entry) - fee, 8)
        order.status = "SIMULATED_SETTLED"
        order.settled_at = settled_at
        order.updated_at = settled_at
    return len(orders)


def resolve_event_outcomes(user_id, *, config=None, limit=25, force=False):
    """Resolve expired contracts from Webull's explicit settlement fields."""
    config = config or get_or_create_config(user_id)
    if config.mode != PAPER_MODE or config.kill_switch:
        return {"success": False, "message": "Outcome resolution is available only in paper mode."}
    credential, environment = _webull_connection_for_user(user_id)
    from services.webull_service import get_webull_event_market

    now = datetime.utcnow()
    snapshots = (
        EventMarketSnapshot.query
        .filter(EventMarketSnapshot.user_id == user_id, EventMarketSnapshot.cutoff_at.isnot(None), EventMarketSnapshot.cutoff_at <= now)
        .order_by(EventMarketSnapshot.cutoff_at.asc())
        .limit(max(1, min(int(limit or 25), 100)))
        .all()
    )
    resolved = []
    pending = []
    seen = set()
    for snapshot in snapshots:
        symbol = str(snapshot.contract_symbol or "").upper()
        if not symbol or (symbol, snapshot.cutoff_at) in seen:
            continue
        seen.add((symbol, snapshot.cutoff_at))
        existing = EventContractOutcome.query.filter_by(
            user_id=user_id, contract_symbol=symbol, cutoff_at=snapshot.cutoff_at,
        ).order_by(EventContractOutcome.id.desc()).first()
        if existing and existing.settlement_status == "RESOLVED":
            continue
        raw = {}
        explicit = None
        error_message = None
        try:
            raw = get_webull_event_market(
                credential.webull_app_key,
                credential.webull_app_secret,
                environment,
                credential.webull_access_token,
                symbol=symbol,
                force=force,
            ) or {}
            explicit = extract_settled_outcome(raw)
        except Exception as exc:
            error_message = str(exc)
            raw = {"error": error_message}
        observed = now
        decision = _latest_decision_for_snapshot(snapshot)
        if not existing:
            existing = EventContractOutcome(
                user_id=user_id,
                config_id=config.id,
                contract_symbol=symbol,
                snapshot_id=snapshot.id,
                decision_id=decision.id if decision else None,
                cutoff_at=snapshot.cutoff_at,
            )
            db.session.add(existing)
        existing.observed_at = observed
        existing.provider_timestamp = _market_provider_timestamp(raw) or snapshot.provider_timestamp
        existing.raw_json = _json_dump(raw)
        existing.resolved_source = "WEBULL_EVENT_MARKET" if not error_message else "WEBULL_LOOKUP_ERROR"
        if explicit:
            existing.outcome = explicit
            existing.settlement_status = "RESOLVED"
            existing.settlement_at = _utc_naive(raw.get("payout_date")) or observed
            existing.settlement_price = _number(raw.get("settlement_price"))
            _settle_simulated_orders(user_id, symbol, explicit, existing.settlement_at)
            resolved.append({"contract_symbol": symbol, "outcome": explicit, "status": "RESOLVED"})
        else:
            existing.settlement_status = "PENDING"
            pending.append({"contract_symbol": symbol, "status": "PENDING", "message": error_message or "Webull has not supplied a settlement result yet."})
    db.session.commit()
    return {"success": True, "resolved": resolved, "pending": pending, "resolved_count": len(resolved), "pending_count": len(pending)}


def simulate_paper_fills(user_id, *, config=None, decision_ids=None, limit=25):
    """Create hypothetical fills for eligible signals without a broker call."""
    config = config or get_or_create_config(user_id)
    if config.mode != PAPER_MODE or config.kill_switch:
        return {"success": False, "message": "Paper-fill simulation is available only while the paper engine is enabled."}
    query = EventStrategyDecision.query.filter_by(user_id=user_id, eligible=True).order_by(EventStrategyDecision.created_at.desc())
    if decision_ids:
        try:
            ids = [int(value) for value in decision_ids]
        except (TypeError, ValueError):
            ids = []
        if ids:
            query = query.filter(EventStrategyDecision.id.in_(ids))
    decisions = query.limit(max(1, min(int(limit or 25), 100))).all()
    fee = _number(_json_load(config.signal_config, dict(DEFAULT_SIGNAL_CONFIG)).get("fee_per_contract"), 0.02) or 0.02
    created = []
    for decision in decisions:
        duplicate = EventStrategyOrder.query.filter_by(user_id=user_id, decision_id=decision.id).first()
        if duplicate:
            continue
        price = _number(decision.executable_price)
        outcome = str(decision.outcome or "").upper()
        if price is None or outcome not in {"YES", "NO"}:
            continue
        order = EventStrategyOrder(
            user_id=user_id,
            config_id=config.id,
            decision_id=decision.id,
            mode=PAPER_MODE,
            broker="WEBULL",
            client_order_id=f"paper-{uuid4().hex}",
            contract_symbol=decision.contract_symbol,
            outcome=outcome,
            side="BUY",
            quantity=1.0,
            limit_price=price,
            status="SIMULATED_FILLED",
            filled_quantity=1.0,
            filled_price=price,
            fee=fee,
        )
        db.session.add(order)
        created.append(order)
    db.session.commit()
    return {
        "success": True,
        "mode": PAPER_MODE,
        "simulated_count": len(created),
        "message": "No eligible signals are available to simulate." if not created else "Eligible signals simulated in paper mode.",
        "orders": [{"id": order.id, "contract_symbol": order.contract_symbol, "outcome": order.outcome, "price": order.filled_price, "status": order.status} for order in created],
    }


def event_strategy_performance(user_id, *, config=None, limit=500):
    """Aggregate settled hypothetical fills; unresolved contracts are excluded."""
    orders = (
        EventStrategyOrder.query.filter_by(user_id=user_id, mode=PAPER_MODE)
        .order_by(EventStrategyOrder.submitted_at.asc()).limit(max(1, min(int(limit or 500), 2000))).all()
    )
    outcomes = {}
    for row in EventContractOutcome.query.filter_by(user_id=user_id, settlement_status="RESOLVED").order_by(EventContractOutcome.observed_at.desc()).all():
        outcomes.setdefault(row.contract_symbol, row.outcome)
    decision_ids = [row.decision_id for row in orders if row.decision_id]
    decision_map = {row.id: row for row in EventStrategyDecision.query.filter(EventStrategyDecision.id.in_(decision_ids)).all()} if decision_ids else {}
    settled = []
    pending = 0
    for order in orders:
        result = outcomes.get(order.contract_symbol)
        if result not in {"YES", "NO"}:
            pending += 1
            continue
        won = str(order.outcome or "").upper() == result
        entry = _number(order.filled_price if order.filled_price is not None else order.limit_price, 0.0) or 0.0
        quantity = _number(order.filled_quantity, 0.0) or 0.0
        fee = _number(order.fee, 0.0) or 0.0
        pnl = _number(order.realized_pnl)
        if pnl is None:
            pnl = (quantity if won else 0.0) - quantity * entry - fee
        details = _json_load(decision_map.get(order.decision_id).feature_json if decision_map.get(order.decision_id) else "{}", {})
        label = ((details.get("contract_details") or {}).get("duration_label") or "Unknown duration") if isinstance(details, dict) else "Unknown duration"
        settled.append({"order": order, "won": won, "pnl": float(pnl), "fee": fee, "duration": label})
    pnls = [item["pnl"] for item in settled]
    gross_profit = sum(item for item in pnls if item > 0)
    gross_loss = sum(item for item in pnls if item < 0)
    running = peak = drawdown = 0.0
    for value in pnls:
        running += value
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    by_duration = {}
    for item in settled:
        bucket = by_duration.setdefault(item["duration"], {"duration": item["duration"], "trades": 0, "wins": 0, "net_pnl": 0.0})
        bucket["trades"] += 1
        bucket["wins"] += int(item["won"])
        bucket["net_pnl"] += item["pnl"]
    return {
        "mode": PAPER_MODE,
        "trades": len(settled),
        "pending": pending,
        "wins": sum(int(item["won"]) for item in settled),
        "losses": sum(int(not item["won"]) for item in settled),
        "gross_profit": round(gross_profit, 8),
        "gross_loss": round(gross_loss, 8),
        "fees": round(sum(item["fee"] for item in settled), 8),
        "net_pnl": round(sum(pnls), 8),
        "max_drawdown": round(drawdown, 8),
        "profit_factor": round(gross_profit / abs(gross_loss), 6) if gross_loss else None,
        "expectancy": round(sum(pnls) / len(pnls), 8) if pnls else None,
        "by_duration": [{**bucket, "net_pnl": round(bucket["net_pnl"], 8)} for bucket in by_duration.values()],
        "generated_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _snapshot_model(user_id, config_id, run_id, market, features, received_at):
    return EventMarketSnapshot(
        user_id=user_id,
        config_id=config_id,
        run_id=run_id,
        contract_symbol=str(market.get("symbol") or "").upper(),
        category_code=market.get("category_code"),
        series_symbol=market.get("series_symbol"),
        underlying_symbol=market.get("underlying_symbol"),
        provider_timestamp=_market_provider_timestamp(market),
        received_at=received_at,
        cutoff_at=_market_cutoff(market),
        yes_bid=_number(market.get("yes_bid")),
        yes_ask=_number(market.get("yes_ask")),
        no_bid=_number(market.get("no_bid")),
        no_ask=_number(market.get("no_ask")),
        yes_bid_size=_number(market.get("yes_bid_size")),
        yes_ask_size=_number(market.get("yes_ask_size")),
        no_bid_size=_number(market.get("no_bid_size")),
        no_ask_size=_number(market.get("no_ask_size")),
        volume=_number(market.get("volume")),
        open_interest=_number(market.get("open_interest")),
        underlying_price=_number(market.get("underlying_price")),
        underlying_change_pct=_number(market.get("underlying_change_pct")),
        realized_volatility=_number(market.get("realized_volatility")),
        time_remaining_seconds=features.get("time_remaining_seconds"),
        spread_yes=features.get("spread_yes"),
        spread_no=features.get("spread_no"),
        feature_json=_json_dump(features),
        raw_json=_json_dump(market),
    )


def _decision_model(user_id, config_id, run_id, snapshot_id, decision, model_version):
    return EventStrategyDecision(
        user_id=user_id,
        config_id=config_id,
        run_id=run_id,
        snapshot_id=snapshot_id,
        contract_symbol=decision["contract_symbol"],
        action=decision["action"],
        outcome=decision.get("outcome"),
        reason_codes=_json_dump(decision.get("reason_codes", [])),
        probability_yes=decision.get("probability_yes"),
        probability_no=decision.get("probability_no"),
        confidence=decision.get("confidence"),
        fair_value_yes=decision.get("fair_value_yes"),
        fair_value_no=decision.get("fair_value_no"),
        executable_price=decision.get("executable_price"),
        gross_edge=decision.get("gross_edge"),
        net_edge=decision.get("net_edge"),
        opportunity_score=decision.get("opportunity_score"),
        eligible=bool(decision.get("eligible")),
        model_version=model_version,
        feature_json=_json_dump(decision.get("features", {})),
    )


def _webull_connection_for_user(user_id):
    credential = Credential.query.filter_by(user_id=user_id).first()
    if not credential:
        raise RuntimeError("Connect Webull before starting Event Contract paper research.")
    app_key = credential.webull_app_key
    app_secret = credential.webull_app_secret
    access_token = credential.webull_access_token
    if not app_key or not app_secret or not access_token:
        raise RuntimeError("Complete Webull API verification before starting Event Contract paper research.")
    setting = UserSetting.query.filter_by(user_id=user_id).first()
    environment = getattr(setting, "webull_environment", None) or "production"
    return credential, environment


def run_event_strategy_scan(user_id, *, config=None, force=False, worker_id="manual"):
    """Scan configured crypto Event Contracts and persist an auditable run."""
    with _ACTIVE_SCAN_LOCK:
        if user_id in _ACTIVE_SCAN_USERS:
            return {"success": False, "message": "An Event Contract strategy scan is already running."}
        _ACTIVE_SCAN_USERS.add(user_id)
    try:
        config = config or get_or_create_config(user_id)
        if config.mode != PAPER_MODE or config.kill_switch:
            return {"success": False, "message": "The Event Contract engine is paper-only and is currently stopped by its kill switch."}
        credential, environment = _webull_connection_for_user(user_id)
        run = EventStrategyRun(
            config_id=config.id,
            user_id=user_id,
            mode=PAPER_MODE,
            status="RUNNING",
            worker_id=worker_id[:120],
            heartbeat_at=datetime.utcnow(),
        )
        db.session.add(run)
        db.session.flush()
        from services.webull_service import get_webull_event_markets

        symbols = _json_load(config.symbols, ["BTC", "ETH"])
        durations = _json_load(config.durations, ["FIFTEEN_MINUTES", "HOURLY"])
        markets = {}
        warnings = []
        scan_diagnostics = []
        for symbol in symbols[:10]:
            for duration in durations[:8]:
                diagnostic = {"symbol": symbol, "duration": duration, "status": "STARTING", "catalog_matches": 0, "verified_matches": 0, "scanned": 0, "warnings": []}
                try:
                    result = get_webull_event_markets(
                        credential.webull_app_key,
                        credential.webull_app_secret,
                        environment,
                        credential.webull_access_token,
                        category_id="CRYPTO",
                        query=symbol,
                        duration=duration,
                        limit=10,
                        force=force,
                        progressive=True,
                    )
                    warnings.extend(result.get("warnings") or [])
                    diagnostic.update({
                        "status": result.get("status") or ("PARTIAL" if result.get("partial") else "OK"),
                        "catalog_matches": result.get("catalog_matches", result.get("total_matches", 0)) or 0,
                        "verified_matches": result.get("verified_matches", len(result.get("markets") or [])) or 0,
                        "scanned": len(result.get("markets") or []),
                        "loading": bool(result.get("loading")),
                    })
                    diagnostic["warnings"] = list(dict.fromkeys(str(item) for item in (result.get("warnings") or [])))
                    for market in result.get("markets") or []:
                        if market.get("symbol"):
                            markets[str(market["symbol"]).upper()] = market
                except Exception as exc:
                    warnings.append(f"{symbol}/{duration}: {exc}")
                    diagnostic.update({"status": "ERROR", "error": str(exc), "warnings": [str(exc)]})
                    run.error_count += 1
                scan_diagnostics.append(diagnostic)
        now = datetime.utcnow()
        decisions = []
        for market in markets.values():
            features = _market_features(market, now)
            snapshot = _snapshot_model(user_id, config.id, run.id, market, features, now)
            db.session.add(snapshot)
            db.session.flush()
            decision = evaluate_market(market, config, now=now)
            record = _decision_model(user_id, config.id, run.id, snapshot.id, decision, config.model_version or MODEL_VERSION)
            db.session.add(record)
            db.session.flush()
            decisions.append({**decision, "decision_id": record.id, "snapshot_id": snapshot.id})
            run.scanned_count += 1
            if decision["eligible"]:
                run.qualified_count += 1
            else:
                run.no_trade_count += 1
        run.status = "COMPLETED" if not warnings else "DEGRADED"
        run.finished_at = datetime.utcnow()
        run.heartbeat_at = run.finished_at
        run.error_message = "\n".join(dict.fromkeys(str(item) for item in warnings))[:4000] if warnings else None
        run.diagnostics_json = _json_dump(scan_diagnostics)
        config.last_run_at = run.finished_at
        config.worker_status = "RUNNING" if config.enabled else "STOPPED"
        db.session.commit()
        return {
            "success": True,
            "mode": PAPER_MODE,
            "run_id": run.id,
            "status": run.status,
            "scanned_count": run.scanned_count,
            "qualified_count": run.qualified_count,
            "no_trade_count": run.no_trade_count,
            "error_count": run.error_count,
            "warnings": list(dict.fromkeys(warnings)),
            "diagnostics": scan_diagnostics,
            "decisions": decisions,
        }
    except Exception as exc:
        db.session.rollback()
        logger.error("Event strategy paper scan failed for user %s: %s", user_id, exc, exc_info=True)
        return {"success": False, "message": str(exc)}
    finally:
        with _ACTIVE_SCAN_LOCK:
            _ACTIVE_SCAN_USERS.discard(user_id)
        db.session.remove()


def event_algo_worker_loop(app):
    """Persisted, paper-only worker; idle unless a user explicitly starts it."""
    logger.info("Event Contract strategy worker started in paper/signal-only mode.")
    with app.app_context():
        while True:
            try:
                configs = EventStrategyConfig.query.filter_by(enabled=True, mode=PAPER_MODE, kill_switch=False).all()
                now = time.time()
                for config in configs:
                    signal = _json_load(config.signal_config, dict(DEFAULT_SIGNAL_CONFIG))
                    interval = max(30, int(_number(signal.get("scan_interval_seconds"), 60)))
                    if config.last_run_at and (datetime.utcnow() - config.last_run_at).total_seconds() < interval:
                        continue
                    run_event_strategy_scan(config.user_id, config=config, worker_id=f"paper-worker-{uuid4().hex[:12]}")
            except Exception as exc:
                logger.error("Event Contract strategy worker iteration failed: %s", exc, exc_info=True)
                db.session.rollback()
            finally:
                db.session.remove()
            time.sleep(15)
