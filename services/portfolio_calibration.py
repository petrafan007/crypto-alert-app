"""Observed Event forecast calibration, independent of whether a trade filled."""
import json
import math
from collections import Counter, defaultdict

from sqlalchemy import case, func, or_

from services.portfolio_strategy_signals import utc


BREAKDOWN_GROUP_LIMIT = 50


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _label(value, fallback):
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _forecast_groups(row):
    """Use only metadata archived on the selected decision, never current settings."""
    features = _object(row.get('feature_json'))
    model = _object(features.get('model'))
    contract = _object(features.get('contract_details'))
    provider = _label(model.get('provider'), 'Unknown provider')
    name = _label(model.get('model'), 'Unknown model')
    version = _label(row.get('model_version'), 'Unknown strategy version')
    duration = _label(contract.get('duration_label'), 'Unknown duration')
    return {'model': (provider, name, version), 'duration': (duration,),
            'period': (utc(row['predicted_at']).strftime('%Y-%m'),)}


def _calibration_metrics(samples):
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
        'buckets': buckets,
    }


def _calibration_breakdowns(chosen, groups):
    breakdowns = {}
    for dimension in ('model', 'duration', 'period'):
        members = defaultdict(list)
        for contract, sample in chosen.items():
            members[groups[contract][dimension]].append(sample)
        # Keep reports bounded. Periods show the newest months; other dimensions
        # show the largest groups, with stable label ordering for ties.
        keys = sorted(members, reverse=True) if dimension == 'period' else sorted(members, key=lambda key: (-len(members[key]), key))
        rows = []
        for key in keys[:BREAKDOWN_GROUP_LIMIT]:
            metrics = _calibration_metrics(members[key])
            metrics.pop('buckets')
            metrics.pop('status')
            rows.append({'key': json.dumps(key), 'label': ' / '.join(key), **metrics})
        omitted = keys[BREAKDOWN_GROUP_LIMIT:]
        breakdowns[dimension] = {'rows': rows, 'total_groups': len(keys), 'group_limit': BREAKDOWN_GROUP_LIMIT,
                                 'omitted_groups': len(omitted),
                                 'omitted_contracts': sum(len(members[key]) for key in omitted)}
    return breakdowns


def summarize_event_calibration(rows):
    """One earliest valid pre-cutoff forecast per contract; never count repeats as trials."""
    exclusions, chosen, groups = Counter(), {}, {}
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
        groups[contract] = _forecast_groups(row)
    return {
        **_calibration_metrics(list(chosen.values())), 'exclusions': dict(exclusions),
        'breakdowns': _calibration_breakdowns(chosen, groups),
        'breakdown_policy': 'Each breakdown partitions the same selected contract sample using its earliest valid forecast. Model groups use archived provider, model and strategy version; duration uses the archived contract label, not time remaining; periods are forecast calendar months in UTC. Missing metadata is Unknown. Model and market Brier scores and skill use the matched subset within each group. Groups can contain different contracts and small, correlated samples; they do not establish a winning model or statistical significance. At most 50 groups are shown per dimension; omitted groups are disclosed.',
        'sample_policy': 'Earliest recorded valid pre-cutoff forecast per resolved contract in this paper run, including no-trade decisions. Repeated forecasts are not independent trials.',
        'interpretation': 'Lower Brier/error is better; positive paired skill beats the contemporaneous YES bid/ask midpoint. These are descriptive diagnostics, not proof of a calibrated model, independent samples, or profitability. The overall scores pool provider/model changes; breakdowns disclose the selected forecast groups.',
    }


def event_calibration(user_id, started_at, limit=10000):
    """Cap distinct eligible contracts, not repeated joined forecast rows."""
    from event_algo_models import EventStrategyDecision as Decision, EventMarketSnapshot as Market, EventContractOutcome as Outcome
    from core.extensions import db
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError('Calibration contract limit must be a positive integer')
    # Mirror the summary's eligibility checks before ranking. An invalid early
    # forecast must never hide a later valid forecast for the same contract.
    exclusion = case(
        (or_(Market.cutoff_at.is_(None), Decision.created_at >= Market.cutoff_at,
             ~Decision.probability_yes.between(0, 1)), 'invalid_or_post_cutoff_forecast'),
        (or_(Outcome.id.is_(None), Outcome.settlement_status != 'RESOLVED',
             Outcome.resolved_source.is_(None), Outcome.resolved_source == '',
             Outcome.outcome.is_(None), ~Outcome.outcome.in_(['YES', 'NO'])), 'no_verified_resolution'),
        (or_(Outcome.settlement_at.is_(None), Outcome.settlement_at < Market.cutoff_at),
         'invalid_resolution_timestamp'),
        (Decision.contract_symbol == '', 'missing_contract'),
        else_=None,
    ).label('exclusion')
    joined = (db.session.query(
                 Decision.id.label('decision_id'), Decision.contract_symbol.label('contract'),
                 Decision.probability_yes, Decision.created_at.label('predicted_at'), Market.cutoff_at,
                 Market.yes_bid, Market.yes_ask, Outcome.outcome.label('result'),
                 Outcome.settlement_at.label('resolved_at'), Outcome.updated_at.label('outcome_updated_at'),
                 Outcome.id.label('outcome_id'), exclusion)
             .select_from(Decision)
             .join(Market, (Market.id == Decision.snapshot_id) & (Market.user_id == Decision.user_id) &
                   (Market.contract_symbol == Decision.contract_symbol))
             .outerjoin(Outcome, (Outcome.user_id == Decision.user_id) &
                        (Outcome.contract_symbol == Decision.contract_symbol) &
                        ((Outcome.config_id == Decision.config_id) | Outcome.config_id.is_(None)) &
                        (Outcome.cutoff_at == Market.cutoff_at))
             .filter(Decision.user_id == user_id, Decision.created_at >= started_at,
                     Decision.probability_yes.isnot(None))
             .subquery())
    ranked = (db.session.query(joined, func.row_number().over(
                  partition_by=joined.c.contract,
                  order_by=(joined.c.predicted_at, joined.c.decision_id,
                            joined.c.outcome_updated_at.desc().nullslast(), joined.c.outcome_id.desc()),
              ).label('forecast_rank'))
              .filter(joined.c.exclusion.is_(None)).subquery())
    entries = (db.session.query(ranked).filter(ranked.c.forecast_rank == 1)
               .order_by(ranked.c.predicted_at, ranked.c.decision_id)
               .limit(limit+1).all())
    rows = [dict(entry._mapping, verified_outcome=True) for entry in entries[:limit]]
    # Fetch metadata only for the bounded selected forecasts, keeping potentially
    # large JSON payloads out of the full-run join, ranking and count queries.
    if rows:
        metadata = {item.id: item for item in db.session.query(Decision.id, Decision.feature_json, Decision.model_version)
                    .filter(Decision.user_id == user_id, Decision.id.in_([row['decision_id'] for row in rows])).all()}
        for row in rows:
            saved = metadata.get(row['decision_id'])
            row.update(feature_json=saved.feature_json if saved else None,
                       model_version=saved.model_version if saved else None)
    result = summarize_event_calibration(rows)
    # Aggregate diagnostics in SQL: reporting exclusions must not require loading
    # every repeated forecast or applying the sample cap to the raw evidence.
    counts = (db.session.query(joined.c.exclusion, func.count(), func.count(func.distinct(joined.c.contract)))
              .group_by(joined.c.exclusion).all())
    exclusions = {reason: count for reason, count, _ in counts if reason is not None}
    eligible_count, resolved_contracts = next(((count, contracts) for reason, count, contracts in counts
                                              if reason is None), (0, 0))
    if eligible_count > resolved_contracts:
        exclusions['repeated_contract_forecast'] = eligible_count - resolved_contracts
    result.update({'forecast_rows_examined': sum(count for _, count, _ in counts),
                   'sampled_forecasts': len(rows), 'eligible_resolved_contracts': resolved_contracts,
                   'exclusions': exclusions, 'contract_limit': limit, 'row_limit': limit,
                   'truncated': len(entries) > limit, 'scope_start': utc(started_at).isoformat(),
                   'coverage_note': 'Earliest valid forecast per resolved contract in the current run, capped at the displayed contract limit after validation and deduplication. Exclusion counts cover joined forecast/outcome rows across the run, including duplicate outcome records. Unresolved/unproven outcomes are excluded; resolution coverage may bias the sample.'})
    return result
