"""Saved Event limits and deterministic, fee-inclusive entry allowances."""
import json
import math
from datetime import timedelta

from services.portfolio_strategy_signals import ET, utc


DEFAULT_RISK_CONFIG = {
    'max_dollars_per_trade': 10.0,
    'max_open_dollars': 30.0,
    'max_open_positions': 3,
    'max_hourly_loss': 15.0,
    'max_daily_loss': 25.0,
    'max_drawdown': 35.0,
    'max_contracts_per_trade': 50,
    'max_spread': 0.15,
    'min_volume': 0.0,
    'min_time_remaining_seconds': 60,
    'max_time_remaining_seconds': 86400,
}


def normalize_risk_config(value):
    """Missing keys use defaults; malformed saved limits never disable gates."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError('Event risk configuration is invalid JSON.') from exc
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('Event risk configuration must be an object.')
    result = {**DEFAULT_RISK_CONFIG, **value}
    for key in DEFAULT_RISK_CONFIG:
        raw = result[key]
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Event risk limit {key} must be a finite nonnegative number.') from exc
        if isinstance(raw, bool) or not math.isfinite(number) or number < 0:
            raise ValueError(f'Event risk limit {key} must be a finite nonnegative number.')
        if key in ('max_open_positions', 'max_contracts_per_trade'):
            if not number.is_integer():
                raise ValueError(f'Event risk limit {key} must be a whole number.')
            number = int(number)
        result[key] = number
    if result['min_time_remaining_seconds'] > result['max_time_remaining_seconds']:
        raise ValueError('Event minimum time remaining cannot exceed its maximum.')
    return result


def entry_allowance(risk, lots, now):
    """Caller supplies only the user's current-generation Event lots under lock.

    Dollar exposure includes entry fees. Loss allowances reserve all open
    stakes plus entry and estimated exit fees, without crediting unrealized
    gains. Hourly is rolling; daily starts at Eastern midnight. Drawdown is
    measured from the closed-trade net-P&L high-water mark for this generation.
    """
    now = utc(now)
    day_start = now.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    opened = [lot for lot in lots if lot.closed_at is None]
    closed = sorted((lot for lot in lots if lot.closed_at is not None),
                    key=lambda lot: (utc(lot.closed_at), lot.id))
    exposure = sum(lot.collateral + lot.entry_fee for lot in opened)
    open_risk = sum(lot.collateral + 2 * lot.entry_fee for lot in opened)
    hourly = daily = cumulative = peak = 0.0
    for lot in closed:
        stamp = utc(lot.closed_at)
        pnl = float(lot.realized_pnl)
        if not math.isfinite(pnl) or stamp > now:
            raise ValueError('Event realized risk history contains an invalid value or future close.')
        cumulative += pnl
        peak = max(peak, cumulative)
        if stamp >= now - timedelta(hours=1):
            hourly += pnl
        if stamp >= day_start:
            daily += pnl
    if not math.isfinite(exposure) or not math.isfinite(open_risk) or exposure < 0 or open_risk < 0:
        raise ValueError('Event open risk history is invalid.')
    loss_remaining = min(
        risk['max_hourly_loss'] + min(0.0, hourly),
        risk['max_daily_loss'] + min(0.0, daily),
        risk['max_drawdown'] - max(0.0, peak - cumulative),
    ) - open_risk
    budget = min(risk['max_dollars_per_trade'], risk['max_open_dollars'] - exposure)
    reason = None
    if len(opened) >= risk['max_open_positions']:
        reason = 'Saved Event open-position limit reached, including pending settlements.'
    elif budget <= 0 or risk['max_contracts_per_trade'] <= 0:
        reason = 'Saved Event dollar exposure or contract limit leaves no entry allowance.'
    elif loss_remaining <= 0:
        reason = 'Saved Event hourly, daily or drawdown loss allowance is exhausted after reserving open risk.'
    return {
        'limits': risk, 'open_positions': len(opened), 'open_dollars': exposure,
        'reserved_loss': open_risk, 'hourly_realized_pnl': hourly, 'daily_realized_pnl': daily,
        'realized_drawdown': max(0.0, peak - cumulative),
        'entry_budget': max(0.0, budget), 'remaining_loss_allowance': max(0.0, loss_remaining),
        'reason': reason,
    }
