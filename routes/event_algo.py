"""HTTP API for the paper-only Webull Event Contract strategy engine."""

import json

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from core.extensions import db
from credentials import UserSetting
from event_algo import (
    PAPER_MODE,
    config_to_dict,
    get_or_create_config,
    run_event_strategy_scan,
    update_config,
)
from event_algo_models import EventStrategyDecision, EventStrategyRun


event_algo_bp = Blueprint("event_algo", __name__)


def _paper_mode_enabled():
    setting = UserSetting.query.filter_by(user_id=current_user.id).first()
    return bool(getattr(setting, "webull_test_mode_enabled", False))


def _run_dict(run):
    if not run:
        return None
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
        "mode": PAPER_MODE,
    }


@event_algo_bp.route("/api/webull/event-algo/config", methods=["GET", "PUT"])
@login_required
def event_algo_config():
    config = get_or_create_config(current_user.id)
    if request.method == "PUT":
        if not _paper_mode_enabled():
            return jsonify({
                "success": False,
                "message": "Enable Webull paper/test mode before configuring the Event Contract engine.",
            }), 400
        update_config(config, request.get_json(silent=True) or {})
        db.session.commit()
    else:
        db.session.commit()
    return jsonify({"success": True, "config": config_to_dict(config)})


@event_algo_bp.route("/api/webull/event-algo/status", methods=["GET"])
@login_required
def event_algo_status():
    config = get_or_create_config(current_user.id)
    last_run = EventStrategyRun.query.filter_by(user_id=current_user.id).order_by(EventStrategyRun.started_at.desc()).first()
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "paper_mode_enabled": _paper_mode_enabled(),
        "config": config_to_dict(config),
        "last_run": _run_dict(last_run),
    })


@event_algo_bp.route("/api/webull/event-algo/start", methods=["POST"])
@login_required
def event_algo_start():
    if not _paper_mode_enabled():
        return jsonify({
            "success": False,
            "message": "The Event Contract strategy engine is paper-only. Enable Webull paper/test mode first.",
        }), 400
    config = get_or_create_config(current_user.id)
    config.enabled = True
    config.kill_switch = False
    config.mode = PAPER_MODE
    config.worker_status = "RUNNING"
    db.session.commit()
    return jsonify({"success": True, "mode": PAPER_MODE, "config": config_to_dict(config)})


@event_algo_bp.route("/api/webull/event-algo/stop", methods=["POST"])
@login_required
def event_algo_stop():
    config = get_or_create_config(current_user.id)
    config.enabled = False
    config.worker_status = "STOPPED"
    db.session.commit()
    return jsonify({"success": True, "mode": PAPER_MODE, "config": config_to_dict(config)})


@event_algo_bp.route("/api/webull/event-algo/kill-switch", methods=["POST"])
@login_required
def event_algo_kill_switch():
    config = get_or_create_config(current_user.id)
    config.enabled = False
    config.kill_switch = True
    config.worker_status = "KILLED"
    db.session.commit()
    return jsonify({
        "success": True,
        "mode": PAPER_MODE,
        "message": "Event Contract strategy entries are disabled by the kill switch.",
        "config": config_to_dict(config),
    })


@event_algo_bp.route("/api/webull/event-algo/scan", methods=["POST"])
@login_required
def event_algo_scan():
    if not _paper_mode_enabled():
        return jsonify({
            "success": False,
            "message": "The Event Contract engine will not scan or trade while Webull paper/test mode is disabled.",
        }), 400
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
@login_required
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
@login_required
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
