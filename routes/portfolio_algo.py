"""Administrator-only quantitative research API; all execution is isolated paper."""
from functools import wraps
import threading

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from core.extensions import db
from event_algo import is_event_strategy_admin
from portfolio_algo_models import DEFAULT_ALLOCATIONS, DEFAULT_MASTER_CIO_PROMPT, DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS
from services import portfolio_engine as engine

portfolio_algo_bp = Blueprint('portfolio_algo', __name__)


def portfolio_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_event_strategy_admin(current_user):
            return jsonify(success=False, message='Administrator privilege required.'), 403
        try:
            return view(*args, **kwargs)
        except ValueError as exc:
            db.session.rollback()
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Quantitative portfolio request failed')
            return jsonify(success=False, message='Portfolio operation failed. Check the application log.'), 500
    return wrapped


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('A JSON object is required.')
    return data


def config_dict(cfg):
    return {'id': cfg.id, 'name': cfg.name, 'total_bankroll': cfg.total_bankroll,
            'target_annual_return': cfg.target_annual_return, 'allocations': engine.allocations_for(cfg),
            'allocation_weights': engine.loads(cfg.allocations_json, DEFAULT_ALLOCATIONS),
            'cash_allocation_pct': 0 if any(s['enabled'] for s in engine.settings_for(cfg).values()) else 100,
            'watchlists': engine.loads(cfg.watchlists_json, DEFAULT_QUANT_WATCHLISTS), 'module_settings': engine.settings_for(cfg),
            'master_ai_prompt': cfg.master_ai_prompt or DEFAULT_MASTER_CIO_PROMPT,
            'master_ai_config': engine.loads(cfg.master_ai_config, {'cadence': 'off'}),
            'mode': 'PAPER', 'enabled': cfg.enabled, 'worker_status': cfg.worker_status}


@portfolio_algo_bp.route('/api/webull/portfolio-algo/config', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_get_config():
    cfg, acc, state = engine.ensure_portfolio(current_user.id)
    return jsonify(success=True, config=config_dict(cfg), account=engine.portfolio_status(current_user.id)['account'],
                   defaults={'allocations': DEFAULT_ALLOCATIONS, 'watchlists': DEFAULT_QUANT_WATCHLISTS,
                             'module_settings': DEFAULT_MODULE_SETTINGS, 'master_ai_prompt': DEFAULT_MASTER_CIO_PROMPT,
                             'total_bankroll': 50000, 'target_annual_return': 18.5})


@portfolio_algo_bp.route('/api/webull/portfolio-algo/config', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_update_config():
    data = payload()
    engine.ensure_portfolio(current_user.id)
    cfg, acc, state = engine.locked(current_user.id)
    changes = engine.validate_config(data, cfg)
    for key, value in changes.items():
        setattr(cfg, key, value)
    # Invalidate in-flight decisions made with the previous settings.
    state.lease_token = state.lease_until = None
    db.session.commit()
    return jsonify(success=True, message='Portfolio settings saved.', config=config_dict(cfg))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/status', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_status():
    return jsonify(engine.portfolio_status(current_user.id))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/data-check', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_data_check():
    from services.portfolio_readiness import check_data_access
    cfg, _, _ = engine.ensure_portfolio(current_user.id)
    return jsonify(success=True, modules=check_data_access(cfg))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/reset-bankroll', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_reset_bankroll():
    data = payload()
    if data.get('confirm') is not True:
        raise ValueError('Explicit bankroll reset confirmation is required.')
    result = engine.reset_bankroll(current_user.id, data.get('amount', 50000))
    return jsonify(success=True, message='New paper bankroll created. Previous run archived; engine stopped.', account=result)


@portfolio_algo_bp.route('/api/webull/portfolio-algo/control', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_control():
    action = payload().get('action')
    if action == 'scan':
        cfg, _, state = engine.ensure_portfolio(current_user.id)
        if not cfg.enabled or state.kill_switch:
            raise ValueError('Start the paper engine before requesting a scan.')
        app, user_id = current_app._get_current_object(), current_user.id
        def work():
            with app.app_context():
                try:
                    engine.run_scan(user_id, force=True)
                finally:
                    db.session.remove()
        threading.Thread(target=work, daemon=True, name='quant-manual-scan').start()
        return jsonify(success=True, message='Paper scan requested. Telemetry will refresh.'), 202
    engine.control(current_user.id, action)
    return jsonify(success=True, message='Portfolio worker control applied.')


@portfolio_algo_bp.route('/api/webull/portfolio-algo/master-audit', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_master_audit():
    prompt = payload().get('prompt')
    if prompt is not None and (not isinstance(prompt, str) or len(prompt)>16000):
        raise ValueError('CIO prompt must be text of at most 16000 characters.')
    app, user_id = current_app._get_current_object(), current_user.id
    audit_id = engine.reserve_audit(user_id)
    audit = engine.audit_dict(db.session.get(engine.Audit, audit_id))
    def work():
        with app.app_context():
            try:
                engine.run_audit(user_id, prompt=prompt, audit_id=audit_id)
            finally:
                db.session.remove()
    threading.Thread(target=work, daemon=True, name=f'quant-audit-{audit_id}').start()
    return jsonify(success=True, audit=audit, message='Audit queued. Progress is saved in report history.'), 202


@portfolio_algo_bp.route('/api/webull/portfolio-algo/audits', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_audits():
    rows = engine.Audit.query.filter_by(user_id=current_user.id).order_by(engine.Audit.id.desc()).limit(50).all()
    return jsonify(success=True, audits=[engine.audit_dict(row) for row in rows])


@portfolio_algo_bp.route('/api/webull/portfolio-algo/ai-config', methods=['GET', 'POST'])
@portfolio_admin_required
def portfolio_algo_ai_config():
    from credentials import UserSetting
    import json
    cfg, acc, state = engine.ensure_portfolio(current_user.id)
    user_setting = UserSetting.query.filter_by(user_id=current_user.id).first()

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        if "audit_hours" in payload and user_setting:
            try:
                user_setting.event_strategy_audit_hours = max(1, min(72, int(payload["audit_hours"])))
            except (TypeError, ValueError):
                pass

        if "master_ai_prompt" in payload:
            prompt = payload["master_ai_prompt"]
            if isinstance(prompt, str) and len(prompt) <= 16000:
                cfg.master_ai_prompt = prompt.strip() or DEFAULT_MASTER_CIO_PROMPT

        if "ai_config" in payload and isinstance(payload["ai_config"], dict):
            try:
                existing_ai = json.loads(cfg.master_ai_config) if cfg.master_ai_config else {}
            except json.JSONDecodeError:
                existing_ai = {}
            new_ai = payload["ai_config"]
            from credential_security import encrypt_secret
            merged_ai = existing_ai.copy()
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
            cfg.master_ai_config = json.dumps(merged_ai)

        from portfolio_algo_models import _record_portfolio_log
        _record_portfolio_log(
            current_user.id,
            "AI_CONFIG_UPDATED",
            "Master AI configuration and audit controls updated."
        )
        db.session.commit()

    audit_hours = getattr(user_setting, "event_strategy_audit_hours", 6) if user_setting else 6
    
    from routes.event_algo import sanitize_event_ai_config
    return jsonify({
        "success": True,
        "audit_hours": audit_hours,
        "master_ai_prompt": cfg.master_ai_prompt,
        "ai_config": sanitize_event_ai_config(cfg.master_ai_config or "{}"),
    })


@portfolio_algo_bp.route('/api/webull/portfolio-algo/ai-test', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_ai_test():
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get("provider") or "").strip().lower()
    model = str(payload.get("model") or "").strip()
    tier = str(payload.get("tier") or "primary").strip().lower()
    reasoning_level = str(payload.get("reasoning_level") or "medium").strip().lower()
    api_key = payload.get("api_key")

    if not provider:
        return jsonify({"success": False, "message": "AI provider is required"}), 400

    if not api_key or api_key == "********":
        cfg, acc, state = engine.ensure_portfolio(current_user.id)
        import json
        try:
            raw_ai = json.loads(cfg.master_ai_config) if cfg.master_ai_config else {}
        except json.JSONDecodeError:
            raw_ai = {}
        tier_data = raw_ai.get(tier) or {}
        from credential_security import decrypt_secret
        if tier_data.get("api_key"):
            api_key = decrypt_secret(tier_data["api_key"])
        if not api_key:
            from event_algo_models import Credential
            cred = Credential.query.filter_by(user_id=current_user.id).first()
            if cred and provider != "ollama":
                api_key = (
                    decrypt_secret(getattr(cred, f"_{provider}_key", None)) or
                    decrypt_secret(getattr(cred, f"{provider}_key", None))
                )

    import requests
    if provider == "ollama":
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

    from routes.event_algo import test_provider_api
    return test_provider_api(provider, api_key, model, reasoning_level)


@portfolio_algo_bp.route('/api/webull/portfolio-algo/logs', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_logs():
    try:
        limit = max(1, min(int(request.args.get("limit") or 200), 500))
    except (TypeError, ValueError):
        limit = 200
    
    from portfolio_algo_models import PortfolioEngineLog
    query = PortfolioEngineLog.query.filter_by(user_id=current_user.id)
    level = request.args.get("level")
    event_type = request.args.get("event_type")
    
    if level and level != "ALL":
        query = query.filter_by(level=level)
    if event_type:
        query = query.filter(PortfolioEngineLog.event_type.ilike(f"%{event_type}%"))
    
    rows = query.order_by(PortfolioEngineLog.id.desc()).limit(limit).all()
    
    data = []
    for r in rows:
        import json
        try:
            details = json.loads(r.details_json) if r.details_json else {}
        except json.JSONDecodeError:
            details = {}
        data.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() + "Z",
            "level": r.level,
            "event_type": r.event_type,
            "message": r.message,
            "details": details
        })
    
    return jsonify({"success": True, "logs": data})


@portfolio_algo_bp.route('/api/webull/portfolio-algo/orders', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_orders():
    from portfolio_algo_models import PortfolioStrategyOrder
    import json
    status_filter = str(request.args.get('status') or '').lower()
    query = PortfolioStrategyOrder.query.filter_by(user_id=current_user.id)
    if status_filter == 'open':
        query = query.filter(PortfolioStrategyOrder.status.in_(['OPEN', 'WORKING', 'PENDING', 'NEW', 'SUBMITTED']))
    rows = query.order_by(PortfolioStrategyOrder.created_at.desc()).limit(500).all()
    orders = []
    for r in rows:
        notes_dict = {}
        if r.notes:
            try:
                notes_dict = json.loads(r.notes)
            except Exception:
                notes_dict = {'raw': r.notes}
        orders.append({
            'id': f'QUANT_{r.id}',
            'order_id': f'QUANT_{r.id}',
            'symbol': r.symbol,
            'instrument_type': r.instrument_type,
            'module_name': r.module_name,
            'side': r.side,
            'order_type': r.order_type,
            'quantity': r.quantity,
            'filled_quantity': r.quantity if r.status == 'FILLED' else 0,
            'price': r.price,
            'status': r.status,
            'pnl': r.pnl,
            'notes': r.notes,
            'details': notes_dict,
            'is_paper': True,
            'is_quant': True,
            'account_id': 'QUANT_PAPER_ACCOUNT',
            'created_at': r.created_at.isoformat() + 'Z' if r.created_at else None,
        })
    return jsonify(success=True, orders=orders, total=len(orders))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/positions', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_positions():
    status = engine.portfolio_status(current_user.id)
    positions = []
    for p in status.get('positions', []):
        positions.append({
            'id': f"QUANT_POS_{p['id']}",
            'symbol': p['symbol'],
            'instrument_type': p.get('instrument_type', 'EQUITY'),
            'module': p.get('module'),
            'side': p.get('side', 'LONG'),
            'quantity': p.get('quantity', 0),
            'cost_price': p.get('average_cost', 0),
            'last_price': p.get('mark', 0),
            'market_value': (p.get('mark', 0) * p.get('quantity', 0)) or p.get('collateral', 0),
            'unrealized_profit_loss': p.get('unrealized_pnl', 0),
            'collateral': p.get('collateral', 0),
            'stop_price': p.get('stop'),
            'target_price': p.get('target'),
            'details': p.get('details', {}),
            'is_paper': True,
            'is_quant': True,
            'account_id': 'QUANT_PAPER_ACCOUNT',
            'source': 'webull_quant',
            'updated_at': p.get('marked_at'),
        })
    return jsonify(success=True, positions=positions, total=len(positions))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/account-summary', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_account_summary():
    status = engine.portfolio_status(current_user.id)
    acc = status.get('account', {})
    perf = status.get('performance', {})
    summary = {
        'account_id': 'QUANT_PAPER_ACCOUNT',
        'account_name': 'Quantitative Strategy Engine (Isolated Paper)',
        'cash_balance': acc.get('cash_balance', 50000.0),
        'net_liquidation': acc.get('total_equity', 50000.0),
        'total_equity': acc.get('total_equity', 50000.0),
        'initial_balance': acc.get('initial_balance', 50000.0),
        'unrealized_pnl': acc.get('unrealized_pnl', 0.0),
        'realized_pnl': acc.get('realized_pnl', 0.0),
        'return_pct': acc.get('return_pct', 0.0),
        'max_drawdown_pct': perf.get('max_drawdown_pct', 0.0),
        'win_rate_pct': perf.get('win_rate_pct'),
        'open_positions_count': status.get('open_positions_count', 0),
        'worker_status': status.get('worker_status', 'STOPPED'),
        'is_paper': True,
        'is_quant': True,
    }
    return jsonify(success=True, summary=summary)
