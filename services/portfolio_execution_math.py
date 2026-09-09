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
                   unit=None, max_loss=None, cost_multiplier=1.0):
    """Quantity after caller's cash/module/position budget and optional loss cap.

    ``price`` is the already-slipped execution price. ``max_loss`` is the
    remaining futures daily risk allowance, when applicable. Callers retain
    ownership, capacity, duplicate-signal, and kill-switch enforcement.
    """
    unit = price * multiplier if unit is None else unit
    if unit <= 0 or budget <= 0:
        return 0
    fee = costs(module, price, 1, cost_multiplier)
    quantity = budget / (unit + fee)
    risk = abs(price - stop) * multiplier if stop is not None else unit
    if risk > 0:
        quantity = min(quantity, max(0, equity) * 0.005 / (risk + 2 * fee))
    if max_loss is not None:
        quantity = min(quantity, max(0, max_loss) / (risk + 2 * fee))
    if module == 'events':
        quantity = min(quantity, 50.0)
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
