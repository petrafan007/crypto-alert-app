"""Deterministic, cash-flow-free paper-run progress against a research target.

This module does not forecast returns or infer unobserved prices. Inputs must be
from one reset generation. Deposits/withdrawals require a new run or an explicit
cash-flow-adjusted return implementation, not silently changed starting capital.
"""
import math
from datetime import datetime, timedelta, timezone


def _time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('A recorded run/valuation timestamp is required.')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _number(value, label):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{label} must be finite.')
    return result


def _annualized(equity, initial, days):
    if days < 30 or equity <= 0:
        return None
    exponent = math.log(equity / initial) * 365 / days
    return math.expm1(exponent) * 100 if abs(exponent) < 700 else None


def build_goal_tracking(*, initial_balance, current_equity, cash_balance,
                        target_annual_return, started_at, as_of, snapshots,
                        module_pnl=None, reserved_capital=0):
    """Return JSON-safe observed progress, not a likelihood of achieving a CAGR.

    ``snapshots`` contains recorded ``time``/``equity`` values. ``module_pnl``
    contains net realized plus unrealized P&L, including entry/exit costs and
    partial closes, for each module. An unexplained attribution residual is
    shown explicitly. Rolling anchors must be at/before the requested boundary
    and no more than 24 hours old; no interpolation or forward filling is used.
    """
    initial = _number(initial_balance, 'Initial balance')
    equity = _number(current_equity, 'Current equity')
    cash = _number(cash_balance, 'Cash balance')
    target = _number(target_annual_return, 'Annual target')
    if initial <= 0 or target <= -100:
        raise ValueError('Initial balance must be positive and annual target greater than -100%.')
    start, end = _time(started_at), _time(as_of)
    if end < start:
        raise ValueError('Valuation cannot precede the paper run.')
    days = (end-start).total_seconds()/86400
    target_at = lambda moment: initial * math.exp(math.log1p(target/100) * (moment-start).total_seconds()/86400/365)
    points, invalid = {}, 0
    for row in snapshots or []:
        try:
            timestamp, value = _time(row['time']), _number(row['equity'], 'Snapshot equity')
        except (ValueError, KeyError, TypeError, OverflowError):
            invalid += 1
            continue
        if start <= timestamp <= end:
            points[timestamp] = value
    ordered = sorted(points.items())
    observed_dates = {timestamp.date() for timestamp, _ in ordered}
    # Starting capital and the as-of valuation are recorded ledger facts, but do
    # not count as persisted daily snapshots or invent intervening history.
    expected = (end.date()-start.date()).days+1
    missing_dates = [start.date()+timedelta(days=offset) for offset in range(expected)
                     if start.date()+timedelta(days=offset) not in observed_dates]
    gaps = []
    for day in missing_dates:
        if gaps and day == gaps[-1][1]+timedelta(days=1):
            gaps[-1][1] = day
        else:
            gaps.append([day, day])
    curve_points = dict(ordered)
    curve_points.setdefault(start, initial)
    curve_points[end] = equity
    curve = [{'time': _iso(timestamp), 'equity': value, 'target_equity': target_at(timestamp)}
             for timestamp, value in sorted(curve_points.items())]
    # Keep endpoint and target comparisons useful without an unbounded API payload.
    if len(curve) > 2000:
        stride = math.ceil((len(curve)-2)/1998)
        curve = [curve[0], *curve[1:-1:stride], curve[-1]]
    anchors = dict(ordered)
    anchors.setdefault(start, initial)
    rolling = {}
    for window in (30, 90, 365):
        boundary = end-timedelta(days=window)
        eligible = [(time, value) for time, value in anchors.items() if time <= boundary]
        anchor = max(eligible, default=None)
        reason = None
        if days < window:
            reason = f'Requires {window} elapsed days in this paper run.'
        elif anchor is None or (boundary-anchor[0]).total_seconds() > 86400:
            reason = 'No observed valuation within 24 hours before the window boundary.'
        elif anchor[1] <= 0:
            reason = 'Window starting equity must be positive.'
        period_days = (end-anchor[0]).total_seconds()/86400 if anchor and not reason else None
        missing = sum(anchor[0].date() <= day <= end.date() for day in missing_dates) if anchor and not reason else None
        rolling[str(window)] = {
            'return_pct': (equity/anchor[1]-1)*100 if not reason else None,
            'target_return_pct': math.expm1(math.log1p(target/100)*period_days/365)*100 if not reason else None,
            'start_at': _iso(anchor[0]) if not reason else None,
            'actual_elapsed_days': period_days,
            'missing_calendar_days': missing,
            'reason': reason,
        }
    target_equity = target_at(end)
    annual = _annualized(equity, initial, days)
    contributions = []
    for module, value in sorted((module_pnl or {}).items()):
        net = _number(value, 'Module net P&L')
        contributions.append({'module': module, 'net_pnl': net,
                              'contribution_pct_points': net/initial*100})
    return {
        'mode': 'PAPER', 'target_annual_return_pct': target,
        'started_at': _iso(start), 'as_of': _iso(end), 'elapsed_days': days,
        'initial_equity': initial, 'current_equity': equity, 'target_equity': target_equity,
        'target_gap_usd': equity-target_equity,
        'target_gap_pct': (equity/target_equity-1)*100,
        'total_return_pct': (equity/initial-1)*100,
        'target_return_to_date_pct': (target_equity/initial-1)*100,
        'annualized_return_pct': annual,
        'cagr_gap_pct_points': annual-target if annual is not None else None,
        'annualization_min_days': 30,
        'annualization_status': 'DESCRIPTIVE_ONLY' if annual is not None else 'INSUFFICIENT_HISTORY',
        'annualization_note': 'Annualization is descriptive after 30 elapsed days, not statistical validation or a forecast. No cash flows are assumed within a reset generation.',
        'capital_utilization_pct': (equity-cash)/equity*100 if equity > 0 else None,
        'reserved_capital_usd': _number(reserved_capital, 'Reserved capital'),
        'cash_balance': cash,
        'module_contributions': contributions,
        'unattributed_pnl_usd': equity-initial-sum(item['net_pnl'] for item in contributions),
        'contribution_basis': 'Net module P&L divided by the paper-run starting balance; not standalone module CAGR.',
        'rolling_returns': rolling,
        'observations': {
            'snapshot_count': len(ordered), 'observed_calendar_days': len(observed_dates),
            'expected_calendar_days': expected, 'missing_calendar_days': len(missing_dates),
            'invalid_snapshot_count': invalid,
            'gap_ranges': [{'start': first.isoformat(), 'end': last.isoformat(), 'days': (last-first).days+1} for first, last in gaps],
            'coverage_note': 'UTC calendar-day coverage, including partial first/last days. Missing snapshots are not interpolated; endpoint returns do not prove intraperiod risk coverage.',
        },
        'curve': curve,
        'target_note': 'A hypothetical compounded research-target path, not a benchmark investment, measured opportunity cost, or predicted return.',
    }
