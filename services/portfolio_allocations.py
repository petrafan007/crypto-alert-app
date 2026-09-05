"""Shared server allocation policy: relative preferences versus effective targets."""
import math

MODULES = ('equities', 'options', 'crypto', 'futures', 'events')
DEFAULT_WEIGHTS = dict(zip(MODULES, (35, 25, 20, 10, 10)))


def normalize_allocations(weights, settings):
    active = [m for m in MODULES if settings[m]['enabled']]
    result = {m: 0.0 for m in MODULES}
    if not active:
        return result
    total = sum(weights[m] for m in active)
    if not total:
        weights = {m: settings[m].get('allocation_preference') or DEFAULT_WEIGHTS[m] for m in MODULES}
        total = sum(weights[m] for m in active)
    quotas = {m: weights[m] / total * 10000 for m in active}
    units = {m: math.floor(quotas[m] + 1e-8) for m in active}
    ranked = sorted(active, key=lambda m: (-(quotas[m] - units[m]), MODULES.index(m)))
    for module in ranked[:10000 - sum(units.values())]:
        units[module] += 1
    result.update({m: units[m] / 100 for m in active})
    return result
