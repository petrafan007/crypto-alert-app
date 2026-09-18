"""Independent Event jobs, bounded AI work and durable provider-call accounting."""
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from sqlalchemy import select, text
from core.extensions import db
from event_algo_models import EventStrategyConfig as Config
from services.provider_resilience import AIRequestDeferred, AuditCancelled, ProviderState, identity

_memory = {}
_mutex = threading.RLock()


def budget(user_id, maximum=None, *, reserve=False):
    """Every transport attempt (search planning, completion, retry, tier) counts."""
    now = datetime.utcnow()
    key = identity('event-provider-budget', user_id)
    def update(payload):
        stamps = [stamp for stamp in payload.get('timestamps', []) if 0 <= time.time()-stamp < 3600]
        if reserve:
            if len(stamps) >= maximum:
                raise AIRequestDeferred('Event hourly provider-request budget exhausted; retry next hour.')
            stamps.append(time.time())
        return {'timestamps': stamps}
    if db.engine.dialect.name == 'postgresql':
        with db.engine.begin() as connection:
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int(key[:15], 16)})
            current = connection.execute(select(ProviderState.payload).where(ProviderState.key == key)).scalar() or {}
            payload = update(current)
            if reserve:
                from sqlalchemy.dialects.postgresql import insert
                stmt = insert(ProviderState).values(key=key, owner=str(user_id), service='Event AI transport', kind='budget', expires_at=now+timedelta(hours=1), payload=payload)
                connection.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={'payload':payload, 'expires_at':now+timedelta(hours=1)}))
    else:
        with _mutex:
            payload = update(_memory.get(key, {}))
            if reserve:
                _memory[key] = payload
    stamps = payload['timestamps']
    return {'calls': len(stamps), 'last_at': max(stamps) if stamps else None, 'basis': 'PROVIDER_TRANSPORT_ATTEMPTS'}


def reserve_provider_call(user_id):
    # A separate connection does not flush the caller's pending scan objects.
    with db.engine.connect() as connection:
        row = connection.execute(select(Config.signal_config, Config.enabled, Config.kill_switch, Config.mode).where(Config.user_id == user_id).order_by(Config.id).limit(1)).first()
    if row is None or row.kill_switch or row.mode != 'PAPER':
        raise AIRequestDeferred('Event configuration is unavailable or killed.')
    signal = json.loads(row.signal_config)
    maximum = int(signal.get('max_ai_calls_per_hour', 12))
    if not 1 <= maximum <= 240:
        raise AIRequestDeferred('Invalid Event provider-request budget.')
    return budget(user_id, maximum, reserve=True)


def event_request_guard(user_id, config_id, *, seconds=240, require_enabled=True):
    deadline = time.monotonic()+seconds
    def guard():
        from portfolio_algo_models import PortfolioEngineState, PortfolioStrategyConfig
        if time.monotonic() >= deadline:
            raise AuditCancelled('Event work exceeded its progress deadline; late output discarded.')
        with db.engine.connect() as connection:
            config = connection.execute(select(Config.enabled, Config.kill_switch, Config.mode).where(Config.id == config_id, Config.user_id == user_id)).first()
            killed = connection.execute(select(PortfolioEngineState.kill_switch).where(PortfolioEngineState.user_id == user_id)).scalar()
            settings = connection.execute(select(PortfolioStrategyConfig.module_settings_json).where(PortfolioStrategyConfig.user_id == user_id)).scalar()
        if config is None or config.kill_switch or config.mode != 'PAPER' or (require_enabled and not config.enabled) or killed:
            raise AuditCancelled('Event controls changed; late work discarded.')
        if settings and not json.loads(settings).get('events', {}).get('enabled', True):
            raise AuditCancelled('Event module is disabled; late work discarded.')
    return guard


@contextmanager
def job_slot(user_id, job):
    """No waiting behind another web/worker request for the same Event job."""
    from services.provider_resilience import serialized_ai_request
    with serialized_ai_request(str(user_id), 'event-job-'+job, wait_timeout=0):
        yield


def event_maintenance_loop(app, stop_event=None, *, job):
    """Settlement and report threads never wait for each other's AI work."""
    import event_algo as event
    from credentials import User, UserSetting
    from event_algo_models import EventStrategyReport
    from portfolio_algo_models import PortfolioEngineState
    stop = stop_event or threading.Event()
    last = {}
    while not stop.is_set():
        with app.app_context():
            try:
                ids = [row.id for row in Config.query.filter_by(mode='PAPER').all()]
                for config_id in ids:
                    config = db.session.get(Config, config_id)
                    if not config or not event.is_event_strategy_admin(db.session.get(User, config.user_id)):
                        continue
                    seconds = 180
                    if job == 'report':
                        state = db.session.get(PortfolioEngineState, config.user_id)
                        if not config.enabled or config.kill_switch or (state and state.kill_switch) or not event.quantitative_event_entries_enabled(config.user_id):
                            continue
                        setting = UserSetting.query.filter_by(user_id=config.user_id).first()
                        hours = max(1, min(72, int(getattr(setting, 'event_strategy_audit_hours', 6) or 6)))
                        seconds = hours*3600
                        latest = EventStrategyReport.query.filter_by(config_id=config.id, user_id=config.user_id).order_by(EventStrategyReport.created_at.desc()).first()
                        if latest and (datetime.utcnow()-latest.created_at).total_seconds() < seconds:
                            continue
                    if time.monotonic()-last.get(config_id, -1e10) < seconds:
                        continue
                    last[config_id] = time.monotonic()
                    user_id = config.user_id
                    db.session.commit()
                    try:
                        if job == 'settlement':
                            with job_slot(user_id, job):
                                result = event.resolve_event_outcomes(user_id, config=config, limit=100)
                        else:
                            result = event.generate_event_strategy_report(user_id, config=config, hours=hours)
                    except (AIRequestDeferred, AuditCancelled) as exc:
                        db.session.rollback()
                        event._record_engine_log(user_id, job.upper()+'_DEFERRED', str(exc)[:500], config_id=config_id)
                        db.session.commit()
                    except Exception as exc:
                        db.session.rollback()
                        event.logger.warning('Event %s job failed: %s', job, type(exc).__name__)
            except Exception as exc:
                db.session.rollback()
                event.logger.warning('Event %s supervisor error: %s', job, type(exc).__name__)
            finally:
                db.session.remove()
        stop.wait(15 if job == 'settlement' else 30)
