"""Daily source-aware AI review and forward-only shadow promotion for paper rules."""
import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from core.extensions import db
from portfolio_algo_models import (
    PortfolioStrategyConfig as Config, PortfolioStrategyLot as Lot,
    PortfolioSignalDecision as Decision, PortfolioStrategyRevision as Revision,
    PortfolioAIReview as Review,
)
from services.portfolio_strategy_signals import ET
from services.strategy_client import request, StrategyUnavailable
from services.provider_resilience import AuditCancelled

logger = logging.getLogger(__name__)
MODULES = ('equities', 'options', 'crypto', 'events')
MAX_DAILY_AI_REQUESTS = 1  # Default; saved config may allow at most three.


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _features(row, options_min_ivr=40):
    checks = json.loads(row.checks_json or '{}')
    if row.module == 'equities' or row.module == 'crypto':
        return {'checks': checks}
    if row.module == 'options':
        return {'checks': checks, 'basis': row.setup or 'CURRENT_IV_VS_REALIZED_VOL',
                'min_ivr': options_min_ivr}
    return {'eligible': row.proposed_action == 'ENTER',
            'fresh_quote': bool(checks.get('quote_revalidated')),
            'risk_allowed': row.disposition not in ('HELD', 'RISK_HELD', 'RISK_BLOCKED')}


def evidence(user_id, cfg):
    from services.portfolio_engine import loads, settings_for
    now = datetime.utcnow()
    since = now - timedelta(days=35)
    rows = Decision.query.filter(Decision.user_id == user_id, Decision.evaluated_at >= since).order_by(
        Decision.evaluated_at.desc()).limit(80).all()
    source = {module: request('source', module=module) for module in MODULES}
    counts = {module: {'evaluated': 0, 'qualified': 0, 'filled': 0, 'dispositions': {},
                       'closed_trades': 0, 'net_pnl_usd': 0.0, 'observation_sessions': 0}
              for module in MODULES}
    groups = db.session.query(Decision.module, Decision.proposed_action, Decision.disposition,
        func.count(Decision.id)).filter(Decision.user_id == user_id,
        Decision.evaluated_at >= since).group_by(
        Decision.module, Decision.proposed_action, Decision.disposition).all()
    for module, action, disposition, total in groups:
        if module not in counts:
            continue
        item = counts[module]
        item['evaluated'] += total
        item['qualified'] += total if action == 'ENTER' else 0
        item['filled'] += total if disposition == 'FILLED' else 0
        item['dispositions'][disposition] = total
    sessions = db.session.query(Decision.module,
        func.count(func.distinct(func.date(Decision.evaluated_at)))).filter(
        Decision.user_id == user_id, Decision.evaluated_at >= since).group_by(Decision.module).all()
    for module, total in sessions:
        if module in counts:
            counts[module]['observation_sessions'] = total
    outcomes = db.session.query(Lot.module, func.count(Lot.id),
        func.coalesce(func.sum(Lot.realized_pnl), 0)).filter(
        Lot.user_id == user_id, Lot.closed_at.isnot(None),
        Lot.closed_at >= since).group_by(Lot.module).all()
    for module, total, pnl in outcomes:
        if module in counts:
            counts[module]['closed_trades'] = total
            counts[module]['net_pnl_usd'] = round(float(pnl), 2)
    return {'as_of': now.isoformat() + 'Z', 'target_annual_return_pct': cfg.target_annual_return,
            'mode': 'PAPER', 'modules': counts,
            'recent_decisions': [{'id': row.id, 'module': row.module, 'symbol': row.symbol,
                                  'at': row.evaluated_at.isoformat() + 'Z', 'setup': row.setup,
                                  'action': row.proposed_action, 'disposition': row.disposition,
                                  'reason': row.reason[:180], 'checks': json.loads(row.checks_json or '{}')}
                                 for row in rows[:80]],
            'active_sources': source, 'daily_request_limit': max(1, min(3, int(json.loads(cfg.master_ai_config or '{}').get('daily_strategy_requests', 1)))),
            'limitations': ['Only measured paper outcomes can validate a revision.',
                            'Unknown counterfactual fills cannot be credited.',
                            'AI may propose source, but activation needs future held-out evidence.']}


def _fixtures(user_id, module, cfg):
    from services.portfolio_engine import settings_for
    min_ivr = settings_for(cfg)['options']['min_ivr']
    rows = Decision.query.filter_by(user_id=user_id, module=module).order_by(Decision.id.desc()).limit(30).all()
    fixtures = []
    for row in rows:
        try:
            fixtures.append({'features': _features(row, min_ivr)})
        except (ValueError, KeyError, TypeError):
            continue
    return fixtures[:30]


def _drawdown(values):
    total = peak = worst = 0.0
    for value in values:
        total += value
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def promote_mature_shadows(user_id, cfg):
    """Require future paper outcomes; no candidate is judged on its proposal date."""
    from services.portfolio_engine import settings_for
    min_ivr = settings_for(cfg)['options']['min_ivr']
    for revision in Revision.query.filter_by(user_id=user_id, status='SHADOW').order_by(Revision.id).limit(10):
        scope = (Decision.user_id == user_id, Decision.module == revision.module,
                 Decision.evaluated_at > revision.created_at)
        sessions = db.session.query(func.count(func.distinct(func.date(Decision.evaluated_at)))).filter(*scope).scalar() or 0
        closed = db.session.query(Decision, Lot).join(Lot, Decision.lot_id == Lot.id).filter(
            *scope, Lot.closed_at.isnot(None)).order_by(Decision.id).limit(1000).all()
        if sessions < 30 or len(closed) < 20:
            continue
        # Two deterministic observations per symbol/session sample the
        # complete future period without running tens of thousands of
        # restricted subprocesses. All observed closed fills are included.
        edges = db.session.query(func.min(Decision.id), func.max(Decision.id)).filter(
            *scope).group_by(func.date(Decision.evaluated_at), Decision.symbol).all()
        sample_ids = {row_id for first, last in edges for row_id in (first, last)}
        sample_ids.update(row.id for row, _ in closed)
        if len(sample_ids) > 2000 or len(closed) >= 1000:
            revision.status, revision.rollback_reason = 'REJECTED', 'Forward holdout exceeds bounded replay capacity.'
            db.session.commit()
            continue
        heldout = Decision.query.filter(Decision.id.in_(sample_ids)).order_by(Decision.id).all()
        selected = []
        added = 0
        try:
            for row in heldout:
                reply = request('evaluate_candidate', module=revision.module,
                    candidate_sha256=revision.candidate_sha256, features=_features(row, min_ivr))
                if reply['enter'] and row.proposed_action != 'ENTER':
                    added += 1
                if reply['enter'] and row.lot_id:
                    selected.append(row.lot_id)
        except (StrategyUnavailable, KeyError, ValueError) as exc:
            revision.status, revision.rollback_reason = 'REJECTED', 'Shadow replay failed: ' + str(exc)[:180]
            db.session.commit()
            continue
        ordered = [lot for _, lot in sorted(closed, key=lambda pair: (pair[1].closed_at, pair[1].id))]
        selected_ids = set(selected)
        baseline = [lot.realized_pnl for lot in ordered]
        candidate = [lot.realized_pnl for lot in ordered if lot.id in selected_ids]
        breaches = Decision.query.filter(*scope, Decision.disposition.in_(
            ('RISK_HELD', 'RISK_BLOCKED'))).count()
        baseline_score = sum(baseline) - _drawdown(baseline)
        candidate_score = sum(candidate) - _drawdown(candidate)
        complete = (added == 0 and breaches == 0 and len(candidate) >= max(10, len(baseline) // 2)
                    and candidate_score > baseline_score and _drawdown(candidate) <= _drawdown(baseline))
        validation = {'observation_sessions': sessions, 'closed_trades': len(closed),
                      'risk_breaches': breaches,
                      'selected_closed_trades': len(candidate), 'new_unobserved_entries': added,
                      'baseline_score': baseline_score, 'candidate_score': candidate_score,
                      'baseline_drawdown_usd': _drawdown(baseline),
                      'candidate_drawdown_usd': _drawdown(candidate),
                      'scope': 'Forward-only suppression replay on observed paper fills; no credit for hypothetical new fills.'}
        revision.validation_json = json.dumps(validation)
        if not complete:
            revision.status, revision.rollback_reason = 'REJECTED', 'Forward holdout did not improve the net-risk score within observable fill support.'
            db.session.commit()
            continue
        try:
            result = request('activate', module=revision.module,
                parent_sha256=revision.parent_sha256,
                candidate_sha256=revision.candidate_sha256,
                evidence_sha256=_hash(validation),
                gates={'observation_sessions': sessions, 'closed_trades': len(closed),
                       'risk_breaches': breaches, 'holdout_fresh': True,
                       'baseline_score': baseline_score, 'candidate_score': candidate_score})
            revision.status, revision.activated_at = result['status'], datetime.utcnow()
            db.session.commit()
        except StrategyUnavailable as exc:
            revision.status, revision.rollback_reason = 'REJECTED', 'Activation declined: ' + str(exc)[:180]
            db.session.commit()


def review_user(user_id, day=None):
    from credentials import User
    from services.ai_service import call_ai_with_web_search, is_ai_enabled
    from services.portfolio_engine import audit_ai_kwargs
    day = day or datetime.now(ET).date()
    previous = Review.query.filter_by(user_id=user_id, review_day=day).first()
    if previous and (previous.status != 'RUNNING' or
                     datetime.utcnow() - previous.started_at <= timedelta(minutes=45)):
        return previous
    cfg = Config.query.filter_by(user_id=user_id).first()
    if not cfg or not cfg.enabled or cfg.mode != 'PAPER':
        return None
    if previous and previous.request_count:
        previous.status, previous.message = 'FAILED', 'Worker interrupted after an AI provider attempt; daily request ceiling preserved.'
        previous.completed_at = datetime.utcnow()
        db.session.commit()
        return previous
    row = previous or Review(user_id=user_id, review_day=day, status='RUNNING')
    row.started_at = datetime.utcnow()
    if previous is None:
        db.session.add(row)
    db.session.commit()
    try:
        promote_mature_shadows(user_id, cfg)
        payload = evidence(user_id, cfg)
        for active_revision in Revision.query.filter_by(user_id=user_id, status='ACTIVE').all():
            pointer = payload['active_sources'][active_revision.module]
            if pointer['sha256'] != active_revision.candidate_sha256:
                active_revision.status = 'ROLLED_BACK'
                active_revision.rollback_reason = pointer.get('rollback_reason') or 'Active service pointer changed after promotion.'
        row.evidence_sha256 = _hash(payload)
        row.summary_json = json.dumps({'modules': payload['modules'], 'source_hashes':
                                       {module: value['sha256'] for module, value in payload['active_sources'].items()}})
        db.session.commit()
        user = db.session.get(User, user_id)
        if not user or not is_ai_enabled(user.username):
            row.status, row.message = 'AI_UNAVAILABLE', 'Configured AI is disabled or unavailable; measured review evidence was saved.'
            row.completed_at = datetime.utcnow()
            db.session.commit()
            return row
        instruction = (
            'Review the supplied PAPER decisions, closed outcomes, gaps, and exact active strategy source. '
            'Return ONLY JSON with keys module, source, reason. module must be one of equities/options/crypto/events '
            'or null. source must be a complete replacement decide(f) function for that module or null. '
            'Choose null if evidence does not justify a concrete, safe code experiment. '
            'Source may use only plain if/assign/return, indexing, arithmetic and comparisons; '
            'no imports, attributes, loops, network, risk policy, orders or credentials. '
            'The source is a proposal for forward shadow evaluation; do not claim profitability. '
            'Do not ask for lower risk limits or guaranteed trade frequency.'
        )
        attempts = {'count': 0}
        limit = payload['daily_request_limit']
        def observe_attempt(**event):
            if event.get('event') == 'started':
                attempts['count'] += 1
                row.request_count = min(attempts['count'], limit)
                db.session.commit()
        def request_guard():
            if attempts['count'] > limit:
                raise AuditCancelled('Daily strategy AI request ceiling reached.')
        response, _ = call_ai_with_web_search(
            username=user.username, user_id=user_id,
            messages=[{'role': 'system', 'content': instruction},
                      {'role': 'user', 'content': json.dumps(payload, default=str)}],
            prompt_type='portfolio_strategy_review', symbol='STRATEGY',
            include_db_context=False, attempt_observer=observe_attempt,
            request_guard=request_guard, **audit_ai_kwargs(cfg))
        row.provider, row.model = getattr(response, 'provider', None), getattr(response, 'model', None)
        raw_content = str(getattr(response, 'text', '') or '').strip()
        if raw_content.startswith('```') and raw_content.endswith('```'):
            raw_content = raw_content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
        content = json.loads(raw_content)
        if not isinstance(content, dict):
            raise ValueError('AI strategy review must be a JSON object.')
        module, source = content.get('module'), content.get('source')
        row.message = str(content.get('reason') or '')[:500]
        if module is None or source is None:
            row.status = 'NO_CHANGE'
        elif module not in MODULES or not isinstance(source, str):
            raise ValueError('AI proposed an invalid module or source.')
        else:
            parent = payload['active_sources'][module]['sha256']
            if source == payload['active_sources'][module]['source']:
                row.status = 'NO_CHANGE'
            else:
                revision = Revision(user_id=user_id, module=module, parent_sha256=parent,
                    candidate_sha256=_hash(source), source_json=json.dumps({'source': source}),
                    evidence_sha256=row.evidence_sha256, status='VALIDATING',
                    provider=row.provider, model=row.model)
                db.session.add(revision)
                db.session.commit()
                try:
                    result = request('propose', module=module, parent_sha256=parent,
                                     source=source, fixtures=_fixtures(user_id, module, cfg))
                    revision.candidate_sha256 = result['candidate_sha256']
                    revision.validation_json = json.dumps(result['validation'])
                    revision.status, row.status = 'SHADOW', 'CANDIDATE_SHADOW'
                except (StrategyUnavailable, ValueError) as exc:
                    revision.status, revision.rollback_reason = 'REJECTED', str(exc)[:300]
                    row.status = 'CANDIDATE_REJECTED'
        row.completed_at = datetime.utcnow()
        db.session.commit()
    except AuditCancelled:
        db.session.rollback()
        row = db.session.get(Review, row.id, populate_existing=True)
        if row:
            row.status = 'AI_BUDGET_EXHAUSTED'
            row.message = 'The configured AI provider did not return a usable response within the daily request ceiling; review evidence was saved.'
            row.request_count = min(row.request_count or 0, limit)
            row.completed_at = datetime.utcnow()
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        row = db.session.get(Review, row.id, populate_existing=True)
        if row:
            row.status, row.message = 'FAILED', type(exc).__name__ + ': ' + str(exc)[:250]
            row.completed_at = datetime.utcnow()
            db.session.commit()
        logger.exception('Daily source-aware strategy review failed for user %s', user_id)
    return row


def strategy_review_loop(app, stop_event=None):
    stop = stop_event or threading.Event()
    while not stop.is_set():
        with app.app_context():
            try:
                from credentials import User
                from event_algo import is_event_strategy_admin
                local = datetime.now(ET)
                if (local.hour, local.minute) >= (0, 30):
                    for cfg in Config.query.filter_by(mode='PAPER', enabled=True).all():
                        if is_event_strategy_admin(db.session.get(User, cfg.user_id)):
                            review_user(cfg.user_id, local.date())
            except Exception:
                db.session.rollback()
                logger.exception('Daily strategy review scheduler failed')
            finally:
                db.session.remove()
        stop.wait(60)
