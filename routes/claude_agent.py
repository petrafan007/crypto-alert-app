"""HTTP surface for the Muse-placed orders channel (v4.19.15).

Two audiences:

- **Settings endpoints** (session login): everything Joseph manages in
  the dedicated Settings tab — master switch, the Muse PIN (set /
  regenerate / TOTP-gated reveal), the auto-generate toggle, the
  per-account switchboard, the agent API key, lockout recovery, and the
  audit list.
- **Agent endpoints** (``X-Claude-Agent-Key`` header): draft / confirm /
  replace / cancel for Muse. The key authenticates the client; the
  spoken PIN, verified server-side per action, authorizes the human.
"""

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from services import claude_agent_service as agent
from services.claude_agent_service import ClaudeAgentError

logger = logging.getLogger(__name__)

claude_agent_bp = Blueprint('claude_agent', __name__)


# ---------------------------------------------------------------------------
# Settings endpoints (session-authenticated)
# ---------------------------------------------------------------------------

def _require_settings_totp(user_id, data):
    """Fresh TOTP gate for credential-grade settings actions, following
    the app's trading-2FA convention (a consumed code authorizes once)."""
    from services.totp_service import consume_totp_code
    from trading_models import TradingSettings
    settings = TradingSettings.query.filter_by(user_id=user_id).first()
    if not settings or not settings.totp_secret:
        return 'Set up two-factor authentication in Settings before managing the Muse PIN.'
    code = (data or {}).get('two_factor_code') or (data or {}).get('twofa_code')
    if not code:
        return 'Enter your six-digit two-factor code.'
    try:
        if consume_totp_code(settings, code):
            return None
    except Exception:
        logger.exception('TOTP verification failed for Muse PIN settings')
    return 'That two-factor code was not accepted.'


@claude_agent_bp.route('/api/claude-agent/config', methods=['GET'])
@login_required
def get_claude_agent_config():
    config = agent.get_or_create_config(current_user.id)
    return jsonify({'success': True, 'config': agent.config_status(config)})


@claude_agent_bp.route('/api/claude-agent/config', methods=['PUT'])
@login_required
def update_claude_agent_config():
    data = request.get_json(silent=True) or {}
    config = agent.get_or_create_config(current_user.id)
    # Turning the channel ON and clearing a lockout are security-grade
    # changes: both require a fresh two-factor code.
    if data.get('enabled') is True and not config.enabled:
        error = _require_settings_totp(current_user.id, data)
        if error:
            return jsonify({'success': False, 'error': error, 'requires_2fa': True}), 403
    if data.get('unlock'):
        error = _require_settings_totp(current_user.id, data)
        if error:
            return jsonify({'success': False, 'error': error, 'requires_2fa': True}), 403
        config.locked = False
        config.failed_attempts = 0
    if 'enabled' in data:
        config.enabled = bool(data['enabled'])
    if 'auto_generate_enabled' in data:
        config.auto_generate_enabled = bool(data['auto_generate_enabled'])
    if 'disabled_accounts' in data:
        agent.set_disabled_accounts(config, data['disabled_accounts'])
    from core.extensions import db
    db.session.commit()
    return jsonify({'success': True, 'config': agent.config_status(config)})


@claude_agent_bp.route('/api/claude-agent/pin', methods=['POST'])
@login_required
def set_claude_pin():
    data = request.get_json(silent=True) or {}
    error = _require_settings_totp(current_user.id, data)
    if error:
        return jsonify({'success': False, 'error': error, 'requires_2fa': True}), 403
    config = agent.get_or_create_config(current_user.id)
    try:
        agent.set_pin(config, data.get('pin'))
    except ClaudeAgentError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    return jsonify({'success': True, 'config': agent.config_status(config)})


@claude_agent_bp.route('/api/claude-agent/pin/regenerate', methods=['POST'])
@login_required
def regenerate_claude_pin():
    data = request.get_json(silent=True) or {}
    error = _require_settings_totp(current_user.id, data)
    if error:
        return jsonify({'success': False, 'error': error, 'requires_2fa': True}), 403
    config = agent.get_or_create_config(current_user.id)
    agent.generate_new_pin(config)
    # The generated PIN is never returned here; it is viewable only
    # through the TOTP-gated reveal.
    return jsonify({'success': True, 'config': agent.config_status(config)})


@claude_agent_bp.route('/api/claude-agent/pin/reveal', methods=['POST'])
@login_required
def reveal_claude_pin():
    data = request.get_json(silent=True) or {}
    error = _require_settings_totp(current_user.id, data)
    if error:
        return jsonify({'success': False, 'error': error, 'requires_2fa': True}), 403
    config = agent.get_or_create_config(current_user.id)
    try:
        pin = agent.reveal_pin(config)
    except ClaudeAgentError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    return jsonify({'success': True, 'pin': pin})


@claude_agent_bp.route('/api/claude-agent/agent-key', methods=['POST'])
@login_required
def generate_claude_agent_key():
    data = request.get_json(silent=True) or {}
    error = _require_settings_totp(current_user.id, data)
    if error:
        return jsonify({'success': False, 'error': error, 'requires_2fa': True}), 403
    config = agent.get_or_create_config(current_user.id)
    key = agent.generate_agent_key(config)
    return jsonify({'success': True, 'agent_key': key,
                    'config': agent.config_status(config)})


@claude_agent_bp.route('/api/claude-agent/audit', methods=['GET'])
@login_required
def get_claude_agent_audit():
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    return jsonify({'success': True, 'audit': agent.list_audit(current_user.id, limit)})


# ---------------------------------------------------------------------------
# Agent endpoints (API-key authenticated)
# ---------------------------------------------------------------------------

def _agent_config_or_401():
    key = request.headers.get('X-Claude-Agent-Key') or ''
    config = agent.find_config_by_agent_key(key)
    if config is None:
        return None, (jsonify({'success': False, 'error': 'Invalid or missing agent API key.'}), 401)
    return config, None


@claude_agent_bp.route('/api/claude-agent/drafts', methods=['POST'])
def create_agent_draft():
    config, error_response = _agent_config_or_401()
    if error_response:
        return error_response
    data = request.get_json(silent=True) or {}
    try:
        draft = agent.create_draft(
            config, data.get('kind'), data.get('spec') or {},
            request_text=data.get('request_text'))
    except ClaudeAgentError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    return jsonify({'success': True, 'draft': draft.to_dict()}), 201


@claude_agent_bp.route('/api/claude-agent/drafts/<draft_id>/confirm', methods=['POST'])
def confirm_agent_draft(draft_id):
    config, error_response = _agent_config_or_401()
    if error_response:
        return error_response
    data = request.get_json(silent=True) or {}
    try:
        draft, outcome = agent.confirm_draft(
            config, draft_id, data.get('pin'),
            request_text=data.get('request_text'))
    except ClaudeAgentError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    return jsonify({'success': True, 'draft': draft.to_dict(),
                    'result': outcome.get('result'),
                    'broker_order_id': outcome.get('broker_order_id'),
                    'ladder_order_id': outcome.get('ladder_order_id')})


@claude_agent_bp.route('/api/claude-agent/replace', methods=['POST'])
def replace_agent_order():
    config, error_response = _agent_config_or_401()
    if error_response:
        return error_response
    data = request.get_json(silent=True) or {}
    if not data.get('order_id'):
        return jsonify({'success': False, 'error': 'order_id is required.'}), 400
    try:
        outcome = agent.replace_order(
            config, data['order_id'], data.get('kind'), data.get('spec') or {},
            data.get('pin'), request_text=data.get('request_text'))
    except ClaudeAgentError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    return jsonify({'success': True, 'result': outcome.get('result'),
                    'broker_order_id': outcome.get('broker_order_id'),
                    'ladder_order_id': outcome.get('ladder_order_id')})


@claude_agent_bp.route('/api/claude-agent/cancel', methods=['POST'])
def cancel_agent_order():
    config, error_response = _agent_config_or_401()
    if error_response:
        return error_response
    data = request.get_json(silent=True) or {}
    if not data.get('order_id'):
        return jsonify({'success': False, 'error': 'order_id is required.'}), 400
    hints = {field: data.get(field) for field in
             ('symbol', 'broker', 'account_id', 'test_mode') if data.get(field) is not None}
    try:
        result = agent.cancel_order(
            config, data['order_id'], data.get('pin'), hints=hints,
            request_text=data.get('request_text'))
    except ClaudeAgentError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    return jsonify({'success': True, 'result': result})
