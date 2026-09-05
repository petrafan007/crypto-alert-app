"""Shared provider cooldowns and short-lived search caches; never stores API keys."""
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from flask import has_app_context
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from core.extensions import db


class ProviderState(db.Model):
    __tablename__ = 'provider_request_states'
    key = db.Column(db.String(64), primary_key=True)
    owner = db.Column(db.String(120), nullable=False, index=True)
    service = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)


class ProviderUnavailable(RuntimeError):
    pass


_memory = {}
_lock = threading.RLock()
_inflight = set()


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()


def persistent():
    return has_app_context() and db.engine.dialect.name == 'postgresql'


def read(key):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if persistent():
        with db.engine.connect() as conn:
            return conn.execute(select(ProviderState.__table__).where(
                ProviderState.key == key, ProviderState.expires_at > now)).mappings().first()
    with _lock:
        row = _memory.get(key)
        return row if row and row['expires_at'] > now else None


def write(key, owner, service, kind, payload, seconds):
    values = dict(key=key, owner=str(owner or ''), service=service, kind=kind,
                  payload=payload, expires_at=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(seconds=seconds))
    if persistent():
        with db.engine.begin() as conn:
            statement = insert(ProviderState).values(**values)
            conn.execute(statement.on_conflict_do_update(index_elements=['key'], set_=values))
    else:
        with _lock:
            if len(_memory) > 1000:
                expired = [k for k, v in _memory.items() if v['expires_at'] <= datetime.now(timezone.utc).replace(tzinfo=None)]
                for k in expired:
                    _memory.pop(k, None)
            _memory[key] = values


def check(key):
    row = read(key)
    if row:
        raise ProviderUnavailable(f"{row['service']}: {row['payload']['reason']}; retry after {row['expires_at'].isoformat()}Z")


def retry_seconds(response=None, detail='', now=None):
    now = now or datetime.now(timezone.utc)
    text = str(detail).lower()
    if 'perday' in text or 'per_day' in text or 'requestsperday' in text:
        pacific = now.astimezone(ZoneInfo('America/Los_Angeles'))
        reset = (pacific+timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, (reset.astimezone(timezone.utc)-now).total_seconds())
    retry = getattr(response, 'headers', {}).get('Retry-After') if response is not None else None
    if isinstance(retry, str):
        try:
            return max(1, min(86400, float(retry)))
        except ValueError:
            try:
                return max(1, min(86400, (parsedate_to_datetime(retry)-now).total_seconds()))
            except (ValueError, TypeError):
                pass
    # Gemini supplies RetryInfo in the JSON body rather than an HTTP header.
    import re
    delay = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', str(detail))
    if delay:
        return max(1, min(86400, float(delay.group(1))))
    return 3600 if 'apikeyexhausted' in text else 60


def block_failure(key, owner, service, exc):
    if isinstance(exc, ProviderUnavailable):
        return
    response = getattr(exc, 'response', None)
    code = getattr(exc, 'status_code', None) or (getattr(response, 'status_code', None) if response is not None else None)
    detail = str(exc)
    if code == 429 or any(word in detail.lower() for word in ('resource_exhausted', 'quota', '429', 'apikeyexhausted')):
        seconds = retry_seconds(response, detail)
        reason = 'quota/rate limit reached'
    elif isinstance(exc, (requests.Timeout, requests.ConnectionError)) or 'timed out' in detail.lower():
        seconds, reason = 60, 'connection unavailable'
    elif code in (401, 403):
        seconds, reason = 300, 'credentials or permission rejected'
    elif code and code >= 500:
        seconds, reason = 60, 'provider temporarily unavailable'
    else:
        return
    write(key, owner, service, 'cooldown', {'reason': reason}, seconds)


def checked_get(service, owner, credential, url, **kwargs):
    key = identity('provider', owner, service, credential)
    check(key)
    try:
        response = requests.get(url, **kwargs)
        if response.status_code != 200:
            # Log/retain only the provider error code, never response bodies or credentials.
            try:
                payload = response.json()
                detail = payload.get('code', '') if isinstance(payload, dict) else ''
            except (ValueError, TypeError):
                detail = ''
            exc = requests.HTTPError(f'{service} HTTP {response.status_code} {detail}', response=response)
            block_failure(key, owner, service, exc)
            raise ProviderUnavailable(str(exc))
        return response
    except (requests.Timeout, requests.ConnectionError) as exc:
        block_failure(key, owner, service, exc)
        raise ProviderUnavailable(f'{service}: connection unavailable') from None


def cached_search(owner, service, parts, fetch):
    key = identity('search', owner, service, parts)
    row = read(key)
    if row:
        return row['payload']['results']
    # PostgreSQL advisory lock deduplicates requests across web and scheduler processes.
    conn = db.engine.connect() if persistent() else None
    lock_id = int(key[:15], 16)
    acquired = False
    try:
        if conn is not None:
            from sqlalchemy import text
            acquired = conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': lock_id}).scalar()
        else:
            with _lock:
                acquired = key not in _inflight
                if acquired:
                    _inflight.add(key)
        if not acquired:
            return []  # Another request is collecting; never invent or mislabel evidence.
        row = read(key)
        if row:
            return row['payload']['results']
        results = fetch()
        write(key, owner, service, 'cache', {'results': results}, 300 if results else 30)
        return results
    finally:
        if conn is not None:
            if acquired:
                from sqlalchemy import text
                conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': lock_id})
            conn.close()
        elif acquired:
            with _lock:
                _inflight.discard(key)


def health(owner):
    if persistent():
        with db.engine.connect() as conn:
            rows = conn.execute(select(ProviderState.__table__).where(
                ProviderState.owner == str(owner), ProviderState.kind == 'cooldown',
                ProviderState.expires_at > datetime.now(timezone.utc).replace(tzinfo=None))).mappings().all()
    else:
        with _lock:
            rows = [r for r in _memory.values() if r['owner'] == str(owner) and r['kind'] == 'cooldown' and r['expires_at'] > datetime.now(timezone.utc).replace(tzinfo=None)]
    return [dict(service=r['service'], reason=r['payload']['reason'], retry_at=r['expires_at'].isoformat()+'Z') for r in rows]
