"""Bounded, versioned market-data storage, separate from strategy observations."""
import gzip
import hashlib
import json
from sqlalchemy import func
from core.extensions import db
from research_data_models import ResearchCapture as Capture, ResearchCollectionConfig as Config, ResearchCollectionState as State, utcnow

LANES = ('options', 'events', 'crypto')
DEFAULTS = {'options_seconds': 300, 'events_seconds': 60, 'crypto_seconds': 30,
            'options_contracts': 200, 'event_contracts': 20, 'storage_mb': 10240}
LIMITS = {'options_seconds': (300, 3600), 'events_seconds': (60, 3600), 'crypto_seconds': (30, 3600),
          'options_contracts': (80, 400), 'event_contracts': (1, 20), 'storage_mb': (100, 102400)}


class CollectionPaused(Exception):
    pass


def settings(row):
    return {**DEFAULTS, **json.loads(row.settings_json or '{}')}


def configure(user_id, changes):
    if not isinstance(changes, dict) or set(changes)-set(DEFAULTS)-{'enabled'}:
        raise ValueError('Unknown collection setting.')
    for key, value in changes.items():
        if key == 'enabled':
            if not isinstance(value, bool):
                raise ValueError('enabled must be true or false.')
        elif isinstance(value, bool) or not isinstance(value, int) or not LIMITS[key][0] <= value <= LIMITS[key][1]:
            raise ValueError(f'{key} must be an integer from {LIMITS[key][0]} to {LIMITS[key][1]}.')
    row = Config.query.filter_by(user_id=user_id).with_for_update().first()
    if row is None:
        row = Config(user_id=user_id, enabled=False, settings_json='{}', stored_bytes=0)
        db.session.add(row)
    row.settings_json = json.dumps({**settings(row), **{k:v for k,v in changes.items() if k != 'enabled'}})
    row.enabled = changes.get('enabled', row.enabled)
    # Saved cadence/cap changes take effect on the next worker tick. Cooldowns
    # survive toggles so repeatedly enabling cannot hammer a denied endpoint.
    for state in State.query.filter_by(user_id=user_id).all():
        state.next_run_at = utcnow()
    db.session.commit()
    return status(user_id)


def sanitize(value, depth=0):
    if depth > 30:
        raise ValueError('Provider payload nesting exceeds archive limit.')
    if isinstance(value, dict):
        return {str(k): sanitize(v, depth+1) for k,v in value.items()
                if not any(word in str(k).lower() for word in ('secret', 'token', 'password', 'api_key', 'app_key', 'signature', 'authorization', 'account_id'))}
    if isinstance(value, list):
        return [sanitize(v, depth+1) for v in value]
    return value


def save_capture(user_id, lane, source, kind, symbol, payload, started_at, metadata=None, *, received_at=None):
    if lane not in LANES:
        raise ValueError('Unknown collection lane.')
    clean = sanitize(payload)
    raw = json.dumps(clean, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 4*1024*1024:
        raise ValueError('Response exceeds the 4 MiB archive batch limit.')
    compressed = gzip.compress(raw, mtime=0)
    meta = json.dumps(sanitize(metadata or {}), allow_nan=False)
    if len(meta.encode()) > 16384:
        raise ValueError('Capture metadata exceeds 16 KiB.')
    storage_size = len(compressed)+len(meta.encode())
    cfg = Config.query.filter_by(user_id=user_id).populate_existing().with_for_update().one()
    if not cfg.enabled:
        db.session.rollback()
        raise CollectionPaused('Collection paused by the administrator.')
    if cfg.stored_bytes+storage_size > settings(cfg)['storage_mb']*1024*1024:
        db.session.rollback()
        raise CollectionPaused('Archive storage limit reached; existing history is retained.')
    row = Capture(user_id=user_id, lane=lane, source=source, kind=kind, symbol=symbol[:160], started_at=started_at,
                  received_at=received_at or utcnow(),
                  sha256=hashlib.sha256(raw).hexdigest(), compressed_bytes=len(compressed), raw_bytes=len(raw),
                  payload_gzip=compressed, metadata_json=meta)
    db.session.add(row)
    cfg.stored_bytes += storage_size
    db.session.commit()
    return row.id


def status(user_id):
    cfg = db.session.get(Config, user_id)
    states = State.query.filter_by(user_id=user_id).all()
    totals = Capture.query.filter_by(user_id=user_id).with_entities(Capture.lane, func.count(Capture.id), func.min(Capture.received_at), func.max(Capture.received_at)).group_by(Capture.lane).all()
    aggregate = {lane: {'batches':n, 'first_at':first.isoformat()+'Z', 'latest_at':last.isoformat()+'Z'} for lane,n,first,last in totals}
    opts = settings(cfg) if cfg else dict(DEFAULTS)
    return {'enabled':bool(cfg and cfg.enabled), 'settings':opts, 'stored_bytes':cfg.stored_bytes if cfg else 0,
            'lanes':[{'lane':r.lane, 'status':r.status, 'heartbeat_at':r.heartbeat_at.isoformat()+'Z' if r.heartbeat_at else None,
                      'next_run_at':r.next_run_at.isoformat()+'Z' if r.next_run_at else None,
                      'details':json.loads(r.details_json), **aggregate.get(r.lane, {})} for r in states],
            'policy':'EXISTING_ACCESS_AND_PUBLIC_ONLY', 'schema_version':1,
            'limitations':['Periodic observations, not every market change or a guaranteed fill.',
                           'Missing provider timestamps remain unknown; receipt time is separate.',
                           'No subscription purchases, AI requests, orders or automatic historical deletion.',
                           'New sources and future purchased data can use separate source/methodology identifiers.']}


def export_page(user_id, after=0, limit=100):
    if isinstance(after, bool) or isinstance(limit, bool) or not isinstance(after, int) or after < 0 or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Invalid export cursor or limit (maximum 100 batches).')
    query = Capture.query.filter(Capture.user_id == user_id, Capture.id > after).order_by(Capture.id)
    records, size, cursor = [], 0, after
    for row in query.limit(limit):
        # Bound uncompressed response size as well as row count.
        if size+row.raw_bytes > 8*1024*1024:
            break
        raw = gzip.decompress(row.payload_gzip)
        if hashlib.sha256(raw).hexdigest() != row.sha256:
            raise ValueError('Archived payload checksum mismatch; export halted.')
        records.append({'id':row.id, 'source':row.source, 'lane':row.lane, 'kind':row.kind, 'symbol':row.symbol,
                        'started_at':row.started_at.isoformat()+'Z', 'received_at':row.received_at.isoformat()+'Z',
                        'sha256':row.sha256, 'metadata':json.loads(row.metadata_json), 'payload':json.loads(raw)})
        size += row.raw_bytes
        cursor = row.id
    more = db.session.query(Capture.id).filter(Capture.user_id == user_id, Capture.id > cursor).first() is not None
    return {'schema_version':1, 'records':records, 'next_cursor':cursor if more else None, 'last_id':cursor,
            'source_verified':False, 'scope':'Captured provider responses; not a complete historical market feed.'}
