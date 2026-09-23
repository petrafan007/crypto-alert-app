"""Durable bounded evaluation queue; HTTP is always outside database transactions."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time

from sqlalchemy.orm import Session
from core.extensions import db
from credentials import Credential, UserSetting
from models import JevEvaluation
from services.jev_contracts import (STATE_SCHEMA_VERSION, JEV_SENTIMENT_CONTRACT_VERSION,
    JEV_CRYPTO_QUANT_CONTRACT_VERSION, build_sentiment_questions, build_crypto_quant_questions)
from services.jev_service import JevClient, JevError
from services.jev_settings import settings_for

logger = logging.getLogger(__name__)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('A decision-time timestamp is required.')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def create_evaluation(user_id, use_case, state, settings, *, action='shadow', base_signal=None, baseline=None):
    """Independent transaction so shadow storage failures cannot roll back trades."""
    decision = utc(state['decision_time']).replace(tzinfo=None)
    encoded = canonical(state)
    if len(encoded) > 24000:
        raise ValueError('Jev state exceeds the bounded evidence budget.')
    horizon = float(state.get('forecast_horizon_hours', 24))
    if not 0.25 <= horizon <= 168:
        raise ValueError('Invalid Jev forecast horizon.')
    with Session(db.engine, expire_on_commit=False) as session:
        pending = session.query(JevEvaluation).filter_by(user_id=user_id, status='pending').count()
        if pending >= 100:
            logger.warning('Jev queue full for user %s; observation skipped', user_id)
            return None
        row = JevEvaluation(user_id=user_id, use_case=use_case, symbol=state['symbol'],
            instrument_type=state['instrument_type'], market_source=state.get('market_source', 'binance' if use_case == 'sentiment' else 'webull'),
            state_schema_version=STATE_SCHEMA_VERSION,
            question_schema_version=JEV_SENTIMENT_CONTRACT_VERSION if use_case == 'sentiment' else JEV_CRYPTO_QUANT_CONTRACT_VERSION,
            state_hash=hashlib.sha256(encoded.encode()).hexdigest(), state_json=encoded,
            settings_json=canonical(settings), model=settings['jev_model'], decision_time=decision,
            target_horizon=horizon, outcome_due_at=decision+timedelta(hours=horizon),
            entry_price=state.get('current_price'), action_taken=action,
            base_signal_json=canonical(base_signal) if base_signal else None,
            counterfactual_json=canonical(baseline) if baseline else None)
        session.add(row)
        session.commit()
        return row.id


def update_evaluation(evaluation_id, user_id=None, **values):
    with Session(db.engine, expire_on_commit=False) as session:
        row = session.get(JevEvaluation, evaluation_id)
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
        logger.warning('Jev evaluation metadata could not be updated.')
        return False


def get_evaluation(evaluation_id):
    with Session(db.engine, expire_on_commit=False) as session:
        return session.get(JevEvaluation, evaluation_id)


def process_evaluation(evaluation_id):
    with Session(db.engine, expire_on_commit=False) as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        claimed = session.query(JevEvaluation).filter_by(id=evaluation_id, status='pending').update(
            {'status': 'running', 'started_at': now}, synchronize_session=False)
        session.commit()  # release claim BEFORE any provider I/O
        if not claimed:
            return get_evaluation(evaluation_id)
        row = session.get(JevEvaluation, evaluation_id)
        config = json.loads(row.settings_json)
        current = settings_for(session.get(UserSetting, row.user_id))
        credential = session.query(Credential).filter_by(user_id=row.user_id).first()
        key = credential.ai_gateway_key if credential else None
        enabled = current['jev_enabled'] and (
            current['jev_sentiment_mode'] != 'off' if row.use_case == 'sentiment' else current['jev_quant_shadow_enabled'])
    # No ORM session, row lock, or paper engine callback survives into this block.
    if not enabled or now-row.created_at > timedelta(minutes=5):
        update_evaluation(evaluation_id, status='abstained', error_code='disabled_or_stale', completed_at=now)
        return get_evaluation(evaluation_id)
    try:
        questions = build_sentiment_questions() if row.use_case == 'sentiment' else build_crypto_quant_questions()
        result = JevClient(key, config['jev_endpoint'], config['jev_model'], config['jev_timeout_seconds']).evaluate(
            state=json.loads(row.state_json), questions=questions)
        values = dict(status='success', answers_json=canonical(result.answers),
            probabilities_json=canonical({k: v.get('probabilities', v.get('probability')) for k, v in result.answers.items()}),
            confidence_json=canonical(result.confidence), model=result.model, provider=result.provider,
            latency_ms=result.latency_ms, usage_json=canonical(result.usage), estimated_cost_usd=result.estimated_cost_usd)
        if row.use_case == 'sentiment':
            from services.jev_sentiment import acceptance
            accepted, result_state = acceptance(result.answers, result.confidence, config, json.loads(row.state_json))
            values.update(status='success' if accepted else 'abstained', result_state=result_state)
    except JevError as exc:
        values = dict(status='timeout' if exc.code == 'timeout' else 'invalid_response' if exc.code == 'invalid_response' else 'error',
                      error_code=exc.code, error_message_safe=str(exc), latency_ms=exc.latency_ms, result_state='JEV_ESCALATED_ERROR')
    except Exception:
        # Never persist provider exception text, which can contain headers/state.
        values = dict(status='error', error_code='internal', error_message_safe='Jev evaluation could not be completed.', result_state='JEV_ESCALATED_ERROR')
    update_evaluation(evaluation_id, **values, completed_at=datetime.now(timezone.utc).replace(tzinfo=None))
    return get_evaluation(evaluation_id)


def process_pending(limit=10):
    with Session(db.engine) as session:
        session.query(JevEvaluation).filter(JevEvaluation.status == 'running',
            JevEvaluation.started_at < datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=2)).update(
                {'status': 'error', 'error_code': 'interrupted', 'error_message_safe': 'Evaluation interrupted; not retried.'}, synchronize_session=False)
        ids = [r.id for r in session.query(JevEvaluation.id).filter_by(status='pending', action_taken='shadow').order_by(JevEvaluation.id).limit(limit)]
        session.commit()
    for evaluation_id in ids:
        process_evaluation(evaluation_id)
    return len(ids)


def jev_worker_loop(app):
    while True:
        with app.app_context():
            try:
                process_pending()
            except Exception:
                logger.warning('Jev worker iteration failed; will retry pending work.')
            finally:
                db.session.remove()
        time.sleep(2)
