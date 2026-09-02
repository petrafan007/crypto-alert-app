"""Paper-first Webull Event Contract strategy engine.

This module intentionally contains no live-order call.  It normalizes current
Webull Event Contract quotes, records an auditable decision trace, and exposes
the risk/edge calculations that a future execution adapter can consume after
forward-paper evidence is sufficient.
"""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

from log import logger
from core.extensions import db
from credentials import Credential, UserSetting
from event_algo_models import (
    EventMarketSnapshot,
    EventStrategyConfig,
    EventStrategyDecision,
    EventStrategyRun,
)


PAPER_MODE = "PAPER"
ENGINE_VERSION = "1.0.0"
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
        for symbol in symbols[:10]:
            for duration in durations[:8]:
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
                    for market in result.get("markets") or []:
                        if market.get("symbol"):
                            markets[str(market["symbol"]).upper()] = market
                except Exception as exc:
                    warnings.append(f"{symbol}/{duration}: {exc}")
                    run.error_count += 1
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
