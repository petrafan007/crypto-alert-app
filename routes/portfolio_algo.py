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
    return jsonify(success=True, audit=engine.run_audit(current_user.id, prompt=prompt))


@portfolio_algo_bp.route('/api/webull/portfolio-algo/audits', methods=['GET'])
@portfolio_admin_required
def portfolio_algo_audits():
    rows = engine.Audit.query.filter_by(user_id=current_user.id).order_by(engine.Audit.id.desc()).limit(50).all()
    return jsonify(success=True, audits=[engine.audit_dict(row) for row in rows])
