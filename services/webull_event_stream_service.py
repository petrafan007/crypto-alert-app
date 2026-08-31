"""Persist provider-explicit Webull Event Contract settlement notifications."""

import hashlib
import json
import threading
import time
from datetime import datetime, timezone

from core.extensions import db
from credentials import Credential, UserSetting
from log import logger
from models import WebullEventSettlement
from services.webull_service import normalize_webull_environment


_streams_lock = threading.Lock()
_streams = {}


def _json_list(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return [str(item).strip() for item in (parsed or []) if str(item).strip()]
    except Exception:
        return []


def _accounts(setting):
    enabled = _json_list(getattr(setting, 'webull_enabled_account_ids', '[]'))
    if enabled:
        return enabled
    try:
        rows = json.loads(getattr(setting, 'webull_connected_accounts', '[]') or '[]')
        return [str(row.get('account_id')).strip() for row in rows if row.get('account_id')]
    except Exception:
        return []


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc(value):
    if not value:
        return datetime.utcnow()
    try:
        numeric = float(value)
        if numeric > 100000000000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        pass
    text = str(value).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.utcnow()
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def persist_webull_event_settlement(user_id, environment, payload, event_time=None):
    """Idempotently store one explicit EVENT_POSITION_SETTLED payload."""
    if not isinstance(payload, dict) or str(payload.get('biz_type') or '').upper() != 'EVENT_POSITION_SETTLED':
        return None
    account_id = str(payload.get('account_id') or '').strip()
    if not account_id:
        return None
    position_id = str(payload.get('position_id') or '').strip()
    canonical = json.dumps(payload, separators=(',', ':'), sort_keys=True, default=str)
    event_key = position_id or hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    row = WebullEventSettlement.query.filter_by(
        user_id=int(user_id), environment=environment, account_id=account_id, event_key=event_key,
    ).first()
    if row is None:
        row = WebullEventSettlement(
            user_id=int(user_id), environment=environment, account_id=account_id, event_key=event_key,
        )
        db.session.add(row)
    row.position_id = position_id or None
    row.symbol = str(payload.get('symbol') or '').strip().upper() or None
    row.event_name = str(payload.get('event_name') or '').strip() or None
    row.yes_condition = str(payload.get('yes_condition') or '').strip() or None
    row.settle_result = str(payload.get('settle_result') or '').strip() or None
    row.settle_side = str(payload.get('settle_side') or '').strip() or None
    row.quantity = _float(payload.get('quantity'))
    row.cost = _float(payload.get('cost'))
    row.settle_amount = _float(payload.get('settle_amount'))
    row.biz_type = 'EVENT_POSITION_SETTLED'
    row.event_time = _utc(event_time)
    row.raw_details = canonical
    row.synced_at = datetime.utcnow()
    db.session.commit()
    return row


def _run_stream(app, user_id, environment, app_key, app_secret, account_ids):
    try:
        from webull.trade.events.types import EVENT_TYPE_POSITION, POSITION_STATUS_CHANGED
        from webull.trade.trade_events_client import TradeEventsClient
        from webull.trade.events import events_pb2 as events_pb
        from webull.trade.events.signature_composer import calc_signature
        from webull.core.auth.algorithm import sha_hmac256_new

        class QuietTradeEventsClient(TradeEventsClient):
            # SDK 2.0.19 prints signed request metadata and account IDs from
            # its default implementation.  Construct the same signed request
            # without writing authentication material to application output.
            def _build_request(self, key, secret, accounts):
                request = events_pb.SubscribeRequest(
                    subscribeType=7,
                    timestamp=int(time.time() * 1000),
                    accounts=accounts,
                )
                _signature, metadata = calc_signature(key, secret, request, sha_hmac256_new)
                return request, metadata

        host = 'events-api.sandbox.webull.com' if environment == 'sandbox' else None
        client = QuietTradeEventsClient(app_key, app_secret, 'us', host=host)

        def on_message(event_type, subscribe_type, payload, raw_message):
            if event_type != EVENT_TYPE_POSITION or subscribe_type != POSITION_STATUS_CHANGED:
                return
            with app.app_context():
                try:
                    event_time = getattr(raw_message, 'timestamp', None)
                    persist_webull_event_settlement(user_id, environment, payload, event_time)
                except Exception as exc:
                    db.session.rollback()
                    logger.warning('Unable to persist Webull Event Contract settlement for user %s: %s', user_id, exc)
                finally:
                    db.session.remove()

        client.on_events_message = on_message
        client.do_subscribe(account_ids)
    except Exception as exc:
        logger.warning('Webull Event Contract settlement stream stopped for user %s: %s', user_id, exc)
    finally:
        with _streams_lock:
            _streams.pop(int(user_id), None)


def ensure_webull_event_streams(app):
    """Start one settlement subscription per connected user without blocking sync."""
    credentials = Credential.query.filter(Credential.webull_token_status == 'NORMAL').all()
    with _streams_lock:
        for credential in credentials:
            user_id = int(credential.user_id)
            running = _streams.get(user_id)
            if running and running.is_alive():
                continue
            setting = UserSetting.query.filter_by(user_id=user_id).first()
            environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
            account_ids = _accounts(setting) if setting else []
            if not account_ids or not credential.webull_app_key or not credential.webull_app_secret:
                continue
            thread = threading.Thread(
                target=_run_stream,
                args=(app, user_id, environment, credential.webull_app_key, credential.webull_app_secret, account_ids),
                name=f'webull-event-settlements-{user_id}',
                daemon=True,
            )
            _streams[user_id] = thread
            thread.start()
