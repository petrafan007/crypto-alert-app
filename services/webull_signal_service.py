"""Read-only Webull signal generation and scheduled evaluation."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.extensions import db
from credentials import Credential, User, UserSetting
from models import ExternalSentimentSignal, WebullHolding
from services.ai_service import call_ai_with_web_search, parse_sentiment_json
from services.analysis_service import is_ai_enabled
from services.external_signal_service import create_external_signal, grade_external_signal
from services.sentiment_outcome_service import format_forecast_rules, get_sentiment_thresholds
from services.webull_analysis_service import build_webull_market_snapshot
from services.webull_service import WebullConnectionError, get_webull_market_bars, normalize_webull_environment

SUPPORTED_WEBULL_SIGNAL_TYPES = {'CRYPTO', 'STOCK', 'EQUITY', 'ETF'}


def _equity_market_is_open(now=None):
    """Avoid grading or scheduling US equities against a stale closing price."""
    eastern = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    if eastern.weekday() >= 5:
        return False
    current_minutes = eastern.hour * 60 + eastern.minute
    return 9 * 60 + 30 <= current_minutes <= 16 * 60


def _settings_value(settings, instrument_type, suffix, default=24):
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
    if not credential or credential.webull_token_status != 'NORMAL' or credential.webull_token_environment != environment or not credential.webull_access_token:
        raise WebullConnectionError('Verify your Webull connection before running Webull AI analysis.')
    return credential, settings, environment


def _latest_market_price(credential, environment, holding):
    bars = get_webull_market_bars(
        credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
        symbol=holding.symbol, instrument_type=holding.instrument_type, interval='M1', limit=2,
    )
    if not bars or not bars[-1].get('close'):
        return None, None
    return float(bars[-1]['close']), bars[-1].get('time')


def create_webull_signal(user, holding, *, origin='manual'):
    """Create one stored read-only forecast for a supported imported holding."""
    instrument_type = str(holding.instrument_type or '').upper()
    if instrument_type not in SUPPORTED_WEBULL_SIGNAL_TYPES:
        raise ValueError('Webull option analysis is unavailable until contract-level options market data is mapped.')
    if instrument_type != 'CRYPTO' and not _equity_market_is_open():
        raise ValueError('Webull equity and ETF signals are available during regular U.S. market hours so they are not anchored to a stale closing price.')
    if not is_ai_enabled(user.username):
        raise ValueError('Enable an AI integration in Settings before generating Webull analysis.')

    credential, settings, environment = _credentials_for_user(user.id)
    bars = get_webull_market_bars(
        credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
        symbol=holding.symbol, instrument_type=instrument_type, interval='D', limit=30,
    )
    market = build_webull_market_snapshot(bars, holding.currency or 'USD')
    entry_price = market.get('last_price') or holding.last_price
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


def run_scheduled_webull_signals():
    """Run enabled per-asset scheduled signals. Disabled by default to avoid surprise AI use."""
    created = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for user in User.query.all():
        settings = UserSetting.query.filter_by(user_id=user.id).first()
        if not settings or not settings.webull_ai_scheduling_enabled or not is_ai_enabled(user.username):
            continue
        holdings = WebullHolding.query.filter(WebullHolding.user_id == user.id).all()
        for holding in holdings:
            instrument_type = str(holding.instrument_type or '').upper()
            if instrument_type not in SUPPORTED_WEBULL_SIGNAL_TYPES:
                continue
            if instrument_type != 'CRYPTO' and not _equity_market_is_open():
                continue
            frequency = _settings_value(settings, instrument_type, 'frequency_hours')
            last = ExternalSentimentSignal.query.filter_by(
                user_id=user.id, provider='webull', symbol=holding.symbol, instrument_type=instrument_type,
            ).order_by(ExternalSentimentSignal.created_at.desc()).first()
            if last and (now - last.created_at).total_seconds() < frequency * 3600:
                continue
            try:
                create_webull_signal(user, holding, origin='scheduled')
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
