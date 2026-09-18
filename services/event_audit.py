"""Exact-window Event audit facts; model prose never supplies measured totals."""
import json
from collections import Counter
from datetime import datetime, timedelta
from sqlalchemy import func
from core.extensions import db
from event_algo_models import EventStrategyRun as Run, EventStrategyLog as Log, EventStrategyDecision as Decision, EventStrategyAIEvaluation as Evaluation, EventMarketSnapshot as Snapshot
from services.event_market_timing import quote_freshness, underlying_observation


def object_json(value, fallback):
    try:
        value = json.loads(value)
        return value if isinstance(value, type(fallback)) else fallback
    except (ValueError, TypeError):
        return fallback


def gather(user_id, config, hours):
    from event_algo import event_worker_heartbeat
    from services.event_universe import configured_universe
    if config.user_id != user_id:
        raise ValueError('Event configuration does not belong to the current user.')
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 1 <= hours <= 72:
        raise ValueError('Audit window must be between 1 and 72 hours.')
    now = datetime.utcnow()
    start = now - timedelta(hours=hours)
    def query(model, stamp):
        return model.query.filter(model.user_id == user_id, model.config_id == config.id, stamp >= start, stamp <= now)
    runs = query(Run, Run.started_at)
    logs = query(Log, Log.created_at)
    decisions = query(Decision, Decision.created_at)
    evaluations = query(Evaluation, Evaluation.updated_at)
    snapshots = query(Snapshot, Snapshot.received_at)
    level_counts = dict(logs.with_entities(Log.level, func.count()).group_by(Log.level).all())
    scan_count, scanned, scan_errors = runs.with_entities(func.count(Run.id), func.coalesce(func.sum(Run.scanned_count), 0), func.coalesce(func.sum(Run.error_count), 0)).one()
    decision_count, eligible = decisions.with_entities(func.count(Decision.id), func.coalesce(func.sum(db.case((Decision.eligible.is_(True), 1), else_=0)), 0)).one()
    recent = logs.filter(Log.level.in_(['ERROR', 'CRITICAL', 'WARNING'])).order_by(Log.created_at.desc(), Log.id.desc()).limit(10).all()
    examples = decisions.order_by(Decision.created_at.desc(), Decision.id.desc()).limit(100).all()
    snapshot_rows = snapshots.order_by(Snapshot.received_at.desc(), Snapshot.id.desc()).limit(200).all()
    reasons = Counter()
    for row in examples:
        reasons.update(str(code) for code in object_json(row.reason_codes, []) if isinstance(code, str))
    quote_status, underlying_status = Counter(), Counter()
    for row in snapshot_rows:
        market = object_json(row.raw_json, {})
        quote_status[quote_freshness(market, row.received_at)['status']] += 1
        underlying_status[underlying_observation(market, row.received_at)['status']] += 1
    latest = Run.query.filter_by(user_id=user_id, config_id=config.id).filter(Run.started_at <= now).order_by(Run.started_at.desc(), Run.id.desc()).first()
    signal = object_json(config.signal_config, {})
    threshold = max(180, int(signal.get('scan_interval_seconds', 60)) * 3)
    _, age, stale = event_worker_heartbeat(config, latest, now, threshold)
    log_errors = level_counts.get('ERROR', 0) + level_counts.get('CRITICAL', 0)
    metrics = dict(scans_count=scan_count, scanned_contracts=scanned, scan_error_count=scan_errors,
        run_status_counts=dict(runs.with_entities(Run.status, func.count()).group_by(Run.status).all()),
        total_logs=sum(level_counts.values()), info_count=level_counts.get('INFO', 0), warning_count=level_counts.get('WARNING', 0),
        log_error_count=log_errors, error_count=log_errors, decisions_count=decision_count,
        eligible_count=eligible, no_trade_count=decision_count-eligible,
        top_reason_codes=dict(reasons.most_common(10)), reason_codes_basis='LATEST_100_DECISIONS',
        ai_evaluations=dict(evaluations.with_entities(Evaluation.status, func.count()).group_by(Evaluation.status).all()),
        ai_evaluations_basis='LATEST_STATE_OF_CONTRACTS_UPDATED_IN_WINDOW_NOT_REQUEST_COUNTS',
        quote_status_at_retrieval=dict(quote_status), underlying_status_at_retrieval=dict(underlying_status))
    sample = {'decisions': {'total': decision_count, 'supplied': len(examples), 'truncated': decision_count > len(examples)},
              'snapshots': {'total': snapshots.count(), 'supplied': len(snapshot_rows), 'limit': 200},
              'incident_examples': {'total': log_errors+level_counts.get('WARNING', 0), 'supplied': len(recent), 'limit': 10},
              'ordering': 'NEWEST_TIMESTAMP_THEN_ID', 'outside_window_fallback': False}
    universe = configured_universe(user_id, config)
    return dict(evidence_version=2, user_id=user_id, config_id=config.id, period_start_iso=start.isoformat(), period_end_iso=now.isoformat(), hours=hours,
        worker_status='STALE' if stale else config.worker_status or 'UNKNOWN', enabled=config.enabled, kill_switch=config.kill_switch,
        stale=stale, heartbeat_age_seconds=round(age, 1) if age is not None else None,
        symbols=universe['symbols'], durations=universe['durations'], collection_scope=universe['scope'], metrics=metrics, sampling=sample,
        recent_errors=[dict(id=row.id, created_at=row.created_at.isoformat(), level=row.level, event_type=row.event_type, message=row.message[:1500]) for row in recent],
        decision_examples=[dict(id=row.id, contract_symbol=row.contract_symbol, created_at=row.created_at.isoformat(), action=row.action,
            probability_yes=row.probability_yes, confidence=row.confidence, net_edge=row.net_edge, reason_codes=object_json(row.reason_codes, [])) for row in examples[:10]])


def deterministic_report(data, error_reason=None):
    metrics = data.get('metrics', {})
    errors = max(metrics.get('error_count', 0), metrics.get('scan_error_count', 0))
    status = ('DEGRADED' if errors >= 3 else 'ATTENTION_REQUIRED') if errors or data.get('stale') else (
        'STOPPED' if data.get('enabled') is False else 'DATA_LIMITED' if not metrics.get('decisions_count') or data.get('heartbeat_age_seconds') is None else 'HEALTHY')
    summary = f"{metrics.get('scans_count', 0)} scans and {metrics.get('decisions_count', 0)} decisions recorded within the {data.get('hours', 'specified')}-hour window. Status describes recorded operations, not strategy profitability or verified quote completeness."
    lines = ['## Event operational evidence', '', f"**Status:** {status}", '', summary, '',
             f"Window: {data.get('period_start_iso')} to {data.get('period_end_iso')} (UTC).", '', '| Recorded measure | Value |', '|---|---:|']
    for key in ('scans_count', 'scanned_contracts', 'decisions_count', 'eligible_count', 'no_trade_count', 'total_logs', 'log_error_count', 'scan_error_count', 'warning_count'):
        lines.append(f"| {key.replace('_', ' ')} | {metrics.get(key, 'Unavailable')} |")
    lines.extend(['', 'Log errors and scan exceptions can describe the same incident and are not added together.',
                  'Zero recorded errors does not prove that every scan, quote or provider response was captured.',
                  'No forecast calibration, execution quality or profitability verdict is established by this operational report.', '', '### Evidence scope'])
    for key, value in data.get('sampling', {}).items():
        lines.append(f'- {key}: {json.dumps(value, sort_keys=True)}')
    for key in ('top_reason_codes', 'ai_evaluations', 'quote_status_at_retrieval', 'underlying_status_at_retrieval'):
        lines.append(f'- {key}: {json.dumps(metrics.get(key, {}), sort_keys=True)}')
    lines.append('Reason and timing distributions describe the bounded samples above. Evaluation states are current states of rows updated in the window, not a history of AI requests.')
    lines.extend(['', '### Cited records'])
    for row in data.get('recent_errors', []):
        lines.append(f"- Log #{row.get('id', 'unknown')} [{row.get('created_at')}] {row.get('level')}: {row.get('message')}")
    for row in data.get('decision_examples', []):
        lines.append(f"- Decision #{row.get('id', 'unknown')} [{row.get('created_at')}] {row.get('contract_symbol')}: {row.get('action')}.")
    if error_reason:
        lines.extend(['', 'AI interpretation unavailable; deterministic evidence remains available.'])
    return dict(status=status, headline=f'Event operational evidence: {status}', summary=summary,
                content_markdown='\n'.join(lines), model='deterministic-evidence-v2', provider='local', tier='evidence')


def cited_interpretation(raw, data):
    """Only bounded, cited suggestions survive; facts/status stay deterministic."""
    value = object_json(raw.strip().removeprefix('```json').removesuffix('```').strip(), {})
    if value.get('complete') is not True or not isinstance(value.get('observations'), list):
        raise ValueError('Incomplete Event audit interpretation.')
    allowed = {f"log:{row['id']}" for row in data['recent_errors']} | {f"decision:{row['id']}" for row in data['decision_examples']} | {'metrics', 'sampling'}
    lines = ['', '### AI interpretation — unverified suggestions', '', 'Citations establish which evidence was supplied; they do not validate the model’s interpretation.']
    for item in value['observations'][:12]:
        if not isinstance(item, dict):
            raise ValueError('Malformed audit observation.')
        refs, text = item.get('evidence_refs'), item.get('text')
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in allowed for ref in refs) or not isinstance(text, str) or not text.strip():
            raise ValueError('Audit observation has missing or unsupported citations.')
        # Keep model text out of deterministic Markdown headings and tables.
        from html import escape
        text = escape(text[:1600]).replace('\n', ' ').replace('|', '&#124;').replace('*', '&#42;').replace('#', '&#35;')
        lines.append(f"- {text} (Evidence: {', '.join(refs)})")
    return '\n'.join(lines)
