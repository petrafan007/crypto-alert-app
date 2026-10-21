"""Durable bounded evaluation queue for the Decision Engine.

HTTP always happens outside database transactions. The queue is provider
neutral: a request is sent to the primary provider and, when that provider
fails, to the fallback provider. The provider that produced the answer is
recorded so every decision is attributable.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time

from sqlalchemy.orm import Session
from core.extensions import db
from credentials import Credential, UserSetting
from models import JevEvaluation as DecisionEvaluation
from services.decision_contracts import (
    DECISION_CRYPTO_QUANT_CONTRACT_VERSION,
    DECISION_SENTIMENT_CONTRACT_VERSION,
    STATE_SCHEMA_VERSION,
    build_crypto_quant_questions,
    build_sentiment_questions,
)
from services.decision_engine import DecisionClient, DecisionError
from services.decision_settings import (
    INCEPTION_DECISIONS_ENDPOINT,
    INCEPTION_DECISIONS_MODEL,
    SUBQ_ENDPOINT,
    SUBQ_MODEL,
    key_for_transport,
    normalize_transport,
    settings_for,
)

logger = logging.getLogger(__name__)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('A decision-time timestamp is required.')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def create_evaluation(user_id, use_case, state, settings, *, action='observe',
                      base_signal=None, baseline=None):
    """Store an evaluation request in an independent transaction.

    Storage failures must never roll back a trade, so this uses its own
    session and swallows nothing silently: a failure is logged and the caller
    continues without a decision.
    """
    decision = utc(state['decision_time']).replace(tzinfo=None)
    encoded = canonical(state)
    if len(encoded) > 24000:
        raise ValueError('Decision state exceeds the bounded evidence budget.')
    horizon = float(state.get('forecast_horizon_hours', 24))
    if not 0.25 <= horizon <= 168:
        raise ValueError('Invalid decision forecast horizon.')
    settings = dict(settings)
    if 'questions' not in settings:
        settings['questions'] = (build_sentiment_questions(user_id, state.get('is_watchlist', False))
                                 if use_case == 'sentiment' else build_crypto_quant_questions(user_id))
    with Session(db.engine, expire_on_commit=False) as session:
        pending = session.query(DecisionEvaluation).filter_by(user_id=user_id, status='pending').count()
        if pending >= 100:
            logger.warning('Decision queue full for user %s; request skipped', user_id)
            return None
        row = DecisionEvaluation(
            user_id=user_id, use_case=use_case, symbol=state['symbol'],
            instrument_type=state['instrument_type'],
            market_source=state.get('market_source', 'binance' if use_case == 'sentiment' else 'webull'),
            state_schema_version=STATE_SCHEMA_VERSION,
            question_schema_version=(DECISION_SENTIMENT_CONTRACT_VERSION if use_case == 'sentiment'
                                     else DECISION_CRYPTO_QUANT_CONTRACT_VERSION),
            state_hash=hashlib.sha256(encoded.encode()).hexdigest(), state_json=encoded,
            settings_json=canonical(settings), model=settings.get('decision_model'),
            decision_time=decision, target_horizon=horizon,
            outcome_due_at=decision+timedelta(hours=horizon),
            entry_price=state.get('current_price'), action_taken=action,
            base_signal_json=canonical(base_signal) if base_signal else None,
            counterfactual_json=canonical(baseline) if baseline else None)
        session.add(row)
        session.commit()
        return row.id


def update_evaluation(evaluation_id, user_id=None, **values):
    with Session(db.engine, expire_on_commit=False) as session:
        row = session.get(DecisionEvaluation, evaluation_id)
        if row and (user_id is None or row.user_id == user_id):
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()


def try_update_evaluation(evaluation_id, user_id=None, **values):
    """Best-effort linkage/telemetry must not invalidate a completed base result."""
    try:
        update_evaluation(evaluation_id, user_id=user_id, **values)
        return True
    except Exception:
        logger.warning('Decision evaluation metadata could not be updated.')
        return False


def get_evaluation(evaluation_id):
    with Session(db.engine, expire_on_commit=False) as session:
        return session.get(DecisionEvaluation, evaluation_id)


def _clients_for(config, credential):
    """Build the primary and fallback clients for the saved configuration."""
    transport = config.get('decision_transport', 'subq')
    key = key_for_transport(credential, transport)
    if not key or key == '********':
        return None, None
    primary = DecisionClient(key, config['decision_endpoint'], config['decision_model'],
                             config['decision_timeout_seconds'], transport=transport)
    fallback = None
    other = 'inception' if transport == 'subq' else 'subq'
    other_key = key_for_transport(credential, other)
    if other_key and other_key != '********':
        fallback_config = normalize_transport({
            'decision_transport': other,
            'decision_endpoint': INCEPTION_DECISIONS_ENDPOINT if other == 'inception' else SUBQ_ENDPOINT,
            'decision_model': INCEPTION_DECISIONS_MODEL if other == 'inception' else SUBQ_MODEL,
        })
        fallback = DecisionClient(other_key, fallback_config['decision_endpoint'],
                                  fallback_config['decision_model'],
                                  config['decision_timeout_seconds'], transport=other)
    return primary, fallback


def process_evaluation(evaluation_id):
    with Session(db.engine, expire_on_commit=False) as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        claimed = session.query(DecisionEvaluation).filter_by(id=evaluation_id, status='pending').update(
            {'status': 'running', 'started_at': now}, synchronize_session=False)
        session.commit()  # release claim BEFORE any provider I/O
        if not claimed:
            return get_evaluation(evaluation_id)
        row = session.get(DecisionEvaluation, evaluation_id)
        config = json.loads(row.settings_json)
        current = settings_for(session.get(UserSetting, row.user_id))
        credential = session.query(Credential).filter_by(user_id=row.user_id).first()
        if 'questions' not in config:
            from services.prompt_catalog import prompt_for
            setting = session.get(UserSetting, row.user_id)
            overrides = json.loads(setting.ai_prompt_overrides or '{}') if setting else {}
            state = json.loads(row.state_json)
            config['questions'] = (build_sentiment_questions(None, state.get('is_watchlist', False), overrides)
                                   if row.use_case == 'sentiment'
                                   else build_crypto_quant_questions(None, overrides))
        config = normalize_transport(config)
        enabled = current['decision_enabled'] and (
            current['decision_sentiment_mode'] != 'off' if row.use_case == 'sentiment'
            else current['decision_quant_enabled'])
    # No ORM session, row lock, or paper engine callback survives into this block.
    if not enabled or now-row.created_at > timedelta(minutes=5):
        update_evaluation(evaluation_id, status='abstained', error_code='disabled_or_stale', completed_at=now)
        return get_evaluation(evaluation_id)
    try:
        questions = config['questions']
        primary, fallback = _clients_for(config, credential)
        if primary is None and fallback is None:
            raise DecisionError('missing_key')
        result, tried = _evaluate(primary, fallback, row, questions, config)
        values = dict(status='success', answers_json=canonical(result.answers),
                      probabilities_json=canonical({k: v.get('probabilities', v.get('probability'))
                                                   for k, v in result.answers.items()}),
                      confidence_json=canonical(result.confidence), model=result.model,
                      provider=result.provider, transport=result.transport,
                      latency_ms=result.latency_ms, usage_json=canonical(result.usage),
                      estimated_cost_usd=result.estimated_cost_usd,
                      fallback_used=result.transport != config.get('decision_transport'))
        if row.use_case == 'sentiment':
            from services.decision_sentiment import acceptance
            accepted, result_state = acceptance(result.answers, result.confidence, config, json.loads(row.state_json))
            values.update(status='success' if accepted else 'abstained', result_state=result_state)
    except DecisionError as exc:
        values = dict(status=('timeout' if exc.code == 'timeout'
                              else 'invalid_response' if exc.code == 'invalid_response' else 'error'),
                      error_code=exc.code, error_message_safe=str(exc), latency_ms=exc.latency_ms,
                      result_state='DECISION_ESCALATED_ERROR')
    except Exception:
        # Never persist provider exception text, which can contain headers/state.
        values = dict(status='error', error_code='internal',
                      error_message_safe='The decision evaluation could not be completed.',
                      result_state='DECISION_ESCALATED_ERROR')
    update_evaluation(evaluation_id, **values, completed_at=datetime.now(timezone.utc).replace(tzinfo=None))
    return get_evaluation(evaluation_id)


def _evaluate(primary, fallback, row, questions, config):
    """Send the request to the primary provider, then the fallback."""
    state = json.loads(row.state_json)
    errors = []
    for client in (primary, fallback):
        if client is None:
            continue
        try:
            return client.evaluate(state=state, questions=questions,
                                   timeout_seconds=config.get('decision_timeout_seconds')), None
        except DecisionError as exc:
            errors.append(exc)
    raise errors[0] if errors else DecisionError('missing_key')


def process_pending(limit=10):
    with Session(db.engine) as session:
        session.query(DecisionEvaluation).filter(
            DecisionEvaluation.status == 'running',
            DecisionEvaluation.started_at < datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=2)
        ).update({'status': 'error', 'error_code': 'interrupted',
                  'error_message_safe': 'Evaluation interrupted; not retried.'}, synchronize_session=False)
        ids = [r.id for r in session.query(DecisionEvaluation.id).filter_by(status='pending').order_by(
            DecisionEvaluation.id).limit(limit)]
        session.commit()
    for evaluation_id in ids:
        process_evaluation(evaluation_id)
    return len(ids)


def decision_worker_loop(app):
    while True:
        with app.app_context():
            try:
                process_pending()
            except Exception:
                logger.warning('Decision worker iteration failed; will retry pending work.')
            finally:
                db.session.remove()
        time.sleep(2)
