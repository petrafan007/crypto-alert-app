"""Fixed-horizon grading and versioned calibration; missing prices stay unscored."""
from datetime import datetime, timedelta, timezone
import json
import math
from statistics import mean

from sqlalchemy.orm import Session
from core.extensions import db
from models import JevEvaluation, PriceHistory, ExternalSentimentSignal


def evaluate_pending_outcomes(now=None, limit=500):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    count = 0
    with Session(db.engine) as session:
        rows = session.query(JevEvaluation).filter(JevEvaluation.status.in_(['success', 'abstained']),
            JevEvaluation.answers_json.isnot(None), JevEvaluation.outcome_due_at <= now,
            JevEvaluation.outcome_evaluated_at.is_(None)).order_by(
                JevEvaluation.outcome_checked_at.asc().nullsfirst(), JevEvaluation.outcome_due_at,
                JevEvaluation.id).limit(max(1, min(500, int(limit)))).all()
        for row in rows:
            row.outcome_checked_at = now
            if not row.entry_price or row.entry_price <= 0:
                continue
            price, actual_at = None, None
            if row.external_sentiment_signal_id:
                signal = session.get(ExternalSentimentSignal, row.external_sentiment_signal_id)
                if signal and signal.outcome_evaluated_at and signal.outcome_price:
                    price, actual_at = signal.outcome_price, signal.outcome_evaluated_at
            elif row.use_case == 'quant_crypto':
                # Quant quotes come from Webull. Later immutable scan snapshots
                # provide the same user's same-source outcome, without a new API call.
                quotes = session.query(JevEvaluation).filter_by(user_id=row.user_id,
                    use_case='quant_crypto', symbol=row.symbol, market_source=row.market_source,
                    instrument_type=row.instrument_type).filter(
                        JevEvaluation.decision_time >= row.outcome_due_at-timedelta(minutes=15),
                        JevEvaluation.decision_time <= min(now, row.outcome_due_at+timedelta(minutes=15)),
                        JevEvaluation.entry_price > 0).all()
                closest = min(quotes, key=lambda q: abs((q.decision_time-row.outcome_due_at).total_seconds()), default=None)
                if closest:
                    price, actual_at = closest.entry_price, closest.decision_time
            elif row.market_source == 'binance' and row.instrument_type == 'CRYPTO':
                target = int(row.outcome_due_at.replace(tzinfo=timezone.utc).timestamp())
                observed = int(now.replace(tzinfo=timezone.utc).timestamp())
                prices = session.query(PriceHistory).filter_by(symbol=row.symbol, exchange='binance').filter(
                    PriceHistory.timestamp >= target-900, PriceHistory.timestamp <= min(target+900, observed)).all()
                closest = min(prices, key=lambda p: abs(p.timestamp-target), default=None)
                if closest:
                    price, actual_at = closest.price, datetime.fromtimestamp(closest.timestamp, timezone.utc).replace(tzinfo=None)
            if (not price or not actual_at or actual_at > now or actual_at < row.decision_time
                    or abs((actual_at-row.outcome_due_at).total_seconds()) > 900):
                continue
            row.outcome_price = price
            row.outcome_return_pct = (price/row.entry_price-1)*100
            row.outcome_evaluated_at = actual_at
            # MFE/MAE require reliable full-window bars; sparse price samples are not extrema.
            count += 1
        session.commit()
    return count


def calibration(rows):
    """Never mix contracts, horizons or instruments in calibration cohorts."""
    groups = {}
    for row in rows:
        if row.outcome_return_pct is None or not row.answers_json:
            continue
        key = f'{row.use_case}/{row.market_source}/{row.instrument_type}/{row.model}/{row.question_schema_version}/{row.target_horizon:g}h'
        group = groups.setdefault(key, {'questions': {}, 'scores': {}, 'sample_count': 0})
        group['sample_count'] += 1
        answers = json.loads(row.answers_json)
        for question, truth in [('bullish', row.outcome_return_pct > 0), ('downside_risk', row.outcome_return_pct <= -2)]:
            if question not in answers:
                continue
            p = answers[question]['probability']
            group['questions'].setdefault(question, []).append((p, int(truth)))
        for question in ('materiality', 'setup_quality'):
            if question in answers:
                bucket = str(min(5, int(answers[question]['score']+1)))
                group['scores'].setdefault(question, {}).setdefault(bucket, []).append(row.outcome_return_pct)
    for group in groups.values():
        for question, samples in list(group['questions'].items()):
            buckets = []
            for lower in range(10):
                members = [(p, y) for p, y in samples if min(9, int(p*10)) == lower]
                if members:
                    buckets.append({'lower': lower/10, 'upper': (lower+1)/10, 'count': len(members),
                                    'mean_probability': mean(p for p, y in members), 'observed_rate': mean(y for p, y in members)})
            thresholds = {}
            for threshold in (0.5, 0.7, 0.8, 0.9):
                selected = [(p, y) for p, y in samples if max(p, 1-p) >= threshold]
                thresholds[str(threshold)] = {'count': len(selected), 'coverage': len(selected)/len(samples),
                    'accuracy': mean((p >= 0.5) == bool(y) for p, y in selected) if selected else None}
            group['questions'][question] = {'count': len(samples), 'brier': mean((p-y)**2 for p, y in samples),
                                            'buckets': buckets, 'thresholds': thresholds}
        for question, buckets in group['scores'].items():
            group['scores'][question] = {k: {'count': len(v), 'mean_return_pct': mean(v)} for k, v in buckets.items()}
    return groups


def serialize(row):
    answers = json.loads(row.answers_json or '{}')
    return {**{key: getattr(row, key) for key in ('id', 'symbol', 'market_source', 'use_case', 'status', 'model', 'latency_ms',
            'error_message_safe', 'action_taken', 'result_state', 'fallback_used', 'outcome_return_pct', 'question_schema_version')},
        'created_at': row.created_at.isoformat()+'Z', 'decision_time': row.decision_time.isoformat()+'Z',
        'answers': answers, 'confidence': json.loads(row.confidence_json or '{}'),
        'baseline': json.loads(row.counterfactual_json or '{}'),
        'estimated_cost_usd': float(row.estimated_cost_usd) if row.estimated_cost_usd is not None else None}


def telemetry(user_id, use_case=None):
    with Session(db.engine) as session:
        query = session.query(JevEvaluation).filter_by(user_id=user_id).filter(
            JevEvaluation.created_at >= datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=30))
        if use_case:
            query = query.filter_by(use_case=use_case)
        rows = query.order_by(JevEvaluation.id.desc()).limit(2000).all()
        terminal = [r for r in rows if r.status not in ('pending', 'running')]
        latencies = sorted(r.latency_ms for r in terminal if r.latency_ms is not None)
        percentile = lambda q: latencies[min(len(latencies)-1, math.ceil(len(latencies)*q)-1)] if latencies else None
        costs = [float(r.estimated_cost_usd) for r in rows if r.estimated_cost_usd is not None]
        return {'window_days': 30, 'sample_limit': 2000, 'sample_count': len(rows),
            'completed_count': len(terminal), 'pending_count': len(rows)-len(terminal),
            'p50_ms': percentile(.5), 'p95_ms': percentile(.95), 'p99_ms': percentile(.99) if len(latencies) >= 100 else None,
            'error_rate': sum(r.status in ('error', 'timeout', 'invalid_response') for r in terminal)/len(terminal) if terminal else None,
            'timeout_rate': sum(r.status == 'timeout' for r in terminal)/len(terminal) if terminal else None,
            'abstention_rate': sum(r.status == 'abstained' for r in terminal)/len(terminal) if terminal else None,
            'fallback_rate': sum(r.fallback_used for r in terminal)/len(terminal) if terminal else None,
            'reported_cost_usd': sum(costs) if costs else None, 'cost_reported_count': len(costs),
            'cost_per_1000_reported': mean(costs)*1000 if costs else None,
            'last_success': next((r.completed_at.isoformat()+'Z' for r in rows if r.status == 'success' and r.completed_at), None),
            'last_safe_error': next((r.error_message_safe for r in rows if r.error_message_safe), None),
            'calibration': calibration(rows), 'recent': [serialize(r) for r in rows[:20]],
            'limitations': 'Paper gating unavailable. Returns are fixed-horizon observations, not simulated P&L. MFE/MAE require full-window bars. Cost excludes generative fallback when its provider does not report cost.'}
