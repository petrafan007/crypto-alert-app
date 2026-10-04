"""Bounded Jev Event-contract evaluations, without generative escalation."""
from datetime import datetime, timezone

from core.extensions import db
from credentials import Credential, UserSetting
from portfolio_algo_models import PortfolioStrategyConfig
from services.jev_service import JevClient, JevError, number
from services.jev_settings import settings_for
from services.provider_resilience import AIRequestDeferred

CONTRACT_VERSION = 'event-jev-v1'


def evaluator_for(user_id):
    return 'jev'


def forecast_identity_for(user_id):
    mode = evaluator_for(user_id)
    if mode == 'jev':
        config = settings_for(db.session.get(UserSetting, user_id))
        from services.prompt_catalog import prompt_for
        return [mode, config['jev_enabled'], config['jev_transport'], config['jev_model'], config['jev_confidence_threshold'], prompt_for(user_id, 'jev.contract_probability')]
    return [mode]


def build_questions(markets, user_id=None):
    from services.prompt_catalog import prompt_for, render_prompt
    templates = prompt_for(user_id, 'jev.contract_probability')
    questions = {}
    for index, market in enumerate(markets):
        for key, question in templates.items():
            questions[f'c{index}_{key}'] = {**question, 'instructions': render_prompt(
                question['instructions'], index=index, symbol=market['symbol'])}
    return questions


def predict(user_id, markets, config, guard):
    """One typed evaluation for a bounded batch; failures never call an LLM."""
    from event_algo import _event_model_context
    from services.event_runtime import reserve_provider_call
    from services.event_inference import MAX_BATCH_CONTRACTS
    if not markets or len(markets) > MAX_BATCH_CONTRACTS:
        raise ValueError('Jev Event batch is outside the configured bound.')
    settings = settings_for(db.session.get(UserSetting, user_id))
    credential = Credential.query.filter_by(user_id=user_id).first()
    key = (credential.openrouter_api_key if settings['jev_transport'] == 'openrouter'
           else credential.ai_gateway_key) if credential else None
    state = {'decision_time': datetime.now(timezone.utc).isoformat(),
             'contract_version': CONTRACT_VERSION,
             'contracts': [_event_model_context(market) for market in markets]}
    questions = build_questions(markets, user_id)
    metadata = {'tier': 'jev', 'provider': 'typesafe-ai', 'model': settings['jev_model'],
                'transport': settings['jev_transport'], 'question_schema_version': CONTRACT_VERSION,
                'search_status': 'Recorded Event evidence only', 'attempts': [],
                'confidence_basis': 'JEV_CHOICE_DISTRIBUTION', 'generative_fallback': False}
    db.session.commit()  # no caller transaction remains open across provider I/O
    if not settings['jev_enabled']:
        return {market['symbol']: {'metadata': {**metadata, 'status': 'skipped',
            'deferral_reason': 'JEV_DISABLED', 'error': 'Jev is disabled; no generative fallback.'}} for market in markets}

    def before_request():
        guard()
        reserve_provider_call(user_id)  # charge every actual transport attempt, including retry

    try:
        result = JevClient(key, settings['jev_endpoint'], settings['jev_model'],
            settings['jev_timeout_seconds'], transport=settings['jev_transport']).evaluate(
                state=state, questions=questions, before_request=before_request)
        guard()
    except AIRequestDeferred:
        raise
    except JevError as exc:
        return {market['symbol']: {'metadata': {**metadata, 'status': 'error',
            'error_code': exc.code, 'error': str(exc), 'latency_ms': exc.latency_ms}} for market in markets}
    metadata.update(model=result.model, latency_ms=result.latency_ms, usage=result.usage,
                    estimated_cost_usd=str(result.estimated_cost_usd) if result.estimated_cost_usd is not None else None,
                    generated_at=datetime.now(timezone.utc).isoformat())
    predictions = {}
    for index, market in enumerate(markets):
        outcome = result.answers[f'c{index}_outcome']
        evidence = result.answers[f'c{index}_evidence']
        confidence = number(result.confidence.get(f'c{index}_outcome', 0))
        usable = (evidence['choice'] == 'usable' and
                  evidence['probabilities']['usable'] >= settings['jev_confidence_threshold'])
        accepted = usable and confidence >= settings['jev_confidence_threshold']
        rationale = (f'Jev YES probability {outcome["probabilities"]["YES"]:.3f}; '
                     f'evidence {evidence["choice"]}; distribution confidence {confidence:.3f}.')
        # Missing/uncertain evidence explicitly prevents an entry; it is not
        # promoted to a confident forecast or escalated to generative providers.
        predictions[market['symbol']] = {
            'model_probability_yes': number(outcome['probabilities']['YES']),
            'model_confidence': confidence if accepted else 0.0,
            'metadata': {**metadata, 'status': 'success', 'rationale': rationale,
                         'abstained': not accepted, 'evidence_quality': evidence['choice'],
                         'reported_confidence': confidence,
                         'answers': {key: value for key, value in result.answers.items() if key.startswith(f'c{index}_')}},
        }
    return predictions
