"""Bounded audit ownership, independent recovery, and fenced report writes."""
import json
import logging
import math
import os
import threading
from datetime import datetime

from core.extensions import db
from portfolio_algo_models import PortfolioAudit as Audit, PortfolioEngineState as State, _record_portfolio_log
from services.portfolio_strategy_signals import utc
from services.provider_resilience import AuditCancelled

logger = logging.getLogger(__name__)


def evidence_for(row):
    try:
        value = json.loads(row.evidence_json or '{}')
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def max_duration_seconds():
    try:
        value = float(os.getenv('AI_AUDIT_MAX_DURATION_SECONDS', '3600'))
        return max(900, min(10800, value)) if math.isfinite(value) else 3600
    except (TypeError, ValueError):
        return 3600


def expiration_reason(row, now=None):
    """Progress can renew idle time, but never the overall deadline."""
    from services.ai_service import audit_provider_timeout_seconds
    now = utc(now or datetime.utcnow())
    created = utc(row.created_at)
    if created > now:
        return 'Audit creation timestamp is in the future; ownership cannot be verified.'
    if (now-created).total_seconds() >= max_duration_seconds():
        return 'Audit exceeded its maximum total duration.'
    try:
        progress = utc(evidence_for(row).get('audit_progress_at') or created)
    except (TypeError, ValueError, AttributeError):
        progress = created
    if progress > now or progress < created:
        progress = created
    idle_limit = max(900, audit_provider_timeout_seconds() + 180)
    if (now-progress).total_seconds() >= idle_limit:
        return 'Audit stopped reporting progress beyond the provider timeout allowance.'
    return None


def active_audit(user_id, now=None):
    """Expired rows cannot indefinitely defer autonomous AI before recovery runs."""
    for row in Audit.query.filter_by(user_id=user_id, status='PENDING').all():
        if expiration_reason(row, now) is None:
            return row
    return None


def mark_expired(row, reason, now):
    evidence = evidence_for(row)
    evidence['audit_error'] = reason
    progress = evidence.get('audit_progress')
    if not isinstance(progress, dict):
        progress = {}
    progress.update(stage='failed', finished_at=utc(now).isoformat(), recovery_reason=reason)
    evidence['audit_progress'] = progress
    if row.evidence_json and not evidence_for(row):
        # Retain malformed legacy evidence rather than silently discarding it.
        evidence['unparsed_prior_evidence'] = row.evidence_json
    row.status = 'FAILED'
    row.content = 'Audit interrupted: ' + reason + ' No quantitative verdict was generated. Completed evidence is preserved.'
    row.evidence_json = json.dumps(evidence)
    _record_portfolio_log(row.user_id, 'AUDIT_RECOVERED',
                          f'Audit {row.id}: {reason}', level='WARNING', audit_id=row.id)


def recover_stale_audits(user_id=None, now=None):
    """Own transaction; do not call while holding an execution/entry lock."""
    now = now or datetime.utcnow()
    query = Audit.query.filter_by(status='PENDING')
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    recovered = []
    for row in query.populate_existing().with_for_update(skip_locked=True).all():
        reason = expiration_reason(row, now)
        if reason:
            mark_expired(row, reason, now)
            recovered.append(row.id)
    db.session.commit()
    return recovered


def require_pending_audit(audit_id):
    """Short state-then-audit locks fence progress and final writes from reset/recovery."""
    identity = db.session.query(Audit.user_id).filter_by(id=audit_id).first()
    if identity is None:
        raise AuditCancelled('Audit no longer exists.')
    state = State.query.filter_by(user_id=identity.user_id).populate_existing().with_for_update().first()
    row = Audit.query.filter_by(id=audit_id).populate_existing().with_for_update().first()
    if row is None or row.status != 'PENDING':
        db.session.rollback()
        raise AuditCancelled('Audit is no longer pending.')
    now = datetime.utcnow()
    reason = expiration_reason(row, now)
    if state is None or state.generation != row.generation:
        reason = 'Portfolio generation changed while the audit was running.'
    if reason:
        mark_expired(row, reason, now)
        db.session.commit()
        raise AuditCancelled(reason)
    return row


def audit_recovery_loop(app, stop_event=None):
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        with app.app_context():
            try:
                recover_stale_audits()
            except Exception:
                db.session.rollback()
                logger.exception('Audit recovery iteration failed')
            finally:
                db.session.remove()
        stop_event.wait(30)
