"""Deterministic grading and reporting for recorded AI sentiment signals."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation


DIRECTIONAL_SENTIMENT_VARIABLES = {
    'buy_immediately': {
        'label': 'Buy Immediately',
        'direction': 'up',
        'correct_field': 'sentiment_buy_immediately_correct_pct',
        'wrong_field': 'sentiment_buy_immediately_wrong_pct',
    },
    'consider_buying': {
        'label': 'Consider Buying',
        'direction': 'up',
        'correct_field': 'sentiment_consider_buying_correct_pct',
        'wrong_field': 'sentiment_consider_buying_wrong_pct',
    },
    'consider_selling': {
        'label': 'Consider Selling',
        'direction': 'down',
        'correct_field': 'sentiment_consider_selling_correct_pct',
        'wrong_field': 'sentiment_consider_selling_wrong_pct',
    },
    'sell_immediately': {
        'label': 'Sell Immediately',
        'direction': 'down',
        'correct_field': 'sentiment_sell_immediately_correct_pct',
        'wrong_field': 'sentiment_sell_immediately_wrong_pct',
    },
}

HOLD_VARIABLE = {
    'label': 'Hold',
    'direction': 'steady',
    'steady_field': 'sentiment_hold_steady_pct',
    'wrong_field': 'sentiment_hold_wrong_pct',
}

SENTIMENT_VARIABLES = {
    **DIRECTIONAL_SENTIMENT_VARIABLES,
    'hold': HOLD_VARIABLE,
}

SENTIMENT_THRESHOLD_FIELDS = tuple(
    field
    for definition in DIRECTIONAL_SENTIMENT_VARIABLES.values()
    for field in (definition['correct_field'], definition['wrong_field'])
) + (HOLD_VARIABLE['steady_field'], HOLD_VARIABLE['wrong_field'])
CORRECT_THRESHOLD_FIELDS = {
    definition['correct_field'] for definition in DIRECTIONAL_SENTIMENT_VARIABLES.values()
}
DEFAULT_SENTIMENT_THRESHOLD_PCT = 5.0
DEFAULT_HOLD_STEADY_PCT = 1.0
DEFAULT_SENTIMENT_CHART_RANGE = '3d'
SENTIMENT_CHART_RANGE_VALUES = frozenset({
    '1d', '3d', '5d', '7d', '14d', '30d', '90d', '180d', '365d', '730d', 'all',
})
SENTIMENT_LOOKBACK_FIELDS = (
    'sentiment_history_lookback_hours', 'watchlist_sentiment_history_lookback_hours',
)
SENTIMENT_FORECAST_HORIZON_FIELDS = (
    'sentiment_forecast_horizon_hours', 'watchlist_sentiment_forecast_horizon_hours',
)

_SIGNAL_ALIASES = {
    'buy immediately': 'buy_immediately',
    'definitely buy': 'buy_immediately',
    'strong buy': 'buy_immediately',
    'consider buying': 'consider_buying',
    'buy': 'consider_buying',
    'hold': 'hold',
    'consider selling': 'consider_selling',
    'watch': 'consider_selling',
    'sell immediately': 'sell_immediately',
    'avoid': 'sell_immediately',
    'strong sell': 'sell_immediately',
    'do not buy': 'sell_immediately',
    'sell': 'sell_immediately',
}

BULLISH_SIGNALS = {
    label for label, key in _SIGNAL_ALIASES.items()
    if SENTIMENT_VARIABLES[key]['direction'] == 'up'
}
BEARISH_SIGNALS = {
    label for label, key in _SIGNAL_ALIASES.items()
    if SENTIMENT_VARIABLES[key]['direction'] == 'down'
}


def validate_sentiment_chart_range(value):
    """Return a normalized chart range and an optional validation error."""
    normalized = str(value or '').strip().lower()
    if normalized not in SENTIMENT_CHART_RANGE_VALUES:
        return None, 'Choose a valid Sentiment Chart range from 1 Day through All Available.'
    return normalized, None


def validate_sentiment_window_payload(data):
    """Validate optional history and forecast window settings."""
    values, errors = {}, {}
    limits = {
        **{field: (1, 72) for field in SENTIMENT_LOOKBACK_FIELDS},
        **{field: (1, 168) for field in SENTIMENT_FORECAST_HORIZON_FIELDS},
    }
    for field, (minimum, maximum) in limits.items():
        if field not in (data or {}):
            continue
        raw_value = data.get(field)
        try:
            if isinstance(raw_value, bool) or float(raw_value) != int(float(raw_value)):
                raise ValueError
            value = int(float(raw_value))
        except (TypeError, ValueError):
            errors[field] = f'Enter a whole number from {minimum} through {maximum}.'
            continue
        if not minimum <= value <= maximum:
            errors[field] = f'Enter a whole number from {minimum} through {maximum}.'
            continue
        values[field] = value
    return values, errors


def validate_sentiment_threshold_payload(data, require_all=False):
    """Validate threshold values and return ({field: float}, {field: error})."""
    data = data or {}
    fields = SENTIMENT_THRESHOLD_FIELDS if require_all else tuple(
        field for field in SENTIMENT_THRESHOLD_FIELDS if field in data
    )
    values = {}
    errors = {}
    for field in fields:
        raw_value = data.get(field)
        if raw_value is None or isinstance(raw_value, bool) or str(raw_value).strip() == '':
            errors[field] = 'A value is required.'
            continue
        try:
            value = Decimal(str(raw_value).strip())
        except (InvalidOperation, ValueError):
            errors[field] = 'Enter a non-negative number with no more than two decimal places.'
            continue
        minimum = Decimal('0.01') if field in CORRECT_THRESHOLD_FIELDS else Decimal('0.00')
        if not value.is_finite() or value < minimum:
            errors[field] = f'Enter a value of at least {minimum:.2f}%.'
            continue
        if value.as_tuple().exponent < -2:
            errors[field] = 'Use no more than two decimal places.'
            continue
        values[field] = float(value)

    steady_field = HOLD_VARIABLE['steady_field']
    hold_wrong_field = HOLD_VARIABLE['wrong_field']
    if steady_field in values and hold_wrong_field in values:
        if values[hold_wrong_field] <= values[steady_field]:
            errors[hold_wrong_field] = 'Hold Wrong Threshold must be greater than the Hold Steady Range.'
    return values, errors


def get_sentiment_thresholds(settings=None):
    """Return four directional rule sets plus the special Hold rule."""
    result = {}
    for key, definition in DIRECTIONAL_SENTIMENT_VARIABLES.items():
        correct = getattr(settings, definition['correct_field'], DEFAULT_SENTIMENT_THRESHOLD_PCT) if settings else DEFAULT_SENTIMENT_THRESHOLD_PCT
        wrong = getattr(settings, definition['wrong_field'], DEFAULT_SENTIMENT_THRESHOLD_PCT) if settings else DEFAULT_SENTIMENT_THRESHOLD_PCT
        try:
            correct = float(correct)
            wrong = float(wrong)
        except (TypeError, ValueError):
            correct = wrong = DEFAULT_SENTIMENT_THRESHOLD_PCT
        if correct < 0.01:
            correct = DEFAULT_SENTIMENT_THRESHOLD_PCT
        if wrong < 0:
            wrong = DEFAULT_SENTIMENT_THRESHOLD_PCT
        result[key] = {
            **definition,
            'correct_pct': correct,
            'wrong_pct': wrong,
        }
    steady = getattr(settings, HOLD_VARIABLE['steady_field'], DEFAULT_HOLD_STEADY_PCT) if settings else DEFAULT_HOLD_STEADY_PCT
    try:
        steady = float(steady)
    except (TypeError, ValueError):
        steady = DEFAULT_HOLD_STEADY_PCT
    if steady < 0:
        steady = DEFAULT_HOLD_STEADY_PCT
    hold_wrong = getattr(settings, HOLD_VARIABLE['wrong_field'], DEFAULT_SENTIMENT_THRESHOLD_PCT) if settings else DEFAULT_SENTIMENT_THRESHOLD_PCT
    try:
        hold_wrong = float(hold_wrong)
    except (TypeError, ValueError):
        hold_wrong = DEFAULT_SENTIMENT_THRESHOLD_PCT
    if hold_wrong <= steady:
        hold_wrong = DEFAULT_SENTIMENT_THRESHOLD_PCT if DEFAULT_SENTIMENT_THRESHOLD_PCT > steady else steady + 0.01
    result['hold'] = {
        **HOLD_VARIABLE,
        'steady_pct': steady,
        'wrong_pct': hold_wrong,
        'upside_wrong_pct': hold_wrong,
        'downside_wrong_pct': hold_wrong,
    }
    return result


def _resolve_signal(sentiment):
    label = (sentiment or '').strip().lower()
    return _SIGNAL_ALIASES.get(label)


def evaluate_sentiment_outcome(sentiment, source_type, entry_price, evaluation_price,
                               correct_threshold_pct=DEFAULT_SENTIMENT_THRESHOLD_PCT,
                               wrong_threshold_pct=DEFAULT_SENTIMENT_THRESHOLD_PCT,
                               hold_steady_pct=DEFAULT_HOLD_STEADY_PCT,
                               hold_wrong_pct=DEFAULT_SENTIMENT_THRESHOLD_PCT):
    """Grade a signal using its entry price and designated evaluation price.

    Directional rules use independent Correct and Wrong boundaries. Hold uses a
    symmetric steady and Wrong bands around zero, with Neutral between them.
    """
    del source_type  # Retained in the public signature for backwards compatibility.
    try:
        entry_value = Decimal(str(entry_price))
        evaluated_value = Decimal(str(evaluation_price))
        correct_threshold_value = Decimal(str(correct_threshold_pct))
        wrong_threshold_value = Decimal(str(wrong_threshold_pct))
        steady_threshold_value = Decimal(str(hold_steady_pct))
        hold_wrong_threshold_value = Decimal(str(hold_wrong_pct))
        decimal_values = (
            entry_value, evaluated_value, correct_threshold_value,
            wrong_threshold_value, steady_threshold_value, hold_wrong_threshold_value,
        )
        if not all(value.is_finite() for value in decimal_values):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        return {'status': 'unscored', 'delta_pct': None, 'direction': None,
                'reason': 'The signal price, next-check price, or threshold is invalid.'}

    if entry_value <= 0 or evaluated_value <= 0:
        return {'status': 'unscored', 'delta_pct': None, 'direction': None,
                'reason': 'The signal price or next-check price is unavailable.'}
    setting_key = _resolve_signal(sentiment)
    if not setting_key:
        return {'status': 'unscored', 'delta_pct': None, 'direction': None,
                'reason': 'This recommendation has no defined outcome rule.'}

    definition = SENTIMENT_VARIABLES[setting_key]
    direction = definition['direction']
    delta_value = ((evaluated_value - entry_value) / entry_value) * Decimal('100')
    delta = float(delta_value)
    rounded = round(delta, 2)
    correct_threshold = float(correct_threshold_value)
    wrong_threshold = float(wrong_threshold_value)
    steady_threshold = float(steady_threshold_value)
    hold_wrong_threshold = float(hold_wrong_threshold_value)

    if direction == 'steady':
        if steady_threshold_value < 0:
            return {'status': 'unscored', 'delta_pct': None, 'direction': direction,
                    'reason': 'Hold steady range cannot be negative.'}
        if hold_wrong_threshold_value <= steady_threshold_value:
            return {'status': 'unscored', 'delta_pct': None, 'direction': direction,
                    'reason': 'Hold Wrong Threshold must be greater than the Hold Steady Range.'}
        if abs(delta_value) <= steady_threshold_value:
            status = 'correct'
        elif abs(delta_value) >= hold_wrong_threshold_value:
            status = 'wrong'
        else:
            status = 'neutral'
        boundary_text = (
            f'Correct requires a move from -{steady_threshold:.2f}% through +{steady_threshold:.2f}%. '
            f'Wrong requires a move of ±{hold_wrong_threshold:.2f}% or farther. '
            f'Moves strictly between the steady and Wrong boundaries are Neutral.'
        )
        return {
            'status': status,
            'delta_pct': delta,
            'direction': direction,
            'setting_key': setting_key,
            'steady_threshold_pct': steady_threshold,
            'wrong_threshold_pct': hold_wrong_threshold,
            'upside_wrong_threshold_pct': hold_wrong_threshold,
            'downside_wrong_threshold_pct': hold_wrong_threshold,
            'reason': (
                f'From this sentiment check to its evaluation point, price moved {rounded:+.2f}%. '
                f'{boundary_text} This outcome is {status.title()}.'
            ),
        }

    if correct_threshold_value < Decimal('0.01') or wrong_threshold_value < 0:
        return {'status': 'unscored', 'delta_pct': None, 'direction': direction,
                'reason': 'Correct must be at least 0.01%; Wrong cannot be negative.'}

    if direction == 'up':
        correct_boundary_value = correct_threshold_value
        wrong_boundary_value = -wrong_threshold_value
        correct_boundary = float(correct_boundary_value)
        wrong_boundary = float(wrong_boundary_value)
        if delta_value >= correct_boundary_value:
            status = 'correct'
        elif delta_value <= wrong_boundary_value:
            status = 'wrong'
        else:
            status = 'neutral'
        boundary_text = (
            f'Correct requires at least +{correct_threshold:.2f}%; '
            f'Wrong requires {wrong_boundary:.2f}% or lower.'
        )
    else:
        correct_boundary_value = -correct_threshold_value
        wrong_boundary_value = wrong_threshold_value
        correct_boundary = float(correct_boundary_value)
        wrong_boundary = float(wrong_boundary_value)
        if delta_value <= correct_boundary_value:
            status = 'correct'
        elif delta_value >= wrong_boundary_value:
            status = 'wrong'
        else:
            status = 'neutral'
        boundary_text = (
            f'Correct requires {correct_boundary:.2f}% or lower; '
            f'Wrong requires at least +{wrong_threshold:.2f}%.'
        )

    return {
        'status': status,
        'delta_pct': delta,
        'direction': direction,
        'setting_key': setting_key,
        'correct_threshold_pct': correct_threshold,
        'wrong_threshold_pct': wrong_threshold,
        'neutral_lower_pct': min(correct_boundary, wrong_boundary),
        'neutral_upper_pct': max(correct_boundary, wrong_boundary),
        'reason': (
            f'From this sentiment check to its evaluation point, price moved {rounded:+.2f}%. '
            f'{boundary_text} This outcome is {status.title()}.'
        ),
    }


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=dt_timezone.utc) if value.tzinfo is None else value.astimezone(dt_timezone.utc)


def pair_next_sentiment_checks(records):
    """Map each check id to the next check for the same symbol and source."""
    next_record_by_id = {}
    previous_by_group = {}
    for record in records:
        group = ((record.symbol or '').upper(), (record.source_type or 'portfolio').lower())
        previous = previous_by_group.get(group)
        if previous is not None:
            next_record_by_id[previous.id] = record
        previous_by_group[group] = record
    return next_record_by_id


def serialize_grading_config(thresholds):
    """Create a stable JSON snapshot so future settings changes do not rewrite a forecast."""
    return json.dumps(thresholds, sort_keys=True, separators=(',', ':'))


def format_forecast_rules(thresholds, is_watchlist=False):
    """Describe the exact labels and deterministic grading rules to the model."""
    labels = (
        [('Definitely Buy', 'buy_immediately'), ('Consider Buying', 'consider_buying'),
         ('Watch', 'consider_selling'), ('Avoid', 'sell_immediately')]
        if is_watchlist else
        [('Buy Immediately', 'buy_immediately'), ('Consider Buying', 'consider_buying'),
         ('Hold', 'hold'), ('Consider Selling', 'consider_selling'),
         ('Sell Immediately', 'sell_immediately')]
    )
    lines = []
    for label, key in labels:
        rule = thresholds[key]
        if key == 'hold':
            lines.append(
                f'- {label}: correct when the move stays within ±{rule["steady_pct"]:.2f}%; '
                f'wrong at ±{rule["wrong_pct"]:.2f}% or farther; otherwise neutral.'
            )
        elif rule['direction'] == 'up':
            lines.append(
                f'- {label}: correct at +{rule["correct_pct"]:.2f}% or higher; '
                f'wrong at -{rule["wrong_pct"]:.2f}% or lower; otherwise neutral.'
            )
        else:
            lines.append(
                f'- {label}: correct at -{rule["correct_pct"]:.2f}% or lower; '
                f'wrong at +{rule["wrong_pct"]:.2f}% or higher; otherwise neutral.'
            )
    return '\n'.join(lines)


def _grading_config_for_record(record, fallback_thresholds):
    if getattr(record, 'grading_config', None):
        try:
            parsed = json.loads(record.grading_config)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            pass
    return fallback_thresholds


def _grade_record(record, evaluation_price, thresholds):
    setting_key = _resolve_signal(record.sentiment)
    threshold = thresholds.get(setting_key) if setting_key else None
    if not threshold:
        return ({'status': 'unscored', 'delta_pct': None, 'direction': None,
                 'reason': 'This recommendation has no configured outcome rule.'}, None)
    if setting_key == 'hold':
        grade = evaluate_sentiment_outcome(
            record.sentiment, record.source_type, record.price_at_prediction, evaluation_price,
            hold_steady_pct=threshold['steady_pct'], hold_wrong_pct=threshold['wrong_pct'],
        )
    else:
        grade = evaluate_sentiment_outcome(
            record.sentiment, record.source_type, record.price_at_prediction, evaluation_price,
            threshold['correct_pct'], threshold['wrong_pct'],
        )
    return grade, threshold


def _resolve_fixed_horizon_price(record, target_at, now_utc):
    """Resolve the closest recorded price; use live price only near the target."""
    import time
    from models import PriceHistory

    target_timestamp = int(_as_utc(target_at).timestamp())
    tolerance_seconds = 15 * 60
    lower = target_timestamp - tolerance_seconds
    upper = target_timestamp + tolerance_seconds
    rows = PriceHistory.query.filter(
        PriceHistory.symbol == (record.symbol or '').upper(),
        PriceHistory.timestamp >= lower,
        PriceHistory.timestamp <= upper,
    ).all()
    closest = min(rows, key=lambda row: abs(int(row.timestamp) - target_timestamp), default=None)
    if closest and float(closest.price or 0) > 0:
        evaluated_at = datetime.fromtimestamp(int(closest.timestamp), tz=dt_timezone.utc)
        return float(closest.price), evaluated_at

    if abs((_as_utc(now_utc) - _as_utc(target_at)).total_seconds()) <= tolerance_seconds:
        try:
            from routes.helpers import fetch_crypto_price
            price = float(fetch_crypto_price(record.symbol) or 0)
            if price > 0:
                return price, datetime.fromtimestamp(int(time.time()), tz=dt_timezone.utc)
        except Exception:
            pass
    return None, None


def evaluate_pending_fixed_horizon_sentiments(now=None, price_resolver=None):
    """Persist due fixed-horizon outcomes without depending on another AI run."""
    from core.extensions import db
    from credentials import UserSetting
    from models import SentimentHistory

    now_utc = _as_utc(now or datetime.now(dt_timezone.utc))
    due = SentimentHistory.query.filter(
        SentimentHistory.evaluation_method == 'fixed_horizon',
        SentimentHistory.target_evaluation_at.isnot(None),
        SentimentHistory.target_evaluation_at <= now_utc.replace(tzinfo=None),
        SentimentHistory.outcome_evaluated_at.is_(None),
    ).order_by(SentimentHistory.target_evaluation_at.asc()).all()
    settings_cache = {}
    evaluated = 0
    for record in due:
        resolver = price_resolver or _resolve_fixed_horizon_price
        resolved = resolver(record, _as_utc(record.target_evaluation_at), now_utc)
        if isinstance(resolved, tuple):
            evaluation_price, evaluated_at = resolved
        else:
            evaluation_price, evaluated_at = resolved, record.target_evaluation_at
        if not evaluation_price or float(evaluation_price) <= 0:
            continue
        if record.user_id not in settings_cache:
            settings = UserSetting.query.filter_by(user_id=record.user_id).first()
            settings_cache[record.user_id] = get_sentiment_thresholds(settings)
        thresholds = _grading_config_for_record(record, settings_cache[record.user_id])
        grade, _ = _grade_record(record, float(evaluation_price), thresholds)
        record.outcome_price = float(evaluation_price)
        record.outcome_pct = grade.get('delta_pct')
        record.outcome_status = grade.get('status') or 'unscored'
        record.outcome_evaluated_at = (_as_utc(evaluated_at) or now_utc).replace(tzinfo=None)
        evaluated += 1
    if evaluated:
        db.session.commit()
    return evaluated


def build_sentiment_accuracy_response(user_id, timeframe='30d', selected_tier=None):
    """Build an accuracy report without mutating signal history."""
    from credentials import UserSetting
    from models import Coin, SentimentHistory, WatchlistCoin

    stablecoins = {'USDT', 'USDC', 'USD', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD', 'USDP'}
    days = {
        '1d': 1, '3d': 3, '5d': 5, '7d': 7, '14d': 14, '30d': 30,
        '90d': 90, '180d': 180, '365d': 365, '730d': 730,
    }
    timeframe = (timeframe or '30d').lower()

    # Pair before applying UI filters so a displayed check can still use the
    # immediately following check even when that check falls outside the view.
    all_records = SentimentHistory.query.filter_by(user_id=user_id).filter(
        ~SentimentHistory.symbol.in_(list(stablecoins))
    ).order_by(SentimentHistory.created_at.asc(), SentimentHistory.id.asc()).all()

    cutoff = datetime.now(dt_timezone.utc) - timedelta(days=days[timeframe]) if timeframe in days else None
    records = [record for record in all_records if (
        (not cutoff or (record.created_at and _as_utc(record.created_at) >= cutoff))
        and (not selected_tier or selected_tier == 'all' or (record.tier or '').lower() == selected_tier.lower())
    )]

    next_record_by_id = pair_next_sentiment_checks(all_records)

    settings = UserSetting.query.filter_by(user_id=user_id).first()
    configured_thresholds = get_sentiment_thresholds(settings)

    history = []
    rec_stats = {}
    model_stats = {}
    counts = {'correct': 0, 'wrong': 0, 'neutral': 0, 'tracking': 0, 'unscored': 0}
    directional = {'bullish': {'correct': 0, 'wrong': 0}, 'bearish': {'correct': 0, 'wrong': 0}}
    distribution = {'buy': 0, 'sell': 0, 'watch': 0}

    for record in records:
        symbol = (record.symbol or '').upper()
        source = (record.source_type or 'portfolio').lower()
        sentiment = (record.sentiment or '').strip()
        label = sentiment.lower()
        setting_key = _resolve_signal(sentiment)
        is_fixed_horizon = (getattr(record, 'evaluation_method', None) == 'fixed_horizon')
        record_thresholds = _grading_config_for_record(record, configured_thresholds)
        threshold = record_thresholds.get(setting_key) if setting_key else None
        next_record = next_record_by_id.get(record.id)
        status = 'tracking'
        delta = None
        evaluation_price = None
        evaluated_at = None
        elapsed_hours = None
        reason = 'Waiting for the fixed forecast horizon.' if is_fixed_horizon else 'Waiting for the next sentiment check for this coin.'
        direction = threshold['direction'] if threshold else None
        neutral_lower = None
        neutral_upper = None

        if is_fixed_horizon and record.outcome_evaluated_at is not None:
            evaluation_price = float(record.outcome_price or 0)
            evaluated_at = record.outcome_evaluated_at
            created_utc = _as_utc(record.created_at)
            evaluated_utc = _as_utc(evaluated_at)
            if created_utc and evaluated_utc:
                elapsed_hours = round((evaluated_utc - created_utc).total_seconds() / 3600, 2)
            grade, threshold = _grade_record(record, evaluation_price, record_thresholds)
            status = record.outcome_status or grade['status']
            delta = record.outcome_pct if record.outcome_pct is not None else grade['delta_pct']
            reason = grade['reason']
            direction = grade.get('direction')
            neutral_lower = grade.get('neutral_lower_pct')
            neutral_upper = grade.get('neutral_upper_pct')
        elif not is_fixed_horizon and next_record is not None:
            evaluation_price = float(next_record.price_at_prediction or 0)
            evaluated_at = next_record.created_at
            created_utc = _as_utc(record.created_at)
            evaluated_utc = _as_utc(evaluated_at)
            if created_utc and evaluated_utc:
                elapsed_hours = round((evaluated_utc - created_utc).total_seconds() / 3600, 2)
            if threshold:
                grade, threshold = _grade_record(record, evaluation_price, record_thresholds)
                status = grade['status']
                delta = grade['delta_pct']
                reason = grade['reason']
                direction = grade['direction']
                neutral_lower = grade.get('neutral_lower_pct')
                neutral_upper = grade.get('neutral_upper_pct')
            else:
                status = 'unscored'
                reason = 'This recommendation has no configured outcome rule.'

        if is_fixed_horizon:
            counts[status] += 1
        if label in BULLISH_SIGNALS:
            if is_fixed_horizon:
                distribution['buy'] += 1
            bucket = 'bullish'
        elif label in BEARISH_SIGNALS:
            if is_fixed_horizon:
                distribution['sell'] += 1
            bucket = 'bearish'
        else:
            if is_fixed_horizon:
                distribution['watch'] += 1
            bucket = None
        if is_fixed_horizon and bucket and status in ('correct', 'wrong'):
            directional[bucket][status] += 1

        if is_fixed_horizon:
            rec = rec_stats.setdefault(sentiment.title() or 'Unknown', {
                'sentiment': sentiment.title() or 'Unknown', 'total': 0, 'correct': 0,
                'wrong': 0, 'neutral': 0, 'tracking': 0, 'unscored': 0
            })
            rec['total'] += 1
            rec[status] += 1
            model_key = record.model or 'Unknown Model'
            model = model_stats.setdefault(model_key, {
                'model': model_key, 'provider': record.provider or 'AI',
                'tier': record.tier or 'primary', 'total': 0, 'correct': 0,
                'wrong': 0, 'neutral': 0, 'tracking': 0, 'unscored': 0
            })
            model['total'] += 1
            model[status] += 1

        def display_parts(value):
            if not value:
                return '', ''
            aware = _as_utc(value).astimezone(__import__('pytz').timezone('US/Eastern'))
            return f'{aware.month:02d}/{aware.day:02d}/{str(aware.year)[-2:]}', aware.strftime('%I:%M %p').lstrip('0')

        created_utc = _as_utc(record.created_at)
        evaluated_utc = _as_utc(evaluated_at)
        date_str, time_str = display_parts(record.created_at)
        eval_date, eval_time = display_parts(evaluated_at)
        history.append({
            'id': record.id, 'symbol': symbol, 'source_type': source,
            'sentiment': sentiment, 'sentiment_reason': record.sentiment_reason,
            'price_at_prediction': float(record.price_at_prediction or 0),
            'evaluation_price': evaluation_price, 'outcome_pct': delta,
            'price_delta_pct': delta, 'outcome_status': status,
            'outcome_reason': reason, 'evaluation_hours': elapsed_hours,
            'evaluation_method': ('fixed_horizon' if is_fixed_horizon else ('next_sentiment_check' if evaluated_at else 'legacy_next_check')),
            'forecast_horizon_hours': record.forecast_horizon_hours if is_fixed_horizon else None,
            'target_evaluation_at': record.target_evaluation_at.isoformat() if is_fixed_horizon and record.target_evaluation_at else None,
            'correct_threshold_pct': threshold.get('correct_pct') if threshold else None,
            'wrong_threshold_pct': threshold.get('wrong_pct') if threshold else None,
            'steady_threshold_pct': threshold.get('steady_pct') if threshold else None,
            'upside_wrong_threshold_pct': threshold.get('upside_wrong_pct') if threshold else None,
            'downside_wrong_threshold_pct': threshold.get('downside_wrong_pct') if threshold else None,
            'neutral_lower_pct': neutral_lower, 'neutral_upper_pct': neutral_upper,
            'threshold_setting': threshold['label'] if threshold else None,
            'provider': record.provider, 'model': record.model, 'tier': record.tier,
            'search_status': record.sentiment_search_status, 'date': date_str, 'time': time_str,
            'eval_date': eval_date, 'eval_time': eval_time,
            'formatted_datetime': f'{date_str} at {time_str}' if date_str else '',
            'created_at': record.created_at.isoformat() if record.created_at else None,
            'evaluated_at': evaluated_at.isoformat() if evaluated_at else None,
            'created_timestamp': int(created_utc.timestamp()) if created_utc else 0,
            'evaluated_timestamp': int(evaluated_utc.timestamp()) if evaluated_utc else None,
            'is_latest': status == 'tracking',
        })

    def finalize(values):
        result = []
        for value in values:
            decisive = value['correct'] + value['wrong']
            value['evaluated'] = decisive
            value['win_rate'] = round(value['correct'] * 100 / decisive, 1) if decisive else None
            result.append(value)
        return result

    rec_breakdown = sorted(finalize(rec_stats.values()), key=lambda row: row['total'], reverse=True)
    model_breakdown = sorted(finalize(model_stats.values()), key=lambda row: (row['win_rate'] is not None, row['win_rate'] or 0), reverse=True)
    decisive = counts['correct'] + counts['wrong']
    bullish_decisive = sum(directional['bullish'].values())
    bearish_decisive = sum(directional['bearish'].values())
    total = sum(counts.values())

    portfolio_symbols = Coin.query.filter_by(user_id=user_id).with_entities(Coin.symbol).all()
    watchlist_symbols = WatchlistCoin.query.filter_by(user_id=user_id).with_entities(WatchlistCoin.symbol).all()
    available = sorted({s.upper() for (s,) in portfolio_symbols + watchlist_symbols if s and s.upper() not in stablecoins})
    top_model = next((f"{m['provider'].capitalize()} ({m['model']})" for m in model_breakdown if m['evaluated'] >= 3), 'Not enough validated data')

    return {
        'success': True, 'timeframe': timeframe,
        'summary': {
            'overall_accuracy': round(counts['correct'] * 100 / decisive, 1) if decisive else None,
            'bullish_win_rate': round(directional['bullish']['correct'] * 100 / bullish_decisive, 1) if bullish_decisive else None,
            'bearish_win_rate': round(directional['bearish']['correct'] * 100 / bearish_decisive, 1) if bearish_decisive else None,
            'total_signals': total, 'evaluated_signals': decisive,
            'correct_count': counts['correct'], 'wrong_count': counts['wrong'],
            'bullish_count': bullish_decisive, 'bearish_count': bearish_decisive,
            'bullish_correct_count': directional['bullish']['correct'],
            'bullish_wrong_count': directional['bullish']['wrong'],
            'bearish_correct_count': directional['bearish']['correct'],
            'bearish_wrong_count': directional['bearish']['wrong'],
            'neutral_count': counts['neutral'], 'tracking_count': counts['tracking'],
            'unscored_count': counts['unscored'], 'top_model': top_model,
            'evaluation_method': 'fixed_horizon',
            'sentiment_thresholds': configured_thresholds,
        },
        'recommendation_breakdown': rec_breakdown,
        'model_breakdown': model_breakdown,
        'signal_distribution': {
            'buy_count': distribution['buy'], 'sell_count': distribution['sell'],
            'watch_count': distribution['watch'],
            'buy_pct': round(distribution['buy'] * 100 / total, 1) if total else 0,
            'sell_pct': round(distribution['sell'] * 100 / total, 1) if total else 0,
            'watch_pct': round(distribution['watch'] * 100 / total, 1) if total else 0,
        },
        'available_symbols': available,
        'history': sorted(history, key=lambda row: row['created_timestamp'], reverse=True),
    }
