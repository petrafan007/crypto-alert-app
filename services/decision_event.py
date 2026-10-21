"""Bounded Decision Engine Event-contract evaluations, without generative escalation."""
from datetime import datetime, timezone

from core.extensions import db
from credentials import Credential, UserSetting
from services.decision_engine import DecisionClient, DecisionError, number
from services.decision_settings import key_for_transport, settings_for
from services.provider_resilience import AIRequestDeferred

CONTRACT_VERSION = 'event-decision-v1'


def evaluator_for(user_id):
    return 'decision'


def forecast_identity_for(user_id):
    mode = evaluator_for(user_id)
    if mode == 'decision':
        config = settings_for(db.session.get(UserSetting, user_id))
        from services.prompt_catalog import prompt_for
        return [mode, config['decision_enabled'], config['decision_transport'],
                config['decision_model'], config['decision_confidence_threshold'],
                prompt_for(user_id, 'decision.contract_probability')]
    return [mode]


def build_questions(markets, user_id=None):
    from services.prompt_catalog import prompt_for, render_prompt
    templates = prompt_for(user_id, 'decision.contract_probability')
    questions = {}
    for index, market in enumerate(markets):
        for key, question in templates.items():
            questions[f'c{index}_{key}'] = {**question, 'instructions': render_prompt(
                question['instructions'], index=index, symbol=market['symbol'])}
    return questions


def _clients(settings, credential):
    transport = settings.get('decision_transport', 'subq')
    key = key_for_transport(credential, transport)
    clients = []
    if key and key != '********':
        clients.append(DecisionClient(key, settings['decision_endpoint'], settings['decision_model'],
                                      settings['decision_timeout_seconds'], transport=transport))
    other = 'inception' if transport == 'subq' else 'subq'
    other_key = key_for_transport(credential, other)
    if other_key and other_key != '********':
        from services.decision_settings import (
            INCEPTION_DECISIONS_ENDPOINT, INCEPTION_DECISIONS_MODEL, SUBQ_ENDPOINT, SUBQ_MODEL,
        )
        clients.append(DecisionClient(
            other_key,
            INCEPTION_DECISIONS_ENDPOINT if other == 'inception' else SUBQ_ENDPOINT,
            INCEPTION_DECISIONS_MODEL if other == 'inception' else SUBQ_MODEL,
            settings['decision_timeout_seconds'], transport=other))
    return clients


def predict(user_id, markets, config, guard):
    """One typed evaluation for a bounded batch; failures never call an LLM."""
    from event_algo import _event_model_context
    from services.event_runtime import reserve_provider_call
    from services.event_inference import MAX_BATCH_CONTRACTS
    if not markets or len(markets) > MAX_BATCH_CONTRACTS:
        raise ValueError('The Decision Engine Event batch is outside the configured bound.')
    settings = dict(settings_for(db.session.get(UserSetting, user_id)))
    credential = Credential.query.filter_by(user_id=user_id).first()
    state = {'decision_time': datetime.now(timezone.utc).isoformat(),
             'contract_version': CONTRACT_VERSION,
             'contracts': [_event_model_context(market) for market in markets]}
    questions = build_questions(markets, user_id)
    provider = 'SubQ' if settings['decision_transport'] == 'subq' else 'Inception'
    metadata = {'tier': 'decision', 'provider': provider, 'model': settings['decision_model'],
                'transport': settings['decision_transport'], 'question_schema_version': CONTRACT_VERSION,
                'search_status': 'Recorded Event evidence only', 'attempts': [],
                'confidence_basis': 'DECISION_CHOICE_DISTRIBUTION', 'generative_fallback': False}
    db.session.commit()  # no caller transaction remains open across provider I/O
    if not settings['decision_enabled']:
        return {market['symbol']: {'metadata': {**metadata, 'status': 'skipped',
            'deferral_reason': 'DECISION_DISABLED',
            'error': 'The Decision Engine is disabled; no generative fallback.'}} for market in markets}

    def before_request():
        guard()
        reserve_provider_call(user_id)  # charge every actual transport attempt, including retry

    clients = _clients(settings, credential)
    if not clients:
        return {market['symbol']: {'metadata': {**metadata, 'status': 'error',
            'error_code': 'missing_key',
            'error': 'Save an API key for the selected decision provider first.'}} for market in markets}
    result = None
    for client in clients:
        try:
            result = client.evaluate(state=state, questions=questions, before_request=before_request)
            break
        except AIRequestDeferred:
            raise
        except DecisionError as exc:
            if client is clients[-1]:
                return {market['symbol']: {'metadata': {**metadata, 'status': 'error',
                    'error_code': exc.code, 'error': str(exc), 'latency_ms': exc.latency_ms}} for market in markets}
    guard()
    metadata.update(model=result.model, provider=result.provider, transport=result.transport,
                    latency_ms=result.latency_ms, usage=result.usage,
                    estimated_cost_usd=str(result.estimated_cost_usd) if result.estimated_cost_usd is not None else None,
                    generated_at=datetime.now(timezone.utc).isoformat())
    predictions = {}
    for index, market in enumerate(markets):
        outcome = result.answers[f'c{index}_outcome']
        evidence = result.answers[f'c{index}_evidence']
        confidence = number(result.confidence.get(f'c{index}_outcome', 0))
        usable = (evidence['choice'] == 'usable' and
                  evidence['probabilities']['usable'] >= settings['decision_confidence_threshold'])
        accepted = usable and confidence >= settings['decision_confidence_threshold']
        rationale = (f"Decision Engine YES probability {outcome['probabilities']['YES']:.3f}; "
                     f"evidence {evidence['choice']}; distribution confidence {confidence:.3f}.")
        # Missing or uncertain evidence explicitly prevents an entry; it is not
        # promoted to a confident forecast or escalated to generative providers.
        predictions[market['symbol']] = {
            'model_probability_yes': number(outcome['probabilities']['YES']),
            'model_confidence': confidence if accepted else 0.0,
            'metadata': {**metadata, 'status': 'success', 'rationale': rationale,
                         'abstained': not accepted, 'evidence_quality': evidence['choice'],
                         'reported_confidence': confidence,
                         'answers': {key: value for key, value in result.answers.items()
                                     if key.startswith(f'c{index}_')}},
        }
    return predictions
