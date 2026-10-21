"""Decision Engine input for the Quantitative Strategy Engine.

The Decision Engine is an ACTIVE input to the crypto module, not an
observation. A qualified entry is confirmed by the decision engine before it
is opened, and a decision that says the setup is not viable blocks the entry.
Every decision, including a block, is recorded with its reason so the
outcome can be graded.
"""
import json
import logging

from core.extensions import db
from services.decision_evaluations import create_evaluation, process_evaluation, try_update_evaluation

logger = logging.getLogger(__name__)

# The decision engine's own entry contract. A negative answer at a
# probability above the configured threshold blocks the entry.
BLOCKING_CONTRACT = 'quant-v3: enter only when the setup probability exceeds 0.5'


def build_state(symbol, price, signal, now, extra=None):
    """Build the decision state from already-computed engine features.

    The features are never recomputed here: the decision engine observes the
    same evidence the engine acted on, so a disagreement is meaningful.
    """
    checks = signal.get('checks') or {}
    state = {
        'symbol': symbol,
        'instrument_type': 'CRYPTO',
        'market_source': 'webull',
        'current_price': price,
        'forecast_horizon_hours': 24,
        'is_watchlist': False,
        'decision_time': now.isoformat() if hasattr(now, 'isoformat') else str(now),
        'outcome_contract': 'return-v1: downside <=-2%',
        'baseline_qualified': bool(signal.get('enter')),
        'baseline_setup': signal.get('setup'),
        'features': checks,
    }
    if extra:
        state.update(extra)
    return state


def evaluate_entry(user_id, symbol, price, signal, now, settings, questions=None):
    """Ask the decision engine whether a qualified entry should be opened.

    Returns a dict with ``verdict`` in ``CONFIRM`` / ``BLOCK`` / ``ABSTAIN``,
    the probability that drove it, and a human-readable reason. The caller
    records the reason with the entry decision.
    """
    state = build_state(symbol, price, signal, now)
    evaluation_settings = {**settings, 'questions': questions} if questions else dict(settings)
    evaluation_id = None
    try:
        evaluation_id = create_evaluation(user_id, 'quant_crypto', state, evaluation_settings,
                                          action='none',
                                          base_signal={'enter': bool(signal.get('enter')),
                                                       'setup': signal.get('setup')},
                                          baseline={'enter': bool(signal.get('enter'))})
        db.session.commit()
        if not evaluation_id:
            return {'verdict': 'ABSTAIN', 'probability': None,
                    'reason': 'The decision request could not be queued.', 'evaluation_id': None}
        row = process_evaluation(evaluation_id)
    except Exception as exc:
        logger.warning('The Decision Engine could not evaluate a crypto entry: %s', str(exc)[:150])
        return {'verdict': 'ABSTAIN', 'probability': None,
                'reason': 'The decision engine was unavailable.', 'evaluation_id': None}
    if not row or row.status != 'success':
        reason = (row.result_state if row and row.result_state else 'the decision engine abstained')
        return {'verdict': 'ABSTAIN', 'probability': None, 'reason': reason, 'evaluation_id': evaluation_id}
    try:
        answers = json.loads(row.answers_json or '{}')
        # The crypto-quant contract answers the entry question as
        # 'confirm_entry'; 'enter' is the legacy answer name.
        answer = answers.get('confirm_entry') or answers.get('enter')
        probability = float(answer['probability'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return {'verdict': 'ABSTAIN', 'probability': None,
                'reason': 'the decision answer was unreadable', 'evaluation_id': evaluation_id}
    threshold = float(settings.get('decision_confidence_threshold', 0.8))
    if probability >= threshold:
        verdict = 'CONFIRM'
        reason = f'The decision engine confirmed the setup (probability {probability:.2f}).'
    elif probability <= 1 - threshold:
        verdict = 'BLOCK'
        reason = f'The decision engine rejected the setup (probability {probability:.2f}).'
    else:
        verdict = 'ABSTAIN'
        reason = f'The decision engine was undecided (probability {probability:.2f}).'
    try_update_evaluation(evaluation_id, action_taken=verdict.lower(), result_state=verdict)
    return {'verdict': verdict, 'probability': probability, 'reason': reason,
            'evaluation_id': evaluation_id, 'provider': row.provider, 'model': row.model}
