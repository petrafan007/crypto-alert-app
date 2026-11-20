"""Muse-placed orders: spoken-PIN authorization channel (v4.19.15).

Muse (the assistant) can place, replace, and cancel orders on a user's
behalf. Two separate secrets guard the channel:

- an **agent API key** (SHA-256 hashed at rest) authenticates Muse as a
  client of the agent endpoints;
- a **six-digit PIN** authorizes the human per action. The PIN is stored
  Fernet-encrypted with the app's existing credential encryption
  (``credential_security``) because it must be revealable in Settings
  behind a fresh TOTP check; verification decrypts server-side and
  compares in constant time. A PIN is valid for at most 30 days.

Execution always goes through the same service-layer functions the UI
routes use — ``place_webull_order``, ``create_ladder_order``,
``create_conditional``, ``create_trailing_order``, the Binance spot
placement helpers, ``staking_purchase_service.purchase``, and
``cancel_any_order`` for cancels/replaces — with the PIN check standing
in for the TOTP check on this path only. There are no amount caps and no
order-type restrictions; a per-account switchboard in Settings can
disable individual accounts for this channel.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta

from claude_agent_models import ClaudeAgentConfig, ClaudeOrderAudit, ClaudeOrderDraft
from core.extensions import db
from credential_security import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

PIN_PATTERN = re.compile(r'^[0-9]{6}$')
PIN_VALIDITY_DAYS = 30
DRAFT_TTL_MINUTES = 5
MAX_FAILED_ATTEMPTS = 3
SOURCE_MARKER = 'CLAUDE_AGENT'
BINANCE_ACCOUNT_KEY = 'binance:US'

ORDER_KINDS = frozenset({
    'webull_native', 'synthetic_ladder', 'synthetic_conditional',
    'trailing', 'binance_spot', 'binance_staking',
})

# Keyword arguments place_webull_order accepts beyond credentials/account.
WEBULL_ORDER_FIELDS = (
    'symbol', 'instrument_type', 'side', 'order_type', 'quantity',
    'limit_price', 'stop_price', 'time_in_force', 'support_trading_session',
    'client_order_id', 'option_type', 'option_strike', 'option_expiration',
    'option_underlying_symbol', 'option_strategy', 'option_legs',
    'trailing_type', 'trailing_stop_step', 'entrust_type', 'total_cash_amount',
    'algo_type', 'algo_start_time', 'algo_end_time', 'max_target_percent',
    'target_vol_percent', 'combo_type', 'client_combo_order_id',
    'combo_orders', 'bracket_take_profit_price', 'bracket_stop_loss_price',
    'bracket_stop_loss_limit_price', 'event_outcome', 'event_market',
)


class ClaudeAgentError(Exception):
    """A refusal from the agent channel with a user-safe message."""


# ---------------------------------------------------------------------------
# Config, PIN lifecycle, agent key, account switchboard
# ---------------------------------------------------------------------------

def get_or_create_config(user_id):
    config = ClaudeAgentConfig.query.filter_by(user_id=user_id).first()
    if config is None:
        config = ClaudeAgentConfig(user_id=user_id)
        db.session.add(config)
        db.session.commit()
    return config


def _pin_expired(config, now=None):
    if not config.pin_encrypted or not config.pin_expires_at:
        return False
    return (now or datetime.utcnow()) >= config.pin_expires_at


def _store_new_pin(config, pin, now=None):
    now = now or datetime.utcnow()
    config.pin_encrypted = encrypt_secret(pin)
    config.pin_set_at = now
    config.pin_expires_at = now + timedelta(days=PIN_VALIDITY_DAYS)


def generate_new_pin(config):
    """Generate a fresh PIN. The generated value is deliberately never
    returned — it is viewable only through the TOTP-gated reveal flow."""
    pin = f'{secrets.randbelow(1000000):06d}'
    _store_new_pin(config, pin)
    db.session.commit()


def refresh_pin_lifecycle(config, now=None):
    """Auto-generate a replacement when the stored PIN has expired and
    the auto-generate toggle is on. Returns True when a PIN was rotated."""
    now = now or datetime.utcnow()
    if config.pin_encrypted and _pin_expired(config, now) and config.auto_generate_enabled:
        generate_new_pin(config)
        return True
    return False


def set_pin(config, pin):
    pin = str(pin or '').strip()
    if not PIN_PATTERN.fullmatch(pin):
        raise ClaudeAgentError('The Muse PIN must be exactly six digits.')
    _store_new_pin(config, pin)
    db.session.commit()


def pin_is_active(config, now=None):
    return bool(config.pin_encrypted) and not _pin_expired(config, now)


def reveal_pin(config):
    refresh_pin_lifecycle(config)
    if not config.pin_encrypted:
        raise ClaudeAgentError('No Muse PIN is set yet.')
    if _pin_expired(config):
        raise ClaudeAgentError('The Muse PIN has expired. Set a new one to continue.')
    pin = decrypt_secret(config.pin_encrypted)
    if not pin:
        raise ClaudeAgentError('The stored Muse PIN could not be read.')
    return pin


def _register_failure(config):
    config.failed_attempts = (config.failed_attempts or 0) + 1
    if config.failed_attempts >= MAX_FAILED_ATTEMPTS:
        config.locked = True


def verify_pin(config, pin):
    """Constant-time PIN verification with lockout accounting.

    Any mismatch — wrong digits, an expired PIN, or no PIN at all —
    counts toward the lockout. A success resets the counter.
    """
    if config.locked:
        return False
    candidate = str(pin or '').strip()
    stored = decrypt_secret(config.pin_encrypted) if pin_is_active(config) else None
    ok = bool(stored) and bool(candidate) and hmac.compare_digest(stored, candidate)
    if ok:
        config.failed_attempts = 0
    else:
        _register_failure(config)
    db.session.commit()
    return ok


def generate_agent_key(config):
    """Return a new agent API key (shown once); only its hash is stored."""
    key = 'claude_' + secrets.token_urlsafe(32)
    config.agent_key_hash = hashlib.sha256(key.encode('utf-8')).hexdigest()
    db.session.commit()
    return key


def find_config_by_agent_key(key):
    if not key:
        return None
    digest = hashlib.sha256(str(key).encode('utf-8')).hexdigest()
    config = ClaudeAgentConfig.query.filter_by(agent_key_hash=digest).first()
    if config is None or not hmac.compare_digest(config.agent_key_hash or '', digest):
        return None
    return config


def disabled_accounts(config):
    try:
        values = json.loads(config.disabled_accounts_json or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    return [str(v) for v in values]


def set_disabled_accounts(config, values):
    cleaned = sorted({str(v).strip() for v in (values or []) if str(v).strip()})
    config.disabled_accounts_json = json.dumps(cleaned)
    db.session.commit()
    return cleaned


def broker_for(kind, spec):
    spec = spec or {}
    if kind == 'webull_native':
        return 'webull'
    if kind in ('synthetic_ladder', 'synthetic_conditional', 'trailing'):
        return str(spec.get('broker', 'binance')).lower()
    return 'binance'


def resolve_environment(user_id, kind, spec):
    """Derive 'real' or 'paper' from the target account's mode, mirroring
    how the UI routes resolve test mode (an explicit spec test_mode wins;
    otherwise the persisted per-platform test-mode setting decides). The
    environment is recorded on the draft and named in the read-back; the
    single Muse PIN verifies for either environment."""
    spec = spec or {}
    broker = broker_for(kind, spec)
    if kind == 'webull_native':
        account_id = str(spec.get('account_id') or '')
        if spec.get('test_mode') is True or account_id == 'TEST_PAPER_ACCOUNT' \
                or account_id.startswith(('SIM_', 'TEST_')):
            return 'paper'
        from credentials import UserSetting
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        if bool(getattr(setting, 'webull_test_mode_enabled', False)):
            return 'paper'
        return 'real'
    if kind in ('synthetic_ladder', 'synthetic_conditional', 'trailing'):
        if isinstance(spec.get('test_mode'), bool):
            return 'paper' if spec['test_mode'] else 'real'
        if broker == 'webull':
            from credentials import UserSetting
            setting = UserSetting.query.filter_by(user_id=user_id).first()
            return 'paper' if bool(getattr(setting, 'webull_test_mode_enabled', False)) else 'real'
        from trading_models import TradingSettings
        settings = TradingSettings.query.filter_by(user_id=user_id).first()
        return 'paper' if (settings.test_mode_enabled if settings else True) else 'real'
    if kind == 'binance_spot':
        from trading_models import TradingSettings
        settings = TradingSettings.query.filter_by(user_id=user_id).first()
        return 'paper' if (settings.test_mode_enabled if settings else True) else 'real'
    # binance_staking: the staking purchase path is real-only in the app.
    return 'real'


def account_key_for(kind, spec):
    if broker_for(kind, spec) == 'webull':
        return f"webull:{(spec or {}).get('account_id') or ''}"
    return BINANCE_ACCOUNT_KEY


def require_account_enabled(config, kind, spec):
    key = account_key_for(kind, spec)
    if key in disabled_accounts(config):
        raise ClaudeAgentError(
            f'Agent orders are switched off for account {key} in Settings.')
    return key


def config_status(config):
    refresh_pin_lifecycle(config)
    now = datetime.utcnow()
    return {
        'enabled': bool(config.enabled),
        'pin_set': bool(config.pin_encrypted),
        'pin_expired': _pin_expired(config, now),
        'pin_set_at': config.pin_set_at.isoformat() if config.pin_set_at else None,
        'pin_expires_at': config.pin_expires_at.isoformat() if config.pin_expires_at else None,
        'auto_generate_enabled': bool(config.auto_generate_enabled),
        'agent_key_set': bool(config.agent_key_hash),
        'locked': bool(config.locked),
        'failed_attempts': config.failed_attempts or 0,
        'disabled_accounts': disabled_accounts(config),
    }


# ---------------------------------------------------------------------------
# Gates shared by every agent action
# ---------------------------------------------------------------------------

def _gate(config):
    if not config.enabled:
        raise ClaudeAgentError('The Muse orders feature is off in Settings.')
    if config.locked:
        raise ClaudeAgentError(
            'The Muse orders channel is locked after failed PIN attempts. '
            'Re-enable it in Settings.')
    refresh_pin_lifecycle(config)
    if not config.pin_encrypted:
        raise ClaudeAgentError('No Muse PIN is set in Settings.')
    if _pin_expired(config):
        raise ClaudeAgentError('The Muse PIN has expired. Set a new one in Settings.')


def _verify_or_raise(config, pin):
    if not verify_pin(config, pin):
        if config.locked:
            raise ClaudeAgentError(
                'Incorrect PIN. The Muse orders channel is now locked; '
                're-enable it in Settings.')
        raise ClaudeAgentError('Incorrect PIN.')


# ---------------------------------------------------------------------------
# Read-back + drafts
# ---------------------------------------------------------------------------

def build_readback(kind, spec, environment='real'):
    spec = spec or {}
    broker = broker_for(kind, spec)
    symbol = spec.get('symbol') or spec.get('asset')
    side = spec.get('side')
    quantity = spec.get('quantity') or spec.get('total_quantity') or spec.get('quoteAmount')
    order_type = spec.get('order_type') or spec.get('type') or (
        'STAKING PURCHASE' if kind == 'binance_staking' else None)
    limit_price = spec.get('limit_price') or spec.get('price')
    parts = []
    if side:
        parts.append(str(side).upper())
    if quantity:
        parts.append(str(quantity))
    if symbol:
        parts.append(str(symbol).upper())
    if order_type:
        parts.append(str(order_type).upper())
    if limit_price:
        parts.append(f'@ {limit_price}')
    summary = ' '.join(parts) if parts else kind
    account_label = spec.get('account_id') or ('Binance US' if broker == 'binance' else None)
    if account_label:
        summary += f' · account {account_label}'
    summary += ' · PAPER account' if environment == 'paper' else ' · REAL account'
    return {
        'kind': kind,
        'environment': environment,
        'broker': broker,
        'account_id': spec.get('account_id'),
        'symbol': symbol,
        'side': side,
        'order_type': order_type,
        'quantity': quantity,
        'limit_price': limit_price,
        'stop_price': spec.get('stop_price') or spec.get('stopPrice'),
        'time_in_force': spec.get('time_in_force'),
        'trading_session': spec.get('trading_session') or spec.get('support_trading_session'),
        'test_mode': bool(spec.get('test_mode', False)),
        'summary': summary,
    }


def create_draft(config, kind, spec, request_text=None):
    _gate(config)
    kind = str(kind or '').strip()
    if kind not in ORDER_KINDS:
        raise ClaudeAgentError(f'Unsupported order kind: {kind}')
    spec = dict(spec or {})
    if broker_for(kind, spec) == 'webull' and not spec.get('account_id'):
        raise ClaudeAgentError('A Webull account_id is required for this order.')
    require_account_enabled(config, kind, spec)
    if kind == 'binance_staking' and not spec.get('id'):
        # The staking purchase service is idempotent on this intent id.
        spec['id'] = str(uuid.uuid4())
    environment = resolve_environment(config.user_id, kind, spec)
    if kind != 'binance_staking':
        # Pin the resolved mode into the stored spec so confirmation
        # executes exactly the environment the read-back named.
        spec['test_mode'] = environment == 'paper'
    now = datetime.utcnow()
    draft = ClaudeOrderDraft(
        id=uuid.uuid4().hex,
        user_id=config.user_id,
        kind=kind,
        environment=environment,
        spec_json=json.dumps(spec, default=str),
        readback_json=json.dumps(build_readback(kind, spec, environment), default=str),
        status='PENDING',
        created_at=now,
        expires_at=now + timedelta(minutes=DRAFT_TTL_MINUTES),
    )
    db.session.add(draft)
    db.session.commit()
    return draft


def confirm_draft(config, draft_id, pin, request_text=None):
    _gate(config)
    draft = ClaudeOrderDraft.query.filter_by(id=draft_id, user_id=config.user_id).first()
    if draft is None:
        raise ClaudeAgentError('Draft not found.')
    if draft.status != 'PENDING':
        raise ClaudeAgentError(
            f'This draft is {draft.status.lower()} and can no longer be confirmed.')
    if datetime.utcnow() >= draft.expires_at:
        draft.status = 'EXPIRED'
        db.session.commit()
        raise ClaudeAgentError('This draft has expired. Ask Muse to create a new one.')
    _verify_or_raise(config, pin)
    spec = json.loads(draft.spec_json)
    require_account_enabled(config, draft.kind, spec)
    try:
        outcome = _execute_place(config.user_id, draft.kind, spec)
    except Exception as exc:
        db.session.rollback()
        _write_audit(config.user_id, 'place', draft=draft, spec=spec,
                     status='FAILED', message=str(exc), request_text=request_text)
        raise ClaudeAgentError(str(exc))
    draft.status = 'CONFIRMED'
    draft.confirmed_at = datetime.utcnow()
    draft.result_json = json.dumps(outcome.get('result'), default=str)
    db.session.commit()
    _write_audit(config.user_id, 'place', draft=draft, spec=spec, status='SUCCESS',
                 broker_order_id=outcome.get('broker_order_id'),
                 ladder_order_id=outcome.get('ladder_order_id'),
                 request_text=request_text)
    return draft, outcome


def replace_order(config, order_id, kind, spec, pin, request_text=None):
    _gate(config)
    kind = str(kind or '').strip()
    if kind not in ORDER_KINDS:
        raise ClaudeAgentError(f'Unsupported order kind: {kind}')
    spec = dict(spec or {})
    _verify_or_raise(config, pin)
    require_account_enabled(config, kind, spec)
    environment = resolve_environment(config.user_id, kind, spec)
    if kind != 'binance_staking':
        spec['test_mode'] = environment == 'paper'
    try:
        if kind in ('synthetic_ladder', 'synthetic_conditional', 'trailing'):
            # Synthetic replaces ride the create path with replacing_order_id,
            # exactly like the UI routes (cancel-first inside the executor).
            spec['replacing_order_id'] = order_id
            outcome = _execute_place(config.user_id, kind, spec)
        else:
            _execute_cancel(config.user_id, order_id, {
                'symbol': spec.get('symbol'),
                'broker': broker_for(kind, spec),
                'account_id': spec.get('account_id'),
                'test_mode': spec.get('test_mode'),
            })
            outcome = _execute_place(config.user_id, kind, spec)
    except Exception as exc:
        db.session.rollback()
        _write_audit(config.user_id, 'replace', kind=kind, spec=spec,
                     status='FAILED', message=str(exc), request_text=request_text,
                     environment=environment)
        raise ClaudeAgentError(str(exc))
    _write_audit(config.user_id, 'replace', kind=kind, spec=spec, status='SUCCESS',
                 broker_order_id=outcome.get('broker_order_id'),
                 ladder_order_id=outcome.get('ladder_order_id'),
                 request_text=request_text, environment=environment)
    return outcome


def cancel_order(config, order_id, pin, hints=None, request_text=None):
    _gate(config)
    _verify_or_raise(config, pin)
    hints = dict(hints or {})
    if hints.get('account_id'):
        key = f"webull:{hints['account_id']}"
        if key in disabled_accounts(config):
            raise ClaudeAgentError(
                f'Agent orders are switched off for account {key} in Settings.')
    try:
        result = _execute_cancel(config.user_id, order_id, hints)
    except Exception as exc:
        db.session.rollback()
        _write_audit(config.user_id, 'cancel', spec=hints,
                     status='FAILED', message=str(exc), request_text=request_text)
        raise ClaudeAgentError(str(exc))
    _write_audit(config.user_id, 'cancel', spec=hints, status='SUCCESS',
                 message=f"Cancelled order {order_id}.", request_text=request_text)
    return result


def _write_audit(user_id, action, *, draft=None, kind=None, spec=None, status='SUCCESS',
                 message=None, broker_order_id=None, ladder_order_id=None,
                 request_text=None, environment=None):
    spec = spec or {}
    kind = kind or (draft.kind if draft else None)
    row = ClaudeOrderAudit(
        user_id=user_id,
        action=action,
        draft_id=draft.id if draft else None,
        kind=kind,
        environment=environment or (draft.environment if draft else None),
        broker=broker_for(kind, spec) if kind else spec.get('broker'),
        account_id=spec.get('account_id'),
        symbol=spec.get('symbol') or spec.get('asset'),
        spec_json=json.dumps(spec, default=str) if spec else None,
        request_text=request_text,
        result_status=status,
        message=message,
        broker_order_id=str(broker_order_id) if broker_order_id else None,
        ladder_order_id=ladder_order_id,
    )
    db.session.add(row)
    db.session.commit()
    return row


def list_audit(user_id, limit=50):
    rows = (ClaudeOrderAudit.query.filter_by(user_id=user_id)
            .order_by(ClaudeOrderAudit.id.desc()).limit(limit).all())
    return [row.to_dict() for row in rows]


# ---------------------------------------------------------------------------
# Execution — the same service-layer functions the UI routes use
# ---------------------------------------------------------------------------

def _execute_place(user_id, kind, spec):
    if kind == 'webull_native':
        return _execute_webull_native(user_id, spec)
    if kind == 'synthetic_ladder':
        return _execute_synthetic_ladder(user_id, spec)
    if kind == 'synthetic_conditional':
        return _execute_synthetic_conditional(user_id, spec)
    if kind == 'trailing':
        return _execute_trailing(user_id, spec)
    if kind == 'binance_spot':
        return _execute_binance_spot(user_id, spec)
    if kind == 'binance_staking':
        return _execute_binance_staking(user_id, spec)
    raise ClaudeAgentError(f'Unsupported order kind: {kind}')


def _execute_cancel(user_id, order_id, hints):
    from services.order_replacement_service import cancel_any_order
    hints = hints or {}
    res = cancel_any_order(
        replacing_order_id=order_id,
        user_id=user_id,
        symbol=hints.get('symbol'),
        test_mode=hints.get('test_mode'),
        broker=hints.get('broker'),
        account_id=hints.get('account_id'),
    )
    if not res or not res.get('success'):
        raise ClaudeAgentError((res or {}).get('error') or f'Could not cancel order {order_id}.')
    return res


def _cancel_for_replace(user_id, spec, test_mode):
    """Cancel the original before creating its replacement (the UI's
    synthetic replace semantics); a failed cancel aborts the replace."""
    res = _execute_cancel(user_id, spec['replacing_order_id'], {
        'symbol': spec.get('symbol'),
        'test_mode': test_mode,
        'broker': spec.get('broker', 'binance'),
        'account_id': spec.get('account_id'),
    })
    return res


def _mark_source(model, row_id, user_id):
    if not row_id:
        return
    row = model.query.filter_by(id=row_id, user_id=user_id).first()
    if row is not None:
        row.source = SOURCE_MARKER
        db.session.commit()


def _execute_webull_native(user_id, spec):
    if spec.get('test_mode'):
        return _execute_webull_paper(user_id, spec)
    from credentials import Credential, UserSetting
    from services.webull_service import normalize_webull_environment, place_webull_order

    setting = UserSetting.query.filter_by(user_id=user_id).first()
    credential = Credential.query.filter_by(user_id=user_id).first()
    environment = normalize_webull_environment(
        getattr(setting, 'webull_environment', None) or 'production')
    if (not credential or not credential.webull_app_key
            or not credential.webull_app_secret
            or credential.webull_token_status != 'NORMAL'
            or credential.webull_token_environment != environment
            or not credential.webull_access_token):
        raise ClaudeAgentError('Webull is not connected for this account.')
    account_id = spec.get('account_id')
    kwargs = {field: spec[field] for field in WEBULL_ORDER_FIELDS
              if spec.get(field) is not None}
    result = place_webull_order(
        credential.webull_app_key, credential.webull_app_secret,
        environment, credential.webull_access_token,
        account_id=account_id, **kwargs)
    order_id = result.get('order_id') or result.get('client_order_id')
    if order_id:
        # Best effort: the ledger row may only appear after the next order
        # sync; the audit row is the authoritative Muse-placed marker.
        from models import WebullOrder
        row = WebullOrder.query.filter_by(
            user_id=user_id, account_id=str(account_id),
            provider_order_id=str(order_id)).first()
        if row is not None:
            row.source = SOURCE_MARKER
            db.session.commit()
    return {'broker_order_id': str(order_id) if order_id else None, 'result': result}


def _execute_synthetic_ladder(user_id, spec):
    from services.ladder_order_service import create_ladder_order

    test_mode = bool(spec.get('test_mode', False))
    replacing = spec.get('replacing_order_id')
    # Mirror the ladder route: a Webull BUY replacing a synthetic parent
    # defers its cancel until the new order is validated (before_persist);
    # every other replace cancels first.
    defer_cancel = (str(spec.get('broker', 'binance')).lower() == 'webull'
                    and str(spec.get('side') or '').upper() == 'BUY'
                    and str(replacing or '').startswith(('ladder_', 'trail_')))

    def cancel_original():
        _cancel_for_replace(user_id, spec, test_mode)

    if replacing and not defer_cancel:
        cancel_original()
    if not replacing:
        from services.synthetic_execution_service import check_synthetic_order_capacity
        check_synthetic_order_capacity(
            user_id=user_id, symbol=spec.get('symbol'), side=spec.get('side'),
            quantity=spec.get('total_quantity') or spec.get('quantity'),
            broker=spec.get('broker', 'binance'), test_mode=test_mode,
            account_id=spec.get('account_id'))
    ladder_dict = create_ladder_order(
        user_id=user_id,
        symbol=spec.get('symbol'),
        side=spec.get('side'),
        total_quantity=spec.get('total_quantity') or spec.get('quantity'),
        preset_name=spec.get('preset_name', 'Conservative'),
        custom_rungs=spec.get('custom_rungs', spec.get('rungs')),
        has_stop_loss=bool(spec.get('has_stop_loss', False)),
        stop_loss_trigger_price=spec.get('stop_loss_trigger_price'),
        stop_loss_action=spec.get('stop_loss_action', 'SELL_ALL'),
        broker=spec.get('broker', 'binance'),
        account_id=spec.get('account_id'),
        instrument_type=spec.get('instrument_type', 'CRYPTO'),
        trading_session=spec.get('trading_session', 'CORE'),
        test_mode=test_mode,
        strategy_type=spec.get('strategy_type', 'SYNTHETIC'),
        upside_mode=spec.get('upside_mode', 'LADDER'),
        upside_target_price=spec.get('upside_target_price'),
        upside_trail_value=spec.get('upside_trail_value'),
        upside_trail_type=spec.get('upside_trail_type', 'PERCENT'),
        upside_activation_price=spec.get('upside_activation_price'),
        downside_mode=spec.get('downside_mode', 'NONE'),
        downside_target_price=spec.get('downside_target_price'),
        downside_trail_value=spec.get('downside_trail_value'),
        downside_trail_type=spec.get('downside_trail_type', 'PERCENT'),
        downside_activation_price=spec.get('downside_activation_price'),
        downside_preset=spec.get('downside_preset', 'Aggressive'),
        downside_rungs=spec.get('downside_rungs'),
        limit_cap_pct=spec.get('limit_cap_pct'),
        activate_at=spec.get('activate_at'),
        before_persist=cancel_original if defer_cancel else None,
        quote_budget=spec.get('quote_budget'),
    )
    ladder_id = ladder_dict.get('id') if isinstance(ladder_dict, dict) else None
    if ladder_id:
        from trading_models import LadderOrder
        _mark_source(LadderOrder, ladder_id, user_id)
    return {'ladder_order_id': ladder_id, 'result': ladder_dict}


def _execute_synthetic_conditional(user_id, spec):
    from services.synthetic_conditional_service import create_conditional

    test_mode = bool(spec.get('test_mode', False))
    data = dict(spec)
    data['test_mode'] = test_mode
    if spec.get('replacing_order_id'):
        _cancel_for_replace(user_id, spec, test_mode)
    else:
        from services.synthetic_execution_service import check_synthetic_order_capacity
        check_synthetic_order_capacity(
            user_id, spec.get('symbol'), spec.get('side'),
            spec.get('total_quantity') or spec.get('quantity'),
            spec.get('broker', 'webull'), test_mode,
            account_id=spec.get('account_id'))
    parent = create_conditional(user_id, data)
    parent.source = SOURCE_MARKER
    db.session.commit()
    return {'ladder_order_id': parent.id, 'result': parent.to_dict()}


def _execute_trailing(user_id, spec):
    from services.trailing_order_service import create_trailing_order

    test_mode = bool(spec.get('test_mode', False))
    if spec.get('replacing_order_id'):
        _cancel_for_replace(user_id, spec, test_mode)
    created = create_trailing_order(
        user_id=user_id,
        symbol=spec.get('symbol'),
        side=spec.get('side'),
        quantity=spec.get('quantity') or spec.get('total_quantity'),
        trail_type=spec.get('trail_type', 'PERCENT'),
        trail_value=spec.get('trail_value', 2.0),
        activation_price=spec.get('activation_price'),
        execution_type=spec.get('execution_type', 'MARKET'),
        test_mode=test_mode,
        broker=spec.get('broker', 'binance'),
        account_id=spec.get('account_id'),
        instrument_type=spec.get('instrument_type', 'CRYPTO'),
        trading_session=spec.get('trading_session', 'CORE'),
        limit_cap_pct=spec.get('limit_cap_pct'),
        activate_at=spec.get('activate_at'),
    )
    trailing_id = created.get('id') if isinstance(created, dict) else getattr(created, 'id', None)
    if trailing_id:
        from trading_models import TrailingOrder
        _mark_source(TrailingOrder, trailing_id, user_id)
    result = created if isinstance(created, dict) else (
        created.to_dict() if hasattr(created, 'to_dict') else {'id': trailing_id})
    return {'ladder_order_id': None, 'trailing_order_id': trailing_id, 'result': result}


def _execute_binance_spot(user_id, spec):
    """Mirror of the Binance.US live place-order route's core sequence
    (filters → formatting → build_order_config → create_order → RealOrder),
    with the PIN check upstream standing in for the route's TOTP check.
    Paper drafts route to the test-order mirror instead."""
    if spec.get('test_mode'):
        return _execute_binance_spot_paper(user_id, spec)
    from binance.client import Client

    from credentials import Credential
    from services.binance_service import (
        build_order_config, get_symbol_filters, validate_order_price_collar)
    from services.common import _coerce_float, format_price, format_quantity
    from trading_models import RealOrder, TradingSettings

    settings = TradingSettings.query.filter_by(user_id=user_id).first()
    if not settings or settings.test_mode_enabled:
        raise ClaudeAgentError(
            'Real trading is disabled. Disable test mode in Settings to place '
            'real Binance.US orders.')
    for field in ('symbol', 'side', 'type'):
        if not spec.get(field):
            raise ClaudeAgentError(f'Missing required field: {field}')
    symbol = str(spec['symbol']).upper()
    side = str(spec['side']).upper()
    order_type = str(spec['type']).upper()

    creds = Credential.query.filter_by(user_id=user_id).first()
    if not creds or not creds.trading_api_key or not creds.trading_api_secret:
        raise ClaudeAgentError(
            'No Binance.US trading credentials found. Add them in Settings.')
    client = Client(creds.trading_api_key, creds.trading_api_secret,
                    testnet=False, tld='us')

    filters = get_symbol_filters(client, symbol)
    if not filters:
        raise ClaudeAgentError(
            f'Unable to get trading rules for {symbol}. Check the symbol is valid.')
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        current_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
    except Exception:
        current_price = 0.0

    price = _coerce_float(spec.get('price'), 0.0) or 0.0
    quote_amount = _coerce_float(
        spec.get('quoteQuantity') or spec.get('quote_quantity') or spec.get('quote_amount'))
    quantity = _coerce_float(spec.get('quantity')) or 0.0
    if quantity <= 0 and quote_amount and quote_amount > 0:
        reference_price = price if price > 0 else current_price
        if reference_price and reference_price > 0:
            quantity = quote_amount / reference_price
    if not quantity or quantity <= 0:
        raise ClaudeAgentError('Unable to determine order quantity.')

    formatted_quantity = format_quantity(quantity, filters['stepSize'])
    if formatted_quantity < filters['minQty']:
        raise ClaudeAgentError(
            f"Quantity too small. Minimum quantity for {symbol} is {filters['minQty']}.")
    if formatted_quantity > filters['maxQty']:
        raise ClaudeAgentError(
            f"Quantity too large. Maximum quantity for {symbol} is {filters['maxQty']}.")

    formatted_price = 0.0
    if price > 0:
        formatted_price = format_price(price, filters['tickSize'])
        if formatted_price < filters['minPrice'] or formatted_price > filters['maxPrice']:
            raise ClaudeAgentError(f'Price out of range for {symbol}.')
    stop_price = _coerce_float(spec.get('stopPrice') or spec.get('stop_price'), 0.0) or 0.0
    formatted_stop_price = format_price(stop_price, filters['tickSize']) if stop_price > 0 else 0.0

    if order_type in ('LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER') \
            and formatted_price <= 0:
        raise ClaudeAgentError('Price is required for limit orders')
    if order_type in ('STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT') \
            and formatted_stop_price <= 0:
        raise ClaudeAgentError(f'Stop price is required for {order_type} orders')
    if formatted_price > 0 and current_price > 0:
        valid, collar_err = validate_order_price_collar(
            formatted_price, side, current_price, filters, symbol)
        if not valid:
            raise ClaudeAgentError(collar_err)

    config_data = dict(spec)
    if formatted_price > 0:
        config_data['price'] = str(formatted_price)
    if formatted_stop_price > 0:
        config_data['stopPrice'] = str(formatted_stop_price)
    order_params = build_order_config(order_type, side, formatted_quantity, config_data, symbol)
    order_response = client.create_order(**order_params)

    executed_qty = float(order_response.get('executedQty', 0) or 0)
    executed_quote_qty = float(
        order_response.get('cummulativeQuoteQty') or order_response.get('cumulativeQuoteQty') or 0)
    fills = order_response.get('fills', []) or []
    avg_fill_price = float(fills[0].get('price', 0)) if fills else (
        price if price > 0 else current_price)
    total_commission = sum(float(f.get('commission', 0) or 0) for f in fills)
    commission_asset = fills[0].get('commissionAsset', 'USDT') if fills else 'USDT'
    binance_order_id = order_response.get('orderId') or order_response.get('orderListId')
    status = order_response.get('status', 'NEW')

    real_order = RealOrder(
        user_id=user_id,
        binance_order_id=binance_order_id,
        symbol=symbol, side=side, type=order_type,
        quantity=formatted_quantity,
        price=formatted_price if formatted_price > 0 else None,
        stop_price=order_params.get('stopPrice'),
        time_in_force=order_response.get('timeInForce', 'GTC'),
        status=status,
        executed_qty=executed_qty,
        cumulative_quote_qty=executed_quote_qty,
        avg_fill_price=avg_fill_price,
        commission=total_commission,
        commission_asset=commission_asset,
        binance_client_order_id=order_response.get('clientOrderId'),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        filled_at=datetime.utcnow() if status == 'FILLED' else None,
        order_response=json.dumps(order_response, default=str),
        source=SOURCE_MARKER,
    )
    db.session.add(real_order)
    if status == 'FILLED':
        real_order.fill_notified = True
    db.session.commit()

    if status == 'FILLED' and executed_qty > 0:
        try:
            from services.notification_service import notify_order_fill
            from services.portfolio_service import update_portfolio_from_real_order
            user = db.session.get(__import__('credentials').User, user_id)
            update_portfolio_from_real_order(
                user_id=user_id, symbol=symbol, side=side, quantity=executed_qty,
                price=avg_fill_price, commission=total_commission,
                commission_asset=commission_asset, order_id=binance_order_id,
                quote_quantity=executed_quote_qty)
            notify_order_fill(real_order, username=getattr(user, 'username', None),
                              executed_qty=executed_qty, quote_qty=executed_quote_qty,
                              fill_price=avg_fill_price)
        except Exception:
            logger.warning('Post-fill portfolio update failed for agent Binance order',
                           exc_info=True)
    return {
        'broker_order_id': str(binance_order_id) if binance_order_id else None,
        'result': {'binance_order_id': binance_order_id, 'status': status,
                   'symbol': symbol, 'side': side, 'type': order_type,
                   'quantity': formatted_quantity},
    }


def _execute_binance_staking(user_id, spec):
    from credentials import Credential
    from services.staking_purchase_service import purchase
    from trading_models import TradingSettings

    cred = Credential.query.filter_by(user_id=user_id).first()
    if not cred:
        raise ClaudeAgentError('No Binance.US credentials found. Add them in Settings.')
    settings = TradingSettings.query.filter_by(user_id=user_id).first()
    result = purchase(user_id, cred, settings, dict(spec))
    return {'broker_order_id': None, 'result': result}


def _execute_webull_paper(user_id, spec):
    """Paper Webull placement — the same service the UI's place route uses
    for simulated orders (execute_webull_test_order)."""
    from credentials import UserSetting
    from services.webull_paper_trading_service import execute_webull_test_order

    setting = UserSetting.query.filter_by(user_id=user_id).first()
    if not bool(getattr(setting, 'webull_test_mode_enabled', False)):
        raise ClaudeAgentError(
            'Webull Test Mode is off in Settings; enable it to place paper orders.')
    data = dict(spec)
    data['test_mode'] = True
    data['account_id'] = 'TEST_PAPER_ACCOUNT'
    result = execute_webull_test_order(user_id, data)
    order_id = None
    if isinstance(result, dict):
        order_id = result.get('order_id') or result.get('id')
        if not order_id and isinstance(result.get('order'), dict):
            order_id = result['order'].get('order_id') or result['order'].get('id')
    if order_id:
        from models import WebullTestOrder
        row = WebullTestOrder.query.filter_by(
            user_id=user_id, order_id=str(order_id)).first()
        if row is not None:
            row.source = SOURCE_MARKER
            db.session.commit()
    return {'broker_order_id': str(order_id) if order_id else None, 'result': result}


def _execute_binance_spot_paper(user_id, spec):
    """Mirror of the Binance.US test-order (paper) route's core sequence:
    exchange-rule formatting, paper matching validation, funds check or
    immediate fill, and a TestOrder record."""
    from services.binance_fee_service import paper_rates
    from services.binance_paper_matching import (
        PaperOrderRejected, check_paper_funds, fill_order, immediate_fill_price,
        validate_new_order)
    from services.binance_service import (
        build_order_config, get_symbol_filters, validate_order_price_collar)
    from services.common import _coerce_float, format_price, format_quantity
    from services.synthetic_execution_service import binance_client, parent_lock
    from trading_models import TestOrder, TradingSettings

    settings = TradingSettings.query.filter_by(user_id=user_id).first()
    if not settings or not settings.test_mode_enabled:
        raise ClaudeAgentError('Enable Binance.US Test Mode before placing paper orders.')
    for field in ('symbol', 'side', 'type'):
        if not spec.get(field):
            raise ClaudeAgentError(f'Missing required field: {field}')
    symbol = str(spec['symbol']).upper()
    side = str(spec['side']).upper()
    order_type = str(spec['type']).upper()

    client = binance_client(user_id)
    filters = get_symbol_filters(client, symbol)
    if not filters:
        raise ClaudeAgentError(
            f'Unable to get trading rules for {symbol}. Check the symbol is valid.')
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])
    except Exception:
        # Never simulate against the order's own price.
        current_price = 0.0
    if not current_price or current_price <= 0:
        raise ClaudeAgentError(
            f'No current market price is available for {symbol}; try again shortly.')

    price = _coerce_float(spec.get('price'), 0.0) or 0.0
    quote_amount = _coerce_float(
        spec.get('quoteQuantity') or spec.get('quote_quantity') or spec.get('quote_amount'))
    quantity = _coerce_float(spec.get('quantity')) or 0.0
    if quantity <= 0 and quote_amount and quote_amount > 0:
        reference_price = price if price > 0 else current_price
        if reference_price and reference_price > 0:
            quantity = quote_amount / reference_price
    if not quantity or quantity <= 0:
        raise ClaudeAgentError('Unable to determine order quantity.')

    formatted_quantity = format_quantity(quantity, filters['stepSize'])
    if formatted_quantity < filters['minQty']:
        raise ClaudeAgentError(
            f"Quantity too small. Minimum quantity for {symbol} is {filters['minQty']}.")
    if formatted_quantity > filters['maxQty']:
        raise ClaudeAgentError(
            f"Quantity too large. Maximum quantity for {symbol} is {filters['maxQty']}.")
    formatted_price = format_price(price, filters['tickSize']) if price > 0 else 0.0
    if formatted_price > 0 and current_price > 0:
        valid, collar_err = validate_order_price_collar(
            formatted_price, side, current_price, filters, symbol)
        if not valid:
            raise ClaudeAgentError(collar_err)

    config_data = dict(spec)
    if formatted_price > 0:
        config_data['price'] = str(formatted_price)
    test_params = build_order_config(order_type, side, formatted_quantity, config_data, symbol)
    stop_record = test_params.get('stopPrice') if 'stopPrice' in test_params else None
    stop_value = float(stop_record) if stop_record else None
    limit_value = formatted_price if formatted_price > 0 else None

    try:
        validate_new_order(order_type, side, limit_value, stop_value, current_price)
    except PaperOrderRejected as rejection:
        raise ClaudeAgentError(str(rejection))
    fill_price = immediate_fill_price(order_type, side, limit_value, stop_value, current_price)

    with parent_lock('BINANCE_PAPER', user_id) as acquired:
        if not acquired:
            raise ClaudeAgentError('The paper account is busy. Try again.')
        test_order = TestOrder(
            user_id=user_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=formatted_quantity,
            price=limit_value,
            stop_price=stop_record,
            time_in_force='GTC' if order_type in (
                'LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT') else None,
            status='NEW',
            created_at=datetime.utcnow(),
            source=SOURCE_MARKER,
        )
        try:
            if fill_price is None:
                check_paper_funds(user_id, symbol, side, formatted_quantity,
                                  limit_value or stop_value or current_price)
                test_order.notes = 'Resting paper order; it fills when the market reaches its price.'
                db.session.add(test_order)
            else:
                db.session.add(test_order)
                fill_order(test_order, fill_price, paper_rates(symbol)['takerRate'])
        except ValueError as funds_err:
            db.session.rollback()
            raise ClaudeAgentError(str(funds_err))
        db.session.commit()
    return {
        'broker_order_id': None,
        'result': {'paper_order_id': test_order.id, 'status': test_order.status,
                   'symbol': symbol, 'side': side, 'type': order_type,
                   'quantity': formatted_quantity},
    }
