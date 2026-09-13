"""Select evidence-backed settlement times and repair the old date-only defect."""
import json
import re
from collections import Counter
from datetime import datetime, timezone

from services.event_market_timing import observation_time


def is_date_only(value):
    return isinstance(value, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value.strip()))


def settlement_timing(raw, cutoff_at, observed_at):
    """A calendar payout date cannot establish an exact settlement instant."""
    cutoff, observed = observation_time(cutoff_at), observation_time(observed_at)
    if cutoff is None or observed is None or observed < cutoff:
        raise ValueError('Settlement requires a confirmation observed at or after cutoff')
    value = raw.get('payout_date')
    parsed = None
    reason = 'MISSING_PAYOUT_TIME'
    if is_date_only(value):
        reason = 'DATE_ONLY_PAYOUT'
    elif value not in (None, ''):
        # Numeric epochs and explicit offsets establish a timezone; a naive
        # timestamp or date cannot silently acquire a UTC timezone here.
        try:
            float(value)
            precise = not isinstance(value, bool)
        except (TypeError, ValueError):
            try:
                stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                precise = stamp.tzinfo is not None and stamp.utcoffset() is not None
            except (TypeError, ValueError):
                precise = False
        parsed = observation_time(value) if precise else None
        reason = 'INVALID_OR_AMBIGUOUS_PAYOUT_TIME'
        if parsed is not None:
            reason = 'PAYOUT_BEFORE_CUTOFF' if parsed < cutoff else 'PAYOUT_AFTER_OBSERVATION' if parsed > observed else None
    selected = parsed if reason is None else observed
    evidence = {'version': 1, 'basis': 'PROVIDER_PAYOUT_TIMESTAMP' if reason is None else 'OBSERVED_RESOLUTION',
                'reason': reason, 'selected_at': selected.isoformat(), 'observed_at': observed.isoformat(),
                'provider_payout_value': value}
    return selected.replace(tzinfo=None), evidence


def repair_date_only_settlements(*, apply=False, user_id=None, limit=1000):
    """Dry-run by default; preserve old values and modify no monetary fields.

    Only the exact date-only-to-midnight defect with matching saved resolution
    evidence is eligible. Repeat calls are safe; callers commit the transaction.
    """
    from core.extensions import db
    from event_algo import extract_settled_outcome
    from event_algo_models import EventContractOutcome as Outcome, EventStrategyOrder as Order

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise ValueError('Repair batch limit must be between 1 and 10000')
    query = Outcome.query.filter(Outcome.settlement_status == 'RESOLVED', Outcome.settlement_at < Outcome.cutoff_at)
    if user_id is not None:
        query = query.filter(Outcome.user_id == user_id)
    query = query.order_by(Outcome.id).limit(limit+1)
    if apply:
        query = query.with_for_update(skip_locked=True)
    candidates = query.all()
    report = {'apply': bool(apply), 'examined': min(len(candidates), limit), 'eligible_outcomes': 0,
              'matching_orders': 0, 'updated_outcomes': 0, 'updated_orders': 0,
              'truncated': len(candidates) > limit, 'skipped': {}}
    skipped = Counter()
    for row in candidates[:limit]:
        try:
            raw = json.loads(row.raw_json)
        except (TypeError, ValueError):
            skipped['invalid_saved_evidence'] += 1
            continue
        if not isinstance(raw, dict) or not is_date_only(raw.get('payout_date')):
            skipped['not_date_only_defect'] += 1
            continue
        original = observation_time(raw['payout_date'])
        if original is None or original.replace(tzinfo=None) != row.settlement_at:
            skipped['original_timestamp_mismatch'] += 1
            continue
        if raw.get('_settlement_timing'):
            skipped['already_annotated'] += 1
            continue
        if (not row.resolved_source or row.outcome not in ('YES', 'NO')
                or extract_settled_outcome(raw) != row.outcome):
            skipped['unverified_resolution'] += 1
            continue
        try:
            selected, evidence = settlement_timing(raw, row.cutoff_at, row.observed_at)
        except ValueError:
            skipped['invalid_observation_time'] += 1
            continue
        orders_query = Order.query.filter(Order.user_id == row.user_id, Order.contract_symbol == row.contract_symbol,
                                          Order.status == 'SIMULATED_SETTLED', Order.settled_at == row.settlement_at)
        if row.config_id is not None:
            orders_query = orders_query.filter(Order.config_id == row.config_id)
        orders = orders_query.order_by(Order.id).with_for_update().all() if apply else orders_query.all()
        report['eligible_outcomes'] += 1
        report['matching_orders'] += len(orders)
        if apply:
            evidence['repair'] = {
                'release': '2.99.20', 'repaired_at': datetime.now(timezone.utc).isoformat(),
                'previous_settlement_at': observation_time(row.settlement_at).isoformat(),
                'previous_updated_at': observation_time(row.updated_at).isoformat(),
                'orders': [{'id': order.id, 'previous_settled_at': observation_time(order.settled_at).isoformat(),
                            'previous_updated_at': observation_time(order.updated_at).isoformat()} for order in orders],
            }
            row.settlement_at = selected
            row.raw_json = json.dumps({**raw, '_settlement_timing': evidence}, default=str)
            for order in orders:
                order.settled_at = selected
            report['updated_outcomes'] += 1
            report['updated_orders'] += len(orders)
    report['skipped'] = dict(skipped)
    if apply:
        db.session.flush()
    return report
