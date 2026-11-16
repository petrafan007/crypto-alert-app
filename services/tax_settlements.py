"""Record settlement results for Event contracts held to expiry, for the tax report.

The strategy engine records outcomes only for contracts it tracked. Contracts
bought by hand and held to settlement would otherwise stay "result unknown"
in the tax report. This job looks each one up by exact ticker from the
listing exchange's public, finalized result and stores it.
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.extensions import db

logger = logging.getLogger(__name__)

MAX_LOOKUPS_PER_RUN = 25


def held_to_expiry_contracts(user_id, now=None):
    """Event tickers this user still held after their contract date, without a recorded result."""
    from models import WebullOrder
    from event_algo_models import EventContractOutcome
    from routes.portfolio import _event_contract_date
    now = now or datetime.utcnow()
    held = defaultdict(float)
    for order in WebullOrder.query.filter_by(user_id=user_id).all():
        if str(order.instrument_type or '').upper() != 'EVENT' or float(order.filled_quantity or 0) <= 0:
            continue
        sign = -1 if str(order.side or '').upper().startswith('SELL') else 1
        held[str(order.symbol).upper()] += sign * float(order.filled_quantity)
    pending = []
    for symbol, quantity in held.items():
        expiry = _event_contract_date(symbol)
        if quantity <= 1e-9 or not expiry or expiry + timedelta(days=1) > now:
            continue
        resolved = EventContractOutcome.query.filter(
            EventContractOutcome.contract_symbol == symbol,
            EventContractOutcome.settlement_status == 'RESOLVED',
            EventContractOutcome.outcome.isnot(None),
        ).first()
        if not resolved:
            pending.append(symbol)
    return sorted(pending)


def resolve_held_event_settlements(user_id, now=None, lookup=None):
    """Look up and store finalized results; returns (resolved, still_unknown)."""
    from event_algo_models import EventContractOutcome
    from services.event_settlement_data import kalshi_settlement_for_ticker
    lookup = lookup or kalshi_settlement_for_ticker
    resolved, unknown = [], []
    for symbol in held_to_expiry_contracts(user_id, now)[:MAX_LOOKUPS_PER_RUN]:
        try:
            evidence = lookup(symbol, datetime.now(timezone.utc))
        except Exception:
            logger.warning('Settlement lookup failed for %s', symbol, exc_info=True)
            unknown.append(symbol)
            continue
        if not evidence:
            unknown.append(symbol)
            continue
        settled_at = datetime.fromisoformat(evidence['payout_date']).astimezone(timezone.utc).replace(tzinfo=None)
        close_time = datetime.fromisoformat(evidence['market']['close_time'].replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        db.session.add(EventContractOutcome(
            user_id=user_id, contract_symbol=symbol, outcome=evidence['settled_outcome'],
            settlement_status='RESOLVED', provider_timestamp=settled_at, observed_at=datetime.utcnow(),
            cutoff_at=close_time, settlement_at=settled_at, settlement_price=evidence['settlement_price'],
            resolved_source='KALSHI_FINALIZED_MARKET',
            raw_json=json.dumps({'source_url': evidence.get('source_url'), 'market': evidence['market']}, default=str),
        ))
        resolved.append(symbol)
    db.session.commit()
    if resolved:
        logger.info('Recorded %s Event settlement result(s) for user %s', len(resolved), user_id)
    return resolved, unknown


def resolve_for_all_users():
    from models import WebullOrder
    user_ids = [row[0] for row in db.session.query(WebullOrder.user_id).filter(
        WebullOrder.instrument_type.ilike('event')).distinct().all()]
    for user_id in user_ids:
        resolve_held_event_settlements(user_id)
