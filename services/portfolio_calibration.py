"""Observed Event forecast calibration, independent of whether a trade filled."""
import json
import math
from collections import Counter

from services.portfolio_strategy_signals import utc


def summarize_event_calibration(rows):
    """One earliest valid pre-cutoff forecast per contract; never count repeats as trials."""
    exclusions, chosen = Counter(), {}
    for row in sorted(rows, key=lambda r: str(r.get('predicted_at') or '')):
        contract = row.get('contract')
        try:
            probability = float(row['probability_yes'])
            predicted, cutoff = utc(row['predicted_at']), utc(row['cutoff_at'])
            if not math.isfinite(probability) or not 0 <= probability <= 1 or predicted >= cutoff:
                raise ValueError('Invalid or post-cutoff forecast')
        except (KeyError, TypeError, ValueError, OverflowError):
            exclusions['invalid_or_post_cutoff_forecast'] += 1
            continue
        if not row.get('verified_outcome') or row.get('result') not in ('YES', 'NO'):
            exclusions['no_verified_resolution'] += 1
            continue
        try:
            if utc(row['resolved_at']) < cutoff:
                raise ValueError('Resolution precedes cutoff')
        except (KeyError, TypeError, ValueError, OverflowError):
            exclusions['invalid_resolution_timestamp'] += 1
            continue
        if contract in chosen:
            exclusions['repeated_contract_forecast'] += 1
            continue
        if not contract:
            exclusions['missing_contract'] += 1
            continue
        market_probability = None
        try:
            bid, ask = float(row['yes_bid']), float(row['yes_ask'])
            if 0 <= bid <= ask <= 1:
                market_probability = (bid+ask)/2
        except (KeyError, TypeError, ValueError):
            pass
        chosen[contract] = (probability, int(row['result'] == 'YES'), market_probability)
    samples = list(chosen.values())
    buckets = []
    for index in range(10):
        items = [(p, y) for p, y, _ in samples if min(9, int(p*10)) == index]
        buckets.append({'lower': index/10, 'upper': (index+1)/10, 'count': len(items),
                        'mean_probability': sum(p for p, _ in items)/len(items) if items else None,
                        'observed_yes_rate': sum(y for _, y in items)/len(items) if items else None})
    n = len(samples)
    paired = [(p, y, m) for p, y, m in samples if m is not None]
    market_brier = sum((m-y)**2 for _, y, m in paired)/len(paired) if paired else None
    paired_brier = sum((p-y)**2 for p, y, _ in paired)/len(paired) if paired else None
    return {
        'status': 'DESCRIPTIVE_ONLY' if n else 'AWAITING_RESOLVED_FORECASTS',
        'resolved_contracts': n,
        'brier_score': sum((p-y)**2 for p, y, _ in samples)/n if n else None,
        'market_brier_score': market_brier,
        'paired_model_brier_score': paired_brier,
        'market_comparison_contracts': len(paired),
        'skill_score': 1-paired_brier/market_brier if market_brier else None,
        'calibration_error': sum(b['count']*abs(b['mean_probability']-b['observed_yes_rate']) for b in buckets if b['count'])/n if n else None,
        'buckets': buckets, 'exclusions': dict(exclusions),
        'sample_policy': 'Earliest recorded valid pre-cutoff forecast per resolved contract in this paper run, including no-trade decisions. Repeated forecasts are not independent trials.',
        'interpretation': 'Lower Brier/error is better; positive paired skill beats the contemporaneous YES bid/ask midpoint. These are descriptive diagnostics, not proof of a calibrated model, independent samples, or profitability. Provider/model changes are pooled.',
    }


def event_calibration(user_id, started_at, limit=10000):
    """Read-only bounded run-scoped diagnostics; no historical records are rewritten."""
    from event_algo_models import EventStrategyDecision as Decision, EventMarketSnapshot as Market, EventContractOutcome as Outcome
    from core.extensions import db
    query = (db.session.query(Decision, Market, Outcome)
             .join(Market, (Market.id == Decision.snapshot_id) & (Market.user_id == Decision.user_id))
             .outerjoin(Outcome, (Outcome.user_id == Decision.user_id) &
                        (Outcome.contract_symbol == Decision.contract_symbol) &
                        ((Outcome.config_id == Decision.config_id) | Outcome.config_id.is_(None)) &
                        (Outcome.cutoff_at == Market.cutoff_at))
             .filter(Decision.user_id == user_id, Decision.created_at >= started_at,
                     Decision.probability_yes.isnot(None))
             .order_by(Decision.created_at, Decision.id, Outcome.updated_at.desc()))
    entries = query.limit(limit+1).all()
    rows = []
    for decision, market, outcome in entries[:limit]:
        rows.append({'contract': decision.contract_symbol, 'probability_yes': decision.probability_yes,
                     'predicted_at': decision.created_at, 'cutoff_at': market.cutoff_at,
                     'yes_bid': market.yes_bid, 'yes_ask': market.yes_ask,
                     'verified_outcome': bool(outcome and outcome.settlement_status == 'RESOLVED' and outcome.resolved_source),
                     'result': outcome.outcome if outcome else None,
                     'resolved_at': outcome.settlement_at if outcome else None})
    result = summarize_event_calibration(rows)
    result.update({'forecast_rows_examined': len(rows), 'row_limit': limit,
                   'truncated': len(entries) > limit, 'scope_start': utc(started_at).isoformat(),
                   'coverage_note': 'Earliest forecast rows in the current run, capped at the displayed row limit. Unresolved/unproven outcomes are excluded; resolution coverage may bias the sample.'})
    return result
