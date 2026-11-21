"""Decision Engine input for the Quantitative Strategy Engine.

Unified three-layer decision stack:
  1. Quantitative layer: deterministic price/chart/volatility/volume math
     (composite watchlist regime, market-state classifier, risk math)
  2. AI layer: news and direction summary for the candidate symbol
  3. Decision models (subq / inception Mercury / gemini): receive BOTH layers
     and confirm, block, or abstain on the candidate trade.

No layer trades alone: AI summaries never place orders directly, and every
decision (including blocks) is recorded with its reason for outcome grading.
"""
import json
import logging
from datetime import timedelta, timezone

from core.extensions import db
from services.decision_evaluations import create_evaluation, process_evaluation, try_update_evaluation

logger = logging.getLogger(__name__)

# The decision engine's own entry contract. A negative answer at a
# probability above the configured threshold blocks the entry.
BLOCKING_CONTRACT = 'quant-v3: enter only when the setup probability exceeds 0.5'

# A gate state is only valid when it describes the asset it claims to
# describe. The deterministic scan requests a 150-bar window for crypto, and a
# candidate priced far outside the asset's own recent range is a
# data-integrity failure, never evidence.
MIN_GATE_COMPLETED_BARS = 100
MIN_EQUITY_COMPLETED_BARS = 50
PRICE_BAND_LOW = 0.25
PRICE_BAND_HIGH = 4.0

MODULE_INSTRUMENT_TYPES = {
    'equities': 'EQUITY',
    'options': 'OPTION',
    'crypto': 'CRYPTO',
    'futures': 'FUTURES',
    'events': 'EVENT',
}


def _integrity_failure(user_id, symbol, price, signal, now, *, module='crypto'):
    """Return a reason string when the candidate's evidence is incoherent."""
    checks = (signal or {}).get('checks') or {}
    try:
        price = float(price)
    except (TypeError, ValueError):
        return 'gate price is not numeric'
    if price <= 0:
        return 'gate price must be positive'

    mod = str(module or 'crypto').lower()
    if mod == 'crypto':
        bars = checks.get('completed_hourly_bars')
        if bars is None or int(bars) < MIN_GATE_COMPLETED_BARS:
            return (f'gate evidence has {bars} completed hourly bars; '
                    f'{MIN_GATE_COMPLETED_BARS} are required')
        channel_high = checks.get('entry_channel_high')
        if channel_high:
            ratio = price / float(channel_high)
            if not PRICE_BAND_LOW <= ratio <= PRICE_BAND_HIGH:
                return (f'gate price {price} is incoherent with the entry channel '
                        f'high {channel_high} for {symbol}')
    elif mod == 'equities':
        bars = checks.get('completed_daily_bars')
        if bars is not None and int(bars) < MIN_EQUITY_COMPLETED_BARS:
            return (f'gate evidence has {bars} completed daily bars; '
                    f'{MIN_EQUITY_COMPLETED_BARS} are required')
    elif mod == 'options':
        bars = checks.get('underlying_bars')
        if bars is not None and int(bars) < MIN_EQUITY_COMPLETED_BARS:
            return (f'gate evidence has {bars} underlying bars; '
                    f'{MIN_EQUITY_COMPLETED_BARS} are required')
    elif mod == 'events':
        if not 0 < price < 1:
            return f'event contract price {price} is outside (0, 1)'

    # Cross-symbol contamination guard: compare against the asset's own
    # recent evaluation prices for the same module use case.
    use_case = f'quant_{mod}'
    if mod in ('crypto', 'equities'):
        try:
            from sqlalchemy.orm import Session
            from models import JevEvaluation as DecisionEvaluation
            moment = now.astimezone(timezone.utc).replace(tzinfo=None) if getattr(now, 'tzinfo', None) else now
            with Session(db.engine) as session:
                recent = (session.query(DecisionEvaluation.entry_price)
                          .filter_by(user_id=user_id, use_case=use_case, symbol=symbol)
                          .filter(DecisionEvaluation.entry_price > 0,
                                  DecisionEvaluation.decision_time >= moment - timedelta(days=7))
                          .order_by(DecisionEvaluation.id.desc()).limit(20).all())
            history = sorted(float(row[0]) for row in recent)
            if len(history) >= 3:
                median = history[len(history) // 2]
                if median > 0 and not PRICE_BAND_LOW <= price / median <= PRICE_BAND_HIGH:
                    return (f'gate price {price} is outside the recent price band '
                            f'for {symbol} (recent median {median})')
        except Exception:
            logger.warning("Could not read prior quantitative evaluations", exc_info=True)
    return None


def build_state(symbol, price, signal, now, extra=None, *, module='crypto', news_summary=None):
    """Build the combined decision state from Layer 1 (quant) + Layer 2 (AI news/direction).

    Quantitative features are never recomputed here: the decision model observes
    the exact same evidence the deterministic engine computed, paired with the
    AI news/direction summary.
    """
    mod = str(module or 'crypto').lower()
    checks = signal.get('checks') or {}
    state = {
        'symbol': symbol,
        'module': mod,
        'instrument_type': MODULE_INSTRUMENT_TYPES.get(mod, 'CRYPTO'),
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
    if news_summary is not None:
        state['news_direction_summary'] = news_summary
    if extra:
        state.update(extra)
    return state


def evaluate_entry(user_id, symbol, price, signal, now, settings, questions=None, *, module='crypto', news_summary=None):
    """Ask the decision engine whether a qualified entry should be opened.

    Receives both Layer 1 (quantitative `signal['checks']`) and Layer 2
    (`news_summary`), and returns a dict with ``verdict`` in
    ``CONFIRM`` / ``BLOCK`` / ``ABSTAIN``, probability, and human-readable reason.
    """
    mod = str(module or 'crypto').lower()
    use_case = f'quant_{mod}'
    failure = _integrity_failure(user_id, symbol, price, signal, now, module=mod)
    if failure:
        logger.warning('Decision Engine gate skipped for %s (%s): %s', symbol, mod, failure)
        return {'verdict': 'ABSTAIN', 'probability': None,
                'reason': f'Data integrity guard: {failure}.', 'evaluation_id': None}
    state = build_state(symbol, price, signal, now, module=mod, news_summary=news_summary)
    evaluation_settings = {**settings, 'questions': questions} if questions else dict(settings)
    evaluation_id = None
    try:
        evaluation_id = create_evaluation(user_id, use_case, state, evaluation_settings,
                                          action='none',
                                          base_signal={'enter': bool(signal.get('enter')),
                                                       'setup': signal.get('setup'),
                                                       'module': mod},
                                          baseline={'enter': bool(signal.get('enter'))})
        db.session.commit()
        if not evaluation_id:
            return {'verdict': 'ABSTAIN', 'probability': None,
                    'reason': 'The decision request could not be queued.', 'evaluation_id': None}
        row = process_evaluation(evaluation_id)
    except Exception as exc:
        logger.warning('The Decision Engine could not evaluate a %s entry: %s', mod, str(exc)[:150])
        return {'verdict': 'ABSTAIN', 'probability': None,
                'reason': 'The decision engine was unavailable.', 'evaluation_id': None}
    if not row or row.status != 'success':
        reason = (row.result_state if row and row.result_state else 'the decision engine abstained')
        return {'verdict': 'ABSTAIN', 'probability': None, 'reason': reason, 'evaluation_id': evaluation_id}
    try:
        answers = json.loads(row.answers_json or '{}')
        # The quant contract answers the entry question as 'confirm_entry'; 'enter' is legacy.
        answer = answers.get('confirm_entry') or answers.get('enter')
        probability = float(answer['probability'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return {'verdict': 'ABSTAIN', 'probability': None,
                'reason': 'the decision answer was unreadable', 'evaluation_id': evaluation_id}
    threshold = float(settings.get('decision_confidence_threshold', 0.8))
    if probability >= threshold:
        verdict = 'CONFIRM'
        reason = f'The decision engine confirmed the setup ({mod}, probability {probability:.2f}).'
    elif probability <= 1 - threshold:
        verdict = 'BLOCK'
        reason = f'The decision engine rejected the setup ({mod}, probability {probability:.2f}).'
    else:
        verdict = 'ABSTAIN'
        reason = f'The decision engine was undecided ({mod}, probability {probability:.2f}).'
    try_update_evaluation(evaluation_id, action_taken=verdict.lower(), result_state=verdict)
    return {'verdict': verdict, 'probability': probability, 'reason': reason,
            'evaluation_id': evaluation_id, 'provider': row.provider, 'model': row.model}
