"""HTTP API for the paper-only Webull Event Contract strategy engine."""

import json
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from core.extensions import db
from event_algo import (
    PAPER_MODE,
    config_to_dict,
    event_strategy_performance,
    event_strategy_health_summary,
    event_strategy_logs,
    generate_event_strategy_report,
    get_latest_event_strategy_report,
    list_event_strategy_reports,
    report_to_dict,
    is_event_strategy_admin,
    _record_engine_log,
    get_or_create_config,
    resolve_event_outcomes,
    run_event_strategy_scan,
    simulate_paper_fills,
    update_config,
)
from credentials import UserSetting
from event_algo_models import EventStrategyDecision, EventStrategyRun


event_algo_bp = Blueprint("event_algo", __name__)


def event_strategy_admin_required(view):
    """Restrict every strategy-engine API to the permanent administrator."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_event_strategy_admin(current_user):
            return jsonify({
                "success": False,
                "message": "The Event Contract Strategy Engine is restricted to the administrator.",
            }), 403
        return view(*args, **kwargs)
    return wrapped


def _paper_mode_enabled():
    """The strategy engine is permanently paper-only.

    This is deliberately independent of the user's Webull trading-mode
    toggle.  The toggle controls broker order routing elsewhere in the app;
    this engine only records paper snapshots, decisions, and simulations.
    """
    return True


def _run_dict(run):
    if not run:
        return None
    try:
        diagnostics = json.loads(run.diagnostics_json or "[]")
    except (TypeError, ValueError):
        diagnostics = []
    return {
        "id": run.id,
        "status": run.status,
        "mode": PAPER_MODE,
        "worker_id": run.worker_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "scanned_count": run.scanned_count,
        "qualified_count": run.qualified_count,
        "no_trade_count": run.no_trade_count,
        "error_count": run.error_count,
        "paper_equity": run.paper_equity,
        "error_message": run.error_message,
        "diagnostics": diagnostics,
    }


def _decision_dict(decision):
    if not decision:
        return None
    try:
        reasons = json.loads(decision.reason_codes or "[]")
    except (TypeError, ValueError):
        reasons = []
    try:
        features = json.loads(decision.feature_json or "{}")
    except (TypeError, ValueError):
        features = {}
    return {
        "id": decision.id,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
        "contract_symbol": decision.contract_symbol,
        "action": decision.action,
        "outcome": decision.outcome,
        "reason_codes": reasons,
        "probability_yes": decision.probability_yes,
        "probability_no": decision.probability_no,
        "confidence": decision.confidence,
        "fair_value_yes": decision.fair_value_yes,
        "fair_value_no": decision.fair_value_no,
        "executable_price": decision.executable_price,
        "gross_edge": decision.gross_edge,
        "net_edge": decision.net_edge,
        "opportunity_score": decision.opportunity_score,
        "eligible": bool(decision.eligible),
        "model_version": decision.model_version,
        "features": features,
        "contract_details": features.get("contract_details") if isinstance(features, dict) else None,
        "mode": PAPER_MODE,
    }


@event_algo_bp.route("/api/webull/event-algo/config", methods=["GET", "PUT"])
@event_strategy_admin_required
def event_algo_config():
    config = get_or_create_config(current_user.id)
    if request.method == "PUT":
        update_config(config, request.get_json(silent=True) or {})
        _record_engine_log(current_user.id, "CONFIG_UPDATED", "Event Contract Strategy Engine settings updated from Settings.", config_id=config.id)
        db.session.commit()
    else:
        db.session.commit()
    return jsonify({"success": True, "config": config_to_dict(config)})


@event_algo_bp.route("/api/webull/event-algo/status", methods=["GET"])
@event_strategy_admin_required
def event_algo_status():
    config = get_or_create_config(current_user.id)
    last_run = EventStrategyRun.query.filter_by(user_id=current_user.id).order_by(EventStrategyRun.started_at.desc()).first()
    health = event_strategy_health_summary(current_user.id)
    db.session.commit()
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "paper_mode_enabled": _paper_mode_enabled(),
        "config": config_to_dict(config),
        "last_run": _run_dict(last_run),
        "health": health,
    })


@event_algo_bp.route("/api/webull/event-algo/logs", methods=["GET"])
@event_strategy_admin_required
def event_algo_logs():
    try:
        limit = max(1, min(int(request.args.get("limit") or 200), 500))
    except (TypeError, ValueError):
        limit = 200
    rows = event_strategy_logs(
        current_user.id,
        limit=limit,
        level=request.args.get("level"),
        event_type=request.args.get("event_type"),
    )
    return jsonify({"success": True, "mode": PAPER_MODE, "logs": rows})


@event_algo_bp.route("/api/webull/event-algo/start", methods=["POST"])
@event_strategy_admin_required
def event_algo_start():
    config = get_or_create_config(current_user.id)
    config.enabled = True
    config.kill_switch = False
    config.mode = PAPER_MODE
    config.worker_status = "RUNNING"
    _record_engine_log(current_user.id, "ENGINE_STARTED", "Event Contract Strategy Engine started in paper/signal-only mode.", config_id=config.id)
    db.session.commit()
    return jsonify({"success": True, "mode": PAPER_MODE, "config": config_to_dict(config)})


@event_algo_bp.route("/api/webull/event-algo/stop", methods=["POST"])
@event_strategy_admin_required
def event_algo_stop():
    config = get_or_create_config(current_user.id)
    config.enabled = False
    config.worker_status = "STOPPED"
    _record_engine_log(current_user.id, "ENGINE_STOPPED", "Event Contract Strategy Engine stopped by the user.", config_id=config.id)
    db.session.commit()
    return jsonify({"success": True, "mode": PAPER_MODE, "config": config_to_dict(config)})


@event_algo_bp.route("/api/webull/event-algo/kill-switch", methods=["POST"])
@event_strategy_admin_required
def event_algo_kill_switch():
    config = get_or_create_config(current_user.id)
    config.enabled = False
    config.kill_switch = True
    config.worker_status = "KILLED"
    _record_engine_log(current_user.id, "KILL_SWITCH_ENABLED", "Event Contract Strategy Engine kill switch enabled; no strategy entries can be created.", level="WARNING", config_id=config.id, notify=True)
    db.session.commit()
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "message": "Event Contract strategy entries are disabled by the kill switch.",
        "config": config_to_dict(config),
    })


@event_algo_bp.route("/api/webull/event-algo/scan", methods=["POST"])
@event_strategy_admin_required
def event_algo_scan():
    config = get_or_create_config(current_user.id)
    payload = request.get_json(silent=True) or {}
    result = run_event_strategy_scan(
        current_user.id,
        config=config,
        force=bool(payload.get("refresh")),
        worker_id="manual",
    )
    return jsonify(result), (200 if result.get("success") else 400)


@event_algo_bp.route("/api/webull/event-algo/decisions", methods=["GET"])
@event_strategy_admin_required
def event_algo_decisions():
    try:
        limit = max(1, min(int(request.args.get("limit") or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    query = EventStrategyDecision.query.filter_by(user_id=current_user.id)
    if request.args.get("eligible") == "1":
        query = query.filter_by(eligible=True)
    rows = query.order_by(EventStrategyDecision.created_at.desc()).limit(limit).all()
    return jsonify({"success": True, "mode": PAPER_MODE, "decisions": [_decision_dict(row) for row in rows]})


@event_algo_bp.route("/api/webull/event-algo/opportunities", methods=["GET"])
@event_strategy_admin_required
def event_algo_opportunities():
    try:
        limit = max(1, min(int(request.args.get("limit") or 25), 100))
    except (TypeError, ValueError):
        limit = 25
    rows = (
        EventStrategyDecision.query
        .filter_by(user_id=current_user.id, eligible=True)
        .order_by(EventStrategyDecision.created_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"success": True, "mode": PAPER_MODE, "opportunities": [_decision_dict(row) for row in rows]})


@event_algo_bp.route("/api/webull/event-algo/resolve", methods=["POST"])
@event_strategy_admin_required
def event_algo_resolve():
    payload = request.get_json(silent=True) or {}
    try:
        limit = max(1, min(int(payload.get("limit") or 25), 100))
    except (TypeError, ValueError):
        limit = 25
    try:
        result = resolve_event_outcomes(current_user.id, limit=limit, force=bool(payload.get("refresh")))
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify(result)


@event_algo_bp.route("/api/webull/event-algo/simulate", methods=["POST"])
@event_strategy_admin_required
def event_algo_simulate():
    payload = request.get_json(silent=True) or {}
    result = simulate_paper_fills(
        current_user.id,
        decision_ids=payload.get("decision_ids"),
        limit=payload.get("limit", 25),
    )
    return jsonify(result), (200 if result.get("success") else 400)


@event_algo_bp.route("/api/webull/event-algo/performance", methods=["GET"])
@event_strategy_admin_required
def event_algo_performance():
    try:
        limit = max(1, min(int(request.args.get("limit") or 500), 2000))
    except (TypeError, ValueError):
        limit = 500
    return jsonify({"success": True, **event_strategy_performance(current_user.id, limit=limit)})


@event_algo_bp.route("/api/webull/event-algo/report", methods=["GET"])
@event_strategy_admin_required
def event_algo_report():
    report_id = request.args.get("id")
    report = get_latest_event_strategy_report(current_user.id, report_id=report_id)
    history = list_event_strategy_reports(current_user.id, limit=20)
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "report": report_to_dict(report),
        "history": [report_to_dict(r) for r in history],
    })


@event_algo_bp.route("/api/webull/event-algo/report/<int:report_id>", methods=["GET"])
@event_strategy_admin_required
def event_algo_report_detail(report_id):
    report = get_latest_event_strategy_report(current_user.id, report_id=report_id)
    if not report:
        return jsonify({"success": False, "message": "Report not found."}), 404
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "report": report_to_dict(report),
    })


@event_algo_bp.route("/api/webull/event-algo/report/generate", methods=["POST"])
@event_strategy_admin_required
def event_algo_report_generate():
    payload = request.get_json(silent=True) or {}
    user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
    default_hours = getattr(user_setting, "event_strategy_audit_hours", 6) or 6
    try:
        hours = max(1, min(int(payload.get("hours") or default_hours), 72))
    except (TypeError, ValueError):
        hours = default_hours
    config = get_or_create_config(current_user.id)
    report = generate_event_strategy_report(current_user.id, config=config, hours=hours, force=True)
    history = list_event_strategy_reports(current_user.id, limit=20)
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "report": report_to_dict(report),
        "history": [report_to_dict(r) for r in history],
    })
