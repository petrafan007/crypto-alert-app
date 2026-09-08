import io
import json
import threading
import zipfile
from datetime import datetime
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_login import current_user, login_required

from core.extensions import db
from event_algo import is_event_strategy_admin
from portfolio_algo_models import (
    DEFAULT_ALLOCATIONS, DEFAULT_MASTER_CIO_PROMPT, DEFAULT_MODULE_SETTINGS, DEFAULT_QUANT_WATCHLISTS,
    PortfolioStrategyOrder, PortfolioStrategyPosition, PortfolioStrategyLot,
    PortfolioEquitySnapshot, PortfolioAudit, PortfolioEngineLog
)
from services import portfolio_engine as engine

portfolio_algo_bp = Blueprint('portfolio_algo', __name__)


def _quant_account_mapping(instrument_type, module_name=None):
    mod = str(module_name or '').upper()
    inst = str(instrument_type or '').upper()
    if mod == 'CRYPTO' or inst == 'CRYPTO':
        return 'QUANT_ACC_CRYPTO', 'Crypto'
    if mod in ('EVENTS', 'EVENT') or inst == 'EVENT':
        return 'QUANT_ACC_EVENTS', 'Events Cash'
    if mod in ('FUTURES', 'FUTURE') or inst == 'FUTURES':
        return 'QUANT_ACC_FUTURES', 'Futures'
    return 'QUANT_ACC_INDIVIDUAL_CASH', 'Individual Cash'


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


def validate_master_ai_config(ai_config):
    """Reject a dedicated cascade that references unavailable local models."""
    allowed_providers = {'gemini', 'openai', 'zai', 'perplexity', 'inception', 'ollama'}
    ollama_models = None
    for tier_name in ('primary', 'secondary', 'tertiary'):
        tier = ai_config.get(tier_name)
        if not isinstance(tier, dict):
            raise ValueError(f'{tier_name.title()} AI integration is required.')
        provider = str(tier.get('provider') or '').strip().lower()
        model = str(tier.get('model') or '').strip()
        if provider not in allowed_providers:
            raise ValueError(f'{tier_name.title()} AI provider is invalid.')
        if not model:
            raise ValueError(f'{tier_name.title()} AI model is required.')
        if provider != 'ollama':
            continue
        if ollama_models is None:
            try:
                from services.ai_service import get_ollama_models
                ollama_models = set(get_ollama_models())
            except Exception as exc:
                raise ValueError(
                    'Ollama model inventory is unavailable; configuration was not saved.'
                ) from exc
        if model not in ollama_models:
            raise ValueError(
                f"{tier_name.title()} Ollama model '{model}' is not available; "
                'refresh the model list and select an installed model.'
            )


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
@portfolio_algo_bp.route('/api/portfolio-algo/reset-bankroll', methods=['POST'])
@portfolio_admin_required
def portfolio_algo_reset_bankroll():
    data = payload()
    if data.get('confirm') is not True:
        raise ValueError('Explicit bankroll reset confirmation is required.')
    amount = float(data.get('amount', 50000))
    if data.get('wipe_history') is True:
        result = engine.wipe_and_reset_portfolio(current_user.id, amount)
        return jsonify(
            success=True,
            message=f'Paper engine cleanly reset with ${amount:,.2f} bankroll. All previous trade data, logs, and reports purged.',
            account=result
        )
    result = engine.reset_bankroll(current_user.id, amount)
    return jsonify(success=True, message='New paper bankroll created. Previous run archived; engine stopped.', account=result)


@portfolio_algo_bp.route('/api/webull/portfolio-algo/export-archive', methods=['GET'])
@portfolio_algo_bp.route('/api/portfolio-algo/export-archive', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_export_archive():
    """Bundle all past quantitative orders, positions, snapshots, audits, and logs into a downloadable ZIP archive."""
    user_id = current_user.id
    cfg, acc, state = engine.ensure_portfolio(user_id)

    orders = PortfolioStrategyOrder.query.filter_by(user_id=user_id).order_by(PortfolioStrategyOrder.created_at.asc()).all()
    orders_data = [{
        'id': o.id, 'symbol': o.symbol, 'module_name': o.module_name, 'instrument_type': o.instrument_type,
        'side': o.side, 'order_type': o.order_type, 'quantity': o.quantity, 'price': o.price,
        'status': o.status, 'pnl': o.pnl, 'notes': o.notes,
        'created_at': o.created_at.isoformat() if o.created_at else None,
    } for o in orders]

    positions = PortfolioStrategyPosition.query.filter_by(user_id=user_id).all()
    pos_data = [{
        'id': p.id, 'symbol': p.symbol, 'instrument_type': p.instrument_type, 'side': p.side,
        'quantity': p.quantity, 'average_cost': p.average_cost, 'market_price': p.market_price,
        'market_value': p.market_value, 'unrealized_pnl': p.unrealized_pnl,
        'updated_at': p.updated_at.isoformat() if p.updated_at else None,
    } for p in positions]

    lots = PortfolioStrategyLot.query.filter_by(user_id=user_id).all()
    lots_data = [{
        'id': l.id, 'position_id': l.position_id, 'generation': l.generation, 'module': l.module,
        'signal_key': l.signal_key, 'collateral': l.collateral, 'multiplier': l.multiplier,
        'stop_price': l.stop_price, 'target_price': l.target_price, 'entry_fee': l.entry_fee,
        'realized_pnl': l.realized_pnl, 'details': l.details_json,
        'opened_at': l.opened_at.isoformat() if l.opened_at else None,
        'closed_at': l.closed_at.isoformat() if l.closed_at else None,
    } for l in lots]

    snapshots = PortfolioEquitySnapshot.query.filter_by(user_id=user_id).order_by(PortfolioEquitySnapshot.created_at.asc()).all()
    snaps_data = [{
        'id': s.id, 'generation': s.generation, 'equity': s.equity, 'cash': s.cash,
        'realized_pnl': s.realized_pnl, 'unrealized_pnl': s.unrealized_pnl,
        'modules': s.modules_json, 'created_at': s.created_at.isoformat() if s.created_at else None,
    } for s in snapshots]

    audits = PortfolioAudit.query.filter_by(user_id=user_id).order_by(PortfolioAudit.created_at.asc()).all()
    audits_data = [{
        'id': a.id, 'generation': a.generation, 'status': a.status, 'provider': a.provider,
        'model': a.model, 'content': a.content, 'evidence': a.evidence_json,
        'created_at': a.created_at.isoformat() if a.created_at else None,
    } for a in audits]

    logs = PortfolioEngineLog.query.filter_by(user_id=user_id).order_by(PortfolioEngineLog.created_at.asc()).all()
    logs_data = [{
        'id': lg.id, 'level': lg.level, 'event_type': lg.event_type, 'message': lg.message,
        'details': lg.details_json, 'created_at': lg.created_at.isoformat() if lg.created_at else None,
    } for lg in logs]

    config_data = {
        'total_bankroll': cfg.total_bankroll,
        'target_annual_return': cfg.target_annual_return,
        'allocations': json.loads(cfg.allocations_json) if cfg.allocations_json else {},
        'watchlists': json.loads(cfg.watchlists_json) if cfg.watchlists_json else {},
        'module_settings': json.loads(cfg.module_settings_json) if cfg.module_settings_json else {},
        'mode': cfg.mode, 'enabled': cfg.enabled,
        'account': {
            'initial_balance': acc.initial_balance, 'cash_balance': acc.cash_balance,
            'total_equity': acc.total_equity, 'reset_at': acc.reset_at.isoformat() if acc.reset_at else None,
        }
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('orders.json', json.dumps(orders_data, indent=2))
        zf.writestr('positions.json', json.dumps(pos_data, indent=2))
        zf.writestr('lots.json', json.dumps(lots_data, indent=2))
        zf.writestr('snapshots.json', json.dumps(snaps_data, indent=2))
        zf.writestr('audits.json', json.dumps(audits_data, indent=2))
        zf.writestr('logs.json', json.dumps(logs_data, indent=2))
        zf.writestr('config.json', json.dumps(config_data, indent=2))

    buf.seek(0)
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f'quant_portfolio_backup_{ts}.zip'
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=filename)


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
            validate_master_ai_config(new_ai)
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


def test_provider_api(provider: str, api_key: str, model: str = None, reasoning_level: str = None):
    """Test connection to an AI provider with the supplied API key and model."""
    provider = str(provider or "").strip().lower()
    import requests

    if provider == "ollama":
        try:
            from services.ai_service import get_ollama_models
            test_model = model or "gpt-oss:120b-cloud"
            available_models = get_ollama_models(timeout=10)
            if test_model not in available_models:
                return jsonify({
                    "success": False,
                    "message": f"Ollama model is not available ({test_model})",
                }), 400
            return jsonify({
                "success": True,
                "message": f"Ollama service and model available ({test_model})",
            })
        except Exception as exc:
            return jsonify({"success": False, "message": f"Ollama error: {exc}"}), 400

    if not api_key:
        return jsonify({"success": False, "message": f"API key is required for {provider.upper()}"}), 400

    if provider == "gemini":
        try:
            test_model = model or "gemini-2.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{test_model}"
            r = requests.get(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                timeout=10,
            )
            if r.status_code == 200:
                return jsonify({"success": True, "message": f"Gemini credentials and model verified ({test_model}). Generation was not tested."})
            try:
                err_data = r.json()
                err_msg = err_data.get("error", {}).get("message") or r.text
            except Exception:
                err_msg = r.text
            return jsonify({"success": False, "message": f"Gemini error ({r.status_code}): {err_msg}"}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Gemini error: {e}"}), 400

    elif provider == "openai":
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, timeout=15.0)
            test_model = model or "gpt-5.4-mini"
            resp = client.chat.completions.create(
                model=test_model,
                messages=[{"role": "user", "content": "ping"}],
                max_completion_tokens=5
            )
            return jsonify({"success": True, "message": f"OpenAI connection OK ({test_model})"})
        except Exception as e:
            return jsonify({"success": False, "message": f"OpenAI error: {e}"}), 400

    elif provider == "zai":
        try:
            from zai_client import ZAIClient
            client = ZAIClient(api_key)
            test_model = model or "glm-4.5-flash"
            resp = client.chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                model=test_model,
                max_tokens=5
            )
            if resp.get("success"):
                return jsonify({"success": True, "message": f"Z.AI connection OK ({test_model})"})
            else:
                return jsonify({"success": False, "message": f"Z.AI error: {resp.get('error')}"}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Z.AI error: {e}"}), 400

    elif provider == "perplexity":
        try:
            test_model = model or "sonar"
            r = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": test_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                timeout=20
            )
            if r.status_code == 200:
                return jsonify({"success": True, "message": f"Perplexity connection OK ({test_model})"})
            return jsonify({"success": False, "message": f"Perplexity error ({r.status_code}): {r.text}"}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Perplexity error: {e}"}), 400

    elif provider == "inception":
        try:
            test_model = model or "mercury-2"
            r = requests.post(
                "https://api.inceptionlabs.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": test_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                timeout=20
            )
            if r.status_code == 200:
                return jsonify({"success": True, "message": f"Inception Labs connection OK ({test_model})"})
            return jsonify({"success": False, "message": f"Inception Labs error ({r.status_code}): {r.text}"}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Inception Labs error: {e}"}), 400

    else:
        return jsonify({"success": False, "message": f"Unsupported provider: {provider}"}), 400


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
            from credentials import Credential
            cred = Credential.query.filter_by(user_id=current_user.id).first()
            if cred and provider != "ollama":
                api_key = (
                    decrypt_secret(getattr(cred, f"_{provider}_key", None)) or
                    decrypt_secret(getattr(cred, f"{provider}_key", None))
                )

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
        acct_id, acct_name = _quant_account_mapping(r.instrument_type, r.module_name)
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
            'account_id': acct_id,
            'account_name': acct_name,
            'created_at': r.created_at.isoformat() + 'Z' if r.created_at else None,
        })
    return jsonify(success=True, orders=orders, total=len(orders))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/positions', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_positions():
    status = engine.portfolio_status(current_user.id)
    positions = []
    for p in status.get('positions', []):
        acct_id, acct_name = _quant_account_mapping(p.get('instrument_type'), p.get('module'))
        positions.append({
            'id': f"QUANT_POS_{p['id']}",
            'symbol': p['symbol'],
            'instrument_type': p.get('instrument_type', 'EQUITY'),
            'module': p.get('module'),
            'side': p.get('side', 'LONG'),
            'quantity': p.get('quantity', 0),
            'cost_price': p.get('average_cost', 0),
            'last_price': p.get('mark', 0),
            'market_value': p.get('market_value_usd'),
            'cost_basis': p.get('collateral'),
            'contract_multiplier': p.get('contract_multiplier'),
            'purchased_outcome': p.get('purchased_outcome'),
            'settlement': p.get('settlement', {}),
            'unrealized_profit_loss': p.get('unrealized_pnl', 0),
            'collateral': p.get('collateral', 0),
            'stop_price': p.get('stop'),
            'target_price': p.get('target'),
            'details': p.get('details', {}),
            'is_paper': True,
            'is_quant': True,
            'account_id': acct_id,
            'account_name': acct_name,
            'source': 'webull_quant',
            'updated_at': p.get('marked_at'),
        })
    from services.position_metadata import enrich_event_positions
    enrich_event_positions(current_user.id, positions)
    return jsonify(success=True, positions=positions, total=len(positions))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/account-summary', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_account_summary():
    status = engine.portfolio_status(current_user.id)
    acc = status.get('account', {})
    perf = status.get('performance', {})
    summary = {
        'account_id': 'QUANT_ACC_INDIVIDUAL_CASH',
        'account_name': 'Quantitative Strategy Engine Portfolio',
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
        'accounts': status.get('sub_accounts', []),
        'is_paper': True,
        'is_quant': True,
    }
    return jsonify(success=True, summary=summary)
