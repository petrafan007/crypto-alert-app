"""Automatic, read-only Webull account and activity synchronization."""

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

from core.extensions import db
from credentials import Credential, UserSetting
from log import logger
from models import WebullAccountSnapshot, WebullActivity
from services.webull_import_service import import_webull_portfolio_snapshot
from services.webull_service import (
    get_webull_cash_activities,
    get_webull_portfolio_preview,
    normalize_webull_environment,
)


_SYNC_COOLDOWN_SECONDS = 60
_sync_guard = threading.Lock()
_user_locks = {}
_last_success = {}


def _user_lock(user_id):
    with _sync_guard:
        return _user_locks.setdefault(int(user_id), threading.Lock())


def _json_list(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return [str(item).strip() for item in (parsed or []) if str(item).strip()]
    except Exception:
        return []


def _allowed_account_ids(setting):
    enabled = _json_list(getattr(setting, 'webull_enabled_account_ids', '[]'))
    if enabled:
        return enabled
    try:
        connected = json.loads(getattr(setting, 'webull_connected_accounts', '[]') or '[]')
        return [str(item.get('account_id')).strip() for item in connected if item.get('account_id')]
    except Exception:
        return []


def _utc(value):
    if isinstance(value, datetime):
        parsed = value
    elif value in (None, ''):
        return None
    else:
        text = str(value).strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _date(value):
    if isinstance(value, date):
        return value
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _amount(value):
    try:
        return float(str(value).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return None


def _api_time(value):
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def _year_windows(start, end):
    cursor = start
    while cursor < end:
        boundary = datetime(cursor.year + 1, 1, 1)
        window_end = min(boundary, end)
        yield cursor, window_end
        cursor = window_end


def _sync_account_activities(*, user_id, environment, account_id, credential, snapshot, now):
    # Webull was launched in 2018.  A first synchronization performs a complete
    # available ledger backfill; later runs overlap two days to catch delayed
    # settlement records and safely upsert them by Webull's immutable ID.
    start = datetime(2018, 1, 1)
    if (
        snapshot and snapshot.activity_synced_at
        and snapshot.activity_sync_environment == environment
    ):
        start = max(start, snapshot.activity_synced_at - timedelta(days=2))

    upserted = 0
    for window_start, window_end in _year_windows(start, now + timedelta(seconds=1)):
        api_window_end = window_end - timedelta(milliseconds=1) if window_end.year != window_start.year else window_end
        cursor = None
        seen = set()
        for _page in range(1000):
            items = get_webull_cash_activities(
                credential.webull_app_key,
                credential.webull_app_secret,
                environment,
                credential.webull_access_token,
                account_id,
                start_time=_api_time(window_start),
                end_time=_api_time(api_window_end),
                page_size=100,
                last_activity_id=cursor,
            )
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                activity_id = str(item.get('id') or '').strip()
                if not activity_id:
                    continue
                row = WebullActivity.query.filter_by(
                    user_id=user_id,
                    environment=environment,
                    account_id=str(account_id),
                    webull_activity_id=activity_id,
                ).first()
                if row is None:
                    row = WebullActivity(
                        user_id=user_id,
                        environment=environment,
                        account_id=str(account_id),
                        webull_activity_id=activity_id,
                    )
                    db.session.add(row)
                row.activity_type = str(item.get('activity_type') or '').strip().upper() or None
                row.activity_sub_type = str(item.get('activity_sub_type') or '').strip().upper() or None
                row.currency = str(item.get('currency') or '').strip().upper() or None
                row.market = str(item.get('market') or '').strip().upper() or None
                row.symbol = str(item.get('symbol') or '').strip().upper() or None
                row.trade_date = _date(item.get('trade_date'))
                row.net_amount = _amount(item.get('net_amount'))
                row.biz_time = _utc(item.get('biz_time'))
                row.raw_details = json.dumps(item, separators=(',', ':'), sort_keys=True)
                row.synced_at = now
                upserted += 1
            if len(items) < 100:
                break
            next_cursor = str((items[-1] or {}).get('id') or '').strip()
            if not next_cursor or next_cursor in seen:
                break
            seen.add(next_cursor)
            cursor = next_cursor

    if snapshot:
        snapshot.activity_synced_at = now
        snapshot.activity_sync_environment = environment
    return upserted


def sync_webull_user_data(user_id, *, force=False):
    """Refresh enabled Webull balances, positions, and the complete activity ledger.

    This performs read-only API calls and local upserts only.  It never submits,
    modifies, or cancels an order in either live or test mode.
    """
    user_id = int(user_id)
    now_epoch = time.monotonic()
    if not force and now_epoch - _last_success.get(user_id, 0) < _SYNC_COOLDOWN_SECONDS:
        return {'success': True, 'skipped': True, 'reason': 'cooldown'}

    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        return {'success': True, 'skipped': True, 'reason': 'already-running'}
    try:
        credential = Credential.query.filter_by(user_id=user_id).first()
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        account_ids = _allowed_account_ids(setting) if setting else []
        if not account_ids:
            return {'success': False, 'skipped': True, 'reason': 'no-enabled-accounts'}
        if not (
            credential
            and credential.webull_token_status == 'NORMAL'
            and credential.webull_token_environment == environment
            and credential.webull_access_token
            and credential.webull_app_key
            and credential.webull_app_secret
        ):
            return {'success': False, 'skipped': True, 'reason': 'not-connected'}

        preview = get_webull_portfolio_preview(
            credential.webull_app_key,
            credential.webull_app_secret,
            environment,
            credential.webull_access_token,
            account_ids=account_ids,
        )
        for account in preview:
            account['_environment'] = environment
        portfolio_result = import_webull_portfolio_snapshot(user_id, preview)
        now = datetime.utcnow()
        activity_count = 0
        for account in preview:
            account_id = str(account.get('account_id') or '').strip()
            if not account_id:
                continue
            snapshot = WebullAccountSnapshot.query.filter_by(user_id=user_id, account_id=account_id).first()
            activity_count += _sync_account_activities(
                user_id=user_id,
                environment=environment,
                account_id=account_id,
                credential=credential,
                snapshot=snapshot,
                now=now,
            )
            db.session.commit()

        _last_success[user_id] = time.monotonic()
        return {
            'success': True,
            'accounts': portfolio_result['accounts'],
            'positions': portfolio_result['positions'],
            'activities': activity_count,
            'synced_at': now.isoformat() + 'Z',
        }
    except Exception:
        db.session.rollback()
        raise
    finally:
        lock.release()


def webull_auto_sync_loop(app, interval_seconds=60):
    """Continuously synchronize every connected user's enabled Webull accounts."""
    logger.info('=== Automatic Webull account synchronization STARTED ===')
    while True:
        with app.app_context():
            try:
                user_ids = [row[0] for row in db.session.query(Credential.user_id).filter(
                    Credential.webull_token_status == 'NORMAL'
                ).all()]
                for user_id in user_ids:
                    try:
                        sync_webull_user_data(user_id)
                    except Exception as exc:
                        logger.warning('Automatic Webull synchronization failed for user %s: %s', user_id, exc)
                    finally:
                        db.session.remove()
            except Exception as exc:
                logger.error('Automatic Webull synchronization iteration failed: %s', exc, exc_info=True)
                db.session.remove()
        time.sleep(max(30, int(interval_seconds)))
