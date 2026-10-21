"""Shared deterministic paper-fill, sizing, and spot-exit rules.

The live ledger and historical replay use these same functions. Multipliers
other than one are explicit replay stress assumptions, not broker estimates.
"""
import math


def costs(module, price, quantity, cost_multiplier=1.0):
    if module == 'options':
        return 1.30 * quantity * cost_multiplier
    if module == 'futures':
        return 1.25 * quantity * cost_multiplier
    if module == 'events':
        return 0.015 * quantity * cost_multiplier
    return price * quantity * 0.001 * cost_multiplier


def fill_price(module, price, side, closing=False, slippage_multiplier=1.0):
    if module in ('options', 'events'):
        return price
    buy = (side == 'LONG') != closing
    return price * (1 + (0.0005 if buy else -0.0005) * slippage_multiplier)


def entry_quantity(module, price, budget, equity, stop=None, *, multiplier=1,
                   unit=None, max_loss=None, cost_multiplier=1.0, max_contracts=50, risk_per_unit=None,
                   risk_cap_pct=None):
    """Quantity after caller's cash/module/position budget and optional loss cap.

    ``price`` is the already-slipped execution price. ``max_loss`` is the
    individual-entry risk allowance, when applicable. ``risk_per_unit`` is
    the maximum loss of a single unit when the instrument's own stop price
    does not describe that risk; it must be supplied for credit spreads,
    whose collateral is a margin requirement rather than an at-risk amount.
    ``risk_cap_pct`` overrides the per-trade loss cap as a fraction of
    portfolio equity.
    Callers retain ownership, capacity, duplicate-signal, and kill-switch
    enforcement.
    """
    unit = price * multiplier if unit is None else unit
    if unit <= 0 or budget <= 0:
        return 0
    fee = costs(module, price, 1, cost_multiplier)
    quantity = budget / (unit + fee)
    if risk_per_unit is not None:
        # The loss cap is applied to the amount actually at risk, not to the
        # collateral reserved to hold the position. ``risk_per_unit`` is
        # already expressed in cash per contract.
        risk = risk_per_unit
    elif stop is not None:
        risk = abs(price - stop) * multiplier
    else:
        risk = unit
    if risk > 0:
        cap_pct = 0.005 if risk_cap_pct is None else risk_cap_pct
        quantity = min(quantity, max(0, equity) * cap_pct / (risk + 2 * fee))
    if max_loss is not None:
        quantity = min(quantity, max(0, max_loss) / (risk + 2 * fee))
    if module == 'events':
        quantity = min(quantity, max(0, max_contracts))
    return math.floor(quantity * 1e6) / 1e6 if module == 'crypto' else math.floor(quantity)


def spot_exit(module, price, side, old_stop, signal):
    """Existing stop precedes trailing-stop updates, exactly as the live scan."""
    reason = 'STRATEGY_EXIT' if signal and signal.get('exit') else None
    if old_stop is not None and ((side == 'LONG' and price <= old_stop) or
                                 (side == 'SHORT' and price >= old_stop)):
        reason = 'STOP_LOSS'
    stop = old_stop
    if module == 'crypto' and signal and not reason:
        stop = max(old_stop or 0, signal['stop'])
    return reason, stop
