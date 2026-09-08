"""Persisted audit stages projected into approximate work completion."""
from datetime import datetime, timezone


def timestamp_seconds(value):
    if not value:
        return None
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def audit_progress(status, created_at, evidence, now=None):
    saved = evidence.get('audit_progress') or {}
    modules = saved.get('modules', list((evidence.get('specialist_mandates') or {}).keys()))
    responses, errors = evidence.get('module_audits') or {}, evidence.get('module_audit_errors') or {}
    finished = [m for m in modules if responses.get(m) or m in errors]
    failed = [m for m in modules if m in errors]
    stage = saved.get('stage') or ('master' if modules and len(finished) == len(modules) else 'module' if modules else 'queued')
    pending = status == 'PENDING'
    percent = 0 if stage == 'queued' else 5 + (80 * len(finished) / len(modules) if modules else 0)
    if stage in ('master', 'finalizing'):
        percent = max(percent, 85 if stage == 'master' else 95)
    if not pending:
        stage = 'complete' if status in ('SUCCESS', 'PARTIAL') else 'failed'
        if stage == 'complete':
            percent = 100
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    end = now if pending else timestamp_seconds(saved.get('finished_at'))
    started = timestamp_seconds(created_at)
    stage_started = timestamp_seconds(saved.get('stage_started_at'))
    return {**saved, 'stage': stage, 'percent': round(min(99 if pending else 100, percent)),
            'modules': modules, 'completed_modules': finished, 'failed_modules': failed,
            'current_module': saved.get('current_module') or (next((m for m in modules if m not in finished), None) if stage == 'module' else None),
            'elapsed_seconds': max(0, round(end-started)) if end is not None and started is not None else None,
            'stage_elapsed_seconds': max(0, round(end-stage_started)) if end is not None and stage_started is not None else None}
