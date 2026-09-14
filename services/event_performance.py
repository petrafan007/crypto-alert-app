"""Read-only, evidence-scoped performance for the legacy Event paper ledger."""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import tuple_

from event_algo_models import EventContractOutcome as Outcome, EventStrategyDecision as Decision, EventStrategyOrder as Order
from services.event_market_timing import observation_time


def _number(value):
    try:
        result = float(value)
        return result if not isinstance(value, bool) and math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _object(value):
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def _resolution(order, candidates, now):
    from event_algo import extract_settled_outcome
    if not candidates:
        return None, 'missing_settlement_evidence'
    # Conflicting saved results need review, not an arbitrary latest-row winner.
    if len({row.outcome for row in candidates if row.outcome in ('YES', 'NO')}) > 1:
        return None, 'conflicting_settlement_evidence'
    submitted, closed = observation_time(order.submitted_at), observation_time(order.settled_at)
    for row in candidates:
        cutoff, settled, observed = map(observation_time, (row.cutoff_at, row.settlement_at, row.observed_at))
        raw = _object(row.raw_json)
        if (row.outcome not in ('YES', 'NO') or not str(row.resolved_source or '').strip()
                or isinstance(raw.get('settlement_price'), bool) or extract_settled_outcome(raw) != row.outcome):
            continue
        if (cutoff and settled and observed and submitted < cutoff <= settled <= observed <= now
                and closed == settled):
            return row.outcome, None
    return None, 'invalid_settlement_evidence'


def _duration(decision, order):
    if decision is None or decision.config_id != order.config_id or decision.contract_symbol != order.contract_symbol:
        return 'Unknown duration'
    details = _object(decision.feature_json).get('contract_details')
    label = details.get('duration_label') if isinstance(details, dict) else None
    return label.strip() if isinstance(label, str) and 0 < len(label.strip()) <= 80 else 'Unknown duration'


def legacy_performance(user_id, *, config=None, limit=500):
    """Report the latest bounded order sample; never rewrite historical P&L."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
        raise ValueError('Performance limit must be a whole number between 1 and 2000.')
    if config is not None and (config.user_id != user_id or config.id is None):
        raise ValueError('Event configuration is unavailable for this user.')
    now = datetime.now(timezone.utc)
    query = Order.query.filter_by(user_id=user_id, mode='PAPER')
    if config is not None:
        query = query.filter_by(config_id=config.id)
    total = query.count()
    orders = query.order_by(Order.submitted_at.desc(), Order.id.desc()).limit(limit).all()
    keys = {(row.config_id, row.contract_symbol) for row in orders}
    outcomes = defaultdict(list)
    if keys:
        for row in Outcome.query.filter(Outcome.user_id == user_id, Outcome.settlement_status == 'RESOLVED',
                                       tuple_(Outcome.config_id, Outcome.contract_symbol).in_(keys)).all():
            outcomes[(row.config_id, row.contract_symbol)].append(row)
    ids = [row.decision_id for row in orders if row.decision_id is not None]
    decisions = {row.id: row for row in Decision.query.filter(Decision.user_id == user_id, Decision.id.in_(ids)).all()} if ids else {}
    exclusions, settled = Counter(), []
    pending = discrepancies = 0
    for order in orders:
        if order.status not in ('SIMULATED_FILLED', 'SIMULATED_PENDING', 'SIMULATED_SETTLED'):
            exclusions['unsupported_order_status'] += 1
            continue
        if order.side != 'BUY' or order.outcome not in ('YES', 'NO'):
            exclusions['unsupported_order_side_or_outcome'] += 1
            continue
        quantity, requested, price, fee = map(_number, (order.filled_quantity, order.quantity, order.filled_price, order.fee))
        if quantity == 0:
            exclusions['unfilled_order'] += 1
            continue
        if (quantity is None or requested is None or not 0 < quantity <= requested
                or not quantity.is_integer() or not requested.is_integer()
                or price is None or not 0 < price < 1 or fee is None or fee < 0):
            exclusions['invalid_fill_values'] += 1
            continue
        submitted, closed = observation_time(order.submitted_at), observation_time(order.settled_at)
        if submitted is None or submitted > now:
            exclusions['invalid_submission_time'] += 1
            continue
        if order.status != 'SIMULATED_SETTLED':
            if closed is not None:
                exclusions['inconsistent_settlement_status'] += 1
            else:
                pending += 1
            continue
        if closed is None or not submitted <= closed <= now:
            exclusions['invalid_settlement_time'] += 1
            continue
        outcome, reason = _resolution(order, outcomes[(order.config_id, order.contract_symbol)], now)
        if reason:
            exclusions[reason] += 1
            continue
        # Compute from the actual fill and recorded $1/contract settlement.
        # A default zero in realized_pnl is not evidence of a breakeven trade.
        gross = (quantity if order.outcome == outcome else 0.0) - quantity * price
        pnl = round(gross - fee, 8)
        if not math.isfinite(pnl) or not math.isfinite(gross):
            exclusions['invalid_fill_values'] += 1
            continue
        stored = _number(order.realized_pnl)
        discrepancies += int(stored is None or abs(stored - pnl) > 1e-8)
        settled.append({'id': order.id, 'closed_at': closed, 'pnl': pnl, 'gross': gross, 'fee': fee,
                        'outcome_won': order.outcome == outcome, 'duration': _duration(decisions.get(order.decision_id), order)})
    # The equity path follows settlement chronology, not entry or query order.
    settled.sort(key=lambda item: (item['closed_at'], item['id']))
    pnls = [item['pnl'] for item in settled]
    profit, loss = sum(value for value in pnls if value > 0), sum(value for value in pnls if value < 0)
    running = peak = drawdown = 0.0
    by_duration = {}
    for item in settled:
        running += item['pnl']
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
        bucket = by_duration.setdefault(item['duration'], {'duration': item['duration'], 'trades': 0,
            'wins': 0, 'losses': 0, 'breakeven': 0, 'net_pnl': 0.0})
        bucket['trades'] += 1
        bucket['wins'] += int(item['pnl'] > 0)
        bucket['losses'] += int(item['pnl'] < 0)
        bucket['breakeven'] += int(item['pnl'] == 0)
        bucket['net_pnl'] += item['pnl']
    return {
        'mode': 'PAPER', 'ledger': 'LEGACY_EVENT',
        'scope': {'user_id': user_id, 'config_id': config.id if config is not None else None},
        'sample': {'limit': limit, 'total_orders': total, 'examined_orders': len(orders),
                   'omitted_orders': max(0, total-len(orders)), 'truncated': total > len(orders),
                   'order': 'NEWEST_SUBMITTED_FIRST',
                   'oldest_submitted_at': observation_time(orders[-1].submitted_at).isoformat() if orders else None,
                   'newest_submitted_at': observation_time(orders[0].submitted_at).isoformat() if orders else None},
        'status': 'READY' if settled else 'NO_VERIFIED_SETTLEMENTS' if orders else 'EMPTY',
        'trades': len(settled), 'pending': pending, 'excluded': sum(exclusions.values()),
        'exclusions': dict(sorted(exclusions.items())), 'stored_pnl_discrepancies': discrepancies,
        'pnl_basis': 'RECONSTRUCTED_SETTLED_FILLS', 'drawdown_basis': 'SELECTED_SETTLEMENT_ORDER',
        'wins': sum(value > 0 for value in pnls), 'losses': sum(value < 0 for value in pnls),
        'breakeven': sum(value == 0 for value in pnls), 'outcome_wins': sum(item['outcome_won'] for item in settled),
        'gross_profit': round(profit, 8) if settled else None, 'gross_loss': round(loss, 8) if settled else None,
        'gross_pnl': round(sum(item['gross'] for item in settled), 8) if settled else None,
        'fees': round(sum(item['fee'] for item in settled), 8) if settled else None,
        'net_pnl': round(sum(pnls), 8) if settled else None,
        'max_drawdown': round(drawdown, 8) if settled else None,
        'profit_factor': round(profit / abs(loss), 6) if loss else None,
        'expectancy': round(sum(pnls) / len(pnls), 8) if pnls else None,
        'by_duration': [{**bucket, 'net_pnl': round(bucket['net_pnl'], 8)}
                        for bucket in sorted(by_duration.values(), key=lambda row: (-row['trades'], row['duration']))],
        'generated_at': now.isoformat().replace('+00:00', 'Z'),
    }
