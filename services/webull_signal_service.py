"""Read-only Webull signal generation and scheduled evaluation."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from core.extensions import db
from credentials import Credential, User, UserSetting
from models import ExternalSentimentSignal, WebullHolding
from services.ai_service import call_ai_with_web_search, parse_sentiment_json, is_user_analysis_window_active
from services.analysis_service import is_ai_enabled
from services.external_signal_service import create_external_signal, grade_external_signal
from services.sentiment_outcome_service import format_forecast_rules, get_sentiment_thresholds
from services.webull_analysis_service import build_webull_market_snapshot
from services.webull_service import (
    WebullConnectionError,
    get_webull_market_bars,
    get_webull_market_snapshot,
    get_webull_option_snapshot,
    normalize_webull_environment,
)

SUPPORTED_WEBULL_SIGNAL_TYPES = {'CRYPTO', 'STOCK', 'EQUITY', 'ETF', 'OPTION'}


def _equity_market_is_open(now=None):
    """Avoid grading or scheduling US equities against a stale closing price."""
    eastern = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    if eastern.weekday() >= 5:
        return False
    current_minutes = eastern.hour * 60 + eastern.minute
    return 9 * 60 + 30 <= current_minutes <= 16 * 60


def _settings_value(settings, instrument_type, suffix, default=24):
    if suffix == 'frequency_hours':
        val = getattr(settings, 'sentiment_analysis_frequency_hours', None)
        if val is not None:
            try:
                return max(1, int(val))
            except (TypeError, ValueError):
                pass
    elif suffix == 'horizon_hours':
        val = getattr(settings, 'forecast_horizon_hours', None)
        if val is not None:
            try:
                return max(1, int(val))
            except (TypeError, ValueError):
                pass
    family = 'crypto' if instrument_type == 'CRYPTO' else 'equity'
    value = getattr(settings, f'webull_{family}_sentiment_{suffix}', None)
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default


def _credentials_for_user(user_id):
    credential = Credential.query.filter_by(user_id=user_id).first()
    settings = UserSetting.query.filter_by(user_id=user_id).first()
    environment = normalize_webull_environment(getattr(settings, 'webull_environment', None) or 'production')
    if (
        not credential or credential.webull_token_status != 'NORMAL'
        or credential.webull_token_environment != environment or not credential.webull_access_token
    ):
        raise WebullConnectionError('Webull is not connected or token has expired.')
    return credential, settings, environment


def _latest_equity_bar(credential, environment, symbol):
    bars = get_webull_market_bars(
        credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
        symbol=symbol, instrument_type='EQUITY', interval='m5', limit=2,
    )
    if not bars or not bars[-1].get('close'):
        return None, None
    return float(bars[-1]['close']), bars[-1].get('time')


def create_webull_signal(user, holding, *, origin='manual'):
    """Create one stored read-only forecast for a supported imported holding."""
    instrument_type = str(holding.instrument_type or '').upper()
    if instrument_type not in SUPPORTED_WEBULL_SIGNAL_TYPES:
        raise ValueError('Webull option analysis is unavailable until contract-level options market data is mapped.')
    if instrument_type != 'CRYPTO' and origin != 'manual' and not _equity_market_is_open():
        raise ValueError('Webull equity and option signals are scheduled during regular U.S. market hours.')
    if not is_ai_enabled(user.username):
        raise ValueError('Enable an AI integration in Settings before generating Webull analysis.')

    credential, settings, environment = _credentials_for_user(user.id)
    if instrument_type == 'OPTION':
        snapshot = {}
        if holding.instrument_id:
            try:
                snapshot = get_webull_option_snapshot(
                    credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
                    symbol=holding.symbol, instrument_id=holding.instrument_id,
                )
            except Exception:
                snapshot = {}
        greeks_str = f"Option Contract: Strike=${holding.option_strike or 'N/A'}, Type={holding.option_type or 'CALL'}, Expiry={holding.option_expiration or 'N/A'}"
        if snapshot:
            greeks_str += f", Delta={snapshot.get('delta')}, Gamma={snapshot.get('gamma')}, Theta={snapshot.get('theta')}, IV={snapshot.get('implied_volatility')}"
        market = {
            'context': greeks_str,
            'last_price': holding.last_price or snapshot.get('last_price') or holding.cost_price or 1.0,
            'currency': holding.currency or 'USD',
        }
        entry_price = market['last_price']
    else:
        bars = get_webull_market_bars(
            credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
            symbol=holding.symbol, instrument_type=instrument_type, interval='D', limit=30,
        )
        snapshot = None
        try:
            snapshot = get_webull_market_snapshot(
                credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
                symbol=holding.symbol, instrument_type=instrument_type,
            )
        except Exception:
            snapshot = None

        market = build_webull_market_snapshot(bars, holding.currency or 'USD')
        entry_price = (
            (snapshot.get('price') or snapshot.get('regular_price')) if snapshot else None
        ) or market.get('last_price') or holding.last_price or holding.cost_price
        if not entry_price or float(entry_price) <= 0:
            raise WebullConnectionError('Webull did not return a usable current market price for this holding.')
    family = 'crypto' if instrument_type == 'CRYPTO' else 'equity'
    horizon = _settings_value(settings, instrument_type, 'horizon_hours')
    rules = format_forecast_rules(get_sentiment_thresholds(settings))
    request_text = (
        'WEBULL_STORED_SIGNAL_READ_ONLY\n'
        f'asset: {holding.symbol}\nasset_class: {instrument_type}\n'
        f'forecast_horizon_hours: {horizon}\n'
        f'quantity: {float(holding.quantity or 0):.8f}\n'
        f'average_entry: {holding.cost_price if holding.cost_price is not None else "unavailable"}\n'
        f'{market["context"]}\n\n'
        'Use these evaluation rules when choosing the recommendation:\n'
        f'{rules}\n\n'
        'Return the required JSON only. This application records a research signal and never sends an order to Webull.'
    )
    prompt_type = 'webull_crypto_analysis' if family == 'crypto' else 'webull_equity_analysis'
    response, _ = call_ai_with_web_search(
        username=user.username,
        messages=[{'role': 'user', 'content': request_text}],
        user_id=user.id,
        prompt_type=prompt_type,
        symbol=holding.symbol,
        amount=holding.quantity,
        search_lookback_hours=24,
        forecast_horizon_hours=horizon,
        use_cache=False,
    )
    content = response.choices[0].message.content if getattr(response, 'choices', None) else str(response)
    recommendation, reason = parse_sentiment_json(content, is_watchlist=False)
    signal = create_external_signal(
        user_id=user.id, provider='webull', account_id=holding.account_id,
        symbol=holding.symbol, instrument_type=instrument_type, prompt_family=family,
        recommendation=recommendation, reason=reason, market_context=market['context'],
        entry_price=entry_price, currency=holding.currency or 'USD', forecast_horizon_hours=horizon,
        origin=origin, ai_provider=getattr(response, 'provider', None),
        provider_model=getattr(response, 'model', None), ai_tier=getattr(response, 'tier', None),
        search_status=getattr(response, 'search_status', None),
    )
    return signal, market


def run_scheduled_webull_signals(force=False, symbol=None):
    """Run Webull signals using the same global sentiment settings and schedule as Binance."""
    created = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for user in User.query.all():
        if not is_ai_enabled(user.username):
            continue
        settings = UserSetting.query.filter_by(user_id=user.id).first()
        if not settings:
            continue

        if not force:
            start_str = getattr(settings, 'ai_analysis_window_start', '08:00')
            end_str = getattr(settings, 'ai_analysis_window_end', '23:59')
            if not is_user_analysis_window_active(start_str, end_str):
                continue

        holdings = WebullHolding.query.filter(WebullHolding.user_id == user.id).all()
        if symbol:
            clean_sym = symbol.upper().strip()
            holdings = [h for h in holdings if str(h.symbol or '').upper() == clean_sym]

        for holding in holdings:
            if holding.sentiment_tracking_enabled is False:
                continue
            instrument_type = str(holding.instrument_type or '').upper()
            if instrument_type not in SUPPORTED_WEBULL_SIGNAL_TYPES:
                continue
            if not force and instrument_type != 'CRYPTO' and not _equity_market_is_open():
                continue
            frequency = _settings_value(settings, instrument_type, 'frequency_hours')
            if not force:
                last = ExternalSentimentSignal.query.filter_by(
                    user_id=user.id, provider='webull', symbol=holding.symbol, instrument_type=instrument_type,
                ).order_by(ExternalSentimentSignal.created_at.desc()).first()
                if last and (now - last.created_at).total_seconds() < frequency * 3600:
                    continue
            try:
                create_webull_signal(user, holding, origin='scheduled' if not force else 'manual')
                created += 1
            except Exception:
                # A single unavailable instrument must not stop the others.
                db.session.rollback()
    return created


def evaluate_due_webull_signals():
    """Grade only due Webull signals, with current connector market data."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = ExternalSentimentSignal.query.filter(
        ExternalSentimentSignal.provider == 'webull',
        ExternalSentimentSignal.target_evaluation_at <= now,
        ExternalSentimentSignal.outcome_evaluated_at.is_(None),
    ).order_by(ExternalSentimentSignal.target_evaluation_at.asc()).all()
    evaluated = 0
    credentials = {}
    for signal in due:
        try:
            if signal.instrument_type != 'CRYPTO' and not _equity_market_is_open():
                continue
            if signal.user_id not in credentials:
                credentials[signal.user_id] = _credentials_for_user(signal.user_id)
            credential, _, environment = credentials[signal.user_id]
            holding = WebullHolding(
                symbol=signal.symbol, instrument_type=signal.instrument_type,
                currency=signal.currency, account_id=signal.account_id or '',
            )
            price, _ = _latest_market_price(credential, environment, holding)
            if price:
                grade_external_signal(signal, price, now)
                db.session.commit()
                evaluated += 1
        except Exception:
            # This signal did not grade. Any earlier completed grades have
            # already committed, so one bad connector response cannot erase
            # them or block another account/instrument.
            db.session.rollback()
    return evaluated


def build_webull_accuracy_response(user_id, timeframe='30d', selected_tier=None):
    """Build an empirical accuracy and ledger report for Webull AI signals."""
    from models import ExternalSentimentSignal, WebullHolding
    from services.sentiment_outcome_service import (
        BULLISH_SIGNALS, BEARISH_SIGNALS, _as_utc, get_sentiment_thresholds
    )
    import pytz

    # Grade any matured signals first
    try:
        evaluate_due_webull_signals()
    except Exception:
        db.session.rollback()

    days = {
        '1d': 1, '3d': 3, '5d': 5, '7d': 7, '14d': 14, '30d': 30,
        '90d': 90, '180d': 180, '365d': 365, '730d': 730,
    }
    timeframe = (timeframe or '30d').lower()

    query = ExternalSentimentSignal.query.filter_by(user_id=user_id, provider='webull')
    cutoff = datetime.now(timezone.utc) - timedelta(days=days[timeframe]) if timeframe in days else None
    if cutoff:
        query = query.filter(ExternalSentimentSignal.created_at >= cutoff.replace(tzinfo=None))
    if selected_tier and selected_tier != 'all':
        query = query.filter(ExternalSentimentSignal.ai_tier == selected_tier.lower())

    records = query.order_by(ExternalSentimentSignal.created_at.desc()).all()

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
        sentiment = (record.recommendation or '').strip()
        label = sentiment.lower()
        status = record.outcome_status or 'tracking'
        if status not in counts:
            status = 'unscored'
        counts[status] += 1

        if label in BULLISH_SIGNALS:
            distribution['buy'] += 1
            bucket = 'bullish'
        elif label in BEARISH_SIGNALS:
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

        model_key = record.provider_model or record.ai_provider or 'Unknown Model'
        model = model_stats.setdefault(model_key, {
            'model': model_key, 'provider': record.ai_provider or 'AI',
            'tier': record.ai_tier or 'primary', 'total': 0, 'correct': 0,
            'wrong': 0, 'neutral': 0, 'tracking': 0, 'unscored': 0
        })
        model['total'] += 1
        model[status] += 1

        def display_parts(val):
            if not val:
                return '', ''
            aware = _as_utc(val).astimezone(pytz.timezone('US/Eastern'))
            return f'{aware.month:02d}/{aware.day:02d}/{str(aware.year)[-2:]}', aware.strftime('%I:%M %p').lstrip('0')

        created_utc = _as_utc(record.created_at)
        evaluated_utc = _as_utc(record.outcome_evaluated_at)
        date_str, time_str = display_parts(record.created_at)
        eval_date, eval_time = display_parts(record.outcome_evaluated_at)

        delta = record.outcome_pct

        history.append({
            'id': record.id,
            'symbol': symbol,
            'source_type': 'webull',
            'instrument_type': record.instrument_type,
            'sentiment': sentiment,
            'sentiment_reason': record.reason,
            'market_context': record.market_context,
            'price_at_prediction': float(record.entry_price or 0),
            'evaluation_price': float(record.outcome_price) if record.outcome_price is not None else None,
            'outcome_pct': delta,
            'price_delta_pct': delta,
            'outcome_status': status,
            'outcome_reason': record.outcome_reason or ('Waiting for the fixed forecast horizon.' if status == 'tracking' else ''),
            'forecast_horizon_hours': record.forecast_horizon_hours,
            'target_evaluation_at': record.target_evaluation_at.isoformat() if record.target_evaluation_at else None,
            'provider': record.ai_provider,
            'model': record.provider_model,
            'tier': record.ai_tier,
            'search_status': record.search_status,
            'date': date_str,
            'time': time_str,
            'eval_date': eval_date,
            'eval_time': eval_time,
            'formatted_datetime': f'{date_str} at {time_str}' if date_str else '',
            'created_at': record.created_at.isoformat() if record.created_at else None,
            'evaluated_at': record.outcome_evaluated_at.isoformat() if record.outcome_evaluated_at else None,
            'created_timestamp': int(created_utc.timestamp()) if created_utc else 0,
            'evaluated_timestamp': int(evaluated_utc.timestamp()) if evaluated_utc else None,
            'is_latest': status == 'tracking',
        })

    def finalize(values):
        result = []
        for val in values:
            decisive = val['correct'] + val['wrong']
            val['evaluated'] = decisive
            val['win_rate'] = round(val['correct'] * 100 / decisive, 1) if decisive else None
            result.append(val)
        return result

    rec_breakdown = sorted(finalize(rec_stats.values()), key=lambda r: r['total'], reverse=True)
    model_breakdown = sorted(finalize(model_stats.values()), key=lambda r: (r['win_rate'] is not None, r['win_rate'] or 0), reverse=True)
    decisive = counts['correct'] + counts['wrong']
    bullish_decisive = sum(directional['bullish'].values())
    bearish_decisive = sum(directional['bearish'].values())
    total = sum(counts.values())

    holdings_symbols = WebullHolding.query.filter_by(user_id=user_id).with_entities(WebullHolding.symbol).all()
    signal_symbols = ExternalSentimentSignal.query.filter_by(user_id=user_id, provider='webull').with_entities(ExternalSentimentSignal.symbol).all()
    available = sorted({s.upper() for (s,) in holdings_symbols + signal_symbols if s and s.upper() not in {'USD', 'USDT'}})
    top_model = next((f"{m['provider'].capitalize()} ({m['model']})" for m in model_breakdown if m['evaluated'] >= 3), 'Not enough validated data')

    return {
        'success': True,
        'timeframe': timeframe,
        'summary': {
            'overall_accuracy': round(counts['correct'] * 100 / decisive, 1) if decisive else None,
            'bullish_win_rate': round(directional['bullish']['correct'] * 100 / bullish_decisive, 1) if bullish_decisive else None,
            'bearish_win_rate': round(directional['bearish']['correct'] * 100 / bearish_decisive, 1) if bearish_decisive else None,
            'total_signals': total,
            'evaluated_signals': decisive,
            'correct_count': counts['correct'],
            'wrong_count': counts['wrong'],
            'bullish_count': bullish_decisive,
            'bearish_count': bearish_decisive,
            'bullish_correct_count': directional['bullish']['correct'],
            'bullish_wrong_count': directional['bullish']['wrong'],
            'bearish_correct_count': directional['bearish']['correct'],
            'bearish_wrong_count': directional['bearish']['wrong'],
            'neutral_count': counts['neutral'],
            'tracking_count': counts['tracking'],
            'unscored_count': counts['unscored'],
            'top_model': top_model,
            'evaluation_method': 'fixed_horizon',
            'sentiment_thresholds': configured_thresholds,
        },
        'recommendation_breakdown': rec_breakdown,
        'model_breakdown': model_breakdown,
        'signal_distribution': {
            'buy_count': distribution['buy'],
            'sell_count': distribution['sell'],
            'watch_count': distribution['watch'],
            'buy_pct': round(distribution['buy'] * 100 / total, 1) if total else 0,
            'sell_pct': round(distribution['sell'] * 100 / total, 1) if total else 0,
            'watch_pct': round(distribution['watch'] * 100 / total, 1) if total else 0,
        },
        'history': history,
        'available_symbols': available,
    }
