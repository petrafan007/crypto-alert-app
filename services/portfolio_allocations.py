"""Shared server allocation policy: relative preferences versus effective targets."""
import math
import re

MODULES = ('equities', 'options', 'crypto', 'futures', 'events')
DEFAULT_WEIGHTS = dict(zip(MODULES, (35, 25, 20, 10, 10)))


def parse_cagr_range(value):
    """Parse a saved ``"12%–16%"`` sleeve target into its numeric bounds.

    The sleeve ranges are stored as display strings, which made them
    unreadable by any logic. Parsing them lets the engine reconcile the
    per-sleeve targets with the portfolio-level annual target instead of
    displaying two numbers that contradict each other.
    """
    if value is None:
        return None
    text = str(value)
    # A hyphen or en-dash between two numbers separates a range. Without
    # this, "20%-35%" parses the second bound as a negative number.
    match = re.search(r'(\d+(?:\.\d+)?)\s*%?\s*[–—\-~]\s*(\d+(?:\.\d+)?)', text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
    else:
        numbers = re.findall(r'\d+(?:\.\d+)?', text)
        if not numbers:
            return None
        low = float(numbers[0])
        high = float(numbers[1]) if len(numbers) > 1 else low
    if high < low:
        low, high = high, low
    return (low, high)


def sleeve_cagr_midpoints(settings):
    """The midpoint of each enabled module's saved sleeve CAGR target."""
    result = {}
    for module in MODULES:
        bounds = parse_cagr_range(settings.get(module, {}).get('target_cagr_range'))
        if bounds:
            result[module] = (bounds[0] + bounds[1]) / 2
    return result


def blended_sleeve_target(settings):
    """Weighted portfolio CAGR implied by the sleeve targets and allocations.

    A sleeve target is the return expected of the capital assigned to that
    sleeve, not of the whole book. The portfolio-level target is therefore
    the allocation-weighted blend of the sleeve midpoints. Computing it
    makes the relationship between the two numbers explicit instead of
    leaving a reader to compare an unweighted sum against the portfolio
    figure.
    """
    midpoints = sleeve_cagr_midpoints(settings)
    if not midpoints:
        return None
    weights = normalize_allocations(
        {m: settings.get(m, {}).get('allocation_preference') or DEFAULT_WEIGHTS[m]
         for m in MODULES}, settings)
    total = sum(weights[m] for m in MODULES if m in midpoints)
    if total <= 0:
        return None
    return sum(weights[m] * midpoints[m] for m in midpoints) / total


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
