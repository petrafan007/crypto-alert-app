"""Read-only, user-scoped contract context for every Positions table."""
import json
from datetime import timezone
from event_algo_models import EventMarketSnapshot, EventContractOutcome


def _iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z') if value else None


def _object(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def apply_event_metadata(row, snapshot=None, outcome=None):
    """Enrich display context without changing prices, holdings, or purchased sides."""
    market = _object(snapshot.raw_json) if snapshot else {}
    row['event_title'] = market.get('name') or market.get('title') or row.get('display_name')
    rules = market.get('provider_rules') or market.get('yes_condition') or market.get('description')
    row['event_rules'] = rules if isinstance(rules, str) else None
    row['event_threshold'] = market.get('target_value')
    existing = row.get('settlement') or {}
    cutoff = (outcome.cutoff_at if outcome and outcome.cutoff_at else snapshot.cutoff_at if snapshot else None)
    row['settlement'] = {
        **existing,
        'status': outcome.settlement_status if outcome else existing.get('status', 'UNKNOWN'),
        'cutoff_at': _iso(cutoff) or existing.get('cutoff_at'),
        'expected_at': market.get('expected_exp_date') or existing.get('expected_at'),
        'confirmed_outcome': outcome.outcome if outcome and outcome.settlement_status == 'RESOLVED' else existing.get('confirmed_outcome'),
        'last_attempt_at': _iso(outcome.observed_at) if outcome else existing.get('last_attempt_at'),
    }
    return row


def enrich_event_positions(user_id, rows):
    from sqlalchemy import func
    from core.extensions import db

    events = [row for row in rows if 'EVENT' in str(row.get('instrument_type', '')).upper()]
    if not events:
        return rows
    # Test positions may append the purchased side to the contract symbol.
    symbols = {str(row.get('symbol', '')).upper().removesuffix(' YES').removesuffix(' NO') for row in events}

    def latest(model):
        ids = db.session.query(func.max(model.id)).filter(model.user_id == user_id, model.contract_symbol.in_(symbols)).group_by(model.contract_symbol)
        return {record.contract_symbol: record for record in model.query.filter(model.user_id == user_id, model.id.in_(ids)).all()}

    snapshots, outcomes = latest(EventMarketSnapshot), latest(EventContractOutcome)
    for row in events:
        symbol = str(row.get('symbol', '')).upper().removesuffix(' YES').removesuffix(' NO')
        apply_event_metadata(row, snapshots.get(symbol), outcomes.get(symbol))
    return rows
