"""Walk-forward isotonic recalibration of Event model probabilities.

The raw Decision Engine probability is miscalibrated in ways that vary by
provider and market regime. Once enough contracts have verified resolutions,
a pool-adjacent-violators (PAV) map learned from those resolutions reshapes
new predictions before the entry gates see them.

Safety properties:
  * The map is fit only on contracts whose verified resolution already exists
    at fit time, and is applied only to predictions published afterwards, so
    no forecast is ever shaped by its own outcome (walk-forward safe).
  * Below the minimum sample count, or when every resolved contract had the
    same outcome, the raw probability passes through untouched.
  * The fit is deterministic: identical samples produce an identical map and
    version stamp regardless of input order.
  * Every calibrated decision archives the map version and the raw probability
    in its model metadata, so research can reconstruct exactly what was applied.
"""
import hashlib
import json
from datetime import datetime

MIN_CALIBRATION_SAMPLES = 50
REFIT_INTERVAL_SECONDS = 6 * 3600
RECHECK_INTERVAL_SECONDS = 3600


def _loads(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _stamp(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def fit_isotonic(samples):
    """Deterministic PAV fit returning monotone constant blocks.

    Each block is {'lower', 'upper', 'value', 'count'}: the pooled observed
    YES rate over the probability interval it covers.
    """
    ordered = sorted(((float(p), int(y)) for p, y in samples), key=lambda item: (item[0], item[1]))
    blocks = []
    for probability, outcome in ordered:
        blocks.append([outcome, 1, probability, probability])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            last = blocks.pop()
            previous = blocks[-1]
            previous[0] += last[0]
            previous[1] += last[1]
            previous[3] = last[3]
    return [{'lower': total[2], 'upper': total[3], 'value': total[0] / total[1], 'count': total[1]}
            for total in blocks]


def apply_isotonic(blocks, probability):
    """Piecewise-constant application: containing block, else nearest block."""
    if not blocks:
        return probability
    point = min(1.0, max(0.0, float(probability)))
    for block in blocks:
        if block['lower'] <= point <= block['upper']:
            return block['value']
    best_distance, best_value = None, None
    for block in blocks:
        distance = min(abs(point - block['lower']), abs(point - block['upper']))
        if best_distance is None or distance < best_distance:
            best_distance, best_value = distance, block['value']
    return best_value


def map_version(blocks, sample_count):
    payload = json.dumps({'blocks': blocks, 'sample_count': sample_count}, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]


def maybe_refit_calibration(user_id, config, now):
    """Refit the stored map when due; otherwise leave it untouched.

    Called once per Event scan before any prediction is published. The sample
    query only runs when the refit/recheck interval has elapsed.
    """
    stored = _loads(getattr(config, 'calibration_json', None))
    fitted_at, checked_at = _stamp(stored.get('fitted_at')), _stamp(stored.get('checked_at'))
    if fitted_at and (now - fitted_at).total_seconds() < REFIT_INTERVAL_SECONDS:
        return stored
    if not fitted_at and checked_at and (now - checked_at).total_seconds() < RECHECK_INTERVAL_SECONDS:
        return stored
    from services.portfolio_calibration import calibration_samples
    started_at = getattr(config, 'created_at', None) or datetime(2000, 1, 1)
    samples = calibration_samples(user_id, started_at)
    outcomes = {outcome for _, outcome in samples}
    if len(samples) < MIN_CALIBRATION_SAMPLES or len(outcomes) < 2:
        updated = {'status': 'AWAITING_SAMPLES', 'sample_count': len(samples),
                   'checked_at': now.isoformat(),
                   'policy': f'Requires at least {MIN_CALIBRATION_SAMPLES} verified resolved contracts '
                             'with both outcomes before a map is fit.'}
    else:
        blocks = fit_isotonic(samples)
        updated = {'status': 'FITTED', 'version': map_version(blocks, len(samples)),
                   'fitted_at': now.isoformat(), 'checked_at': now.isoformat(),
                   'sample_count': len(samples), 'blocks': blocks,
                   'scope_start': started_at.isoformat(),
                   'policy': 'Isotonic PAV fit on the earliest valid pre-cutoff forecast per verified '
                             'resolved contract. Fit uses only resolutions observed before fitted_at; '
                             'predictions published afterwards are shaped by this map.'}
    config.calibration_json = json.dumps(updated)
    return updated


def calibrate_market(market, config):
    """Shape a fresh prediction with the stored map, stamping provenance.

    Idempotent: the raw probability is archived in the stamp, so republishing
    a market never calibrates an already-calibrated value.
    """
    probability = market.get('model_probability_yes')
    if probability is None:
        return
    stored = _loads(getattr(config, 'calibration_json', None))
    blocks = stored.get('blocks') or []
    if not blocks:
        return
    metadata = dict(market.get('_model_metadata') or {})
    stamp = metadata.get('calibration') or {}
    raw = stamp.get('raw_probability_yes', probability)
    calibrated = apply_isotonic(blocks, raw)
    market['model_probability_yes'] = calibrated
    metadata['calibration'] = {'version': stored.get('version'), 'fitted_at': stored.get('fitted_at'),
                               'samples': stored.get('sample_count'), 'raw_probability_yes': raw,
                               'calibrated_probability_yes': calibrated}
    market['_model_metadata'] = metadata


def calibration_summary(config):
    """Compact status for the configuration API; never exposes the full map."""
    stored = _loads(getattr(config, 'calibration_json', None))
    return {key: stored.get(key) for key in ('status', 'version', 'sample_count', 'fitted_at', 'checked_at')}