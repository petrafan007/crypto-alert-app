"""Bounded, two-stage provider verification of legacy date-only settlements.

Collection uses a short read connection and makes provider calls after closing
it. Preview/application uses only the collected evidence, never network I/O.
The caller reviews the preview and owns the application transaction/commit.
"""
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import select

from core.extensions import db
from event_algo_models import EventContractOutcome as Outcome, EventStrategyOrder as Order
from services.event_market_timing import observation_time
from services.event_settlement_data import confirmed_kalshi_settlement, validated_kalshi_market
from services.event_settlement_timing import is_date_only, settlement_timing


def _snapshot(row, table):
    result = {}
    for column in table.columns:
        value = row[column.name] if isinstance(row, Mapping) else getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


def _legacy_defect(before):
    try:
        raw = json.loads(before['raw_json'])
    except (TypeError, ValueError):
        return False
    old, cutoff = observation_time(before['settlement_at']), observation_time(before['cutoff_at'])
    return (before['settlement_status'] == 'RESOLVED' and before['resolved_source'] == 'WEBULL_EVENT_MARKET'
            and before['outcome'] in ('YES', 'NO') and isinstance(raw, dict)
            and not raw.get('_settlement_timing') and is_date_only(raw.get('payout_date'))
            and old is not None and cutoff is not None and old < cutoff
            and observation_time(raw['payout_date']) == old)


def collect_legacy_settlement_evidence(user_id, *, limit=100, after_id=0):
    """Return a serializable plan; does not write or hold DB locks during HTTP."""
    if (isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0
            or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000
            or isinstance(after_id, bool) or not isinstance(after_id, int) or after_id < 0):
        raise ValueError('Positive user, limit 1..1000 and nonnegative cursor required')
    query = select(Outcome.__table__).where(
        Outcome.user_id == user_id, Outcome.id > after_id, Outcome.settlement_status == 'RESOLVED',
        Outcome.settlement_at < Outcome.cutoff_at).order_by(Outcome.id).limit(limit+1)
    with db.engine.connect() as connection:
        rows = connection.execute(query).mappings().all()
    plan = {'version': 1, 'user_id': user_id, 'examined': min(len(rows), limit),
            'truncated': len(rows) > limit, 'last_id': after_id, 'not_date_only_defect': 0, 'records': []}
    for row in rows[:limit]:
        before = _snapshot(row, Outcome.__table__)
        plan['last_id'] = before['id']
        if not _legacy_defect(before):
            plan['not_date_only_defect'] += 1
            continue
        provider, error = None, None
        try:
            provider = confirmed_kalshi_settlement(before['contract_symbol'], observation_time(before['cutoff_at']))
        except Exception as exc:
            # Store the error type, never exception text containing request data.
            error = type(exc).__name__
        plan['records'].append({'before': before, 'provider': provider, 'error': error,
                                'verified_at': datetime.now(timezone.utc).isoformat()})
    return plan


def repair_verified_legacy_settlements(plan, *, user_id, apply=False):
    """Preview by default; only same-outcome, unchanged, proven rows may change."""
    if (isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0
            or plan.get('version') != 1 or plan.get('user_id') != user_id or len(plan.get('records', [])) > 1000):
        raise ValueError('Invalid or cross-user repair plan')
    if db.session.new or db.session.dirty or db.session.deleted:
        raise ValueError('Repair requires a session without pending writes')
    report = {'apply': bool(apply), 'examined': plan['examined'], 'truncated': plan['truncated'],
              'last_id': plan['last_id'], 'eligible_outcomes': 0, 'matching_orders': 0,
              'updated_outcomes': 0, 'updated_orders': 0, 'skipped': {}, 'conflicts': []}
    skipped = Counter()
    if plan['not_date_only_defect']:
        skipped['not_date_only_defect'] = plan['not_date_only_defect']
    seen = set()
    for item in plan['records']:
        before = item['before']
        if before['user_id'] != user_id:
            raise ValueError('Cross-user evidence in repair plan')
        if before['id'] in seen:
            skipped['duplicate_plan_record'] += 1
            continue
        seen.add(before['id'])
        provider = item.get('provider')
        verified = observation_time(item.get('verified_at'))
        if not isinstance(provider, dict) or not provider:
            skipped['provider_unavailable'] += 1
            continue
        proof = validated_kalshi_market(before['contract_symbol'], before['cutoff_at'],
                                         provider.get('market'), verified)
        allowed_urls = {f'https://external-api.kalshi.com/trade-api/v2/{path}/{quote(before["contract_symbol"], safe="")}'
                        for path in ('markets', 'historical/markets')}
        if (not proof or verified > datetime.now(timezone.utc) or provider.get('source_url') not in allowed_urls
                or not _legacy_defect(before)):
            skipped['invalid_provider_evidence'] += 1
            continue
        if proof['settled_outcome'] != before['outcome']:
            skipped['outcome_conflict'] += 1
            report['conflicts'].append({'id': before['id'], 'contract_symbol': before['contract_symbol'],
                                        'saved': before['outcome'], 'provider': proof['settled_outcome']})
            continue
        query = Outcome.query.filter_by(id=before['id'], user_id=user_id).populate_existing()
        row = query.with_for_update().one_or_none() if apply else query.one_or_none()
        if row is None or _snapshot(row, Outcome.__table__) != before:
            skipped['changed_or_missing_outcome'] += 1
            continue
        orders_query = Order.query.filter_by(user_id=user_id, contract_symbol=row.contract_symbol,
            mode='PAPER', status='SIMULATED_SETTLED', settled_at=row.settlement_at).populate_existing()
        if row.config_id is not None:
            orders_query = orders_query.filter_by(config_id=row.config_id)
        orders_query = orders_query.order_by(Order.id)
        orders = orders_query.with_for_update().all() if apply else orders_query.all()
        report['eligible_outcomes'] += 1
        report['matching_orders'] += len(orders)
        if apply:
            selected, timing = settlement_timing(proof, row.cutoff_at, verified)
            timing['repair'] = {'release': '2.99.21', 'repaired_at': datetime.now(timezone.utc).isoformat(),
                                'previous_outcome': before,
                                'previous_orders': [_snapshot(order, Order.__table__) for order in orders]}
            row.raw_json = json.dumps({**proof, 'source_url': provider['source_url'], '_settlement_timing': timing})
            row.settlement_at = selected
            row.settlement_price = proof['settlement_price']
            row.provider_timestamp = selected
            row.observed_at = verified.replace(tzinfo=None)
            row.resolved_source = 'KALSHI_FINALIZED_MARKET'
            for order in orders:
                order.settled_at = selected
            report['updated_outcomes'] += 1
            report['updated_orders'] += len(orders)
            db.session.flush()
    report['skipped'] = dict(skipped)
    return report
