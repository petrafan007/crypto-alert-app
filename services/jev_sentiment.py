"""Jev sentiment evaluation with no generative escalation."""
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
    state = {k: context[k] for k in ('symbol', 'instrument_type', 'current_price', 'forecast_horizon_hours', 'is_watchlist', 'market_source', 'recommendation_boundaries') if k in context}
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
    if not (state.get('evidence') or state.get('market_context')) or not state.get('current_price') or state['current_price'] <= 0:
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
    if generative is None:
        try:
            from services.ai_service import _call_generative_with_web_search
            generative = _call_generative_with_web_search
        except ImportError:
            pass

    fallback_allowed = config.get('jev_generative_fallback_enabled', True)

    if not config['jev_enabled'] or config['jev_sentiment_mode'] == 'off':
        if fallback_allowed and generative is not None:
            return generative(**kwargs)
        raise ValueError('Jev sentiment is disabled; no generative fallback.')
    if is_stablecoin(context['symbol']):
        if fallback_allowed and generative is not None:
            return generative(**kwargs)
        raise ValueError('Stablecoins do not require a model evaluation.')
    # Preserve audit scheduling guard before any paid Jev or search call.
    from services.portfolio_audit_lifecycle import active_audit
    from services.provider_resilience import AIRequestDeferred
    if active_audit(user_id):
        raise AIRequestDeferred('Quantitative audit has exclusive AI access; sentiment deferred.')
    captured = []
    # Deterministic queries, reusing the application's existing search providers.
    from services.prompt_catalog import prompt_for, render_prompt, overrides_for
    prompt_overrides = overrides_for(user_id)
    query_key = 'jev.watchlist_sentiment_search' if context.get('is_watchlist') else 'jev.sentiment_search'
    settings = db.session.get(UserSetting, user_id)
    if getattr(settings, 'ai_web_search_enabled', True):
        instrument = 'crypto' if context['instrument_type'] == 'CRYPTO' else 'equity'
        username = kwargs['username']
        for fetch in (
            lambda: news_api_search(context['symbol'], username, kwargs.get('search_lookback_hours', 12), asset_context=instrument),
            lambda: web_search(render_prompt(prompt_for(user_id, query_key, prompt_overrides), symbol=context['symbol'], instrument=instrument, datetime=datetime.now(timezone.utc).isoformat()), max_results=4, username=username),
        ):
            try:
                items = fetch()
                if isinstance(items, list):
                    observed = datetime.now(timezone.utc).isoformat()
                    captured.extend(dict(i, available_at=observed) for i in items if isinstance(i, dict))
            except Exception:
                pass
    state = build_state(context, captured, datetime.now(timezone.utc))
    from services.jev_contracts import build_sentiment_questions
    questions = build_sentiment_questions(user_id, context.get('is_watchlist', False), prompt_overrides)
    evaluation_settings = {**config, 'questions': questions}
    evaluation_id, row = None, None
    try:
        evaluation_id = create_evaluation(user_id, 'sentiment', state, evaluation_settings, action='none')
        db.session.commit()
        if evaluation_id and (not state.get('current_price') or not (state.get('evidence') or state.get('market_context'))):
            try_update_evaluation(evaluation_id, status='abstained', result_state='JEV_ABSTAINED_NO_EVIDENCE')
        else:
            row = process_evaluation(evaluation_id) if evaluation_id else None
    except Exception:
        logger.warning('Jev sentiment evaluation unavailable; attempting fallback.')
    if row and row.status == 'success':
        label, reason = mapped_result(json.loads(row.answers_json), context.get('is_watchlist', False))
        response = AIResponseWrapper(json.dumps({'sentiment': label, 'reason': reason}), tier='jev',
            provider='typesafe-ai', model=row.model, search_status=f'Jev grounded ({len(state["evidence"])} sources)')
        response.jev_evaluation_id = evaluation_id
        try_update_evaluation(evaluation_id, action_taken='sentiment')
        return response, json.dumps({'questions': questions, 'state': state}, ensure_ascii=False)

    if fallback_allowed and generative is not None:
        if evaluation_id:
            try_update_evaluation(evaluation_id, fallback_used=True)
        try:
            response, prompt = generative(**kwargs)
            if hasattr(response, 'jev_evaluation_id'):
                response.jev_evaluation_id = evaluation_id
            return response, prompt
        except Exception as gen_err:
            logger.warning(f"Generative fallback after Jev abstention failed: {gen_err}")

    if not fallback_allowed:
        raise ValueError('Jev abstained or was unavailable; no generative fallback.')

    # Safe neutral fallback when evaluation abstains and generative fallback is unavailable
    default_label = 'Watch' if context.get('is_watchlist', False) else 'Hold'
    abstain_reason = row.result_state if row and row.result_state else 'evaluation abstained or unavailable'
    default_reason = f"Maintains {default_label} stance; market signals remain balanced ({abstain_reason})."
    fallback_resp = AIResponseWrapper(
        json.dumps({'sentiment': default_label, 'reason': default_reason}),
        tier='fallback',
        provider='internal',
        model='neutral-stance',
        search_status='Fallback'
    )
    if evaluation_id:
        fallback_resp.jev_evaluation_id = evaluation_id
    return fallback_resp, json.dumps({'questions': questions, 'state': state}, ensure_ascii=False)
