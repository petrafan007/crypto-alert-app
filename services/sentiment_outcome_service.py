"""Deterministic grading and reporting for recorded AI sentiment signals."""

from bisect import bisect_left
from datetime import datetime, timedelta, timezone as dt_timezone

BULLISH_SIGNALS = {
    'definitely buy', 'consider buying', 'buy immediately', 'strong buy', 'buy'
}
BEARISH_SIGNALS = {
    'consider selling', 'sell immediately', 'avoid', 'strong sell', 'do not buy', 'sell'
}


def evaluate_sentiment_outcome(sentiment, source_type, entry_price, evaluation_price,
                               neutral_threshold_pct=5.0):
    """Grade one signal after its configured horizon.

    Moves inside the neutral band are inconclusive and excluded from win rates.
    Portfolio ``Hold`` participates like a bullish/hold-position thesis; watchlist
    ``Watch`` participates like a wait-for-a-better-entry thesis.
    """
    try:
        entry = float(entry_price)
        evaluated = float(evaluation_price)
        threshold = max(0.0, float(neutral_threshold_pct))
    except (TypeError, ValueError):
        return {'status': 'unscored', 'delta_pct': None, 'direction': None,
                'reason': 'The signal or evaluation price is invalid.'}

    if entry <= 0 or evaluated <= 0:
        return {'status': 'unscored', 'delta_pct': None, 'direction': None,
                'reason': 'The signal or evaluation price is unavailable.'}

    label = (sentiment or '').strip().lower()
    source = (source_type or '').strip().lower()
    if label in BULLISH_SIGNALS or (label == 'hold' and source == 'portfolio'):
        direction = 'up'
    elif label in BEARISH_SIGNALS or (label == 'watch' and source == 'watchlist'):
        direction = 'down'
    else:
        return {'status': 'unscored', 'delta_pct': None, 'direction': None,
                'reason': 'This recommendation has no defined outcome rule.'}

    delta = ((evaluated - entry) / entry) * 100.0
    rounded = round(delta, 2)
    if abs(delta) < threshold:
        return {
            'status': 'neutral', 'delta_pct': rounded, 'direction': direction,
            'reason': f'The {rounded:+.2f}% move stayed inside the ±{threshold:g}% neutral band.'
        }

    correct = (direction == 'up' and delta > 0) or (direction == 'down' and delta < 0)
    thesis = 'price increase' if direction == 'up' else 'price decrease'
    return {
        'status': 'correct' if correct else 'wrong',
        'delta_pct': rounded,
        'direction': direction,
        'reason': f'The signal expected a {thesis}; price moved {rounded:+.2f}% after the evaluation horizon.'
    }


def _nearest_price(points, target_timestamp, tolerance_seconds):
    if not points:
        return None
    timestamps = [point[0] for point in points]
    index = bisect_left(timestamps, target_timestamp)
    candidates = points[max(0, index - 1):index + 1]
    if not candidates:
        return None
    closest = min(candidates, key=lambda point: abs(point[0] - target_timestamp))
    return closest if abs(closest[0] - target_timestamp) <= tolerance_seconds else None


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=dt_timezone.utc) if value.tzinfo is None else value.astimezone(dt_timezone.utc)


def build_sentiment_accuracy_response(user_id, timeframe='3d', selected_tier=None):
    """Build an accuracy report without mutating signal history."""
    from credentials import UserSetting
    from models import Coin, PriceHistory, SentimentHistory, WatchlistCoin

    stablecoins = {'USDT', 'USDC', 'USD', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD', 'USDP'}
    days = {'1d': 1, '3d': 3, '5d': 5, '7d': 7, '14d': 14, '30d': 30, '90d': 90}
    timeframe = (timeframe or '3d').lower()
    query = SentimentHistory.query.filter_by(user_id=user_id).filter(
        ~SentimentHistory.symbol.in_(list(stablecoins))
    )
    if timeframe in days:
        query = query.filter(SentimentHistory.created_at >= datetime.utcnow() - timedelta(days=days[timeframe]))
    if selected_tier and selected_tier != 'all':
        query = query.filter(SentimentHistory.tier == selected_tier.lower())
    records = query.order_by(SentimentHistory.created_at.asc()).all()

    settings = UserSetting.query.filter_by(user_id=user_id).first()
    portfolio_hours = max(1, int(getattr(settings, 'sentiment_analysis_frequency_hours', 24) or 24))
    watchlist_hours = max(1, int(getattr(settings, 'watchlist_sentiment_analysis_frequency_hours', 24) or 24))
    threshold = max(0.0, float(getattr(settings, 'ai_outcome_neutral_threshold_pct', 5.0) or 5.0))
    now = datetime.now(dt_timezone.utc)

    price_points = {}
    if records:
        symbols = sorted({r.symbol.upper() for r in records if r.symbol})
        earliest = min(_as_utc(r.created_at) for r in records if r.created_at)
        latest_target = max(
            _as_utc(r.created_at) + timedelta(hours=watchlist_hours if (r.source_type or '').lower() == 'watchlist' else portfolio_hours)
            for r in records if r.created_at
        )
        price_rows = PriceHistory.query.filter(
            PriceHistory.symbol.in_(symbols),
            PriceHistory.timestamp >= int((earliest - timedelta(hours=2)).timestamp()),
            PriceHistory.timestamp <= int((latest_target + timedelta(hours=2)).timestamp()),
        ).order_by(PriceHistory.symbol, PriceHistory.timestamp).all()
        for point in price_rows:
            price_points.setdefault(point.symbol.upper(), []).append((int(point.timestamp), float(point.price)))

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
        horizon_hours = watchlist_hours if source == 'watchlist' else portfolio_hours
        created_utc = _as_utc(record.created_at)
        target = created_utc + timedelta(hours=horizon_hours) if created_utc else None
        status = 'tracking'
        delta = None
        evaluation_price = None
        evaluated_at = None
        reason = f'Waiting for the {horizon_hours}-hour evaluation horizon.'
        direction = None

        if target and target <= now:
            tolerance = min(7200, max(900, int(horizon_hours * 3600 * 0.25)))
            point = _nearest_price(price_points.get(symbol, []), int(target.timestamp()), tolerance)
            if point:
                evaluated_at = datetime.fromtimestamp(point[0], dt_timezone.utc)
                evaluation_price = point[1]
                grade = evaluate_sentiment_outcome(
                    sentiment, source, record.price_at_prediction, evaluation_price, threshold
                )
                status, delta, reason, direction = (
                    grade['status'], grade['delta_pct'], grade['reason'], grade['direction']
                )
            else:
                status = 'unscored'
                reason = 'No reliable market price was recorded near the evaluation horizon.'

        counts[status] += 1
        if label in BULLISH_SIGNALS or (label == 'hold' and source == 'portfolio'):
            distribution['buy'] += 1
            bucket = 'bullish'
        elif label in BEARISH_SIGNALS or (label == 'watch' and source == 'watchlist'):
            distribution['sell'] += 1
            bucket = 'bearish'
        else:
            distribution['watch'] += 1
            bucket = None
        if bucket and status in ('correct', 'wrong'):
            directional[bucket][status] += 1

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
            aware = _as_utc(value).astimezone(
                __import__('pytz').timezone('US/Eastern')
            )
            return f'{aware.month:02d}/{aware.day:02d}/{str(aware.year)[-2:]}', aware.strftime('%I:%M %p').lstrip('0')

        date_str, time_str = display_parts(record.created_at)
        eval_date, eval_time = display_parts(evaluated_at)
        history.append({
            'id': record.id, 'symbol': symbol, 'source_type': source,
            'sentiment': sentiment, 'sentiment_reason': record.sentiment_reason,
            'price_at_prediction': float(record.price_at_prediction or 0),
            'evaluation_price': evaluation_price, 'outcome_pct': delta,
            'price_delta_pct': delta, 'outcome_status': status,
            'outcome_reason': reason, 'evaluation_hours': horizon_hours,
            'evaluation_method': 'fixed_horizon_price_history' if evaluated_at else None,
            'provider': record.provider, 'model': record.model, 'tier': record.tier,
            'search_status': record.sentiment_search_status, 'date': date_str, 'time': time_str,
            'eval_date': eval_date, 'eval_time': eval_time,
            'formatted_datetime': f'{date_str} at {time_str}' if date_str else '',
            'created_at': record.created_at.isoformat() if record.created_at else None,
            'evaluated_at': evaluated_at.isoformat() if evaluated_at else None,
            'created_timestamp': int(created_utc.timestamp()) if created_utc else 0,
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
    total = len(records)

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
            'bullish_count': bullish_decisive, 'bearish_count': bearish_decisive,
            'neutral_count': counts['neutral'], 'tracking_count': counts['tracking'],
            'unscored_count': counts['unscored'], 'top_model': top_model,
            'neutral_threshold_pct': threshold,
            'portfolio_evaluation_hours': portfolio_hours,
            'watchlist_evaluation_hours': watchlist_hours,
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
