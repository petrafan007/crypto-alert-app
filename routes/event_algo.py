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
    DEFAULT_AUDIT_SYSTEM_PROMPT,
    DEFAULT_EVENT_AI_CONFIG,
    sanitize_event_ai_config,
    _json_load,
    _json_dump,
)
from credentials import Credential, UserSetting
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


@event_algo_bp.route("/api/webull/event-algo/ai-config", methods=["GET", "POST"])
@event_strategy_admin_required
def event_algo_ai_config():
    config = get_or_create_config(current_user.id)
    user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        # 1. Update Audit Settings
        if "audit_hours" in payload and user_setting:
            try:
                user_setting.event_strategy_audit_hours = max(1, min(72, int(payload["audit_hours"])))
            except (TypeError, ValueError):
                pass
        if "audit_prompt" in payload and user_setting:
            user_setting.event_strategy_audit_prompt = str(payload["audit_prompt"] or "").strip()

        # 2. Update AI Config (Primary, Secondary, Tertiary)
        if "ai_config" in payload and isinstance(payload["ai_config"], dict):
            existing_ai = _json_load(config.ai_config, {})
            new_ai = payload["ai_config"]
            from credential_security import encrypt_secret
            merged_ai = {}
            for tier in ("primary", "secondary", "tertiary"):
                new_tier = new_ai.get(tier) or {}
                old_tier = existing_ai.get(tier) or {}
                raw_key = new_tier.get("api_key")
                if raw_key == "********":
                    stored_key = old_tier.get("api_key")
                elif raw_key and str(raw_key).strip():
                    stored_key = encrypt_secret(str(raw_key).strip())
                else:
                    stored_key = None
                merged_ai[tier] = {
                    "provider": str(new_tier.get("provider") or "").strip().lower(),
                    "model": str(new_tier.get("model") or "").strip(),
                    "reasoning_level": str(new_tier.get("reasoning_level") or "medium").strip().lower(),
                    "api_key": stored_key,
                }
            config.ai_config = _json_dump(merged_ai)

        _record_engine_log(
            current_user.id,
            "AI_CONFIG_UPDATED",
            "Event Strategy Engine AI configuration and audit controls updated.",
            config_id=config.id,
        )
        db.session.commit()

    audit_hours = getattr(user_setting, "event_strategy_audit_hours", 6) if user_setting else 6
    audit_prompt = getattr(user_setting, "event_strategy_audit_prompt", None) if user_setting else None
    if not audit_prompt:
        audit_prompt = DEFAULT_AUDIT_SYSTEM_PROMPT

    return jsonify({
        "success": True,
        "audit_hours": audit_hours,
        "audit_prompt": audit_prompt,
        "ai_config": sanitize_event_ai_config(getattr(config, "ai_config", "{}")),
    })


@event_algo_bp.route("/api/webull/event-algo/ai-test", methods=["POST"])
@event_strategy_admin_required
def event_algo_ai_test():
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get("provider") or "").strip().lower()
    model = str(payload.get("model") or "").strip()
    tier = str(payload.get("tier") or "primary").strip().lower()
    reasoning_level = str(payload.get("reasoning_level") or "medium").strip().lower()
    api_key = payload.get("api_key")

    if not provider:
        return jsonify({"success": False, "message": "AI provider is required"}), 400

    # If api_key is masked or omitted, check saved event config or global credentials
    if not api_key or api_key == "********":
        config = get_or_create_config(current_user.id)
        raw_ai = _json_load(config.ai_config, {})
        tier_data = raw_ai.get(tier) or {}
        from credential_security import decrypt_secret
        if tier_data.get("api_key"):
            api_key = decrypt_secret(tier_data["api_key"])
        if not api_key:
            cred = Credential.query.filter_by(user_id=current_user.id).first()
            if cred and provider != "ollama":
                api_key = (
                    decrypt_secret(getattr(cred, f"_{provider}_key", None)) or
                    decrypt_secret(getattr(cred, f"{provider}_key", None))
                )

    import requests
    if provider == "ollama":
        if not is_event_strategy_admin(current_user):
            return jsonify({"success": False, "message": "Ollama is restricted to the administrator account."}), 403
        try:
            from services.ai_service import call_ollama_chat
            test_model = model or "gpt-oss:120b-cloud"
            call_ollama_chat(
                test_model,
                [{"role": "user", "content": "Reply with exactly OK."}],
                max_tokens=32,
                timeout=30,
                reasoning_level=reasoning_level,
            )
            return jsonify({"success": True, "message": f"Ollama connection OK ({test_model})"})
        except Exception as exc:
            return jsonify({"success": False, "message": f"Ollama error: {exc}"}), 400

    if not api_key:
        return jsonify({"success": False, "message": f"API key is required for {provider.upper()}"}), 400

    try:
        if provider == "gemini":
            test_model = model or "gemini-3.8-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{test_model}:generateContent?key={api_key}"
            r = requests.post(url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": "ping"}]}]}, timeout=20)
            if r.status_code == 200:
                return jsonify({"success": True, "message": f"Gemini connection OK ({test_model})"})
            return jsonify({"success": False, "message": f"Gemini error: {r.text[:300]}"}), 400
        elif provider == "openai":
            import openai
            client = openai.OpenAI(api_key=api_key)
            test_model = model or "gpt-5.4-mini"
            client.chat.completions.create(model=test_model, messages=[{"role": "user", "content": "ping"}], max_completion_tokens=5)
            return jsonify({"success": True, "message": f"OpenAI connection OK ({test_model})"})
        elif provider == "zai":
            from zai_client import ZAIClient
            client = ZAIClient(api_key)
            test_model = model or "glm-4.5-flash"
            resp = client.chat_completion(messages=[{"role": "user", "content": "ping"}], model=test_model, max_tokens=5)
            if resp.get("success"):
                return jsonify({"success": True, "message": f"Z.AI connection OK ({test_model})"})
            return jsonify({"success": False, "message": f"Z.AI error: {resp.get('error')}"}), 400
        elif provider == "perplexity":
            test_model = model or "sonar"
            r = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": test_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                timeout=20,
            )
            if r.status_code == 200:
                return jsonify({"success": True, "message": f"Perplexity connection OK ({test_model})"})
            return jsonify({"success": False, "message": f"Perplexity error: {r.text[:300]}"}), 400
        elif provider == "inception":
            test_model = model or "mercury-2"
            r = requests.post(
                "https://api.inceptionlabs.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": test_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                timeout=20,
            )
            if r.status_code == 200:
                return jsonify({"success": True, "message": f"Inception Labs connection OK ({test_model})"})
            return jsonify({"success": False, "message": f"Inception Labs error: {r.text[:300]}"}), 400
        else:
            return jsonify({"success": False, "message": f"Unsupported provider: {provider}"}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"{provider.capitalize()} error: {exc}"}), 400


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
