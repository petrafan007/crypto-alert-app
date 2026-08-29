"""Provider-neutral storage and grading for broker-held AI signals.

The Binance sentiment ledger remains deliberately untouched.  This module is
for instruments whose market data comes from another connector (Webull today),
and is intentionally capable of serving later broker integrations.
"""

import json
from datetime import datetime, timedelta, timezone

from core.extensions import db
from models import ExternalSentimentSignal
from services.sentiment_outcome_service import (
    evaluate_sentiment_outcome,
    get_sentiment_thresholds,
    serialize_grading_config,
)


def create_external_signal(*, user_id, provider, account_id, symbol,
                           instrument_type, prompt_family, recommendation,
                           reason, market_context, entry_price, currency,
                           forecast_horizon_hours, origin='manual',
                           ai_provider=None, provider_model=None, ai_tier=None,
                           search_status=None, failover_history=None, created_at=None):
    """Store one forecast with its immutable grading rules snapshot."""
    from credentials import UserSetting

    now = created_at or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    horizon = max(1.0, float(forecast_horizon_hours or 24))
    settings = UserSetting.query.filter_by(user_id=user_id).first()
    signal = ExternalSentimentSignal(
        user_id=user_id,
        provider=str(provider or '').lower(),
        account_id=str(account_id) if account_id else None,
        symbol=str(symbol or '').upper(),
        instrument_type=str(instrument_type or '').upper(),
        prompt_family=str(prompt_family or '').lower(),
        recommendation=recommendation,
        reason=reason,
        market_context=market_context,
        entry_price=float(entry_price),
        currency=str(currency or 'USD').upper(),
        ai_provider=ai_provider,
        provider_model=provider_model,
        ai_tier=ai_tier,
        search_status=search_status,
        failover_history=failover_history,
        origin=origin,
        forecast_horizon_hours=horizon,
        target_evaluation_at=now + timedelta(hours=horizon),
        grading_config=serialize_grading_config(get_sentiment_thresholds(settings)),
        outcome_status='tracking',
        created_at=now,
    )
    db.session.add(signal)
    db.session.commit()
    return signal


def signal_to_dict(signal, include_reason=True):
    data = {
        'id': signal.id,
        'provider': signal.provider,
        'account_id': signal.account_id,
        'symbol': signal.symbol,
        'instrument_type': signal.instrument_type,
        'prompt_family': signal.prompt_family,
        'recommendation': signal.recommendation,
        'entry_price': signal.entry_price,
        'currency': signal.currency,
        'origin': signal.origin,
        'forecast_horizon_hours': signal.forecast_horizon_hours,
        'target_evaluation_at': signal.target_evaluation_at.isoformat() if signal.target_evaluation_at else None,
        'outcome_price': signal.outcome_price,
        'outcome_pct': signal.outcome_pct,
        'outcome_status': signal.outcome_status,
        'outcome_reason': signal.outcome_reason,
        'outcome_evaluated_at': signal.outcome_evaluated_at.isoformat() if signal.outcome_evaluated_at else None,
        'created_at': signal.created_at.isoformat() if signal.created_at else None,
        'ai_provider': signal.ai_provider,
        'provider_model': signal.provider_model,
        'ai_tier': signal.ai_tier,
        'search_status': signal.search_status,
        'failover_history': signal.failover_history,
    }
    if include_reason:
        data['reason'] = signal.reason
        data['market_context'] = signal.market_context
    return data


def _thresholds_for_signal(signal):
    try:
        parsed = json.loads(signal.grading_config or '')
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    from credentials import UserSetting
    return get_sentiment_thresholds(UserSetting.query.filter_by(user_id=signal.user_id).first())


def grade_external_signal(signal, evaluation_price, evaluated_at=None):
    """Grade a due signal against a connector-supplied price only once."""
    thresholds = _thresholds_for_signal(signal)
    key_by_recommendation = {
        'buy immediately': 'buy_immediately', 'consider buying': 'consider_buying',
        'hold': 'hold', 'consider selling': 'consider_selling', 'sell immediately': 'sell_immediately',
    }
    key = key_by_recommendation.get(str(signal.recommendation or '').strip().lower())
    rule = thresholds.get(key) if key else None
    if not rule:
        grade = {'status': 'unscored', 'delta_pct': None, 'reason': 'This recommendation has no configured outcome rule.'}
    elif key == 'hold':
        grade = evaluate_sentiment_outcome(
            signal.recommendation, 'external', signal.entry_price, evaluation_price,
            hold_steady_pct=rule['steady_pct'], hold_wrong_pct=rule['wrong_pct'],
        )
    else:
        grade = evaluate_sentiment_outcome(
            signal.recommendation, 'external', signal.entry_price, evaluation_price,
            rule['correct_pct'], rule['wrong_pct'],
        )
    signal.outcome_price = float(evaluation_price)
    signal.outcome_pct = grade.get('delta_pct')
    signal.outcome_status = grade.get('status') or 'unscored'
    signal.outcome_reason = grade.get('reason')
    timestamp = evaluated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    signal.outcome_evaluated_at = timestamp
    return signal
