"""Sentiment orchestration; preserves the existing generative response contract."""
from datetime import datetime, timezone
import json
import logging

from credentials import UserSetting
from core.extensions import db
from services.jev_settings import settings_for
from services.jev_evaluations import utc, create_evaluation, process_evaluation, try_update_evaluation

PORTFOLIO_LABELS = dict(zip(['strong_bullish', 'bullish', 'neutral', 'bearish', 'strong_bearish'],
                          ['Buy Immediately', 'Consider Buying', 'Hold', 'Consider Selling', 'Sell Immediately']))
WATCHLIST_LABELS = dict(zip(PORTFOLIO_LABELS, ['Definitely Buy', 'Consider Buying', 'Watch', 'Avoid', 'Avoid']))
logger = logging.getLogger(__name__)


def build_state(context, evidence, decision_time):
    decision = utc(decision_time)
    items = []
    for item in evidence[:30]:
        try:
            # Retrieval time is required even when publication time is unknown.
            available = utc(item['available_at'])
            if available > decision:
                continue
            published = item.get('published_at')
            if published and utc(published) > decision:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        items.append({k: str(item.get(k) or '')[:limit] for k, limit in
                      [('title', 200), ('snippet', 500), ('source', 100), ('published_at', 40), ('available_at', 40)]})
        if len(items) == 12:
            break
    state = {k: context[k] for k in ('symbol', 'instrument_type', 'current_price', 'forecast_horizon_hours', 'is_watchlist', 'market_source') if k in context}
    try:
        if context.get('market_context') and utc(context['market_available_at']) <= decision:
            state['market_context'] = str(context['market_context'])[:4000]
            state['market_available_at'] = utc(context['market_available_at']).isoformat()
    except (KeyError, TypeError, ValueError):
        pass
    state.update(decision_time=decision.isoformat(), evidence=items, outcome_contract='return-v1: bullish >0%; downside <=-2%')
    return state


def acceptance(answers, confidence, settings, state):
    direction = answers['direction']
    probability = direction['probabilities'][direction['choice']]
    reported_confidence = confidence.get('direction')
    if not state.get('evidence') or not state.get('current_price') or state['current_price'] <= 0:
        return False, 'JEV_ABSTAINED_NO_EVIDENCE'
    if answers['conflicted']['probability'] > settings['jev_conflict_threshold']:
        return False, 'JEV_ESCALATED_CONFLICT'
    if probability < settings['jev_confidence_threshold'] or (reported_confidence is not None and reported_confidence < settings['jev_confidence_threshold']):
        return False, 'JEV_ABSTAINED_LOW_CONFIDENCE'
    return True, 'JEV_ACCEPTED'


def mapped_result(answers, is_watchlist=False):
    direction = answers['direction']['choice']
    label = (WATCHLIST_LABELS if is_watchlist else PORTFOLIO_LABELS)[direction]
    reason = (f"Jev: {direction}; materiality {answers['materiality']['score']+1:.1f}/5; "
              f"bullish probability {answers['bullish']['probability']:.2f}; "
              f"downside-risk probability {answers['downside_risk']['probability']:.2f}; "
              f"evidence-conflict probability {answers['conflicted']['probability']:.2f}.")
    return label, reason


def run_sentiment(generative, kwargs, context):
    from services.ai_service import AIResponseWrapper, news_api_search, web_search
    from routes.helpers import is_stablecoin
    user_id = kwargs['user_id']
    config = settings_for(db.session.get(UserSetting, user_id))
    if not config['jev_enabled'] or config['jev_sentiment_mode'] == 'off' or is_stablecoin(context['symbol']):
        return generative(**kwargs)
    # Preserve audit scheduling guard before any paid Jev or search call.
    from services.portfolio_audit_lifecycle import active_audit
    from services.provider_resilience import AIRequestDeferred
    if active_audit(user_id):
        raise AIRequestDeferred('Quantitative audit has exclusive AI access; sentiment deferred.')
    captured = []
    def observe(items):
        captured.extend(items)
    if config['jev_sentiment_mode'] == 'shadow':
        response, prompt = generative(**kwargs, evidence_observer=observe)
        try:
            # Evidence timestamps came from the search completed before synthesis.
            decision = max((utc(i['available_at']) for i in captured), default=datetime.now(timezone.utc))
            state = build_state(context, captured, decision)
            evaluation_id = create_evaluation(user_id, 'sentiment', state, config,
                baseline={'generative_provider': getattr(response, 'provider', None), 'generative_model': getattr(response, 'model', None)})
            response.jev_evaluation_id = evaluation_id
        except Exception:
            logger.warning('Jev shadow observation could not be queued.')
        return response, prompt
    # Deterministic queries, reusing the application's existing search providers.
    settings = db.session.get(UserSetting, user_id)
    if getattr(settings, 'ai_web_search_enabled', True):
        instrument = 'crypto' if context['instrument_type'] == 'CRYPTO' else 'equity'
        username = kwargs['username']
        for fetch in (
            lambda: news_api_search(context['symbol'], username, kwargs.get('search_lookback_hours', 12), asset_context=instrument),
            lambda: web_search(f"{context['symbol']} {instrument} latest market news today", max_results=4, username=username),
        ):
            try:
                items = fetch()
                if isinstance(items, list):
                    observed = datetime.now(timezone.utc).isoformat()
                    captured.extend(dict(i, available_at=observed) for i in items if isinstance(i, dict))
            except Exception:
                pass
    state = build_state(context, captured, datetime.now(timezone.utc))
    evaluation_id, row = None, None
    try:
        evaluation_id = create_evaluation(user_id, 'sentiment', state, config, action='none')
        row = process_evaluation(evaluation_id) if evaluation_id else None
    except Exception:
        logger.warning('Jev sentiment evaluation unavailable; applying configured fallback policy.')
    if row and row.status == 'success':
        label, reason = mapped_result(json.loads(row.answers_json), context.get('is_watchlist', False))
        response = AIResponseWrapper(json.dumps({'sentiment': label, 'reason': reason}), tier='jev',
            provider='typesafe-ai', model=row.model, search_status=f'Jev grounded ({len(state["evidence"])} sources)')
        response.jev_evaluation_id = evaluation_id
        try_update_evaluation(evaluation_id, action_taken='sentiment')
        return response, 'Jev sentiment-v1: structured point-in-time evaluation.'
    if config['jev_generative_fallback_enabled']:
        if evaluation_id:
            try_update_evaluation(evaluation_id, fallback_used=True)
        response, prompt = generative(**kwargs)
        response.jev_evaluation_id = evaluation_id
        return response, prompt
    # Explicit error, never a fabricated neutral sentiment; existing caller clears checking.
    raise ValueError('Jev abstained or was unavailable; generative fallback is disabled.')
